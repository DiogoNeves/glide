#!/usr/bin/env python3
"""Local, allowlisted recovery exports. No uploads, scheduling or writer activation."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile


class RecoveryError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"


def local_path(value):
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise RecoveryError("Local paths must be absolute")
    for part in [p, *p.parents]:
        if part.is_symlink():
            raise RecoveryError("Symlinks are not admitted")
    return p


def relative_name(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or ".." in p.parts or "\\" in value or str(p) != value:
        raise RecoveryError("Invalid export name")
    if p.parts[0] in {"manifest.json", "RESTORE.md"}:
        raise RecoveryError("Reserved export name")
    return value


def load_policy(path):
    policy = json.loads(local_path(path).read_text())
    if policy.get("schema") != 1 or not policy.get("instance_id") or not isinstance(policy.get("files"), list):
        raise RecoveryError("Expected schema 1, instance_id and an explicit files allowlist")
    local_path(policy["export_root"])
    names = [relative_name(e["name"]) for e in policy["files"]]
    if len(set(names)) != len(names):
        raise RecoveryError("Duplicate export name")
    return policy


def admitted_bytes(entry):
    p = local_path(entry["source"])
    if not p.is_file():
        raise RecoveryError("An allowlisted file is missing")
    if p.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pem", ".key"} or p.name.endswith(("-wal", "-shm", ".lock")) or p.name in {".env", "auth.json"}:
        raise RecoveryError("Database, lock or credential file is not admitted")
    if p.stat().st_size > 4 * 1024 * 1024:
        raise RecoveryError("Configuration export file exceeds 4 MiB")
    data = p.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecoveryError("Only reviewed UTF-8 configuration files are admitted") from exc
    # A tripwire, not a complete secret detector; review the allowlist before any upload.
    if re.search(r"-----BEGIN .*PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})", text):
        raise RecoveryError("Possible credential detected")
    if re.search(r'''(?im)^\s*["']?(?:api_key|access_token|refresh_token|password|client_secret)["']?\s*[:=]\s*["'][^"']+["']''', text):
        raise RecoveryError("Possible credential assignment detected")
    return data


def collect(policy):
    blobs = {e["name"]: admitted_bytes(e) for e in policy["files"]}
    metadata = {"schema": 1, "instance_id": policy["instance_id"], "policy_sha256": digest(encoded(policy)),
                "files": {name: digest(data) for name, data in sorted(blobs.items())},
                "scope": "Allowlisted private configuration only; not a vault or off-machine backup"}
    return blobs, metadata


def verify(bundle):
    root = local_path(bundle)
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema") != 1 or not isinstance(manifest.get("files"), dict):
        raise RecoveryError("Invalid bundle manifest")
    for name, expected in manifest["files"].items():
        relative_name(name)
        p = local_path(str(root / name))
        if not p.is_file() or digest(p.read_bytes()) != expected:
            raise RecoveryError("Missing or changed exported file")
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json", "RESTORE.md"}:
        raise RecoveryError("Unexpected files in export")
    return {"verified": True, "files": len(manifest["files"]), "instance_id": manifest["instance_id"]}


def inspect(policy):
    _, metadata = collect(policy)
    key = digest(encoded(metadata))
    target = local_path(policy["export_root"]) / key
    present = target.exists()
    if present:
        verify(str(target))
        if json.loads((target / "manifest.json").read_text()) != metadata:
            raise RecoveryError("Existing export metadata differs")
    return {"configuration_export": "current" if present else "missing-or-changed", "bundle": str(target),
            "files": len(metadata["files"]), "off_machine_backup": policy.get("off_machine_backup", {"status": "pending"}),
            "private_repository": policy.get("private_repository", {"status": "not-selected"}),
            "meaning": "Destination configuration is not proof of completed backup or tested recovery"}


def export(policy):
    blobs, metadata = collect(policy)
    root = local_path(policy["export_root"])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / digest(encoded(metadata))
    if target.exists():
        result = inspect(policy)
        return dict(result, created=False)
    staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
    try:
        for name, data in blobs.items():
            p = staging / name
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            p.write_bytes(data)
            p.chmod(0o600)
        (staging / "manifest.json").write_bytes(encoded(metadata))
        (staging / "RESTORE.md").write_text(
            "This private configuration export is not a complete backup.\n\n"
            "1. Verify hashes with recovery_bundle.py verify.\n"
            "2. Recover the durable workspace and required sources from a separate backup.\n"
            "3. Install the pinned runtime and helpers; restore custom instructions with ownership checks.\n"
            "4. Review paths and credentials separately. Never replay saved automation files directly.\n"
            "5. Set writer_active=false in restored configuration; keep all restored jobs paused.\n"
            "6. Rebuild a disposable index and check records, history, evidence and required dependencies.\n"
            "7. Confirm the old writer is stopped before enabling one writer and approved jobs.\n\n"
            "Original configuration files may describe an active writer; do not run them unchanged.\n")
        for name in ("manifest.json", "RESTORE.md"):
            (staging / name).chmod(0o600)
        # Abort if a source changed while the export was being assembled.
        if collect(policy)[1] != metadata:
            raise RecoveryError("Source changed during export; retry after it stabilizes")
        verify(str(staging))
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return dict(inspect(policy), created=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "export"):
        sub.add_parser(command).add_argument("--policy", required=True)
    sub.add_parser("verify").add_argument("--bundle", required=True)
    args = parser.parse_args()
    try:
        result = verify(args.bundle) if args.command == "verify" else globals()[args.command](load_policy(args.policy))
    except (RecoveryError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Recovery check failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
