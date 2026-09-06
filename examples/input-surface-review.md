# Input boundary scenario review — 6 September 2026

An independent Codex sub-agent read only the canonical checklist and six synthetic input cases, without an answer key or the implementation author's hypothesis. It described the next behavior, destination, permitted writes and application status for each case. This was a reading-based reasoning check: no notes, notifications or runtime decisions were executed, and it is not a model benchmark or a production acceptance test.

| Case | Observed proposed behavior |
| --- | --- |
| routine-start | Bring the due proposal and its evidence into conversation; retain lower-priority questions internally. No owner note or presumed approval. |
| joint-draft | Use the authorized normal writing area and Draft section with visible attribution; preserve owner edits. Use conversation if the scoped writer is unavailable. Drafting does not authorize sending. |
| checkbox | Treat the unbound checkbox as input, identify the intended proposal, and reconcile stale revisions before application. No receipt is inferred. |
| candidate-backlog | Surface the current question in chat; retain the historical internal drafts rather than exporting them. |
| label-scope | Add only the requested paragraph through a scoped capability; preserve owner reflections and avoid silently replacing a remembered preference. |
| delivery-gap | Keep a failed delivery and unanswered question pending; use an authorized fallback or available conversation. Saving internal content does not establish delivery. |

The evaluator identified an underspecified delivery-failure path. The canonical checklist was clarified to separate preparation from delivery, retain pending input, restrict fallback channels and avoid indefinite retries. A follow-up independent reading confirmed that clarification addressed the gap. Priority selection, evidence interpretation and revision handling remain delegated to their existing procedures rather than repeated here.

The next real request for input still needs observation in each installed harness. Structural skill and link checks establish format and reachability, not future adherence or successful delivery.
