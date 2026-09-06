"""Run source-reading commands under a verified Codex filesystem boundary.

Only the configured scratch directory is writable. This wrapper does not grant
connector authority, configure Codex, or turn an unrestricted parent into a sandbox.
Use the narrow trusted writer separately for approved durable-memory changes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Sequence


class ProtectionUnavailable(RuntimeError):
    """The requested execution boundary could not be established."""


def _directory(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("expected an existing directory")
    return path


def reader_permissions(source_roots: Sequence[str | Path], scratch_root: str | Path) -> dict:
    """Return a profile granting root reads and only non-overlapping scratch writes."""
    if not source_roots:
        raise ValueError("at least one protected source root is required")
    sources = [_directory(source) for source in source_roots]
    scratch = _directory(scratch_root)
    for source in sources:
        if scratch == source or scratch.is_relative_to(source) or source.is_relative_to(scratch):
            raise ValueError("scratch and protected sources must not overlap")
    return {"filesystem": {":root": "read", str(scratch): "write"}, "network": {"enabled": False}}


def build_reader_command(
    command: Sequence[str],
    *,
    source_roots: Sequence[str | Path],
    scratch_root: str | Path,
    codex_executable: str | Path | None = None,
) -> list[str]:
    """Build argv for the current named-profile CLI; never interpolate a shell."""
    if platform.system() != "Darwin":
        raise ProtectionUnavailable("This runner currently verifies macOS only; no unsandboxed fallback is allowed")
    if not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
        raise ValueError("command must be a nonempty argument list")
    configured_executable = str(codex_executable) if codex_executable else shutil.which("codex")
    if not configured_executable:
        raise ProtectionUnavailable("Codex executable is unavailable; configure a compatible local executable")
    executable = Path(configured_executable).expanduser().resolve(strict=True)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ProtectionUnavailable("Codex executable is not an executable file")
    profile = reader_permissions(source_roots, scratch_root)
    filesystem = ", ".join(json.dumps(path) + " = " + json.dumps(access) for path, access in profile["filesystem"].items())
    # Replace the whole permissions table, so inherited named-profile grants cannot
    # add another writable root. JSON-quoted scalar strings are valid TOML strings.
    config = 'permissions = { glide-source-reader = { filesystem = { ' + filesystem + ' }, network = { enabled = false } } }'
    return [str(executable), "sandbox", "-c", config, "--permission-profile", "glide-source-reader", "--cd", str(_directory(scratch_root)), "--", *command]


def run_protected(
    command: Sequence[str],
    *,
    source_roots: Sequence[str | Path],
    scratch_root: str | Path,
    codex_executable: str | Path | None = None,
    timeout: float = 120,
) -> dict:
    """Execute once; return failure as failure, never retry outside the sandbox."""
    argv = build_reader_command(command, source_roots=source_roots, scratch_root=scratch_root, codex_executable=codex_executable)
    started = time.monotonic()
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        process = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, env=environment)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProtectionUnavailable("Protected command could not complete: " + type(error).__name__) from error
    startup_errors = ("sandbox_apply: Operation not permitted", "unexpected argument '--permission-profile'", "unrecognized subcommand", "failed to parse configuration", "unknown permissions profile")
    unavailable = process.returncode != 0 and any(marker in process.stderr for marker in startup_errors)
    return {"returncode": process.returncode, "stdout": process.stdout, "stderr": process.stderr, "elapsed_seconds": round(time.monotonic() - started, 6), "boundary": "unavailable" if unavailable else "requested", "platform": platform.system()}


_PROBE = r'''
import json, os, pathlib, subprocess, sys
source, scratch = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
note = source / "Original.md"
results = {"source_read": note.read_text() == "Original content\n"}
try:
    note.write_text("changed")
    results["direct_write_denied"] = False
except PermissionError:
    results["direct_write_denied"] = True
try:
    (scratch / "source-link.md").write_text("changed through link")
    results["symlink_write_denied"] = False
except PermissionError:
    results["symlink_write_denied"] = True
try:
    os.link(note, scratch / "source-hardlink.md")
    (scratch / "source-hardlink.md").write_text("changed through hardlink")
    results["hardlink_write_denied"] = False
except PermissionError:
    results["hardlink_write_denied"] = True
shell = subprocess.run(["/bin/sh", "-c", 'printf changed > "$1"', "glide-test", str(note)], capture_output=True, text=True)
results["shell_write_denied"] = shell.returncode != 0 and note.read_text() == "Original content\n"
results["shell_diagnostic"] = shell.stderr.strip()
(scratch / "allowed.txt").write_text("scratch output")
results["scratch_write"] = (scratch / "allowed.txt").read_text() == "scratch output"
apple = subprocess.run(["/usr/bin/osascript", str(scratch / "alternate.scpt")], capture_output=True, text=True)
results["applescript_write_denied"] = apple.returncode != 0 and note.read_text() == "Original content\n"
results["applescript_diagnostic"] = apple.stderr.strip()
print(json.dumps(results))
'''


def protection_test(codex_executable: str | Path | None = None, *, fixture_parent: str | Path | None = None) -> dict:
    """Exercise only disposable fixtures; a startup denial is inconclusive, not pass."""
    if platform.system() != "Darwin":
        return {"status": "unavailable", "reason": "Local protection probe currently verifies macOS only"}
    with tempfile.TemporaryDirectory(prefix="glide-protection-", dir=fixture_parent) as directory:
        base = Path(directory).resolve()
        source, scratch = base / "sources", base / "scratch"
        source.mkdir()
        scratch.mkdir()
        original = source / "Original.md"
        original.write_text("Original content\n")
        (scratch / "source-link.md").symlink_to(original)
        before = original.read_bytes()
        # Compile before entering the sandbox so a missing scripting dictionary or
        # syntax error cannot masquerade as denial of a valid alternate write route.
        script = "do shell script " + json.dumps("printf changed > " + shlex.quote(str(original)))
        try:
            compiled = subprocess.run(["/usr/bin/osacompile", "-o", str(scratch / "alternate.scpt"), "-e", script], capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return {"status": "unavailable", "reason": "AppleScript probe compilation unavailable", "original_unchanged": original.read_bytes() == before}
        if compiled.returncode:
            return {"status": "unavailable", "reason": "AppleScript probe could not be validated before sandbox execution", "original_unchanged": original.read_bytes() == before}
        try:
            result = run_protected([sys.executable, "-c", _PROBE, str(source), str(scratch)], source_roots=[source], scratch_root=scratch, codex_executable=codex_executable, timeout=45)
        except ProtectionUnavailable as error:
            return {"status": "unavailable", "reason": str(error), "original_unchanged": original.read_bytes() == before}
        unchanged = original.read_bytes() == before
        if result["boundary"] == "unavailable":
            return {"status": "unavailable", "reason": result["stderr"].strip(), "original_unchanged": unchanged}
        if result["returncode"] != 0:
            return {"status": "failed", "reason": "probe did not complete", "stderr": result["stderr"], "original_unchanged": unchanged}
        try:
            checks = json.loads(result["stdout"])
        except ValueError:
            return {"status": "failed", "reason": "probe returned no valid report", "original_unchanged": unchanged}
        required = ("source_read", "direct_write_denied", "symlink_write_denied", "hardlink_write_denied", "shell_write_denied", "scratch_write", "applescript_write_denied")
        return {"status": "passed" if unchanged and all(checks.get(check) is True for check in required) else "failed", "checks": checks, "applescript_validated_before_sandbox": True, "original_unchanged": unchanged, "elapsed_seconds": result["elapsed_seconds"], "platform": result["platform"], "limitation": "Verifies this local command boundary and these write routes, not arbitrary connector or parent-session tools"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", help="Explicit path to compatible installed Codex executable")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--scratch")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.self_test:
        result = protection_test(args.codex)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["status"] == "passed" else 1)
    if not args.scratch or not args.source:
        parser.error("--source and --scratch are required for protected execution")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    result = run_protected(command, source_roots=args.source, scratch_root=args.scratch, codex_executable=args.codex)
    sys.stdout.write(result["stdout"])
    sys.stderr.write(result["stderr"])
    raise SystemExit(result["returncode"])


if __name__ == "__main__":
    main()
