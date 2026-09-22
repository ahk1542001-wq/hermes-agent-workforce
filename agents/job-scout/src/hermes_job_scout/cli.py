"""Local-only dry-run CLI for synthetic Job Scout verification."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import typer

from .config import WorkspacePaths
from .database import JobStore
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
from .models import (
    CandidateFact,
    CandidateProfile,
    DiscoveryRun,
    JobRecord,
    JobState,
    RawFeedItem,
    SearchPolicy,
    SourceAuthority,
    WorkType,
)
from .normalize import deduplicate, normalize_feed_item, normalize_job
from .policy import evaluate_hard_filters
from .reporting import QualifiedJobView, RunReport, render_markdown
from .scoring import score_job
from .sources import (
    parse_himalayas_feed,
    parse_remoteok_json,
    parse_remoteok_rss,
    parse_remotive_api,
    parse_remotive_rss,
    parse_weworkremotely_rss,
)
from .workspace import bootstrap_private_workspace

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


def _validate_report_targets(report: Path, markdown: Path, paths: WorkspacePaths) -> None:
    protected = {
        paths.marker.absolute(),
        paths.lock.absolute(),
        paths.database.absolute(),
        Path(f"{paths.database}-journal").absolute(),
        Path(f"{paths.database}-wal").absolute(),
        Path(f"{paths.database}-shm").absolute(),
    }
    if report.absolute() in protected or markdown.absolute() in protected:
        raise typer.BadParameter("report path cannot overwrite a protected workspace file")


def _same_job_content(left: JobRecord, right: JobRecord) -> bool:
    def comparable(record: JobRecord) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        payload.pop("last_verified_at", None)
        for field in ("evidence_refs", "salary_evidence", "work_authorization_evidence"):
            for ref in payload.get(field, []):
                ref.pop("retrieved_at", None)
        return payload

    return comparable(left) == comparable(right)


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


def _ingest_feed_file(
    path: Path,
    now: datetime,
    wwr_approved: bool = False,
) -> tuple[str, list[RawFeedItem]]:
    name = path.name.casefold()
    if name.endswith(".json"):
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if "himalayas" in name or (isinstance(data, dict) and "data" in data):
            if not isinstance(data, dict):
                raise ValueError("himalayas payload must be a JSON object")
            return "himalayas", parse_himalayas_feed(data, now)
        if "remoteok" in name or isinstance(data, list):
            if not isinstance(data, list):
                raise ValueError("remoteok payload must be a JSON array")
            return "remoteok", parse_remoteok_json(data, now)
        if "remotive" in name or (isinstance(data, dict) and "jobs" in data):
            if not isinstance(data, dict):
                raise ValueError("remotive payload must be a JSON object")
            return "remotive", parse_remotive_api(data, now)
        raise ValueError(f"unrecognized JSON feed format: {path.name}")

    if name.endswith(".xml") or name.endswith(".rss"):
        text = path.read_text(encoding="utf-8")
        lower = text.casefold()
        if "remoteok" in name or "remoteok" in lower:
            return "remoteok", parse_remoteok_rss(text, now)
        if "remotive" in name or "remotive" in lower:
            return "remotive", parse_remotive_rss(text, now)
        if "wwr" in name or "weworkremotely" in name or "weworkremotely" in lower:
            return "weworkremotely", parse_weworkremotely_rss(
                text, now, preflight_approved=wwr_approved
            )
        raise ValueError(f"unrecognized XML/RSS feed format: {path.name}")

    raise ValueError(f"unsupported feed extension: {path.name}")


@app.command("pilot-feed-discovery")
def pilot_feed_discovery(
    feed_dir: Path = typer.Option(..., "--feed-dir", "--feeds", "-f"),
    workspace: Path = typer.Option(..., "--workspace", "-w"),
    report: Path = typer.Option(..., "--report", "-r"),
    wwr_approved: bool = typer.Option(False, "--wwr-approved"),
    now: str | None = typer.Option(None, "--now"),
) -> None:
    feed_root = _safe_input_directory(feed_dir)

    if now is not None:
        try:
            now_dt = datetime.fromisoformat(now.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise typer.BadParameter(f"invalid --now timestamp: {now}") from exc
        if now_dt.tzinfo is None or now_dt.utcoffset() is None:
            raise typer.BadParameter("--now timestamp must include a timezone")
        now_dt = now_dt.astimezone(timezone.utc)
    else:
        now_dt = datetime.now(timezone.utc)

    workspace_root = workspace.expanduser().absolute()
    if _inside(workspace_root, feed_root):
        raise typer.BadParameter("workspace directory cannot be inside feed directory")
    paths = WorkspacePaths.from_root(workspace_root)
    raw_report_path = report.expanduser().absolute()
    raw_markdown_path = raw_report_path.with_suffix(".md")
    _validate_report_targets(raw_report_path, raw_markdown_path, paths)
    report_path = _safe_output(raw_report_path, feed_root)
    markdown_path = _safe_output(raw_markdown_path, feed_root)
    marker = bootstrap_private_workspace(paths)
    start_monotonic = time.monotonic()

    raw_items: list[RawFeedItem] = []
    checked_sources: set[str] = set()
    failed_sources: set[str] = set()
    unknown_inputs: list[str] = []
    input_errors: dict[str, str] = {}
    invalid_count = 0
    digest = hashlib.sha256()

    for path in sorted(feed_root.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        raw_bytes = path.read_bytes()
        digest.update(path.name.encode("utf-8") + b"\0" + raw_bytes)
        try:
            source_id, items = _ingest_feed_file(path, now_dt, wwr_approved=wwr_approved)
            checked_sources.add(source_id)
            raw_items.extend(items)
        except Exception as exc:
            invalid_count += 1
            identified = False
            for candidate in ("himalayas", "remoteok", "remotive", "weworkremotely", "wwr"):
                if candidate in path.name.casefold():
                    norm_id = "weworkremotely" if candidate == "wwr" else candidate
                    checked_sources.add(norm_id)
                    failed_sources.add(norm_id)
                    input_errors[path.name] = str(exc)
                    identified = True
                    break
            if not identified:
                unknown_inputs.append(path.name)
                input_errors[path.name] = str(exc)

    normalized_records: list[JobRecord] = []
    for item in raw_items:
        try:
            normalized_records.append(normalize_feed_item(item, now_dt))
        except Exception as exc:
            invalid_count += 1
            input_errors[f"item_{item.source_name}_{item.source_item_id}"] = str(exc)

    dedup_result = deduplicate(normalized_records)
    verified_records: list[JobRecord] = dedup_result.records

    policy = _policy()
    profile = _profile()
    qualified: list[QualifiedJobView] = []
    records_to_persist: list[JobRecord] = []
    rejection_reasons: dict[str, int] = {}
    verified_count = 0
    needs_verification_count = 0
    closing_soon_count = 0

    for record in verified_records:
        if record.state == JobState.VERIFIED:
            verified_count += 1
        elif record.authority in (
            SourceAuthority.DISCOVERY_HINT,
            SourceAuthority.NEEDS_VERIFICATION,
        ):
            needs_verification_count += 1

        decision = evaluate_hard_filters(record, policy, now_dt)
        if decision.decision.value != "qualified":
            code = decision.reason_codes[0] if decision.reason_codes else "UNSPECIFIED"
            rejection_reasons[code] = rejection_reasons.get(code, 0) + 1
            records_to_persist.append(record)
            continue

        qualified_record = record.model_copy(
            update={"state": JobState.QUALIFIED, "work_auth_label": decision.work_auth_label}
        )
        score = score_job(qualified_record, profile, policy.policy_version)
        records_to_persist.append(qualified_record)

        closing_soon = False
        if record.closes_at is not None:
            remaining_days = (record.closes_at - now_dt).total_seconds() / 86400.0
            if 0 <= remaining_days <= 5:
                closing_soon = True
                closing_soon_count += 1

        qualified.append(
            QualifiedJobView(
                job_id=record.job_id,
                company=record.company,
                role=record.role,
                score=score.total_score,
                stable_url=str(record.stable_url),
                authority=(
                    record.authority.value
                    if hasattr(record.authority, "value")
                    else str(record.authority)
                ),
                closing_soon=closing_soon,
            )
        )

    runtime_ms = int((time.monotonic() - start_monotonic) * 1000)
    duplicate_count = sum(max(0, len(group.aliases) - 1) for group in dedup_result.duplicate_groups)
    run_identity = f"{digest.hexdigest()}:{now_dt.isoformat()}"
    run_id = hashlib.sha256(run_identity.encode("utf-8")).hexdigest()[:16]
    run_report = RunReport(
        run_id=f"pilot-{run_id}",
        created_at=now_dt,
        qualified_jobs=tuple(qualified),
        rejection_reasons=rejection_reasons,
        invalid_fixture_count=invalid_count,
        duplicate_count=duplicate_count,
        runtime_ms=runtime_ms,
        model_calls=0,
        tool_calls=0,
        free_credit_usage={},
        search_retrieval_spend_usd=0.0,
        external_actions=0,
        discovered_count=len(dedup_result.records),
        verified_count=verified_count,
        needs_verification_count=needs_verification_count,
        closing_soon_count=closing_soon_count,
        unknown_inputs=tuple(unknown_inputs),
        input_errors=input_errors,
    )

    coverage = "partial" if failed_sources or unknown_inputs or invalid_count else "full"
    with JobStore.open(paths.database, marker) as store:
        persisted_records: list[JobRecord] = []
        changed_records: list[JobRecord] = []
        for record in records_to_persist:
            existing = store.get_job(record.job_id)
            if existing is not None and existing.first_seen_at < record.first_seen_at:
                record = JobRecord.model_validate(
                    {
                        **record.model_dump(mode="python"),
                        "first_seen_at": existing.first_seen_at,
                    }
                )
            if existing is not None and _same_job_content(existing, record):
                persisted_records.append(existing)
            else:
                persisted_records.append(record)
                changed_records.append(record)
        expected_revision = store.current_revision()
        persisted_run_id = f"pilot-{run_id}"
        existing_run = store.get_discovery_run(persisted_run_id)
        with store.transaction(expected_revision) as txn:
            for rec in persisted_records:
                txn.upsert_job(rec)
            for source_id in sorted(checked_sources):
                is_failed = source_id in failed_sources
                items_from_source = any(item.source_name == source_id for item in raw_items)
                txn.update_source_health(
                    source_id=source_id,
                    checked_at=now_dt,
                    success=not is_failed,
                    error_code="FETCH_ERROR" if is_failed else None,
                    changed=items_from_source and bool(changed_records),
                )
            if existing_run is None:
                discovery_run = DiscoveryRun(
                    run_id=persisted_run_id,
                    started_at=now_dt,
                    completed_at=now_dt + timedelta(milliseconds=runtime_ms),
                    coverage=coverage,
                    checked_source_ids=sorted(checked_sources),
                    failed_source_ids=sorted(failed_sources),
                    changed_count=len(changed_records),
                    result_count=len(persisted_records),
                    provider="feed_pilot",
                    tokens_used=None,
                    tool_calls=0,
                    query_count=len(checked_sources),
                    pages_checked=len(checked_sources),
                    cache_hits=0,
                    free_credits_remaining={},
                    model_calls=0,
                    actual_search_retrieval_spend_usd=0.0,
                )
                txn.record_discovery_run(discovery_run)

    report_path.write_text(run_report.to_json(), encoding="utf-8")
    os.chmod(report_path, 0o600)
    markdown_path.write_text(render_markdown(run_report), encoding="utf-8")
    os.chmod(markdown_path, 0o600)

    summary = (
        f"discovered={len(dedup_result.records)} verified={verified_count} "
        f"qualified={len(qualified)} needs_verification={needs_verification_count} "
        f"duplicates={duplicate_count} invalid={invalid_count}"
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
        contact=tuple(
            _fact_claim(fact.allowed_wording, facts)
            for fact in profile.facts
            if fact.category == "contact"
        ),
        skills=tuple(_fact_claim(value, facts) for value in profile.skills),
        experience=tuple(_fact_claim(value, facts) for value in profile.experience),
        projects=tuple(
            _fact_claim(fact.allowed_wording, facts)
            for fact in profile.facts
            if fact.category == "project"
        ),
        credentials=tuple(
            _fact_claim(fact.allowed_wording, facts)
            for fact in profile.facts
            if fact.category == "credential"
        ),
        education=tuple(_fact_claim(value, facts) for value in profile.education),
        languages=tuple(
            _fact_claim(f"{language}: {level}", facts)
            for language, level in profile.languages.items()
        ),
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
