"""Fixed, hash-verified local import adapters; no caller-supplied commands or bodies.

The launcher admits private configuration and reviewed helper hashes. Native
connectors need their normal OS permissions; these tools do not bypass them.
Apple Notes body access requires a fresh successful metadata scan and listed IDs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote

from .pipeline import _apply_records, _body, _observation, _records
from .store import Store, StoreError, IntegrityError, atomic_write, canonical, digest, file_hash, no_symlinks, safe_child, slug

TOKEN = re.compile(r"^[a-f0-9]{64}$")
MAX_EXPORT = 16 * 1024 * 1024


def _native_config(store: Store, kind: str) -> dict:
    path = safe_child(store.state_dir, "native.json")
    if not path.is_file():
        raise StoreError("Native imports are not configured on this machine")
    config = json.loads(path.read_text())
    if set(config) - {"apple_notes", "voice_memos"} or not isinstance(config.get(kind), dict):
        raise StoreError("Requested native adapter is not configured")
    value = dict(config[kind])
    allowed = {"script", "sha256", "max_days", "legacy_log"} if kind == "apple_notes" else {"script", "sha256", "source", "data_root", "model", "state_dir", "staging_vault", "since_days", "limit", "threads", "legacy_manifest"}
    if set(value) - allowed or not TOKEN.fullmatch(str(value.get("sha256", ""))):
        raise StoreError("Unknown native adapter option or invalid approved helper hash")
    helper = no_symlinks(Path(value.get("script", "")))
    if helper.is_relative_to(store.vault) or not helper.is_file() or helper.suffix != ".py" or file_hash(helper) != value["sha256"]:
        raise StoreError("Native helper must be an approved, unchanged Python file outside the vault")
    value["script"] = str(helper)
    return value


def _run_helper(config: dict, args: list[str], *, timeout=120) -> dict:
    # Reverify immediately before execution; the reader must not have write access
    # to the admitted helper or its configuration.
    helper = no_symlinks(Path(config["script"]))
    if file_hash(helper) != config["sha256"]:
        raise StoreError("Approved helper changed before execution")
    try:
        result = subprocess.run([sys.executable, str(helper), *args], capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": type(error).__name__, "data": None}
    if len(result.stdout) > MAX_EXPORT:
        return {"ok": False, "error": "Helper output exceeds the configured intake limit", "data": None}
    try:
        data = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, ValueError):
        data = None
    if result.returncode or data is None:
        return {"ok": False, "returncode": result.returncode, "error": result.stderr.decode("utf-8", errors="replace")[-2000:] or "Helper did not return a successful JSON export", "data": data}
    return {"ok": True, "returncode": 0, "data": data}


def _receipt(store: Store, name: str, report: dict) -> dict:
    _, previous = _records(store)
    record = {"id": "native:" + name, "title": name.replace("-", " ").title() + " receipt", "kind": "receipt", "origin": "imported", "status": "complete" if report["status"] in {"complete", "no-change"} else "blocked", "body": _body("Native import execution report. A failed or partial scan does not establish clean coverage.", report), "sources": [_observation(name, report)]}
    return _apply_records(store, [record], previous, rationale="Retain the actual native import outcome and coverage", key_prefix="native-" + name)


def _reported(store: Store, name: str, report: dict, **extra) -> dict:
    receipt = _receipt(store, name, report)
    result = {**report, **extra, "receipt": receipt}
    if receipt.get("publication", {}).get("status") != "complete":
        result.update(status="publication-pending", coverage_status=report["status"])
    return result


def _cache(store: Store, suffix: str) -> Path:
    return safe_child(store.state_dir, "native/" + suffix)


def _save_export(store: Store, kind: str, items: list[dict]) -> str:
    payload = {"kind": kind, "items": items}
    token = digest(payload)
    atomic_write(_cache(store, "exports/" + token + ".json"), canonical(payload) + "\n", immutable=True)
    return token


def _notes_output(outcome: dict) -> tuple[list | None, dict]:
    data = outcome.get("data")
    if isinstance(data, list):
        return data, {"status": "unknown", "errors": [], "scope": "Legacy helper does not report per-note coverage"}
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        return None, {"status": "failed", "errors": [], "scope": "Malformed helper result"}
    coverage = data.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("status") not in {"complete", "partial", "failed"} or not isinstance(coverage.get("errors"), list):
        return None, {"status": "failed", "errors": [], "scope": "Missing explicit helper coverage"}
    # Retain identifiers and diagnostic stages, never note bodies/messages in an
    # error channel. The copied local helper emits this bounded shape directly.
    errors = [{key: error.get(key) for key in ("stage", "note_id", "code")} for error in coverage["errors"] if isinstance(error, dict)]
    status = "partial" if coverage["status"] == "complete" and coverage["errors"] else coverage["status"]
    return data["notes"], {**coverage, "status": status, "errors": errors}


def _legacy_notes(store: Store, config: dict) -> dict:
    if not config.get("legacy_log"):
        return {}
    path = no_symlinks(Path(config["legacy_log"]))
    if not path.is_relative_to(store.vault) or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise StoreError("Legacy Notes log must be an existing bounded file inside the vault")
    known, section = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
        match = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if match and section in {"imported", "skipped"}:
            known[match.group(1)] = section
    return known


def apple_notes_metadata(store: Store, *, days: int = 2) -> dict:
    store._require_writer()
    config = _native_config(store, "apple_notes")
    maximum = config.get("max_days", 7)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= min(maximum, 31):
        raise StoreError("Apple Notes metadata window is outside the configured bound")
    metadata_path = _cache(store, "apple-metadata.json")
    # Invalidate the prior grant before touching the connector. An interrupted or
    # failed refresh must never leave old metadata authorizing a body export.
    atomic_write(metadata_path, canonical({"status": "pending"}) + "\n")
    outcome = _run_helper(config, ["--days", str(days)])
    notes, coverage = _notes_output(outcome)
    if coverage["status"] == "failed" and outcome["ok"]:
        outcome = {"ok": False, "error": "Native metadata coverage failed", "data": None}
    if outcome["ok"]:
        valid = isinstance(notes, list) and all(isinstance(note, dict) and isinstance(note.get("note_id"), str) and note["note_id"] and not note["note_id"].startswith("-") and not any(ord(c) < 32 for c in note["note_id"]) and "body_html" not in note and "body_text" not in note for note in notes)
        if not valid or len({note["note_id"] for note in notes}) != len(notes):
            outcome = {"ok": False, "error": "Metadata helper returned malformed or body-containing data"}
    if not outcome["ok"]:
        report = {"status": "failed", "days": days, "error": outcome["error"], "coverage": coverage}
        atomic_write(metadata_path, canonical(report) + "\n")
        return _reported(store, "apple-notes-metadata", report)
    known = _legacy_notes(store, config)
    notes = [{**note, **({"previous_disposition": known[note["note_id"]]} if note["note_id"] in known else {})} for note in notes]
    state = {"status": coverage["status"], "days": days, "scanned_at": datetime.now(timezone.utc).isoformat(), "notes": notes, "coverage": coverage}
    token = digest(state)
    atomic_write(metadata_path, canonical({**state, "token": token}) + "\n")
    report = {"status": coverage["status"], "days": days, "note_count": len(notes), "metadata_token": token, "scanned_at": state["scanned_at"], "coverage": coverage}
    return _reported(store, "apple-notes-metadata", report, notes=notes)


def apple_notes_export(store: Store, *, metadata_token: str, note_ids: list[str]) -> dict:
    store._require_writer()
    config = _native_config(store, "apple_notes")
    if not TOKEN.fullmatch(str(metadata_token)) or not isinstance(note_ids, list) or not 1 <= len(note_ids) <= 20 or len(set(note_ids)) != len(note_ids) or not all(isinstance(note_id, str) for note_id in note_ids):
        raise StoreError("Provide a metadata token and one to twenty unique listed note IDs")
    metadata = json.loads(_cache(store, "apple-metadata.json").read_text())
    stable = {key: value for key, value in metadata.items() if key != "token"}
    if metadata.get("status") not in {"complete", "partial", "unknown"} or metadata.get("token") != metadata_token or digest(stable) != metadata_token:
        raise StoreError("A successful current metadata scan is required before reading bodies")
    age = datetime.now(timezone.utc) - datetime.fromisoformat(metadata["scanned_at"])
    if age.total_seconds() < 0 or age.total_seconds() > 3600:
        raise StoreError("Metadata grant expired; run a fresh metadata scan")
    listed = {note["note_id"]: note for note in metadata["notes"]}
    if not set(note_ids) <= set(listed):
        raise StoreError("Body export is limited to IDs returned by the current metadata scan")
    known = _legacy_notes(store, config)
    if set(note_ids) & set(known):
        raise StoreError("Previously imported or skipped Apple Notes remain excluded; use their existing records")
    args = ["--days", str(metadata["days"]), "--include-body"]
    for note_id in note_ids:
        args.extend(["--note-id", note_id])
    outcome = _run_helper(config, args)
    notes, coverage = _notes_output(outcome)
    if coverage["status"] == "failed" and outcome["ok"]:
        outcome = {"ok": False, "error": "Native body-export coverage failed", "data": None}
    if outcome["ok"]:
        valid = isinstance(notes, list) and all(isinstance(note, dict) and note.get("note_id") in note_ids and isinstance(note.get("body_html"), str) and isinstance(note.get("body_text"), str) and note.get("modified") == listed[note["note_id"]].get("modified") for note in notes)
        if not valid or len({note["note_id"] for note in notes}) != len(notes):
            outcome = {"ok": False, "error": "Body export changed since metadata, returned unrequested IDs, or was malformed"}
    if not outcome["ok"]:
        report = {"status": "failed", "requested_ids": note_ids, "error": outcome["error"], "coverage": coverage}
        atomic_write(_cache(store, "apple-metadata.json"), canonical({"status": "failed", "reason": "Body export failed; metadata must be refreshed"}) + "\n")
        return _reported(store, "apple-notes-export", report)
    returned = {note["note_id"] for note in notes}
    token = _save_export(store, "apple-notes", notes)
    report = {"status": coverage["status"] if returned == set(note_ids) else "partial", "requested_ids": note_ids, "missing_ids": sorted(set(note_ids) - returned), "export_token": token, "note_count": len(notes), "coverage": coverage}
    return _reported(store, "apple-notes-export", report, notes=notes)


def _capture_markdown(kind: str, item: dict, *, adapter="obsidian", relative_root=None) -> tuple[str, str, str]:
    original_id = item["note_id"] if kind == "apple-notes" else item["uuid"]
    original_uri = original_id if kind == "apple-notes" else "voice-memos:" + original_id
    text = item["body_text"] if kind == "apple-notes" else item["transcript"]
    fingerprint = digest(item)
    source_id = kind + ":" + hashlib.sha256(original_id.encode()).hexdigest()
    title = slug(item.get("title") or ("Apple Note" if kind == "apple-notes" else "Voice Memo"))
    filename = title + "--" + digest(original_id)[:12] + "-" + fingerprint[:12] + ".md"
    frontmatter = "---\norigin: imported\nsource_id: " + json.dumps(source_id) + "\nsource_revision: " + json.dumps(fingerprint) + "\ncanonical_uri: " + json.dumps(original_uri) + "\n---\n\n"
    warning = "Captured Apple Notes text; the exact exported HTML is retained below." if kind == "apple-notes" else "Automatically generated transcript; recognition errors remain possible. Original words were not rewritten."
    body = frontmatter + warning + "\n\n**Original source:** `" + original_uri + "`\n\n## Captured text\n\n" + text + "\n\n"
    def asset_link(path: str, *, playback=False) -> str:
        if adapter == "obsidian":
            return ("!" if playback else "") + "[[" + path + "]]"
        relative = os.path.relpath(path, str(relative_root))
        return "[" + ("Play recording" if playback else "Download original recording") + "](" + quote(relative, safe="/.-_") + ")"
    if item.get("playback_capture"):
        body += "**Playback:**\n" + asset_link(item["playback_capture"], playback=True) + "\n\n"
    if item.get("audio_capture"):
        body += "**Original recording (download):** " + asset_link(item["audio_capture"]) + "\n\n"
    body += "## Raw export\n\n```json\n" + json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2) + "\n```\n"
    return filename, body, original_uri


def capture_export(store: Store, *, export_token: str) -> dict:
    """Capture only records emitted by a configured helper; no body/path input."""
    if not TOKEN.fullmatch(str(export_token)):
        raise StoreError("Export token must identify a verified local export")
    payload = json.loads(_cache(store, "exports/" + export_token + ".json").read_text())
    if digest(payload) != export_token or payload.get("kind") not in {"apple-notes", "voice-memos"}:
        raise IntegrityError("Local export content does not match its verified token")
    store._require_writer()
    source_name = "Apple Notes" if payload["kind"] == "apple-notes" else "Voice Memos"
    relative_root = Path(store.config["store_path"]).parent / "Source Captures" / source_name
    captures = []
    for item in payload["items"]:
        filename, text, original_uri = _capture_markdown(payload["kind"], item, adapter=store.adapter, relative_root=relative_root)
        relative = (relative_root / filename).as_posix()
        target = safe_child(store.vault, relative)
        existed = target.exists()
        atomic_write(target, text, immutable=True)
        content = item["body_text"] if payload["kind"] == "apple-notes" else item["transcript"]
        captures.append({"path": relative, "sha256": file_hash(target), "canonical_uri": original_uri, "source_kind": payload["kind"] + "-capture", "quote": content if content.strip() else original_uri, "created": not existed})
    if captures:
        indexed = store.index_sources(captures, idempotency_key="native-captures:" + export_token)
    else:
        indexed = None
    report = {"status": "complete", "export_token": export_token, "captures": [{k: v for k, v in capture.items() if k != "quote"} for capture in captures], "index_receipt": indexed}
    return _reported(store, "source-captures", report, sources=captures)


def _configured_path(store: Store, config: dict, key: str, *, exists=False, source=False) -> Path:
    if not isinstance(config.get(key), str) or not Path(config[key]).expanduser().is_absolute():
        raise StoreError("Native configuration needs an absolute " + key + " path")
    path = no_symlinks(Path(config[key]))
    if not source and (path.is_relative_to(store.vault) or store.vault.is_relative_to(path)):
        raise StoreError("Native helper output paths must remain outside the vault")
    if exists and not path.exists():
        raise StoreError("Configured native path is unavailable: " + key)
    return path


def _immutable_audio(source: Path, destination: Path) -> None:
    if source.stat().st_size > 512 * 1024 * 1024:
        raise StoreError("Recording exceeds the configured capture limit")
    expected = file_hash(source)
    no_symlinks(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if file_hash(destination) != expected:
            raise IntegrityError("Existing recording differs; append-only capture cannot replace it")
        return
    fd, temporary = tempfile.mkstemp(prefix=".glide-audio-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        if file_hash(Path(temporary)) != expected:
            raise IntegrityError("Recording changed during capture")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if file_hash(destination) != expected:
                raise IntegrityError("Concurrent recording capture differs")
    finally:
        Path(temporary).unlink(missing_ok=True)


def _playable_m4a(path: Path) -> bool:
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "json", str(path)], capture_output=True, text=True, timeout=15, check=False)
        formats = set(json.loads(result.stdout).get("format", {}).get("format_name", "").split(","))
        return result.returncode == 0 and bool(formats & {"mov", "mp4", "m4a"})
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def voice_memos_sync(store: Store) -> dict:
    store._require_writer()
    config = _native_config(store, "voice_memos")
    source = _configured_path(store, config, "source", exists=True, source=True)
    data_root = _configured_path(store, config, "data_root")
    state_dir = _configured_path(store, config, "state_dir")
    stage = _configured_path(store, config, "staging_vault")
    model = _configured_path(store, config, "model", exists=True)
    if any(path == source or path.is_relative_to(source) or source.is_relative_to(path) for path in (data_root, state_dir, stage)):
        raise StoreError("Voice outputs must not overlap original recordings")
    for key, default, maximum in (("since_days", 7, 31), ("limit", 3, 20), ("threads", 4, 16)):
        value = config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise StoreError("Voice limit is outside the configured bound: " + key)
        config[key] = value
    for directory in (data_root, state_dir, stage):
        directory.mkdir(parents=True, exist_ok=True)
    args = ["--source", str(source), "--data-root", str(data_root), "--vault-root", str(stage), "--state-dir", str(state_dir), "--model", str(model), "--since-days", str(config["since_days"]), "--limit", str(config["limit"]), "--threads", str(config["threads"]), "--copy", "--transcribe", "--stage-notes", "--order", "desc"]
    outcome = _run_helper(config, args, timeout=900)
    report_data = outcome.get("data")
    if not isinstance(report_data, dict):
        report_data = {}
    if any(report_data.get(key, 0) for key in ("root_notes_created", "root_notes_refreshed", "refreshed_notes")):
        raise IntegrityError("Voice helper reported a forbidden note-writing mode")
    if report_data.get("transcribe_failed", 0) and outcome["ok"]:
        outcome = {"ok": False, "error": "Helper reported transcription failures despite a successful exit"}
    if not outcome["ok"]:
        report = {"status": "failed", "error": outcome["error"], "helper_report": report_data}
        return _reported(store, "voice-memos", report)
    manifest_path = safe_child(state_dir, "manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, list):
        raise IntegrityError("Voice helper did not publish a valid manifest")
    legacy = {}
    if config.get("legacy_manifest"):
        old_path = _configured_path(store, config, "legacy_manifest", exists=True, source=True)
        if not old_path.is_relative_to(store.vault):
            raise StoreError("Legacy manifest must refer to the existing vault import state")
        old = json.loads(old_path.read_text())
        legacy = {item["uuid"]: item for item in old if isinstance(item, dict) and isinstance(item.get("uuid"), str)}
    items, retained, pending = [], [], []
    for memo in manifest:
        uuid = memo.get("uuid")
        if not isinstance(uuid, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", uuid):
            raise IntegrityError("Voice manifest contains an invalid original ID")
        old = legacy.get(uuid)
        if old and old.get("note_path"):
            old_note = no_symlinks(Path(old["note_path"]))
            if old_note.is_relative_to(store.vault) and old_note.is_file():
                retained.append({"uuid": uuid, "path": old_note.relative_to(store.vault).as_posix()})
                continue
        if memo.get("transcript_status") != "transcribed":
            pending.append({"uuid": uuid, "status": memo.get("transcript_status", "unknown")})
            continue
        transcript = no_symlinks(Path(memo.get("transcript_txt", "")))
        if not transcript.is_relative_to(state_dir / "Transcripts") or not transcript.is_file() or transcript.stat().st_size > 2 * 1024 * 1024:
            raise IntegrityError("Transcript path is outside the configured staging area")
        audio = no_symlinks(Path(memo.get("audio_copy_path", "")))
        if not audio.is_relative_to(data_root) or not audio.is_file():
            raise IntegrityError("Recording copy is outside the configured data area")
        extension = audio.suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
            raise IntegrityError("Unexpected recording extension")
        asset_relative = Path("system/x/voice-memos") / (uuid + "-" + file_hash(audio)[:12] + extension)
        _immutable_audio(audio, safe_child(store.vault, asset_relative.as_posix()))
        item = {"uuid": uuid, "title": str(memo.get("title") or "Voice Memo"), "recorded_at": memo.get("recorded_at"), "transcript": transcript.read_bytes().decode("utf-8"), "transcript_sha256": file_hash(transcript), "audio_sha256": file_hash(audio), "audio_capture": asset_relative.as_posix(), "source_kind": "automatic-transcription"}
        if memo.get("audio_asset_path"):
            playback = no_symlinks(Path(memo["audio_asset_path"]))
            if not playback.is_relative_to(stage):
                raise IntegrityError("Playback asset is outside the configured staging vault")
            if playback.is_file() and playback.suffix.lower() == ".m4a" and _playable_m4a(playback):
                playback_relative = Path("system/x/voice-memos") / (uuid + "-playback-" + file_hash(playback)[:12] + ".m4a")
                _immutable_audio(playback, safe_child(store.vault, playback_relative.as_posix()))
                item["playback_capture"] = playback_relative.as_posix()
        items.append(item)
    token = _save_export(store, "voice-memos", items)
    captured = capture_export(store, export_token=token)
    report = {"status": "partial" if pending else "complete", "helper_report": report_data, "retained_legacy": retained, "pending": pending, "capture_export_token": token, "capture_count": len(items)}
    if captured["status"] == "publication-pending":
        report["status"] = "publication-pending"
    return _reported(store, "voice-memos", report, captures=captured)
