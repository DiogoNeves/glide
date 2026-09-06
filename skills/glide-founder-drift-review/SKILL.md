---
name: glide-founder-drift-review
description: Review Glide operating files for drift against Harness Design Principles.md. Use for scheduled drift reviews, behavior audits, approval-boundary checks, and simplifying verbose instructions without changing behavior.
---

# Glide Founder Drift Review

## Load

- `Glide HQ/Harness Design Principles.md`
- `Glide HQ/Checklists/Founder Drift Review.md`
- `Glide HQ/Checklists/Eval Loop.md`
- Operational files listed in the checklist
- `Glide HQ/Evals/*.md` if present, as read-only evidence
- Installed `glide-*` skills

## Process

1. Treat `Harness Design Principles.md` as read-only unless the user explicitly asks to edit it.
2. Review operating files for drift.
3. Interpret eval signal through `Glide HQ/Checklists/Eval Loop.md`.
4. Treat recurring facets, signal clusters, `Improve Next` notes, and `Partial` outcomes in evals as candidates for small instruction updates.
5. Add or update compact signal clusters before making eval-derived instruction changes.
6. Fix only clear non-behavioral issues directly.
7. Reduce verbosity when clarity and behavior survive.
8. Ask before behavior-changing edits outside the explicitly opted-in learned-overlay policy in `Memory Protocol.md`.
9. Preserve human-approval boundaries for external actions.

## Output

- Drift found or not found.
- Files changed.
- Eval clusters created or updated.
- Verbosity reductions.
- Approval-needed recommendations.

For an explicitly enabled memory store, delegate integrity and eligible learned-overlay evaluation to `glide-integrity` using `Glide HQ/Memory Protocol.md`. This exception does not authorize core-instruction changes. Managed record changes use the runtime and preserve revision history.
