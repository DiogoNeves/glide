# Install Glide

This file is written for an agent harness to execute, but it is readable by a human.

## Human Summary

The installer should:

1. Start from the root of the target Markdown workspace, company repo, or shared docs folder.
2. Inspect existing files without changing anything.
3. Ask which harness is being used: Codex, Claude Code, other, or manual.
4. Draft company context from existing materials when possible.
5. Ask focused questions to correct or fill the company context.
6. Copy `Glide HQ/` and selected skills only after confirmation.
7. Create or update the root harness instruction file.
8. Inspect available harness connectors and record what is actually connected.
9. Initialize git if the workspace is not already a repository.
10. Create `Glide HQ/Glide Updates.md` with the upstream repo URL and installed release.
11. Mention optional software access guides, including WhatsApp on macOS.
12. Offer starter automations after explicit confirmation.

Glide defines behavior. The harness decides where computation happens and what data is sent.

## Installer Contract

- Install from the workspace root, not a nested folder.
- Do not change files during inspection.
- Do not overwrite existing files without explicit confirmation.
- Do not install automations without explicit confirmation.
- Reading and fetching information is allowed when access is configured.
- Posting, sending, publishing, scheduling, purchasing, approving, deleting, changing external systems, or making commitments requires explicit human approval.

## Step 1: Inspect

Inspect only. Check for:

- existing `Glide HQ/`
- `.agents/skills/`
- `.claude/skills/`
- `AGENTS.md`
- `CLAUDE.md`
- `.git/`
- existing company docs, README files, product docs, strategy notes, customer notes, investor updates, pitch decks, metrics docs, and decision records
- configured connector docs, active connector/tool lists, MCP/app tools, or automation notes

Summarize what exists and what Glide would need to create or update.

If `Glide HQ/` already exists, stop and ask whether to merge carefully, install elsewhere, install only skills, or cancel.

## Step 2: Choose Harness

Recommended mappings:

| Harness | Root instruction file | Skill directory |
| --- | --- | --- |
| Codex | `AGENTS.md` | `.agents/skills/` |
| Claude Code | `CLAUDE.md` | `.claude/skills/` |
| Other/manual | ask the user | ask the user |

Create the root instruction file if missing. If it exists, append or update a clearly marked Glide section and leave unrelated instructions intact.

## Step 3: Draft Company Context

Prefer draft-then-ask.

Read available materials and draft:

- `Glide HQ/Company Context.md`
- `Glide HQ/Founder Brief.md`

Then ask:

- What is wrong?
- What is missing?
- What is uncertain?
- What should the company optimize for right now?

Do not turn missing fields into homework. Ask only the questions that materially improve early recommendations.

## Step 4: Install

After confirmation:

1. Copy `templates/Glide HQ/` into the workspace.
2. Copy selected `skills/glide-*` folders into the harness skill directory.
3. Create or update the root harness instruction file with the relevant adapter snippet.
4. Record installed skills and proposed automations in `Glide HQ/Automation Registry.md`.
5. Create or update `Glide HQ/Connector Inventory.md` from the connectors actually visible to the harness.
6. If the workspace is not already a git repository, run `git init` after confirmation.
7. Add the Glide root instruction section telling agents to keep useful content and harness updates committed with very short commit messages.
8. Set `Glide HQ/Glide Updates.md` with the upstream repo URL, installed release, and update policy.

## Step 5: Offer Starter Automations

Offer only:

- Daily Founder Check-In
- Weekly CEO Review
- Follow-Through Review
- Founder Drift Review
- Nightly Founder Research Review
- Weekly Glide Update Check

Confirm before enabling any automation. If the harness does not support automations, keep the prompts as proposed manual automations in `Glide HQ/Automations/`.

## Step 6: Git Hygiene

If the workspace has no git repository, initialize one after installation confirmation.

Root harness instructions should say:

- Keep meaningful Glide content, context, checklist, skill, automation, and harness updates committed.
- Use very brief commit messages, such as `Update company context`, `Add GTM question`, `Refresh follow-through`, or `Tighten harness rules`.
- Do not commit secrets, credentials, private exports, raw transcripts, or connector data dumps.
- Do not push unless the user or workspace policy says to push.

## Step 7: Connector Inventory

Assume Codex or Claude Code may already have useful connectors, but do not rely on a static registry.

During setup:

1. Inspect the harness-provided tools, MCP servers, apps, plugins, or connector list.
2. Record only what is actually connected in `Glide HQ/Connector Inventory.md`.
3. Ask the user before installing or enabling anything new.
4. Use available connectors for read/fetch workflows when access is granted.
5. For write or external-state changes, draft the action and ask for approval first.

## Step 8: Optional Software Access

Mention that `software/` contains optional guides for connecting other apps. Do not enable app access by default.

If the user wants app access:

1. Ask which software they want to connect.
2. Prefer official connectors, APIs, MCP servers, exports, AppleScript, Shortcuts, or URL schemes before computer control.
3. Add only the relevant app guide or checklist.
4. Record approval boundaries before reading or writing app data.
5. For app-specific behavior, create a small skill and checklist instead of expanding the daily check-in.

Current starter guide:

- `software/whatsapp.md`

## Step 9: Help The User Evolve Glide

Tell the user they can ask Glide to operate differently when the tone, cadence, question style, or proactivity feels wrong.

As confidence increases, suggest automating more areas gradually with clear approval boundaries and small reversible checks first.

## Optional Versioned Memory

If the user selects versioned memory, follow the complete [setup walkthrough](docs/SETUP.md), [runtime contract](docs/MEMORY-RUNTIME.md) and [existing-instance upgrade procedure](docs/UPGRADING.md). Keep Python and SQLite physically outside the synchronized workspace. Install the four memory skills only with their canonical `Memory Protocol.md` and `Checklists/Input and Collaboration.md`. Record the actual runtime entrypoint and private instance configuration. Leave jobs disabled until verified cutover, and leave automatic learned overlays disabled unless explicitly selected. Existing instances must use the upgrade procedure rather than overwrite installation.

The optional runtime is pinned to **0.1.0, build `df711b913f09`** in `compatibility.json`. Use a supplied matching Glide checkout/archive with `runtime/package-manifest.json`; the installer must receive the required `--expected-build` flag:

```sh
python3 "/path/to/glide/runtime/install.py" --source "/path/to/glide/runtime" --home "/path/to/local-glide" --vault "/path/to/workspace" --instance main --adapter markdown --store-path "Glide HQ/Memory" --expected-build df711b913f09
```

Substitute verified local paths. A build or package-manifest mismatch stops installation; do not remove the flag to force a different runtime. See [compatibility](docs/COMPATIBILITY.md) for future pin updates.

Fresh runtime preferences are `--knowledge-review manual --review-ui text`. Optional automatic knowledge requires `--knowledge-review automatic` and one or more explicit `--automatic-source-prefix` values; it retains AI/unreviewed provenance and grants no operational or external-action authority. Presentation is independent: `--review-ui interactive` uses a verified conversation bridge with text fallback. Omitted upgrade preferences preserve local choices. The native helpers ship with the shared runtime; enabling their permissions and private configuration is separate.

## Optional Conversation Continuity

Offer [conversation continuity](docs/CONVERSATION-LEARNING.md) with versioned memory. Install `glide-conversation-learning`, `Conversation Learning.md` and `Conversation Recovery.md`; retain existing source ownership and review settings. Ask which accounts, devices and history sources are authorized for recovery, preserving any existing explicit choices. Live capture of useful current input does not require access to other chats. Install the optional local metadata helper outside the workspace and reuse selected daily/dream/drift jobs; no new permissions or schedules are implied.

## Owner-facing input

Install `Checklists/Input and Collaboration.md` with the core instructions. Explain that Glide HQ is agent-maintained and required questions arrive in conversation. Offer a shared document only when useful or requested; agree on a location outside HQ in the owner's normal writing area and its edit scope before creating it. Do not create a second inbox, export internal records, or infer permission from an AI-assisted label. See [input and collaboration](docs/INPUT-AND-COLLABORATION.md).

## Protect and recover this instance

Follow [instance recovery](docs/RECOVERY.md) before claiming setup or upgrade readiness. Install `Checklists/Recovery.md` and the separately hashed shared helper, inventory private dependencies, preserve backup/export choices, create and verify an approved local export, and test a disposable restore with writers/jobs disabled. Report missing off-machine protection in conversation. Embedded instances need this too; a rebuildable SQLite index does not make all local state disposable.
