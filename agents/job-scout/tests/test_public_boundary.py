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
FORBIDDEN_TEXT = (
    "/Users/" + "mac/Documents/Private",
    "/Users/" + "mac/Documents/Second Brain Test",
    "passport_" + "number",
    "bank_" + "account",
    "FYF_GENERATION_" + "ACCESS_TOKEN",
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def test_repository_has_no_private_paths_or_secret_files() -> None:
    files = [p for p in ROOT.rglob("*") if p.is_file() and not IGNORED_PARTS.intersection(p.parts)]
    assert not [p for p in files if p.name in FORBIDDEN_NAMES or p.suffix in {".pem", ".key"}]
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
    assert violations == []
