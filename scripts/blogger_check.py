"""Compare every mapped public Blogger post body with its local HTML source."""

import argparse
import difflib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BODY_CLASSES = {"post-body", "entry-content", "float-container"}


class PostBodyParser(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.lines = [0] + [i + 1 for i, char in enumerate(html) if char == "\n"]
        self.depth = 0
        self.start = None
        self.bodies = []

    def source_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        if self.depth:
            self.depth += 1
        elif BODY_CLASSES <= set((dict(attrs).get("class") or "").split()):
            self.start = self.source_offset() + len(self.get_starttag_text())
            self.depth = 1

    def handle_endtag(self, tag):
        if tag == "div" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.bodies.append(self.html[self.start:self.source_offset()])


def extract_post_body(html):
    parser = PostBodyParser(html)
    parser.feed(html)
    parser.close()
    if parser.depth:
        raise ValueError("Post-body div is not closed")
    if len(parser.bodies) != 1:
        raise ValueError(f"Expected one post-body.entry-content.float-container div; found {len(parser.bodies)}")
    return parser.bodies[0]


def normalize(html):
    return html.replace("\r\n", "\n").replace("\r", "\n")


def fetch_html(url):
    request = Request(url, headers={"User-Agent": "WebGenWFRP4Ed-HTML-Check/1.0"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8")
        except (HTTPError, URLError, TimeoutError) as error:
            if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))


def compare_entry(filename, entry, root, output):
    result = {"file": filename, "url": entry.get("url", ""), "status": "error"}
    try:
        source_path = (root / filename).resolve()
        if not source_path.is_relative_to(root.resolve()):
            raise ValueError("Source path is outside repository")
        if not result["url"].startswith("https://"):
            raise ValueError("Mapping must contain an HTTPS public URL")
        source = normalize(source_path.read_text(encoding="utf-8"))
        published = normalize(extract_post_body(fetch_html(result["url"])))
        if source == published:
            result["status"] = "match"
        else:
            result["status"] = "different"
            diff_path = output / (filename.replace("/", "__").replace("\\", "__") + ".diff")
            diff = "".join(difflib.unified_diff(
                published.splitlines(keepends=True), source.splitlines(keepends=True),
                fromfile="Blogger: " + result["url"], tofile="Source: " + filename,
            ))
            diff_path.write_text(diff, encoding="utf-8")
            result["diff"] = diff_path.name
    except (OSError, ValueError, UnicodeError) as error:
        result["message"] = str(error)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=ROOT / "blogger-map.json")
    parser.add_argument("--output", type=Path, default=ROOT / "blogger-check-results")
    args = parser.parse_args(argv)
    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("Mapping must be a nonempty object")
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for filename, entry in mapping.items():
        result = compare_entry(filename, entry, ROOT, args.output)
        results.append(result)
        print(f"{result['status'].upper()}: {filename} - {result.get('message', result['url'])}")
    (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    summary = ["## Blogger HTML comparison", "", "| Source | Result |", "| --- | --- |"]
    for result in results:
        detail = result.get("message", result["status"]).replace("|", "\\|").replace("\n", " ")
        summary.append(f"| {result['file']} | {detail} |")
    summary.extend(["", "Only line endings are normalized; all other HTML and whitespace must match exactly.",
                    "Download the blogger-html-comparison artifact for results and per-file diffs.", ""])
    report = "\n".join(summary)
    (args.output / "summary.md").write_text(report, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(report)
    return 0 if all(result["status"] == "match" for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
