"""Small JSON CLI for the local Glide memory broker."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
from .store import Store, StoreError
from .jobs import JOBS, compact_job_inputs, job_input_page, finish_job


def parser():
    p = argparse.ArgumentParser(prog="glide-memory")
    p.add_argument("--config", default=os.environ.get("GLIDE_CONFIG"), help="Local config.json outside the vault")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--vault", required=True)
    init.add_argument("--state-dir", required=True)
    init.add_argument("--store-path", default="Agent HQ/Memory")
    init.add_argument("--adapter", choices=["obsidian", "markdown"], default="obsidian")
    writer = sub.add_parser("writer")
    writers = writer.add_subparsers(dest="writer_command", required=True)
    activate = writers.add_parser("activate")
    activate.add_argument("--old-writer-stopped", action="store_true")
    writers.add_parser("deactivate")
    propose = sub.add_parser("propose")
    propose.add_argument("--file", required=True, help="JSON proposal file, or - for stdin")
    apply = sub.add_parser("apply")
    apply.add_argument("proposal_id")
    apply.add_argument("--decision", choices=["approved", "unreviewed", "rejected"], default="unreviewed")
    apply.add_argument("--idempotency-key")
    apply.add_argument("--actor", default="agent")
    apply.add_argument("--knowledge-ingestion", action="store_true", help="Apply only scoped AI knowledge under the configured automatic policy; remains unreviewed")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--no-sources", action="store_true")
    search.add_argument("--kind")
    search.add_argument("--valid-at")
    search.add_argument("--recorded-at")
    get = sub.add_parser("get")
    get.add_argument("record_id")
    get.add_argument("--at")
    history = sub.add_parser("history")
    history.add_argument("record_id", nargs="?")
    changes = sub.add_parser("changes-since")
    changes.add_argument("cursor", nargs="?")
    rebuild = sub.add_parser("rebuild")
    rebuild.add_argument("--index-only", action="store_true")
    sub.add_parser("verify")
    sub.add_parser("export")
    backup = sub.add_parser("backup")
    backup.add_argument("destination")
    restore = sub.add_parser("restore-snapshot")
    restore.add_argument("source")
    overlay = sub.add_parser("overlay")
    overlay.add_argument("action", choices=["evaluate", "activate", "rollback"])
    overlay.add_argument("--file", required=True, help="JSON: change for evaluate; change/evidence/rationale/idempotency_key for activate; evidence/rationale/idempotency_key for rollback")
    index = sub.add_parser("index-sources")
    index.add_argument("--file", required=True)
    index.add_argument("--idempotency-key", required=True)
    job_input = sub.add_parser("job-inputs")
    job_input.add_argument("job_id", choices=sorted(JOBS))
    job_input.add_argument("--batch-limit", type=int, default=20)
    page = sub.add_parser("job-input-page")
    page.add_argument("job_id", choices=sorted(JOBS))
    page.add_argument("bundle")
    page.add_argument("--cursor", type=int, default=0)
    page.add_argument("--limit", type=int, default=20)
    finish = sub.add_parser("finish-job")
    finish.add_argument("job_id", choices=sorted(JOBS))
    finish.add_argument("--file", required=True, help="Job output JSON file, or - for stdin")
    return p


def read_json(path):
    return json.loads(sys.stdin.read() if path == "-" else Path(path).read_text())


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.command == "init":
            store = Store.initialize(args.vault, args.state_dir, args.store_path, args.adapter)
            result = {"config": str(store.config_path), "store": str(store.store), "writer_active": store.config["writer_active"], "instance_id": store.config["instance_id"]}
        else:
            if not args.config:
                p.error("--config or GLIDE_CONFIG is required")
            store = Store.from_config(args.config)
            match args.command:
                case "writer":
                    result = store.activate_writer(old_writer_stopped=args.old_writer_stopped) if args.writer_command == "activate" else store.deactivate_writer()
                case "propose":
                    result = store.propose(read_json(args.file))
                case "apply":
                    result = store.apply(args.proposal_id, decision=args.decision, idempotency_key=args.idempotency_key, actor=args.actor, knowledge_ingestion=args.knowledge_ingestion)
                case "search":
                    result = store.search(args.query, limit=args.limit, include_sources=not args.no_sources, kind=args.kind, valid_at=args.valid_at, recorded_at=args.recorded_at)
                case "get":
                    result = store.get(args.record_id, at=args.at)
                case "history":
                    result = store.history(args.record_id)
                case "changes-since":
                    result = store.changes_since(args.cursor)
                case "rebuild":
                    result = store.rebuild(publish=not args.index_only)
                case "verify":
                    result = store.verify()
                case "export":
                    result = store.export()
                case "backup":
                    result = store.backup(args.destination)
                case "restore-snapshot":
                    result = store.restore_snapshot(args.source)
                case "overlay":
                    from . import overlays
                    data = read_json(args.file)
                    if args.action == "evaluate":
                        result = overlays.evaluate(store, data.get("change", data))
                    elif args.action == "activate":
                        result = overlays.activate(store, data["change"], evidence=data["evidence"], rationale=data["rationale"], idempotency_key=data["idempotency_key"])
                    else:
                        result = overlays.rollback(store, evidence=data["evidence"], rationale=data["rationale"], idempotency_key=data["idempotency_key"])
                case "index-sources":
                    data = read_json(args.file)
                    result = store.index_sources(data.get("sources", []) if isinstance(data, dict) else data, idempotency_key=args.idempotency_key)
                case "job-inputs":
                    result = compact_job_inputs(store, args.job_id, batch_limit=args.batch_limit)
                case "job-input-page":
                    result = job_input_page(store, args.job_id, args.bundle, cursor=args.cursor, limit=args.limit)
                case "finish-job":
                    result = finish_job(store, args.job_id, **read_json(args.file))
                case _:
                    p.error("Unknown command")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (StoreError, OSError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
