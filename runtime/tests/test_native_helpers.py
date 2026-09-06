import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from glide_memory.helpers import export_recent_notes as notes
from glide_memory.helpers import sync_voice_memos as voice
from glide_memory.helpers import codex_day_context as context


class NativeHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root/'Recordings'; self.source.mkdir()
        self.state = self.root/'state'; self.state.mkdir()
        self.data = self.root/'data'
        self.stage = self.root/'stage'
        self.db = self.source/'CloudRecordings.db'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE ZFOLDER (Z_PK INTEGER, ZENCRYPTEDNAME TEXT)')
            db.execute('CREATE TABLE ZCLOUDRECORDING (ZUNIQUEID TEXT, ZDATE REAL, ZDURATION REAL, ZCUSTOMLABEL TEXT, ZFOLDER INTEGER, ZPATH TEXT)')
            db.execute("INSERT INTO ZCLOUDRECORDING VALUES ('SYNTHETIC-UUID', 810000000, 2.0, 'Example thought', NULL, 'recording.m4a')")
        (self.source/'recording.m4a').write_bytes(b'original synthetic audio')

    def test_notes_coverage_and_raw_html_are_retained(self):
        raw = {'notes':[{'note_id':'example','title':'Example','created':'2026-09-01','modified':'2026-09-02','accounts':['Example'],'folders':['Inbox'],'body_html':'<div>  Original &amp; text </div>'}], 'coverage':{'status':'complete','errors':[]}}
        exported = notes.parse_payload(json.dumps(raw), True)
        self.assertEqual(raw['notes'][0]['body_html'], exported['notes'][0]['body_html'])
        with self.assertRaises(ValueError):
            notes.parse_payload(json.dumps(raw), False)
        raw['coverage']['errors']=[{'stage':'note-metadata','note_id':'unread','code':1}]
        self.assertEqual('partial', notes.parse_payload(json.dumps(raw), True)['coverage']['status'])

    def test_notes_body_cli_requires_specific_ids(self):
        with patch('sys.argv', ['helper','--include-body']), patch.object(notes,'run_osascript') as run, self.assertRaises(SystemExit):
            notes.main()
        run.assert_not_called()

    def test_voice_metadata_is_read_only_and_uuid_paths_remain_compatible(self):
        before = self.db.read_bytes()
        memo = voice.read_memos(self.source,self.state,self.data,self.stage)[0]
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(self.state/'Transcripts/SYNTHETIC-UUID.txt', Path(memo['transcript_txt']))
        self.assertEqual('Example thought', memo['title'])
        Path(memo['transcript_txt']).parent.mkdir()
        Path(memo['transcript_txt']).write_text('  Preserve exact text.\n')
        self.assertEqual('transcribed', voice.read_memos(self.source,self.state,self.data,self.stage)[0]['transcript_status'])
        self.assertEqual('  Preserve exact text.\n', Path(memo['transcript_txt']).read_text())

    def test_voice_malformed_historical_transcript_is_preserved_and_flagged(self):
        transcript=self.state/'Transcripts/SYNTHETIC-UUID.txt';transcript.parent.mkdir();transcript.write_bytes(b'bad \xff bytes')
        memo=voice.read_memos(self.source,self.state,self.data,self.stage)[0]
        self.assertEqual('invalid-text',memo['transcript_status'])
        self.assertEqual(b'bad \xff bytes',transcript.read_bytes())

    def test_voice_rejects_traversal_and_symlink_source(self):
        for path in ('../outside.m4a','/outside.m4a'):
            with sqlite3.connect(self.db) as db:
                db.execute('UPDATE ZCLOUDRECORDING SET ZPATH=?',(path,))
            with self.assertRaises(ValueError):
                voice.read_memos(self.source,self.state,self.data,self.stage)
        (self.source/'linked.m4a').symlink_to(self.source/'recording.m4a')
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE ZCLOUDRECORDING SET ZPATH='linked.m4a'")
        with self.assertRaises(ValueError):
            voice.read_memos(self.source,self.state,self.data,self.stage)

    def test_voice_copy_checks_content_not_only_size_and_preserves_original(self):
        memo = voice.read_memos(self.source,self.state,self.data,self.stage)[0]
        original = (self.source/'recording.m4a').read_bytes()
        self.assertTrue(voice.copy_audio(memo))
        self.assertFalse(voice.copy_audio(memo))
        output=Path(memo['audio_copy_path']); output.write_bytes(b'x'*len(original))
        with self.assertRaises(ValueError):
            voice.copy_audio(memo)
        self.assertEqual(original, (self.source/'recording.m4a').read_bytes())
        self.assertEqual(b'x'*len(original), output.read_bytes())

    def test_voice_transcript_is_published_only_after_success(self):
        memo = voice.read_memos(self.source,self.state,self.data,self.stage)[0]
        voice.copy_audio(memo)
        model=self.root/'model.bin';model.write_bytes(b'placeholder')
        def run(args, *unused):
            if args[0]=='ffprobe':
                return subprocess.CompletedProcess(args,0,'audio\n','')
            if args[0].endswith('whisper-cli'):
                Path(args[args.index('-of')+1]+'.txt').write_bytes(b'  Exact transcript.\n\n')
            return subprocess.CompletedProcess(args,0,'','')
        with patch.object(voice.shutil,'which',side_effect=lambda value:value),patch.object(voice,'command',side_effect=run):
            voice.transcribe(memo,model,2,self.state)
        self.assertEqual(b'  Exact transcript.\n\n',Path(memo['transcript_txt']).read_bytes())
        Path(memo['transcript_txt']).unlink()
        with patch.object(voice.shutil,'which',side_effect=lambda value:value),patch.object(voice,'command',side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):
                voice.transcribe(memo,model,2,self.state)
        self.assertFalse(Path(memo['transcript_txt']).exists())

    def test_voice_no_root_writer_or_refresh_flags(self):
        with self.assertRaises(SystemExit):
            voice.main(['--write-root-notes'])
        source = Path(voice.__file__).read_text()
        self.assertNotIn('def write_root_notes',source)
        self.assertNotIn('def route_memo',source)

    def test_codex_context_excludes_injected_user_context_and_marks_internal(self):
        path = self.root/'rollout-synthetic.jsonl'
        entries=[{'type':'session_meta','payload':{'id':'synthetic','source':{'subagent':'review'}}},
                 {'type':'event_msg','payload':{'type':'user_message','message':'# AGENTS.md instructions\nDo not count this'}},
                 {'type':'event_msg','payload':{'type':'user_message','message':'An actual user thought'}}]
        path.write_text('\n'.join(json.dumps(e) for e in entries))
        before=path.read_bytes(); parsed=context.parse_rollout(path,{})
        self.assertTrue(parsed['internal'])
        self.assertEqual(['An actual user thought'],parsed['user_messages'])
        self.assertEqual(before,path.read_bytes())
        with self.assertRaises(ValueError):
            context.day_dir(self.root,'../../other')


if __name__ == '__main__':
    unittest.main()
