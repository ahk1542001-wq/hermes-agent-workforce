#!/usr/bin/env python3
"""Build a public artifact from the exact release allowlist."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path, PurePosixPath

REQUIRED = {
    "README.md",
    "SECURITY.md",
    "LICENSE",
    "release-manifest.json",
    "docs/ARCHITECTURE.md",
    "docs/PERMISSION_MODEL.md",
    "docs/ATTRIBUTION.md",
    "docs/DATA_BOUNDARIES.md",
    "docs/UPSTREAM_REVIEW.md",
}


def _load_manifest(root: Path) -> list[str]:
    payload = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
    entries = payload.get("files")
    if not isinstance(entries, list) or any(not isinstance(item, str) for item in entries):
        raise ValueError("release manifest files must be a string list")
    if len(entries) != len(set(entries)):
        raise ValueError("release manifest contains duplicate entries")
    for entry in entries:
        path = PurePosixPath(entry)
        if path.is_absolute() or not entry or ".." in path.parts or "." in path.parts:
            raise ValueError("release manifest contains an unsafe path")
    if not REQUIRED.issubset(entries):
        raise ValueError("release manifest omits a required public file")
    return entries


def build_release(root: Path, output: Path) -> None:
    root = root.absolute()
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("release output must be a new path")
    entries = _load_manifest(root)
    output.mkdir(parents=True, mode=0o700)
    for entry in entries:
        source = root / entry
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"release entry is missing or not a regular file: {entry}")
        destination = output / entry
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination, follow_symlinks=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_release(args.root, args.output)
    print("release artifact built")


if __name__ == "__main__":
    main()
