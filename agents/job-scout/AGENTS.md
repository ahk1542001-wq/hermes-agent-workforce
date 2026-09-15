# Hermes Job Scout contributor guidance

## Source hierarchy

The approved design specification and repository tests define the intended
interfaces. This repository's implementation is authoritative for behavior;
generated artifacts and external handoffs are not source of truth.

## Public/private boundary

The repository is public-ready and local-only. Commit synthetic examples and
schemas only. Private documents, identity data, credentials, session artifacts,
and machine-specific paths belong outside this repository and must never be
copied into it.

## Safety and network rules

Tests must be deterministic and make no network, job-provider, model, or live
service calls. Submitters must use mocks or synthetic fixtures only. Never use
live credentials, personal data, real identity documents, or live external
actions in development, tests, or examples.

## Exact verification commands

Use `./scripts/verify.sh` for the complete local check. Task-scoped checks may
use `uv sync --all-groups && uv run pytest tests/test_public_boundary.py -q`.
Do not weaken pinned dependency constraints to work around installation issues.

## Prohibited actions

Do not discover jobs over the network, contact providers or models, publish,
deploy, push to a remote, send messages, or perform live submissions without
explicit approval and a separately reviewed implementation.
