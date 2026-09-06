# Glide

Glide helps founders and CEOs keep context, question assumptions and follow through using Markdown and an AI agent.

Talk to it in Codex, Claude Code or another supported harness. Keep writing in your existing files. Glide connects useful knowledge and maintains open loops, decisions and workflows in `Glide HQ/`.

## Three parts

- **Your writing:** original notes and source material, preserved unchanged.
- **Knowledge:** useful concepts with supporting passages, dates, uncertainty and meaningful links.
- **Operations:** intentions, commitments, decisions and outcomes, kept distinct.

The optional memory runtime stores durable records and complete revision history in **human-readable Markdown**. SQLite is a local, rebuildable search index. Python, the database and private machine configuration stay outside the synchronized workspace. Both Glide editions use the same runtime; no empty database needs downloading.

Reviews work in conversation. Text is the default; interactive reviews are optional and only report success after a real writer receipt. Optional automatic knowledge processing keeps its output marked as AI and unreviewed. It does not authorize external actions.

The recorded local validation passed **139 runtime tests**, including recovery after deleting a disposable SQLite index. [Validation details](docs/VALIDATION.md) explain the checks, model screen and remaining field observations.

## Get started

Ask your agent to follow [INSTALL.md](INSTALL.md). It inspects your workspace and preserves local conventions before installing selected components.

- [Complete memory setup](docs/SETUP.md): fresh synthetic walkthrough, Codex configuration and optional imports.
- [Upgrade an existing instance](docs/UPGRADING.md): inspection, migration, machine handover and rollback.
- [Validation](docs/VALIDATION.md): executable checks for provenance, recovery, stale writes and bounded learning, with their limits.
- [Model-selection evidence](examples/model-screen/README.md): a recorded eight-case synthetic screen and its limits.
- [Storage and runtime contract](docs/MEMORY-RUNTIME.md).

Glide provides no hosted service or telemetry. Your harness, model provider, connectors and synchronization choices determine data exposure. See [privacy](docs/PRIVACY.md).

For a personal vault, see [Glide for Obsidian](https://github.com/DiogoNeves/glide-obsidian). [Contributions](CONTRIBUTING.md) are welcome.
