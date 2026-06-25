# Glide

Glide is a Markdown operating system for founders and CEOs.

It gives an AI agent a durable home for company context, founder preferences, strategic decisions, open questions, research, follow-through, and operating cadence. The point is simple: stop repeating context, make better company decisions, and keep important threads moving without turning the business into more admin.

Glide is not an app or SaaS. It is a public set of Markdown templates, skills, checklists, and automation prompts that works with Codex, Claude Code, or another agent harness. Your harness is the execution layer; Glide defines the operating behavior.

## Why Glide Exists

Founders carry too much in their heads: product direction, customer signal, investor context, hiring constraints, GTM bets, awkward unresolved decisions, and promises made in passing.

Glide turns that into an agent-readable company operating layer. The agent can read, research, synthesize, challenge, draft, and maintain context over time. It can fetch information when access is configured, but it should ask before posting, sending, changing, purchasing, scheduling, approving, or making commitments.

## A Small Example

A founder asks: "Are we avoiding the real GTM problem?"

Glide loads the company context, GTM area, customer notes, active goals, decision log, contradictions, and follow-through ledger. It gives a direct read, names the missing evidence, suggests the next customer or metric check, and updates the right Markdown files as the conversation progresses.

## How It Works

- `Glide HQ/` is the agent-owned company operating workspace.
- `Company Context.md` captures product, market, customers, business model, metrics, strategy, risks, and open questions.
- `Founder Brief.md` captures leadership style, risk appetite, working preferences, and approval boundaries.
- Areas cover Strategy, Customers, Product, GTM, Sales, Marketing, Finance, Fundraising, Hiring, Operations, and Board & Investors.
- Skills and checklists encode repeatable founder/CEO workflows.
- Automations are optional prompts for daily, weekly, follow-through, drift, quiet 4am research, and release-update reviews.
- Connectors are discovered from the user's harness during setup; Glide records what is actually available and how it may be used safely.

Glide keeps its internal memory and working structure in `Glide HQ/`. It can read company docs, repos, tools, and external sources when allowed, but it should not modify external systems without explicit approval.

## Included

- `templates/Glide HQ/`: installable company operating workspace.
- `skills/`: portable Agent Skills prefixed with `glide-`.
- `automations/`: starter automation prompts.
- `adapters/`: Codex, Claude Code, and generic harness snippets.
- `docs/`: concept, privacy, harness, and release checks.
- `examples/`: short examples for common founder workflows.

## Install

Open the target Markdown workspace or company repo in your agent harness, then ask the harness to follow [INSTALL.md](INSTALL.md).

The installer should inspect before writing, ask which harness to use, draft company context from existing materials when possible, then ask focused questions to correct and fill gaps.

## Privacy

Glide itself does not collect telemetry, run servers, transmit data, or store user data anywhere. It is Markdown structure and instructions.

Privacy depends on the selected harness, model provider, connectors, sync, Git hosting, and automation setup. Review those policies before giving tools access to sensitive company data.

See [docs/PRIVACY.md](docs/PRIVACY.md).

## Inspiration

Glide's company-context-first pattern is inspired by [Marketing Skills](https://github.com/coreyhaines31/marketingskills), especially the idea that one canonical context document should feed many specialized skills. Glide applies that pattern to broader founder/CEO operating work.

## Contributing

Suggestions are welcome: sharper founder workflows, better checklists, new skills, safer connector patterns, and examples from real startup operating work.

See [CONTRIBUTING.md](CONTRIBUTING.md).
