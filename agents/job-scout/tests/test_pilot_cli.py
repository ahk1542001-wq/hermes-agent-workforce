from __future__ import annotations

import json
import socket
from pathlib import Path

from typer.testing import CliRunner

from hermes_job_scout.cli import app
from hermes_job_scout.config import WorkspacePaths
from hermes_job_scout.database import JobStore, RevisionConflict
from hermes_job_scout.models import JobState, SourceAuthority
from hermes_job_scout.workspace import bootstrap_private_workspace

RUNNER = CliRunner()

HIMALAYAS_PAYLOAD = {
    "data": [
        {
            "title": "AI Automation Engineer",
            "companyName": "Acme AI Corp",
            "companySlug": "acme-ai",
            "slug": "req-acme-101",
            "applicationLink": "https://jobs.ashbyhq.com/acme-ai/12345",
            "description": "Build agentic workflows with Python and n8n. 0-3 years experience.",
            "location": "Worldwide Remote",
            "seniority": "Entry-level",
            "employmentType": "full_time",
            "pubDate": "2026-09-15T00:00:00Z",
        },
        {
            "title": "Senior AI Architect",
            "companyName": "Legacy Enterprise",
            "companySlug": "legacy",
            "slug": "req-legacy-999",
            "applicationLink": "https://jobs.ashbyhq.com/legacy/99999",
            "description": "Lead architecture.",
            "location": "Worldwide Remote",
            "seniority": "Senior",
            "pubDate": "2026-09-15T00:00:00Z",
        },
    ]
}

REMOTEOK_PAYLOAD = [
    {
        "id": "req-acme-101",
        "epoch": 1789804800,
        "date": "2026-09-15T00:00:00+00:00",
        "company": "Acme AI Corp",
        "position": "AI Automation Engineer",
        "tags": ["python", "n8n"],
        "description": "Build agentic workflows with Python and n8n. 0-3 years experience.",
        "location": "Worldwide Remote",
        "url": "https://remoteok.com/remote-jobs/req-acme-101?utm_source=remoteok",
        "apply_url": "https://jobs.ashbyhq.com/acme-ai/12345?ref=remoteok",
    },
    {
        "id": "rok-102",
        "epoch": 1789804800,
        "date": "2026-09-15T00:00:00+00:00",
        "company": "Discovery Startup",
        "position": "AI Automation Engineer",
        "tags": ["python", "n8n"],
        "description": "Build agentic workflows.",
        "location": "Worldwide",
        "url": "https://remoteok.com/remote-jobs/rok-102",
        "apply_url": "https://remoteok.com/apply/rok-102",
    },
]


def _setup_feeds(feed_dir: Path) -> None:
    feed_dir.mkdir(parents=True, exist_ok=True)
    (feed_dir / "himalayas_feed.json").write_text(json.dumps(HIMALAYAS_PAYLOAD), encoding="utf-8")
    (feed_dir / "remoteok_feed.json").write_text(json.dumps(REMOTEOK_PAYLOAD), encoding="utf-8")


def test_pilot_feed_discovery_cli_e2e(tmp_path: Path, monkeypatch) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)

    def deny_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("network socket creation is forbidden during pilot feed discovery")

    monkeypatch.setattr(socket, "socket", deny_socket)

    workspace_dir = tmp_path / "workspace"
    paths = WorkspacePaths.from_root(workspace_dir)
    marker = bootstrap_private_workspace(paths)

    report_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(workspace_dir),
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "discovered=" in result.output
    assert "verified=" in result.output
    assert "qualified=" in result.output

    # Verify report JSON
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["model_calls"] == 0
    assert payload["search_retrieval_spend_usd"] == 0
    assert payload["external_actions"] == 0
    assert payload["duplicate_count"] >= 1
    assert payload["runtime_ms"] > 0
    assert len(payload["qualified_jobs"]) == 1
    assert payload["qualified_jobs"][0]["company"] == "Acme AI Corp"

    # Verify markdown digest
    assert markdown_path.exists()
    md_text = markdown_path.read_text(encoding="utf-8")
    assert "[ATS]" in md_text
    assert "Acme AI Corp" in md_text
    assert "Model calls: 0" in md_text

    # Verify database via JobStore
    with JobStore.open(paths.database, marker) as store:
        job = store.get_job("req-acme-101")
        assert job is not None
        assert job.company == "Acme AI Corp"
        assert job.authority == SourceAuthority.ATS
        assert job.state == JobState.QUALIFIED

        src = store.get_source("himalayas")
        assert src is not None
        assert src.status == "healthy"

        run = store.get_discovery_run(payload["run_id"])
        assert run is not None
        assert run.coverage == "full"
        assert "himalayas" in run.checked_source_ids
        assert "remoteok" in run.checked_source_ids
        assert run.failed_source_ids == []


def test_pilot_feed_discovery_clock_injection(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)

    workspace_dir = tmp_path / "workspace"
    paths = WorkspacePaths.from_root(workspace_dir)
    marker = bootstrap_private_workspace(paths)
    report_path = tmp_path / "report.json"

    injected_time = "2026-09-18T10:30:00+00:00"
    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(workspace_dir),
            "--report",
            str(report_path),
            "--now",
            injected_time,
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["created_at"].startswith("2026-09-18T10:30:00")

    with JobStore.open(paths.database, marker) as store:
        run = store.get_discovery_run(payload["run_id"])
        assert run is not None
        assert run.completed_at.isoformat().startswith("2026-09-18T10:30:00")


def test_pilot_feed_discovery_re_run_no_duplicate_events(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)

    workspace_dir = tmp_path / "workspace"
    paths = WorkspacePaths.from_root(workspace_dir)
    marker = bootstrap_private_workspace(paths)
    report_path = tmp_path / "report.json"

    fixed_now = "2026-09-15T08:00:00+00:00"
    args = [
        "pilot-feed-discovery",
        "--feed-dir",
        str(feed_dir),
        "--workspace",
        str(workspace_dir),
        "--report",
        str(report_path),
        "--now",
        fixed_now,
    ]

    # First run
    res1 = RUNNER.invoke(app, args)
    assert res1.exit_code == 0, res1.output

    with JobStore.open(paths.database, marker) as store:
        rev1 = store.current_revision()
        events1 = store.list_events("req-acme-101")
        assert len(events1) == 1

    # Second run with unchanged feeds and same --now
    res2 = RUNNER.invoke(app, args)
    assert res2.exit_code == 0, res2.output

    with JobStore.open(paths.database, marker) as store:
        rev2 = store.current_revision()
        events2 = store.list_events("req-acme-101")
        # No duplicate application events
        assert len(events2) == 1
        # No unnecessary revision bump
        assert rev2 == rev1


def test_pilot_feed_discovery_partial_coverage_malformed_feed(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    feed_dir.mkdir(parents=True, exist_ok=True)
    (feed_dir / "himalayas_feed.json").write_text(json.dumps(HIMALAYAS_PAYLOAD), encoding="utf-8")
    (feed_dir / "remoteok_feed.json").write_text("{malformed json", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    paths = WorkspacePaths.from_root(workspace_dir)
    marker = bootstrap_private_workspace(paths)
    report_path = tmp_path / "report.json"

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(workspace_dir),
            "--report",
            str(report_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["invalid_fixture_count"] >= 1
    assert "remoteok_feed.json" in payload["input_errors"]

    with JobStore.open(paths.database, marker) as store:
        run = store.get_discovery_run(payload["run_id"])
        assert run is not None
        assert run.coverage == "partial"
        assert "himalayas" in run.checked_source_ids
        assert "remoteok" in run.checked_source_ids
        assert run.failed_source_ids == ["remoteok"]

        himalayas_src = store.get_source("himalayas")
        assert himalayas_src is not None
        assert himalayas_src.status == "healthy"

        remoteok_src = store.get_source("remoteok")
        assert remoteok_src is not None
        assert remoteok_src.status == "failing"


def test_pilot_feed_discovery_unknown_feed_filename_reporting(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    feed_dir.mkdir(parents=True, exist_ok=True)
    (feed_dir / "himalayas_feed.json").write_text(json.dumps(HIMALAYAS_PAYLOAD), encoding="utf-8")
    (feed_dir / "unrecognized_source.xyz").write_text("some content", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    paths = WorkspacePaths.from_root(workspace_dir)
    marker = bootstrap_private_workspace(paths)
    report_path = tmp_path / "report.json"

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(workspace_dir),
            "--report",
            str(report_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "unrecognized_source.xyz" in payload["unknown_inputs"]
    assert "unrecognized_source.xyz" in payload["input_errors"]

    with JobStore.open(paths.database, marker) as store:
        assert store.get_job("req-acme-101") is not None
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        run = store.get_discovery_run(payload["run_id"])
        assert run is not None
        assert run.coverage == "partial"


def test_pilot_feed_discovery_unknown_only_run_is_audited(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    feed_dir.mkdir(parents=True, exist_ok=True)
    (feed_dir / "unknown.bin").write_bytes(b"not a supported feed")
    workspace_dir = tmp_path / "workspace"
    report_path = tmp_path / "report.json"

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(workspace_dir),
            "--report",
            str(report_path),
            "--now",
            "2026-09-20T12:00:00+00:00",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(report_path.read_text(encoding="utf-8"))
    paths = WorkspacePaths.from_root(workspace_dir)
    with JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8")) as store:
        run = store.get_discovery_run(report["run_id"])
        assert run is not None
        assert run.coverage == "partial"
        assert run.checked_source_ids == []
        assert run.result_count == 0


def test_pilot_feed_discovery_concurrent_revision_conflict_rollback(
    tmp_path: Path, monkeypatch
) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)

    workspace_dir = tmp_path / "workspace"
    paths = WorkspacePaths.from_root(workspace_dir)
    marker = bootstrap_private_workspace(paths)
    report_path = tmp_path / "report.json"

    # Simulate revision conflict on transaction enter
    def conflict_transaction(self, expected_revision: int):
        # Force a revision conflict
        raise RevisionConflict("simulated conflict")

    monkeypatch.setattr(JobStore, "transaction", conflict_transaction)

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(workspace_dir),
            "--report",
            str(report_path),
        ],
    )
    assert result.exit_code != 0
    # Confirm nothing was committed
    with JobStore.open(paths.database, marker) as store:
        assert store.get_job("req-acme-101") is None


def test_pilot_feed_discovery_safety_and_validation(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)

    # Invalid input dir
    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(tmp_path / "nonexistent"),
            "--workspace",
            str(tmp_path / "workspace"),
            "--report",
            str(tmp_path / "test.json"),
        ],
    )
    assert result.exit_code != 0

    # Output inside feed dir
    result_inside = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(feed_dir / "nested-workspace"),
            "--report",
            str(tmp_path / "test.json"),
        ],
    )
    assert result_inside.exit_code != 0


def test_pilot_feed_discovery_wwr_and_remotive(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    feed_dir.mkdir(parents=True, exist_ok=True)
    wwr_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>We Work Remotely: Remote Programming Jobs</title>
    <link>https://weworkremotely.com</link>
    <description>Remote programming jobs</description>
    <item>
      <title>CognitiveWorks: AI Automation Architect</title>
      <link>https://weworkremotely.com/remote-jobs/cognitiveworks-ai-automation-architect</link>
      <guid>https://weworkremotely.com/remote-jobs/cognitiveworks-ai-automation-architect</guid>
      <description>Design agentic workflows.</description>
      <pubDate>Sun, 20 Sep 2026 08:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""
    (feed_dir / "wwr_feed.xml").write_text(wwr_xml, encoding="utf-8")

    remotive_json = {
        "jobs": [
            {
                "id": 1928374,
                "url": "https://remotive.com/remote-jobs/ai-dev-1928374",
                "title": "AI Automation Developer",
                "company_name": "CloudScale",
                "publication_date": "2026-09-19T12:00:00Z",
                "candidate_required_location": "Worldwide Remote",
                "description": "Build agentic AI workflows and integrations.",
            }
        ]
    }
    (feed_dir / "remotive_feed.json").write_text(json.dumps(remotive_json), encoding="utf-8")

    workspace_dir = tmp_path / "workspace2"
    report_path = tmp_path / "report2.json"

    # With WWR approved
    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(workspace_dir),
            "--report",
            str(report_path),
            "--wwr-approved",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["discovered_count"] == 2
    assert payload["needs_verification_count"] >= 1


def test_pilot_feed_discovery_wwr_unapproved_records_failure(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    feed_dir.mkdir(parents=True, exist_ok=True)
    wwr_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>WWR</title>
    <item>
      <title>CognitiveWorks: AI Automation Architect</title>
      <link>https://weworkremotely.com/remote-jobs/123</link>
      <guid>https://weworkremotely.com/remote-jobs/123</guid>
    </item>
  </channel>
</rss>"""
    (feed_dir / "wwr_feed.xml").write_text(wwr_xml, encoding="utf-8")

    workspace_dir = tmp_path / "workspace3"
    report_path = tmp_path / "report3.json"

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(workspace_dir),
            "--report",
            str(report_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["invalid_fixture_count"] == 1
    assert payload["discovered_count"] == 0


def test_pilot_feed_discovery_invalid_now_timestamp(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(tmp_path / "workspace"),
            "--report",
            str(tmp_path / "report.json"),
            "--now",
            "not-a-valid-date",
        ],
    )
    assert result.exit_code != 0
    assert "invalid --now timestamp" in result.output
    assert not (tmp_path / "workspace").exists()


def test_pilot_feed_discovery_rejects_naive_now_timestamp(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(tmp_path / "workspace"),
            "--report",
            str(tmp_path / "report.json"),
            "--now",
            "2026-09-20T12:00:00",
        ],
    )
    assert result.exit_code != 0
    assert "timezone" in result.output.casefold()
    assert not (tmp_path / "workspace").exists()


def test_pilot_feed_discovery_distinct_times_preserve_distinct_runs(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)
    workspace_dir = tmp_path / "workspace"

    first_report = tmp_path / "first.json"
    second_report = tmp_path / "second.json"
    for report, now in (
        (first_report, "2026-09-20T10:00:00+00:00"),
        (second_report, "2026-09-20T11:00:00+00:00"),
    ):
        result = RUNNER.invoke(
            app,
            [
                "pilot-feed-discovery",
                "--feed-dir",
                str(feed_dir),
                "--workspace",
                str(workspace_dir),
                "--report",
                str(report),
                "--now",
                now,
            ],
        )
        assert result.exit_code == 0, result.output

    first_run_id = json.loads(first_report.read_text(encoding="utf-8"))["run_id"]
    second_run_id = json.loads(second_report.read_text(encoding="utf-8"))["run_id"]
    assert first_run_id != second_run_id

    paths = WorkspacePaths.from_root(workspace_dir)
    with JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8")) as store:
        first_run = store.get_discovery_run(first_run_id)
        second_run = store.get_discovery_run(second_run_id)
        assert first_run is not None
        assert second_run is not None
        assert first_run.changed_count > 0
        assert second_run.changed_count == 0
        assert len(store.list_events("req-acme-101")) == 1


def test_pilot_feed_discovery_rejects_workspace_control_file_as_report(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)
    paths = WorkspacePaths.from_root(tmp_path / "workspace")
    bootstrap_private_workspace(paths)
    marker_before = paths.marker.read_bytes()

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--workspace",
            str(paths.root),
            "--report",
            str(paths.marker),
        ],
    )

    assert result.exit_code != 0
    assert "protected workspace" in result.output
    assert paths.marker.read_bytes() == marker_before


def test_pilot_feed_discovery_requires_workspace(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--report",
            str(tmp_path / "report.json"),
        ],
    )
    assert result.exit_code != 0
    assert "--workspace" in result.output


def test_pilot_feed_discovery_rejects_legacy_db_copy_mode(tmp_path: Path) -> None:
    feed_dir = tmp_path / "feeds"
    _setup_feeds(feed_dir)
    legacy_db = tmp_path / "pilot.sqlite"

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--db",
            str(legacy_db),
            "--report",
            str(tmp_path / "report.json"),
        ],
    )

    assert result.exit_code != 0
    assert "--db" in result.output
    assert not legacy_db.exists()
    assert not (tmp_path / "workspace_pilot").exists()
