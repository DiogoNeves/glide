---
name: glide-daily-founder-check-in
description: Run a concise daily founder/CEO check-in. Use for morning operating reviews, daily automations, checking company priorities, surfacing one risk/opportunity/question, reviewing follow-through, or scanning configured connectors for important business signal.
---

# Glide Daily Founder Check-In

## Load

- `Glide HQ/AGENTS.md`
- `Glide HQ/Company Context.md`
- `Glide HQ/Founder Brief.md`
- `Glide HQ/Connector Inventory.md`
- `Glide HQ/Checklists/Daily Founder Check-In.md`
- `Glide HQ/Follow-Through Ledger.md`
- `Glide HQ/Decision Log.md`
- `Glide HQ/Questions Queue.md`
- `Glide HQ/Contradiction Register.md`
- `Glide HQ/Checklists/Eval Loop.md`
- `Glide HQ/Evals/Run Log.md`
- `Glide HQ/Evals/Signal Clusters.md`
- `Glide HQ/Evals/Eval Cases.md`
- Relevant area files
- Configured connectors when safe and useful

## Process

1. Run `$glide-update-company-context` when recent durable signal should shape the check-in.
2. Scan priorities, follow-through, decisions, questions, contradictions, and relevant area files.
3. Fetch from configured connectors only when it may reveal important signal.
4. Choose the smallest useful output: prefer one item; use two or three only when each is genuinely urgent or very important.
5. When signals compete, rank candidates by concrete deadline, date, amount, company or founder stakes, source reliability, and whether the founder can usefully act today.
6. When email, calendar, Things, Messages, CRM, or app data disagree, prefer the source of record, confirmation email, or official app over auto-created calendar or task artifacts, and mention the caveat briefly.
7. During the first week of usage, occasionally ask one light calibration question about the daily update's signal, noise, timing, tone, length, missing context, or preferred action level.
8. Draft external actions only for approval.
9. Update Glide HQ as the conversation progresses, including durable calibration preferences.
10. After a useful run, follow `Glide HQ/Checklists/Eval Loop.md` and append a light entry to `Glide HQ/Evals/Run Log.md` with facets and an eval decision of `keep`, `tune`, or `case`.
11. Promote an eval case only for important failures, near-misses, repeated patterns, or unusually good behavior worth preserving.
12. Add or update `Glide HQ/Evals/Signal Clusters.md` only when repeated facets suggest a reusable process or instruction change.

## Output

- One concise question, risk, opportunity, contradiction, or follow-through nudge by default.
- Two or three items only when each is genuinely urgent or very important.
- Never surface more than three items. If more than three may matter, say: `Hey, there are other things that might be important. Do you want me to continue?`
- A light calibration question during the first week when useful.
- A tiny run-log entry when useful, including facets and a `keep`, `tune`, or `case` decision.
- Optional Glide HQ updates after the user responds.
