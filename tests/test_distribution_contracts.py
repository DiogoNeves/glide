import hashlib
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import unquote


TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import distribute_contracts as renderer
import check_distribution as checker


class DistributionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_all_editions_render_deterministically_with_resolved_paths(self):
        for edition, hq in renderer.EDITIONS.items():
            target = self.root / edition
            first = renderer.write(target, edition)
            self.assertTrue(first["ok"])
            paths = list(target.rglob("*.md"))
            snapshot = {str(p): p.read_bytes() for p in paths}
            self.assertEqual(2, len(paths))
            self.assertTrue(renderer.write(target, edition)["ok"])
            self.assertEqual(snapshot, {str(p): p.read_bytes() for p in paths})
            self.assertIn(hq + "/Memory/Bundles/", paths[0].read_text() + paths[1].read_text())
            self.assertNotIn("{{HQ}}", paths[0].read_text() + paths[1].read_text())

    def test_check_is_read_only_and_detects_missing_or_changed_outputs(self):
        self.assertFalse(renderer.check(self.root, "glide")["ok"])
        self.assertEqual([], list(self.root.iterdir()))
        renderer.write(self.root, "glide")
        path = next(self.root.rglob("Memory Core.md"))
        path.write_text(path.read_text() + "\nOwner addition.\n")
        before = path.read_bytes()
        self.assertFalse(renderer.check(self.root, "glide")["ok"])
        self.assertEqual(before, path.read_bytes())
        with self.assertRaisesRegex(ValueError, "local edits"):
            renderer.write(self.root, "glide")
        self.assertEqual(before, path.read_bytes())

    def test_unowned_target_or_symlink_is_never_overwritten(self):
        path = self.root / "templates/Glide HQ/Contracts/Recovery Core.md"
        path.parent.mkdir(parents=True)
        path.write_text("Existing owner document.")
        with self.assertRaisesRegex(ValueError, "unowned"):
            renderer.write(self.root, "glide")
        self.assertFalse(path.with_name("Memory Core.md").exists())
        other = self.root / "other"
        other.mkdir()
        link = self.root / "linked"
        link.symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError):
            renderer.write(link, "glide")
        self.assertEqual([], list(other.iterdir()))

    def fixture(self):
        pin = {"version": "0.1.0", "build": "12345678abcd"}
        (self.root / "examples").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "compatibility.json").write_text(json.dumps({"distribution": "glide", "optional_memory_runtime": pin}))
        (self.root / "examples/install-manifest.example.json").write_text(json.dumps({"runtime": pin}))
        for relative in ("INSTALL.md", "docs/SETUP.md", "docs/COMPATIBILITY.md", "docs/UPGRADING.md", "docs/MEMORY-RUNTIME.md"):
            (self.root / relative).write_text("Use --expected-build 12345678abcd.")
        renderer.write(self.root, "glide")

    def test_stale_example_and_document_commands_fail_the_distribution_gate(self):
        self.fixture()
        self.assertTrue(checker.verify(self.root)["ok"])
        path = self.root / "examples/install-manifest.example.json"
        path.write_text(json.dumps({"runtime": {"version": "0.1.0", "build": "df711b913f09"}}))
        with self.assertRaisesRegex(ValueError, "example"):
            checker.verify(self.root)
        path.write_text(json.dumps({"runtime": {"version": "0.1.0", "build": "12345678abcd"}}))
        (self.root / "docs/SETUP.md").write_text("Use --expected-build df711b913f09.")
        with self.assertRaisesRegex(ValueError, "SETUP"):
            checker.verify(self.root)

    def test_companion_pairing_manifest_and_code_constant_cannot_drift(self):
        self.fixture()
        companion = self.root / "daily_notes"
        package = companion / "package-manifest.json"
        init = companion / "glide_obsidian/__init__.py"
        init.parent.mkdir(parents=True)
        package.write_text(json.dumps({"required_runtime_build": "12345678abcd"}))
        init.write_text('REQUIRED_RUNTIME_BUILD = "12345678abcd"\n')
        self.assertTrue(checker.verify(self.root)["ok"])
        package.write_text(json.dumps({"required_runtime_build": "df711b913f09"}))
        with self.assertRaisesRegex(ValueError, "pairing"):
            checker.verify(self.root)
        package.write_text(json.dumps({"required_runtime_build": "12345678abcd"}))
        init.write_text('REQUIRED_RUNTIME_BUILD = "df711b913f09"\n')
        with self.assertRaisesRegex(ValueError, "pairing"):
            checker.verify(self.root)

    def test_core_entrypoints_reach_all_workflows_and_existing_files(self):
        root = Path(__file__).parents[1]
        hq = root / "templates/Glide HQ"
        for name in ("AGENTS.md", "Operating Manual.md", "Communication Preferences.md",
                     "Memory Protocol.md", "Checklists/Recovery.md"):
            path = hq / name
            text = path.read_text()
            links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
            for link in links:
                if "://" not in link:
                    self.assertTrue((path.parent / unquote(link.split("#", 1)[0])).is_file(), link)
            for relative in re.findall(r"`([^`]+\.md)`", text):
                self.assertTrue((hq / relative).is_file(), relative)
        routes = re.findall(r"\]\((Checklists/[^)]+)\)", (hq / "Operating Manual.md").read_text())
        expected_routes = {"Company Context Setup.md", "Update Company Context.md",
                           "Daily Founder Check-In.md", "Weekly CEO Review.md",
                           "Follow-Through Review.md", "Decision Packet.md", "Area Review.md",
                           "Nightly Founder Research Review.md", "Glide Update Check.md",
                           "Founder Drift Review.md", "Input and Collaboration.md"}
        self.assertEqual(expected_routes, {Path(unquote(route)).name for route in routes})
        self.assertEqual(len(expected_routes), len(routes))
        expected = {"glide-check-for-updates", "glide-conversation-learning", "glide-create-area",
                    "glide-create-company-context", "glide-create-decision-packet",
                    "glide-daily-founder-check-in", "glide-deep-research-subject",
                    "glide-detect-contradictions", "glide-dream", "glide-follow-through-review",
                    "glide-founder-drift-review", "glide-integrity", "glide-memory",
                    "glide-nightly-founder-research-review", "glide-review", "glide-run-area-review",
                    "glide-update-company-context", "glide-weekly-ceo-review"}
        self.assertEqual(expected, {p.parent.name for p in (root / "skills").glob("*/SKILL.md")})

    def test_original_reference_content_and_protected_principles_are_preserved(self):
        hq = Path(__file__).parents[1] / "templates/Glide HQ"
        expected = {
            "Reference/AGENTS.md": "3234f07cd2755455e468e80ed7c7f9e1921e571f7f80e6c8b27bd293dbb3386f",
            "Reference/Operating Manual.md": "279ecb2e87a04e8c3361ae56a2e23a1dfff715935e537707ee6eab04ddede236",
            "Reference/Communication Preferences.md": "f7bbe66bd4761d083cd6830db3a234ecae1ad2bc9235e98a31d2d611bc9d996a",
            "Reference/Memory Protocol.md": "0e82cda10af3aafa121e351330817dfd4205d8023c9d01e236c9807dd815ca2e",
            "Reference/Recovery.md": "8c7a45b5e8d55d55d58d120aab4d14e047a892bb2d034c976725e61bc7a4e73d",
            "Harness Design Principles.md": "188d6cb4de607b1d0d1c36e5066601df40221cad5ad9e7f5b96572132aa2e02d"}
        for relative, digest in expected.items():
            self.assertEqual(digest, hashlib.sha256((hq / relative).read_bytes()).hexdigest(), relative)

    def test_actual_owner_contracts_and_active_build_references_match(self):
        self.assertTrue(checker.verify(Path(__file__).parents[1])["ok"])
