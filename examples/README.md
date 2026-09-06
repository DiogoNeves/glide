# Examples

Short examples of Glide workflows.

## Daily Founder Check-In

The agent reads `Company Context.md`, `Founder Brief.md`, area reminders, questions, open decisions, and `Follow-Through Ledger.md`, then surfaces one useful question, risk, opportunity, or small action. It only adds a second or third item when each one is urgent or very important.

## GTM Review

The agent checks GTM context, customers, sales signal, active experiments, contradictions, and research, then identifies the most important bottleneck or missing evidence.

## Investor Update Draft

The agent reads company context, metrics notes, decision log, and recent follow-through, then drafts an investor update for human review. It does not send it.

## Versioned Memory

- [Synthetic behavior cases](memory-evaluation-cases.json): observable assertions for provenance, coaching, recovery and controlled improvement.
- [Private installation-manifest shape](install-manifest.example.json): fill measured versions and hashes locally during an explicit upgrade.

## Portable memory examples

Start with [the setup walkthrough](../docs/SETUP.md), then [validation](../docs/VALIDATION.md). Behavior specifications in `memory-evaluation-cases.json` are synthetic cases, not a record that a model passed. The shared runtime's [model screen](https://github.com/DiogoNeves/glide/tree/main/examples/model-screen) includes actual synthetic results and an explicit opt-in runner; use the matching local checkout for unpublished builds.
