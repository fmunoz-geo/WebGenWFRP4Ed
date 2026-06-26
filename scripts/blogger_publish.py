import json
import os
import sys
from pathlib import Path

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/blogger/v3"


def access_token():
    r = requests.post(TOKEN_URL, data={
        "client_id": os.environ["BLOGGER_CLIENT_ID"],
        "client_secret": os.environ["BLOGGER_CLIENT_SECRET"],
        "refresh_token": os.environ["BLOGGER_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    })
    r.raise_for_status()
    return r.json()["access_token"]


def blogger_items(token, blog_id, item_type):
    endpoint = "posts" if item_type == "post" else "pages"
    items = []
    page_token = None

    while True:
        params = {"maxResults": 500}
        if page_token:
            params["pageToken"] = page_token

        r = requests.get(
            f"{API}/blogs/{blog_id}/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        r.raise_for_status()

        data = r.json()
        items.extend(data.get("items", []))

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return items


def resolve_id_by_url(token, blog_id, item_type, target_url):
    target_url = target_url.rstrip("/")

    for item in blogger_items(token, blog_id, item_type):
        item_url = item.get("url", "").rstrip("/")
        if item_url == target_url:
            return item["id"]

    raise RuntimeError(f"Could not resolve Blogger {item_type} ID for URL: {target_url}")


def get_entry_id(token, blog_id, filename, entry):
    entry_id = entry.get("id")

    if entry_id:
        return entry_id

    url = entry.get("url")
    if not url:
        raise RuntimeError(f"{filename}: missing both 'id' and 'url' in blogger-map.json")

    entry_id = resolve_id_by_url(token, blog_id, entry["type"], url)

    print(f"Resolved Blogger ID: {filename}")
    print(f"  type: {entry['type']}")
    print(f"  url:  {url}")
    print(f"  id:   {entry_id}")

    return entry_id


def patch_blogger(token, blog_id, item_type, item_id, html):
    endpoint = "posts" if item_type == "post" else "pages"

    r = requests.patch(
        f"{API}/blogs/{blog_id}/{endpoint}/{item_id}",
        params={"publish": "true"},
        headers={"Authorization": f"Bearer {token}"},
        json={"content": html},
    )
    r.raise_for_status()
    return r.json()


def main():
    changed_file = Path(sys.argv[1])
    changed = [x.strip() for x in changed_file.read_text().splitlines() if x.strip()]

    if not changed:
        print("No changed HTML files.")
        return

    mapping = json.loads(Path("blogger-map.json").read_text(encoding="utf-8"))

    token = access_token()
    blog_id = os.environ.get("BLOGGER_BLOG_ID", "5786466792766468793")

    for filename in changed:
        if filename not in mapping:
            print(f"Skipping {filename}: no entry in blogger-map.json")
            continue

        entry = mapping[filename]
        item_type = entry["type"]
        item_id = get_entry_id(token, blog_id, filename, entry)

        html = Path(filename).read_text(encoding="utf-8")
        result = patch_blogger(token, blog_id, item_type, item_id, html)

        print(f"Updated {filename}")
        print(f"  Blogger {item_type} ID: {item_id}")
        print(f"  URL: {result.get('url')}")


if __name__ == "__main__":
    main()
