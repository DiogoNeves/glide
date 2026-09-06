# Validate a Glide installation

## Recorded local validation — 6 September 2026

Content build `df711b913f09` passed **139 runtime tests with no skips** on the tested macOS host, including the explicitly enabled Codex source-reader boundary check. Both fresh adapter installations passed the package/content-pin checks; the installed wheel rendered the review and imported its packaged helpers. The separate model-screen evaluator passed five synthetic tests without calling a model. These are local results, not a claim that hosted CI has run or every supported host is equivalent.

Recovery tests delete an independent disposable SQLite index and recover the same Markdown records, historical answers and review receipts. Paging regressions keep a large archive and long record bodies out of default job summaries while preserving exact revision references. The [eight-case model screen](../examples/model-screen/README.md) is limited evidence for provisional model roles, not a ranking of coaching quality.


Validation has three layers: deterministic data behavior, the actual harness/tool boundary, and whether coaching helps a person. A pass in one layer does not prove the others.

## Reproduce the runtime checks

From a supplied matching Glide checkout, with Python 3.11+ and SQLite FTS5:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=runtime python3 -m unittest discover -s runtime/tests -v
```

The tests cover exact evidence and source identity, revision history, stale and duplicate writes, interrupted publication, incomplete sync, local-index reconstruction, fixed MCP schemas, intake checkpoints, review rendering, installation/packaging and bounded learned overlays. Read [the tests](../runtime/tests) for the exercised inputs and assertions. A skip is not a pass: an earlier 100-test execution was 99 passed and one environment-dependent sandbox skip. Use the current run's actual totals when reporting a changed build.

Run the non-model package checks from the owner checkout:

```sh
python3 runtime/check_package.py --compatibility /absolute/path/to/glide-obsidian/compatibility.json
python3 runtime/check_wheel.py
python3 -m unittest discover -s examples/model-screen -p 'test_*.py' -v
```

The wheel check needs the packaging tools required by `runtime/pyproject.toml`; core pinned installation uses the standard library. Repository CI runs the checks configured in `.github/workflows/`; a CI file alone is not evidence that a hosted run passed. Consumer CI fetches the owner commit pinned in the Obsidian compatibility manifest, so publish that verified owner commit before depending on a remote consumer run. Model screens require separate explicit usage opt-in and are not CI jobs.

Run the [complete setup walkthrough](SETUP.md) for both `markdown` and `obsidian` adapters. Also validate package hashes against `runtime/package-manifest.json` and each distribution's `compatibility.json`. A matching hash establishes exact content, not semantic truth or a trusted publisher.

## Rebuild without SQLite

After the setup fixture has a source and accepted record, use only its disposable paths:

```sh
python3 - <<'PYTEST'
import json, os, shutil, tempfile
from pathlib import Path
from glide_memory import Store
original = Store.from_config(os.environ["GLIDE_CONFIG"])
root = Path(tempfile.mkdtemp(prefix="glide-rebuild-")).resolve()
copied_vault = root / "workspace"
shutil.copytree(original.vault, copied_vault)
reader = Store.initialize(copied_vault, root / "state", original.config["store_path"], original.adapter)
before = original.export()
assert reader.export() == before
assert not reader.config["writer_active"]
reader.db_path.unlink()  # only the independent disposable reader's index
reader.rebuild()
assert reader.export() == before
assert reader.history("demo:specimen") == original.history("demo:specimen")
assert reader.verify()["ok"]
print(json.dumps({"recovered": True, "reader_writer_active": False, "fixture": str(root)}))
PYTEST
```

Include historical queries, retained quotes and review receipts in real upgrade comparisons. Do not delete a production database to demonstrate recovery. A copied-store test does not establish that remote Sync transferred every file or that a second physical host is configured correctly.

## Verify the execution boundary

In a fresh task using the actual configured harness, test synthetic source reads and attempted direct/shell/symlink/hardlink writes. Check any installed alternate file or computer-control tools too. Require observable tool output and unchanged original bytes; an agent's statement that it was blocked is not enough. Test native permissions on the real host. The macOS runner tests establish only the tested process boundary, not universal protection across every app.

## Evaluate reasoning and coaching

The [behavior cases](../examples/memory-evaluation-cases.json) are specifications, not recorded model results. A separate [eight-case model screen](../examples/model-screen/README.md) has recorded synthetic results and a repeatable opt-in runner; it is a limited classification screen, not a coaching benchmark. Have an independent evaluator use realistic raw inputs without revealing the desired answer or change author's hypothesis. Check dated belief versus fact, preference versus weakened assumption, echo versus corroboration, intention versus commitment, and approval/delivery versus completion.

Record the tested model/effort, prompts, tool outputs, errors, usage and elapsed time with the tested build in private instance evidence. Public reports must use synthetic data. Do not claim that passing a small prompted screen proves one model is superior, equal cost, or reliable in long conversations. Use the existing provider unless a change is authorized.

Each weekly human review samples two uncertain cases and one ordinary case, including skipped material over time. Track unsupported claims, missed loops, useful resurfacing and review effort. A three-item sample is not a trust score. Real scheduled runs, mobile interaction, fresh live transcription and a physical-machine handover need their own observation.

## Review interaction

Text is the portable default. Interactive UI follows preview → submit → validate current revision → apply once → receipt. Local selection cannot prove persistence. Verify a real host follow-up through the writer; browser mocks alone are insufficient. A desktop conversation round-trip has been exercised during integration, but client versions and mobile surfaces still need their own check. Keep the same review available as text when a bridge is absent.

## Release evidence

Before publishing, run the current suite and both clean setup paths, check wheel contents include the HTML and helper modules, validate links and skills, and review staged files for private data. Record failures/skips and remaining field observations. CI checks reproducible code behavior; it should not silently invoke a paid model or external connector. Existing instances still need [upgrade inspection and rollback](UPGRADING.md).

## Conversation continuity

The separately distributed metadata inventory and its tests are byte-identical to the Obsidian edition’s 6 September 2026 implementation. This generic port passed **14 synthetic tests** locally on macOS; they cover resumed older tasks, missing/stale indexes, internal-origin filtering before pagination, header-only reads, symlinks, unreadable/partial inputs, changed files and paging drift. Reproduce them from this checkout:

```sh
python3 -B -m unittest discover -s tests -p test_conversation_inventory.py -v
```

The conversation-learning skill and changed daily/dream/drift entrypoints passed structural skill validation. Six synthetic scenario inputs are supplied in [conversation-learning-cases.json](../examples/conversation-learning-cases.json). They distinguish explicit steering, temporary context, unaccepted suggestions, late corrections, duplicate retries and inferred overgeneralization. These inputs are not a model benchmark or proof of future compliance. The original Obsidian procedure received an independent reading-based scenario review; this generic adaptation preserves its authority distinctions but needs observation in each installed harness.

No pinned core runtime files or schema changed, and the 139-test core result above is prior evidence, not a rerun for this documentation/helper port. Verify exact helper/test identity between the two checkouts using the [compatibility checks](CONVERSATION-LEARNING.md#jobs-verification-and-upgrades). Real history coverage is partial by source and page; inventory counts are not reviewed-message counts. Record actual capture/application receipts and later behavior before claiming successful continuing use.

## Input and collaboration boundary

[Input-surface scenarios](../examples/input-surface-cases.json) provide six synthetic prompts covering ordinary chat, a scoped joint draft, a stale checkbox, a backlog of internal drafts, later human edits and failed delivery. They are inputs for an independent behavioral review, not an executed runtime test or a model benchmark. Check whether the response delivers useful input in conversation, keeps HQ agent-maintained, preserves owner writing and requires an actual revision receipt before claiming application. Record any independent review and the first real request for input separately.

The current change is instructions and documentation only. The two changed skill entrypoints pass structural validation; that checks their format, not future compliance. The content-pinned runtime, source sandbox and protected design principles are unchanged, so prior runtime results are not being reported as a new test run.

A [recorded independent scenario review](../examples/input-surface-review.md) exercised the six prompts as reasoning cases and identified a delivery-failure gap that was clarified and reviewed again. No document edits, notifications or runtime decisions were executed by that evaluation. Observe the next real input request in the installed harness.

## Recovery configuration exports

The shared owner helper has eight synthetic tests for version preservation/idempotency, read-only inspection, pending backup status, changed/missing inputs, symlinks, traversal/duplicate names, credential/database tripwires and unexpected export files. Run `python3 -B -m unittest discover -s tests -p test_recovery_bundle.py -v` in the matching **glide** checkout. These checks do not prove backup service operation or restoration of a complete instance; follow [the recovery procedure](RECOVERY.md) in the actual harness.
