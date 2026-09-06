"""Opt-in, evidence-backed retrieval/context refinements with frozen-case gates.

Only typed data is accepted. No prompts, permissions, schedules, provider choices,
commands, closure rules or arbitrary skill text can be activated by this mechanism.
"""
from __future__ import annotations

import datetime as dt
import contextlib
import fcntl
import hashlib
import json
from pathlib import Path

from .store import StoreError, canonical, digest, file_hash, now, no_symlinks

RECORD_ID = "workflow:glide-learned-retrieval"


def normalize(change, records):
    if not isinstance(change, dict) or set(change) - {"retrieval_aliases", "context_priority"}:
        raise StoreError("Learned changes support only retrieval_aliases and context_priority")
    aliases = change.get("retrieval_aliases", {})
    priority = change.get("context_priority", [])
    if not isinstance(aliases, dict) or len(aliases) > 20 or not isinstance(priority, list) or len(priority) > 12:
        raise StoreError("Learned changes exceed their bounded size")
    clean = {}
    for query, alternatives in aliases.items():
        if not isinstance(query, str) or not query.strip() or len(query) > 160 or any(ord(c) < 32 for c in query):
            raise StoreError("Alias query must be a short, nonempty string")
        if not isinstance(alternatives, list) or not 1 <= len(alternatives) <= 3:
            raise StoreError("Each alias must have one to three alternative queries")
        if any(not isinstance(s, str) or not s.strip() or len(s) > 160 or any(ord(c) < 32 for c in s) for s in alternatives):
            raise StoreError("Alias terms must be short query strings")
        clean[query.casefold().strip()] = list(dict.fromkeys(s.strip() for s in alternatives))
    if len(set(priority)) != len(priority) or any(rid not in records or records[rid]["kind"] == "workflow" for rid in priority):
        raise StoreError("Context priority must reference distinct existing non-workflow records")
    return {"retrieval_aliases": clean, "context_priority": priority}


def payload_from_record(record):
    if not record or record.get("status") != "active":
        return {"retrieval_aliases": {}, "context_priority": []}
    try:
        payload = json.loads(record["body"].rsplit("```json\n", 1)[1].rsplit("\n```", 1)[0])
        return payload["change"]
    except (IndexError, KeyError, ValueError) as exc:
        raise StoreError("Learned workflow has malformed typed data; stop instead of guessing") from exc


def current_change(store):
    loaded = store._load()
    return normalize(payload_from_record(loaded["records"].get(RECORD_ID)), loaded["records"])


def search_with_change(store, query, change, *, limit=20, **kwargs):
    queries = [query] + change["retrieval_aliases"].get(query.casefold().strip(), [])
    seen, result = set(), []
    for variant in queries:
        for hit in store.search(variant, limit=limit, use_overlays=False, **kwargs):
            if hit["id"] not in seen:
                seen.add(hit["id"])
                result.append({**hit, "matched_query": variant})
    return result[:limit]


def _configuration(store):
    config = json.loads(store.config_path.read_text()).get("learned_overlays", {})
    if not config.get("enabled"):
        raise StoreError("Learned overlays are disabled; configure a frozen case set before enabling")
    case_path = no_symlinks(Path(config.get("cases_path", "")))
    if case_path.is_relative_to(store.vault) or not case_path.is_file():
        raise StoreError("Frozen evaluator cases must be a local file outside the vault")
    if file_hash(case_path) != config.get("cases_sha256"):
        raise StoreError("Frozen evaluator cases changed; do not retry against an altered test set")
    case_set = json.loads(case_path.read_text())
    cases = case_set.get("cases", [])
    if case_set.get("schema") != 1 or {c.get("split") for c in cases} != {"regression", "heldout"}:
        raise StoreError("Evaluation needs fixed regression and held-out cases")
    ids = [c.get("id") for c in cases]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise StoreError("Evaluation case IDs must be unique")
    return config, cases


def _context_ids(store, change, view, limit):
    loaded = store._load()
    priority = {rid: index for index, rid in enumerate(change["context_priority"])}
    records = sorted(loaded["records"].values(), key=lambda r: (r.get("due_at") or "9999", priority.get(r["id"], 999), r["title"], r["id"]))
    if view == "Now":
        contexts = sorted([r for r in records if r["kind"] == "context" and r["status"] == "active" and "context:now" in r.get("tags", [])], key=lambda r: (r["recorded_at"], r["id"]), reverse=True)
        as_of = loaded["bundles"][-1]["recorded_at"] if loaded["bundles"] else "0001-01-01T00:00:00.000000Z"
        operations = [r for r in records if r["kind"] == "operation" and (r["status"] in {"committed", "blocked"} or (r["status"] in {"open", "waiting"} and (r.get("due_at") or (r.get("review_at") and r["review_at"] <= as_of))))]
        selected = contexts[:1] + operations[:5]
    elif view == "Durable":
        selected = [r for r in records if r["kind"] in {"knowledge", "context"} and r["status"] not in {"inactive", "superseded"}]
    else:
        raise StoreError("Context evaluation supports Now or Durable")
    return [r["id"] for r in selected[:limit]]


def _evaluate(store, change, cases):
    results = []
    for case in cases:
        if not isinstance(case.get("expected_ids"), list) or not case["expected_ids"]:
            raise StoreError("Every frozen case needs explicit expected record IDs")
        limit = case.get("limit", 5)
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            raise StoreError("Evaluation result limits must be 1 to 20")
        if case.get("view"):
            actual = _context_ids(store, change, case["view"], limit)
            passed = actual[:len(case["expected_ids"])] == case["expected_ids"]
        else:
            actual = [r["id"] for r in search_with_change(store, case["query"], change, limit=limit, include_sources=False)]
            passed = set(case["expected_ids"]).issubset(actual)
        results.append({"id": case["id"], "split": case["split"], "passed": passed, "actual_ids": actual})
    return results


def evaluate(store, change):
    config, cases = _configuration(store)
    loaded = store._load()
    candidate = normalize(change, loaded["records"])
    baseline = normalize(payload_from_record(loaded["records"].get(RECORD_ID)), loaded["records"])
    before, after = _evaluate(store, baseline, cases), _evaluate(store, candidate, cases)
    improvement = any(not old["passed"] and new["passed"] for old, new in zip(before, after))
    accepted = all(row["passed"] for row in after) and improvement
    return {"schema": 1, "candidate_digest": digest(candidate), "cases_sha256": config["cases_sha256"], "base_head": loaded["head"], "base_revision": loaded["records"].get(RECORD_ID, {}).get("revision", 0), "baseline": before, "candidate": after, "all_cases_pass": all(r["passed"] for r in after), "improvement": improvement, "accepted": accepted, "change": candidate}


def _week(timestamp):
    value = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    iso = value.date().isocalendar()
    return iso.year, iso.week


def _write(store, payload, evidence, rationale, key, expected_revision=None):
    try:
        previous = store.get(RECORD_ID)
        revision = previous["revision"]
    except StoreError:
        previous, revision = None, 0
    if expected_revision is not None and revision != expected_revision:
        raise StoreError("Learned workflow changed during evaluation; refresh before activating")
    body = "Typed retrieval and context refinements. Evidence, fixed-case results and the preceding configuration are retained for review and rollback.\n\n```json\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n```"
    record = {"id": RECORD_ID, "title": "Learned retrieval and context", "kind": "workflow", "origin": "ai", "status": "active", "body": body, "sources": evidence, "review": "unreviewed"}
    store._overlay_mutation = True
    try:
        proposal = store.propose([record], expected_revisions={RECORD_ID: revision}, rationale=rationale, idempotency_key=key)
        return store.apply(proposal["proposal_id"], decision="unreviewed", actor="tested-typed-overlay", idempotency_key=key)
    finally:
        store._overlay_mutation = False


def _activate(store, change, *, evidence, rationale, idempotency_key):
    loaded = store._load()
    existing = loaded["idempotency"].get(idempotency_key)
    if existing:
        previous = existing.get("records", [])
        if existing.get("actor") == "typed-overlay-review":
            raise StoreError("This candidate was already rejected and recorded; do not retry until conditions change")
        if existing.get("actor") != "tested-typed-overlay" or not previous or payload_from_record(previous[0]) != normalize(change, loaded["records"]):
            raise StoreError("Idempotency key belongs to another change")
        return store.apply(existing["proposal_id"], idempotency_key=idempotency_key, actor="tested-typed-overlay")
    # Fixed regressions and held-out cases run here; a caller-provided pass flag
    # is never an activation credential.
    for event in loaded["bundles"]:
        candidate_attempt = event["actor"] == "typed-overlay-review" or (event["actor"] == "tested-typed-overlay" and any('"action": "activate"' in r["body"] for r in event["records"]))
        if candidate_attempt and _week(event["recorded_at"]) == _week(now()):
            raise StoreError("The weekly candidate budget is used; do not keep retrying candidates")
    report = evaluate(store, change)
    if not report["accepted"]:
        rid = "review:glide-learned-candidate:" + digest({"key": idempotency_key})[:24]
        body = "A bounded learned-change candidate was rejected by fixed regression and held-out cases. No retrieval change was activated.\n\n```json\n" + json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n```"
        record = {"id": rid, "title": "Rejected learned retrieval candidate " + report["candidate_digest"][:8], "kind": "review", "origin": "ai", "status": "inactive", "body": body, "sources": evidence}
        store._overlay_mutation = True
        try:
            proposal = store.propose([record], expected_revisions={rid: 0}, rationale=rationale, idempotency_key=idempotency_key)
            receipt = store.apply(proposal["proposal_id"], actor="typed-overlay-review", idempotency_key=idempotency_key)
        finally:
            store._overlay_mutation = False
        raise StoreError("Candidate rejected and durably recorded in " + receipt["bundle"] + "; it must pass every fixed case and improve an observed failure")
    before = current_change(store)
    payload = {"action": "activate", "change": report["change"], "previous_change": before, "evaluation": report}
    # The protected writer serializes Store.propose/apply. The recorded base
    # head is checked before proposal creation; stale evaluations must rerun.
    if store._load()["head"] != report["base_head"]:
        raise StoreError("Evidence changed during evaluation; rerun against the new head")
    return _write(store, payload, evidence, rationale, idempotency_key, report["base_revision"])


def _rollback(store, *, evidence, rationale, idempotency_key):
    # Recovery must remain available when activation is disabled or its frozen
    # evaluator is missing/broken. The writer and retained typed history still
    # validate the rollback; no new behavior is introduced here.
    existing = store._load()["idempotency"].get(idempotency_key)
    if existing:
        if existing.get("actor") != "tested-typed-overlay" or not any('"action": "rollback"' in r["body"] for r in existing["records"]):
            raise StoreError("Idempotency key belongs to another change")
        return store.apply(existing["proposal_id"], idempotency_key=idempotency_key, actor="tested-typed-overlay")
    previous = store.get(RECORD_ID)
    payload = json.loads(previous["body"].rsplit("```json\n", 1)[1].rsplit("\n```", 1)[0])
    if payload.get("action") != "activate":
        raise StoreError("The current learned change has already been rolled back")
    restored_change = normalize(payload["previous_change"], store._load()["records"])
    reverted = {"action": "rollback", "change": restored_change, "rolled_back_revision": previous["revision"], "rollback_reason": rationale}
    return _write(store, reverted, evidence, rationale, idempotency_key, previous["revision"])


@contextlib.contextmanager
def _operation_lock(store):
    # Separate from the Store commit lock so nested propose/apply calls remain
    # safe. Serialize evaluation-plus-budget-check, including failed candidates.
    path = no_symlinks(store.state_dir / "overlay.lock")
    with path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def activate(store, change, *, evidence, rationale, idempotency_key):
    with _operation_lock(store):
        return _activate(store, change, evidence=evidence, rationale=rationale, idempotency_key=idempotency_key)


def rollback(store, *, evidence, rationale, idempotency_key):
    with _operation_lock(store):
        return _rollback(store, evidence=evidence, rationale=rationale, idempotency_key=idempotency_key)
