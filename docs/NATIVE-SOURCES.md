# Optional native sources

Core memory needs no native apps. The shared package includes reusable helper source under `runtime/glide_memory/helpers/`; the pinned installer and wheel include it. Enabling a helper is a separate local setup step. It does not change the knowledge-review preference or authorize writing original notes.

| Helper | Input and output | Requirements |
| --- | --- | --- |
| `export_recent_notes.py` | Recent Apple Notes metadata, then selected note bodies as an explicit JSON export | macOS, Notes installed, Apple Automation permission for the invoking process |
| `sync_voice_memos.py` | Read selected recordings; stage copied audio and local transcripts outside the real vault | macOS Voice Memos store access, `ffmpeg`/`ffprobe`, `whisper-cli`, an explicitly installed model |
| `codex_day_context.py` | Bounded local Codex history as source context on stdout | Read permission to the chosen local Codex history; optional, not an automatically enabled broker route |

No helper downloads a model, changes a provider or sends a transcript to a new service. Test ordinary macOS permissions instead of bypassing them. Voice transcription fidelity and actual app-store compatibility need live host checks, separately from synthetic tests.

## Configure Apple Notes

After the core setup, locate `glide_memory/helpers/export_recent_notes.py` under the **installed runtime** recorded in `installation.json`. Measure its hash using Python, not a copied hash from another build:

```sh
python3 - <<'PYTEST'
import hashlib, json, os
from pathlib import Path
helper = Path(os.environ["PYTHONPATH"]) / "glide_memory/helpers/export_recent_notes.py"
print(json.dumps({"apple_notes": {"script": str(helper), "sha256": hashlib.sha256(helper.read_bytes()).hexdigest(), "max_days": 7}}, indent=2))
PYTEST
```

Review the output and save it as `native.json` beside this instance's `config.json`. Keep it local. The runtime verifies the helper path and exact hash before execution; after an upgrade, review changes before admitting a new hash.

Call `glide_apple_notes_metadata(days=2)`. A successful complete or explicitly partial scan grants access only to the IDs actually returned; a failed scan grants none. Preserve reported coverage gaps. Choose relevant IDs from that result, call `glide_apple_notes_export(metadata_token, note_ids)`, then `glide_capture_export(export_token)`. The writer retains a source capture and coverage receipt; original Apple Notes stay unchanged. A failed scan does not mean no updates and cannot authorize body reads. Existing installations can optionally supply a reviewed `legacy_log` for dedupe; don't invent one for a fresh install.

## Configure Voice Memos

Inspect the actual recordings directory on the machine and install the selected transcription dependency/model explicitly. Run the packaged helper's `--help` for its current flags. Configure an additional `voice_memos` object in the same local `native.json`:

```json
{
  "voice_memos": {
    "script": "/absolute/installed/runtime/glide_memory/helpers/sync_voice_memos.py",
    "sha256": "REPLACE_WITH_MEASURED_HELPER_SHA256",
    "source": "/absolute/macos/VoiceMemos/Recordings",
    "data_root": "/absolute/local/glide/voice-data",
    "model": "/absolute/local/models/ggml-model.bin",
    "state_dir": "/absolute/local/glide/voice-state",
    "staging_vault": "/absolute/local/glide/voice-staging",
    "since_days": 7,
    "limit": 5,
    "threads": 4
  }
}
```

`data_root`, `state_dir`, the model, helper and staging directory must be outside the real vault. Create and verify the local directories; never point staging at the original notes. The broker supplies fixed copy/transcribe/stage flags, keeps original recording identity and captures eligible staged Markdown. It does not pass arbitrary shell commands or rewrite root notes. Start with one recording and inspect the actual transcript and receipt, then repeat to confirm dedupe. Preserve a failed transcription as pending instead of claiming complete coverage.

## Optional Codex context

For authorized ongoing conversation recovery, use [Conversation Learning](CONVERSATION-LEARNING.md): app message history plus the separately installed metadata inventory. The legacy date-based snippet helper below does not cover resumed older tasks reliably and must not establish reviewed coverage.

The packaged `codex_day_context.py` is a standalone reader, not an implicit source of durable claims. Inspect `--help`, choose the local Codex history and bounded date/window, and review its stdout before making a sourced capture. For example: `python3 /absolute/installed/runtime/glide_memory/helpers/codex_day_context.py --date 2025-01-01 --codex-home /absolute/private/codex-history --max-sessions 20`. Session records may contain private tool output and inferred progress; a conversation summary is not independent corroboration or delivery evidence. The core installer does not automatically enable this helper or import all conversations.

## Adding another source

Prefer an existing export/API or small reviewed adapter. Keep source IDs, revisions, coverage and exact supporting passages. Original file contents belong in readable captures, while credentials, local paths and temporary exports stay in private application data. Validate duplicate and failure behavior before scheduling. Add only the relevant source skill; do not expand every daily skill with native implementation details.
