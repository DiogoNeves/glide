"""Rename recovery must prove source identity without relaxing payload integrity."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from glide_memory.store import Store, StoreError, IntegrityError, ConflictError, MARKER, obsidian_link_shape


class ObsidianRenameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        (self.vault / "References").mkdir()
        self.old = self.vault / "References/Lab.md"
        self.old.write_text("Specimen workflow.\n")
        self.sha = hashlib.sha256(self.old.read_bytes()).hexdigest()
        self.store = Store.initialize(self.vault, self.root / "state", adapter="obsidian")
        self.store.activate_writer(old_writer_stopped=True)
        source = {"path": "References/Lab.md", "sha256": self.sha, "quote": "Specimen workflow."}
        self.record = {"id": "lab", "title": "Lab context", "kind": "context", "origin": "ai",
                       "body": "Review [[Lab]] and [[Lab#Results|the results]].", "sources": [source]}
        p = self.store.propose([self.record], expected_revisions={"lab": 0}, rationale="Capture", idempotency_key="one")
        self.store.apply(p["proposal_id"])
        self.bundle = next((self.store.store / "Bundles").glob("*.md"))
        self.projection = self.store.store / self.store.get("lab")["path"]
        self.before_bundle = self.bundle.read_text()
        self.before_projection = self.projection.read_text()
        self.before = self.store.export()
        self.new = self.old.with_name("Lab (Revised).md")
        self.old.rename(self.new)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def rewrite(text):
        visible, marker, payload = text.partition(MARKER)
        visible = visible.replace("[[Lab", "[[Lab (Revised)").replace("[[References/Lab]]", "[[Lab (Revised)]]")
        return visible + marker + payload

    def test_reads_preserve_historical_meaning_and_do_not_write(self):
        self.bundle.write_text(self.rewrite(self.before_bundle))
        changed = self.bundle.read_bytes()
        self.assertEqual(self.before, self.store.export())
        self.assertEqual(changed, self.bundle.read_bytes())
        self.assertEqual("Specimen workflow.\n", self.new.read_text())

    def test_writer_recovers_bundle_and_projection_then_continues(self):
        self.bundle.write_text(self.rewrite(self.before_bundle))
        self.projection.write_text(self.rewrite(self.before_projection))
        result = self.store.verify()
        self.assertTrue(result["ok"])
        self.assertEqual(2, len(result["obsidian_link_updates"]))
        self.assertTrue(all(x["restored"] for x in result["obsidian_link_updates"]))
        self.assertEqual(self.before_bundle, self.bundle.read_text())
        self.assertEqual(self.before_projection, self.projection.read_text())
        self.assertEqual(self.before, self.store.export())
        self.assertEqual(2, len(list((self.store.state_dir / "rename-recovery").glob("*.md"))))
        self.assertEqual([], self.store.verify()["obsidian_link_updates"])
        p = self.store.propose([{**self.record, "body": "Next observation."}], expected_revisions={"lab": 1}, rationale="Continue", idempotency_key="two")
        self.store.apply(p["proposal_id"])
        self.assertEqual(2, self.store.get("lab")["revision"])
        self.assertTrue(self.new.exists())
        self.assertFalse(self.old.exists())

    def test_read_only_instance_leaves_presentations_untouched(self):
        self.bundle.write_text(self.rewrite(self.before_bundle))
        changed = self.bundle.read_bytes()
        self.store.config["writer_active"] = False
        result = self.store.verify()
        self.assertFalse(result["obsidian_link_updates"][0]["restored"])
        self.assertEqual(changed, self.bundle.read_bytes())
        self.assertFalse((self.store.state_dir / "rename-recovery").exists())

    def test_changed_destination_is_not_a_verified_rename(self):
        self.new.write_text("Different source.\n")
        self.bundle.write_text(self.rewrite(self.before_bundle))
        with self.assertRaises(IntegrityError):
            self.store.verify()

    def test_copy_or_ambiguous_basename_is_not_a_verified_rename(self):
        self.bundle.write_text(self.rewrite(self.before_bundle))
        self.old.write_text(self.new.read_text())
        with self.assertRaises(IntegrityError):
            self.store.verify()
        self.old.unlink()
        (self.vault / self.new.name).write_text(self.new.read_text())
        with self.assertRaises(IntegrityError):
            self.store.verify()

    def test_non_navigation_edits_fail_closed(self):
        for before, after in [
            ("Review ", "Ignore "),
            ("#Results", "#Other"),
            ("|the results", "|new claim"),
            ('"origin": "ai"', '"origin": "human"'),
        ]:
            with self.subTest(edit=before):
                text = self.rewrite(self.before_bundle)
                self.assertIn(before, text)
                self.bundle.write_text(text.replace(before, after, 1))
                with self.assertRaises(IntegrityError):
                    self.store.verify()
        self.bundle.write_text(self.before_bundle)

    def test_projection_prose_is_never_overwritten(self):
        bad = self.rewrite(self.before_projection).replace("Review ", "Ignore ")
        self.projection.write_text(bad)
        with self.assertRaises(ConflictError):
            self.store.verify()
        self.assertEqual(bad, self.projection.read_text())

    def test_generic_adapter_does_not_allow_link_rewrites(self):
        self.bundle.write_text(self.rewrite(self.before_bundle))
        self.store.adapter = "markdown"
        with self.assertRaises(IntegrityError):
            self.store.verify()

    def test_pending_proposal_keeps_exact_approval_payload(self):
        p = self.store.propose([{**self.record, "body": "Continue [[Lab]]."}], expected_revisions={"lab": 1}, rationale="Review", idempotency_key="pending")
        path = self.store.store / "Proposals" / (p["proposal_id"] + ".md")
        path.write_text(self.rewrite(path.read_text()))
        self.store.apply(p["proposal_id"])
        self.assertEqual("Continue [[Lab]].", self.store.get("lab")["body"])

    def test_symlink_destination_is_rejected(self):
        real = self.root / "outside.md"
        self.new.rename(real)
        self.new.symlink_to(real)
        self.bundle.write_text(self.rewrite(self.before_bundle))
        with self.assertRaises(StoreError):
            self.store.verify()

    def test_code_and_payload_text_cannot_be_masked(self):
        for code in ["\u0060[[Lab]]\u0060", "    [[Lab]]", "\u0060\u0060\u0060md\n[[Lab]]\n\u0060\u0060\u0060", "> ~~~\n> [[Lab]]\n> ~~~", MARKER + '"[[Lab]]"\n\u0060\u0060\u0060']:
            self.assertNotEqual(obsidian_link_shape(code), obsidian_link_shape(code.replace("Lab", "Changed")))


if __name__ == "__main__":
    unittest.main()
