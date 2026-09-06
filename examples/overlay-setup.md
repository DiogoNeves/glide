# Try a learned retrieval overlay

Use only the disposable instance from [the setup walkthrough](../docs/SETUP.md), containing `demo:specimen`. This is a mechanics fixture with an obvious synonym, not a held-out assessment of coaching quality. Production evaluation needs fresh cases unavailable to the change author.

The script enables learning **only in that fixture**, freezes two cases outside its workspace, evaluates a typed alias, applies it, verifies the result and rolls it back. The week's candidate budget remains used after rollback.

```sh
python3 - <<'PYTEST'
import hashlib, json, os
from pathlib import Path
from glide_memory import Store, overlays
store = Store.from_config(os.environ["GLIDE_CONFIG"])
assert store.state_dir.name == "demo", "Use the isolated setup fixture"
record = store.get("demo:specimen")
cases = {"schema": 1, "cases": [
    {"id": "known-query", "split": "regression", "query": "specimen", "expected_ids": ["demo:specimen"]},
    {"id": "different-vocabulary", "split": "heldout", "query": "sample inventory", "expected_ids": ["demo:specimen"]}
]}
case_file = store.state_dir / "frozen-cases.json"
case_file.write_text(json.dumps(cases, indent=2) + "\n")
store.config["learned_overlays"] = {"enabled": True, "cases_path": str(case_file), "cases_sha256": hashlib.sha256(case_file.read_bytes()).hexdigest()}
store._save_config()  # deliberate fixture setup, not a model-facing tool
change = {"retrieval_aliases": {"sample inventory": ["specimen"]}}
report = overlays.evaluate(store, change)
assert report["accepted"]
receipt = overlays.activate(store, change, evidence=record["sources"], rationale="A synthetic vocabulary miss motivates this fixture alias", idempotency_key="demo-overlay")
assert receipt["committed"]
assert "demo:specimen" in [r["id"] for r in store.search("sample inventory", include_sources=False)]
rollback = overlays.rollback(store, evidence=record["sources"], rationale="Finish the synthetic demonstration", idempotency_key="demo-overlay-rollback")
assert rollback["committed"]
print(json.dumps({"evaluation": report, "activation": receipt, "rollback": rollback}, indent=2))
PYTEST
```

Do not enable production learning merely because this example passes. Keep motivating evidence, regressions, held-out cases and rollback; allow only the runtime's typed retrieval/context changes. Permissions, goals, schedules, providers, completion rules and evaluation criteria remain outside automatic changes.
