import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from glide_memory.runner import ProtectionUnavailable, build_reader_command, protection_test, reader_permissions, run_protected


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "vault"
        self.scratch = self.root / 'scratch " quoted $(literal)'
        self.source.mkdir()
        self.scratch.mkdir()

    def test_profile_only_grants_nonoverlapping_scratch_writes(self):
        profile = reader_permissions([self.source], self.scratch)
        self.assertEqual(profile["filesystem"], {":root": "read", str(self.scratch): "write"})
        self.assertFalse(profile["network"]["enabled"])
        inside = self.source / "inside"
        inside.mkdir()
        for scratch in (inside, self.source, self.root):
            with self.assertRaises(ValueError):
                reader_permissions([self.source], scratch)
        link = self.root / "looks-safe"
        link.symlink_to(inside, target_is_directory=True)
        with self.assertRaises(ValueError):
            reader_permissions([self.source], link)

    @patch("glide_memory.runner.platform.system", return_value="Darwin")
    def test_command_uses_literal_arguments_and_whole_profile_override(self, _):
        command = ["/bin/echo", "literal $(do not run)", "--permission-profile", "another"]
        argv = build_reader_command(command, source_roots=[self.source], scratch_root=self.scratch, codex_executable="/bin/echo")
        parsed = tomllib.loads(argv[argv.index("-c") + 1])
        self.assertEqual(parsed, {"permissions": {"glide-source-reader": reader_permissions([self.source], self.scratch)}})
        self.assertEqual(argv[argv.index("--") + 1:], command)
        self.assertNotIn("macos", argv)

    @patch("glide_memory.runner.platform.system", return_value="Linux")
    def test_unsupported_platform_fails_closed(self, _):
        with self.assertRaises(ProtectionUnavailable):
            build_reader_command(["/bin/echo", "hi"], source_roots=[self.source], scratch_root=self.scratch, codex_executable="/bin/echo")

    @patch("glide_memory.runner.platform.system", return_value="Darwin")
    @patch("glide_memory.runner.subprocess.run")
    def test_nested_denial_is_unavailable_and_never_retried_unprotected(self, run, _):
        run.return_value = subprocess.CompletedProcess([], 71, "", "sandbox-exec: sandbox_apply: Operation not permitted")
        result = run_protected(["/bin/echo", "hello"], source_roots=[self.source], scratch_root=self.scratch, codex_executable="/bin/echo")
        self.assertEqual(result["boundary"], "unavailable")
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("glide_memory.runner.platform.system", return_value="Darwin")
    @patch("glide_memory.runner.subprocess.run")
    def test_timeout_has_no_unsafe_fallback(self, run, _):
        run.side_effect = subprocess.TimeoutExpired("synthetic", 1)
        with self.assertRaises(ProtectionUnavailable):
            run_protected(["/bin/echo", "hello"], source_roots=[self.source], scratch_root=self.scratch, codex_executable="/bin/echo")
        self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(os.environ.get("GLIDE_CODEX_SANDBOX_EXECUTABLE"), "explicit local sandbox integration test not requested")
    def test_real_sandbox_read_write_and_alternate_routes(self):
        result = protection_test(os.environ["GLIDE_CODEX_SANDBOX_EXECUTABLE"])
        self.assertEqual(result["status"], "passed", result)


if __name__ == "__main__":
    unittest.main()
