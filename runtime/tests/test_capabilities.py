import json
import unittest
from unittest import mock

import test_bridge
from glide_memory.bridge import MemoryServer, TOOLS, TOOL_CAPABILITIES, obj


LEGACY_TOOLS = {"glide_search", "glide_get", "glide_history", "glide_changes_since",
    "glide_propose", "glide_apply", "glide_verify", "glide_read_source", "glide_index_sources",
    "glide_intake", "glide_apple_notes_metadata", "glide_apple_notes_export", "glide_capture_export",
    "glide_voice_memos_sync", "glide_job_inputs", "glide_job_input_page", "glide_finish_job",
    "glide_overlay_evaluate", "glide_overlay_activate", "glide_overlay_rollback"}


class CapabilityTests(unittest.TestCase):
    setUp = test_bridge.BridgeTest.setUp
    initialize = test_bridge.BridgeTest.initialize
    call = test_bridge.BridgeTest.call
    proposal = test_bridge.BridgeTest.proposal

    def configure(self, value):
        config = json.loads(self.store.config_path.read_text())
        config["tool_capabilities"] = value
        self.store.config_path.write_text(json.dumps(config))

    def inventory(self):
        return self.server.handle({"jsonrpc": "2.0", "id": 90, "method": "tools/list"})

    def test_omitted_profile_preserves_exact_legacy_inventory(self):
        self.assertEqual(LEGACY_TOOLS, {tool[0] for tool in TOOLS})
        self.assertEqual(LEGACY_TOOLS, {tool["name"] for tool in self.inventory()["result"]["tools"]})
        self.assertNotIn("tool_capabilities", self.store.config)
        self.assertEqual(LEGACY_TOOLS, set().union(*TOOL_CAPABILITIES.values()))

    def test_reader_profile_rejects_direct_mutations_before_dispatch(self):
        self.configure(["reader"])
        self.assertEqual(TOOL_CAPABILITIES["reader"], {tool["name"] for tool in self.inventory()["result"]["tools"]})
        before = self.store.export()
        with mock.patch("glide_memory.bridge.voice_memos_sync", side_effect=AssertionError("disabled helper invoked")) as helper:
            self.assertTrue(self.call("glide_voice_memos_sync")["isError"])
            helper.assert_not_called()
        self.assertTrue(self.call("glide_propose", self.proposal())["isError"])
        self.assertTrue(self.call("glide_finish_job", {"job_id": "daily"})["isError"])
        self.assertFalse(self.call("glide_read_source", {"path": self.source.name})["isError"])
        self.assertEqual(before, self.store.export())

    def test_narrowing_is_enforced_by_existing_process_and_empty_profile_denies_all(self):
        self.assertFalse(self.call("glide_job_inputs", {"job_id": "daily"})["isError"])
        self.configure(["reader"])
        self.assertTrue(self.call("glide_job_inputs", {"job_id": "daily"})["isError"])
        self.configure([])
        self.assertEqual([], self.inventory()["result"]["tools"])
        for name in LEGACY_TOOLS:
            self.assertTrue(self.call(name)["isError"])

    def test_unknown_duplicate_or_wrong_type_profile_fails_closed(self):
        before = self.store.export()
        for profile in (None, "reader", ["reader", "reader"], ["shell"], [1], {"reader": True}):
            with self.subTest(profile=profile):
                self.configure(profile)
                with self.assertRaises(ValueError):
                    MemoryServer(self.store)
                self.assertIn("error", self.inventory())
                self.assertTrue(self.call("glide_propose", self.proposal())["isError"])
        self.assertEqual(before, self.store.export())

    def test_fixed_adapter_extension_is_also_filtered_and_validated(self):
        class Adapter(MemoryServer):
            def tool_inventory(self):
                return [*super().tool_inventory(), ("glide_test_extra", "Synthetic adapter read", obj(), True)]
            def capability_groups(self):
                return {**super().capability_groups(), "test_extra": {"glide_test_extra"}}
            def call_tool(self, name, arguments):
                self.validate_call(name, arguments)
                if name == "glide_test_extra":
                    return {"synthetic": True}
                return super().call_tool(name, arguments)
        self.server = Adapter(self.store)
        self.initialize()
        self.assertEqual(21, len(self.inventory()["result"]["tools"]))
        self.configure(["test_extra"])
        self.assertEqual(["glide_test_extra"], [tool["name"] for tool in self.inventory()["result"]["tools"]])
        self.assertFalse(self.call("glide_test_extra")["isError"])
        self.assertTrue(self.call("glide_test_extra", {"shell": "ignored"})["isError"])
        self.configure(["reader"])
        self.assertTrue(self.call("glide_test_extra")["isError"])

    def test_bounded_broker_read_rejects_partial_round_trip(self):
        proposed = self.call("glide_propose", self.proposal(text="First.\nSecond.\n"))["structuredContent"]
        self.call("glide_apply", {"proposal_id": proposed["proposal_id"], "decision": "unreviewed",
                  "idempotency_key": "initial", "expected_revisions": {"sample": 0}})
        page = self.call("glide_get", {"record_id": "sample", "max_lines": 1})["structuredContent"]
        self.assertEqual("First.\n", page["body"])
        self.assertTrue(self.call("glide_propose", {"records": [page], "expected_revisions": {"sample": 1},
            "rationale": "Must expand", "idempotency_key": "partial"})["isError"])
        full = self.call("glide_get", page["read_window"]["full_args"])["structuredContent"]
        self.assertEqual("First.\nSecond.", full["body"])
