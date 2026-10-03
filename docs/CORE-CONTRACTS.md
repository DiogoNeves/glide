# Common policy ownership

Glide owns `contracts/memory-core.md` and `contracts/recovery-core.md`. These concise contracts are shared by the founder, Obsidian and optional Developer memory profiles. Domain permissions, source maps, communication preferences and legacy exceptions remain local or in the domain profile.

Generate the necessary distribution copies deterministically:

```sh
python3 -B tools/distribute_contracts.py --distribution glide --target /path/to/glide --write
python3 -B tools/distribute_contracts.py --distribution glide-obsidian --target /path/to/glide-obsidian --write
python3 -B tools/distribute_contracts.py --distribution glide-developer --target /path/to/glide-developer --write
```

Omit `--write` or use `--check` for a read-only comparison. Generated outputs name the canonical source and retain its hash plus a rendered-body hash. A local edit causes regeneration to stop rather than overwrite it. Keep custom domain or instance additions outside generated files and merge them explicitly.

The short Memory Protocol routes ordinary work to the shared contract, with the preceding full protocol retained under `Reference/` for optional features and recovery. A generated contract file does not enable versioned memory, migrate a Developer profile, change schedules, grant source access or activate a writer.

`python3 -B tools/check_distribution.py` checks owner generated copies, the example installation manifest and active expected-build commands against the consuming compatibility pin. Use `--root /path/to/glide-obsidian` for the consumer. The Developer profile has no runtime pin; check its generated copies with the renderer.

Runtime package content pins remain separate from prose ownership. Update the exact owner package manifest and consuming pins together after code changes, retaining the preceding package for rollback. These static checks do not establish behavioral quality or prove hosted CI ran.

## Conditional owner entrypoints

The founder/CEO template keeps authority, company context and judgment in its compact HQ instructions. The operating manual selects all eleven existing workflow routes; memory protocol and source-app details load only when that capability is in use. The original instructions, manual, preferences, memory protocol and recovery checklist remain byte-preserved under `templates/Glide HQ/Reference/`. These are historical detail, not a second always-loaded policy. Skill names, protected principles and Markdown-first defaults remain unchanged; enabling memory or learned overlays is still explicit.

Repository checks protect the original reference bytes, protected principles, skill names and active route destinations. They establish structural compatibility, not future model compliance.
