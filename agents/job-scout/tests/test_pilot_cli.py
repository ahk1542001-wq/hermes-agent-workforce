from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from hermes_job_scout.cli import app

RUNNER = CliRunner()

HIMALAYAS_PAYLOAD = {
    "data": [
        {
            "title": "AI Automation Engineer",
            "companyName": "Acme AI Corp",
            "companySlug": "acme-ai",
            "slug": "req-acme-101",
            "applicationLink": "https://jobs.ashbyhq.com/acme-ai/12345",
            "description": "Build agentic workflows with Python and n8n.",
            "location": "Worldwide Remote",
            "seniority": "Entry-level",
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
        "description": "Build agentic workflows with Python and n8n.",
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

    db_path = tmp_path / "pilot.sqlite"
    report_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--db",
            str(db_path),
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
    assert len(payload["qualified_jobs"]) == 1
    assert payload["qualified_jobs"][0]["company"] == "Acme AI Corp"

    # Verify markdown digest
    assert markdown_path.exists()
    md_text = markdown_path.read_text(encoding="utf-8")
    assert "[ATS]" in md_text
    assert "Acme AI Corp" in md_text
    assert "Model calls: 0" in md_text

    # Verify database
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM qualified_jobs")
        count = cursor.fetchone()[0]
        assert count == 1
        cursor.execute("SELECT COUNT(*) FROM discovered_jobs")
        disc_count = cursor.fetchone()[0]
        assert disc_count >= 2


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
            "--db",
            str(tmp_path / "test.sqlite"),
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
            "--db",
            str(feed_dir / "nested.sqlite"),
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

    db_path = tmp_path / "pilot2.sqlite"
    report_path = tmp_path / "report2.json"

    # With WWR approved
    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--db",
            str(db_path),
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

    db_path = tmp_path / "pilot3.sqlite"
    report_path = tmp_path / "report3.json"

    result = RUNNER.invoke(
        app,
        [
            "pilot-feed-discovery",
            "--feed-dir",
            str(feed_dir),
            "--db",
            str(db_path),
            "--report",
            str(report_path),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["invalid_fixture_count"] == 1
    assert payload["discovered_count"] == 0
