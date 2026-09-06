# Set up versioned memory

Use this walkthrough after selecting the optional runtime in [INSTALL.md](../INSTALL.md). Existing instances follow [UPGRADING.md](UPGRADING.md) first. Commands below run from a terminal you control, not the restricted source-reading agent. Paths are examples; resolve real directories before running them. No command downloads a model, creates a schedule or publishes data.

## Requirements and choices

- Python 3.11+ with SQLite FTS5. The storage implementation uses POSIX file locking; macOS is the validated execution platform. Linux core operation needs its own host checks; the protected native runner and Apple adapters are macOS-only. Native Windows is unsupported; WSL is not a tested protection substitute.
- A trusted matching Glide source checkout/archive, including `runtime/package-manifest.json`. Obsidian also needs its matching distribution checkout. A Git checkout is not evidence that a release was published.
- An existing workspace and a separate local application-data directory, outside Git/Obsidian/cloud-sync roots. Use macOS `~/Library/Application Support/Glide`; use a private local application-data location for an independently validated POSIX host.
- One writer per instance. Other machines may read Markdown or rebuild a local index without becoming writers.

Installation preferences are independent:

| Option | Default | Meaning |
| --- | --- | --- |
| `--knowledge-review manual` | manual | Present knowledge proposals for a conversational decision; job transactions cannot include knowledge outputs. |
| `--knowledge-review automatic` | opt-in | Apply eligible AI knowledge without a mandatory confirmation UI, only from explicitly selected source prefixes. |
| `--automatic-source-prefix Clippings` | none | Repeat to allow additional workspace-relative source areas for automatic knowledge ingestion. |
| `--review-ui text` | text | Show concise evidence, proposed changes and choices in the conversation. |
| `--review-ui interactive` | opt-in | Use interactive reviews when the host has a working submission bridge; retain text fallback. |

Automatic processing does not mean human approval: derived records remain `origin: ai` and `review: unreviewed`. It does not create commitments, change goals, close loops or grant permission to send messages, move money or alter an external service. Learned overlays are a separate opt-in. On upgrades, omitted preferences preserve existing settings and absent keys; see the [review-policy contract](MEMORY-RUNTIME.md#setup-and-review-preferences).

## 1. Install a fresh synthetic instance

Try the complete flow in an isolated folder before pointing it at valuable material. Choose **one** distribution configuration:

```sh
export GLIDE_PACKAGE='/absolute/path/to/glide'
export GLIDE_DIST="$GLIDE_PACKAGE"
export GLIDE_ADAPTER='markdown'
export GLIDE_STORE='Glide HQ/Memory'
```

For Obsidian, change `GLIDE_DIST` to the matching `glide-obsidian` checkout, `GLIDE_ADAPTER` to `obsidian`, and `GLIDE_STORE` to `Agent HQ/Memory`. The shared Python still comes from `GLIDE_PACKAGE/runtime`.

```sh
export GLIDE_TRIAL="$(python3 -c 'import tempfile; from pathlib import Path; print(Path(tempfile.mkdtemp(prefix="glide-trial-")).resolve())')"
export GLIDE_VAULT="$GLIDE_TRIAL/workspace"
export GLIDE_LOCAL="$GLIDE_TRIAL/local"
mkdir -p "$GLIDE_VAULT/Clippings"
export GLIDE_BUILD="$(python3 -c 'import json,os; from pathlib import Path; print(json.loads((Path(os.environ["GLIDE_DIST"])/"compatibility.json").read_text())["optional_memory_runtime"]["build"])')"
python3 "$GLIDE_PACKAGE/runtime/install.py" \
  --source "$GLIDE_PACKAGE/runtime" --home "$GLIDE_LOCAL" \
  --vault "$GLIDE_VAULT" --instance demo --adapter "$GLIDE_ADAPTER" \
  --store-path "$GLIDE_STORE" --expected-build "$GLIDE_BUILD" \
  --knowledge-review manual --review-ui text
export GLIDE_CONFIG="$GLIDE_LOCAL/instances/demo/config.json"
export PYTHONPATH="$(python3 -c 'import json,os; from pathlib import Path; print(json.loads((Path(os.environ["GLIDE_CONFIG"]).parent/"installation.json").read_text())["runtime"])')"
export PYTHONDONTWRITEBYTECODE=1
python3 -m glide_memory --config "$GLIDE_CONFIG" verify
```

The installer checks the content pin before loading package code. Leave the pin check in place; resolve a mismatch rather than editing the manifest to accept it. The new writer starts **inactive**. Source checks reject symlinked paths; if your temporary directory resolves through a symlink, use its physical path.

For a real install, substitute the existing workspace and local application-data directory, select an instance name, and repeat the verified command. Do not reuse the disposable instance's identity or copy its fictional records into production.

## 2. Activate and prove source → proposal → receipt

In this new fixture there is no previous writer. For a real handover, stop the old writer and its jobs first. The following assertion does not stop another machine:

```sh
python3 -m glide_memory --config "$GLIDE_CONFIG" writer activate --old-writer-stopped
```

The following synthetic check calls the same bounded tool dispatcher exposed by MCP. Its `unreviewed` decision is explicitly limited to this fixture; it is not a human-approval claim.

```sh
python3 - <<'PYTEST'
import hashlib, json, os
from pathlib import Path
from glide_memory import Store
from glide_memory.bridge import MemoryServer
store = Store.from_config(os.environ["GLIDE_CONFIG"])
source = store.vault / "Clippings/Fictional sample labels.md"
source.write_text("Specimen labels help locate experimental samples.\n")
before = source.read_bytes()
server = MemoryServer(store)
read = server.call_tool("glide_read_source", {"path": source.relative_to(store.vault).as_posix()})
evidence = {"path": read["path"], "sha256": read["sha256"], "quote": "Specimen labels help locate experimental samples.", "locator": "line 1"}
record = {"id": "demo:specimen", "title": "Specimen labels", "kind": "knowledge", "origin": "ai", "review": "unreviewed", "status": "active", "body": "A fictional experiment uses specimen labels to locate samples. This fixture does not establish a universal lab practice.", "sources": [evidence]}
proposal = server.call_tool("glide_propose", {"records": [record], "expected_revisions": {record["id"]: 0}, "rationale": "Synthetic setup check", "idempotency_key": "demo-proposal"})
arguments = {"proposal_id": proposal["proposal_id"], "decision": "unreviewed", "expected_revisions": {record["id"]: 0}, "idempotency_key": "demo-apply"}
receipt = server.call_tool("glide_apply", arguments)
assert receipt["committed"]
assert server.call_tool("glide_apply", arguments)["bundle"] == receipt["bundle"]
assert store.get(record["id"])["origin"] == "ai"
assert source.read_bytes() == before
assert store.verify()["ok"]
print(json.dumps({"receipt": receipt, "source_unchanged": True}, indent=2))
PYTEST
```

Read the resulting `Records/` page and `Views/Durable.md`. It should link back to the original clipping, with its exact retained passage and fingerprint. The receipt is the evidence of application; a selected button, successful proposal or agent statement is not.

## 3. Install the protocol and skills on each device

Copy the selected distribution's `templates/Glide HQ/Memory Protocol.md`, `templates/Glide HQ/Checklists/Input and Collaboration.md` and four `skills/glide-{memory,dream,review,integrity}` folders after inspecting the destination. The Obsidian equivalent is `templates/Agent HQ/Memory Protocol.md`. Merge existing installations using their recorded baseline; never overwrite local customization just because a new package exists.

For Codex, skills belong in `.agents/skills/` or another supported local discovery location; for Claude Code use `.claude/skills/`. Record installed paths and content hashes in the private installation manifest. Install code and dependencies outside the synchronized workspace. Device-specific skill discovery/configuration must be checked on each machine; hidden folders are not an Obsidian Sync installation strategy.

In the workspace's root agent instructions, identify the managed store, the local configuration path, the protocol and source-ownership boundary. Do not duplicate the whole protocol in every skill. Reload the harness and confirm it actually discovers all selected skills.

## 4. Connect Codex with a restricted reader

Merge this example into the target project's `.codex/config.toml`, preserving unrelated settings. Replace all three absolute paths using the installation receipt. Do not copy another machine's credentials or configuration.

```toml
sandbox_mode = "read-only"
approval_policy = "on-request"
approvals_reviewer = "user"

[mcp_servers.glide_memory]
command = "/absolute/path/to/python3"
args = ["-m", "glide_memory.bridge", "--config", "/absolute/local/state/config.json"]
startup_timeout_sec = 30
tool_timeout_sec = 300

[mcp_servers.glide_memory.env]
PYTHONPATH = "/absolute/local/runtime/0.1.0-CONTENT_BUILD"
PYTHONDONTWRITEBYTECODE = "1"
```

The model's ordinary shell is read-only; the fixed MCP process is the separate trusted writer. Tool approval configuration is distinct from filesystem sandboxing. Review the configured tools and explicitly disable any alternative unrestricted filesystem, shell or computer-control route that could bypass this project's source boundary. Preserve unrelated authorized connectors; do not globally disable useful apps.

Use the actual current Codex binary's `mcp list --json`, then start a fresh task in this project. In the synthetic workspace ask it to read the clipping, retrieve `demo:specimen`, and propose a sourced revision. Give a real decision and inspect the returned revision receipt. Separately test that shell, direct write, symlink/hardlink and any exposed alternate tool cannot change the synthetic original. A passed storage test is not proof of this execution boundary.

These settings follow [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) and [security guidance](https://learn.chatgpt.com/docs/security). Harness versions and managed policy can affect availability; inspect the effective settings, not only this snippet.

## 5. Add bounded intake

Put this optional `intake.json` beside the instance's `config.json`:

```json
{
  "source_batch_size": 100,
  "source_max_bytes": 2097152,
  "source_excluded_roots": [],
  "project_index_root": null,
  "project_max_commits": 100,
  "project_lookback_days": 14
}
```

Run one batch with `glide_intake` or:

```sh
python3 -m glide_memory.pipeline --config "$GLIDE_CONFIG" --sources-only
```

This registers permitted changed Markdown where it already lives. It is not a completed knowledge extraction or proof of trusted claims. Honor reported pending, missing and unavailable coverage; don't treat an earlier scheduled start as a completed dependency. Set `project_index_root` only to an inspected local project index outside the workspace; its repository paths and exclusions are instance-specific. Git commits establish repository activity, not shipped outcomes.

For optional Apple Notes, Voice Memos and Codex-context inputs, follow [NATIVE-SOURCES.md](NATIVE-SOURCES.md). Imports and original-note capture are independent of the knowledge-review preference.

## 6. Choose knowledge processing and reviews

To opt into automatic knowledge for a defined inbox, repeat the installer for the same instance with `--knowledge-review automatic --automatic-source-prefix Clippings`. Add `--review-ui interactive` only if wanted. This changes local preferences; it does not process sources or create a schedule by itself.

Eligible extracted knowledge uses `glide_apply` with `knowledge_ingestion: true`, `decision: "unreviewed"`, the proposal ID, expected revisions and an idempotency key. The runtime admits only scoped AI knowledge; operations use their existing separately authorized procedure. Manual wiki ingestion uses a conversational decision and normal `glide_apply`, separately from job checkpoints. Follow the [review-policy contract](MEMORY-RUNTIME.md#setup-and-review-preferences), including the distinct legacy-upgrade case. No interactive UI is required in either mode.

For interactive reviews, render the reusable review packet only in a host with a verified follow-up bridge. A click submits a decision for validation; the writer checks current revisions, applies once and returns a receipt. If the bridge is absent or rendering fails, show the same evidence and choices in text. Mobile behavior must be tested separately. See [the review contract](MEMORY-RUNTIME.md).

## 7. Enable learning and schedules separately

Learned overlays are off by default. To test them, use [the synthetic overlay fixture](../examples/overlay-setup.md) in the disposable instance. Real use needs a frozen, content-pinned regression/held-out set with cases grounded in actual failures. Eligible automatic changes are limited to retrieval aliases and context priority, with one candidate attempt per week and durable rollback. Knowledge mode does not enable this permission.

Use the [optional automation portfolio](../automations/portable-memory.md). Only create schedules after the owner selects cadence, timezone, model/effort, scope and output destination. Keep fresh runs backed by explicit `glide_job_inputs`/`glide_finish_job` checkpoints; do not use an ever-growing conversation as the authoritative store. Verify intake receipts before dependent work. Inspect existing jobs to prevent duplicate writers. Test a scheduled run on the actual awake host before calling scheduling reliable.

## 8. Recover and stop the trial

Run [VALIDATION.md](VALIDATION.md), including a copied-store rebuild. Preserve its receipt if this is release evidence. Then deactivate the trial writer:

```sh
python3 -m glide_memory --config "$GLIDE_CONFIG" writer deactivate
```

Keep or remove only the disposable directory you created, after inspecting its path. Production cutover, backups and machine transfer follow [UPGRADING.md](UPGRADING.md).

## Optional conversation continuity

For meaningful conversational capture and optional history recovery, follow [Conversation Learning](CONVERSATION-LEARNING.md). Install its skill and both checklists; select authorized history sources independently of knowledge-review mode. Install the metadata helper outside the workspace only when local Codex discovery is wanted. Existing schedules can run the bounded recovery branch after their prompts are explicitly updated; installing templates alone changes no job.

## Owner-facing input

Install [Input and Collaboration](INPUT-AND-COLLABORATION.md) and its canonical checklist with the memory protocol. Setup verification may inspect internal records; normal use never depends on the owner editing them. Required questions and spot checks arrive in conversation. Choose an external collaboration destination only when a shared document is useful, with clear AI attribution and explicit edit scope.
