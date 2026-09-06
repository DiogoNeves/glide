"""Deterministic Markdown authority, bounded writes, and a disposable SQLite index.

This module is a filesystem broker, not an OS sandbox. Callers must run model/source
readers with separate read-only permissions. The one-writer marker is a handover
check, not a distributed lock: stop the previous writer before activating another.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import uuid

SCHEMA = 1
FORMAT_VERSION = 1
MARKER = "<!-- glide:payload -->\n```json\n"
KINDS = {"knowledge", "operation", "decision", "workflow", "review", "context", "receipt"}
ORIGINS = {"ai", "human", "imported"}
REVIEWS = {"unreviewed", "approved", "rejected", "contested"}
STATUSES = {"candidate", "committed", "open", "waiting", "sent", "delivered", "complete", "cancelled", "active", "inactive", "historical", "superseded", "blocked"}
CLAIM_TYPES = {"fact", "historical-record", "stated-view", "ai-inference", "preference", "hypothesis", "observation", "decision"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
CLAIM_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class StoreError(RuntimeError):
    pass


class ConflictError(StoreError):
    pass


class IntegrityError(StoreError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: str | None, *, optional=True) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise StoreError("Timestamp must be an ISO 8601 string with a timezone")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StoreError("Invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise StoreError("Timestamp needs a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def no_symlinks(path: Path) -> Path:
    """Reject symlinks in existing ancestors, including a final symlink."""
    path = Path(os.path.abspath(os.path.expanduser(str(path))))
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise StoreError(f"Symlink paths are not allowed: {part}")
    return path


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(p in {".", ".."} for p in path.parts) or "\\" in value:
        raise StoreError("Expected a safe relative path")
    return path


def safe_child(root: Path, value: str) -> Path:
    rel = relative_path(value)
    path = no_symlinks(root.joinpath(*rel.parts))
    if not path.is_relative_to(root):
        raise StoreError("Path escapes its allowed root")
    return path


def atomic_write(path: Path, text: str, *, immutable=False):
    no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_text() != text:
            raise ConflictError(f"Immutable file differs: {path.name}")
        return
    fd, temp_name = tempfile.mkstemp(prefix=".glide-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if immutable:
            try:
                os.link(temp_name, path)
            except FileExistsError:
                if path.read_text() != text:
                    raise ConflictError(f"Immutable file differs: {path.name}")
            os.unlink(temp_name)
        else:
            os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def payload_markdown(intro: str, payload: dict) -> str:
    return intro.rstrip() + "\n\n" + MARKER + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n```\n"


def read_payload(path: Path) -> dict:
    try:
        raw = no_symlinks(path).read_text(encoding="utf-8")
        _, data = raw.rsplit(MARKER, 1)
        if not data.endswith("\n```\n"):
            raise ValueError("Missing payload terminator")
        result = json.loads(data[:-5])
        if not isinstance(result, dict):
            raise ValueError("Expected object")
        return result
    except (OSError, ValueError, KeyError) as exc:
        raise IntegrityError(f"Invalid Markdown payload in {path.name}: {exc}") from exc


def archived_history_path(path: str | None) -> bool:
    if not path:
        return False
    parts = tuple(part.casefold() for part in PurePosixPath(path).parts)
    return len(parts) > 2 and parts[:2] in {("agent hq", "legacy memory"), ("glide hq", "legacy memory")}


def source_metadata(source: dict) -> dict:
    result = dict(source)
    if archived_history_path(result.get("path")):
        result.update(source_kind="archived-ai-history", provenance_role="non-independent-history")
    return result


def record_metadata(record: dict) -> dict:
    # Read-time annotations derive from the source path, so legacy registry and
    # record payloads need no rewriting or immutable-format change.
    result = json.loads(canonical(record))
    for key in ("sources", "commitment_evidence", "delivery_evidence", "completion_evidence"):
        if key in result:
            result[key] = [source_metadata(source) for source in result[key]]
    for claim in result.get("claims", []):
        claim["sources"] = [source_metadata(source) for source in claim["sources"]]
    return result


def slug(title: str) -> str:
    # Cross-platform filenames; avoid Obsidian link metacharacters as well.
    clean = re.sub(r'[<>:"/\\|?*\[\]#^\x00-\x1f]', " ", title)
    clean = re.sub(r"\s+", " ", clean).strip(" .")[:100].rstrip(" .")
    if not clean:
        clean = "Untitled"
    if clean.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        clean = "Note " + clean
    return clean


class Store:
    def __init__(self, config_path: str | Path):
        self.config_path = no_symlinks(Path(config_path))
        try:
            self.config = json.loads(self.config_path.read_text())
        except (OSError, ValueError) as exc:
            raise StoreError("Cannot read Glide configuration") from exc
        if self.config.get("schema") != SCHEMA:
            raise StoreError("Unsupported configuration schema")
        self.vault = no_symlinks(Path(self.config["vault"]))
        self.state_dir = no_symlinks(Path(self.config["state_dir"]))
        self.store = safe_child(self.vault, self.config["store_path"])
        if self.state_dir.is_relative_to(self.vault) or self.vault.is_relative_to(self.state_dir):
            raise StoreError("Local runtime state must be physically separate from the vault")
        if not self.config_path.is_relative_to(self.state_dir):
            raise StoreError("Configuration must live in the local state directory")
        self.db_path = self.state_dir / "index.sqlite3"
        self.adapter = self.config["adapter"]
        if self.adapter not in {"obsidian", "markdown"}:
            raise StoreError("Unknown Markdown adapter")
        self.review_settings()
        manifest = read_payload(self.store / "Store.md")
        if manifest.get("instance_id") != self.config.get("instance_id") or manifest.get("schema") != SCHEMA:
            raise IntegrityError("Instance or schema mismatch")
        if manifest.get("adapter") != self.adapter:
            raise IntegrityError("Adapter does not match the durable store")

    def review_settings(self):
        """Local presentation and bounded knowledge-ingestion preferences."""
        mode = self.config.get("knowledge_review", "manual")
        ui = self.config.get("review_ui", "text")
        prefixes = self.config.get("automatic_source_prefixes", [])
        if mode not in {"manual", "automatic"} or ui not in {"text", "interactive"}:
            raise StoreError("Use knowledge_review manual|automatic and review_ui text|interactive")
        if not isinstance(prefixes, list) or any(not isinstance(p, str) for p in prefixes):
            raise StoreError("automatic_source_prefixes must be a list of vault-relative paths")
        for prefix in prefixes:
            raw = prefix.removesuffix("/")
            if not raw or any(part in {"", ".", ".."} or part.startswith(".") for part in raw.split("/")):
                raise StoreError("Automatic source prefixes must name explicit non-hidden files or folders")
            safe_child(self.vault, raw)
        if mode == "automatic" and not prefixes:
            raise StoreError("Automatic knowledge ingestion needs explicit automatic_source_prefixes")
        return {"knowledge_review": mode, "review_ui": ui, "automatic_source_prefixes": list(prefixes), "job_knowledge_policy": mode if "knowledge_review" in self.config else "legacy-authorized"}

    @classmethod
    def from_config(cls, path):
        return cls(path)

    @classmethod
    def initialize(cls, vault, state_dir, store_path="Agent HQ/Memory", adapter="obsidian"):
        vault, state_dir = no_symlinks(Path(vault)), no_symlinks(Path(state_dir))
        if not vault.is_dir() or state_dir.is_relative_to(vault) or vault.is_relative_to(state_dir):
            raise StoreError("Use an existing vault and a separate local state directory")
        if adapter not in {"obsidian", "markdown"}:
            raise StoreError("Adapter must be obsidian or markdown")
        store = safe_child(vault, store_path)
        config_path = state_dir / "config.json"
        if config_path.exists():
            existing = cls(config_path)
            if existing.vault != vault or existing.store != store or existing.adapter != adapter:
                raise ConflictError("State directory is already configured for another store")
            return existing
        if (store / "Store.md").exists():
            manifest = read_payload(store / "Store.md")
            if manifest.get("schema") != SCHEMA or manifest.get("adapter") != adapter:
                raise StoreError("Existing store schema or adapter differs")
        else:
            if store.exists() and any(store.iterdir()):
                raise StoreError("Refusing to initialize over a nonempty unrecognized directory")
            manifest = {"schema": SCHEMA, "instance_id": str(uuid.uuid4()), "adapter": adapter, "created_at": now()}
            store.mkdir(parents=True, exist_ok=True)
            atomic_write(store / "Store.md", payload_markdown("Portable memory store. Immutable bundles are authoritative. Current pages and the local search index can be rebuilt.", manifest), immutable=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(state_dir, 0o700)
        for directory in ("Bundles", "Proposals", "Records", "Views"):
            safe_child(store, directory).mkdir(exist_ok=True)
        config = {"schema": SCHEMA, "instance_id": manifest["instance_id"], "machine_id": str(uuid.uuid4()), "vault": str(vault), "state_dir": str(state_dir), "store_path": str(relative_path(store_path)), "adapter": adapter, "writer_active": False, "knowledge_review": "manual", "review_ui": "text", "automatic_source_prefixes": []}
        atomic_write(config_path, json.dumps(config, indent=2) + "\n", immutable=True)
        result = cls(config_path)
        result.rebuild()
        return result

    @contextlib.contextmanager
    def _lock(self):
        path = no_symlinks(self.state_dir / "writer.lock")
        with path.open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _save_config(self):
        atomic_write(self.config_path, json.dumps(self.config, indent=2) + "\n")

    def activate_writer(self, *, old_writer_stopped=False):
        if not old_writer_stopped:
            raise StoreError("Confirm old_writer_stopped after stopping the previous writer; Sync is not a lock")
        with self._lock():
            self._load()
            owner = {"machine_id": self.config["machine_id"], "active": True, "activated_at": now(), "old_writer_stopped": True}
            atomic_write(self.store / "Writer.md", payload_markdown("Writer handover marker. This is not a distributed lock; only one machine may execute writer jobs.", owner))
            self.config["writer_active"] = True
            self._save_config()
        return owner

    def deactivate_writer(self):
        with self._lock():
            path = self.store / "Writer.md"
            owner = read_payload(path) if path.exists() else {}
            if owner.get("machine_id") == self.config["machine_id"]:
                owner.update(active=False, deactivated_at=now())
                atomic_write(path, payload_markdown("Writer handover marker. This is not a distributed lock; only one machine may execute writer jobs.", owner))
            self.config["writer_active"] = False
            self._save_config()
        return {"writer_active": False}

    def _require_writer(self):
        # Reload to prevent an old in-process Store object ignoring deactivation.
        self.config = json.loads(self.config_path.read_text())
        owner_path = self.store / "Writer.md"
        owner = read_payload(owner_path) if owner_path.exists() else {}
        if not self.config.get("writer_active") or not owner.get("active") or owner.get("machine_id") != self.config["machine_id"]:
            raise StoreError("Writer is disabled or this machine no longer owns the writer marker")

    def _proposal_markdown(self, proposal):
        intro = f"**Review proposal:** {proposal['proposal_id']}\n\n**Reason:** {proposal['rationale']}\n\n**Created:** {proposal['created_at']}\n\n"
        for record in proposal["records"]:
            intro += f"## {record['title']}\n\n{record['body']}\n\n"
        return payload_markdown(intro, proposal)

    def _bundle_markdown(self, bundle):
        if bundle.get("format_version") != 1:
            raise IntegrityError("Unsupported immutable Markdown format; use a compatible reader or explicit migration")
        return self._bundle_markdown_v1(bundle)

    def _bundle_markdown_v1(self, bundle):
        # Frozen format. Future renderers must preserve this reader and the
        # golden format-v1 fixture; never silently rerender old bundles.
        intro = f"**Change:** {bundle['sequence']}\n\n**Recorded:** {bundle['recorded_at']}\n\n**Reason:** {bundle['rationale']}\n\n**Parent:** {bundle['parent'] or 'initial'}\n\n**Review:** {bundle['decision']}\n\n"
        for record in bundle["records"]:
            from_path = f"Bundles/{bundle['sequence']:08d}-{bundle['hash']}.md"
            rendered = self._record_markdown_v1(record, from_path=from_path)
            intro += f"## {record['title']} · revision {record['revision']}\n\n{rendered}\n\n"
        if bundle["sources"]:
            intro += "## Source observations\n\n" + "\n".join(f"- {s['path']} · `{s['sha256']}`" for s in bundle["sources"]) + "\n"
        return payload_markdown(intro, bundle)

    def _load(self):
        bundles = []
        children = {}
        seen_hashes = set()
        for path in sorted(safe_child(self.store, "Bundles").glob("*.md")):
            bundle = read_payload(path)
            body = {k: v for k, v in bundle.items() if k != "hash"}
            if bundle.get("schema") != SCHEMA or bundle.get("instance_id") != self.config["instance_id"] or digest(body) != bundle.get("hash"):
                raise IntegrityError(f"Invalid bundle hash, schema, or instance: {path.name}")
            if path.read_text() != self._bundle_markdown(bundle):
                raise IntegrityError(f"Bundle Markdown differs from its canonical payload: {path.name}")
            expected_name = f"{bundle['sequence']:08d}-{bundle['hash']}.md"
            if path.name != expected_name:
                raise IntegrityError("Unexpected or duplicated bundle filename")
            if bundle["hash"] in seen_hashes or bundle["parent"] in children:
                raise ConflictError("Duplicate or divergent bundle history; reconcile before writing")
            seen_hashes.add(bundle["hash"])
            children[bundle["parent"]] = bundle
        parent = None
        records, sources, idempotency = {}, {}, {}
        while parent in children:
            bundle = children.pop(parent)
            if bundle["sequence"] != len(bundles) + 1:
                raise IntegrityError("Missing or invalid predecessor sequence")
            if bundles and bundle["recorded_at"] <= bundles[-1]["recorded_at"]:
                raise IntegrityError("Recorded time must increase with committed history")
            for record in bundle["records"]:
                previous = records.get(record["id"])
                if record["revision"] != (previous["revision"] if previous else 0) + 1:
                    raise IntegrityError("Record revision chain is incomplete")
                if previous and (record["origin"] != previous["origin"] or record["path"] != previous["path"]):
                    raise IntegrityError("Origin and stable projection paths cannot change")
                records[record["id"]] = record
            for source in bundle["sources"]:
                sources[source["source_id"]] = source
            key = bundle["idempotency_key"]
            if key in idempotency:
                raise IntegrityError("Repeated idempotency identity in history")
            idempotency[key] = bundle
            bundles.append(bundle)
            parent = bundle["hash"]
        if children:
            raise IntegrityError("Incomplete sync: missing predecessor or disconnected history")
        return {"bundles": bundles, "records": records, "sources": sources, "idempotency": idempotency, "head": parent}

    def _retained_evidence(self, loaded, additional_records=()):
        retained = set()
        records = [r for b in loaded["bundles"] for r in b["records"]] + list(additional_records)
        for record in records:
            groups = [record.get("sources", [])] + [c.get("sources", []) for c in record.get("claims", [])]
            groups += [record.get(key, []) for key in ("commitment_evidence", "delivery_evidence", "completion_evidence")]
            for group in groups:
                for source in group:
                    if source.get("path"):
                        retained.add((source["path"], source["sha256"], source["quote"]))
        return retained

    def _set_evidence_context(self, loaded, additional_records=()):
        self._validated_evidence = self._retained_evidence(loaded, additional_records)
        lineages = {}
        for bundle in loaded["bundles"]:
            for source in bundle["sources"]:
                if source.get("canonical_uri"):
                    lineages.setdefault((source["path"], source["sha256"]), set()).add(source["canonical_uri"])
        for record in [r for b in loaded["bundles"] for r in b["records"]] + list(additional_records):
            groups = [record.get("sources", [])] + [c.get("sources", []) for c in record.get("claims", [])]
            groups += [record.get(key, []) for key in ("commitment_evidence", "delivery_evidence", "completion_evidence")]
            for group in groups:
                for source in group:
                    if source.get("path") and source.get("canonical_uri"):
                        lineages.setdefault((source["path"], source["sha256"]), set()).add(source["canonical_uri"])
        self._validated_lineage = lineages

    def _normalize_source(self, source):
        result = dict(source)
        path = result.get("path")
        uri = result.get("uri")
        if not path and not uri:
            raise StoreError("Evidence needs a vault-relative path or URI")
        if path:
            source_path = safe_child(self.vault, path)
            if source_path.is_relative_to(self.store):
                raise StoreError("Derived memory is not independent source evidence; link its record and preserve original sources")
        if not HASH_PATTERN.fullmatch(str(result.get("sha256", ""))):
            raise StoreError("Evidence needs its source revision SHA256")
        if not isinstance(result.get("quote"), str) or not result["quote"].strip():
            raise StoreError("Evidence needs the exact supporting passage")
        if path:
            if source_path.is_file() and file_hash(source_path) == result["sha256"]:
                if result["quote"] not in source_path.read_text(encoding="utf-8"):
                    raise StoreError("Supporting passage does not occur in the cited source revision")
            elif (path, result["sha256"], result["quote"]) not in getattr(self, "_validated_evidence", set()):
                raise StoreError("Unverified source revision: missing/changed files require an exact passage retained by a prior committed record or this verified proposal")
            result["verification"] = "verified-file-revision"
        else:
            # A URI and caller-supplied excerpt preserve attribution; this broker
            # does not claim to have fetched or independently verified that URI.
            result["verification"] = "provided-excerpt"
        if path and result.get("canonical_uri"):
            allowed = getattr(self, "_validated_lineage", {}).get((path, result["sha256"]), set())
            if result["canonical_uri"] not in allowed:
                raise StoreError("Canonical file-source identity must match registered or previously verified captured lineage")
        identity = result.get("canonical_uri") or (path if path else uri)
        prefix = "uri:" if (result.get("canonical_uri") or not path) else "markdown:"
        result["source_id"] = prefix + hashlib.sha256(str(identity).encode()).hexdigest()
        return result

    def _normalize_record(self, record, previous=None):
        allowed = {"id", "title", "kind", "body", "origin", "review", "valid_from", "valid_until", "status", "sources", "relationships", "claims", "due_at", "review_at", "completion_evidence", "commitment_evidence", "delivery_evidence", "supersedes", "tags", "path", "revision", "recorded_at"}
        unknown = set(record) - allowed
        if unknown:
            raise StoreError("Unknown record fields: " + ", ".join(sorted(unknown)))
        rid = record.get("id")
        if not isinstance(rid, str) or not ID_PATTERN.fullmatch(rid):
            raise StoreError("Record id must be a stable, filesystem-independent identifier")
        if (rid == "workflow:glide-learned-retrieval" or rid.startswith("review:glide-learned-candidate:")) and not getattr(self, "_overlay_mutation", False):
            raise StoreError("Learned retrieval changes require the tested typed-overlay pathway")
        if rid.startswith("receipt:glide-job:") and rid != "receipt:glide-job:" + str(getattr(self, "_job_mutation", None)):
            raise StoreError("Job checkpoints require the atomic job-finish pathway")
        title = record.get("title")
        if not isinstance(title, str) or not title.strip() or "\n" in title:
            raise StoreError("Record needs a single-line title")
        kind, origin = record.get("kind", "knowledge"), record.get("origin", "ai")
        if kind not in KINDS or origin not in ORIGINS:
            raise StoreError("Unknown record kind or origin")
        if previous and origin != previous["origin"]:
            raise StoreError("Approval or correction cannot change recorded authorship")
        body = record.get("body", "")
        if not isinstance(body, str) or not body.strip():
            raise StoreError("Record needs readable Markdown")
        first = body.strip().splitlines()[0].strip()
        if re.match(r"^#\s+", first):
            raise StoreError("Do not repeat a title as an opening H1; filename is the title")
        result = {"id": rid, "title": title.strip(), "kind": kind, "body": body.strip(), "origin": origin, "review": record.get("review", "unreviewed"), "status": record.get("status", "candidate" if kind in {"operation", "decision"} else "active"), "sources": [self._normalize_source(s) for s in record.get("sources", [])], "relationships": [], "claims": []}
        if result["review"] not in REVIEWS or result["status"] not in STATUSES:
            raise StoreError("Unknown review or status")
        for field in ("valid_from", "valid_until", "due_at", "review_at"):
            result[field] = timestamp(record.get(field))
        if result["valid_from"] and result["valid_until"] and result["valid_until"] <= result["valid_from"]:
            raise StoreError("valid_until must follow valid_from")
        result["tags"] = sorted(set(record.get("tags", [])))
        for relation in record.get("relationships", []):
            if not isinstance(relation, dict) or not ID_PATTERN.fullmatch(str(relation.get("target", ""))) or not relation.get("type") or not str(relation.get("reason", "")).strip():
                raise StoreError("Every relationship needs a target id, type and explained reason")
            item = {"target": relation["target"], "type": str(relation["type"]), "reason": str(relation["reason"])}
            if relation.get("block"):
                if not re.fullmatch(r"[A-Za-z0-9-]+", relation["block"]):
                    raise StoreError("Block references require letters, numbers and hyphens")
                item["block"] = relation["block"]
            for name in ("target_path", "target_title"):
                if relation.get(name):
                    item[name] = relation[name]
            result["relationships"].append(item)
        claim_ids = set()
        for claim in record.get("claims", []):
            if not CLAIM_ID_PATTERN.fullmatch(str(claim.get("id", ""))) or claim["id"] in claim_ids or claim.get("type") not in CLAIM_TYPES or not str(claim.get("text", "")).strip():
                raise StoreError("Claim needs a unique id, text, and explicit claim type")
            claim_ids.add(claim["id"])
            claim_sources = [self._normalize_source(s) for s in claim.get("sources", [])]
            if not claim_sources:
                raise StoreError("Each substantive claim needs its own evidence")
            result["claims"].append({"id": claim["id"], "text": claim["text"], "type": claim["type"], "sources": claim_sources, "uncertainty": claim.get("uncertainty", ""), "valid_from": timestamp(claim.get("valid_from")), "valid_until": timestamp(claim.get("valid_until"))})
        if not result["sources"] and not result["claims"]:
            raise StoreError("Every durable record needs evidence; use a conversation source for stated input")
        for field in ("commitment_evidence", "completion_evidence", "delivery_evidence"):
            result[field] = [self._normalize_source(s) for s in record.get(field, [])]
        if kind == "operation":
            if result["status"] == "committed" and not result["commitment_evidence"]:
                raise StoreError("An accepted commitment needs explicit commitment evidence")
            if result["status"] == "complete" and not result["completion_evidence"]:
                raise StoreError("Sent or delivered does not establish completion; supply completion evidence")
            if result["status"] == "delivered" and not result["delivery_evidence"]:
                raise StoreError("Delivery requires delivery evidence")
        result["supersedes"] = record.get("supersedes")
        suffix = hashlib.sha256(rid.encode()).hexdigest()[:12]
        result["path"] = previous["path"] if previous else f"Records/{kind}/{slug(title)}--{suffix}.md"
        return result

    def propose(self, records=None, *, expected_revisions=None, rationale=None, idempotency_key=None, **kwargs):
        if isinstance(records, dict):
            payload = records
            records = payload.get("records")
            expected_revisions = payload.get("expected_revisions")
            rationale = payload.get("rationale")
            idempotency_key = payload.get("idempotency_key")
        if kwargs or not records or not isinstance(records, list) or not rationale or not idempotency_key:
            raise StoreError("Proposal needs records, expected_revisions, rationale and idempotency_key")
        with self._lock():
            self._require_writer()
            loaded = self._load()
            self._set_evidence_context(loaded)
            normalized = [self._normalize_record(r, loaded["records"].get(r.get("id"))) for r in records]
            ids = [r["id"] for r in normalized]
            if len(set(ids)) != len(ids) or set(expected_revisions or {}) != set(ids):
                raise StoreError("Expected revisions must name each proposed record exactly once")
            for rid in ids:
                if expected_revisions[rid] != loaded["records"].get(rid, {}).get("revision", 0):
                    raise ConflictError(f"Stale expected revision for {rid}")
            available = {**loaded["records"], **{r["id"]: r for r in normalized}}
            for record in normalized:
                for relation in record["relationships"]:
                    if relation["target"] not in available:
                        raise StoreError(f"Relationship target is unknown: {relation['target']}")
                    target = available[relation["target"]]
                    if relation.get("block") and relation["block"] not in {c["id"] for c in target["claims"]}:
                        raise StoreError("Relationship block does not identify a target claim")
                    relation["target_path"] = target["path"]
                    relation["target_title"] = target["title"]
            stable = {"schema": SCHEMA, "instance_id": self.config["instance_id"], "records": normalized, "expected_revisions": expected_revisions, "rationale": str(rationale), "idempotency_key": str(idempotency_key)}
            pid = digest(stable)
            path = safe_child(self.store, f"Proposals/{pid}.md")
            if path.exists():
                existing = read_payload(path)
                if existing.get("proposal_id") != pid or path.read_text() != self._proposal_markdown(existing):
                    raise IntegrityError("Proposal has unexpected edits")
                return existing
            proposal = {**stable, "proposal_id": pid, "created_at": now()}
            atomic_write(path, self._proposal_markdown(proposal), immutable=True)
            return proposal

    def _read_proposal(self, proposal_id):
        if not HASH_PATTERN.fullmatch(str(proposal_id)):
            raise StoreError("Expected a proposal hash")
        path = safe_child(self.store, f"Proposals/{proposal_id}.md")
        proposal = read_payload(path)
        stable = {k: v for k, v in proposal.items() if k not in {"proposal_id", "created_at"}}
        if digest(stable) != proposal_id or proposal.get("instance_id") != self.config["instance_id"] or path.read_text() != self._proposal_markdown(proposal):
            raise IntegrityError("Proposal hash, instance or rendered content mismatch")
        return proposal

    def _knowledge_ingestion_policy(self, proposal, decision, loaded):
        settings = self.review_settings()
        if settings["knowledge_review"] != "automatic" or decision != "unreviewed":
            raise StoreError("Automatic knowledge ingestion requires configured automatic mode and an unreviewed decision")
        prefixes = [PurePosixPath(p.removesuffix("/")) for p in settings["automatic_source_prefixes"]]
        for record in proposal["records"]:
            previous = loaded["records"].get(record["id"])
            if record["kind"] != "knowledge" or record["origin"] != "ai" or record["review"] != "unreviewed":
                raise StoreError("Automatic ingestion accepts only unreviewed AI knowledge")
            if previous and previous["kind"] != "knowledge":
                raise StoreError("Automatic ingestion cannot replace operational or decision records")
            if record["status"] not in {"active", "historical"} or record.get("due_at") or record.get("supersedes") or any(record.get(key) for key in ("commitment_evidence", "delivery_evidence", "completion_evidence")):
                raise StoreError("Automatic knowledge ingestion cannot accept commitments, complete actions or supersede records")
            evidence = record["sources"] + [source for claim in record["claims"] for source in claim["sources"]]
            if not evidence:
                raise StoreError("Automatic knowledge ingestion requires exact scoped source evidence")
            for source in evidence:
                path = source.get("path")
                if not path or PurePosixPath(path).suffix.lower() != ".md" or not any(PurePosixPath(path) == prefix or prefix in PurePosixPath(path).parents for prefix in prefixes):
                    raise StoreError("Automatic knowledge evidence is outside automatic_source_prefixes; retain a local Markdown capture first")
        return {"knowledge_review": "automatic", "automatic_source_prefixes": settings["automatic_source_prefixes"]}

    def apply(self, proposal_id, *, decision="unreviewed", idempotency_key=None, actor="agent", expected_revisions=None, knowledge_ingestion=False):
        if decision not in {"approved", "unreviewed", "rejected"}:
            raise StoreError("Decision must be approved, unreviewed, or rejected")
        with self._lock():
            self._require_writer()
            proposal = self._read_proposal(proposal_id)
            key = idempotency_key or proposal["idempotency_key"]
            loaded = self._load()
            expected = proposal["expected_revisions"]
            if expected_revisions is not None and expected_revisions != expected:
                raise ConflictError("Submitted review versions do not match the proposal")
            if actor == "knowledge-ingestion" and not knowledge_ingestion:
                raise StoreError("The knowledge-ingestion actor requires its scoped policy path")
            policy = self._knowledge_ingestion_policy(proposal, decision, loaded) if knowledge_ingestion else None
            if policy:
                actor = "knowledge-ingestion"
            elif actor.startswith("job:") and "knowledge_review" in self.config:
                knowledge = [record for record in proposal["records"] if record["kind"] == "knowledge"]
                if knowledge:
                    if self.review_settings()["knowledge_review"] == "manual":
                        raise StoreError("Manual knowledge review: propose and review knowledge separately before checkpointing the job")
                    policy = self._knowledge_ingestion_policy({**proposal, "records": knowledge}, decision, loaded)
            old = loaded["idempotency"].get(key)
            if old:
                if old.get("proposal_id") != proposal_id or old["decision"] != decision or old["actor"] != actor:
                    raise ConflictError("Idempotency key was used for a different change")
                publication = self._publish(loaded)
                return self._receipt(old, publication, replayed=True)
            if any(b.get("proposal_id") == proposal_id for b in loaded["bundles"]):
                raise ConflictError("Proposal was already decided with another idempotency key")
            self._set_evidence_context(loaded, proposal["records"])
            for rid, revision in expected.items():
                if loaded["records"].get(rid, {}).get("revision", 0) != revision:
                    raise ConflictError(f"Stale proposal for {rid}; refresh the review")
            self._check_projections(loaded)
            recorded = self._next_time(loaded)
            records = []
            if decision != "rejected":
                for candidate in proposal["records"]:
                    current = self._normalize_record(candidate, loaded["records"].get(candidate["id"]))
                    current.update(revision=expected[current["id"]] + 1, recorded_at=recorded)
                    if decision == "approved":
                        current["review"] = "approved"
                    records.append(current)
            bundle = self._commit(loaded, records=records, sources=[], rationale=proposal["rationale"], idempotency_key=key, decision=decision, actor=actor, proposal_id=proposal_id, recorded_at=recorded, **({"knowledge_policy": policy} if policy else {}))
            loaded = self._load()
            try:
                publication = self._publish(loaded)
            except (OSError, StoreError) as exc:
                return self._receipt(bundle, {"status": "pending", "error": str(exc)})
            return self._receipt(bundle, publication)

    def _next_time(self, loaded):
        value = now()
        if loaded["bundles"] and value <= loaded["bundles"][-1]["recorded_at"]:
            previous = dt.datetime.fromisoformat(loaded["bundles"][-1]["recorded_at"].replace("Z", "+00:00"))
            value = (previous + dt.timedelta(microseconds=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")
        return value

    def _commit(self, loaded, **fields):
        bundle = {"schema": SCHEMA, "format_version": FORMAT_VERSION, "instance_id": self.config["instance_id"], "sequence": len(loaded["bundles"]) + 1, "parent": loaded["head"], **fields}
        # Persist expected projection hashes once per commit. This makes edit
        # detection linear in history size rather than rerendering every historic
        # record set on each write. Views contain the head hash, so their hashes
        # are excluded here and reconstructed from their compact history below.
        bundle["projection_hashes"] = {r["path"]: hashlib.sha256(self._record_markdown(r).encode()).hexdigest() for r in bundle["records"]}
        bundle["hash"] = digest(bundle)
        filename = f"Bundles/{bundle['sequence']:08d}-{bundle['hash']}.md"
        atomic_write(safe_child(self.store, filename), self._bundle_markdown(bundle), immutable=True)
        return bundle

    def _receipt(self, bundle, publication, replayed=False):
        return {"committed": True, "replayed": replayed, "bundle": bundle["hash"], "sequence": bundle["sequence"], "recorded_at": bundle["recorded_at"], "decision": bundle["decision"], "actor": bundle["actor"], "proposal_id": bundle.get("proposal_id"), "revisions": {r["id"]: r["revision"] for r in bundle["records"]}, "publication": publication, **({"knowledge_policy": bundle["knowledge_policy"]} if "knowledge_policy" in bundle else {})}

    def index_sources(self, sources: list[dict], *, idempotency_key: str):
        """Register original-file revisions durably; full text is a disposable cache.

        Reads current files directly and verifies the supplied hash. Text supplied
        by an intake scanner is not trusted as an independent source.
        """
        with self._lock():
            self._require_writer()
            loaded = self._load()
            normalized = []
            known_lineages = {s["path"]: s["canonical_uri"] for b in loaded["bundles"] for s in b["sources"] if s.get("canonical_uri")}
            for source in sources:
                path = safe_child(self.vault, source["path"])
                if path.is_relative_to(self.store) or not path.is_file():
                    raise StoreError("Index only existing original files outside the derived store")
                value_hash = file_hash(path)
                if value_hash != source.get("sha256"):
                    raise ConflictError("Source changed after intake; rescan")
                source_id = "markdown:" + hashlib.sha256(source["path"].encode()).hexdigest()
                previous = loaded["sources"].get(source_id, {})
                same_revision = previous.get("path") == source["path"] and previous.get("sha256") == value_hash
                lineage = source.get("canonical_uri")
                if lineage is not None and (not isinstance(lineage, str) or not lineage.strip() or len(lineage) > 4096 or any(ord(c) < 32 for c in lineage)):
                    raise StoreError("Canonical source identity must be a nonempty, bounded string")
                if lineage and known_lineages.get(source["path"]) and lineage != known_lineages[source["path"]]:
                    raise ConflictError("Source path already belongs to a different canonical identity")
                if lineage is None and same_revision:
                    lineage = previous.get("canonical_uri")
                source_kind = source.get("source_kind")
                if same_revision and previous.get("canonical_uri") and source_kind in {None, "original-markdown", "legacy-agent-context"}:
                    source_kind = previous.get("source_kind", "original-markdown")
                elif source_kind is None:
                    source_kind = previous.get("source_kind", "original-markdown") if same_revision else "original-markdown"
                observed = {"source_id": source_id, "path": source["path"], "sha256": value_hash, "title": source.get("title") or (previous.get("title") if same_revision else None) or path.stem, "modified_at": source.get("modified_at", previous.get("modified_at") if same_revision else None), "observed_at": source.get("observed_at") or now(), "source_kind": source_kind, "trust": "source-only"}
                if lineage is not None:
                    observed["canonical_uri"] = lineage
                normalized.append(observed)
            stable_request = [{k: v for k, v in s.items() if k != "observed_at"} for s in normalized]
            request_digest = digest(stable_request)
            old = loaded["idempotency"].get(idempotency_key)
            if old:
                if old.get("request_digest") != request_digest:
                    raise ConflictError("Idempotency key belongs to another source batch")
                return self._receipt(old, self._publish(loaded), replayed=True)
            if not normalized:
                return {"committed": False, "reason": "No sources"}
            self._check_projections(loaded)
            bundle = self._commit(loaded, records=[], sources=normalized, rationale="Register original source revisions for repeatable retrieval", idempotency_key=idempotency_key, decision="unreviewed", actor="source-intake", proposal_id=None, recorded_at=self._next_time(loaded), request_digest=request_digest)
            return self._receipt(bundle, self._publish(self._load()))

    def _link(self, path, label=None, block=None, *, from_path=None):
        target = PurePosixPath(self.config["store_path"]) / path
        if self.adapter == "obsidian":
            location = str(target.with_suffix("")) + ("#^" + block if block else "")
            return "[[" + location + ("|" + label if label else "") + "]]"
        from urllib.parse import quote
        base = PurePosixPath(self.config["store_path"]) / (from_path or "Views/Now.md")
        relative = os.path.relpath(str(target), str(base.parent))
        return "[" + (label or PurePosixPath(path).stem) + "](" + quote(relative, safe="/.-_") + ("#" + quote(block) if block else "") + ")"

    def _source_link(self, source, from_path):
        if source.get("path"):
            if self.adapter == "obsidian":
                return "[[" + str(PurePosixPath(source["path"]).with_suffix("")) + "]]"
            from urllib.parse import quote
            start = (PurePosixPath(self.config["store_path"]) / from_path).parent
            return "[" + PurePosixPath(source["path"]).stem + "](" + quote(os.path.relpath(source["path"], str(start)), safe="/.-_") + ")"
        return "[Source](" + source["uri"].replace(")", "%29") + ")"

    def _record_markdown(self, record, *, from_path=None):
        return self._record_markdown_v1(record, from_path=from_path)

    def _record_markdown_v1(self, record, *, from_path=None):
        from_path = from_path or record["path"]
        frontmatter = {k: record[k] for k in ("id", "origin", "revision", "review", "recorded_at", "valid_from", "valid_until") if record.get(k) is not None}
        text = "---\n" + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items()) + "\n---\n\n"
        text += record["body"].strip() + "\n\n"
        text += f"**Kind:** {record['kind']} · **State:** {record['status']}\n"
        for field in ("due_at", "review_at"):
            if record.get(field):
                text += f"\n**{field.replace('_', ' ').capitalize()}:** {record[field]}\n"
        for claim in record["claims"]:
            text += f"\n## {claim['id']}\n\n{claim['text']}" + (f" ^{claim['id']}" if self.adapter == "obsidian" else f"\n\n<a id=\"{claim['id']}\"></a>") + "\n\n"
            text += f"**Type:** {claim['type']}\n\n**Uncertainty:** {claim['uncertainty'] or 'Not specified'}\n"
            if claim.get("valid_from") or claim.get("valid_until"):
                text += f"\n**Applies:** {claim.get('valid_from') or 'unknown'} to {claim.get('valid_until') or 'unspecified'}\n"
            text += self._evidence_markdown(claim["sources"], from_path)
        text += "\n## Evidence\n" + self._evidence_markdown(record["sources"], from_path)
        for field in ("commitment_evidence", "delivery_evidence", "completion_evidence"):
            if record.get(field):
                text += "\n## " + field.replace("_", " ").capitalize() + "\n" + self._evidence_markdown(record[field], from_path)
        if record["relationships"]:
            text += "\n## Connections\n\n"
            for relation in record["relationships"]:
                target_path = relation["target_path"]
                link = self._link(target_path, relation.get("target_title") or relation["target"], block=relation.get("block"), from_path=from_path)
                text += f"- **{relation['type']}** → {link} · `{relation['target']}`: {relation['reason']}\n"
        text += "\n---\nGenerated record. Correct through a reviewed proposal; original authorship remains unchanged.\n"
        return text

    def _evidence_markdown(self, sources, from_path):
        text = "\n"
        for source in sources:
            text += f"- {self._source_link(source, from_path)} · source `{source['source_id']}` · revision `{source['sha256']}` · {source.get('verification', 'provided-excerpt')}\n"
            text += "\n" + "\n".join("> " + line for line in source["quote"].splitlines()) + "\n\n"
            if source.get("locator"):
                text += f"  Locator: {source['locator']}\n\n"
        return text

    def _projections(self, loaded, *, include_records=True, include_due_reviews=True):
        outputs = {record["path"]: self._record_markdown(record) for record in loaded["records"].values()} if include_records else {}
        from .overlays import payload_from_record
        change = payload_from_record(loaded["records"].get("workflow:glide-learned-retrieval"))
        priority = {rid: index for index, rid in enumerate(change.get("context_priority", []))}
        records = sorted(loaded["records"].values(), key=lambda r: (r.get("due_at") or "9999", priority.get(r["id"], 999), r["title"], r["id"]))
        # Projections are snapshots of a committed head. Compare scheduled
        # review times with that durable as-of time so rebuilding on a later
        # date cannot silently alter a previously published view.
        as_of = loaded["bundles"][-1]["recorded_at"] if loaded["bundles"] else "0001-01-01T00:00:00.000000Z"
        definitions = {
            "Now": lambda r: r["kind"] == "operation" and (r["status"] in {"committed", "blocked"} or (r["status"] in {"open", "waiting"} and (bool(r.get("due_at")) or (include_due_reviews and bool(r.get("review_at")) and r["review_at"] <= as_of)))) ,
            "Ongoing": lambda r: r["kind"] in {"operation", "decision", "workflow"} and r["status"] not in {"complete", "cancelled", "historical", "superseded", "inactive"},
            "Durable": lambda r: r["kind"] in {"knowledge", "context"} and r["status"] not in {"superseded", "inactive"},
            "Record Index": lambda r: True,
        }
        for name, predicate in definitions.items():
            path = f"Views/{name}.md"
            text = f"**As of:** {loaded['head'] or 'empty store'}\n\n"
            all_matching = [r for r in records if predicate(r)]
            context = []
            if name == "Now":
                candidates = [r for r in records if r["kind"] == "context" and r["status"] == "active" and "context:now" in r.get("tags", [])]
                context = sorted(candidates, key=lambda r: (r["recorded_at"], r["id"]), reverse=True)[:1]
            bound = {"Now": 5, "Ongoing": 12, "Durable": 12}.get(name)
            chosen = context + (all_matching[:bound] if bound else all_matching)
            for record in chosen:
                text += f"- {self._link(record['path'], record['title'], from_path=path)} · `{record['id']}` · {record['status']} · {record['review']}\n"
            if not chosen:
                text += "No matching records.\n"
            if bound and len(all_matching) > bound:
                text += f"\n{len(all_matching) - bound} more records: {self._link('Views/Record Index.md', 'Browse all records', from_path=path)}.\n"
            outputs[path] = text
        text = "Recent committed changes; permanent history remains in Bundles.\n\n"
        for bundle in loaded["bundles"][-50:][::-1]:
            path = f"Bundles/{bundle['sequence']:08d}-{bundle['hash']}.md"
            text += f"- {self._link(path, bundle['recorded_at'], from_path='Views/Changes.md')} · {bundle['rationale']} · {bundle['decision']}\n"
        outputs["Views/Changes.md"] = text
        return outputs

    def _historical_projection_hashes(self, loaded):
        hashes = {}
        # Current view text changes at each head. Reconstruct only small view
        # projections here, not every full record page on every history prefix.
        prefix = {"records": {}, "bundles": [], "head": None}
        for path, text in self._projections(prefix, include_records=False).items():
            hashes.setdefault(path, set()).add(hashlib.sha256(text.encode()).hexdigest())
        for bundle in loaded["bundles"]:
            prefix["bundles"].append(bundle)
            prefix["head"] = bundle["hash"]
            for record in bundle["records"]:
                prefix["records"][record["id"]] = record
                expected = hashlib.sha256(self._record_markdown(record).encode()).hexdigest()
                if bundle.get("projection_hashes", {}).get(record["path"]) != expected:
                    raise IntegrityError("Recorded projection hash differs from its record")
                hashes.setdefault(record["path"], set()).add(expected)
            for path, text in self._projections(prefix, include_records=False).items():
                hashes.setdefault(path, set()).add(hashlib.sha256(text.encode()).hexdigest())
            # Recognize the previously shipped generated Now projection while
            # adding review-time eligibility. This allows safe regeneration,
            # without treating arbitrary human edits as an authorized version.
            legacy_now = self._projections(prefix, include_records=False, include_due_reviews=False)["Views/Now.md"]
            hashes.setdefault("Views/Now.md", set()).add(hashlib.sha256(legacy_now.encode()).hexdigest())
        return hashes

    def _check_projections(self, loaded):
        allowed = self._historical_projection_hashes(loaded)
        for path in list(safe_child(self.store, "Records").rglob("*.md")) + list(safe_child(self.store, "Views").rglob("*.md")):
            relative = path.relative_to(self.store).as_posix()
            no_symlinks(path)
            if relative not in allowed or file_hash(path) not in allowed[relative]:
                raise ConflictError(f"Unexpected generated-page edit; reconcile without overwriting: {relative}")
        return allowed

    def _publish(self, loaded):
        self._check_projections(loaded)
        for path, text in self._projections(loaded).items():
            target = safe_child(self.store, path)
            if not target.exists() or target.read_text() != text:
                atomic_write(target, text)
        self._rebuild_index(loaded)
        return {"status": "complete", "head": loaded["head"]}

    def rebuild(self, *, publish=True):
        with self._lock():
            loaded = self._load()
            if publish:
                # Rebuild is allowed before writer activation: only deterministic
                # derived pages may be restored, never semantic data changed.
                result = self._publish(loaded)
            else:
                self._rebuild_index(loaded)
                result = {"status": "complete", "head": loaded["head"]}
            return {**result, "records": len(loaded["records"]), "sources": len(loaded["sources"])}

    def _rebuild_index(self, loaded):
        # Construct a separate DB and atomically replace the cache. Never mix a
        # partially rebuilt index with a previous authoritative head.
        fd, tmp_name = tempfile.mkstemp(prefix=".index-", suffix=".sqlite3", dir=self.state_dir)
        os.close(fd)
        temp = Path(tmp_name)
        try:
            with sqlite3.connect(temp) as db:
                db.executescript("""
                    PRAGMA journal_mode=DELETE;
                    CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE records(id TEXT PRIMARY KEY, revision INTEGER, kind TEXT, status TEXT, path TEXT, recorded_at TEXT, valid_from TEXT, valid_until TEXT, json TEXT);
                    CREATE TABLE versions(id TEXT, revision INTEGER, bundle TEXT, recorded_at TEXT, json TEXT, PRIMARY KEY(id,revision));
                    CREATE TABLE relationships(record_id TEXT, target_id TEXT, type TEXT, reason TEXT, block TEXT);
                    CREATE TABLE evidence(record_id TEXT, claim_id TEXT, source_id TEXT, revision_hash TEXT, quote TEXT, path TEXT, uri TEXT);
                    CREATE TABLE sources(id TEXT PRIMARY KEY, path TEXT, sha256 TEXT, status TEXT, json TEXT);
                    CREATE VIRTUAL TABLE search_index USING fts5(id UNINDEXED, record_kind UNINDEXED, title, body, tokenize='unicode61');
                """)
                for key, value in {"schema": str(SCHEMA), "instance_id": self.config["instance_id"], "head": loaded["head"] or ""}.items():
                    db.execute("INSERT INTO metadata VALUES (?,?)", (key, value))
                for bundle in loaded["bundles"]:
                    for record in bundle["records"]:
                        db.execute("INSERT INTO versions VALUES (?,?,?,?,?)", (record["id"], record["revision"], bundle["hash"], bundle["recorded_at"], canonical(record)))
                for record in loaded["records"].values():
                    db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)", (record["id"], record["revision"], record["kind"], record["status"], record["path"], record["recorded_at"], record["valid_from"], record["valid_until"], canonical(record)))
                    searchable = record["body"] + "\n" + "\n".join(c["text"] for c in record["claims"]) + "\n" + "\n".join(r["reason"] for r in record["relationships"])
                    db.execute("INSERT INTO search_index VALUES (?,?,?,?)", (record["id"], record["kind"], record["title"], searchable))
                    for relation in record["relationships"]:
                        db.execute("INSERT INTO relationships VALUES (?,?,?,?,?)", (record["id"], relation["target"], relation["type"], relation["reason"], relation.get("block")))
                    groups = [(None, record["sources"])] + [(c["id"], c["sources"]) for c in record["claims"]] + [(k, record[k]) for k in ("commitment_evidence", "delivery_evidence", "completion_evidence")]
                    for claim_id, evidence in groups:
                        for source in evidence:
                            db.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?)", (record["id"], claim_id, source["source_id"], source["sha256"], source["quote"], source.get("path"), source.get("uri")))
                for source in loaded["sources"].values():
                    status, text = self._source_cache_content(source)
                    db.execute("INSERT INTO sources VALUES (?,?,?,?,?)", (source["source_id"], source["path"], source["sha256"], status, canonical(source)))
                    if text is not None:
                        db.execute("INSERT INTO search_index VALUES (?,?,?,?)", (source["source_id"], "source", source["title"], text))
                db.commit()
            no_symlinks(self.db_path)
            os.replace(temp, self.db_path)
        finally:
            if temp.exists():
                temp.unlink()

    def _source_cache_content(self, source):
        """Hash and decode the same bytes; text mode would normalize CRLF."""
        path = safe_child(self.vault, source["path"])
        try:
            raw = path.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            return "missing", None
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            return "changed", None
        try:
            return "current", raw.decode("utf-8")
        except UnicodeDecodeError:
            return "binary", None

    def _index_matches(self, db, loaded, *, check_source_freshness=True):
        """Check every cached semantic row, including original-source full text.

        An older snapshot may contain a verified historical source revision which
        the author has since changed. Validate its bytes against that historical
        fingerprint, then rebuild it from current files before using it.
        """
        metadata = dict(db.execute("SELECT key,value FROM metadata"))
        if metadata != {"schema": str(SCHEMA), "instance_id": self.config["instance_id"], "head": loaded["head"] or ""}:
            return False
        expected_records = [(r["id"], r["revision"], r["kind"], r["status"], r["path"], r["recorded_at"], r["valid_from"], r["valid_until"], canonical(r)) for r in loaded["records"].values()]
        if sorted(db.execute("SELECT id,revision,kind,status,path,recorded_at,valid_from,valid_until,json FROM records")) != sorted(expected_records):
            return False
        versions = sorted((r["id"], r["revision"], b["hash"], b["recorded_at"], canonical(r)) for b in loaded["bundles"] for r in b["records"])
        if sorted(db.execute("SELECT id,revision,bundle,recorded_at,json FROM versions")) != versions:
            return False
        source_rows = list(db.execute("SELECT id,path,sha256,status,json FROM sources"))
        if {row[0] for row in source_rows} != set(loaded["sources"]) or len(source_rows) != len(loaded["sources"]):
            return False
        source_search = list(db.execute("SELECT id,title,body FROM search_index WHERE record_kind = 'source'"))
        source_text = {sid: (title, body) for sid, title, body in source_search}
        if len(source_text) != len(source_search):
            return False
        expected_source_search = []
        for sid, path, fingerprint, status, serialized in source_rows:
            source = loaded["sources"][sid]
            if (path, fingerprint, serialized) != (source["path"], source["sha256"], canonical(source)):
                return False
            if status not in {"current", "changed", "missing", "binary"}:
                return False
            if status == "current":
                title, body = source_text.get(sid, (None, None))
                if title != source["title"] or not isinstance(body, str) or hashlib.sha256(body.encode("utf-8")).hexdigest() != fingerprint:
                    return False
                expected_source_search.append((sid, "source", title, body))
            elif sid in source_text:
                return False
            if check_source_freshness and self._source_cache_content(source)[0] != status:
                return False
        relations, evidence, searchable = [], [], expected_source_search
        for r in loaded["records"].values():
            relations += [(r["id"], x["target"], x["type"], x["reason"], x.get("block")) for x in r["relationships"]]
            body = r["body"] + "\n" + "\n".join(c["text"] for c in r["claims"]) + "\n" + "\n".join(x["reason"] for x in r["relationships"])
            searchable.append((r["id"], r["kind"], r["title"], body))
            groups = [(None, r["sources"])] + [(c["id"], c["sources"]) for c in r["claims"]] + [(k, r[k]) for k in ("commitment_evidence", "delivery_evidence", "completion_evidence")]
            for cid, group in groups:
                evidence += [(r["id"], cid, x["source_id"], x["sha256"], x["quote"], x.get("path"), x.get("uri")) for x in group]
        stable_sort = lambda rows: sorted((canonical(list(row)) for row in rows))
        if stable_sort(db.execute("SELECT * FROM relationships")) != stable_sort(relations):
            return False
        if stable_sort(db.execute("SELECT * FROM evidence")) != stable_sort(evidence):
            return False
        if stable_sort(db.execute("SELECT id,record_kind,title,body FROM search_index")) != stable_sort(searchable):
            return False
        return True

    def _ensure_index(self, loaded):
        try:
            with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as db:
                healthy = self._index_matches(db, loaded)
        except sqlite3.Error:
            healthy = False
        if not healthy:
            self._rebuild_index(loaded)

    def search(self, query: str, *, limit=20, include_sources=True, kind=None, valid_at=None, recorded_at=None, use_overlays=True):
        if use_overlays:
            from .overlays import current_change, search_with_change
            change = current_change(self)
            if change.get("retrieval_aliases", {}).get(query.casefold().strip()):
                return search_with_change(self, query, change, limit=limit, include_sources=include_sources, kind=kind, valid_at=valid_at, recorded_at=recorded_at)
        if not query.strip():
            return []
        if limit < 1 or limit > 200:
            raise StoreError("Search limit must be between 1 and 200")
        with self._lock():
            loaded = self._load()
            tokens = re.findall(r"\w+", query, flags=re.UNICODE)
            if not tokens:
                return []
            expression = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)
            when, recorded_when = timestamp(valid_at), timestamp(recorded_at)
            statement = """
                SELECT search_index.id,search_index.record_kind,search_index.title,
                       snippet(search_index,3,'[',']',' … ',32),bm25(search_index),search_index.body
                FROM search_index LEFT JOIN sources ON sources.id=search_index.id
                WHERE search_index MATCH ?
                  AND (? = '' OR search_index.record_kind = ?)
                  AND (? OR search_index.record_kind != 'source')
                  AND (? != '' OR (search_index.record_kind NOT IN ('receipt','review')
                       AND search_index.id != 'workflow:glide-learned-retrieval'))
                  AND (? = 'source' OR sources.path IS NULL OR
                       (sources.path NOT LIKE 'Agent HQ/Legacy Memory/%'
                        AND sources.path NOT LIKE 'Glide HQ/Legacy Memory/%'))
                ORDER BY CASE WHEN search_index.record_kind='source' THEN 1 ELSE 0 END,
                         bm25(search_index),search_index.id
                LIMIT ?
            """
            search_arguments = (expression, kind or '', kind or '', include_sources, kind or '', kind or '', limit)
            if when or recorded_when:
                if recorded_when:
                    prefix = [b for b in loaded["bundles"] if b["recorded_at"] <= recorded_when]
                    loaded = {**loaded, "bundles": prefix, "records": {r["id"]: r for b in prefix for r in b["records"]}, "sources": {source["source_id"]: source for b in prefix for source in b["sources"]}}
                eligible = {}
                for rid, record in loaded["records"].items():
                    if when and ((record["valid_from"] and when < record["valid_from"]) or (record["valid_until"] and when >= record["valid_until"])):
                        continue
                    claims = [c for c in record["claims"] if not when or not ((c["valid_from"] and when < c["valid_from"]) or (c["valid_until"] and when >= c["valid_until"]))]
                    eligible[rid] = {**record, "claims": claims}
                loaded = {**loaded, "records": eligible}
                # Temporal FTS is deliberately ephemeral: it cannot replace the
                # current cache head or flatten expired/future claim text into
                # an apparently applicable match.
                with sqlite3.connect(":memory:") as db:
                    db.execute("CREATE VIRTUAL TABLE search_index USING fts5(id UNINDEXED, record_kind UNINDEXED, title, body, tokenize='unicode61')")
                    db.execute("CREATE TABLE sources(id TEXT PRIMARY KEY, path TEXT)")
                    for source in loaded["sources"].values():
                        db.execute("INSERT INTO sources VALUES (?,?)", (source["source_id"], source["path"]))
                    for record in eligible.values():
                        searchable = record["body"] + "\n" + "\n".join(c["text"] for c in record["claims"]) + "\n" + "\n".join(r["reason"] for r in record["relationships"])
                        db.execute("INSERT INTO search_index VALUES (?,?,?,?)", (record["id"], record["kind"], record["title"], searchable))
                    if include_sources:
                        for source in loaded["sources"].values():
                            _, text = self._source_cache_content(source)
                            if text is not None:
                                db.execute("INSERT INTO search_index VALUES (?,?,?,?)", (source["source_id"], "source", source["title"], text))
                    rows = db.execute(statement, search_arguments).fetchall()
            else:
                self._ensure_index(loaded)
                with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as db:
                    rows = db.execute(statement, search_arguments).fetchall()
            results = []
            for rid, record_kind, title, snippet, score, cached_body in rows:
                if kind is None and (record_kind in {"receipt", "review"} or rid == "workflow:glide-learned-retrieval"):
                    continue
                if (not include_sources and record_kind == "source") or (kind and record_kind != kind):
                    continue
                record = loaded["records"].get(rid)
                source = loaded["sources"].get(rid)
                if record and when and ((record["valid_from"] and when < record["valid_from"]) or (record["valid_until"] and when >= record["valid_until"])):
                    continue
                # Verify source cache freshness against the actual original on
                # each return; changed text must never masquerade as its old hash.
                if source:
                    path = safe_child(self.vault, source["path"])
                    if title != source["title"] or hashlib.sha256(cached_body.encode("utf-8")).hexdigest() != source["sha256"]:
                        continue
                    if not path.is_file() or file_hash(path) != source["sha256"]:
                        continue
                result = {"id": rid, "kind": record_kind, "title": title, "snippet": snippet, "score": score, "path": (self.config["store_path"] + "/" + record["path"]) if record else source["path"]}
                if record:
                    record = record_metadata(record)
                    result.update(revision=record["revision"], review=record["review"], origin=record["origin"], recorded_at=record["recorded_at"], valid_from=record["valid_from"], valid_until=record["valid_until"], sources=record["sources"], claims=record["claims"])
                else:
                    source = source_metadata(source)
                    result.update(sha256=source["sha256"], source_status="current", source_kind=source.get("source_kind", "original-markdown"), trust="source-only")
                    if source.get("provenance_role"):
                        result["provenance_role"] = source["provenance_role"]
                results.append(result)
                if len(results) >= limit:
                    break
            return results

    def get(self, record_id, *, at=None):
        loaded = self._load()
        if at is None:
            result = loaded["records"].get(record_id)
        else:
            when = timestamp(at, optional=False)
            result = None
            for bundle in loaded["bundles"]:
                if bundle["recorded_at"] > when:
                    break
                result = next((r for r in bundle["records"] if r["id"] == record_id), result)
        if result is None:
            raise StoreError("Record not found at the requested recorded time")
        return record_metadata(result)

    def history(self, record_id=None):
        loaded = self._load()
        if record_id is None:
            return [{"bundle": b["hash"], "parent": b["parent"], "recorded_at": b["recorded_at"], "rationale": b["rationale"], "decision": b["decision"], "actor": b["actor"], "proposal_id": b.get("proposal_id"), "records": [r["id"] for r in b["records"]]} for b in loaded["bundles"]]
        return [{"bundle": b["hash"], "recorded_at": b["recorded_at"], "rationale": b["rationale"], "decision": b["decision"], "record": record_metadata(r)} for b in loaded["bundles"] for r in b["records"] if r["id"] == record_id]

    def changes_since(self, cursor=None):
        history = self.history()
        if not cursor:
            return history
        if HASH_PATTERN.fullmatch(cursor):
            for index, entry in enumerate(history):
                if entry["bundle"] == cursor:
                    return history[index + 1:]
            raise StoreError("Unknown change cursor; do not silently skip missing history")
        when = timestamp(cursor, optional=False)
        return [entry for entry in history if entry["recorded_at"] > when]

    def export(self):
        loaded = self._load()
        return {"schema": SCHEMA, "instance_id": self.config["instance_id"], "head": loaded["head"], "records": sorted(loaded["records"].values(), key=lambda r: r["id"]), "sources": sorted(loaded["sources"].values(), key=lambda r: r["source_id"]), "history": self.history()}

    def verify(self):
        with self._lock():
            loaded = self._load()
            self._check_projections(loaded)
            expected = self._projections(loaded)
            stale = [path for path, text in expected.items() if not safe_child(self.store, path).exists() or safe_child(self.store, path).read_text() != text]
            warnings = []
            observed = {(s["path"], s["sha256"]): set() for s in loaded["sources"].values()}
            for record in loaded["records"].values():
                groups = [record["sources"]] + [c["sources"] for c in record["claims"]] + [record[k] for k in ("commitment_evidence", "delivery_evidence", "completion_evidence")]
                for group in groups:
                    for source in group:
                        if source.get("path"):
                            observed.setdefault((source["path"], source["sha256"]), set()).add(record["id"])
            for (relative, fingerprint), referring_records in sorted(observed.items()):
                path = safe_child(self.vault, relative)
                if not path.is_file() or file_hash(path) != fingerprint:
                    warnings.append({"path": relative, "status": "changed-or-missing", "sha256": fingerprint, "record_ids": sorted(referring_records), "meaning": "The retained passage remains historical evidence; current source freshness is not established."})
            index_status = "missing"
            if self.db_path.exists():
                try:
                    with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as db:
                        check = db.execute("PRAGMA integrity_check").fetchone()[0]
                        metadata = dict(db.execute("SELECT key,value FROM metadata"))
                        index_status = "current" if check == "ok" and self._index_matches(db, loaded) else "stale-or-corrupt"
                except sqlite3.Error:
                    index_status = "stale-or-corrupt"
            return {"ok": not stale and index_status == "current", "head": loaded["head"], "bundles": len(loaded["bundles"]), "records": len(loaded["records"]), "sources": len(loaded["sources"]), "stale_projections": stale, "source_warnings": warnings, "index": index_status, "source_protection": "broker-path-validation-only; OS isolation must be verified separately", "review_settings": self.review_settings()}

    def backup(self, destination):
        """Create a completed database snapshot and compatibility manifest outside the vault."""
        destination = no_symlinks(Path(destination))
        if destination.is_relative_to(self.vault):
            raise StoreError("Create snapshots outside the vault, then transfer completed artifacts deliberately")
        with self._lock():
            if destination.exists():
                raise StoreError("Backup destination must not exist")
            loaded = self._load()
            self._ensure_index(loaded)
            destination.mkdir(parents=True)
            temp = destination / "index.sqlite3"
            try:
                with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as source, sqlite3.connect(temp) as target:
                    source.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise IntegrityError("Backup integrity check failed")
                manifest = {"schema": SCHEMA, "instance_id": self.config["instance_id"], "head": loaded["head"], "created_at": now(), "sha256": file_hash(temp), "records": len(loaded["records"])}
                atomic_write(destination / "Snapshot.md", payload_markdown("Completed local search-index snapshot. Durable Markdown is still required. This snapshot contains private source text.", manifest), immutable=True)
            except Exception:
                shutil.rmtree(destination)
                raise
            return manifest

    def restore_snapshot(self, source):
        source = no_symlinks(Path(source))
        with self._lock():
            loaded = self._load()
            manifest = read_payload(source / "Snapshot.md")
            snapshot = no_symlinks(source / "index.sqlite3")
            if manifest.get("schema") != SCHEMA or manifest.get("instance_id") != self.config["instance_id"] or manifest.get("sha256") != file_hash(snapshot):
                raise IntegrityError("Snapshot identity, schema, or digest mismatch")
            known_heads = {None, *(b["hash"] for b in loaded["bundles"])}
            if manifest.get("head") not in known_heads:
                raise IntegrityError("Snapshot refers to unknown or unsynced authoritative history")
            with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise IntegrityError("Snapshot integrity failure")
                metadata = dict(db.execute("SELECT key,value FROM metadata"))
                if metadata.get("head") != (manifest["head"] or "") or metadata.get("instance_id") != manifest["instance_id"] or metadata.get("schema") != str(SCHEMA):
                    raise IntegrityError("Snapshot metadata does not match its manifest")
                sequence = next((entry["sequence"] for entry in loaded["bundles"] if entry["hash"] == manifest["head"]), 0)
                prefix = loaded["bundles"][:sequence]
                snapshot_loaded = {"bundles": prefix, "head": manifest["head"], "records": {r["id"]: r for b in prefix for r in b["records"]}, "sources": {s["source_id"]: s for b in prefix for s in b["sources"]}}
                if not self._index_matches(db, snapshot_loaded, check_source_freshness=manifest["head"] == loaded["head"]):
                    raise IntegrityError("Snapshot semantic contents differ from the authoritative Markdown or current sources")
            if manifest["head"] == loaded["head"]:
                fd, temp_name = tempfile.mkstemp(prefix=".restore-", suffix=".sqlite3", dir=self.state_dir)
                os.close(fd)
                try:
                    with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as old, sqlite3.connect(temp_name) as restored:
                        old.backup(restored)
                    no_symlinks(self.db_path)
                    os.replace(temp_name, self.db_path)
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
                status = "restored"
            else:
                # Incremental cache catch-up is optional. Rebuild safely when a
                # compatible snapshot precedes the complete synced history.
                self._rebuild_index(loaded)
                status = "verified-and-rebuilt"
            return {"status": status, "snapshot_head": manifest["head"], "head": loaded["head"]}
