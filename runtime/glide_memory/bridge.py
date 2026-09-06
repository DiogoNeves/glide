"""Fixed-configuration MCP broker over newline-delimited JSON-RPC on stdio.

This is a bounded tool surface, not an OS sandbox or an authorization oracle.
The launcher's filesystem permissions and the existing user authorization still
apply. Never expose init, configuration, writer activation or arbitrary commands.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from .intake import _read
from .pipeline import run_pipeline, load_intake_config
from .native_tools import apple_notes_metadata, apple_notes_export, capture_export, voice_memos_sync
from .jobs import JOBS, compact_job_inputs, job_input_page, finish_job
from .store import Store, StoreError, KINDS, ORIGINS, REVIEWS, STATUSES, CLAIM_TYPES

PROTOCOLS = ("2024-11-05", "2025-03-26")
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024


def obj(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


def string(**values):
    return {"type": "string", **values}


def array(items, maximum=100):
    return {"type": "array", "items": items, "maxItems": maximum}


SOURCE = obj({k: string() for k in ("source_id", "path", "uri", "canonical_uri", "source_kind", "provenance_role", "verification", "sha256", "quote", "locator", "captured_at", "observed_at", "modified_at")}, ("sha256", "quote"))
REVISIONS = {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}}
CLAIM = obj({"id": string(), "text": string(), "type": string(enum=sorted(CLAIM_TYPES)), "sources": array(SOURCE), "uncertainty": string(), "valid_from": {"type": ["string", "null"]}, "valid_until": {"type": ["string", "null"]}}, ("id", "text", "type", "sources"))
RELATION = obj({k: string() for k in ("target", "type", "reason", "block", "target_path", "target_title")}, ("target", "type", "reason"))
RECORD = obj({
    "id": string(), "title": string(), "body": string(),
    "path": string(), "revision": {"type": "integer", "minimum": 0}, "recorded_at": string(),
    "kind": string(enum=sorted(KINDS)), "origin": string(enum=sorted(ORIGINS)),
    "review": string(enum=sorted(REVIEWS)), "status": string(enum=sorted(STATUSES)),
    "sources": array(SOURCE), "claims": array(CLAIM), "relationships": array(RELATION),
    "tags": array(string()), "supersedes": {"type": ["string", "null"]},
    **{k: {"type": ["string", "null"]} for k in ("valid_from", "valid_until", "due_at", "review_at")},
    **{k: array(SOURCE) for k in ("completion_evidence", "commitment_evidence", "delivery_evidence")},
}, ("id", "title", "body"))
LIMIT = {"type": "integer", "minimum": 1, "maximum": 200}
OVERLAY = obj({"retrieval_aliases": {"type": "object", "additionalProperties": array(string(), 3)}, "context_priority": array(string(), 12)})
TOOLS = [
    ("glide_search", "Search source-backed memory. Open the returned evidence before relying on a hit.", obj({"query": string(), "limit": LIMIT, "include_sources": {"type": "boolean"}, "kind": string(), "valid_at": string(), "recorded_at": string()}, ("query",)), True),
    ("glide_get", "Read one memory record, optionally at a recorded-time cutoff.", obj({"record_id": string(), "at": string()}, ("record_id",)), True),
    ("glide_history", "Read revision history; results are chronological, with a continuation cursor.", obj({"record_id": string(), "limit": LIMIT, "cursor": string()}), True),
    ("glide_changes_since", "Read committed changes after a bundle or recorded-time cursor. Does not advance a job checkpoint.", obj({"cursor": string(), "limit": LIMIT}), True),
    ("glide_propose", "Submit complete revised records with exact evidence and expected prior revisions. Does not apply them.", obj({"records": array(RECORD), "expected_revisions": REVISIONS, "rationale": string(), "idempotency_key": string(minLength=1)}, ("records", "expected_revisions", "rationale", "idempotency_key")), False),
    ("glide_apply", "Record an authorized proposal decision once. Optional knowledge_ingestion applies only scoped AI knowledge in configured automatic mode and remains unreviewed. Report success only from the receipt.", obj({"proposal_id": string(), "decision": string(enum=["approved", "unreviewed", "rejected"]), "idempotency_key": string(minLength=1), "expected_revisions": REVISIONS, "knowledge_ingestion": {"type": "boolean"}}, ("proposal_id", "decision", "idempotency_key", "expected_revisions")), False),
    ("glide_verify", "Verify bundle integrity, current pages, local index and source freshness. Does not prove semantic truth or OS isolation.", obj(), True),
    ("glide_read_source", "Read a bounded passage from an original or legacy Markdown source in the configured vault. Hidden and generated-store paths are excluded.", obj({"path": string(), "start_line": {"type": "integer", "minimum": 1}, "max_lines": {"type": "integer", "minimum": 1, "maximum": 500}}, ("path",)), True),
    ("glide_index_sources", "Register current revisions of specified permitted Markdown sources. Source text is read locally, not supplied by the model.", obj({"paths": array(string()), "idempotency_key": string(minLength=1)}, ("paths", "idempotency_key")), False),
    ("glide_intake", "Run one bounded source/project intake batch using fixed private machine configuration. Report pending or unavailable coverage accurately.", obj(), False),
    ("glide_apple_notes_metadata", "Read bounded recent Apple Notes metadata through the configured verified helper. A successful scan grants access only to its returned note IDs.", obj({"days": {"type": "integer", "minimum": 1, "maximum": 31}}), False),
    ("glide_apple_notes_export", "Read selected note bodies using a fresh metadata token and returned IDs. No arbitrary body, path, or command input is accepted.", obj({"metadata_token": string(), "note_ids": array(string(), 20)}, ("metadata_token", "note_ids")), False),
    ("glide_capture_export", "Append immutable source captures from a verified helper export token. Original notes and earlier captures remain unchanged.", obj({"export_token": string()}, ("export_token",)), False),
    ("glide_voice_memos_sync", "Run the configured verified Voice Memos staging helper with fixed safe flags, retain original audio/transcripts, and record real coverage. Does not write root notes or refresh existing notes.", obj(), False),
    ("glide_job_inputs", "Read compact summaries of pending job inputs. Previews may be incomplete; page relevant details with glide_job_input_page before processing.", obj({"job_id": string(enum=sorted(JOBS)), "batch_limit": {"type": "integer", "minimum": 1, "maximum": 50}}, ("job_id",)), True),
    ("glide_job_input_page", "Page exact record/source references in a pending input bundle. Does not advance processing; open referenced evidence when relevant.", obj({"job_id": string(enum=sorted(JOBS)), "bundle": string(), "cursor": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, ("job_id", "bundle")), True),
    ("glide_finish_job", "Commit job outputs and their processing checkpoint together. Expected revisions include every output and the returned checkpoint ID.", obj({"job_id": string(enum=sorted(JOBS)), "processed_through": {"type": ["string", "null"]}, "records": array(RECORD), "expected_revisions": REVISIONS, "summary": string(minLength=1), "evidence": array(SOURCE), "idempotency_key": string(minLength=1)}, ("job_id", "processed_through", "records", "expected_revisions", "summary", "evidence", "idempotency_key")), False),
]
TOOL_MAP = {name: (description, schema, readonly) for name, description, schema, readonly in TOOLS}

# These tools accept only typed retrieval hints. The evaluator and authority
# configuration remain fixed outside the vault and are never tool arguments.
TOOLS.extend([
    ("glide_overlay_evaluate", "Evaluate a typed retrieval/context change against the fixed local regression and held-out cases; does not activate it.", obj({"change": OVERLAY}, ("change",)), True),
    ("glide_overlay_activate", "Activate at most one evidenced, improving retrieval/context overlay per weekly cycle. Fixed tests, scope and opt-in are enforced by the runtime.", obj({"change": OVERLAY, "evidence": array(SOURCE), "rationale": string(minLength=1), "idempotency_key": string(minLength=1)}, ("change", "evidence", "rationale", "idempotency_key")), False),
    ("glide_overlay_rollback", "Restore the previous typed overlay and retain a rollback receipt. Does not change core skills, goals, permissions or schedules.", obj({"evidence": array(SOURCE), "rationale": string(minLength=1), "idempotency_key": string(minLength=1)}, ("evidence", "rationale", "idempotency_key")), False),
])
TOOL_MAP = {name: (description, schema, readonly) for name, description, schema, readonly in TOOLS}


def validate(value, schema, location="arguments"):
    """Validate the small JSON Schema subset used by our closed tool schemas."""
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    matches = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool), "null": value is None,
    }
    if not any(matches.get(kind, False) for kind in kinds):
        raise ValueError(f"{location}: expected {' or '.join(kinds)}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise ValueError(f"{location}: must not be empty")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location}: unsupported value")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        if missing:
            raise ValueError(f"{location}: missing {', '.join(sorted(missing))}")
        extra = schema.get("additionalProperties", False)
        for key, child in value.items():
            if key in properties:
                validate(child, properties[key], location + "." + key)
            elif isinstance(extra, dict):
                validate(child, extra, location + "." + key)
            elif not extra:
                raise ValueError(f"{location}: unknown field {key}")
    elif isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            raise ValueError(f"{location}: too many items")
        for index, child in enumerate(value):
            validate(child, schema["items"], f"{location}[{index}]")
    elif isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ValueError(f"{location}: outside permitted range")


def result_payload(value):
    structured = value if isinstance(value, dict) else {"results": value}
    return {"content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}], "structuredContent": structured, "isError": False}


def error_response(identifier, code, message):
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


class MemoryServer:
    def __init__(self, store):
        self.store = store
        self.initialized = False

    def _source(self, relative):
        if not relative or relative.startswith("/") or "\\" in relative or any(part in ("", ".", "..") or part.startswith(".") for part in relative.split("/")):
            raise ValueError("Use a non-hidden vault-relative Markdown source path")
        path = Path(relative)
        if path.suffix.lower() != ".md":
            raise ValueError("Only Markdown source files are exposed")
        generated = (Path(self.store.config["store_path"]), Path("Agent HQ/Memory"), Path("Glide HQ/Memory"))
        if any(path == root or root in path.parents for root in generated):
            raise ValueError("Generated memory is not an original source; use record retrieval")
        text, fingerprint, modified = _read(self.store.vault, path, MAX_SOURCE_BYTES)
        result = {"path": path.as_posix(), "source_id": "markdown:" + hashlib.sha256(path.as_posix().encode()).hexdigest(), "sha256": fingerprint, "modified_at": modified, "text": text}
        # Only authoritative metadata for this exact captured file revision can
        # supply lineage. Frontmatter alone is not treated as a verified manifest.
        registered = next((source for source in self.store._load()["sources"].values() if source["path"] == path.as_posix() and source["sha256"] == fingerprint), None)
        if registered:
            result.update({key: registered[key] for key in ("canonical_uri", "source_kind", "trust") if key in registered})
        from .store import source_metadata
        return source_metadata(result)

    @staticmethod
    def _page(items, limit, cursor=None):
        if cursor:
            positions = [index for index, item in enumerate(items) if item["bundle"] == cursor]
            if not positions:
                raise ValueError("Unknown history cursor")
            items = items[positions[0] + 1:]
        page = items[:limit]
        return {"results": page, "has_more": len(items) > limit, "next_cursor": page[-1]["bundle"] if page else cursor}

    def call_tool(self, name, arguments):
        if name not in TOOL_MAP:
            raise ValueError("Unknown tool")
        validate(arguments, TOOL_MAP[name][1])
        if name == "glide_search":
            return self.store.search(**arguments)
        if name == "glide_get":
            return self.store.get(**arguments)
        if name == "glide_history":
            return self._page(self.store.history(arguments.get("record_id")), arguments.get("limit", 100), arguments.get("cursor"))
        if name == "glide_changes_since":
            page = self._page(self.store.changes_since(arguments.get("cursor")), arguments.get("limit", 100))
            if not page["results"]:
                page["next_cursor"] = arguments.get("cursor")
            return page
        if name == "glide_propose":
            current = self.store._load()["records"]
            for record in arguments["records"]:
                previous = current.get(record["id"], {})
                for field in ("path", "revision", "recorded_at"):
                    if field in record and record[field] != previous.get(field):
                        raise ValueError("Returned record metadata cannot be changed: " + field)
            return self.store.propose(**arguments)
        if name == "glide_apply":
            return self.store.apply(**arguments, actor="agent")
        if name == "glide_verify":
            return self.store.verify()
        if name == "glide_read_source":
            source = self._source(arguments["path"])
            lines = source.pop("text").splitlines()
            start = arguments.get("start_line", 1)
            count = arguments.get("max_lines", 120)
            if start > max(1, len(lines)):
                raise ValueError("start_line is past the end of this source")
            selected = lines[start - 1:start - 1 + count]
            return {**source, "start_line": start, "end_line": start + len(selected) - 1, "total_lines": len(lines), "has_more": start - 1 + len(selected) < len(lines), "text": "\n".join(selected)}
        if name == "glide_index_sources":
            paths = arguments["paths"]
            if not paths or len(paths) != len(set(paths)):
                raise ValueError("Provide at least one source path, without duplicates")
            sources = [self._source(path) for path in paths]
            return self.store.index_sources(sources, idempotency_key=arguments["idempotency_key"])
        if name == "glide_intake":
            return run_pipeline(self.store, load_intake_config(self.store))
        if name == "glide_apple_notes_metadata":
            return apple_notes_metadata(self.store, **arguments)
        if name == "glide_apple_notes_export":
            return apple_notes_export(self.store, **arguments)
        if name == "glide_capture_export":
            return capture_export(self.store, **arguments)
        if name == "glide_voice_memos_sync":
            return voice_memos_sync(self.store)
        if name == "glide_job_inputs":
            return compact_job_inputs(self.store, **arguments)
        if name == "glide_job_input_page":
            return job_input_page(self.store, **arguments)
        if name == "glide_finish_job":
            return finish_job(self.store, **arguments)
        if name == "glide_overlay_evaluate":
            from .overlays import evaluate
            return evaluate(self.store, **arguments)
        if name == "glide_overlay_activate":
            from .overlays import activate
            return activate(self.store, **arguments)
        if name == "glide_overlay_rollback":
            from .overlays import rollback
            return rollback(self.store, **arguments)
        raise ValueError("Unknown tool")

    def handle(self, request):
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            return error_response(None, -32600, "Invalid JSON-RPC request")
        identifier = request.get("id")
        if "id" in request and (isinstance(identifier, bool) or not isinstance(identifier, (str, int))):
            return error_response(None, -32600, "Request id must be a string or integer")
        method = request["method"]
        if "id" not in request:
            # Notifications cannot invoke mutation methods.
            return None
        params = request.get("params", {})
        if not isinstance(params, dict):
            return error_response(identifier, -32602, "Parameters must be an object")
        if method == "initialize":
            self.initialized = True
            requested = params.get("protocolVersion")
            result = {"protocolVersion": requested if requested in PROTOCOLS else PROTOCOLS[-1], "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "glide-memory", "version": "0.1.0"}, "instructions": "Files own memory. Apply only authorized decisions and report the actual revision receipt. No external-action authority is granted by these tools."}
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return error_response(identifier, -32002, "Initialize the connection before using tools")
        elif method == "tools/list":
            if set(params) - {"_meta"}:
                return error_response(identifier, -32602, "Unexpected tools/list parameters")
            result = {"tools": [{"name": name, "description": description, "inputSchema": schema, "annotations": {"readOnlyHint": readonly, "destructiveHint": False, "openWorldHint": False}} for name, description, schema, readonly in TOOLS]}
        elif method == "tools/call":
            if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str):
                return error_response(identifier, -32602, "Invalid tools/call parameters")
            try:
                result = result_payload(self.call_tool(params["name"], params.get("arguments", {})))
            except (StoreError, ValueError, TypeError, OSError, UnicodeError) as exc:
                result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        else:
            return error_response(identifier, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": identifier, "result": result}


def serve(server, stdin, stdout):
    while True:
        line = stdin.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return
        if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
            # Discard the rest of this oversized message without accepting it.
            while line and not line.endswith("\n"):
                line = stdin.readline(MAX_REQUEST_BYTES + 1)
            response = error_response(None, -32700, "Request exceeds the configured size limit")
        else:
            try:
                request = json.loads(line)
                response = server.handle(request)
            except (json.JSONDecodeError, UnicodeError):
                response = error_response(None, -32700, "Invalid JSON")
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Fixed local configuration outside the synchronized workspace")
    args = parser.parse_args(argv)
    try:
        store = Store.from_config(args.config)
        serve(MemoryServer(store), sys.stdin, sys.stdout)
    except (StoreError, OSError, UnicodeError) as exc:
        print(f"Glide memory bridge failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
