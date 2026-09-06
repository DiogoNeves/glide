"""The optional wiki path is scoped automation, never human approval."""
import json
import unittest

import test_store
from glide_memory.store import Store, StoreError, read_payload
from glide_memory.jobs import job_inputs, finish_job


class KnowledgePolicyTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown
    source = test_store.StoreTests.source
    record = test_store.StoreTests.record
    propose = test_store.StoreTests.propose
    commit = test_store.StoreTests.commit

    def automatic(self, **extra):
        self.store.config.update(knowledge_review="automatic", automatic_source_prefixes=[self.original.name], **extra)
        self.store._save_config()

    def test_manual_is_default_and_regular_personal_operations_still_work(self):
        self.assertEqual({"knowledge_review": "manual", "review_ui": "text", "automatic_source_prefixes": [], "job_knowledge_policy": "manual"}, self.store.review_settings())
        p = self.propose()
        with self.assertRaises(StoreError):
            self.store.apply(p["proposal_id"], knowledge_ingestion=True)
        self.assertEqual([], self.store.history())
        operation = self.propose([self.record("open-loop", kind="operation", status="open")], key="operation")
        receipt = self.store.apply(operation["proposal_id"])
        self.assertTrue(receipt["committed"])
        self.assertEqual("open", self.store.get("open-loop")["status"])

    def test_automatic_wiki_ingestion_retains_policy_origin_and_unreviewed_receipt_after_rebuild(self):
        self.automatic(review_ui="interactive")
        p = self.propose()
        receipt = self.store.apply(p["proposal_id"], knowledge_ingestion=True, expected_revisions={"thinking": 0})
        self.assertEqual("knowledge-ingestion", receipt["actor"])
        self.assertEqual("unreviewed", receipt["decision"])
        self.assertEqual("automatic", receipt["knowledge_policy"]["knowledge_review"])
        bundle = read_payload(next((self.store.store / "Bundles").glob("*.md")))
        self.assertEqual(receipt["knowledge_policy"], bundle["knowledge_policy"])
        self.store.db_path.unlink()
        self.store.rebuild()
        self.assertEqual("ai", self.store.get("thinking")["origin"])
        self.assertEqual("unreviewed", self.store.get("thinking")["review"])
        repeated = self.store.apply(p["proposal_id"], knowledge_ingestion=True, expected_revisions={"thinking": 0})
        self.assertTrue(repeated["replayed"])
        self.assertEqual(receipt["bundle"], repeated["bundle"])
        self.assertEqual(receipt["knowledge_policy"], repeated["knowledge_policy"])

    def test_retries_cannot_bypass_policy_or_versions_or_manufacture_human_approval(self):
        self.automatic()
        p = self.propose()
        self.store.apply(p["proposal_id"], knowledge_ingestion=True)
        for args in ({"decision": "approved", "knowledge_ingestion": True}, {"decision": "approved"}, {"knowledge_ingestion": True, "expected_revisions": {"thinking": 123}}, {"actor": "knowledge-ingestion"}):
            with self.subTest(args=args), self.assertRaises(StoreError):
                self.store.apply(p["proposal_id"], **args)
        self.store.config["knowledge_review"] = "manual"
        self.store._save_config()
        with self.assertRaises(StoreError):
            self.store.apply(p["proposal_id"], knowledge_ingestion=True)
        self.assertEqual(1, len(self.store.history()))
        self.assertEqual("unreviewed", self.store.get("thinking")["review"])

    def test_explicit_scopes_match_path_components_not_similar_prefixes(self):
        self.automatic()
        p = self.propose()
        for prefix in ("2024", "Other Inbox/", "2024-02-10"):
            self.store.config["automatic_source_prefixes"] = [prefix]
            self.store._save_config()
            with self.subTest(prefix=prefix), self.assertRaises(StoreError):
                self.store.apply(p["proposal_id"], knowledge_ingestion=True)
        self.assertEqual([], self.store.history())

    def test_invalid_or_missing_configured_scope_fails_closed(self):
        for value in ([], ["/"], ["."], ["../Inbox"], [".private"], ["Inbox//Notes"], ["Inbox/../Notes"], "Inbox"):
            with self.subTest(value=value):
                config = dict(self.store.config, knowledge_review="automatic", automatic_source_prefixes=value)
                self.store.config_path.write_text(json.dumps(config))
                with self.assertRaises(StoreError):
                    Store.from_config(self.store.config_path)
        self.store._save_config()

    def test_automatic_path_rejects_other_record_kinds_authorship_approval_and_action_states(self):
        self.automatic()
        changes = [
            {"kind": "operation", "status": "open"}, {"kind": "decision"}, {"kind": "workflow"},
            {"origin": "human"}, {"review": "approved"}, {"status": "committed"},
            {"completion_evidence": [self.source()]}, {"commitment_evidence": [self.source()]},
            {"due_at": "2026-09-07T00:00:00Z"}, {"supersedes": "someone-else"},
            {"sources": [{"uri": "https://example.com/evidence", "sha256": "a" * 64, "quote": "Provided excerpt"}]},
        ]
        for index, fields in enumerate(changes):
            with self.subTest(fields=fields):
                p = self.propose([self.record("case-" + str(index), **fields)], key="case-" + str(index))
                with self.assertRaises(StoreError):
                    self.store.apply(p["proposal_id"], knowledge_ingestion=True)
        self.assertEqual([], self.store.history())

    def test_knowledge_cannot_replace_existing_operation_or_invent_evidence(self):
        self.commit([self.record(kind="operation", status="open")])
        self.automatic()
        p = self.propose([self.record()], {"thinking": 1}, "type-change")
        with self.assertRaises(StoreError):
            self.store.apply(p["proposal_id"], knowledge_ingestion=True)
        forged = self.source()
        forged["quote"] = "An invented business fact"
        with self.assertRaises(StoreError):
            self.propose([self.record("forged", sources=[forged])], key="forged")
        self.assertEqual("operation", self.store.get("thinking")["kind"])

    def finish_knowledge_job(self, inputs, *, records=None, key="finish-policy"):
        records = records if records is not None else [self.record("new-knowledge")]
        revisions = {inputs["checkpoint_id"]: inputs["checkpoint_revision"], **{record["id"]: 0 for record in records}}
        return finish_job(self.store, "dream", inputs["processed_through"], records, revisions, "Processed a scoped source.", [self.source()], key)

    def test_fresh_manual_job_cannot_publish_knowledge_or_advance_checkpoint_without_review(self):
        self.commit([self.record("input")])
        inputs = job_inputs(self.store, "dream")
        before = self.store.export()
        with self.assertRaisesRegex(StoreError, "Manual knowledge review"):
            self.finish_knowledge_job(inputs)
        self.assertEqual(before, self.store.export())
        self.assertEqual(0, job_inputs(self.store, "dream")["checkpoint_revision"])
        # An explicitly reviewed knowledge proposal can be applied separately;
        # ordinary authorized operation outputs and the checkpoint remain usable.
        p = self.propose([self.record("reviewed")], key="reviewed")
        self.store.apply(p["proposal_id"], decision="approved")
        receipt = self.finish_knowledge_job(inputs, records=[self.record("followup", kind="operation", status="open")], key="operations-only")
        self.assertTrue(receipt["committed"])
        self.assertNotIn("knowledge_policy", receipt)

    def test_automatic_job_checks_knowledge_subset_and_retains_atomic_policy_receipt(self):
        self.automatic()
        self.commit([self.record("input")])
        inputs = job_inputs(self.store, "dream")
        records = [self.record("new-knowledge"), self.record("followup", kind="operation", status="open")]
        receipt = self.finish_knowledge_job(inputs, records=records)
        self.assertEqual("job:dream", receipt["actor"])
        self.assertEqual("automatic", receipt["knowledge_policy"]["knowledge_review"])
        self.assertEqual({"new-knowledge", "followup", inputs["checkpoint_id"]}, set(receipt["revisions"]))
        self.assertEqual("unreviewed", self.store.get("new-knowledge")["review"])
        self.assertTrue(self.finish_knowledge_job(inputs, records=records)["replayed"])
        self.store.config["automatic_source_prefixes"] = ["Different Inbox/"]
        self.store._save_config()
        with self.assertRaises(StoreError):
            self.finish_knowledge_job(inputs, records=records)

    def test_explicit_automatic_job_cannot_bypass_scope_or_launder_human_approval(self):
        self.automatic()
        self.commit([self.record("input")])
        inputs = job_inputs(self.store, "dream")
        self.store.config["automatic_source_prefixes"] = ["Different Inbox/"]
        self.store._save_config()
        with self.assertRaises(StoreError):
            self.finish_knowledge_job(inputs)
        self.assertEqual(0, job_inputs(self.store, "dream")["checkpoint_revision"])
        self.automatic()
        with self.assertRaises(StoreError):
            self.finish_knowledge_job(inputs, records=[self.record("preapproved", review="approved")], key="preapproved")

    def test_upgrade_without_review_setting_preserves_only_existing_authorized_job_scope(self):
        self.store.config.pop("knowledge_review")
        self.store._save_config()
        self.assertEqual("legacy-authorized", self.store.review_settings()["job_knowledge_policy"])
        self.commit([self.record("input")])
        inputs = job_inputs(self.store, "dream")
        receipt = self.finish_knowledge_job(inputs)
        self.assertTrue(receipt["committed"])
        self.assertNotIn("knowledge_policy", receipt)
        self.assertEqual("unreviewed", self.store.get("new-knowledge")["review"])
        # Absence does not opt a legacy instance into the new automatic API.
        p = self.propose([self.record("new-wiki")], key="new-wiki")
        with self.assertRaises(StoreError):
            self.store.apply(p["proposal_id"], knowledge_ingestion=True)
