"""Golden immutable-data contract. Never regenerate this fixture to fix a test.

A changed renderer needs a new format version and the old reader must stay able
 to validate this exact file. Fixtures contain only fictional source material.
"""
from pathlib import Path
import unittest
from glide_memory.store import Store, digest, read_payload


class FormatTests(unittest.TestCase):
    def test_immutable_v1_markdown_has_a_frozen_reader(self):
        path = Path(__file__).parent / 'fixtures/format-v1-bundle.md'
        bundle = read_payload(path)
        self.assertEqual(bundle['hash'], digest({k: v for k, v in bundle.items() if k != 'hash'}))
        renderer = object.__new__(Store)
        renderer.config = {'store_path': 'Glide HQ/Memory'}
        renderer.adapter = 'markdown'
        self.assertEqual(path.read_text(), renderer._bundle_markdown(bundle))
        self.assertEqual(1, bundle['format_version'])


if __name__ == '__main__':
    unittest.main()
