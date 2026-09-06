from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from glide_memory.pipeline import PROJECT_STATE_ID, SOURCE_STATE_ID, _read_state, load_intake_config, run_pipeline
from glide_memory.store import Store, StoreError


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="glide-pipeline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.source = self.vault / "A historical thought.md"
        self.source.write_text("I value a surface that helps me think.\n")
        self.original_bytes = self.source.read_bytes()
        self.store = Store.initialize(self.vault, self.root / "state")
        self.store.activate_writer(old_writer_stopped=True)
        self.index = self.root / "project-index"
        (self.index / "projects").mkdir(parents=True)
        self.repository = self.root / "project"
        self.repository.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Synthetic")
        self.git("config", "user.email", "synthetic@example.invalid")
        self.git("remote", "add", "origin", "https://github.com/example/synthetic.git")
        (self.index / "projects/project.md").write_text(f"# Synthetic project\n- GitHub: https://github.com/example/synthetic\n- Local path: {self.repository}\n\n## What it does\nA promotional description is not a progress event.\n")
        self.moment = datetime(2026, 9, 6, tzinfo=timezone.utc)

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original_bytes)

    def git(self, *args):
        env = dict(os.environ)
        env.update(GIT_AUTHOR_DATE="2026-09-05T10:00:00+00:00", GIT_COMMITTER_DATE="2026-09-05T10:00:00+00:00")
        return subprocess.run(["git", "-C", str(self.repository), *args], capture_output=True, text=True, check=True, env=env).stdout.strip()

    def commit(self, number):
        (self.repository / f"file-{number}").write_text(f"Change {number}")
        self.git("add", "--", f"file-{number}")
        self.git("commit", "-m", f"Implement synthetic change {number}")
        return self.git("rev-parse", "HEAD")

    def run_sources(self, **config):
        return run_pipeline(self.store, config, projects=False, now=self.moment)["results"]["sources"]

    def run_projects(self, **config):
        return run_pipeline(self.store, {"project_index_root": str(self.index), **config}, sources=False, now=self.moment)["results"]["projects"]

    def test_source_batches_reconstruct_cursor_and_no_change_is_write_free(self):
        for i in range(4):
            (self.vault / f"Note {i}.md").write_text(f"Original {i}")
        first = self.run_sources(source_batch_size=2)
        self.assertEqual(first["registered"], 2)
        self.assertEqual(first["pending"], 3)
        self.assertEqual(len(self.store.export()["sources"]), 2)
        second = self.run_sources(source_batch_size=2)
        self.assertEqual(second["registered"], 2)
        self.assertEqual(second["pending"], 1)
        third = self.run_sources(source_batch_size=2)
        self.assertEqual(third["registered"], 1)
        self.assertEqual(third["status"], "complete")
        self.assertEqual(len(self.store.export()["sources"]), 5)
        before = self.store.export()
        self.assertEqual(self.run_sources(source_batch_size=2)["status"], "no-change")
        self.assertEqual(self.store.export(), before)
        self.assertTrue(all(not s["path"].startswith("Agent HQ/Memory") for s in before["sources"]))
        self.store.db_path.unlink()
        self.assertEqual(self.run_sources(source_batch_size=2)["status"], "no-change")
        self.assertEqual(self.store.export(), before)

    def test_failure_after_source_commit_does_not_skip_pending_data(self):
        (self.vault / "Z second.md").write_text("Second source")
        with mock.patch.object(self.store, "apply", side_effect=RuntimeError("interrupted before coverage summary")):
            with self.assertRaises(RuntimeError):
                self.run_sources(source_batch_size=1)
        self.assertEqual(len(self.store.export()["sources"]), 1)
        resumed = self.run_sources(source_batch_size=1)
        self.assertEqual(resumed["registered"], 1)
        self.assertEqual(len(self.store.export()["sources"]), 2)
        self.assertEqual(self.run_sources(source_batch_size=1)["status"], "no-change")

    def test_missing_source_and_coverage_gap_are_retained_without_deleting_evidence(self):
        extra = self.vault / "Temporary thought.md"
        extra.write_text("A historical source may disappear.")
        self.run_sources()
        extra.unlink()
        missing = self.run_sources()
        self.assertEqual(missing["coverage"]["missing"], ["Temporary thought.md"])
        self.assertEqual(len(self.store.export()["sources"]), 2)
        (self.vault / "Oversize.md").write_text("x" * 100)
        partial = self.run_sources(source_max_bytes=60)
        self.assertEqual(partial["status"], "partial")
        self.assertIn("Oversize.md", [s["path"] for s in partial["coverage"]["unavailable"]])
        repeated = self.run_sources(source_max_bytes=60)
        self.assertEqual(repeated["status"], "partial")
        self.assertIsNone(repeated["summary_receipt"])

    def test_project_cursor_and_monthly_activity_commit_together(self):
        commits = {self.commit(i) for i in range(3)}
        first = self.run_projects(project_max_commits=2)
        self.assertEqual(first["events"], 2)
        self.assertEqual(first["status"], "partial")
        state = _read_state(self.store.get(PROJECT_STATE_ID))
        cursor = state["cursor"]
        self.assertEqual(sum(len(r["seen_commits"]) for r in cursor["repositories"].values()), 2)
        self.assertEqual(len(first["activity_records"]), 1)
        same_bundle = self.store.history()[-1]
        self.assertEqual(set(same_bundle["records"]), {PROJECT_STATE_ID, *first["activity_records"]})
        second = self.run_projects(project_max_commits=2)
        self.assertEqual(second["events"], 1)
        activity = self.store.get(first["activity_records"][0])
        events = _read_state(activity)["events"]
        self.assertEqual({e["commit"] for e in events}, commits)
        self.assertEqual(len(activity["sources"]), 3)
        self.assertTrue(all(e["uri"].startswith("https://github.com/example/synthetic/commit/") for e in activity["sources"]))
        self.assertNotIn("promotional", activity["body"])
        before = self.store.export()
        self.assertEqual(self.run_projects(project_max_commits=2)["status"], "no-change")
        self.assertEqual(self.store.export(), before)

    def test_project_apply_failure_keeps_cursor_unadvanced(self):
        commit = self.commit(1)
        with mock.patch.object(self.store, "apply", side_effect=RuntimeError("interrupted before durable commit")):
            with self.assertRaises(RuntimeError):
                self.run_projects()
        self.assertEqual(self.store.export()["records"], [])
        resumed = self.run_projects()
        self.assertEqual(resumed["events"], 1)
        activity = self.store.get(resumed["activity_records"][0])
        self.assertEqual(_read_state(activity)["events"][0]["commit"], commit)
        self.assertEqual(self.run_projects()["events"], 0)

    def test_project_publication_failure_is_visible_and_recovers_without_duplicates(self):
        self.commit(1)
        with mock.patch.object(self.store, "_publish", side_effect=OSError("publication interrupted")):
            failed = self.run_projects()
        self.assertEqual(failed["status"], "publication-pending")
        self.assertTrue(failed["receipt"]["committed"])
        resumed = self.run_projects()
        self.assertEqual(resumed["events"], 0)
        self.assertEqual(resumed["status"], "no-change")
        self.assertTrue(self.store.verify()["ok"])

    def test_unavailable_repository_is_not_successful_no_change(self):
        (self.index / "projects/missing.md").write_text("- Local path: /missing-synthetic-project\n")
        first = self.run_projects()
        self.assertEqual(first["status"], "partial")
        self.assertTrue(any(c["status"] == "unavailable" for c in first["coverage"]))
        before = self.store.export()
        second = self.run_projects()
        self.assertEqual(second["status"], "partial")
        self.assertIsNone(second["receipt"])
        self.assertEqual(self.store.export(), before)

    def test_private_config_is_off_vault_and_source_integrity_is_verified(self):
        config_file = self.store.state_dir / "intake.json"
        config_file.write_text(json.dumps({"project_index_root": str(self.index), "source_batch_size": 1}))
        config = load_intake_config(self.store)
        self.assertEqual(config["project_index_root"], str(self.index))
        self.assertEqual(config["source_batch_size"], 1)
        with self.assertRaises(StoreError):
            load_intake_config(self.store, self.vault / "config.json")
        with self.assertRaises(StoreError):
            run_pipeline(self.store, {"project_index_root": str(self.vault)})
        result = run_pipeline(self.store, config, projects=False)
        source = self.store.export()["sources"][0]
        self.assertEqual(source["sha256"], hashlib.sha256(self.original_bytes).hexdigest())
        self.assertEqual(source["source_kind"], "original-markdown")
        self.assertEqual(source["trust"], "source-only")
        self.assertEqual(result["results"]["sources"]["registered"], 1)


if __name__ == "__main__":
    unittest.main()
