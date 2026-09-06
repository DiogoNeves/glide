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
