import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from glide_memory.bridge import MemoryServer
from glide_memory.native_tools import apple_notes_metadata, apple_notes_export, capture_export, voice_memos_sync, _capture_markdown
from glide_memory.store import Store, StoreError, IntegrityError


class NativeToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="glide-native-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.original = self.vault / "An authored note.md"
        self.original.write_text("Never edit this authored note.\n")
        self.store = Store.initialize(self.vault, self.root / "state")
        self.store.activate_writer(old_writer_stopped=True)
        self.fail_flag = self.root / "fail-notes"
        self.log = self.root / "notes-args.json"
        self.notes_script = self.root / "notes.py"
        self.notes_script.write_text('''import argparse, json, pathlib, sys
p=argparse.ArgumentParser()
p.add_argument('--days',type=int,required=True)
p.add_argument('--include-body',action='store_true')
p.add_argument('--note-id',action='append',default=[])
a=p.parse_args()
pathlib.Path(LOG).write_text(json.dumps(sys.argv[1:]))
if pathlib.Path(FAIL).exists():
    print('Synthetic metadata failure',file=sys.stderr)
    raise SystemExit(1)
n={'note_id':'note-1','title':'../../A title / with? unsafe: symbols','created':'2026-09-04 00:00:00','modified':'2026-09-05 00:00:00','accounts':['Synthetic'],'folders':['Inbox']}
if a.include_body:
    n.update(body_html='<div>  Exact source text.<br><br>Trailing space  </div>',body_text='  Exact source text.\\n\\nTrailing space  ')
print(json.dumps({'notes':[n], 'coverage':{'status':'complete','errors':[]}}))
'''.replace("LOG", repr(str(self.log))).replace("FAIL", repr(str(self.fail_flag))))
        self.voice_script = self.root / "voice.py"
        self.voice_log = self.root / "voice-args.json"
        self.voice_script.write_text('''import argparse, json, pathlib, sys
p=argparse.ArgumentParser()
for name in ('source','data-root','vault-root','state-dir','model','since-days','limit','threads','order'):
    p.add_argument('--'+name,required=True)
for name in ('copy','transcribe','stage-notes'):
    p.add_argument('--'+name,action='store_true')
a=p.parse_args()
pathlib.Path(LOG).write_text(json.dumps(sys.argv[1:]))
state=pathlib.Path(a.state_dir); data=pathlib.Path(a.data_root)
(state/'Transcripts').mkdir(parents=True,exist_ok=True)
(data/'audio').mkdir(parents=True,exist_ok=True)
transcript=state/'Transcripts'/'SYNTHETIC-UUID-1.txt'
if not transcript.exists(): transcript.write_text('  A raw transcript.\\nTrailing spaces  ')
audio=data/'audio'/'memo.m4a'
if not audio.exists(): audio.write_bytes(b'synthetic original audio')
manifest=[{'uuid':'SYNTHETIC-UUID-1','title':'Original voice idea','recorded_at':'2026-09-05 10:00:00','transcript_status':'transcribed','transcript_txt':str(transcript),'audio_copy_path':str(audio)}]
(state/'manifest.json').write_text(json.dumps(manifest))
print(json.dumps({'transcribed':1,'root_notes_created':0,'root_notes_refreshed':0,'refreshed_notes':0}))
'''.replace("LOG", repr(str(self.voice_log))))
        self.source_audio = self.root / "Original recordings"
        self.source_audio.mkdir()
        self.model = self.root / "model.bin"
        self.model.write_bytes(b"synthetic model placeholder")
        self.configuration = {
            "apple_notes": {"script": str(self.notes_script), "sha256": self.sha(self.notes_script), "max_days": 7},
            "voice_memos": {"script": str(self.voice_script), "sha256": self.sha(self.voice_script), "source": str(self.source_audio), "data_root": str(self.root / "audio-data"), "state_dir": str(self.root / "voice-state"), "staging_vault": str(self.root / "staging-vault"), "model": str(self.model), "since_days": 7, "limit": 3, "threads": 2},
        }
        self.save_config()

    def tearDown(self):
        self.assertEqual(self.original.read_text(), "Never edit this authored note.\n")

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def save_config(self):
        (self.store.state_dir / "native.json").write_text(json.dumps(self.configuration))

    def export_note(self):
        metadata = apple_notes_metadata(self.store)
        return apple_notes_export(self.store, metadata_token=metadata["metadata_token"], note_ids=["note-1"])

    def test_metadata_first_body_allowlist_and_literal_arguments(self):
        metadata = apple_notes_metadata(self.store, days=2)
        self.assertEqual(metadata["status"], "complete")
        self.assertEqual(json.loads(self.log.read_text()), ["--days", "2"])
        with self.assertRaises(StoreError):
            apple_notes_export(self.store, metadata_token=metadata["metadata_token"], note_ids=["--output"])
        exported = apple_notes_export(self.store, metadata_token=metadata["metadata_token"], note_ids=["note-1"])
        self.assertEqual(exported["status"], "complete")
        self.assertEqual(json.loads(self.log.read_text()), ["--days", "2", "--include-body", "--note-id", "note-1"])
        self.assertEqual(exported["notes"][0]["body_text"], "  Exact source text.\n\nTrailing space  ")
        with self.assertRaises(StoreError):
            apple_notes_metadata(self.store, days=8)

    def test_failed_metadata_invalidates_previous_body_grant(self):
        first = apple_notes_metadata(self.store)
        self.fail_flag.write_text("fail")
        failed = apple_notes_metadata(self.store)
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["receipt"]["committed"])
        self.fail_flag.unlink()
        with self.assertRaises(StoreError):
            apple_notes_export(self.store, metadata_token=first["metadata_token"], note_ids=["note-1"])

    def test_legacy_imported_and_skipped_ids_cannot_be_exported_again(self):
        log = self.vault / "Agent HQ/Apple Notes Sync Log.md"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.configuration["apple_notes"]["legacy_log"] = str(log)
        self.save_config()
        for disposition in ("Imported", "Skipped"):
            contents = "## " + disposition + "\n\n| Note ID | Note |\n| --- | --- |\n| `note-1` | Existing source |\n"
            log.write_text(contents)
            metadata = apple_notes_metadata(self.store)
            self.assertEqual(metadata["notes"][0]["previous_disposition"], disposition.lower())
            before = self.log.read_bytes()
            with self.assertRaises(StoreError):
                apple_notes_export(self.store, metadata_token=metadata["metadata_token"], note_ids=["note-1"])
            self.assertEqual(self.log.read_bytes(), before, "body helper must not run for previously handled notes")
            self.assertEqual(log.read_text(), contents)

    def test_append_only_capture_preserves_body_and_export_html(self):
        exported = self.export_note()
        captured = capture_export(self.store, export_token=exported["export_token"])
        path = self.vault / captured["captures"][0]["path"]
        self.assertTrue(path.is_relative_to(self.vault / "Agent HQ/Source Captures/Apple Notes"))
        self.assertNotIn("?", path.name)
        self.assertNotIn(":", path.name)
        text = path.read_text()
        self.assertIn("  Exact source text.\n\nTrailing space  ", text)
        self.assertIn(exported["notes"][0]["body_html"], text)
        self.assertNotIn("\n# ", text)
        before = path.read_bytes()
        repeated = capture_export(self.store, export_token=exported["export_token"])
        self.assertFalse(repeated["captures"][0]["created"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list(path.parent.glob("*.md"))), 1)
        self.assertEqual(captured["sources"][0]["canonical_uri"], "note-1")

    def test_capture_rejects_forged_token_and_tampered_export(self):
        with self.assertRaises(StoreError):
            capture_export(self.store, export_token="../../outside")
        exported = self.export_note()
        cache = self.store.state_dir / "native/exports" / (exported["export_token"] + ".json")
        content = json.loads(cache.read_text())
        content["items"][0]["body_text"] = "Invented replacement"
        cache.write_text(json.dumps(content))
        with self.assertRaises(IntegrityError):
            capture_export(self.store, export_token=exported["export_token"])

    def test_helper_hash_and_extra_argument_configuration_fail_closed(self):
        self.notes_script.write_text("raise RuntimeError('tampered')")
        with self.assertRaises(StoreError):
            apple_notes_metadata(self.store)
        self.assertFalse(self.log.exists())
        self.configuration["voice_memos"]["extra_args"] = ["--write-root-notes"]
        self.save_config()
        with self.assertRaises(StoreError):
            voice_memos_sync(self.store)
        self.assertFalse(self.voice_log.exists())

    def test_voice_fixed_flags_preserve_audio_and_raw_transcript(self):
        result = voice_memos_sync(self.store)
        self.assertEqual(result["status"], "complete")
        args = json.loads(self.voice_log.read_text())
        self.assertTrue(all(flag in args for flag in ("--copy", "--transcribe", "--stage-notes")))
        self.assertEqual(args[args.index("--order") + 1], "desc")
        self.assertNotIn("--write-root-notes", args)
        self.assertNotIn("--refresh-existing-notes", args)
        self.assertEqual(args[args.index("--vault-root") + 1], str(self.root / "staging-vault"))
        source = result["captures"]["sources"][0]
        capture = self.vault / source["path"]
        self.assertIn("  A raw transcript.\nTrailing spaces  ", capture.read_text())
        self.assertIn("recognition errors", capture.read_text())
        self.assertIn("Original recording (download)", capture.read_text())
        self.assertNotIn("![[", capture.read_text(), "unverified audio must not be presented as playable")
        assets = list((self.vault / "system/x/voice-memos").glob("*.m4a"))
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].read_bytes(), b"synthetic original audio")
        before = capture.read_bytes()
        repeated = voice_memos_sync(self.store)
        self.assertFalse(repeated["captures"]["captures"][0]["created"])
        self.assertEqual(capture.read_bytes(), before)

    def test_voice_playback_embeds_only_verified_staged_audio(self):
        playback = self.root / "staging-vault/system/x/playable.m4a"
        playback.parent.mkdir(parents=True)
        playback.write_bytes(b"synthetic verified playback")
        self.voice_script.write_text(self.voice_script.read_text().replace("'audio_copy_path':str(audio)", "'audio_copy_path':str(audio),'audio_asset_path':" + repr(str(playback))))
        self.configuration["voice_memos"]["sha256"] = self.sha(self.voice_script)
        self.save_config()
        with mock.patch("glide_memory.native_tools._playable_m4a", return_value=True) as verify:
            result = voice_memos_sync(self.store)
        verify.assert_called_once_with(playback)
        capture = self.vault / result["captures"]["sources"][0]["path"]
        self.assertIn("![[system/x/voice-memos/SYNTHETIC-UUID-1-playback-", capture.read_text())
        assets = list((self.vault / "system/x/voice-memos").glob("*-playback-*.m4a"))
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].read_bytes(), playback.read_bytes())

    def test_generic_capture_uses_relative_markdown_asset_links(self):
        _, text, _ = _capture_markdown("voice-memos", {"uuid": "EXAMPLE-1", "title": "A voice note", "transcript": "Original words.", "audio_capture": "system/x/voice-memos/original audio.qta", "playback_capture": "system/x/voice-memos/playback.m4a"}, adapter="markdown", relative_root=Path("Glide HQ/Source Captures/Voice Memos"))
        self.assertNotIn("[[", text)
        self.assertIn("[Play recording](../../../system/x/voice-memos/playback.m4a)", text)
        self.assertIn("[Download original recording](../../../system/x/voice-memos/original%20audio.qta)", text)

    def test_capture_lineage_survives_source_read_and_ordinary_reindex(self):
        exported = self.export_note()
        captured = capture_export(self.store, export_token=exported["export_token"])
        path = captured["sources"][0]["path"]
        server = MemoryServer(self.store)
        source = server.call_tool("glide_read_source", {"path": path})
        self.assertEqual(source["canonical_uri"], "note-1")
        self.assertEqual(source["source_kind"], "apple-notes-capture")
        self.store.index_sources([{"path": path, "sha256": source["sha256"]}], idempotency_key="ordinary-reindex")
        reread = server.call_tool("glide_read_source", {"path": path})
        self.assertEqual(reread["canonical_uri"], "note-1")
        self.assertEqual(reread["source_kind"], "apple-notes-capture")

    def test_legacy_manifest_retains_existing_stage_without_duplicate_capture(self):
        stage = self.vault / "Agent HQ/Voice Memos Sync/Staged Notes/Old memo.md"
        stage.parent.mkdir(parents=True)
        stage.write_text("Existing staged original transcription")
        manifest = self.vault / "Agent HQ/Voice Memos Sync/manifest.json"
        manifest.write_text(json.dumps([{"uuid": "SYNTHETIC-UUID-1", "note_path": str(stage)}]))
        self.configuration["voice_memos"]["legacy_manifest"] = str(manifest)
        self.save_config()
        result = voice_memos_sync(self.store)
        self.assertEqual(result["capture_count"], 0)
        self.assertEqual(result["retained_legacy"][0]["path"], stage.relative_to(self.vault).as_posix())
        self.assertEqual(stage.read_text(), "Existing staged original transcription")

    def test_mcp_fixed_tools_reject_config_commands_and_supplied_bodies(self):
        server = MemoryServer(self.store)
        for tool, arguments in (("glide_intake", {"config": {"project_index_root": "/tmp"}}), ("glide_voice_memos_sync", {"args": ["--write-root-notes"]}), ("glide_capture_export", {"export_token": "a" * 64, "body": "Invented"})):
            with self.assertRaises(ValueError):
                server.call_tool(tool, arguments)
        result = server.call_tool("glide_apple_notes_metadata", {"days": 2})
        self.assertEqual(result["status"], "complete")
        exported = server.call_tool("glide_apple_notes_export", {"metadata_token": result["metadata_token"], "note_ids": ["note-1"]})
        captured = server.call_tool("glide_capture_export", {"export_token": exported["export_token"]})
        self.assertEqual(captured["status"], "complete")

    def test_voice_manifest_cannot_read_transcripts_outside_staging(self):
        outside = self.root / "outside-transcript.txt"
        outside.write_text("This is outside the approved transcript directory")
        old = self.voice_script.read_text()
        self.voice_script.write_text(old.replace("'transcript_txt':str(transcript)", "'transcript_txt':" + repr(str(outside))))
        self.configuration["voice_memos"]["sha256"] = self.sha(self.voice_script)
        self.save_config()
        with self.assertRaises(IntegrityError):
            voice_memos_sync(self.store)
        self.assertFalse((self.vault / "Agent HQ/Source Captures").exists())
        self.assertEqual(outside.read_text(), "This is outside the approved transcript directory")

    def test_successful_metadata_scan_does_not_hide_pending_publication(self):
        with mock.patch.object(self.store, "_publish", side_effect=OSError("interrupted publication")):
            result = apple_notes_metadata(self.store)
        self.assertEqual(result["status"], "publication-pending")
        self.assertEqual(result["coverage_status"], "complete")
        self.assertTrue(result["receipt"]["committed"])

    def test_partial_metadata_grants_only_returned_ids_and_preserves_gap(self):
        script = self.notes_script.read_text().replace("'status':'complete','errors':[]", "'status':'partial','errors':[{'stage':'note-metadata','note_id':'unreadable-id','code':-1}]")
        self.notes_script.write_text(script)
        self.configuration["apple_notes"]["sha256"] = self.sha(self.notes_script)
        self.save_config()
        metadata = apple_notes_metadata(self.store)
        self.assertEqual(metadata["status"], "partial")
        self.assertEqual(metadata["coverage"]["errors"][0]["note_id"], "unreadable-id")
        with self.assertRaises(StoreError):
            apple_notes_export(self.store, metadata_token=metadata["metadata_token"], note_ids=["unreadable-id"])
        exported = apple_notes_export(self.store, metadata_token=metadata["metadata_token"], note_ids=["note-1"])
        self.assertEqual(exported["status"], "partial")
        self.assertEqual(exported["notes"][0]["note_id"], "note-1")

    def test_legacy_list_is_unknown_coverage_not_a_clean_scan(self):
        self.notes_script.write_text(self.notes_script.read_text().replace("{'notes':[n], 'coverage':{'status':'complete','errors':[]}}", "[n]"))
        self.configuration["apple_notes"]["sha256"] = self.sha(self.notes_script)
        self.save_config()
        result = apple_notes_metadata(self.store)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["coverage"]["status"], "unknown")
        exported = apple_notes_export(self.store, metadata_token=result["metadata_token"], note_ids=["note-1"])
        self.assertEqual(exported["status"], "unknown")
        self.assertEqual(exported["notes"][0]["note_id"], "note-1")

    def test_structured_global_failure_invalidates_the_grant(self):
        first = apple_notes_metadata(self.store)
        self.notes_script.write_text(self.notes_script.read_text().replace("{'notes':[n], 'coverage':{'status':'complete','errors':[]}}", "{'notes':[], 'coverage':{'status':'failed','errors':[{'stage':'application-access','note_id':None,'code':-600}]}}"))
        self.configuration["apple_notes"]["sha256"] = self.sha(self.notes_script)
        self.save_config()
        failed = apple_notes_metadata(self.store)
        self.assertEqual(failed["status"], "failed")
        with self.assertRaises(StoreError):
            apple_notes_export(self.store, metadata_token=first["metadata_token"], note_ids=["note-1"])


if __name__ == "__main__":
    unittest.main()
