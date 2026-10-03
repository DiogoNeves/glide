import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import test_store
from glide_memory.store import ConflictError, StoreError


class RecordReaderTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown
    source = test_store.StoreTests.source
    record = test_store.StoreTests.record
    propose = test_store.StoreTests.propose
    commit = test_store.StoreTests.commit

    def test_full_default_is_unchanged_and_window_retains_evidence_graph_and_time(self):
        text = "First line.\n" + "🦆" * 111 + "\nImportant final constraint."
        self.commit([self.record("target"), self.record(body=text,
            relationships=[{"target": "target", "type": "supports", "reason": "Related context"}],
            claims=[{"id": "c1", "text": "A qualified inference", "type": "ai-inference", "sources": [self.source()]}])])
        original = self.store.get("thinking")
        chunks, page = [], self.store.get("thinking", max_lines=2, max_chars=31)
        while True:
            self.assertLessEqual(len(page["body"]), 31)
            for name in ("sources", "claims", "relationships", "origin", "review", "valid_from", "revision"):
                self.assertEqual(original[name], page[name])
            self.assertFalse(page["read_window"]["metadata_bounded"])
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), page["read_window"]["body_sha256"])
            chunks.append(page["body"])
            args = page["read_window"]["next_args"]
            if args is None:
                break
            self.assertEqual(original["revision"], args["expected_revision"])
            page = self.store.get(**args)
        self.assertEqual(text, "".join(chunks))
        self.assertEqual(original, self.store.get(**page["read_window"]["full_args"]))
        self.assertNotIn("read_window", original)
        self.assertEqual(original, self.store.get("thinking"))

    def test_window_helper_preserves_crlf_and_unicode_without_normalizing_text(self):
        from glide_memory.readers import record_window
        text = "A\r\n" + "🦆" * 31 + "\r\nEnd\r\n"
        record = {"body": text, "recorded_at": "2026-10-03T12:00:00Z", "revision": 1}
        pieces, arguments = [], {"record_id": "synthetic", "max_lines": 1, "max_chars": 7}
        while True:
            page = record_window(record, **arguments)
            pieces.append(page["body"])
            next_args = page["read_window"]["next_args"]
            if next_args is None:
                break
            arguments = {key: value for key, value in next_args.items() if key != "expected_revision"}
        self.assertEqual(text, "".join(pieces))

    def test_continuation_remains_on_exact_revision_after_new_write(self):
        first = self.commit([self.record(body="Old first.\nOld last.\n")])
        page = self.store.get("thinking", max_lines=1)
        self.commit([self.record(body="New current.")], {"thinking": 1}, "new")
        remainder = self.store.get(**page["read_window"]["next_args"])
        self.assertEqual("Old last.", remainder["body"])
        self.assertEqual(1, remainder["revision"])
        self.assertEqual(first["recorded_at"], remainder["read_window"]["full_args"]["at"])
        with self.assertRaises(ConflictError):
            self.store.get("thinking", expected_revision=1, max_lines=1)
        self.assertEqual(2, self.store.get("thinking")["revision"])

    def test_window_is_not_admitted_as_complete_durable_record(self):
        self.commit([self.record(body="First.\nSecond.\n")])
        before = self.store.export()
        proposals = set((self.store.store / "Proposals").iterdir())
        window = self.store.get("thinking", max_lines=1)
        with self.assertRaisesRegex(StoreError, "not a complete"):
            self.store.propose([window], expected_revisions={"thinking": 1},
                               rationale="Must not silently truncate", idempotency_key="window")
        self.assertEqual(proposals, set((self.store.store / "Proposals").iterdir()))
        self.assertEqual(before, self.store.export())

    def test_invalid_bounds_and_bool_values_are_rejected(self):
        self.commit([self.record(body="One\nTwo")])
        cases = [{"start_line": 0}, {"start_line": 4}, {"start_line": True},
                 {"start_offset": -1}, {"start_offset": True}, {"start_offset": 4},
                 {"max_lines": 0}, {"max_lines": 501}, {"max_lines": True},
                 {"max_chars": 0}, {"max_chars": 32769}, {"max_chars": True},
                 {"expected_revision": 0}, {"expected_revision": True}]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises((ValueError, StoreError)):
                self.store.get("thinking", **arguments)

    def test_default_window_budget_bounds_a_single_long_line(self):
        self.commit([self.record(body="x" * 20000)])
        page = self.store.get("thinking", start_line=1)
        self.assertEqual(8000, len(page["body"]))
        self.assertTrue(page["read_window"]["truncated"])
        self.assertEqual(8000, page["read_window"]["next_args"]["start_offset"])

    def test_cli_window_matches_store_and_does_not_mutate_history(self):
        self.commit([self.record(body="First.\nSecond.\n")])
        before = self.store.export()
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1]), "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, "-B", "-m", "glide_memory", "--config", str(self.store.config_path),
                   "get", "thinking", "--start-line", "2", "--max-chars", "3"]
        result = subprocess.run(command, capture_output=True, text=True, check=True, env=environment)
        self.assertEqual(self.store.get("thinking", start_line=2, max_chars=3), json.loads(result.stdout))
        self.assertEqual(before, self.store.export())
