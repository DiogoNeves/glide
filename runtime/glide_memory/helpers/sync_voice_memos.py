#!/usr/bin/env python3
"""Read macOS Voice Memos and retain copied audio and exact local transcripts.

This helper has no root-note writer, project routing, or interpretation policy.
The fixed broker consumes its manifest and publishes attributed Markdown captures.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

APPLE_EPOCH_OFFSET = 978307200
UUID = re.compile(r"[A-Za-z0-9-]{1,128}")


def safe_path(value):
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Symlink paths are not supported")
    return path


def child(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError("Native source contains an unsafe path")
    return safe_path(root / path)


def sha(path):
    with safe_path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sanitize_filename(value, fallback='Voice Memo', max_len=48):
    # Keep prior importer copy names compatible; identity is always the full UUID.
    text = re.sub(r'[\\/:*?"<>|#^\[\]]+', ' ', value.strip() or fallback)
    return (re.sub(r'\s+', ' ', text).strip(' .') or fallback)[:max_len].strip(' .')


def atomic(path, data):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.capture-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_memos(source, state, data, stage):
    db = child(source, 'CloudRecordings.db')
    if not db.is_file():
        raise ValueError('Voice Memos database not found')
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute('''SELECT c.ZUNIQUEID AS uuid,
          datetime(c.ZDATE + ?, 'unixepoch', 'localtime') AS recorded_at,
          c.ZDURATION AS duration_seconds, c.ZCUSTOMLABEL AS raw_title,
          COALESCE(f.ZENCRYPTEDNAME, '') AS folder, c.ZPATH AS rel_path
          FROM ZCLOUDRECORDING c LEFT JOIN ZFOLDER f ON c.ZFOLDER=f.Z_PK
          ORDER BY c.ZDATE ASC''', (APPLE_EPOCH_OFFSET,)).fetchall()
    memos = []
    identities = set()
    for row in rows:
        uuid = row['uuid']
        if not isinstance(uuid, str) or not UUID.fullmatch(uuid) or uuid in identities:
            raise ValueError('Native recording identity is invalid or duplicated')
        identities.add(uuid)
        recorded = dt.datetime.strptime(row['recorded_at'], '%Y-%m-%d %H:%M:%S')
        raw_title = row['raw_title'] or ''
        title = raw_title if raw_title and not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', raw_title) else 'Voice Memo'
        source_path = child(source, row['rel_path'] or f'{uuid}.missing')
        extension = source_path.suffix.lower() or '.audio'
        if not re.fullmatch(r'\.[a-z0-9]{1,8}', extension):
            raise ValueError('Native audio extension is unsupported')
        stem = sanitize_filename(title if title != 'Voice Memo' else row['folder'])
        name = f'{recorded:%Y-%m-%d %H%M} {stem} {uuid[:8]}{extension}'
        transcript = child(state, f'Transcripts/{uuid}.txt')
        try:
            text = transcript.read_text() if transcript.is_file() else None
            status = 'missing' if text is None else 'blank' if blank(text) else 'transcribed'
        except UnicodeDecodeError:
            text = ''
            status = 'invalid-text'  # Preserve bytes; do not silently repair an old transcript.
        if text is None and child(state, f'Failures/{uuid}.json').exists():
            status = 'failed'
        memos.append({'uuid': uuid, 'title': title, 'recorded_at': row['recorded_at'],
          'duration_seconds': row['duration_seconds'], 'folder': row['folder'],
          'source_path': str(source_path),
          'audio_copy_path': str(child(data, f'audio/{recorded:%Y}/{name}')),
          'audio_asset_path': str(child(stage, f'system/x/voice-memos/{recorded:%Y}/{Path(name).with_suffix(".m4a")}')),
          'transcript_txt': str(transcript),
          'transcript_json': str(transcript.with_suffix('.json')),
          'transcript_status': status})
    return memos


def blank(text):
    return re.sub(r'\s+', ' ', text).strip().upper() in {'', '[BLANK_AUDIO]', '[SILENCE]'}


def command(arguments, timeout=240):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        # Subprocess diagnostics can contain private paths or transcript text.
        raise ValueError(Path(arguments[0]).name + ' failed')
    return result


def copy_audio(memo):
    source, output = safe_path(memo['source_path']), safe_path(memo['audio_copy_path'])
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError('Recording audio is missing or empty')
    before = sha(source)
    if output.exists():
        if sha(output) != before:
            raise ValueError('Existing recording copy differs; reconcile before importing')
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.audio-', dir=output.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        if sha(temporary) != before or sha(source) != before:
            raise ValueError('Recording changed during capture')
        try:
            os.link(temporary, output)
        except FileExistsError:
            if sha(output) != before:
                raise ValueError('Concurrent recording copy differs')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def transcribe(memo, model, threads, state):
    whisper = shutil.which('whisper-cli')
    if not whisper or not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('Install ffmpeg and whisper-cpp before enabling Voice Memos')
    if not safe_path(model).is_file():
        raise ValueError('Configure an existing local whisper.cpp model')
    output = safe_path(memo['transcript_txt'])
    audio = safe_path(memo['audio_copy_path'])
    if output.exists():
        return
    probe = command(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(audio)], 15)
    if 'audio' not in probe.stdout:
        raise ValueError('Recording does not contain a supported audio stream')
    with tempfile.TemporaryDirectory(prefix='voice-transcribe-', dir=state) as temporary:
        scratch = Path(temporary)
        wav, base = scratch/'input.wav', scratch/'transcript'
        command(['ffmpeg', '-v', 'error', '-i', str(audio), '-map', '0:a:0', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)])
        command([whisper, '-m', str(model), '-f', str(wav), '-l', 'auto', '-t', str(threads), '-otxt', '-oj', '-ojf', '-of', str(base), '-np'], 600)
        result = base.with_suffix('.txt')
        if not result.is_file():
            raise ValueError('Transcriber omitted its text output')
        # Publish only completed transcripts. Preserve exact bytes, including whitespace.
        atomic(output, result.read_bytes())
        if base.with_suffix('.json').is_file():
            atomic(output.with_suffix('.json'), base.with_suffix('.json').read_bytes())
    memo['transcript_status'] = 'blank' if blank(output.read_text()) else 'transcribed'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'data-root', 'vault-root', 'state-dir', 'model'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--since-days', type=int, required=True)
    parser.add_argument('--limit', type=int, required=True)
    parser.add_argument('--threads', type=int, required=True)
    parser.add_argument('--order', choices=['asc', 'desc'], default='desc')
    parser.add_argument('--copy', action='store_true')
    parser.add_argument('--transcribe', action='store_true')
    parser.add_argument('--stage-notes', action='store_true', help='Broker compatibility flag; Markdown publication belongs to the broker')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        parser.error('Native Voice Memos requires macOS; no connector was opened')
    if not 1 <= args.since_days <= 31 or not 1 <= args.limit <= 20 or not 1 <= args.threads <= 16:
        parser.error('Invalid bounded processing settings')
    try:
        source, data, state, stage, model = [safe_path(p) for p in (args.source, args.data_root, args.state_dir, args.vault_root, args.model)]
        for output in (data, state, stage):
            if output.is_relative_to(source) or source.is_relative_to(output):
                raise ValueError('Capture outputs must not overlap original recordings')
        state.mkdir(parents=True, exist_ok=True)
        memos = read_memos(source, state, data, stage)
        cutoff = dt.datetime.now() - dt.timedelta(days=args.since_days)
        memos = [m for m in memos if dt.datetime.strptime(m['recorded_at'], '%Y-%m-%d %H:%M:%S') >= cutoff]
        memos.sort(key=lambda m:m['recorded_at'], reverse=args.order=='desc')
        copied = transcribed = failed = attempted = 0
        for memo in memos:
            try:
                if args.copy:
                    copied += int(copy_audio(memo))
                if args.transcribe and memo['transcript_status'] == 'missing' and attempted < args.limit:
                    attempted += 1
                    transcribe(memo, model, args.threads, state)
                    transcribed += 1
            except (OSError, ValueError, subprocess.TimeoutExpired):
                memo['transcript_status'] = 'failed'
                memo['error'] = 'Audio capture or transcription failed; inspect local dependencies and source availability'
                atomic(child(state, f"Failures/{memo['uuid']}.json"), json.dumps({'uuid':memo['uuid'],'status':'failed'}).encode())
                failed += 1
        atomic(child(state, 'manifest.json'), (json.dumps(memos, ensure_ascii=False, indent=2)+'\n').encode())
        print(json.dumps({'count':len(memos),'copied':copied,'transcribed':transcribed,'transcribe_failed':failed,
            'root_notes_created':0,'root_notes_refreshed':0,'refreshed_notes':0}))
        return 1 if failed else 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({'status':'failed','error':type(error).__name__,'transcribe_failed':1}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
