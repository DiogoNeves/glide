# Conversation continuity and gradual improvement

Glide should retain useful things said in conversation and let the owner steer it through scoped corrections. The [canonical procedure](../templates/Glide%20HQ/Checklists/Conversation%20Learning.md) distinguishes direct guidance from inferred improvements; protected principles stay stable.

## Install and select sources

With versioned memory enabled, install these files after inspecting local customizations:

- `skills/glide-conversation-learning/` in the harness’s skill location.
- `templates/Glide HQ/Checklists/Conversation Learning.md` in `Glide HQ/Checklists/`.
- `templates/Glide HQ/Checklists/Conversation Recovery.md` alongside it; load this detail only during recovery.

Merge the selected distribution’s routing into active Glide HQ instructions and existing daily/dream/founder-drift procedures. Keep installed paths and baseline hashes in the private installation manifest. The review inbox and `conversation-coverage` use existing managed Markdown records; no new database or schema is needed. Retain the protocol’s manual/automatic knowledge-review policy.

Select the accounts, devices and available history sources with the owner. Existing explicit authorization persists. A company instance must not import a personal account or a separate work instance by assumption. Live capture of useful current conversation is independent of cross-task history access. Missing connectors leave visible coverage gaps.

## Private recovery configuration

Install the skill and both checklists as one unit. Create `conversation-intake.json` beside this instance’s private `config.json`, outside the workspace. It is declarative setup context read by the agent, not a new runtime-parsed configuration format. Start disabled, then fill the selected source/exclusion scopes and authority reference before enabling recovery:

```json
{
  "enabled": false,
  "source_scope": [],
  "excluded_scope": [],
  "bootstrap_hours": 48,
  "max_tasks_per_pass": 5,
  "max_pages_per_task": 2,
  "coverage_record": "conversation-coverage",
  "inbox_record": "conversation-inbox",
  "helper": {
    "python": "/absolute/path/to/python3",
    "path": "/absolute/local/glide/tools/conversation_inventory.py",
    "codex_home": "/absolute/private/codex-history",
    "sha256": "VERIFIED_INSTALLED_FILE_SHA256",
    "repository": "https://github.com/DiogoNeves/glide",
    "source_commit": "REVIEWED_FULL_COMMIT_SHA"
  },
  "installed_at": "ACTUAL_INSTALLATION_TIMESTAMP",
  "authority": "OWNER_SETUP_DECISION_RECEIPT"
}
```

The values above are placeholders, not a ready configuration. If local Codex inventory is not selected, omit `helper`. Record exact account/device/source scope rather than a blanket claim of all history. The agent reads this file before recovery and verifies the helper against the recorded hash; absent or disabled recovery leaves live conversational capture available. Coverage positions and capture outcomes belong in versioned Markdown receipts, not only in this machine configuration. Record the private configuration location in the installed protocol/manifest so subsequent runs can find it.

## Optional local Codex inventory

Where available, the Codex app’s `list_threads`/`read_thread` tools provide the primary history interface. Other harnesses use their configured read-only history interface. The optional `tools/conversation_inventory.py` supplements discovery across local Codex creation dates by reading only metadata and session headers. It does not read messages or establish reviewed coverage.

Copy that file from a trusted, pinned checkout to a versioned directory under local application data **outside the workspace and synchronization roots**. Record the file SHA-256, source commit, installed path and interpreter in the private installation manifest; compare source and destination hashes before use. Do not edit the content-pinned shared runtime or put Python in synced skills. Use Python 3.11+ on a compatible POSIX host; the helper uses `O_NOFOLLOW` and has synthetic checks, while native Windows is unsupported.

Resolve the actual private paths, then inspect the CLI and run a bounded metadata page:

```sh
python3 -B /absolute/local/glide/tools/conversation_inventory.py --help
python3 -B /absolute/local/glide/tools/conversation_inventory.py \
  --codex-home /absolute/private/codex-history \
  --since 2026-01-01T00:00:00+00:00 --limit 20
```

The date above is a synthetic example. Choose the first window from the recovery procedure, then preserve its reviewed-message positions and unfinished ranges. File modification and inventory offsets are discovery hints; changing inventory fingerprints require a new metadata page and identity-based deduplication. Exact user passages, dates and stable message IDs support captures. Selected local logs can be read within authorized source scope when app tools are unavailable; remote history remains unavailable.

## Jobs, verification and upgrades

Reuse the selected daily/dream/founder-drift jobs. Update their actual saved prompts only within the owner’s authorization; installing files does not schedule anything. Daily recovers a bounded batch, dream continues pending work, and drift review checks later behavior. Commit permitted outputs and inspected coverage together through the existing job transaction. Pending manual-review knowledge is not applied knowledge.

Before an upgrade, preserve prior instruction/helper hashes and job prompts. Run the [validation checks](VALIDATION.md#conversation-continuity) and [six synthetic scenarios](../examples/conversation-learning-cases.json), and retain the first real capture receipt plus explicit partial coverage. Compatibility with the runtime depends on the existing memory protocol and record kinds; the core build and schema are unchanged. The helper and tests are distributed byte-identically in both Glide repositories. When releasing either copy, compare both against the corresponding reviewed checkout:

```sh
cmp tools/conversation_inventory.py /absolute/path/to/glide-obsidian/tools/conversation_inventory.py
cmp tests/test_conversation_inventory.py /absolute/path/to/glide-obsidian/tests/test_conversation_inventory.py
```

A matching copy proves code identity, not comprehensive history access or long-term usefulness. Native Obsidian daily-note output remains specific to the Obsidian distribution.

To roll back a procedural change, restore its recorded prior instructions and job prompt while preserving user decisions and receipts. Clear direct guidance can be corrected or withdrawn through conversation. Inferred procedural candidates stay inactive until reviewed. Automatic activation remains limited to the runtime’s typed retrieval/context overlays and existing evaluation/rollback policy.
