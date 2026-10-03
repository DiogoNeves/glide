# Privacy

Glide is Markdown structure, templates, skills, and instructions.

Glide does not:

- run a server,
- collect telemetry,
- transmit data,
- provide a hosted service.

Privacy depends on the user's harness, model provider, connector configuration, sync provider, Git hosting, and automation setup.

## Connector Boundary

Connectors can expose sensitive company data. Reading and fetching may be allowed when the user has configured access. External changes require explicit approval.

Examples of approval-gated actions:

- sending email or messages,
- posting to social channels,
- changing CRM records,
- changing analytics or ad accounts,
- scheduling meetings,
- purchasing tools,
- changing billing,
- approving customer or investor communication.

## Public Repo Hygiene

This repository should not include private company data, real customer names, confidential metrics, credentials, or internal transcripts.

## Optional Local Memory Runtime

When enabled, the runtime stores a searchable SQLite index and private configuration outside the workspace/vault. The index can contain source text and metadata; treat it as sensitive local data even though it is rebuildable. The Markdown bundle store includes history and retained evidence, so its sync and backup destinations receive that content too. The runtime itself does not grant connector access, choose a cloud model or enable a hosted service. Public repositories contain only synthetic fixtures and generic setup instructions.

## Public file checks

Run the pinned owner helper `python3 -B tools/check_public_privacy.py` in the owner checkout, or add `--root /path/to/consumer` for a consumer. `--include-untracked` includes prospective working-tree files before staging; run `--staged` after staging to check the exact indexed bytes before committing. CI checks tracked files and invokes no models or connectors.

The checker derives the repository-owner handle locally, flags identifying file names and home paths, non-example email addresses, private-key headers, common token prefixes, credential-bearing URLs and common private artifacts, and prints only finding categories and locations. Reserved example addresses and explicit synthetic path placeholders remain permitted. Set `GLIDE_PUBLIC_PRIVACY_DENYLIST` or pass `--denylist` for a JSON array of additional private terms stored outside the repository; never commit that file. Binary files appear in a separate inventory for manual review; their content is not scanned, and the check fails when this inventory is nonempty. Unrecognized credential formats, contextual sensitivity and Git history still need human review. The check does not anonymize repository hosting, remotes, author metadata or historical commits.
