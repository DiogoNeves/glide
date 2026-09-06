#!/usr/bin/env python3
"""Extract compact, read-only context from local Codex rollout logs."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import re
import textwrap


ROLL_OUT_RE = re.compile(
    r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(?P<id>.+)\.jsonl$"
)


def codex_home(value: str | None) -> pathlib.Path:
    if value:
        return pathlib.Path(value).expanduser()
    return pathlib.Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()


def day_dir(home: pathlib.Path, day: str) -> pathlib.Path:
    year, month, dom = dt.date.fromisoformat(day).isoformat().split("-")
    return home / "sessions" / year / month / dom


def clip(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"input_text", "output_text"}:
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def looks_like_context_injection(text: str) -> bool:
    stripped = text.lstrip()
    return (
        stripped.startswith("# AGENTS.md instructions")
        or stripped.startswith("<environment_context>")
        or stripped.startswith("<permissions instructions>")
        or stripped.startswith("<skills_instructions>")
        or stripped.startswith("<plugins_instructions>")
    )


def load_index(home: pathlib.Path) -> dict[str, dict[str, str]]:
    index_path = home / "session_index.jsonl"
    index: dict[str, dict[str, str]] = {}
    if not index_path.exists():
        return index

    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            session_id = item.get("id")
            if isinstance(session_id, str):
                index[session_id] = {
                    "thread_name": str(item.get("thread_name") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                }
    return index


def parse_rollout(path: pathlib.Path, index: dict[str, dict[str, str]]) -> dict[str, object]:
    meta: dict[str, object] = {}
    event_user_messages: list[str] = []
    fallback_user_messages: list[str] = []
    assistant_messages: list[str] = []
    tool_calls: collections.Counter[str] = collections.Counter()

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            item_type = item.get("type")
            payload = item.get("payload") or {}
            if not isinstance(payload, dict):
                continue

            if item_type == "session_meta":
                meta = payload
                continue

            if item_type == "event_msg" and payload.get("type") == "user_message":
                message = payload.get("message")
                if isinstance(message, str) and message.strip():
                    if not looks_like_context_injection(message):
                        event_user_messages.append(message)
                continue

            if item_type != "response_item":
                continue

            if payload.get("type") == "function_call":
                name = payload.get("name")
                if isinstance(name, str):
                    tool_calls[name] += 1
                continue

            if payload.get("type") != "message":
                continue

            role = payload.get("role")
            text = content_text(payload.get("content"))
            if not text.strip() or looks_like_context_injection(text):
                continue

            if role == "user":
                fallback_user_messages.append(text)
            elif role == "assistant":
                assistant_messages.append(text)

    match = ROLL_OUT_RE.match(path.name)
    session_id = str(meta.get("id") or (match.group("id") if match else path.stem))
    indexed = index.get(session_id, {})
    user_messages = event_user_messages or fallback_user_messages

    raw_source = meta.get("source") or meta.get("originator") or ""
    source = raw_source if isinstance(raw_source, str) else json.dumps(raw_source, sort_keys=True)
    internal_prompt = any(
        message.lstrip().startswith("The following is the Codex agent history")
        for message in user_messages[:2]
    )
    internal_source = isinstance(raw_source, dict) and "subagent" in raw_source
    internal_source = internal_source or "approval" in source.lower() or "review" in source.lower()

    return {
        "path": str(path),
        "id": session_id,
        "title": indexed.get("thread_name") or "",
        "updated_at": indexed.get("updated_at") or "",
        "cwd": str(meta.get("cwd") or ""),
        "source": source,
        "started_at": str(meta.get("timestamp") or ""),
        "user_messages": user_messages,
        "assistant_messages": assistant_messages,
        "tool_calls": tool_calls,
        "internal": internal_source or internal_prompt,
    }


def render_session(session: dict[str, object], args: argparse.Namespace) -> str:
    title = str(session["title"] or "Untitled Codex session")
    session_id = str(session["id"])
    cwd = str(session["cwd"])
    started_at = str(session["started_at"])
    updated_at = str(session["updated_at"])
    source = str(session["source"])
    lines = [f"## {title}", ""]
    lines.append(f"- Session: `{session_id}`")
    if started_at:
        lines.append(f"- Started: {started_at}")
    if updated_at:
        lines.append(f"- Updated: {updated_at}")
    if source:
        lines.append(f"- Source: {source}")
    if cwd:
        lines.append(f"- CWD: `{cwd}`")

    tool_calls = session["tool_calls"]
    if isinstance(tool_calls, collections.Counter) and tool_calls:
        top_tools = ", ".join(f"{name} x{count}" for name, count in tool_calls.most_common(8))
        lines.append(f"- Tool calls: {top_tools}")

    user_messages = list(session["user_messages"])[: args.max_messages_per_session]
    if user_messages:
        lines.extend(["", "User prompts:"])
        for message in user_messages:
            lines.append(f"- {clip(str(message), args.max_message_chars)}")

    if args.include_assistant:
        assistant_messages = list(session["assistant_messages"])[: args.max_messages_per_session]
        if assistant_messages:
            lines.extend(["", "Assistant messages:"])
            for message in assistant_messages:
                lines.append(f"- {clip(str(message), args.max_message_chars)}")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    today = dt.date.today().isoformat()
    parser = argparse.ArgumentParser(
        description="Print compact context from local Codex rollout logs for one day."
    )
    parser.add_argument("--date", default=today, help="Local date to scan, YYYY-MM-DD.")
    parser.add_argument("--codex-home", default=None, help="Override CODEX_HOME.")
    parser.add_argument("--cwd-contains", default=None, help="Only include sessions whose cwd contains this text.")
    parser.add_argument("--include-assistant", action="store_true", help="Include assistant message snippets.")
    parser.add_argument("--include-internal", action="store_true", help="Include internal review/subagent sessions.")
    parser.add_argument("--max-sessions", type=int, default=20)
    parser.add_argument("--max-message-chars", type=int, default=500)
    parser.add_argument("--max-messages-per-session", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.max_sessions <= 100 or not 1 <= args.max_message_chars <= 2000 or not 1 <= args.max_messages_per_session <= 20:
        parser.error("Use 1-100 sessions, 1-2000 characters and 1-20 messages per session")
    return args


def main() -> int:
    args = parse_args()
    home = codex_home(args.codex_home)
    directory = day_dir(home, args.date)
    index = load_index(home)
    files = sorted((p for p in directory.glob("rollout-*.jsonl") if not p.is_symlink()), reverse=True)

    print(f"# Codex Daily Context: {args.date}")
    print()
    print(f"- Codex home: `{home}`")
    print(f"- Rollout directory: `{directory}`")
    print("- Mode: read-only transcript extraction for profile signal")
    print()

    if not files:
        print("No rollout files found for this date.")
        return 0

    sessions = [parse_rollout(path, index) for path in files[:args.max_sessions]]
    if not args.include_internal:
        sessions = [s for s in sessions if not s.get("internal")]
    if args.cwd_contains:
        needle = args.cwd_contains.lower()
        sessions = [s for s in sessions if needle in str(s.get("cwd", "")).lower()]

    if not sessions:
        print("No sessions matched the filters.")
        return 0

    print(
        textwrap.fill(
            "Use these snippets as retrieval pointers only. Reopen exact prompts for evidence "
            "before proposing durable memory changes; assistant summaries are not independent sources.",
            width=88,
        )
    )
    print()

    for session in sessions:
        print(render_session(session, args))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
