import re
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

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
    assert find_text_violations(files) == []


def find_text_violations(files: list[Path]) -> list[str]:
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
    return violations


def test_reachable_commit_emails_use_public_noreply_identity() -> None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "log", "--format=%ae%n%ce"],
        check=True,
        capture_output=True,
        text=True,
    )
    emails = [line.strip().lower() for line in result.stdout.splitlines() if line.strip()]
    assert emails
    assert all(email.endswith(("@users.noreply.github.com", "@example.com")) for email in emails)


def test_root_level_forbidden_text_is_detected(tmp_path: Path) -> None:
    root_file = tmp_path / "README.md"
    root_file.write_text(FORBIDDEN_TEXT[0], encoding="utf-8")
    violations = find_text_violations([root_file])
    assert violations == [f"{root_file}:{FORBIDDEN_TEXT[0]}"]


REQUIRED_PUBLIC_FILES = {
    "README.md",
    "SECURITY.md",
    "docs/ARCHITECTURE.md",
    "docs/PERMISSION_MODEL.md",
    "docs/ATTRIBUTION.md",
    "docs/DATA_BOUNDARIES.md",
    "docs/UPSTREAM_REVIEW.md",
    "agents/job-scout/README.md",
    "agents/job-scout/hermes-profile.example/README.md",
    ".gitleaks.toml",
    ".github/workflows/ci.yml",
    "release-manifest.json",
    "scripts/build_release.py",
    "scripts/verify_public_boundary.py",
}


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = spec_from_file_location(f"test_{name}_module", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_docs_ci_and_mock_only_contract_exist() -> None:
    assert not [path for path in REQUIRED_PUBLIC_FILES if not (ROOT / path).is_file()]
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required in ("permissions:", "contents: read", "ruff", "mypy", "pytest", "gitleaks"):
        assert required in ci.lower()
    assert "pull_request_target" not in ci
    docs = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/PERMISSION_MODEL.md", "agents/job-scout/README.md")
    ).lower()
    assert "mock-only" in docs


def test_public_docs_describe_the_current_stage3_local_pilot() -> None:
    current_docs = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "agents/job-scout/README.md",
            "docs/ARCHITECTURE.md",
            "docs/PERMISSION_MODEL.md",
        )
    }
    assert all("Stage 3" in text for text in current_docs.values())
    assert "pilot-feed-discovery" in current_docs["README.md"]
    assert "local feed snapshots" in current_docs["docs/ARCHITECTURE.md"]


def test_private_path_fails_public_boundary(tmp_path: Path) -> None:
    scanner = _load_script("verify_public_boundary")
    (tmp_path / "README.md").write_text(
        "/Users/" + "example/Documents/Private/Career", encoding="utf-8"
    )
    findings = scanner.scan_tree(tmp_path)
    assert any(finding.rule == "private_path" for finding in findings)
    assert all("Private/Career" not in finding.message for finding in findings)


def test_release_builder_uses_exact_allowlist(tmp_path: Path) -> None:
    builder = _load_script("build_release")
    artifact = tmp_path / "artifact"
    builder.build_release(ROOT, artifact)
    manifest = __import__("json").loads((ROOT / "release-manifest.json").read_text())
    expected = set(manifest["files"])
    actual = {
        path.relative_to(artifact).as_posix() for path in artifact.rglob("*") if path.is_file()
    }
    assert actual == expected


@pytest.mark.parametrize(
    ("relative", "content", "rule"),
    [
        ("unexpected.txt", b"synthetic", "unexpected_file"),
        ("private.sqlite", b"SQLite format 3", "forbidden_extension"),
        ("archive.zip", b"PK synthetic", "forbidden_extension"),
        ("resume.docx", b"synthetic", "forbidden_extension"),
        ("secret.pem", b"synthetic", "forbidden_extension"),
        ("binary.bin", b"\x00\x01", "binary_file"),
        ("contact.txt", b"person@" + b"real-domain.test", "personal_contact"),
        ("credential.txt", b"api_" + b"key=synthetic-but-forbidden", "credential_like"),
        ("pointer.txt", b"private_" + b"workspace=/tmp/example", "private_workspace_pointer"),
        ("examples/real.json", b'{"company":"Acme"}', "non_synthetic_artifact"),
    ],
)
def test_built_artifact_mutations_fail(
    tmp_path: Path, relative: str, content: bytes, rule: str
) -> None:
    scanner = _load_script("verify_public_boundary")
    root = tmp_path / "artifact"
    root.mkdir()
    mutation = root / relative
    mutation.parent.mkdir(parents=True, exist_ok=True)
    mutation.write_bytes(content)
    findings = scanner.scan_tree(root, expected_files=set())
    assert any(finding.rule == rule for finding in findings)


def test_symlink_and_oversized_artifacts_fail(tmp_path: Path) -> None:
    scanner = _load_script("verify_public_boundary")
    root = tmp_path / "artifact"
    root.mkdir()
    target = root / "target.txt"
    target.write_text("synthetic", encoding="utf-8")
    (root / "link.txt").symlink_to(target)
    (root / "large.txt").write_bytes(b"x" * (1024 * 1024 + 1))
    findings = scanner.scan_tree(root)
    assert {finding.rule for finding in findings} >= {"symlink", "oversized_file"}


@pytest.mark.parametrize(
    "entries",
    [
        ["README.md", "README.md"],
        ["/absolute/path"],
        ["../traversal"],
        ["README.md"],
    ],
)
def test_release_manifest_rejects_duplicate_unsafe_or_omitted_entries(
    tmp_path: Path, entries: list[str]
) -> None:
    builder = _load_script("build_release")
    (tmp_path / "release-manifest.json").write_text(
        __import__("json").dumps({"version": 1, "files": entries}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        builder.build_release(tmp_path, tmp_path / "artifact")


def test_release_builder_rejects_symlinked_allowlist_entry(tmp_path: Path) -> None:
    builder = _load_script("build_release")
    for required in builder.REQUIRED:
        path = tmp_path / required
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic", encoding="utf-8")
    target = tmp_path / "target.txt"
    target.write_text("synthetic", encoding="utf-8")
    link = tmp_path / "linked.txt"
    link.symlink_to(target)
    entries = sorted({*builder.REQUIRED, "linked.txt"})
    (tmp_path / "release-manifest.json").write_text(
        __import__("json").dumps({"version": 1, "files": entries}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="regular file"):
        builder.build_release(tmp_path, tmp_path / "artifact")
