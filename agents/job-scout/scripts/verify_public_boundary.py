"""Reject private paths, credentials, and identity artifacts from the repository."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
IGNORED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
FORBIDDEN_NAMES = {".env", "cookies.json", "jobs.sqlite", "browser_session"}
FORBIDDEN_SUFFIXES = {".pem", ".key"}
FORBIDDEN_TEXT = (
    "/Users/" + "mac/Documents/Private",
    "/Users/" + "mac/Documents/Second Brain Test",
    "passport_" + "number",
    "bank_" + "account",
    "FYF_GENERATION_" + "ACCESS_TOKEN",
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def iter_public_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not IGNORED_PARTS.intersection(path.parts)
    ]


def main() -> None:
    files = iter_public_files()
    secret_files = [
        path
        for path in files
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    if secret_files:
        raise SystemExit("Forbidden files: " + ", ".join(map(str, secret_files)))

    violations: list[str] = []
    for path in files:
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf", ".docx", ".lock"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        violations.extend(f"{path}:{needle}" for needle in FORBIDDEN_TEXT if needle in text)
        violations.extend(
            f"{path}:email outside example.com"
            for domain in EMAIL_PATTERN.findall(text)
            if domain.lower() != "example.com"
        )
    if violations:
        raise SystemExit("Forbidden content:\n" + "\n".join(violations))


if __name__ == "__main__":
    main()
