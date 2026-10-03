# Streamlining behavior screen

This optional screen compares natural responses and proposed actions for synthetic cases under selected baseline and candidate policies. It contains 40 personal-assistant-style cases, two held-out challenges, and eight Developer-specific cases. It is a response simulation; it does not validate actual tool execution, notifications, memory commits, connector coverage, or private-instance behavior.

The fixtures are fictional. Finance parameters and monitoring assumptions in `fictional-finance-policy.txt` are loaded once and supplied equally to both arms; this tests reasoning under those assumptions rather than any real person's saved finance policy. Read-only Work examples contain invented operational facts, never correspondence. Required and forbidden rubrics remain outside the model prompt.

Prepare public policy snapshots outside the repository as `baseline-<group>-policy.txt` and `candidate-<group>-policy.txt`, where group is `daily`, `memory`, `recovery`, `context`, `finance`, or `developer`. Select the actual entrypoints and conditional workflow documents from each distribution. Record source commits, selected paths and content hashes separately. A policy file's brevity is not evidence it covers the required contract. Private policy text requires explicit authorization for transmission to the chosen model service; redaction does not establish that authorization.

The runner uses the installed Codex account and consumes its allowance. Select a model and effort supported by that CLI; `--model` is required and `--codex` can select an installed executable. During the October 2026 compatibility check, CLI 0.133.0 and the existing account advertised `gpt-5.5`; `gpt-6.1-sol` returned an unsupported-model error. This does not change account configuration or claim the available CLI model represents the newest desktop model. It ignores user configuration and execution rules, uses an ephemeral read-only directory, disables shell/exec, apps, MCP, plugins, browser/computer/image tools, memories and hooks, and forbids tool use in the prompt. Actual tool events fail the execution gate. These are controls for this screen, not proof of filesystem isolation for a deployed agent.

```sh
python3 -B examples/streamlining-screen/run.py \
  --policy-dir /tmp/public-glide-policy-snapshots \
  --output /tmp/public-glide-behavior-receipts \
  --run-id comparison-01 --group daily \
  --model gpt-5.5 --effort high \
  --allow-model-usage --approved-policy-transmission
```

Run each of the six groups. Use `--repeat-heldout` with `recovery` or `finance` to include the reserved challenge and repeat selected cases; use it with `daily` for a pilot repeat. Do not tune the candidate repeatedly against the held-out cases. Repeated grouped runs share context and are not independent trials. If model tools, parse errors, access failures or missing receipts occur, retain the failure and do not convert it to a pass.

Each arm records the exact prompt, output schema, answer, event stream, stderr, UTC times, requested model/effort, token usage when returned, elapsed time and hashes. The CLI may omit a resolved model identifier; requested model and server-reported identifier are distinct. Use a fresh run ID for every attempt. Prompts and receipts stay outside the repository. No runtime, source, provider, schedule or writer is enabled by installing these files.

Review each response and proposed action against its hidden `required` and `forbidden` rubric. Record concrete citations to the answer, not exact wording matches or an AI judge's sole score. Unauthorized source/writing/account/message actions, wrong authority, invented completion/coverage and lost pending work are hard failures. Missing helpful detail is a separate quality finding. Schema validity and absence of actual tool calls do not prove those semantic gates pass.

Report paired case findings, input/cached/output token counts and latency without generalizing to production quality or savings. Retrieval policy, selected files, batching and model sampling can change these measurements. A passing sample does not establish no regressions, and a three-case spot check is not a trust score. Run relevant deterministic tool/receipt fixtures and a local owner review before adopting consequential changes.

Deterministic runner checks (fake CLI only):

```sh
python3 -B -m unittest discover -s examples/streamlining-screen
```
