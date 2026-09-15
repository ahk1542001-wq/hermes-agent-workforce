from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_repository_uses_workforce_monorepo_layout() -> None:
    assert (ROOT / "agents/job-scout/pyproject.toml").is_file()
    assert (ROOT / "agents/job-scout/src/hermes_job_scout").is_dir()
    assert (ROOT / "agents/job-scout/tests/test_public_boundary.py").is_file()
    assert (ROOT / "scripts/verify_all.sh").is_file()
    assert not (ROOT / "pyproject.toml").exists()
    assert not (ROOT / "src/hermes_job_scout").exists()
