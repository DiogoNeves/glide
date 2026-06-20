---
name: glide-founder-drift-review
description: Review Glide operating files for drift against Harness Design Principles.md. Use for scheduled drift reviews, behavior audits, approval-boundary checks, and simplifying verbose instructions without changing behavior.
---

# Glide Founder Drift Review

## Load

- `Glide HQ/Harness Design Principles.md`
- `Glide HQ/Checklists/Founder Drift Review.md`
- Operational files listed in the checklist
- `Glide HQ/Evals/*.md` if present, as read-only evidence
- Installed `glide-*` skills

## Process

1. Treat `Harness Design Principles.md` as read-only unless the user explicitly asks to edit it.
2. Review operating files for drift.
3. Treat recurring `Improve Next` notes and `Partial` outcomes in evals as candidates for small instruction updates.
4. Fix only clear non-behavioral issues directly.
5. Reduce verbosity when clarity and behavior survive.
6. Ask before behavior-changing edits.
7. Preserve human-approval boundaries for external actions.

## Output

- Drift found or not found.
- Files changed.
- Verbosity reductions.
- Approval-needed recommendations.
