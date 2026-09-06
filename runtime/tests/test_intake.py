import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone

from glide_memory.intake import scan_markdown_sources, scan_project_activity


class MarkdownIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "vault"
        self.root.mkdir()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_incremental_hashes_and_original_bytes(self):
        original = self.write("A thought.md", "A dated thought with [[connections]].\n")
        before = original.read_bytes()
        legacy = self.write("Agent HQ/Old ledger.md", "Old agent interpretation.")
        self.write("Agent HQ/Memory/Knowledge/Derived.md", "Never a source")
        self.write("Glide HQ/Memory/History/change.md", "Never a source")
        self.write(".hidden/Secret.md", "Never a source")
        self.write("run.py", "print('not a source')")
        first = scan_markdown_sources(self.root)
        self.assertEqual({s["path"] for s in first["sources"]}, {"A thought.md", "Agent HQ/Old ledger.md"})
        self.assertEqual(first["sources"][0]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(next(s for s in first["sources"] if s["path"].startswith("Agent HQ"))["source_kind"], "legacy-agent-context")
        self.assertEqual(original.read_bytes(), before)
        second = scan_markdown_sources(self.root, first["next_cursor"])
        self.assertEqual(second["sources"], [])
        self.assertEqual(second["coverage"]["unchanged"], 2)
        original.write_text("A revised thought.")
        third = scan_markdown_sources(self.root, second["next_cursor"])
        self.assertEqual([s["path"] for s in third["sources"]], ["A thought.md"])
        self.assertEqual(third["sources"][0]["source_id"], first["sources"][0]["source_id"])
        legacy.unlink()
        fourth = scan_markdown_sources(self.root, third["next_cursor"])
        self.assertEqual(fourth["deletions"], ["Agent HQ/Old ledger.md"])

    def test_oversize_binary_and_symlinks_are_coverage_gaps(self):
        self.write("regular.md", "unchanged")
        before = scan_markdown_sources(self.root)
        (self.root / "regular.md").unlink()
        self.write("large.md", "x" * 100)
        (self.root / "binary.md").write_bytes(b"some\x00binary")
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        outside_note = outside / "Foreign.md"
        outside_note.write_text("must not read or modify")
        (self.root / "Linked.md").symlink_to(outside_note)
        (self.root / "foreign").symlink_to(outside, target_is_directory=True)
        result = scan_markdown_sources(self.root, before["next_cursor"], max_bytes=50)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["deletions"], [])
        self.assertEqual(result["coverage"]["status"], "partial")
        self.assertEqual(len(result["coverage"]["unavailable"]), 4)
        self.assertEqual(outside_note.read_text(), "must not read or modify")
        self.assertIn("regular.md", result["next_cursor"]["sources"])

    def test_restarting_unaccepted_scan_returns_identical_source_ids(self):
        self.write("idea.md", "a useful idea")
        first = scan_markdown_sources(self.root)
        restarted = scan_markdown_sources(self.root)
        self.assertEqual(first["sources"], restarted["sources"])

    def test_generated_memory_cannot_be_enabled_by_custom_exclusions(self):
        self.write("Agent HQ/Memory/Now.md", "Generated text")
        self.write("private/Ignore.md", "Excluded text")
        result = scan_markdown_sources(self.root, excluded_roots=["private"])
        self.assertEqual(result["sources"], [])
        with self.assertRaises(ValueError):
            scan_markdown_sources(self.root, excluded_roots=["../outside"])


class ProjectIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index = self.root / "index"
        (self.index / "projects").mkdir(parents=True)
        # Shell metacharacters are literal paths, never evaluated by intake.
        self.repository = self.root / "a repo $(touch SHOULD_NOT_EXIST)"
        self.repository.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Synthetic Author")
        self.git("config", "user.email", "synthetic@example.invalid")
        self.git("remote", "add", "origin", "git@github.com:Example/Project.git")
        self.write_index("example", self.repository)

    def git(self, *args, date=None):
        env = dict(os.environ)
        if date:
            env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        result = subprocess.run(["git", "-C", str(self.repository), *args], capture_output=True, text=True, check=True, env=env)
        return result.stdout.strip()

    def commit(self, name, text, date="2026-09-05T10:00:00+00:00"):
        (self.repository / name).write_text(text)
        self.git("add", "--", name)
        self.git("commit", "-m", text, date=date)
        return self.git("rev-parse", "HEAD")

    def write_index(self, name, path, description="A description that is not progress."):
        entry = self.index / "projects" / (name + ".md")
        entry.write_text(f"# {name}\n\n- GitHub: https://github.com/Example/Project\n- Local path: `{path}`\n\n## What it does\n{description}\n")
        return entry

    def scan(self, cursor=None, **kwargs):
        return scan_project_activity(self.index, cursor, now=datetime(2026, 9, 6, tzinfo=timezone.utc), **kwargs)

    def test_all_branches_exact_refs_dedupe_and_read_only(self):
        main_commit = self.commit("main.txt", "Main work")
        self.git("switch", "-c", "feature")
        feature_commit = self.commit("feature.txt", "Feature work")
        self.git("switch", "main")
        # A second project-index entry must not duplicate repository activity.
        self.write_index("alias", self.repository)
        before_status = self.git("status", "--porcelain=v1")
        before_index = (self.repository / ".git/index").read_bytes()
        first = self.scan()
        self.assertEqual({e["commit"] for e in first["events"]}, {main_commit, feature_commit})
        event = next(e for e in first["events"] if e["commit"] == feature_commit)
        self.assertIn("refs/heads/feature", event["refs"])
        self.assertEqual(event["url"], f"https://github.com/example/project/commit/{feature_commit}")
        self.assertTrue(event["source_ref"].endswith("@" + feature_commit))
        self.assertNotIn("description", str(first["events"]))
        self.assertEqual(self.git("status", "--porcelain=v1"), before_status)
        self.assertEqual((self.repository / ".git/index").read_bytes(), before_index)
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        second = self.scan(first["next_cursor"])
        self.assertEqual(second["events"], [])
        self.assertIn("duplicate-mapping", [c["status"] for c in second["coverage"]])

    def test_missing_clone_and_non_repo_are_unavailable_not_unchanged(self):
        self.write_index("missing", self.root / "missing")
        self.write_index("not-repo", self.root)
        self.write_index("remote", "(not cloned)")
        result = self.scan()
        statuses = {c["index_path"]: c["status"] for c in result["coverage"]}
        self.assertEqual(statuses["projects/missing.md"], "unavailable")
        self.assertEqual(statuses["projects/not-repo.md"], "unavailable")
        self.assertEqual(statuses["projects/remote.md"], "unavailable")
        self.assertEqual(result["events"], [])

    def test_partial_batch_resumes_without_skipping_ancestral_commits(self):
        commits = {self.commit(f"file-{i}", f"Change {i}") for i in range(4)}
        first = self.scan(max_commits=2)
        self.assertEqual(first["coverage"][0]["status"], "partial")
        second = self.scan(first["next_cursor"], max_commits=2)
        self.assertEqual(second["coverage"][0]["status"], "complete")
        self.assertEqual({e["commit"] for e in first["events"] + second["events"]}, commits)
        self.assertEqual(len({e["event_id"] for e in first["events"] + second["events"]}), 4)
        self.assertEqual(self.scan(second["next_cursor"])["events"], [])
        self.assertEqual(self.scan(max_commits=2)["events"], first["events"])

    def test_initial_lookback_then_new_backdated_commit(self):
        old = self.commit("old", "Old work", date="2020-01-01T10:00:00+00:00")
        first = self.scan(lookback_days=7)
        self.assertEqual(first["events"], [])
        backdated = self.commit("new", "Newly observed backdated commit", date="2020-01-02T10:00:00+00:00")
        second = self.scan(first["next_cursor"], lookback_days=7)
        self.assertEqual([e["commit"] for e in second["events"]], [backdated])
        self.assertNotIn(old, [e["commit"] for e in second["events"]])

    def test_index_symlink_never_reads_external_mapping(self):
        (self.index / "projects/example.md").unlink()
        foreign = self.root / "foreign.md"
        foreign.write_text(f"- Local path: {self.repository}\n")
        (self.index / "projects/linked.md").symlink_to(foreign)
        before = foreign.read_bytes()
        result = self.scan()
        self.assertEqual(result["events"], [])
        self.assertEqual(result["coverage"][0]["status"], "unavailable")
        self.assertEqual(foreign.read_bytes(), before)

    def test_private_remote_credentials_never_appear_in_events(self):
        self.git("remote", "set-url", "origin", "https://username:SECRET_TOKEN@github.com/Example/Project.git")
        self.commit("one", "One change")
        result = self.scan()
        self.assertEqual(len(result["events"]), 1)
        self.assertNotIn("SECRET_TOKEN", str(result))
        self.assertNotIn("username", str(result))

    def test_two_clones_of_one_origin_include_local_commits_from_each(self):
        shared = self.commit("shared", "Shared work")
        other = self.root / "other-clone"
        subprocess.run(["git", "clone", str(self.repository), str(other)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(other), "remote", "set-url", "origin", "https://github.com/Example/Project.git"], check=True)
        self.write_index("other", other)
        original_repo = self.repository
        first_local = self.commit("first", "First clone work")
        self.repository = other
        self.git("config", "user.name", "Synthetic Author")
        self.git("config", "user.email", "synthetic@example.invalid")
        second_local = self.commit("second", "Second clone work")
        self.repository = original_repo
        first = self.scan()
        self.assertEqual({e["commit"] for e in first["events"]}, {shared, first_local, second_local})
        self.assertEqual(len(first["events"]), 3)
        self.assertEqual(len({e["repo_id"] for e in first["events"]}), 1)
        self.assertEqual(self.scan(first["next_cursor"])["events"], [])


if __name__ == "__main__":
    unittest.main()
