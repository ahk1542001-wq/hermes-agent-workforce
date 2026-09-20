"""Deterministic redacted JSON and Markdown reporting."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import cast

from .models import DiscoveryRun, SourceRecord
from .redaction import redact_data, redact_text


@dataclass(frozen=True)
class QualifiedJobView:
    job_id: str
    company: str
    role: str
    score: float
    stable_url: str
    authority: str = ""
    closing_soon: bool = False


@dataclass(frozen=True)
class RunReport:
    run_id: str
    created_at: datetime
    qualified_jobs: tuple[QualifiedJobView, ...]
    rejection_reasons: dict[str, int]
    invalid_fixture_count: int
    duplicate_count: int
    runtime_ms: int
    model_calls: int
    tool_calls: int
    free_credit_usage: dict[str, int]
    search_retrieval_spend_usd: float
    external_actions: int
    discovered_count: int = 0
    verified_count: int = 0
    needs_verification_count: int = 0
    closing_soon_count: int = 0

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("report timestamp must include a timezone")
        ordered = tuple(sorted(self.qualified_jobs, key=lambda job: (-job.score, job.job_id)))
        object.__setattr__(self, "qualified_jobs", ordered)

    @property
    def top(self) -> tuple[QualifiedJobView, ...]:
        return self.qualified_jobs[:15]

    @property
    def secondary(self) -> tuple[QualifiedJobView, ...]:
        return self.qualified_jobs[15:35]

    @property
    def additional_qualified_count(self) -> int:
        return max(0, len(self.qualified_jobs) - 35)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["top"] = [asdict(job) for job in self.top]
        payload["secondary"] = [asdict(job) for job in self.secondary]
        payload["additional_qualified_count"] = self.additional_qualified_count
        return cast(dict[str, object], redact_data(payload))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_markdown(report: RunReport) -> str:
    def rows(jobs: tuple[QualifiedJobView, ...]) -> list[str]:
        if not jobs:
            return ["- None"]
        items = []
        for job in jobs:
            badge = f"[{job.authority.upper()}] " if job.authority else ""
            alert = " ⚠️ [CLOSING SOON]" if job.closing_soon else ""
            role_str = redact_text(job.role)
            comp_str = redact_text(job.company)
            items.append(f"- {badge}{role_str} — {comp_str} — {job.score:.2f}{alert}")
        return items

    closing_soon_jobs = [job for job in report.qualified_jobs if job.closing_soon]
    closing_alerts: list[str] = []
    if closing_soon_jobs or report.closing_soon_count > 0:
        alert_rows = (
            [
                f"- {redact_text(j.role)} at {redact_text(j.company)} (Job ID: {j.job_id})"
                for j in closing_soon_jobs
            ]
            if closing_soon_jobs
            else ["- None"]
        )
        closing_alerts = [
            "## Closing Soon Alerts",
            "",
            *alert_rows,
            "",
        ]

    lines = [
        "# Synthetic Job Scout Run Report",
        "",
        f"Qualified: {len(report.qualified_jobs)}",
        f"Discovered: {report.discovered_count}",
        f"Verified: {report.verified_count}",
        f"Needs verification: {report.needs_verification_count}",
        f"Closing soon: {report.closing_soon_count}",
        f"Duplicates: {report.duplicate_count}",
        f"Invalid fixtures: {report.invalid_fixture_count}",
        f"Model calls: {report.model_calls}",
        f"External actions: {report.external_actions}",
        f"Search/retrieval spend USD: {report.search_retrieval_spend_usd:.2f}",
        "",
        *closing_alerts,
        "## Top 15",
        "",
        *rows(report.top),
        "",
        "## Secondary 20",
        "",
        *rows(report.secondary),
        "",
        f"Additional qualified: {report.additional_qualified_count}",
        "",
        "## Full qualified board",
        "",
        *rows(report.qualified_jobs),
        "",
    ]
    return "\n".join(lines)


def format_run_summary(run: DiscoveryRun, sources: Sequence[SourceRecord] = ()) -> str:
    """Format an auditable summary of a discovery run and source health."""
    failed_names = ", ".join(run.failed_source_ids) if run.failed_source_ids else "None"
    lines = [
        f"# Discovery Run Summary: {run.run_id}",
        "",
        f"- Provider: {run.provider}",
        f"- Coverage: {run.coverage}",
        f"- Checked sources ({len(run.checked_source_ids)}): {', '.join(run.checked_source_ids)}",
        f"- Failed sources: {failed_names}",
        f"- Results found: {run.result_count}",
        f"- Changed count: {run.changed_count}",
        f"- Model calls: {run.model_calls}",
        f"- Search/retrieval spend USD: {run.actual_search_retrieval_spend_usd:.2f}",
    ]
    if sources:
        lines.extend(["", "## Source Health Status", ""])
        for src in sources:
            err = f", error: {src.last_error_code}" if src.last_error_code else ""
            succ = (
                f", last success: {src.last_success_at.isoformat()}" if src.last_success_at else ""
            )
            lines.append(
                f"- {src.source_id}: {src.status} "
                f"(last checked: {src.last_checked_at.isoformat()}{succ}{err})"
            )
    lines.append("")
    return "\n".join(lines)


__all__ = ["QualifiedJobView", "RunReport", "format_run_summary", "render_markdown"]
