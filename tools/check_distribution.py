#!/usr/bin/env python3
"""Read-only checks for generated contracts and active distribution build references."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from distribute_contracts import check


def verify(root):
    root = Path(root)
    compatibility = json.loads((root / "compatibility.json").read_text())
    pin = compatibility["optional_memory_runtime"]
    example = json.loads((root / "examples/install-manifest.example.json").read_text())["runtime"]
    if (example["version"], example["build"]) != (pin["version"], pin["build"]):
        raise ValueError("Synthetic installation example differs from the consuming runtime pin")
    for relative in ("INSTALL.md", "docs/SETUP.md", "docs/COMPATIBILITY.md", "docs/UPGRADING.md", "docs/MEMORY-RUNTIME.md"):
        for build in re.findall(r"--expected-build ([a-f0-9]{12})", (root / relative).read_text()):
            if build != pin["build"]:
                raise ValueError("Stale expected-build command in " + relative)
    companion = root / "daily_notes/package-manifest.json"
    if companion.exists():
        required = json.loads(companion.read_text())["required_runtime_build"]
        init = (root / "daily_notes/glide_obsidian/__init__.py").read_text()
        constant = re.search(r'^REQUIRED_RUNTIME_BUILD = "([a-f0-9]{12})"$', init, re.MULTILINE)
        if required != pin["build"] or constant is None or constant.group(1) != pin["build"]:
            raise ValueError("Companion runtime pairing differs from the consuming runtime pin")
    generated = check(root, compatibility["distribution"])
    if not generated["ok"]:
        raise ValueError("Generated contract copies differ: " + json.dumps(generated))
    return {"ok": True, "distribution": compatibility["distribution"], "build": pin["build"], "generated_contracts": 2}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.root), indent=2))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, str(error) + "\n")
