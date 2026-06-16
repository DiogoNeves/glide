# Connector Registry

Glide assumes the user's harness may already have connectors.

Use this file to record connector categories, not secrets.

## Safe Default

- Reading and fetching information is allowed when the user has granted connector access.
- External-state changes require explicit approval.
- Draft first for high-stakes or public-facing actions.

## Common Categories

| Category | Examples | Typical Use | Write Boundary |
| --- | --- | --- | --- |
| Email | Gmail, Outlook | find action items, draft replies, summarize newsletters | ask before send, archive, delete, unsubscribe |
| Calendar | Google Calendar, Apple Calendar | schedule context, conflict checks, prep | ask before create, move, RSVP, invite |
| CRM | HubSpot, Salesforce, Close | pipeline review, customer context | ask before record changes |
| Analytics | GA4, PostHog, Mixpanel, Amplitude | metric review, funnel diagnosis | ask before tracking/config changes |
| Payments | Stripe, Paddle | revenue and billing context | ask before refunds, pricing, customer changes |
| Project Tools | Linear, Jira, GitHub | execution context and follow-through | ask before issue changes unless explicitly approved |
| Docs | Google Drive, Notion, Slack | context retrieval and synthesis | ask before publishing or editing shared docs |
