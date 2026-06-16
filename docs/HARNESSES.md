# Harnesses

Glide works through an agent harness. The harness reads the Markdown workspace, runs skills, and may provide connectors.

## Codex

- root instructions: `AGENTS.md`
- skills: `.agents/skills/<skill-name>/SKILL.md`
- workspace: `Glide HQ/`

## Claude Code

- root instructions: `CLAUDE.md`
- skills: `.claude/skills/<skill-name>/SKILL.md`
- workspace: `Glide HQ/`

## Other Harnesses

Use the generic adapter. The user should identify:

- the root instruction file,
- the skill directory,
- whether recurring automations are supported,
- which connectors are configured.
