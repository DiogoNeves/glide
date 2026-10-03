#!/usr/bin/env python3
"""Audit public tracked files without printing matched private content."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import parse_qsl, unquote, urlsplit

EMAIL = re.compile(r"[A-Z0-9._%+!#$&'*=/^{}|~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
HOME = re.compile(r"(?:/(?:Users|home)/|[A-Z]:\\Users\\)([^/\\\s\"'<>]+)", re.I)
PLACEHOLDER_USERS = {"example", "test-user", "synthetic", "user", "$user"}
PLACEHOLDER_LOCAL = {"secret_token", "example_token", "your_token", "username"}
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")
TOKEN = re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})(?![A-Za-z0-9_])")
URL = re.compile(r"(?:https?|ftp|ssh|git|s3|wss?)://[^\s\"'<>"+chr(96)+r"]+", re.I)
PLACEHOLDER_CREDENTIALS = {"username", "password", "token", "secret_token", "example_token", "your_token", "api_key", "example_key", "your_api_key"}
CREDENTIAL_QUERY_KEYS = {"token", "access_token", "api_key", "apikey", "key", "password", "secret", "client_secret", "authorization", "auth", "signature", "x-goog-signature", "x-amz-signature", "x-amz-credential", "awsaccesskeyid", "googleaccessid", "sig", "sharedaccesssignature"}
RESERVED_DOMAINS = {"example.com", "example.net", "example.org"}
PRIVATE_MARKERS = tuple(" ".join(words) for words in [
    ("BEGIN", "PRIVATE", "DATA"), ("PRIVATE", "INSTANCE", "DATA"),
    ("LIVE", "FINANCE", "STATE"), ("CONFIDENTIAL", "CUSTOMER", "EXPORT"),
])

def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    return result.stdout

def public_paths(root, include_untracked=False):
    args = ["ls-files", "--cached", "-z"]
    if include_untracked:
        args += ["--others", "--exclude-standard"]
    return sorted(set(p.decode() for p in git(root, *args).split(b"\0") if p))

def owner_terms(root):
    """Repository namespace is discovered locally, never hardcoded or fetched."""
    terms = []
    configured = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    if configured:
        terms.append(configured)
    result = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True, text=True)
    if result.returncode == 0:
        match = re.search(r"github[.]com[/:]([^/\s]+)/", result.stdout)
        if match:
            terms.append(match[1])
    return sorted({term.casefold() for term in terms if len(term) >= 3})

def private_terms(path, root):
    if path is None:
        return []
    path = path.resolve(strict=True)
    if path.is_relative_to(root.resolve()):
        raise ValueError("Keep the optional private denylist outside the repository")
    data = json.loads(path.read_text())
    if not isinstance(data, list) or any(not isinstance(v, str) or len(v) < 3 or "\0" in v for v in data):
        raise ValueError("Private denylist must be a JSON array of nonempty terms of at least three characters")
    return [v.casefold() for v in data]

def artifact(relative):
    path = PurePosixPath(relative)
    name = path.name.lower()
    return (
        "__pycache__" in path.parts or name.endswith((".pyc", ".pyo", ".log"))
        or name in {"writer.lock", "conversation-intake.json", "installation.json", "index.sqlite3"}
        or name.startswith("index.sqlite3-")
        or (name == ".env" or name.startswith(".env.")) and not name.endswith((".example", ".sample", ".template"))
    )

def placeholder_credential(value):
    value = unquote(value)
    return value.casefold() in PLACEHOLDER_CREDENTIALS or bool(re.fullmatch(r"\$\{?[A-Z][A-Z0-9_]*\}?", value))

def credential_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.username is not None:
            if not placeholder_credential(parsed.username):
                return True
            if parsed.password is not None and not placeholder_credential(parsed.password):
                return True
        return any(key.casefold() in CREDENTIAL_QUERY_KEYS and value and not placeholder_credential(value)
                   for key, value in parse_qsl(parsed.query))
    except ValueError:
        return "@" in value

def audit(root, paths, deny_terms=(), binary_paths=None, staged=False):
    root = root.resolve()
    findings = []
    for relative in sorted(set(paths)):
        identifying_name = any(term in relative.casefold() for term in deny_terms)
        public_location = "[redacted private filename]" if identifying_name else relative
        if identifying_name:
            findings.append({"path": public_location, "kind": "private-or-owner-identifier-in-path"})
        posix = PurePosixPath(relative)
        if posix.is_absolute() or ".." in posix.parts:
            findings.append({"path": public_location, "kind": "unsafe-path"})
            continue
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            findings.append({"path": public_location, "kind": "symlink-or-escape"})
            continue
        if not staged and not path.is_file():
            continue
        if artifact(relative):
            findings.append({"path": public_location, "kind": "private-or-generated-artifact"})
        if staged:
            entries = git(root, "ls-files", "--stage", "-z", "--", relative).split(b"\0")
            modes = [entry.split(b" ", 1)[0] for entry in entries if entry]
            if modes != [b"100644"] and modes != [b"100755"]:
                findings.append({"path": public_location, "kind": "unsafe-index-entry"})
                continue
            data = git(root, "show", ":" + relative)
        else:
            data = path.read_bytes()
        try:
            body = data.decode("utf-8")
            if "\0" in body:
                raise UnicodeDecodeError("utf-8", data, 0, min(1, len(data)), "NUL content")
        except UnicodeDecodeError:
            if binary_paths is not None:
                binary_paths.append(public_location)
            continue
        for number, line in enumerate(body.splitlines(), 1):
            folded = line.casefold()
            kinds = set()
            if PRIVATE_KEY.search(line) or TOKEN.search(line):
                kinds.add("credential")
            if any(credential_url(match[0]) for match in URL.finditer(line)):
                kinds.add("credential-bearing-url")
            if any(term in folded for term in deny_terms):
                kinds.add("private-or-owner-identifier")
            if any(marker.casefold() in folded for marker in PRIVATE_MARKERS):
                kinds.add("private-data-marker")
            for match in HOME.finditer(line):
                if match[1].strip(chr(96)).casefold() not in PLACEHOLDER_USERS:
                    kinds.add("identifying-home-path")
            for match in EMAIL.finditer(line):
                local, domain = match[0].casefold().split("@", 1)
                tail = line[match.end():]
                is_git_remote = local == "git" and tail.startswith((":", "/"))
                is_example = domain in RESERVED_DOMAINS or domain.endswith((".invalid", ".example", ".test"))
                if not (is_git_remote or is_example or local in PLACEHOLDER_LOCAL):
                    kinds.add("email-address")
            findings.extend({"path": public_location, "line": number, "kind": kind} for kind in sorted(kinds))
    return findings

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--include-untracked", action="store_true", help="Preflight new public files before staging")
    selection.add_argument("--staged", action="store_true", help="Check exact indexed bytes before committing")
    parser.add_argument("--denylist", type=Path, default=os.environ.get("GLIDE_PUBLIC_PRIVACY_DENYLIST"), help="Optional private JSON terms, stored outside the repository")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        paths = public_paths(root, args.include_untracked)
        terms = owner_terms(root) + private_terms(args.denylist, root)
        binaries = []
        findings = audit(root, paths, terms, binaries, staged=args.staged)
        print(json.dumps({"ok": not findings and not binaries, "files_checked": len(paths), "findings": findings,
                          "binary_files_for_manual_review": binaries}, indent=2))
        return bool(findings or binaries)
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(2, "Privacy check could not read its repository or private configuration; no matching content was printed.\n")

if __name__ == "__main__":
    raise SystemExit(main())
