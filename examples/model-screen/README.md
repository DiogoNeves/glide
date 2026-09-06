# A small model screen

These [eight synthetic cases](prompt.txt) were run once per model/effort setting on September 6, 2026. The [recorded results](results-2026-09-06.json) contain measured decisions, required-evidence checks, usage and elapsed time. They contain no private vault inputs, raw session events or stderr.

| Tested configuration | Expected decision and required evidence |
| --- | --- |
| Terra xhigh | 8/8 |
| Terra high | 8/8 |
| Astra high | 8/8 |
| Sol high | 8/8 |

The screen supplies answer choices, making the intended distinction easier to infer. It checks basic classification around ideas, commitments, provenance, dated context and failed scans. It does not test unaided coaching, rich retrieval, tool reliability or long-term usefulness. One run cannot rank models, establish equivalent quality, or justify a cost claim.

The original harness contributed roughly 13–14 thousand input tokens despite the short prompt. Ambient instructions and model-specific system context therefore affect timings and usage. The JSON retains those measurements for inspection; they are not transferable benchmarks or current pricing estimates.

A provisional allocation is Terra high for routine reconciliation, Astra high for coaching/dreaming and Sol high for integrity review. This is a starting hypothesis, not a measured winner for those roles. Choose models available in the existing account/provider, run representative cases, and collect real review feedback before changing production jobs. Installation does not change models or billing.

## Repeat deliberately

`run.py` requires explicit model-usage opt-in and an output directory outside this repository. Select the current compatible Codex binary; the desktop-bundled and PATH binaries may differ. The command calls the chosen model once by default and can consume account usage. It does not run in CI.

```sh
python3 examples/model-screen/run.py \
  --model gpt-5.6-terra --effort high --allow-model-usage \
  --codex /absolute/path/to/codex --output /absolute/private/model-screen-run
```

Use `--repeat` for a bounded repeat count, or run a different available model explicitly. Results are matched by exact case ID; missing, duplicate, unexpected or extra cases fail. The runner stores a bounded result summary and usage, discarding raw event streams that can contain ambient information. Inspect the prompt and schema before running.

The current runner corrects the original evaluator's positional comparison: it verifies the exact set of eight unique IDs and evidence IDs. This is a reproduction harness revision, not a claim that the historical runs were repeated. `test_run.py` verifies the evaluator with synthetic responses and a fake local command without calling a model.

For stronger evaluation, write independent questions without supplied options, freeze regression and held-out material separately, and examine supported conclusions plus actual tool traces. Keep private inputs/results out of this public package. See [validation](../../docs/VALIDATION.md).
