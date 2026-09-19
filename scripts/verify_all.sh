#!/usr/bin/env bash
set -euo pipefail

cd agents/job-scout
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q --cov=hermes_job_scout --cov-report=term-missing --cov-fail-under=90
cd ../..
release_dir="$(mktemp -d)"
python3 scripts/build_release.py . "$release_dir/artifact"
python3 scripts/verify_public_boundary.py "$release_dir/artifact" --manifest release-manifest.json
git diff --check
