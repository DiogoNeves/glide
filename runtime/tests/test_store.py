import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from glide_memory.store import Store, StoreError, ConflictError, IntegrityError, digest, payload_markdown, read_payload


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="glide-test-", dir="/private/tmp" if Path("/private/tmp").is_dir() else None)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.original = self.vault / "2024-02-10 1045.md"
        self.original.write_text("The lab surface layout made specimen labels easier to find.\n")
        self.original_bytes = self.original.read_bytes()
        self.store = Store.initialize(self.vault, self.root / "local")
        self.store.activate_writer(old_writer_stopped=True)

    def tearDown(self):
        self.assertEqual(self.original_bytes, self.original.read_bytes())
        self.tmp.cleanup()

    def source(self):
        return {"path": self.original.name, "sha256": hashlib.sha256(self.original_bytes).hexdigest(), "quote": "The lab surface layout", "locator": "line 1"}

    def record(self, rid="thinking", **overrides):
        record = {"id": rid, "title": "Thinking surfaces", "kind": "knowledge", "body": "A readable surface can support reflection. This is an interpretation, not a universal claim.", "origin": "ai", "sources": [self.source()], "valid_from": "2026-08-30T16:31:00Z"}
        record.update(overrides)
        return record

    def propose(self, records=None, revisions=None, key="initial"):
        records = records or [self.record()]
        return self.store.propose(records, expected_revisions=revisions or {r["id"]: 0 for r in records}, rationale="Retain a useful, qualified interpretation", idempotency_key=key)

    def commit(self, records=None, revisions=None, key="initial", decision="unreviewed"):
        p = self.propose(records, revisions, key)
        return self.store.apply(p["proposal_id"], decision=decision)

    def test_roundtrip_delete_database_preserves_exact_semantic_export(self):
        first = self.commit()
        self.commit([self.record(body="The preference is useful in this context; it does not prove paper is always better.")], {"thinking": 1}, "correction", "approved")
        before = self.store.export()
        answers = self.store.search("preference")
        self.store.db_path.unlink()
        self.assertEqual("missing", self.store.verify()["index"])
        self.store.rebuild()
        self.assertEqual(before, self.store.export())
        self.assertEqual(answers, self.store.search("preference"))
        historical = self.store.get("thinking", at=first["recorded_at"])
        self.assertEqual(1, historical["revision"])
        self.assertEqual("ai", self.store.get("thinking")["origin"])
        self.assertEqual("approved", self.store.get("thinking")["review"])
        self.assertTrue(self.store.verify()["ok"])

    def test_idempotency_and_stale_review_fail_closed(self):
        p = self.propose()
        result = self.store.apply(p["proposal_id"])
        repeated = self.store.apply(p["proposal_id"])
        self.assertEqual(result["bundle"], repeated["bundle"])
        self.assertTrue(repeated["replayed"])
        with self.assertRaises(ConflictError):
            self.store.apply(p["proposal_id"], idempotency_key="another-key")
        stale = self.propose([self.record(body="Another interpretation")], {"thinking": 1}, "stale")
        self.commit([self.record(body="A newer interpretation")], {"thinking": 1}, "new")
        with self.assertRaises(ConflictError):
            self.store.apply(stale["proposal_id"])
        self.assertEqual(2, len(self.store.history()))

    def test_rejected_review_is_durable_without_publishing_claim(self):
        p = self.propose()
        receipt = self.store.apply(p["proposal_id"], decision="rejected", actor="human")
        self.assertEqual("rejected", receipt["decision"])
        self.assertEqual({}, self.store._load()["records"])
        self.assertEqual("rejected", self.store.history()[0]["decision"])
        self.store.db_path.unlink()
        self.store.rebuild()
        self.assertEqual("rejected", self.store.history()[0]["decision"])

    def test_committed_bundle_recovers_after_publication_failure(self):
        p = self.propose()
        with mock.patch.object(self.store, "_publish", side_effect=OSError("power loss")):
            receipt = self.store.apply(p["proposal_id"])
        self.assertTrue(receipt["committed"])
        self.assertEqual("pending", receipt["publication"]["status"])
        self.store.rebuild()
        self.assertEqual(1, self.store.get("thinking")["revision"])
        self.assertTrue(self.store.verify()["ok"])

    def test_partial_projection_replay_preserves_readable_authority(self):
        self.commit()
        original_publish = self.store._publish
        p = self.propose([self.record(body="Newly qualified thinking")], {"thinking": 1}, "new")
        def crash(loaded):
            outputs = self.store._projections(loaded)
            path, text = next(iter(outputs.items()))
            (self.store.store / path).write_text(text)
            raise OSError("interrupted after one page")
        with mock.patch.object(self.store, "_publish", side_effect=crash):
            receipt = self.store.apply(p["proposal_id"])
        self.assertEqual("pending", receipt["publication"]["status"])
        self.store.rebuild()
        self.assertTrue(self.store.verify()["ok"])

    def test_missing_predecessor_and_divergent_history_are_rejected(self):
        self.commit()
        self.commit([self.record(body="Updated thought")], {"thinking": 1}, "new")
        files = sorted((self.store.store / "Bundles").glob("*.md"))
        first_bytes = files[0].read_bytes()
        files[0].unlink()
        with self.assertRaises(IntegrityError):
            self.store.rebuild()
        files[0].write_bytes(first_bytes)
        second = read_payload(files[1])
        second["idempotency_key"] = "fork"
        second["rationale"] = "Another machine wrote concurrently"
        second["hash"] = digest({k: v for k, v in second.items() if k != "hash"})
        fork = files[1].with_name(f"{second['sequence']:08d}-{second['hash']}.md")
        fork.write_text(self.store._bundle_markdown(second))
        with self.assertRaises(ConflictError):
            self.store.verify()

    def test_tampering_rendered_bundle_or_projection_fails(self):
        self.commit()
        projection = self.store.store / self.store.get("thinking")["path"]
        original = projection.read_text()
        projection.write_text(original + "\nA human edit must be reconciled.\n")
        with self.assertRaises(ConflictError):
            self.store.rebuild()
        self.assertIn("human edit", projection.read_text())
        projection.write_text(original)
        bundle = next((self.store.store / "Bundles").glob("*.md"))
        bundle.write_text(bundle.read_text().replace("This is an interpretation", "This is proven", 1))
        with self.assertRaises(IntegrityError):
            self.store.verify()

    def test_source_search_is_a_cache_not_a_duplicate_claim(self):
        s = {"path": self.original.name, "sha256": hashlib.sha256(self.original_bytes).hexdigest()}
        self.store.index_sources([s], idempotency_key="sources")
        self.commit()
        first = self.store.search("surface")
        self.assertEqual({"knowledge", "source"}, {r["kind"] for r in first})
        with sqlite3.connect(self.store.db_path) as db:
            rows = db.execute("SELECT COUNT(DISTINCT source_id) FROM evidence").fetchone()[0]
        self.assertEqual(1, rows)
        self.assertEqual(1, len(self.store.search("surface", include_sources=False)))
        # Original sources are caller-owned. Simulate user editing then restore.
        self.original.write_text("New source content")
        try:
            self.assertEqual(1, len(self.store.search("surface")))
            self.assertTrue(self.store.verify()["source_warnings"])
        finally:
            self.original.write_bytes(self.original_bytes)

    def test_unknown_source_hash_and_missing_file_cannot_launder_evidence(self):
        wrong = self.source()
        wrong.update(sha256="a" * 64, quote="Invented old supporting evidence")
        with self.assertRaises(StoreError):
            self.propose([self.record(sources=[wrong])])
        missing = self.source()
        missing["path"] = "never-captured.md"
        with self.assertRaises(StoreError):
            self.propose([self.record(sources=[missing])])

    def test_verified_old_passage_survives_user_edit_and_proposal_delay(self):
        first = self.propose()
        self.original.write_text("The author changed this note after its first capture.")
        try:
            self.store.apply(first["proposal_id"])
            retained = self.store.get("thinking")["sources"]
            warnings = self.store.verify()["source_warnings"]
            self.assertEqual(["thinking"], warnings[0]["record_ids"])
            self.commit([self.record(body="A new interpretation of the retained old passage", sources=retained)], {"thinking": 1}, "historical")
            self.assertEqual(2, self.store.get("thinking")["revision"])
            invented = self.source()
            invented["quote"] = "This was never in the captured source"
            with self.assertRaises(StoreError):
                self.propose([self.record("bad", sources=[invented])], key="invented")
        finally:
            self.original.write_bytes(self.original_bytes)

    def test_graph_links_target_real_pages_and_claim_blocks(self):
        target = self.record("target", title="Specimen protocol", claims=[{"id": "labels", "text": "The fictional trial used readable specimen labels.", "type": "observation", "sources": [self.source()]}])
        other = self.record("other", relationships=[{"target": "target", "block": "labels", "type": "supports", "reason": "The trial is relevant to designing the readable reference surface."}])
        self.commit([target, other])
        page = (self.store.store / self.store.get("other")["path"]).read_text()
        self.assertIn(Path(self.store.get("target")["path"]).stem + "#^labels", page)
        self.assertNotIn("Record Index", page)

    def test_verify_detects_semantic_db_corruption_even_with_matching_head(self):
        self.commit()
        with sqlite3.connect(self.store.db_path) as db:
            db.execute("UPDATE search_index SET body='unsupported claim' WHERE record_kind='knowledge'")
        self.assertEqual("stale-or-corrupt", self.store.verify()["index"])
        self.store.rebuild()
        self.assertTrue(self.store.verify()["ok"])

    def test_now_does_not_turn_undated_open_loops_into_immediate_work(self):
        records = [self.record(f"open-{i}", kind="operation", status="open") for i in range(8)]
        records += [self.record(f"committed-{i}", kind="operation", status="committed", commitment_evidence=[self.source()]) for i in range(7)]
        self.commit(records)
        now_page = (self.store.store / "Views/Now.md").read_text()
        ongoing = (self.store.store / "Views/Ongoing.md").read_text()
        self.assertEqual(5, sum(line.startswith("- ") for line in now_page.splitlines()))
        self.assertNotIn("`open-", now_page)
        self.assertEqual(12, sum(line.startswith("- ") for line in ongoing.splitlines()))
        self.assertIn("Browse all records", now_page)

    def test_registered_capture_lineage_survives_only_identical_revision_reindex(self):
        captured = {"path": self.original.name, "sha256": hashlib.sha256(self.original_bytes).hexdigest(), "canonical_uri": "fictional-note:specimen-1", "source_kind": "apple-notes"}
        self.store.index_sources([captured], idempotency_key="capture")
        generic = {"path": self.original.name, "sha256": captured["sha256"], "source_kind": "original-markdown"}
        self.store.index_sources([generic], idempotency_key="reindex")
        registered = self.store.export()["sources"][0]
        self.assertEqual(captured["canonical_uri"], registered["canonical_uri"])
        self.assertEqual("apple-notes", registered["source_kind"])
        with self.assertRaises(ConflictError):
            self.store.index_sources([{**captured, "canonical_uri": "different-source"}], idempotency_key="wrong-lineage")
        self.original.write_text("A changed file has not been reverified by the native capture adapter.")
        try:
            self.store.index_sources([{"path": self.original.name, "sha256": hashlib.sha256(self.original.read_bytes()).hexdigest()}], idempotency_key="changed-generic")
            changed = self.store.export()["sources"][0]
            self.assertNotIn("canonical_uri", changed)
            self.assertEqual("original-markdown", changed["source_kind"])
        finally:
            self.original.write_bytes(self.original_bytes)

    def test_a_model_cannot_relabel_verified_file_evidence_as_another_canonical_source(self):
        fake = {**self.source(), "canonical_uri": "fictional-forged-source"}
        with self.assertRaises(StoreError):
            self.propose([self.record(sources=[fake])], key="fake-lineage")
        source = {"path": self.original.name, "sha256": fake["sha256"], "canonical_uri": "fictional-native-source", "source_kind": "apple-notes"}
        self.store.index_sources([source], idempotency_key="verified-capture")
        proper = {**self.source(), "canonical_uri": source["canonical_uri"]}
        self.commit([self.record(sources=[proper])])
        self.assertTrue(self.store.get("thinking")["sources"][0]["source_id"].startswith("uri:"))
        with self.assertRaises(StoreError):
            self.propose([self.record("another", sources=[fake])], key="wrong-registered-lineage")

    def test_legacy_ai_archives_require_explicit_source_search_and_stay_readable(self):
        paths, observations = [], []
        for root in ("Agent HQ", "Glide HQ"):
            path = self.vault / root / "Legacy Memory" / "Fictional old automation.md"
            path.parent.mkdir(parents=True)
            path.write_text("Archive-only platypus observations from a fictional automation.")
            paths.append(path)
            observations.append({"path": path.relative_to(self.vault).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source_kind": "legacy-agent-context"})
        self.store.index_sources(observations, idempotency_key="old-archives")
        original = {str(path): path.read_bytes() for path in paths}
        self.assertEqual([], self.store.search("platypus"))
        explicit = self.store.search("platypus", kind="source")
        self.assertEqual(2, len(explicit))
        self.assertTrue(all(hit["source_kind"] == "archived-ai-history" and hit["provenance_role"] == "non-independent-history" for hit in explicit))
        historical = {**observations[0], "quote": "Archive-only platypus observations"}
        self.commit([self.record("dated-history", body="This is a dated record of an earlier AI interpretation, not independent corroboration.", sources=[historical])])
        retained = self.store.get("dated-history")["sources"][0]
        self.assertEqual("non-independent-history", retained["provenance_role"])
        before = self.store.export()
        explicit_before_rebuild = self.store.search("platypus", kind="source")
        self.store.db_path.unlink()
        self.store.rebuild()
        self.assertEqual(before, self.store.export())
        self.assertEqual([], self.store.search("platypus"))
        self.assertEqual(explicit_before_rebuild, self.store.search("platypus", kind="source"))
        for path in paths:
            self.assertEqual(original[str(path)], path.read_bytes())

    def test_managed_records_rank_before_sources_and_kind_filters_precede_limit(self):
        observations = []
        for index in range(210):
            path = self.vault / f"Fictional source {index}.md"
            path.write_text("ideas ideas ideas")
            observations.append({"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        self.store.index_sources(observations, idempotency_key="many-sources")
        self.commit([self.record("managed-ideas", body="A qualified account of several ideas in a fictional laboratory context.")])
        self.assertEqual("managed-ideas", self.store.search("ideas", limit=1)[0]["id"])
        self.assertEqual("managed-ideas", self.store.search("ideas", kind="knowledge", limit=1)[0]["id"])
        self.assertEqual("source", self.store.search("ideas", kind="source", limit=1)[0]["kind"])
        self.assertEqual("managed-ideas", self.store.search("ideas", valid_at="2026-09-01T00:00:00Z", limit=1)[0]["id"])

    def test_source_fingerprint_and_quote_must_match(self):
        source = self.source()
        source["quote"] = "An invented supporting quote"
        with self.assertRaises(StoreError):
            self.propose([self.record(sources=[source])])
        with self.assertRaises(ConflictError):
            self.store.index_sources([{"path": self.original.name, "sha256": "a" * 64}], idempotency_key="bad-source")

    def test_approval_preserves_origin_and_operation_states(self):
        with self.assertRaises(StoreError):
            self.propose([self.record(kind="operation", status="complete")])
        with self.assertRaises(StoreError):
            self.propose([self.record(kind="operation", status="committed")])
        self.commit([self.record(kind="operation", status="sent")], decision="approved")
        self.assertEqual("sent", self.store.get("thinking")["status"])
        self.assertEqual("ai", self.store.get("thinking")["origin"])
        with self.assertRaises(StoreError):
            self.propose([self.record(kind="operation", status="sent", origin="human")], {"thinking": 1}, "origin-change")
        self.commit([self.record(kind="operation", status="complete", completion_evidence=[self.source()])], {"thinking": 1}, "complete", "approved")
        self.assertEqual("complete", self.store.get("thinking")["status"])

    def test_readonly_new_machine_and_explicit_handover(self):
        self.commit()
        second = Store.initialize(self.vault, self.root / "second-local")
        self.assertFalse(second.config["writer_active"])
        self.assertEqual(self.store.export(), second.export())
        with self.assertRaises(StoreError):
            second.propose([self.record("other")], expected_revisions={"other": 0}, rationale="No writer authority", idempotency_key="other")
        with self.assertRaises(StoreError):
            second.activate_writer()
        self.store.deactivate_writer()
        second.activate_writer(old_writer_stopped=True)
        with self.assertRaises(StoreError):
            self.propose([self.record("stale")], key="stale-writer")
        self.assertEqual(self.store.export(), second.export())

    def test_snapshot_compatibility_and_source_head(self):
        self.commit()
        snapshot = self.root / "snapshot"
        self.store.backup(snapshot)
        self.store.db_path.unlink()
        self.assertEqual("restored", self.store.restore_snapshot(snapshot)["status"])
        before = self.store.export()
        self.store.rebuild()
        self.assertEqual(before, self.store.export())
        manifest_path = snapshot / "Snapshot.md"
        manifest = read_payload(manifest_path)
        manifest["head"] = "a" * 64
        manifest_path.write_text(payload_markdown("Bad snapshot", manifest))
        with self.assertRaises(IntegrityError):
            self.store.restore_snapshot(snapshot)

    def test_paths_symlinks_and_duplicate_titles(self):
        with self.assertRaises(StoreError):
            Store.initialize(self.vault, self.vault / "local")
        with self.assertRaises(StoreError):
            Store.initialize(self.vault, self.root / "other", "../escape")
        outside = self.root / "outside.md"
        outside.write_text("private")
        symlink = self.vault / "linked.md"
        symlink.symlink_to(outside)
        with self.assertRaises(StoreError):
            self.propose([self.record(sources=[{"path": "linked.md", "sha256": hashlib.sha256(b"private").hexdigest(), "quote": "private"}])])
        self.commit([self.record("one", title="A: title? / valid"), self.record("two", title="A: title? / valid")])
        self.assertNotEqual(self.store.get("one")["path"], self.store.get("two")["path"])
        for record in self.store.export()["records"]:
            self.assertNotIn(":", record["path"])
            self.assertFalse((self.store.store / record["path"]).read_text().split("---\n\n", 1)[1].startswith("# "))
        with self.assertRaises(StoreError):
            self.propose([self.record("header", body="# Duplicate title\n\nText")], key="header")

    def test_temporal_search_matches_claim_validity_and_old_revision_text(self):
        future = self.record("future", title="Experiment record", body="An overview of a fictional trial.", valid_from=None, claims=[{"id": "later", "type": "hypothesis", "text": "Cobalt specimens may be easier to identify.", "valid_from": "2026-01-01T00:00:00Z", "sources": [self.source()]}])
        first = self.commit([future])
        self.assertEqual([], self.store.search("Cobalt", valid_at="2025-01-01T00:00:00Z", include_sources=False))
        self.assertEqual(["future"], [r["id"] for r in self.store.search("Cobalt", valid_at="2026-02-01T00:00:00Z", include_sources=False)])
        changed = self.record("future", title="Experiment record", body="An overview of a fictional trial.", valid_from=None, claims=[{"id": "later", "type": "hypothesis", "text": "Amber specimens may be easier to identify.", "valid_from": "2026-01-01T00:00:00Z", "sources": [self.source()]}])
        self.commit([changed], {"future": 1}, "replace-color")
        self.assertEqual([], self.store.search("Cobalt", include_sources=False))
        earlier = self.store.search("Cobalt", recorded_at=first["recorded_at"], valid_at="2026-02-01T00:00:00Z", include_sources=False)
        self.assertEqual(1, earlier[0]["revision"])
        self.assertEqual([], self.store.search("Amber", recorded_at=first["recorded_at"], include_sources=False))
        self.assertTrue(self.store.verify()["ok"])

    def test_now_surfaces_due_reviews_but_not_future_reviews(self):
        self.commit([self.record("due-review", kind="operation", status="waiting", review_at="2001-01-01T00:00:00Z"), self.record("future-review", kind="operation", status="waiting", review_at="2999-01-01T00:00:00Z")])
        page = (self.store.store / "Views/Now.md").read_text()
        self.assertIn("`due-review`", page)
        self.assertNotIn("`future-review`", page)
        legacy = self.store._projections(self.store._load(), include_due_reviews=False)["Views/Now.md"]
        (self.store.store / "Views/Now.md").write_text(legacy)
        self.assertIn("Views/Now.md", self.store.verify()["stale_projections"])
        self.store.rebuild()
        self.assertEqual(page, (self.store.store / "Views/Now.md").read_text())
        self.assertTrue(self.store.verify()["ok"])

    def test_temporal_validity_and_changed_since(self):
        first = self.commit([self.record(valid_until="2026-09-01T00:00:00Z")])
        second = self.commit([self.record("new", body="Unrelated useful knowledge")], key="second")
        self.assertEqual([], self.store.search("surface", valid_at="2026-09-02T00:00:00Z"))
        self.assertEqual(1, len(self.store.search("surface", valid_at="2026-08-31T00:00:00Z")))
        self.assertEqual([second["bundle"]], [r["bundle"] for r in self.store.changes_since(first["bundle"])])
        with self.assertRaises(StoreError):
            self.store.changes_since("a" * 64)

    def test_claim_ids_are_compatible_with_obsidian_block_anchors(self):
        for claim_id in ("claim:one", "claim.one", "claim_one"):
            with self.assertRaises(StoreError):
                self.propose([self.record(claims=[{"id": claim_id, "type": "observation", "text": "A fictional observation", "sources": [self.source()]}])], key=claim_id)

    def test_typed_claims_preserve_qualifications_and_independent_evidence(self):
        record = self.record(claims=[{"id": "claim-1", "type": "stated-view", "text": "The author preferred a thinking surface on this date.", "sources": [self.source()], "uncertainty": "This does not establish a permanent tool preference."}])
        self.commit([record])
        page = (self.store.store / self.store.get("thinking")["path"]).read_text()
        self.assertIn("stated-view", page)
        self.assertIn("does not establish", page)
        self.assertIn("^claim-1", page)
        with sqlite3.connect(self.store.db_path) as db:
            self.assertEqual(1, db.execute("SELECT COUNT(DISTINCT source_id) FROM evidence").fetchone()[0])

    def test_generic_markdown_adapter_does_not_emit_wikilinks(self):
        store = Store.initialize(self.vault, self.root / "generic-local", "Glide HQ/Memory", "markdown")
        store.activate_writer(old_writer_stopped=True)
        p = store.propose([self.record()], expected_revisions={"thinking": 0}, rationale="Generic rendering", idempotency_key="generic")
        store.apply(p["proposal_id"])
        record = store.get("thinking")
        text = (store.store / record["path"]).read_text()
        self.assertNotIn("[[", text)
        self.assertIn("2024-02-10%201045.md", text)


if __name__ == "__main__":
    unittest.main()
