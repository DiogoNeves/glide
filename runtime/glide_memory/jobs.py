"""Bounded scheduled-job inputs and atomic durable checkpoints.

A checkpoint means inputs through a specific immutable bundle were processed. It
never means a source scan succeeded, an external action completed, or a whole
project is finished. New inputs after that bundle remain pending.
"""
from __future__ import annotations

import json

from .store import StoreError, IntegrityError, ConflictError, canonical, digest

JOBS = {"daily", "evening", "dream", "integrity"}
CHECKPOINT_PREFIX = "receipt:glide-job:"
STATE_MARKER = "<!-- glide:job-checkpoint -->\n```json\n"


def checkpoint_id(job_id):
    if job_id not in JOBS:
        raise StoreError("Unknown job; use daily, evening, dream, or integrity")
    return CHECKPOINT_PREFIX + job_id


def _read_checkpoint(record):
    if record is None:
        return {"processed_through": None}
    body = record["body"]
    if body.count(STATE_MARKER) != 1 or not body.endswith("\n```"):
        raise IntegrityError("Job checkpoint has an unrecognized format")
    try:
        payload = json.loads(body.split(STATE_MARKER, 1)[1][:-4])
    except ValueError as exc:
        raise IntegrityError("Job checkpoint contains invalid JSON") from exc
    if payload.get("schema") != 1 or payload.get("job_id") not in JOBS:
        raise IntegrityError("Job checkpoint has an unsupported schema or job")
    return payload


def _project_activity(record):
    if record.get("kind") != "receipt":
        return False
    # This fixed marker comes from the local intake protocol. Other receipt
    # prose mentioning a project is not promoted to an activity event.
    marker = "<!-- glide:intake-state -->\n```json\n"
    try:
        body = record["body"]
        return body.count(marker) == 1 and json.loads(body.split(marker, 1)[1][:-4]).get("kind") == "project-activity"
    except (KeyError, ValueError):
        return False


def _semantic_digest(record):
    return digest({key: value for key, value in record.items() if key not in {"revision", "recorded_at"}})


def _eligible(loaded, job_id, after_cursor):
    if after_cursor is not None and after_cursor not in {b["hash"] for b in loaded["bundles"]}:
        raise IntegrityError("Job checkpoint refers to missing history; wait for complete sync")
    started = after_cursor is None
    records, sources, selected = {}, {}, []
    for bundle in loaded["bundles"]:
        changed_records, changed_sources = [], []
        for record in bundle["records"]:
            fingerprint = _semantic_digest(record)
            changed = records.get(record["id"]) != fingerprint
            records[record["id"]] = fingerprint
            reserved = record["id"].startswith(CHECKPOINT_PREFIX)
            useful = record["kind"] != "receipt" or _project_activity(record)
            if changed and not reserved and useful:
                changed_records.append(record)
        for source in bundle["sources"]:
            fingerprint = (source["path"], source["sha256"])
            changed = sources.get(source["source_id"]) != fingerprint
            sources[source["source_id"]] = fingerprint
            if changed:
                changed_sources.append(source)
        if started and bundle["actor"] != "job:" + job_id and (changed_records or changed_sources):
            selected.append({"bundle": bundle["hash"], "sequence": bundle["sequence"], "recorded_at": bundle["recorded_at"], "actor": bundle["actor"], "records": changed_records, "sources": changed_sources})
        if bundle["hash"] == after_cursor:
            started = True
    return selected


def job_inputs(store, job_id, batch_limit=20):
    rid = checkpoint_id(job_id)
    if isinstance(batch_limit, bool) or not isinstance(batch_limit, int) or not 1 <= batch_limit <= 50:
        raise StoreError("Job batch_limit must be between 1 and 50 bundles")
    loaded = store._load()
    record = loaded["records"].get(rid)
    checkpoint = _read_checkpoint(record)
    if record and checkpoint["job_id"] != job_id:
        raise IntegrityError("Job checkpoint identity differs from its record")
    eligible = _eligible(loaded, job_id, checkpoint["processed_through"])
    chosen = eligible[:batch_limit]
    return {"job_id": job_id, "checkpoint_id": rid, "checkpoint_revision": record["revision"] if record else 0, "from_cursor": checkpoint["processed_through"], "processed_through": chosen[-1]["bundle"] if chosen else checkpoint["processed_through"], "observed_head": loaded["head"], "bundles": chosen, "pending_count": max(0, len(eligible) - len(chosen)), "has_work": bool(chosen)}



def _input_reference(kind, value, recorded_at):
    if kind == "record":
        return {"type": "record", "id": value["id"], "title": value["title"][:200],
                "kind": value["kind"], "status": value["status"], "revision": value["revision"],
                "get_args": {"record_id": value["id"], "at": recorded_at}}
    return {"type": "source", **{key: value[key] for key in
            ("source_id", "path", "sha256", "modified_at") if key in value},
            "title": value.get("title", "")[:200],
            "read_source_args": {"path": value["path"]},
            "freshness": "compare returned source hash with this historical revision"}


def compact_job_inputs(store, job_id, batch_limit=20):
    """Summarize immutable input bundles without loading archive bodies into chat.

    Preview entries are explicitly incomplete. Paging is read-only discovery;
    finish_job remains the only way to commit processing of the selected batch.
    """
    result = job_inputs(store, job_id, batch_limit)
    compact = []
    for bundle in result["bundles"]:
        preview = [_input_reference("record", r, bundle["recorded_at"]) for r in bundle["records"][:3]]
        preview += [_input_reference("source", s, bundle["recorded_at"]) for s in bundle["sources"][:2]]
        total = len(bundle["records"]) + len(bundle["sources"])
        compact.append({key: bundle[key] for key in ("bundle", "sequence", "recorded_at", "actor")} | {
            "record_count": len(bundle["records"]), "source_count": len(bundle["sources"]),
            "preview": preview, "preview_complete": len(preview) == total,
            "detail_args": {"job_id": job_id, "bundle": bundle["bundle"], "cursor": 0, "limit": 20}})
    return {**result, "bundles": compact, "detail_tool": "glide_job_input_page",
            "guidance": "Page relevant changes, then open exact record revisions or source passages. Archive indexing is not automatic promotion to knowledge. Only finish_job advances processing."}


def job_input_page(store, job_id, bundle, cursor=0, limit=20):
    """Return bounded references for one still-pending immutable input bundle."""
    rid = checkpoint_id(job_id)
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
        raise StoreError("Input cursor must be a nonnegative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise StoreError("Input page limit must be between 1 and 50")
    loaded = store._load()
    checkpoint_record = loaded["records"].get(rid)
    checkpoint = _read_checkpoint(checkpoint_record)
    if checkpoint_record and checkpoint["job_id"] != job_id:
        raise IntegrityError("Job checkpoint identity differs from its record")
    selected = next((entry for entry in _eligible(loaded, job_id, checkpoint["processed_through"])
                     if entry["bundle"] == bundle), None)
    if selected is None:
        raise ConflictError("Input bundle is not pending for this job; reload job inputs")
    entries = [("record", r) for r in selected["records"]] + [("source", s) for s in selected["sources"]]
    if cursor > len(entries):
        raise StoreError("Input cursor is past the end of the bundle")
    chosen = entries[cursor:cursor + limit]
    end = cursor + len(chosen)
    return {"job_id": job_id, "bundle": bundle, "recorded_at": selected["recorded_at"],
            "results": [_input_reference(kind, value, selected["recorded_at"]) for kind, value in chosen],
            "total": len(entries), "next_cursor": end if end < len(entries) else None,
            "checkpoint_revision": checkpoint_record["revision"] if checkpoint_record else 0,
            "processing_advanced": False}


def finish_job(store, job_id, processed_through, records, expected_revisions, summary, evidence, idempotency_key):
    rid = checkpoint_id(job_id)
    if not isinstance(records, list) or len(records) > 100 or not isinstance(expected_revisions, dict):
        raise StoreError("Finish a job with at most 100 output records and explicit expected revisions")
    if not isinstance(summary, str) or not summary.strip() or not isinstance(evidence, list) or not idempotency_key:
        raise StoreError("Job finish needs a summary, evidence list, and idempotency key")
    if any(r.get("id", "").startswith(CHECKPOINT_PREFIX) for r in records):
        raise StoreError("Do not submit checkpoint records; the job helper creates its own atomically")
    ids = [r.get("id") for r in records]
    if len(set(ids)) != len(ids) or set(expected_revisions) != set(ids) | {rid}:
        raise StoreError("Expected revisions must name every output plus this job checkpoint exactly once")
    request = {"job_id": job_id, "processed_through": processed_through, "records": records, "expected_revisions": expected_revisions, "summary": summary, "evidence": evidence}
    request_digest = digest(request)
    loaded = store._load()
    old = loaded["idempotency"].get(idempotency_key)
    if old:
        prior = next((r for r in old["records"] if r["id"] == rid), None)
        if old["actor"] != "job:" + job_id or not prior or _read_checkpoint(prior).get("request_digest") != request_digest:
            raise ConflictError("Idempotency key belongs to a different job result")
        return store.apply(old["proposal_id"], actor="job:" + job_id, idempotency_key=idempotency_key)
    previous = loaded["records"].get(rid)
    checkpoint = _read_checkpoint(previous)
    if expected_revisions[rid] != (previous["revision"] if previous else 0):
        raise ConflictError("Stale job checkpoint; reload pending inputs")
    positions = {bundle["hash"]: index for index, bundle in enumerate(loaded["bundles"])}
    if processed_through is not None and processed_through not in positions:
        raise StoreError("processed_through must identify an existing immutable history bundle")
    prior_cursor = checkpoint["processed_through"]
    if prior_cursor is not None and prior_cursor not in positions:
        raise IntegrityError("Checkpoint predecessor is missing")
    if positions.get(processed_through, -1) < positions.get(prior_cursor, -1):
        raise ConflictError("Job checkpoint cannot move backwards")
    eligible = _eligible(loaded, job_id, prior_cursor)
    processed = [entry for entry in eligible if positions[entry["bundle"]] <= positions.get(processed_through, -1)]
    if len(processed) > 50:
        raise StoreError("Finish at most 50 input bundles; checkpoint the bounded batch and resume the rest later")
    if not processed and not records:
        return {"committed": False, "status": "no-change", "job_id": job_id, "processed_through": prior_cursor, "pending_count": len(eligible)}
    if records and processed_through is None and loaded["head"] is not None:
        raise StoreError("Output-bearing jobs must name the input history boundary they evaluated")
    state = {"schema": 1, "job_id": job_id, "processed_through": processed_through, "previous_cursor": prior_cursor, "input_bundles": [entry["bundle"] for entry in processed], "output_records": ids, "summary": summary.strip(), "request_digest": request_digest}
    observed = {"job_id": job_id, "processed_through": processed_through, "input_bundles": state["input_bundles"], "output_records": ids, "meaning": "This is a processing receipt, not independent evidence of real-world completion."}
    observation = {"uri": "glide-job:" + job_id + ":" + digest(observed), "sha256": digest(observed), "quote": canonical(observed), "locator": "Deterministic job transaction observation", "source_kind": "tool-observation"}
    checkpoint_record = {"id": rid, "title": job_id.capitalize() + " processing checkpoint", "kind": "receipt", "origin": "ai", "status": "complete", "body": summary.strip() + "\n\n" + STATE_MARKER + json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n```", "sources": [*evidence, observation]}
    store._job_mutation = job_id
    try:
        proposal = store.propose([*records, checkpoint_record], expected_revisions=expected_revisions, rationale="Finish " + job_id + " processing and checkpoint its exact input boundary", idempotency_key=idempotency_key)
        return store.apply(proposal["proposal_id"], actor="job:" + job_id, idempotency_key=idempotency_key)
    finally:
        store._job_mutation = None
