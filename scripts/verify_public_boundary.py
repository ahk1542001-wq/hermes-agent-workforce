#!/usr/bin/env python3
"""Scan an allowlisted public artifact without printing matched sensitive values."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_SIZE = 1024 * 1024
FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".doc",
    ".docx",
    ".pdf",
    ".pem",
    ".key",
    ".p12",
}
_PRIVATE_PATH = re.compile(
    r"/" + r"(?:Users|home)/[A-Za-z0-9._-]+/(?:Documents/)?(?:Private|Second Brain)"
)
_HOME_PATH = re.compile(r"/" + r"(?:Users|home)/[A-Za-z0-9._-]+/")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_CREDENTIAL = re.compile(
    r"(?i)\b(?:api[_-]?" + r"key|access[_-]?token|password|secret)\s*[:=]\s*\S+"
)
_PRIVATE_POINTER = re.compile(r"(?i)private[_-]?" + r"workspace\s*[:=]")


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    message: str


def _finding(path: Path, root: Path, rule: str) -> Finding:
    relative = path.relative_to(root).as_posix()
    return Finding(relative, rule, f"{relative}: blocked by {rule}")


def scan_tree(root: Path, expected_files: set[str] | None = None) -> list[Finding]:
    root = root.absolute()
    findings: list[Finding] = []
    paths = sorted(root.rglob("*"))
    actual_files: set[str] = set()
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            findings.append(_finding(path, root, "symlink"))
            continue
        if not path.is_file():
            continue
        actual_files.add(relative)
        if expected_files is not None and relative not in expected_files:
            findings.append(_finding(path, root, "unexpected_file"))
        if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            findings.append(_finding(path, root, "forbidden_extension"))
        if path.stat().st_size > MAX_FILE_SIZE:
            findings.append(_finding(path, root, "oversized_file"))
            continue
        raw = path.read_bytes()
        if b"\x00" in raw:
            findings.append(_finding(path, root, "binary_file"))
            continue
        text = raw.decode("utf-8", errors="replace")
        if _PRIVATE_PATH.search(text) or _HOME_PATH.search(text):
            findings.append(_finding(path, root, "private_path"))
        if _CREDENTIAL.search(text):
            findings.append(_finding(path, root, "credential_like"))
        if _PRIVATE_POINTER.search(text):
            findings.append(_finding(path, root, "private_workspace_pointer"))
        if any(domain.casefold() != "example.com" for domain in _EMAIL.findall(text)):
            findings.append(_finding(path, root, "personal_contact"))
        if any(part in {"examples", "fixtures"} for part in path.parts) and not any(
            marker in text.casefold() for marker in ("synthetic", "example")
        ):
            findings.append(_finding(path, root, "non_synthetic_artifact"))
    if expected_files is not None:
        for missing in sorted(expected_files - actual_files):
            findings.append(Finding(missing, "missing_file", f"{missing}: blocked by missing_file"))
    return findings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    expected: set[str] | None = None
    if args.manifest:
        import json

        expected = set(json.loads(args.manifest.read_text(encoding="utf-8"))["files"])
    findings = scan_tree(args.root, expected)
    if findings:
        for finding in findings:
            print(finding.message)
        raise SystemExit(1)
    print("public boundary: clean")


if __name__ == "__main__":
    main()
