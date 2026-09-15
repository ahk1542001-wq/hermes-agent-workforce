#!/usr/bin/env bash
set -euo pipefail

cd agents/job-scout
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q --cov=hermes_job_scout --cov-report=term-missing --cov-fail-under=90
cd ../..
git diff --check
