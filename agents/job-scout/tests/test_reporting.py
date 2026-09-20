import json
from datetime import datetime, timezone

from hermes_job_scout.reporting import QualifiedJobView, RunReport, render_markdown

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def _report(count: int = 40) -> RunReport:
    jobs = tuple(
        QualifiedJobView(
            job_id=f"job-{index:02d}",
            company="Synthetic Company",
            role=f"AI Automation Engineer {index:02d}",
            score=float(100 - index),
            stable_url=f"https://careers.example.com/jobs/{index}",
        )
        for index in range(count)
    )
    return RunReport(
        run_id="synthetic-run",
        created_at=NOW,
        qualified_jobs=jobs,
        rejection_reasons={"NON_AI_ROLE": 2},
        invalid_fixture_count=1,
        duplicate_count=3,
        runtime_ms=0,
        model_calls=0,
        tool_calls=0,
        free_credit_usage={},
        search_retrieval_spend_usd=0,
        external_actions=0,
    )


def test_digest_has_top_15_secondary_20_and_full_board() -> None:
    report = _report()
    assert len(report.top) == 15
    assert len(report.secondary) == 20
    assert report.additional_qualified_count == 5
    assert len(report.qualified_jobs) == 40
    assert report.top[0].job_id == "job-00"
    assert report.secondary[0].job_id == "job-15"


def test_json_and_markdown_are_structured_redacted_and_deterministic() -> None:
    report = _report(2)
    first = report.to_json()
    second = report.to_json()
    assert first == second
    payload = json.loads(first)
    assert payload["model_calls"] == 0
    assert payload["external_actions"] == 0
    assert payload["search_retrieval_spend_usd"] == 0
    markdown = render_markdown(report)
    assert "Top 15" in markdown
    assert "Secondary 20" in markdown
    assert "Full qualified board" in markdown


def test_markdown_redacts_sensitive_values_in_job_fields() -> None:
    private_path = "/" + "/".join(("Users", "example", "private-note"))
    report = RunReport(
        run_id="synthetic-redaction",
        created_at=NOW,
        qualified_jobs=(
            QualifiedJobView(
                job_id="job-sensitive",
                company="Contact person@example.com or +66 81 234 5678",
                role=f"token=synthetic-secret {private_path}",
                score=91.0,
                stable_url="https://careers.example.com/jobs/sensitive",
            ),
        ),
        rejection_reasons={},
        invalid_fixture_count=0,
        duplicate_count=0,
        runtime_ms=0,
        model_calls=0,
        tool_calls=0,
        free_credit_usage={},
        search_retrieval_spend_usd=0,
        external_actions=0,
    )

    markdown = render_markdown(report)

    assert "person@example.com" not in markdown
    assert "+66 81 234 5678" not in markdown
    assert "synthetic-secret" not in markdown
    assert private_path not in markdown
    assert markdown.count("<REDACTED>") >= 4
