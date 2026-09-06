import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from glide_memory.bridge import MemoryServer, serve, TOOLS
from glide_memory.store import Store


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.source = self.vault / "A source.md"
        self.source.write_text("A dated observation.\nA second line.\nA third line.\n")
        self.store = Store.initialize(self.vault, self.root / "state")
        self.store.activate_writer(old_writer_stopped=True)
        self.server = MemoryServer(self.store)
        self.initialize()
        self.counter = 10

    def initialize(self, version="2025-03-26"):
        return self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})

    def call(self, name, arguments=None):
        self.counter += 1
        return self.server.handle({"jsonrpc": "2.0", "id": self.counter, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}})["result"]

    def proposal(self, revision=0, text="An interpretation of an observation."):
        return {"records": [{"id": "sample", "title": "Example / knowledge?", "kind": "knowledge", "origin": "ai", "body": text, "sources": [{"path": "A source.md", "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(), "quote": "A dated observation."}]}], "expected_revisions": {"sample": revision}, "rationale": "Synthetic source-supported interpretation", "idempotency_key": "proposal-" + str(revision)}

    def test_protocol_negotiation_and_closed_inventory(self):
        for version in ("2024-11-05", "2025-03-26"):
            self.assertEqual(self.initialize(version)["result"]["protocolVersion"], version)
        inventory = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({t["name"] for t in inventory}, {t[0] for t in TOOLS})
        self.assertFalse(any(word in t["name"] for t in inventory for word in ("init", "backup", "shell", "config", "writer_activate")))
        self.assertTrue(all(t["inputSchema"]["additionalProperties"] is False for t in inventory))

    def test_propose_apply_read_history_and_idempotent_receipt(self):
        before = self.source.read_bytes()
        proposed = self.call("glide_propose", self.proposal())
        self.assertFalse(proposed["isError"])
        proposal_id = proposed["structuredContent"]["proposal_id"]
        args = {"proposal_id": proposal_id, "decision": "approved", "idempotency_key": "decision-1", "expected_revisions": {"sample": 0}}
        applied = self.call("glide_apply", args)["structuredContent"]
        self.assertTrue(applied["committed"])
        self.assertEqual(applied["revisions"], {"sample": 1})
        repeated = self.call("glide_apply", args)["structuredContent"]
        self.assertTrue(repeated["replayed"])
        self.assertEqual(repeated["bundle"], applied["bundle"])
        record = self.call("glide_get", {"record_id": "sample"})["structuredContent"]
        self.assertEqual(record["origin"], "ai")
        self.assertEqual(record["review"], "approved")
        history = self.call("glide_history", {"record_id": "sample"})["structuredContent"]
        self.assertEqual(len(history["results"]), 1)
        unchanged = self.call("glide_changes_since", {"cursor": applied["bundle"]})["structuredContent"]
        self.assertEqual(unchanged["results"], [])
        self.assertEqual(unchanged["next_cursor"], applied["bundle"])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(json.loads(proposed["content"][0]["text"]), proposed["structuredContent"])

    def test_optional_automatic_knowledge_flag_enforces_scope_and_durable_policy(self):
        p = self.call("glide_propose", self.proposal())["structuredContent"]
        args = {"proposal_id": p["proposal_id"], "decision": "unreviewed", "idempotency_key": "automatic-1", "expected_revisions": {"sample": 0}, "knowledge_ingestion": True}
        self.assertTrue(self.call("glide_apply", args)["isError"])
        self.store.config.update(knowledge_review="automatic", automatic_source_prefixes=["A source.md"])
        self.store._save_config()
        receipt = self.call("glide_apply", args)["structuredContent"]
        self.assertEqual("knowledge-ingestion", receipt["actor"])
        self.assertEqual("automatic", receipt["knowledge_policy"]["knowledge_review"])
        self.assertTrue(self.call("glide_apply", args)["structuredContent"]["replayed"])
        self.assertTrue(self.call("glide_apply", {**args, "decision": "approved"})["isError"])
        record = self.call("glide_get", {"record_id": "sample"})["structuredContent"]
        self.assertEqual("ai", record["origin"])
        self.assertEqual("unreviewed", record["review"])
        self.assertEqual("automatic", self.call("glide_verify")["structuredContent"]["review_settings"]["knowledge_review"])

    def test_round_trip_record_and_overlay_scope(self):
        p=self.call("glide_propose",self.proposal())["structuredContent"]
        self.call("glide_apply",{"proposal_id":p["proposal_id"],"decision":"unreviewed","idempotency_key":"initial","expected_revisions":{"sample":0}})
        record=self.call("glide_get",{"record_id":"sample"})["structuredContent"]
        record["body"]="The observation is useful but still uncertain."
        args={"records":[record],"expected_revisions":{"sample":1},"rationale":"Refine a qualified interpretation","idempotency_key":"round-trip"}
        self.assertFalse(self.call("glide_propose",args)["isError"])
        record["path"]="../../Original.md"
        self.assertTrue(self.call("glide_propose",args)["isError"])
        self.assertTrue(self.call("glide_overlay_evaluate",{"change":{"permissions":{}}})["isError"])
        self.assertTrue(self.call("glide_overlay_activate",{"change":{"retrieval_aliases":{"trial":["observation"]}},"evidence":[],"rationale":"No opt-in","idempotency_key":"not-authorized"})["isError"])

    def test_stale_review_and_rejected_decision(self):
        p = self.call("glide_propose", self.proposal())["structuredContent"]
        bad = self.call("glide_apply", {"proposal_id": p["proposal_id"], "decision": "approved", "idempotency_key": "bad-review", "expected_revisions": {"sample": 1}})
        self.assertTrue(bad["isError"])
        rejected = self.call("glide_apply", {"proposal_id": p["proposal_id"], "decision": "rejected", "idempotency_key": "rejection", "expected_revisions": {"sample": 0}})["structuredContent"]
        self.assertEqual(rejected["decision"], "rejected")
        self.assertEqual(rejected["revisions"], {})
        self.assertTrue(self.call("glide_get", {"record_id": "sample"})["isError"])

    def test_unknown_tools_kwargs_and_method_injection(self):
        for name, arguments in [("__getattribute__", {"name": "config"}), ("glide_verify", {"vault": "/"}), ("glide_search", {"query": "test", "limit": True}), ("glide_apply", {"proposal_id": "x", "decision": "approved", "idempotency_key": "x", "expected_revisions": {}, "actor": "human"})]:
            self.assertTrue(self.call(name, arguments)["isError"])
        malformed = self.proposal()
        malformed["records"][0]["path"] = "../../overwrite.md"
        self.assertTrue(self.call("glide_propose", malformed)["isError"])
        escaped_evidence = self.proposal()
        escaped_evidence["records"][0]["sources"][0]["path"] = "../../outside.md"
        self.assertTrue(self.call("glide_propose", escaped_evidence)["isError"])
        empty_key = self.proposal()
        empty_key["idempotency_key"] = ""
        self.assertTrue(self.call("glide_propose", empty_key)["isError"])
        self.assertEqual(self.server.handle({"jsonrpc": "2.0", "id": 4, "method": "store.activate_writer"})["error"]["code"], -32601)

    def test_source_read_bounds_index_and_traversal(self):
        passage = self.call("glide_read_source", {"path": "A source.md", "start_line": 2, "max_lines": 1})["structuredContent"]
        self.assertEqual(passage["text"], "A second line.")
        self.assertTrue(passage["has_more"])
        self.assertEqual(passage["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        indexed = self.call("glide_index_sources", {"paths": ["A source.md"], "idempotency_key": "source-1"})["structuredContent"]
        self.assertTrue(indexed["committed"])
        results = self.call("glide_search", {"query": "dated observation"})["structuredContent"]["results"]
        self.assertEqual(results[0]["path"], "A source.md")
        for path in ("../outside.md", str(self.source), ".private.md", "folder/../A source.md", "folder//file.md", "settings.json", "Agent HQ/Memory/Store.md"):
            self.assertTrue(self.call("glide_read_source", {"path": path})["isError"], path)
            self.assertTrue(self.call("glide_index_sources", {"paths": [path], "idempotency_key": "escape"})["isError"], path)
        outside = self.root / "outside.md"
        outside.write_text("Not in scope")
        (self.vault / "escape.md").symlink_to(outside)
        self.assertTrue(self.call("glide_read_source", {"path": "escape.md"})["isError"])
        self.assertTrue(self.call("glide_index_sources", {"paths": ["escape.md"], "idempotency_key": "symlink"})["isError"])

    def test_job_endpoints_commit_checkpoint_with_output_and_cli_matches(self):
        self.store.config.update(knowledge_review="automatic", automatic_source_prefixes=[self.source.name])
        self.store._save_config()
        self.call("glide_index_sources", {"paths": ["A source.md"], "idempotency_key": "job-source"})
        inputs = self.call("glide_job_inputs", {"job_id": "dream", "batch_limit": 1})["structuredContent"]
        self.assertTrue(inputs["has_work"])
        proposal = self.proposal()
        finished = self.call("glide_finish_job", {"job_id": "dream", "processed_through": inputs["processed_through"], "records": proposal["records"], "expected_revisions": {"sample": 0, inputs["checkpoint_id"]: inputs["checkpoint_revision"]}, "summary": "Reviewed one source and retained a qualified interpretation.", "evidence": proposal["records"][0]["sources"], "idempotency_key": "dream-finished"})
        self.assertFalse(finished["isError"], finished)
        self.assertTrue(finished["structuredContent"]["committed"])
        self.assertFalse(self.call("glide_job_inputs", {"job_id": "dream"})["structuredContent"]["has_work"])
        process = subprocess.run([sys.executable, "-m", "glide_memory", "--config", str(self.store.config_path), "job-inputs", "dream", "--batch-limit", "1"], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(json.loads(process.stdout)["has_work"])
        historical = self.call("glide_search", {"query": "observation", "recorded_at": "2999-01-01T00:00:00Z"})
        self.assertFalse(historical["isError"], historical)

    def test_protocol_errors_and_notification_cannot_mutate(self):
        before = len(list((self.store.store / "Proposals").glob("*.md")))
        notification = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "glide_propose", "arguments": self.proposal()}}
        self.assertIsNone(self.server.handle(notification))
        self.assertEqual(before, len(list((self.store.store / "Proposals").glob("*.md"))))
        self.assertEqual(self.server.handle([])["error"]["code"], -32600)
        server = MemoryServer(self.store)
        self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["error"]["code"], -32002)
        output = io.StringIO()
        serve(self.server, io.StringIO('not json\n' + json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}) + '\n'), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["result"], {})

    def test_actual_stdio_module_has_only_protocol_output(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "glide_read_source", "arguments": {"path": "A source.md"}}},
        ]
        process = subprocess.run([sys.executable, "-m", "glide_memory.bridge", "--config", str(self.store.config_path)], input="".join(json.dumps(m) + "\n" for m in messages), capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertIn("A dated observation.", responses[1]["result"]["structuredContent"]["text"])
        self.assertEqual(process.stderr, "")


if __name__ == "__main__":
    unittest.main()
