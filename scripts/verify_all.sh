#!/usr/bin/env bash
set -euo pipefail
python3 -B scripts/verify_video.py
git diff --check
