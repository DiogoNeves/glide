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

With authorized conversation recovery, follow [Conversation Learning](Conversation%20Learning.md) for captured feedback versus observed behavior, temporary scope and inactive candidates. Clear scoped guidance already given by the owner does not need repeated permission; inferred procedural changes retain the existing review requirements. Record checks actually performed and leave untested effects pending.

Follow [Input and Collaboration](Input%20and%20Collaboration.md) to check whether questions were delivered with enough context in conversation, internal queues became owner homework, or shared documents exceeded their edit scope. Keep findings and receipts internal; surface only the useful decision or correction.

Follow `Recovery.md` for configuration drift, approved local export refresh and backup/restore evidence. Respect recorded deferrals and bring material gaps into conversation.
