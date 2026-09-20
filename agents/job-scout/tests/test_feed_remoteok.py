import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hermes_job_scout.models import SourceAuthority
from hermes_job_scout.sources import (
    SourceEnvelopeError,
    parse_remoteok_json,
    parse_remoteok_rss,
)

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def test_parses_valid_remoteok_json() -> None:
    data = json.loads((FIXTURES / "remoteok_valid.json").read_text(encoding="utf-8"))
    items = parse_remoteok_json(data, NOW)
    assert len(items) == 2

    first = items[0]
    assert first.source_name == "remoteok"
    assert first.source_item_id == "12345"
    assert first.title == "AI Automation Specialist"
    assert first.company == "SuperAI"
    assert str(first.url) == "https://remoteok.com/remote-jobs/12345-ai-automation-specialist"
    assert str(first.apply_url) == "https://boards.greenhouse.io/superai/jobs/999"
    assert first.authority is SourceAuthority.DISCOVERY_HINT
    assert first.retrieved_at == NOW

    second = items[1]
    assert second.source_name == "remoteok"
    assert second.company == "NextGen AI"
    assert str(second.apply_url) == "https://jobs.ashbyhq.com/nextgen/888"


def test_parses_valid_remoteok_rss() -> None:
    xml_text = (FIXTURES / "remoteok_valid.xml").read_text(encoding="utf-8")
    items = parse_remoteok_rss(xml_text, NOW)
    assert len(items) == 1

    item = items[0]
    assert item.source_name == "remoteok"
    assert item.title == "AI Automation Specialist"
    assert item.company == "SuperAI"
    assert item.authority is SourceAuthority.DISCOVERY_HINT
    assert str(item.url) == "https://remoteok.com/remote-jobs/12345-ai-automation-specialist"
    assert item.published_at is not None
    assert item.published_at.tzinfo is not None


def test_remoteok_malformed_fails_closed() -> None:
    with pytest.raises(SourceEnvelopeError):
        parse_remoteok_json([], NOW)  # empty sequence

    with pytest.raises(SourceEnvelopeError):
        parse_remoteok_json("not-a-list", NOW)  # type: ignore[arg-type]

    with pytest.raises(SourceEnvelopeError):
        parse_remoteok_json([{"legal": "info"}], NOW)  # only legal header, no jobs

    with pytest.raises(SourceEnvelopeError):
        parse_remoteok_json([{"legal": "info"}, "not-a-dict"], NOW)  # non-mapping item

    with pytest.raises(SourceEnvelopeError):
        parse_remoteok_json([{"position": "Dev"}], NOW)  # missing company/id

    with pytest.raises(SourceEnvelopeError):
        parse_remoteok_rss("<invalid xml", NOW)

    with pytest.raises(SourceEnvelopeError):
        parse_remoteok_rss("<rss><channel></channel></rss>", NOW)  # no items


def test_remoteok_url_fallback() -> None:
    payload = [
        {
            "id": "789",
            "position": "Engineer",
            "company": "Beta",
            "slug": "engineer-789",
        }
    ]
    items = parse_remoteok_json(payload, NOW)
    assert str(items[0].url) == "https://remoteok.com/remote-jobs/engineer-789"
