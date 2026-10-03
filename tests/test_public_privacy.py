import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("public_privacy", Path(__file__).resolve().parents[1] / "tools/check_public_privacy.py")
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)

class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()

    def findings(self, body, terms=()):
        (self.root / "example.md").write_text(body)
        return privacy.audit(self.root, ["example.md"], terms)

    def test_email_and_home_path_tripwires_do_not_echo_matches(self):
        email = "owner" + "@" + "company" + ".com"
        home = "/" + "Users" + "/" + "person/private"
        findings = self.findings(email + "\n" + home)
        self.assertEqual({f["kind"] for f in findings}, {"email-address", "identifying-home-path"})
        self.assertNotIn(email, json.dumps(findings))
        self.assertNotIn(home, json.dumps(findings))

    def test_reserved_examples_and_git_remotes_remain_usable(self):
        body = "\n".join(["synthetic@example.invalid", "person@example.com", "git@github.com:Example/Project.git"]) + "\n"
        body += "https://username:SECRET_TOKEN@github.com/Example/Project.git\n"
        body += "/" + "Users" + "/" + "example/private.txt\n"
        self.assertEqual(self.findings(body), [])

    def test_private_terms_and_markers_are_checked_without_echo(self):
        private = "Fictional" + " Owner"
        marker = " ".join(["BEGIN", "PRIVATE", "DATA"])
        findings = self.findings(private + "\n" + marker, [private.casefold()])
        self.assertEqual({f["kind"] for f in findings}, {"private-or-owner-identifier", "private-data-marker"})
        self.assertNotIn(private, json.dumps(findings))

    def test_private_denylist_must_stay_outside_repository(self):
        inside = self.root / "denylist.json"
        inside.write_text('["synthetic term"]')
        with self.assertRaises(ValueError):
            privacy.private_terms(inside, self.root)
        outside = self.root.parent / "private.json"
        outside.write_text('["synthetic term"]')
        self.assertEqual(privacy.private_terms(outside, self.root), ["synthetic term"])
        outside.write_text('{"incorrect":"shape"}')
        with self.assertRaises(ValueError):
            privacy.private_terms(outside, self.root)

    def test_private_artifacts_and_symlinks_are_rejected(self):
        (self.root / ".env").write_text("PLACEHOLDER")
        (self.root / "index.sqlite3").write_bytes(b"\0binary")
        (self.root / "link").symlink_to(self.root.parent)
        findings = privacy.audit(self.root, [".env", "index.sqlite3", "link", "../escape"])
        self.assertEqual({f["kind"] for f in findings}, {"private-or-generated-artifact", "symlink-or-escape", "unsafe-path"})

    def test_private_keys_and_common_token_prefixes_are_rejected(self):
        credentials = [
            "-----" + "BEGIN PRIVATE KEY" + "-----",
            "-----" + "BEGIN OPENSSH PRIVATE KEY" + "-----",
            "gh" + "p_" + "a" * 24,
            "github_" + "pat_" + "b" * 32,
            "sk-" + "proj-" + "c" * 24,
            "xo" + "xb-" + "d" * 24,
            "AK" + "IA" + "E" * 16,
        ]
        for credential in credentials:
            findings = self.findings(credential)
            self.assertEqual({f["kind"] for f in findings}, {"credential"})
            self.assertNotIn(credential, json.dumps(findings))

    def test_real_credentials_in_urls_are_rejected_even_with_placeholder_username(self):
        urls = [
            "https://" + "username:" + "actualpassword@" + "example.invalid/repository",
            "https://" + "actualtoken@" + "example.invalid/repository",
            "https://example.invalid/?access_token=" + "actualtoken",
            "https://example.invalid/?api_key=" + "actualkey",
        ]
        for url in urls:
            findings = self.findings(url)
            self.assertIn("credential-bearing-url", {f["kind"] for f in findings})
            self.assertNotIn(url, json.dumps(findings))
        examples = [
            "https://username:SECRET_TOKEN@github.com/Example/Project.git",
            "https://example.invalid/?access_token=YOUR_TOKEN",
            "https://example.invalid/" + "?api_key=$" + "{EXAMPLE_KEY}",
            "https://example.invalid/?page=2",
        ]
        self.assertEqual(self.findings("\n".join(examples)), [])

    def test_private_filename_is_rejected_and_redacted(self):
        name = "fictional-owner.md"
        (self.root / name).write_text("PUBLIC")
        findings = privacy.audit(self.root, [name], ["fictional-owner"])
        self.assertEqual({f["kind"] for f in findings}, {"private-or-owner-identifier-in-path"})
        self.assertNotIn(name, json.dumps(findings))

    def test_binary_content_is_inventoried_for_manual_review(self):
        (self.root / "asset.png").write_bytes(bytes([137, 80, 78, 71, 0]))
        (self.root / "utf8-nul.bin").write_bytes(bytes([0]) + b"PRIVATE")
        binaries = []
        findings = privacy.audit(self.root, ["asset.png", "utf8-nul.bin"], binary_paths=binaries)
        self.assertEqual(findings, [])
        self.assertEqual(binaries, ["asset.png", "utf8-nul.bin"])

    def test_staged_content_is_checked_even_when_worktree_is_cleaned(self):
        import subprocess
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        path = self.root / "example.md"
        path.write_text("gh" + "p_" + "a" * 24)
        subprocess.run(["git", "-C", str(self.root), "add", "example.md"], check=True)
        path.write_text("PUBLIC")
        self.assertEqual(privacy.audit(self.root, ["example.md"]), [])
        findings = privacy.audit(self.root, ["example.md"], staged=True)
        self.assertEqual({f["kind"] for f in findings}, {"credential"})
        path.unlink()
        self.assertEqual({f["kind"] for f in privacy.audit(self.root, ["example.md"], staged=True)}, {"credential"})

    def test_git_tracks_hidden_and_optional_new_files(self):
        import subprocess
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".hidden").write_text("PUBLIC")
        (self.root / "new.md").write_text("PUBLIC")
        subprocess.run(["git", "-C", str(self.root), "add", ".hidden"], check=True)
        self.assertEqual(privacy.public_paths(self.root), [".hidden"])
        self.assertEqual(privacy.public_paths(self.root, True), [".hidden", "new.md"])

if __name__ == "__main__":
    unittest.main()
