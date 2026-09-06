"""Bounded local intake with durable receipts and restart-safe checkpoints.

Original Markdown stays in place. Project activity is observed from configured
local Git repositories, not inferred from project-index descriptions. Connector
imports (Apple Notes, Voice Memos, email) are separate adapters.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .intake import scan_markdown_sources, scan_project_activity
from .store import Store, StoreError, IntegrityError, canonical, digest, no_symlinks


STATE_MARKER = "<!-- glide:intake-state -->\n```json\n"
SOURCE_STATE_ID = "intake:sources"
PROJECT_STATE_ID = "intake:projects"
DEFAULT_CONFIG = {"source_batch_size": 100, "source_max_bytes": 2 * 1024 * 1024, "source_excluded_roots": [], "project_index_root": None, "project_max_commits": 100, "project_lookback_days": 14}


def _config(store: Store, supplied: dict | None) -> dict:
    supplied = supplied or {}
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULT_CONFIG):
        raise StoreError("Unknown or invalid local intake configuration")
    result = {**DEFAULT_CONFIG, **supplied}
    for key in ("source_batch_size", "source_max_bytes", "project_max_commits", "project_lookback_days"):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < (0 if key == "project_lookback_days" else 1):
            raise StoreError("Invalid intake limit: " + key)
    if result["source_batch_size"] > 1000 or result["project_max_commits"] > 1000:
        raise StoreError("Use at most 1000 records per intake batch")
    excluded = result["source_excluded_roots"]
    if not isinstance(excluded, list) or any(not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts for path in excluded):
        raise StoreError("Source exclusions must be vault-relative paths")
    # A custom derived-store path must be excluded as well as the standard roots.
    result["source_excluded_roots"] = sorted(set([*excluded, store.config["store_path"]]))
    if result["project_index_root"] is not None:
        configured = Path(result["project_index_root"]).expanduser()
        if not configured.is_absolute():
            raise StoreError("Configure an absolute local project-index root outside the vault")
        index_root = no_symlinks(configured)
        if index_root.is_relative_to(store.vault) or store.vault.is_relative_to(index_root):
            raise StoreError("Project-index configuration must resolve outside the vault")
        result["project_index_root"] = str(index_root)
    return result


def load_intake_config(store: Store, path: str | Path | None = None) -> dict:
    """Read private machine configuration only from the local runtime state area."""
    config_path = no_symlinks(Path(path)) if path else store.state_dir / "intake.json"
    if not config_path.is_relative_to(store.state_dir) or config_path.is_relative_to(store.vault):
        raise StoreError("Intake configuration must live in the local state directory")
    if not config_path.exists():
        if path:
            raise StoreError("Requested intake configuration does not exist")
        return _config(store, None)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StoreError("Cannot read local intake configuration") from error
    return _config(store, value)


def _body(introduction: str, state: dict) -> str:
    return introduction.strip() + "\n\n" + STATE_MARKER + json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n```"


def _read_state(record: dict | None) -> dict:
    if record is None:
        return {}
    body = record["body"]
    if body.count(STATE_MARKER) != 1 or not body.endswith("\n```"):
        raise IntegrityError("Intake checkpoint has an unrecognized format")
    try:
        state = json.loads(body.split(STATE_MARKER, 1)[1][:-4])
    except ValueError as error:
        raise IntegrityError("Intake checkpoint is not valid JSON") from error
    if not isinstance(state, dict):
        raise IntegrityError("Intake checkpoint must be an object")
    return state


def _records(store: Store) -> tuple[dict, dict]:
    exported = store.export()
    return exported, {record["id"]: record for record in exported["records"]}


def _observation(kind: str, report: dict) -> dict:
    """Execution evidence, explicitly distinct from independent domain knowledge."""
    quote = canonical(report)
    fingerprint = digest(report)
    return {"source_id": "intake-observation:" + fingerprint, "uri": "glide-intake:" + kind + ":" + fingerprint, "sha256": fingerprint, "quote": quote, "locator": "Captured deterministic intake report", "source_kind": "tool-observation"}


def _apply_records(store: Store, records: list[dict], previous: dict, *, rationale: str, key_prefix: str) -> dict:
    expected = {record["id"]: previous.get(record["id"], {}).get("revision", 0) for record in records}
    key = key_prefix + ":" + digest({"records": records, "expected": expected})
    proposal = store.propose(records, expected_revisions=expected, rationale=rationale, idempotency_key=key)
    return store.apply(proposal["proposal_id"], idempotency_key=key, actor="local-intake", decision="unreviewed")


def _source_intake(store: Store, config: dict) -> dict:
    exported, previous_records = _records(store)
    prior_state = _read_state(previous_records.get(SOURCE_STATE_ID))
    acknowledged_missing = set(prior_state.get("missing", []))
    registry = {source["path"]: source["sha256"] for source in exported["sources"]}
    cursor = {"kind": "markdown-v1", "sources": {path: sha for path, sha in registry.items() if path not in acknowledged_missing}}
    scanned = scan_markdown_sources(store.vault, cursor, excluded_roots=config["source_excluded_roots"], max_bytes=config["source_max_bytes"])
    selected = scanned["sources"][:config["source_batch_size"]]
    pending = len(scanned["sources"]) - len(selected)
    source_receipt = None
    if selected:
        stable = [{key: source[key] for key in ("source_id", "path", "sha256", "modified_at", "source_kind")} for source in selected]
        source_receipt = store.index_sources(selected, idempotency_key="source-intake:" + digest(stable))
        if not source_receipt.get("committed"):
            raise StoreError("Source batch was not durably accepted; checkpoint is unchanged")
    # Source registry entries are themselves committed cursors. Do not persist the
    # scanner's full cursor: it includes changed files outside this bounded batch.
    missing = sorted((acknowledged_missing | set(scanned["deletions"])) - {source["path"] for source in selected})
    coverage = {"status": "partial" if pending or scanned["coverage"]["status"] != "complete" else "complete", "unavailable": scanned["coverage"]["unavailable"], "pending_sources": pending, "missing": missing}
    previous_coverage = prior_state.get("coverage")
    needs_receipt = bool(selected or scanned["deletions"] or previous_coverage != coverage or not previous_records.get(SOURCE_STATE_ID))
    summary_receipt = None
    if needs_receipt:
        report = {"coverage": coverage, "registered": [{"path": source["path"], "sha256": source["sha256"], "source_kind": source["source_kind"]} for source in selected], "source_bundle": source_receipt["bundle"] if source_receipt else None, "meaning": "Source registration and local availability only; no extracted claims were promoted to trusted knowledge."}
        state = {"schema": 1, "kind": "source-intake", "missing": missing, "coverage": coverage, "last_batch": report}
        introduction = f"Original Markdown intake registered {len(selected)} changed source revisions in this batch. {pending} changed files remain pending. Coverage is **{coverage['status']}**.\n\nOriginals stay in place. Missing files remain historical evidence; they are not deletion instructions. Legacy agent notes are source context, not automatically trusted current facts."
        record = {"id": SOURCE_STATE_ID, "title": "Source intake receipt", "kind": "receipt", "origin": "imported", "status": "complete" if coverage["status"] == "complete" else "blocked", "body": _body(introduction, state), "sources": [_observation("sources", report)]}
        # Source commits may have happened immediately above; record revisions are
        # unaffected, while apply validates them against any concurrent writer.
        summary_receipt = _apply_records(store, [record], previous_records, rationale="Record source-intake coverage without changing original notes", key_prefix="source-coverage")
    result_status = "no-change" if not needs_receipt and coverage["status"] == "complete" else coverage["status"]
    if summary_receipt and summary_receipt.get("publication", {}).get("status") != "complete":
        result_status = "publication-pending"
    return {"status": result_status, "registered": len(selected), "checked": scanned["coverage"]["checked"], "pending": pending, "coverage": coverage, "source_receipt": source_receipt, "summary_receipt": summary_receipt}


def _commit_evidence(event: dict) -> dict:
    captured = {key: event[key] for key in ("repo_id", "commit", "committed_at", "title", "source_ref")}
    return {"source_id": event["event_id"], "uri": event.get("url") or event["source_ref"], "sha256": digest(captured), "quote": canonical(captured), "locator": "Exact local Git commit metadata", "source_kind": "git-commit"}


def _activity_record(record_id: str, repo_id: str, month: str, events: list[dict]) -> dict:
    ordered = sorted(events, key=lambda event: (event["committed_at"], event["commit"]))
    source_ref = ordered[-1]["source_ref"].split("@", 1)[0]
    repository_label = source_ref.removeprefix("git:").removeprefix("github.com/")
    if repository_label.startswith(("roots:", "empty-index:")):
        repository_label = "Local project " + repo_id[-8:]
    introduction = f"Observed Git commits for **{repository_label}**, {month}. Commit dates and exact revisions are retained.\n\nThese records establish changes committed locally. They do not establish release, deployment, accepted commitments, or user outcomes.\n\n| Committed | Revision | Commit message |\n| --- | --- | --- |"
    for event in ordered:
        label = event["commit"][:12]
        reference = f"[{label}]({event['url']})" if event.get("url") else "`" + event["commit"] + "`"
        title = event["title"].replace("|", "\\|").replace("\n", " ")
        introduction += f"\n| {event['committed_at']} | {reference} | {title} |"
    return {"id": record_id, "title": repository_label + " activity - " + month, "kind": "receipt", "origin": "imported", "status": "historical", "valid_from": min(event["committed_at"] for event in ordered), "body": _body(introduction, {"schema": 1, "kind": "project-activity", "repo_id": repo_id, "month": month, "events": ordered}), "sources": [_commit_evidence(event) for event in ordered]}


def _project_intake(store: Store, config: dict, *, now: datetime | None = None) -> dict:
    if not config["project_index_root"]:
        return {"status": "disabled", "reason": "No local project-index root configured", "events": 0}
    _, previous_records = _records(store)
    prior_state = _read_state(previous_records.get(PROJECT_STATE_ID))
    cursor = prior_state.get("cursor")
    try:
        scanned = scan_project_activity(config["project_index_root"], cursor, lookback_days=config["project_lookback_days"], max_commits=config["project_max_commits"], now=now)
    except (OSError, ValueError) as error:
        scanned = {"events": [], "next_cursor": cursor or {"kind": "projects-v1", "repositories": {}}, "coverage": [{"index_path": "projects", "status": "unavailable", "reason": type(error).__name__ + ": configured index is unavailable"}]}
    # Coverage identity excludes transient per-run counts. A repeat scan with no
    # changes is quiet; missing clones remain explicitly unavailable in the output.
    stable_coverage = [{key: value for key, value in item.items() if key not in {"commits", "changed"}} for item in scanned["coverage"]]
    events = scanned["events"]
    changed = bool(events or prior_state.get("cursor") != scanned["next_cursor"] or prior_state.get("coverage") != stable_coverage)
    status = "partial" if any(item["status"] in {"partial", "unavailable"} for item in scanned["coverage"]) else "complete"
    if not changed:
        return {"status": "no-change" if status == "complete" else status, "events": 0, "coverage_status": status, "coverage": scanned["coverage"], "receipt": None}
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        month = datetime.fromisoformat(event["committed_at"].replace("Z", "+00:00")).strftime("%Y-%m")
        grouped[(event["repo_id"], month)].append(event)
    records = []
    for (repo_id, month), incoming in sorted(grouped.items()):
        record_id = "activity:" + repo_id.removeprefix("git:")[:40] + ":" + month
        previous = _read_state(previous_records.get(record_id))
        merged = {event["event_id"]: event for event in previous.get("events", [])}
        for event in incoming:
            # Preserve the first exact observation if a restarted scan repeats it.
            merged.setdefault(event["event_id"], event)
        records.append(_activity_record(record_id, repo_id, month, list(merged.values())))
    report = {"coverage": stable_coverage, "events": [{key: event[key] for key in ("event_id", "repo_id", "commit", "source_ref", "title", "committed_at")} for event in events], "activity_records": [record["id"] for record in records], "meaning": "Git observations only; project descriptions and unstaged changes are not progress evidence."}
    state = {"schema": 1, "kind": "project-intake", "cursor": scanned["next_cursor"], "coverage": stable_coverage, "last_batch": report}
    introduction = f"Local project intake observed **{len(events)} new commits**. Coverage is **{status}**.\n\nRepositories were resolved through the configured local project index and inspected without fetching or modifying them. Unavailable repositories are not reported as unchanged. This checkpoint was committed with the associated activity records."
    records.append({"id": PROJECT_STATE_ID, "title": "Project intake receipt", "kind": "receipt", "origin": "imported", "status": "complete" if status == "complete" else "blocked", "body": _body(introduction, state), "sources": [_observation("projects", report)]})
    receipt = _apply_records(store, records, previous_records, rationale="Record verified local Git activity and its checkpoint together", key_prefix="project-intake")
    result_status = status if receipt.get("publication", {}).get("status") == "complete" else "publication-pending"
    return {"status": result_status, "events": len(events), "activity_records": [record["id"] for record in records if record["id"] != PROJECT_STATE_ID], "coverage_status": status, "coverage": scanned["coverage"], "receipt": receipt}


def run_pipeline(store: Store, config: dict | None = None, *, sources: bool = True, projects: bool = True, now: datetime | None = None) -> dict:
    """Run one bounded batch. Call again while pending; do not loop without a budget."""
    configuration = _config(store, config) if config is not None else load_intake_config(store)
    # Do not silently continue through unexpected edits or a partial publication.
    verified = store.verify()
    recovery = None
    if verified.get("stale_projections") or verified.get("index") != "current":
        recovery = store.rebuild()
    results = {"sources": _source_intake(store, configuration) if sources else {"status": "disabled"}, "projects": _project_intake(store, configuration, now=now) if projects else {"status": "disabled"}}
    return {"instance_id": store.config["instance_id"], "observed_at": (now or datetime.now(timezone.utc)).isoformat(), "results": results, "recovery": recovery, "meaning": "Intake receipts establish coverage and observations; they do not approve knowledge claims or complete commitments."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Local Store config.json")
    parser.add_argument("--intake-config", help="Private intake JSON inside the local state directory")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--sources-only", action="store_true")
    scope.add_argument("--projects-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        store = Store(args.config)
        configuration = load_intake_config(store, args.intake_config)
        result = run_pipeline(store, configuration, sources=not args.projects_only, projects=not args.sources_only)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (StoreError, OSError, ValueError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
