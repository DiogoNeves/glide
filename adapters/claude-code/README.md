# Claude Code Adapter

Use when installing Glide into a Claude Code workspace.

- root instructions: `CLAUDE.md`
- skills: `.claude/skills/<skill-name>/SKILL.md`
- workspace: `Glide HQ/`

Use `ROOT_CLAUDE_SECTION.md` for the root instruction snippet.

## Optional Memory Runtime

Follow [runtime setup](../../docs/MEMORY-RUNTIME.md) and [existing-instance upgrades](../../docs/UPGRADING.md). Install code and local state outside the synchronized workspace; install the selected `glide-memory`, `glide-dream`, `glide-review` and `glide-integrity` skills with `Glide HQ/Memory Protocol.md`. Configure the actual runtime/configuration path on each host.

Verify source-read restrictions through this harness's actual tool and filesystem permissions. A documented rule or narrow file-writing tool does not constrain an unrestricted shell. Fresh scheduled runs use explicit successful cursors; persistent conversation history is not the memory authority. Do not enable duplicate jobs or automatic learned overlays merely by installing the adapter. Interactive review controls must use a working submission bridge and runtime receipt; otherwise use conversation.
