# Hermes Agent Workforce

This is a **Stage 2 dry-run prototype** for local-first, privacy-preserving agent
packages. The current package is `agents/job-scout`.

Architecture: sanitized policy context → public reusable code → private local state →
future isolated Hermes execution. The implemented synthetic pipeline normalizes,
deduplicates, filters, ranks, produces ATS-readable documents, and writes redacted reports.
Submission is mock-only and exact-approval gated.

Run `./scripts/verify_all.sh` or, inside `agents/job-scout`, `./scripts/verify.sh`.
Run the synthetic demo with `uv run job-scout run-fixtures --fixtures
tests/fixtures/jobs --db /tmp/job-scout.sqlite --report /tmp/job-scout.json`.

Not implemented: real discovery, Hermes integration, Telegram, scheduler, live submitter,
VPS, LinkedIn automation, income result, or ATS guarantee. No push or publication is
performed by the build scripts.
