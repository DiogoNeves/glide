"""Read-only Markdown and local Git intake; callers persist cursors after acceptance.

Returned cursors are proposals. Persist one only after its associated sources/events
have been durably accepted. Losing a cursor may repeat intake, but stable source and
event IDs let the caller deduplicate it. No function fetches or changes a repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit


DEFAULT_EXCLUDED_ROOTS = ("Agent HQ/Memory", "Glide HQ/Memory")
MAX_GIT_OUTPUT = 16 * 1024 * 1024


def _stamp(value: float | None = None) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else datetime.now(timezone.utc).isoformat()


def _hash(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _read(root: Path, relative: Path, max_bytes: int) -> tuple[str, str, str]:
    """Open each path component without following symlinks, including parent dirs."""
    if relative.is_absolute() or any(p in ("", ".", "..") for p in relative.parts):
        raise ValueError("invalid relative path")
    handles: list[int] = []
    try:
        handles.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in relative.parts[:-1]:
            handles.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=handles[-1]))
        handle = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=handles[-1])
        handles.append(handle)
        before = os.fstat(handle)
        import stat
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("not a regular file")
        if before.st_size > max_bytes:
            raise ValueError("file exceeds configured size limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            data = os.read(handle, min(65536, remaining))
            if not data:
                break
            chunks.append(data)
            remaining -= len(data)
        data = b"".join(chunks)
        after = os.fstat(handle)
        if len(data) > max_bytes:
            raise ValueError("file exceeds configured size limit")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("file changed during read; retry next scan")
        if b"\x00" in data:
            raise ValueError("binary content in Markdown file")
        return data.decode("utf-8"), _hash(data), _stamp(after.st_mtime)
    finally:
        for handle in reversed(handles):
            os.close(handle)


def scan_markdown_sources(
    vault_root: str | Path,
    prior_cursor: dict | None = None,
    *,
    excluded_roots: tuple[str, ...] | list[str] = DEFAULT_EXCLUDED_ROOTS,
    max_bytes: int = 2 * 1024 * 1024,
) -> dict:
    """Return changed original/legacy Markdown sources, never generated memory.

    Legacy HQ files are historical evidence, not trusted current facts. Exclusions
    always include both generated Memory roots, even when additional roots are given.
    Any coverage gap suppresses deletion reports: an unreadable source is not absent.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    root = Path(vault_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("vault_root must be a directory")
    prior_cursor = prior_cursor or {}
    if prior_cursor.get("kind") not in (None, "markdown-v1"):
        raise ValueError("incompatible source cursor")
    previous = dict(prior_cursor.get("sources", {}))
    next_sources = dict(previous)
    excluded = tuple(Path(p).parts for p in (*DEFAULT_EXCLUDED_ROOTS, *excluded_roots))
    if any(Path(p).is_absolute() or ".." in Path(p).parts for p in excluded_roots):
        raise ValueError("excluded roots must be vault-relative")
    sources: list[dict] = []
    unavailable: list[dict] = []
    seen: set[str] = set()
    checked = unchanged = skipped = 0

    def is_excluded(relative: Path) -> bool:
        return any(p.startswith(".") for p in relative.parts) or any(relative.parts[:len(parts)] == parts for parts in excluded)

    def on_error(error: OSError) -> None:
        unavailable.append({"path": str(Path(error.filename).relative_to(root)) if error.filename else "", "reason": "directory unavailable"})

    for directory, subdirs, files in os.walk(root, followlinks=False, onerror=on_error):
        directory_path = Path(directory)
        kept: list[str] = []
        for name in sorted(subdirs):
            candidate = directory_path / name
            relative = candidate.relative_to(root)
            if is_excluded(relative):
                skipped += 1
            elif candidate.is_symlink():
                unavailable.append({"path": relative.as_posix(), "reason": "symlink directory excluded"})
            else:
                kept.append(name)
        subdirs[:] = kept
        for name in sorted(files):
            relative = (directory_path / name).relative_to(root)
            if relative.suffix.lower() != ".md" or is_excluded(relative):
                continue
            path = relative.as_posix()
            seen.add(path)
            try:
                text, fingerprint, modified_at = _read(root, relative, max_bytes)
            except (OSError, UnicodeError, ValueError) as error:
                unavailable.append({"path": path, "reason": str(error) if not isinstance(error, OSError) else "file unavailable or symlink excluded"})
                continue
            checked += 1
            next_sources[path] = fingerprint
            if previous.get(path) == fingerprint:
                unchanged += 1
                continue
            source_kind = "legacy-agent-context" if relative.parts[0] in ("Agent HQ", "Glide HQ") else "original-markdown"
            sources.append({"source_id": "markdown:" + _hash(path), "path": path, "sha256": fingerprint, "text": text, "modified_at": modified_at, "source_kind": source_kind, "trust": "source-only"})
    deletions = sorted(set(previous) - seen) if not unavailable else []
    # Explicitly excluded files are outside this scan's scope, not deletion evidence.
    deletions = [p for p in deletions if not is_excluded(Path(p))]
    for path in deletions:
        next_sources.pop(path, None)
    return {
        "sources": sources,
        "deletions": deletions,
        "coverage": {"status": "partial" if unavailable else "complete", "checked": checked, "unchanged": unchanged, "excluded_directories": skipped, "unavailable": unavailable},
        "next_cursor": {"kind": "markdown-v1", "sources": next_sources},
    }


def _git(root: Path, *args: str, timeout: int = 30) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    command = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull, "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-C", str(root), *args]
    result = subprocess.run(command, capture_output=True, timeout=timeout, check=False, env=environment)
    if result.returncode:
        # Never expose remote credentials/configuration through Git diagnostics.
        raise ValueError("local Git inspection failed")
    if len(result.stdout) > MAX_GIT_OUTPUT:
        raise ValueError("Git result exceeds intake limit")
    return result.stdout.decode("utf-8", errors="replace")


def _remote_identity(value: str) -> str | None:
    value = value.strip()
    ssh = re.fullmatch(r"(?:[^@/\s]+@)?([^:/\s]+):(.+)", value)
    if ssh and "://" not in value:
        host, path = ssh.groups()
    else:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https", "ssh", "git") or not parsed.hostname:
            return None
        host, path = parsed.hostname, parsed.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path or any(part in ("", ".", "..") for part in path.split("/")) or any(c in path for c in "?#\n\r\x00"):
        return None
    return host.lower() + "/" + (path.lower() if host.lower() == "github.com" else path)


def _index_field(text: str, name: str) -> str | None:
    matches = re.findall(r"^\s*-\s+" + re.escape(name) + r":\s*(.*?)\s*$", text, re.MULTILINE)
    if len(matches) > 1:
        raise ValueError("ambiguous index " + name + " mapping")
    if not matches:
        return None
    value = matches[0].strip().strip("`")
    link = re.fullmatch(r"\[[^\]]*\]\(([^)]+)\)", value)
    return link.group(1) if link else value


def scan_project_activity(
    project_index_root: str | Path,
    prior_cursor: dict | None = None,
    *,
    lookback_days: int = 14,
    max_commits: int = 500,
    now: datetime | None = None,
) -> dict:
    """Inspect configured projects/*.md mappings and commit history across all refs.

    First intake uses an explicit lookback window. Subsequent intake compares saved
    ref heads, including newly introduced/backdated commits. A limited batch keeps
    old heads until all pending commits are accepted. Coverage distinguishes missing
    clones, failed inspection, partial batches and genuinely unchanged repositories.
    """
    if lookback_days < 0 or max_commits < 1:
        raise ValueError("lookback_days must be nonnegative and max_commits positive")
    root = Path(project_index_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("project index must be a directory")
    prior_cursor = prior_cursor or {}
    if prior_cursor.get("kind") not in (None, "projects-v1"):
        raise ValueError("incompatible project cursor")
    next_repositories = json.loads(json.dumps(prior_cursor.get("repositories", {})))
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("now must include a timezone")
    first_since = (moment - timedelta(days=lookback_days)).isoformat()
    projects = root / "projects"
    coverage: list[dict] = []
    events: list[dict] = []
    inspected: dict[str, dict] = {}
    if not projects.is_dir() or projects.is_symlink():
        return {"events": [], "coverage": [{"index_path": "projects", "status": "unavailable", "reason": "projects directory missing or symlinked"}], "next_cursor": {"kind": "projects-v1", "repositories": next_repositories}}
    for entry in sorted(projects.glob("*.md")):
        index_path = entry.relative_to(root).as_posix()
        item: dict = {"index_path": index_path}
        try:
            text, index_sha, _ = _read(root, entry.relative_to(root), 1024 * 1024)
            local = _index_field(text, "Local path")
            index_remote = _remote_identity(_index_field(text, "GitHub") or "")
            if not local or local.startswith("("):
                item.update(status="unavailable", reason="no local clone configured")
                coverage.append(item)
                continue
            if any(c in local for c in "\x00\n\r"):
                raise ValueError("invalid local path mapping")
            candidate = Path(local).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            repository = candidate.resolve(strict=True)
            if not repository.is_dir():
                raise ValueError("configured local path is not a directory")
            actual_root = Path(_git(repository, "rev-parse", "--show-toplevel").strip()).resolve()
            if actual_root != repository:
                raise ValueError("configured local path is not the repository root")
            try:
                remote = _remote_identity(_git(repository, "config", "--local", "--get", "remote.origin.url"))
            except ValueError:
                remote = None
            roots = sorted(_git(repository, "rev-list", "--max-parents=0", "--all").splitlines())
            identity = remote or ("roots:" + ",".join(roots) if roots else "empty-index:" + index_path)
            repo_id = "git:" + _hash(identity)
            item["repo_id"] = repo_id
            if remote and index_remote and remote != index_remote:
                item["warning"] = "index GitHub mapping differs from actual origin; commits attributed to actual repository"
            clone_key = str(repository)
            if clone_key in inspected:
                item.update(status="duplicate-mapping", canonical_index_path=inspected[clone_key]["index_path"])
                coverage.append(item)
                continue
            inspected[clone_key] = item
            repository_previous = next_repositories.get(repo_id, {})
            previous = repository_previous.get("clones", {}).get(index_path, {})
            seen = set(repository_previous.get("seen_commits", []))
            heads = sorted(set(_git(repository, "for-each-ref", "--format=%(objectname)").splitlines()))
            # Include detached HEAD, which may not appear in for-each-ref.
            try:
                head = _git(repository, "rev-parse", "--verify", "HEAD").strip()
                if head not in heads:
                    heads.append(head)
            except ValueError:
                pass
            valid_prior_heads: list[str] = []
            for old_head in previous.get("heads", []):
                if not re.fullmatch(r"[0-9a-f]{40,64}", old_head):
                    raise ValueError("invalid Git head in intake cursor")
                try:
                    _git(repository, "cat-file", "-e", old_head + "^{commit}")
                    valid_prior_heads.append(old_head)
                except ValueError:
                    pass
            since = previous.get("initial_since", first_since)
            args = ["rev-list", "--date-order", *heads]
            if not previous.get("baseline_complete"):
                args.append("--since-as-filter=" + since)
            if valid_prior_heads:
                args.extend(["--not", *valid_prior_heads])
            all_pending = _git(repository, *args).splitlines() if heads else []
            pending = [commit for commit in reversed(all_pending) if commit not in seen]
            selected = pending[:max_commits]
            repository_events: list[dict] = []
            for commit in selected:
                if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
                    raise ValueError("invalid commit identifier")
                commit_hash, committed_at, subject = _git(repository, "show", "--no-patch", "--format=%H%x00%cI%x00%s", commit).rstrip("\n").split("\x00", 2)
                refs = _git(repository, "for-each-ref", "--contains=" + commit, "--format=%(refname)").splitlines()
                commit_url = "https://" + remote + "/commit/" + commit if remote and remote.startswith("github.com/") else None
                repository_events.append({"event_id": "commit:" + _hash(repo_id + ":" + commit_hash), "repo_id": repo_id, "commit": commit_hash, "source_ref": "git:" + identity + "@" + commit_hash, "url": commit_url, "title": subject, "committed_at": committed_at, "observed_at": moment.isoformat(), "refs": refs, "index_path": index_path, "index_sha256": index_sha, "source_kind": "git-commit", "meaning": "commit-record; not evidence of release, deployment, or user outcome"})
            seen.update(selected)
            complete = len(pending) == len(selected)
            clones = dict(repository_previous.get("clones", {}))
            clones[index_path] = {"heads": sorted(heads) if complete else previous.get("heads", []), "initial_since": since, "baseline_complete": complete or previous.get("baseline_complete", False)}
            next_repositories[repo_id] = {"clones": clones, "seen_commits": sorted(seen)}
            events.extend(repository_events)
            item.update(status="complete" if complete else "partial", commits=len(selected), pending=len(pending) - len(selected), changed=bool(selected))
        except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as error:
            item.update(status="unavailable", reason=str(error) if isinstance(error, ValueError) else "local source unavailable")
        coverage.append(item)
    return {"events": events, "coverage": coverage, "next_cursor": {"kind": "projects-v1", "repositories": next_repositories}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("markdown", "projects"))
    parser.add_argument("root")
    parser.add_argument("--cursor", help="Previously accepted cursor JSON; read only")
    parser.add_argument("--lookback-days", type=int, default=14)
    args = parser.parse_args()
    cursor = json.loads(Path(args.cursor).read_text()) if args.cursor else None
    result = scan_markdown_sources(args.root, cursor) if args.kind == "markdown" else scan_project_activity(args.root, cursor, lookback_days=args.lookback_days)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
