import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hermes_job_scout.models import SourceAuthority
from hermes_job_scout.sources import (
    SourceEnvelopeError,
    parse_remotive_api,
    parse_remotive_rss,
)

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def test_parses_valid_remotive_api_with_delay_metadata() -> None:
    data = json.loads((FIXTURES / "remotive_valid.json").read_text(encoding="utf-8"))
    items = parse_remotive_api(data, NOW)
    assert len(items) == 2

    first = items[0]
    assert first.source_name == "remotive"
    assert first.source_item_id == "1928374"
    assert first.title == "AI Automation Developer"
    assert first.company == "CloudScale"
    assert str(first.url) == "https://remotive.com/remote-jobs/software-dev/ai-automation-dev-1928374"
    assert first.is_delayed is True
    assert first.metadata.get("source_delay") == "documented_24h_delay"
    assert first.authority is SourceAuthority.DISCOVERY_HINT
    assert first.location == "Worldwide"

    second = items[1]
    assert second.source_item_id == "5647382"
    assert second.company == "DataFlow"
    assert second.location == "APAC Remote"
    assert second.is_delayed is True


def test_parses_valid_remotive_rss() -> None:
    xml_text = (FIXTURES / "remotive_valid.xml").read_text(encoding="utf-8")
    items = parse_remotive_rss(xml_text, NOW)
    assert len(items) == 1

    item = items[0]
    assert item.source_name == "remotive"
    assert item.title == "AI Automation Developer"
    assert item.company == "CloudScale"
    assert item.is_delayed is True
    assert item.metadata.get("source_delay") == "documented_24h_delay"
    assert item.authority is SourceAuthority.DISCOVERY_HINT


def test_remotive_malformed_fails_closed() -> None:
    with pytest.raises(SourceEnvelopeError):
        parse_remotive_api("not-a-mapping", NOW)  # type: ignore[arg-type]

    with pytest.raises(SourceEnvelopeError):
        parse_remotive_api({"job-count": 0, "jobs": []}, NOW)

    with pytest.raises(SourceEnvelopeError):
        parse_remotive_rss("<invalid xml", NOW)

    with pytest.raises(SourceEnvelopeError):
        parse_remotive_rss("<rss><channel></channel></rss>", NOW)
