# Changelog

Notable changes to Glide.

## 2026-07-09

### Added WhatsApp macOS Access Guide

- Added optional software guidance for safe read-only WhatsApp Desktop access on macOS.
- Documented approval boundaries for opening chats, sending messages, changing read state, and storing transcripts.

### Added Lightweight Eval Loop

- Added Markdown-native eval-loop templates for run logs, signal clusters, eval cases, and the standard eval-loop checklist.
- Updated daily check-ins, nightly research review, drift review, and update checks to use run-log facets, `keep`/`tune`/`case` decisions, signal clusters, and approval-gated instruction changes.
- Migration guidance: existing workspaces should add missing eval files if absent, preserve local `Run Log.md`, `Eval Cases.md`, `Signal Clusters.md`, `Nightly Research Audit.md`, and audit history, and add new run-log columns without overwriting existing rows.
- Installed skills and checklists may be updated, but behavior-changing local customizations require approval.
- This release adds no telemetry, external storage, automated scoring, model-judge infrastructure, or new enabled automations.

## 2026-07-07

### Clarified Evolution Guidance

- Updated installation guidance to invite users to adjust Glide's operating style and expand automations gradually as confidence grows.

## 2026-06-25

### Added Weekly Glide Update Checks

- Added `glide-check-for-updates`, `Glide HQ/Glide Updates.md`, a weekly update-check automation prompt, and harness adapter prompts.
- Added update-state and migration guidance so installed workspaces can track the last seen upstream release and preserve local instructions.

### Added Nightly Founder Research Review

- Added a quiet 4am research and memory maintenance skill, checklist, automation prompt, and rolling 4-day audit.
- Included the schedule in Codex, Claude Code, and generic automation adapters.

## 2026-06-20

### Capped Daily Founder Output

- Updated daily founder check-ins to prefer one item, allow up to three only when each is urgent or very important, and ask before continuing when more may matter.
- Added daily ranking and source-arbitration rules for competing signals.
- Added evals as read-only drift-review evidence when present.

## 2026-06-16

### Added First-Week Daily Calibration

- Updated daily founder check-ins to ask occasional lightweight calibration questions during the first week of usage.
- Added guidance to capture durable preferences about signal, noise, timing, tone, length, context, and action level.

### Switched To Install-Time Connector Inventory

- Replaced the static connector registry with `Glide HQ/Connector Inventory.md`.
- Updated installer guidance to inspect the harness's actual connected tools during setup.
- Kept the approval boundary: read/fetch when access is granted; ask before external changes.

### Added Git Hygiene To Installation

- Updated installation to initialize git when the workspace has no repository.
- Added root instruction guidance to keep meaningful Glide content and harness updates committed with very brief commit messages.
- Clarified not to commit secrets, raw exports, transcripts, or connector dumps.

### Initial Founder/CEO Version

- Created Glide as a Markdown-first founder/CEO operating system.
- Added installable `Glide HQ/` templates.
- Added company context, founder brief, follow-through ledger, decision log, questions, contradictions, research, and automation registry.
- Added default areas: Strategy, Customers, Product, GTM, Sales, Marketing, Finance, Fundraising, Hiring, Operations, and Board & Investors.
- Added starter skills and automations for company context, daily founder check-ins, weekly CEO reviews, follow-through, decisions, research, area reviews, contradictions, and drift review.
- Added Codex, Claude Code, and generic harness adapters.
