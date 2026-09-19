"""Local-only dry-run CLI for synthetic Job Scout verification."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from .documents import (
    ApplicationPackDraft,
    DraftClaim,
    extract_docx_text,
    render_resume_docx,
    render_resume_pdf,
    render_synthetic_resume,
)
from .evidence import (
    EvidenceApprovalError,
    EvidencePackError,
    load_evidence_pack,
    require_approved_evidence,
)
from .models import CandidateFact, CandidateProfile, JobState, SearchPolicy, WorkType
from .normalize import deduplicate, normalize_job
from .policy import evaluate_hard_filters
from .reporting import QualifiedJobView, RunReport, render_markdown
from .scoring import score_job

app = typer.Typer(no_args_is_help=True)
_NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_input_directory(path: Path) -> Path:
    if "://" in str(path):
        raise typer.BadParameter("fixture input must be a local directory")
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise typer.BadParameter("fixture input cannot be a symlink")
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise typer.BadParameter("fixture input must be a real local directory")
    return resolved


def _safe_output(path: Path, fixtures: Path) -> Path:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise typer.BadParameter("output cannot be a symlink")
    resolved = candidate.resolve()
    if _inside(resolved, fixtures):
        raise typer.BadParameter("outputs cannot be written inside the fixture directory")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() and (resolved.is_symlink() or not resolved.is_file()):
        raise typer.BadParameter("output must be a regular non-symlink file")
    return resolved


def _policy() -> SearchPolicy:
    return SearchPolicy(
        policy_version="synthetic-v1",
        headline="AI Automation Engineer",
        role_aliases=[
            "AI automation engineer",
            "agentic workflow engineer",
            "n8n automation engineer",
        ],
        geography_priority=["worldwide remote", "APAC remote", "international remote", "Thailand"],
        allowed_work_types=list(WorkType),
        accepted_languages=["English", "Thai basic or optional"],
        max_experience_years=3,
        freshness_days=30,
        excluded_seniority=["senior", "lead", "principal"],
    )


def _profile() -> CandidateProfile:
    claims = {
        "summary": "Builds synthetic AI automation workflows",
        "python": "Python",
        "n8n": "n8n",
        "experience": "Built synthetic automation workflows",
    }
    facts = [
        CandidateFact(
            fact_id=key,
            category="synthetic",
            allowed_wording=value,
            source="synthetic fixture",
            verified=True,
        )
        for key, value in claims.items()
    ]
    return CandidateProfile(
        candidate_id="synthetic-candidate",
        display_name="Synthetic Candidate",
        headline="AI Automation Engineer",
        summary=claims["summary"],
        facts=facts,
        skills=[claims["python"], claims["n8n"]],
        experience=[claims["experience"]],
    )


def _load_fixture_records(fixtures: Path) -> tuple[list[Any], int, str]:
    records: list[Any] = []
    invalid = 0
    digest = hashlib.sha256()
    for path in sorted(fixtures.glob("*.json")):
        if path.is_symlink() or path.parent != fixtures:
            raise typer.BadParameter("fixture files must remain inside the supplied directory")
        raw = path.read_bytes()
        digest.update(path.name.encode("utf-8") + b"\0" + raw)
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                for field in ("first_seen_at", "last_verified_at", "posted_at", "closes_at"):
                    value = payload.get(field)
                    if isinstance(value, str):
                        payload[field] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            records.append(normalize_job(payload, _NOW))
        except (ValueError, TypeError, json.JSONDecodeError):
            invalid += 1
    return records, invalid, digest.hexdigest()[:16]


def _write_dry_run_database(path: Path, jobs: tuple[QualifiedJobView, ...]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE qualified_jobs (job_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO qualified_jobs(job_id, payload) VALUES (?, ?)",
            [
                (job.job_id, json.dumps(job.__dict__, sort_keys=True, separators=(",", ":")))
                for job in jobs
            ],
        )
    os.chmod(path, 0o600)


@app.command("run-fixtures")
def run_fixtures(
    fixtures: Path = typer.Option(...),
    db: Path = typer.Option(...),
    report: Path = typer.Option(...),
) -> None:
    fixture_root = _safe_input_directory(fixtures)
    database_path = _safe_output(db, fixture_root)
    report_path = _safe_output(report, fixture_root)
    markdown_path = _safe_output(report_path.with_suffix(".md"), fixture_root)
    if len({database_path, report_path, markdown_path}) != 3:
        raise typer.BadParameter("database, JSON report, and Markdown report paths must differ")
    if database_path.exists() or report_path.exists() or markdown_path.exists():
        raise typer.BadParameter("dry-run outputs must not already exist")
    records, invalid_count, run_id = _load_fixture_records(fixture_root)
    deduped = deduplicate(records)
    policy = _policy()
    profile = _profile()
    qualified: list[QualifiedJobView] = []
    rejection_reasons: dict[str, int] = {}
    for record in deduped.records:
        decision = evaluate_hard_filters(record, policy, _NOW)
        if decision.decision.value != "qualified":
            code = decision.reason_codes[0] if decision.reason_codes else "UNSPECIFIED"
            rejection_reasons[code] = rejection_reasons.get(code, 0) + 1
            continue
        qualified_record = record.model_copy(
            update={"state": JobState.QUALIFIED, "work_auth_label": decision.work_auth_label}
        )
        score = score_job(qualified_record, profile, policy.policy_version)
        qualified.append(
            QualifiedJobView(
                job_id=record.job_id,
                company=record.company,
                role=record.role,
                score=score.total_score,
                stable_url=str(record.stable_url),
            )
        )
    run_report = RunReport(
        run_id=f"fixtures-{run_id}",
        created_at=_NOW,
        qualified_jobs=tuple(qualified),
        rejection_reasons=rejection_reasons,
        invalid_fixture_count=invalid_count,
        duplicate_count=sum(max(0, len(group.aliases) - 1) for group in deduped.duplicate_groups),
        runtime_ms=0,
        model_calls=0,
        tool_calls=0,
        free_credit_usage={},
        search_retrieval_spend_usd=0,
        external_actions=0,
    )
    _write_dry_run_database(database_path, run_report.qualified_jobs)
    report_path.write_text(run_report.to_json(), encoding="utf-8")
    os.chmod(report_path, 0o600)
    markdown_path.write_text(render_markdown(run_report), encoding="utf-8")
    os.chmod(markdown_path, 0o600)
    summary = (
        f"qualified={len(qualified)} invalid={invalid_count} "
        f"duplicates={run_report.duplicate_count}"
    )
    typer.echo(summary)


@app.command("render-synthetic")
def render_synthetic(output: Path = typer.Option(...)) -> None:
    artifacts = render_synthetic_resume(output.expanduser().resolve())
    typer.echo(f"rendered={len(artifacts)} synthetic artifacts")


@app.command("validate-evidence")
def validate_evidence(pack: Path = typer.Option(...), approval: Path = typer.Option(...)) -> None:
    try:
        evidence = load_evidence_pack(pack)
        approved = require_approved_evidence(evidence, approval)
    except (EvidencePackError, EvidenceApprovalError) as exc:
        raise typer.BadParameter("evidence pack or approval failed validation") from exc
    typer.echo(f"approved facts={len(approved.profile.facts)} sha256={approved.sha256}")


def _fact_claim(text: str, facts: dict[str, CandidateFact]) -> DraftClaim:
    for fact in facts.values():
        if fact.verified and fact.allowed_wording == text:
            return DraftClaim(text, fact.fact_id)
    raise typer.BadParameter("profile claim is not bound to an approved fact")


@app.command("build-master-resume")
def build_master_resume(
    pack: Path = typer.Option(...),
    approval: Path = typer.Option(...),
    output: Path = typer.Option(...),
) -> None:
    try:
        evidence = require_approved_evidence(load_evidence_pack(pack), approval)
    except (EvidencePackError, EvidenceApprovalError) as exc:
        raise typer.BadParameter("evidence pack or approval failed validation") from exc
    profile = evidence.profile
    facts = {fact.fact_id: fact for fact in profile.facts}
    draft = ApplicationPackDraft(
        identity=_fact_claim(profile.display_name, facts),
        headline=_fact_claim(profile.headline, facts),
        summary=_fact_claim(profile.summary, facts),
        skills=tuple(_fact_claim(value, facts) for value in profile.skills),
        experience=tuple(_fact_claim(value, facts) for value in profile.experience),
        education=tuple(_fact_claim(value, facts) for value in profile.education),
    )
    destination = output.expanduser().absolute()
    expected_destination = evidence.workspace_root / "master"
    if destination != expected_destination or destination.is_symlink():
        raise typer.BadParameter(
            "master resume output must be the canonical private master directory"
        )
    docx_path = render_resume_docx(draft, list(facts.values()), destination / "master-resume.docx")
    render_resume_pdf(draft, list(facts.values()), destination / "master-resume.pdf")
    text_path = destination / "master-resume.txt"
    text_path.write_text(extract_docx_text(docx_path), encoding="utf-8")
    os.chmod(text_path, 0o600)
    typer.echo("master resume rendered from approved evidence")


@app.command("report")
def report_command(report: Path = typer.Option(...)) -> None:
    payload = json.loads(report.read_text(encoding="utf-8"))
    typer.echo(
        f"qualified={len(payload.get('qualified_jobs', []))} "
        f"model_calls={payload.get('model_calls', 'unknown')} "
        f"external_actions={payload.get('external_actions', 'unknown')}"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
