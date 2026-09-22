# Hermes Agent Workforce

This is a **Stage 3 local, network-free pilot** for privacy-preserving agent packages.
The current package is `agents/job-scout`.

Architecture: sanitized policy context → public reusable code → private local state →
future isolated Hermes execution. The implemented pipeline imports synthetic fixtures or
local feed snapshots, normalizes and deduplicates listings, applies fail-closed policy,
stores revision-checked state, ranks evidence, produces ATS-readable documents, and writes
redacted reports. Submission remains mock-only and exact-approval gated.

Run `./scripts/verify_all.sh` or, inside `agents/job-scout`, `./scripts/verify.sh`.
Run the synthetic demo with `uv run job-scout run-fixtures --fixtures
tests/fixtures/jobs --db /tmp/job-scout.sqlite --report /tmp/job-scout.json`.
Inspect the Stage 3 local feed-snapshot pilot with
`uv run job-scout pilot-feed-discovery --help`.

Not implemented: network discovery, Hermes runtime integration, Telegram, scheduler, live
submitter, VPS, LinkedIn automation, income result, or ATS guarantee. No push or publication
is performed by the build scripts.
