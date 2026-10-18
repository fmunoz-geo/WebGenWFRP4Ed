import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

import blogger_check as check


def wrap(body):
    return '<html><div class="extra float-container post-body entry-content">' + body + '</div></html>'


class PostBodyTests(unittest.TestCase):
    def test_preserves_nested_markup_scripts_and_entities(self):
        body = '<!DOCTYPE html>\n<style>.x{color:red}</style><div><div>Mu&ntilde;oz</div></div><script>const x="<div></div>";</script>'
        self.assertEqual(check.extract_post_body(wrap(body)), body)

    def test_missing_duplicate_and_unclosed_bodies_are_errors(self):
        for html in ('<div class="post-body">wrong</div>', wrap('a') + wrap('b'), '<div class="post-body entry-content float-container">x'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                check.extract_post_body(html)

    def test_boundary_whitespace_is_preserved(self):
        self.assertEqual(check.extract_post_body(wrap('\n x \n')), '\n x \n')

    def test_compare_match_diff_and_fetch_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.html').write_bytes(b'<b>example</b>\r\n')
            entry = {'url': 'https://example.com/post'}
            with patch.object(check, 'fetch_html', return_value=wrap('<b>example</b>\n')):
                self.assertEqual(check.compare_entry('source.html', entry, root, root)['status'], 'match')
            with patch.object(check, 'fetch_html', return_value=wrap('<b>other</b>\n')):
                result = check.compare_entry('source.html', entry, root, root)
                self.assertEqual(result['status'], 'different')
                diff = (root / result['diff']).read_text()
                self.assertIn('-<b>other</b>', diff)
                self.assertIn('+<b>example</b>', diff)
            with patch.object(check, 'fetch_html', side_effect=URLError('offline')):
                self.assertEqual(check.compare_entry('source.html', entry, root, root)['status'], 'error')

    def test_main_checks_every_mapping_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapping = root / 'map.json'
            mapping.write_text(json.dumps({'a.html': {'url': 'https://example.com/a'}, 'b.html': {'url': 'https://example.com/b'}}))
            def compare(filename, entry, *_):
                return {'file': filename, 'url': entry['url'], 'status': 'match' if filename == 'a.html' else 'different'}
            with patch.object(check, 'compare_entry', side_effect=compare) as mocked, patch.dict(check.os.environ, {'GITHUB_STEP_SUMMARY': ''}):
                self.assertEqual(check.main(['--map', str(mapping), '--output', str(root / 'out')]), 1)
                self.assertEqual(mocked.call_count, 2)
                self.assertEqual(len(json.loads((root / 'out/results.json').read_text())), 2)


if __name__ == '__main__':
    unittest.main()
