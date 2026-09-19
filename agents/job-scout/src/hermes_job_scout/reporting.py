"""Deterministic redacted JSON and Markdown reporting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import cast

from .redaction import redact_data


@dataclass(frozen=True)
class QualifiedJobView:
    job_id: str
    company: str
    role: str
    score: float
    stable_url: str


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
        return [f"- {job.role} — {job.company} — {job.score:.2f}" for job in jobs]

    lines = [
        "# Synthetic Job Scout Run Report",
        "",
        f"Qualified: {len(report.qualified_jobs)}",
        f"Duplicates: {report.duplicate_count}",
        f"Invalid fixtures: {report.invalid_fixture_count}",
        f"Model calls: {report.model_calls}",
        f"External actions: {report.external_actions}",
        f"Search/retrieval spend USD: {report.search_retrieval_spend_usd:.2f}",
        "",
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


__all__ = ["QualifiedJobView", "RunReport", "render_markdown"]
