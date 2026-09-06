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
