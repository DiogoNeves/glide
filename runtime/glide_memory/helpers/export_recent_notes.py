#!/usr/bin/env python3
"""Export recent Apple Notes metadata, and optionally selected note bodies."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path




class NotesHTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "div", "p", "li", "h1", "h2", "h3"}:
            self._newline()
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"div", "p", "li", "h1", "h2", "h3"}:
            self._newline()

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def _newline(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [line.strip() for line in raw.splitlines()]
        compact: list[str] = []
        blank = False
        for line in lines:
            if not line:
                if not blank and compact:
                    compact.append("")
                blank = True
                continue
            compact.append(line)
            blank = False
        return "\n".join(compact).strip()




def build_script() -> str:
    return """
function run(argv) {
  const daysBack = Number(argv[0]);
  let includeBody = false;
  const requestedIds = [];
  for (const argValue of argv.slice(1)) {
    if (argValue === "--include-body") {
      includeBody = true;
    } else {
      requestedIds.push(String(argValue));
    }
  }

  const requested = new Set(requestedIds);
  const hasRequestedIds = requestedIds.length > 0;
  const cutoff = new Date(Date.now() - daysBack * 24 * 60 * 60 * 1000);
  const notes = [];
  const errors = [];
  let excluded = 0;
  let notesApp;

  function recordError(stage, noteId, error) {
    errors.push({stage: stage, note_id: noteId || null,
      code: error && typeof error.number === "number" ? error.number : null});
  }
  function result(status) {
    return JSON.stringify({notes: notes, coverage: {
      status: status || (errors.length ? "partial" : "complete"),
      errors: errors, excluded: excluded, returned: notes.length,
      scope: "requested IDs or created/modified date queries; protected and deleted folders excluded"
    }});
  }
  try {
    notesApp = Application("Notes");
  } catch (error) {
    recordError("application-access", null, error);
    return result("failed");
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function formatDate(dateValue) {
    return [
      dateValue.getFullYear(),
      pad2(dateValue.getMonth() + 1),
      pad2(dateValue.getDate()),
    ].join("-") + " " + [
      pad2(dateValue.getHours()),
      pad2(dateValue.getMinutes()),
      pad2(dateValue.getSeconds()),
    ].join(":");
  }

  function pushNote(note) {
    let noteId = null;
    try {
      noteId = String(note.id());
      const folder = note.container();
      const folderName = String(folder.name());
      if (
        folderName === "Recently Deleted" ||
        folderName.includes("Protected") ||
        folderName.includes("🔐")
      ) {
        excluded += 1;
        return;
      }

      let accountName = "";
      try {
        accountName = String(folder.container().name());
      } catch (error) {
        recordError("account-metadata", noteId, error);
      }

      const exported = {note_id: noteId, title: String(note.name()),
        created: formatDate(note.creationDate()), modified: formatDate(note.modificationDate()),
        accounts: [accountName], folders: [folderName]};
      if (includeBody) {
        exported.body_html = String(note.body());
      }
      notes.push(exported);
    } catch (error) {
      recordError(includeBody ? "note-body-or-metadata" : "note-metadata", noteId, error);
    }
  }

  if (hasRequestedIds) {
    for (const noteId of requested) {
      try {
        const matches = notesApp.notes.whose({id: noteId})();
        if (!matches.length) recordError("requested-note-not-found", noteId, null);
        for (const note of matches) pushNote(note);
      } catch (error) {
        recordError("query-requested-id", noteId, error);
      }
    }
  } else {
    const notesById = new Map();
    function collect(field) {
      try {
        const filter = {};
        filter[field] = {_greaterThan: cutoff};
        for (const note of notesApp.notes.whose(filter)()) {
          try {
            notesById.set(String(note.id()), note);
          } catch (error) {
            recordError("note-identity", null, error);
          }
        }
      } catch (error) {
        recordError("query-" + field, null, error);
      }
    }
    collect("creationDate");
    collect("modificationDate");
    for (const note of notesById.values()) pushNote(note);
  }

  return result();
}
"""


def parse_payload(raw: str, include_body: bool) -> dict:
    """Preserve native coverage and exact HTML; text is a derived display field."""
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("notes"), list):
        raise ValueError("Native export did not contain a structured note list")
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("status") not in {"complete", "partial", "failed"} or not isinstance(coverage.get("errors"), list):
        raise ValueError("Native export did not contain explicit coverage")
    if coverage["errors"] and coverage["status"] == "complete":
        coverage["status"] = "partial"
    notes = {}
    for item in payload["notes"]:
        if not isinstance(item, dict) or not isinstance(item.get("note_id"), str):
            raise ValueError("Native export contained malformed metadata")
        if include_body:
            if not isinstance(item.get("body_html"), str):
                raise ValueError("Requested body export omitted its HTML")
            parser = NotesHTMLToText()
            parser.feed(item["body_html"])
            item["body_text"] = parser.text()
        elif "body_html" in item or "body_text" in item:
            raise ValueError("Metadata-only export unexpectedly contained a body")
        previous = notes.get(item["note_id"])
        if previous:
            previous["accounts"] = sorted(set(previous["accounts"]) | set(item["accounts"]))
            previous["folders"] = sorted(set(previous["folders"]) | set(item["folders"]))
        else:
            notes[item["note_id"]] = item
    return {"notes": sorted(notes.values(), key=lambda item: (item["created"], item["modified"], item["title"])), "coverage": coverage}




def run_osascript(days: int, include_body: bool, note_ids: list[str]) -> str:
    args = ["osascript", "-l", "JavaScript", "-", str(days)]
    if include_body:
        args.append("--include-body")
    args.extend(note_ids)
    result = subprocess.run(
        args,
        input=build_script(),
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=2, help="Recent window for metadata export.")
    parser.add_argument("--include-body", action="store_true", help="Include Apple Notes body HTML and stripped text.")
    parser.add_argument("--note-id", action="append", default=[], help="Specific Apple Note ID to export. Repeatable.")
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout.")
    args = parser.parse_args()
    if not 1 <= args.days <= 31:
        parser.error("--days must be between 1 and 31")
    if args.include_body and not args.note_id:
        parser.error("Body export requires explicit --note-id values after a successful metadata scan")
    if sys.platform != "darwin":
        parser.error("Apple Notes export requires macOS")

    raw = run_osascript(args.days, args.include_body, args.note_id)
    payload = json.dumps(parse_payload(raw, args.include_body), indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
