"""Read-time body windows; never change durable records or their evidence."""
from __future__ import annotations

import hashlib


def record_window(record, *, record_id, at=None, start_line=None, start_offset=None,
                  max_lines=None, max_chars=None):
    """Keep metadata complete while bounding body text, with an exact continuation."""
    options = {"start_line": (start_line, 1, None), "start_offset": (start_offset, 0, None),
               "max_lines": (max_lines, 1, 500), "max_chars": (max_chars, 1, 32768)}
    for name, (value, minimum, maximum) in options.items():
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or value < minimum or (maximum and value > maximum)):
            raise ValueError("Invalid record window " + name)
    first, offset = start_line or 1, start_offset or 0
    count, budget = max_lines or 120, max_chars or 8000
    body = record["body"]
    lines = body.splitlines(keepends=True)
    if first > max(1, len(lines)):
        raise ValueError("start_line is past the end of this record")
    line = lines[first - 1] if lines else ""
    if offset > len(line) or (line and offset == len(line)):
        raise ValueError("start_offset must identify a character in the requested line")
    begin = sum(map(len, lines[:first - 1])) + offset
    end = min(begin + budget, sum(map(len, lines[:first - 1 + count])))
    selected = body[begin:end]
    pinned = {"record_id": record_id, "at": record["recorded_at"],
              "expected_revision": record["revision"]}
    next_args = None
    if end < len(body):
        position = 0
        for number, text in enumerate(lines, 1):
            if end < position + len(text):
                next_args = {**pinned, "start_line": number, "start_offset": end - position,
                             "max_lines": count, "max_chars": budget}
                break
            position += len(text)
    return {**record, "body": selected, "read_window": {
        "partial_record": True, "body_bounded": True, "metadata_bounded": False,
        "start_line": first, "start_offset": offset, "max_lines": count, "max_chars": budget,
        "total_lines": len(lines), "total_chars": len(body),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "truncated": selected != body, "has_more": next_args is not None,
        "next_args": next_args, "full_args": pinned,
        "instruction": "Only the body is bounded; evidence and graph metadata remain complete. "
                       "Expand before preparing a complete revised record. "
                       "A read window cannot be submitted as a durable record."}}
