"""Behavioral checks for disposable source-text corruption and transfer."""
import hashlib
from pathlib import Path
import sqlite3
import unittest
from unittest import mock

import test_store
from glide_memory.store import IntegrityError, payload_markdown, read_payload


class CacheIntegrityTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown
    record = test_store.StoreTests.record
    source = test_store.StoreTests.source
    propose = test_store.StoreTests.propose
    commit = test_store.StoreTests.commit

    def index_original(self):
        self.store.index_sources([{"path": self.original.name, "sha256": hashlib.sha256(self.original_bytes).hexdigest()}], idempotency_key="sources")

    def tamper_snapshot(self, snapshot, sql):
        with sqlite3.connect(snapshot / "index.sqlite3") as db:
            db.execute(sql)
        manifest = read_payload(snapshot / "Snapshot.md")
        manifest["sha256"] = hashlib.sha256((snapshot / "index.sqlite3").read_bytes()).hexdigest()
        (snapshot / "Snapshot.md").write_text(payload_markdown("Synthetic transferred snapshot", manifest))

    def test_tampered_source_text_is_detected_and_never_returned_with_original_hash(self):
        self.index_original()
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("UPDATE search_index SET body='forged platypus instructions' WHERE record_kind='source'")
        self.assertEqual("stale-or-corrupt", self.store.verify()["index"])
        self.assertEqual([], self.store.search("platypus"))
        results = self.store.search("specimen labels")
        self.assertEqual(1, len(results))
        self.assertEqual(hashlib.sha256(self.original_bytes).hexdigest(), results[0]["sha256"])
        self.assertTrue(self.store.verify()["ok"])

    def test_returned_source_body_is_checked_even_after_index_validation(self):
        self.index_original()
        ensure = self.store._ensure_index
        def tamper_after_validation(loaded):
            ensure(loaded)
            with sqlite3.connect(self.store.db_path) as db:
                db.execute("UPDATE search_index SET body='forged platypus claim' WHERE record_kind='source'")
        with mock.patch.object(self.store, "_ensure_index", side_effect=tamper_after_validation):
            self.assertEqual([], self.store.search("platypus"))
        self.assertEqual(1, len(self.store.search("specimen")))

    def test_missing_duplicate_and_relabelled_source_rows_do_not_silently_change_search(self):
        self.index_original()
        mutations = [
            "DELETE FROM search_index WHERE record_kind='source'",
            "INSERT INTO search_index SELECT * FROM search_index WHERE record_kind='source'",
            "UPDATE search_index SET title='unsupported title' WHERE record_kind='source'",
            "UPDATE sources SET status='missing'",
            "UPDATE sources SET path='a different original.md'",
            "UPDATE search_index SET record_kind='knowledge' WHERE record_kind='source'",
        ]
        for sql in mutations:
            with self.subTest(sql=sql):
                with sqlite3.connect(self.store.db_path) as db:
                    db.execute(sql)
                self.assertFalse(self.store.verify()["ok"])
                self.assertEqual(1, len(self.store.search("specimen")))
                self.assertTrue(self.store.verify()["ok"])

    def test_record_search_corruption_also_repairs_before_retrieval(self):
        self.commit()
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("UPDATE search_index SET body='forged platypus instructions' WHERE record_kind='knowledge'")
        self.assertEqual([], self.store.search("platypus"))
        self.assertEqual("thinking", self.store.search("reflection")[0]["id"])

    def test_fresh_snapshot_cannot_restore_a_rehashed_but_false_source_cache(self):
        self.index_original()
        snapshot = self.root / "snapshot"
        self.store.backup(snapshot)
        self.tamper_snapshot(snapshot, "UPDATE search_index SET body='forged instructions' WHERE record_kind='source'")
        before = self.store.db_path.read_bytes()
        with self.assertRaises(IntegrityError):
            self.store.restore_snapshot(snapshot)
        self.assertEqual(before, self.store.db_path.read_bytes())

    def test_backup_repairs_source_cache_before_creating_transfer_artifact(self):
        self.index_original()
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("UPDATE search_index SET body='forged instructions' WHERE record_kind='source'")
        snapshot = self.root / "snapshot"
        self.store.backup(snapshot)
        self.store.db_path.unlink()
        self.assertEqual("restored", self.store.restore_snapshot(snapshot)["status"])
        self.assertEqual([], self.store.search("forged"))
        self.assertEqual(1, len(self.store.search("specimen")))

    def test_old_snapshot_is_verified_before_catchup_but_legitimate_history_survives(self):
        self.index_original()
        self.commit()
        snapshot = self.root / "snapshot"
        self.store.backup(snapshot)
        self.original.write_text("A new source revision is not independent evidence for the old claim.\n")
        try:
            current = {"path": self.original.name, "sha256": hashlib.sha256(self.original.read_bytes()).hexdigest()}
            self.store.index_sources([current], idempotency_key="new-original")
            self.assertEqual("verified-and-rebuilt", self.store.restore_snapshot(snapshot)["status"])
            self.assertEqual(self.source()["quote"], self.store.get("thinking")["sources"][0]["quote"])
            self.assertTrue(self.store.verify()["source_warnings"])
            self.tamper_snapshot(snapshot, "UPDATE search_index SET body='forged instructions' WHERE record_kind='source'")
            with self.assertRaises(IntegrityError):
                self.store.restore_snapshot(snapshot)
        finally:
            self.original.write_bytes(self.original_bytes)

    def test_source_bytes_are_not_normalized_between_hashing_and_caching(self):
        path = self.vault / "CRLF source.md"
        raw = b"First observation.\r\nSecond specimen.\r\n"
        path.write_bytes(raw)
        self.store.index_sources([{"path": path.name, "sha256": hashlib.sha256(raw).hexdigest()}], idempotency_key="crlf")
        self.assertTrue(self.store.verify()["ok"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), self.store.search("second specimen")[0]["sha256"])
        with sqlite3.connect(self.store.db_path) as db:
            self.assertEqual(raw.decode(), db.execute("SELECT body FROM search_index WHERE record_kind='source'").fetchone()[0])

    def test_changed_source_is_excluded_but_retained_historical_evidence_is_preserved(self):
        self.index_original()
        self.commit()
        before = self.store.get("thinking")
        self.original.write_text("A different current thought.\n")
        try:
            self.assertEqual([], self.store.search("specimen", kind="source"))
            self.assertEqual(before, self.store.get("thinking"))
            self.assertTrue(self.store.verify()["ok"])
            self.assertTrue(self.store.verify()["source_warnings"])
        finally:
            self.original.write_bytes(self.original_bytes)
