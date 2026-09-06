# Founder Drift Review

Purpose: keep Glide operations aligned with `Harness Design Principles.md`.

## Load

- `Harness Design Principles.md`
- `AGENTS.md`
- `Operating Manual.md`
- `Communication Preferences.md`
- `Automation Registry.md`
- `Skills Index.md`
- `Checklists/Eval Loop.md`
- `Checklists/*.md`
- `Evals/*.md` if present, read-only
- installed `glide-*` skills

## Review

1. Compare operational files against the design principles.
2. Follow `Checklists/Eval Loop.md` when interpreting eval signal.
3. Read evals only as evidence. Recurring facets, signal clusters, `Improve Next` notes, and `Partial` outcomes are candidates for small instruction updates.
4. If repeated facets explain a pattern, add or update `Evals/Signal Clusters.md` before changing instructions.
5. Fix only clear non-behavioral issues directly.
6. Reduce verbosity in newly edited instructions when clarity and behavior stay intact.
7. Ask before behavior-changing edits outside the explicitly opted-in learned-overlay policy in `Memory Protocol.md`.
8. Do not edit company memory files except for clearly stale collection-candidate cleanup.

## Output

- Drift found or not found.
- Files changed.
- Eval clusters created or updated.
- Verbosity reductions.
- Approval-needed recommendations.

## Versioned Memory Integration

When versioned memory is enabled, use `glide-integrity` for its store and learned overlays. The opt-in applies only to tested eligible overlays; it does not authorize rewriting core instructions or protected principles. Propose stale managed-record cleanup through the runtime with preserved history rather than directly deleting or clearing it. Existing non-behavioral instruction repairs retain their current scope.
