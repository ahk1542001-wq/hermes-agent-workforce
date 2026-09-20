from datetime import datetime, timezone
from pathlib import Path

import pytest

from hermes_job_scout.models import SourceAuthority
from hermes_job_scout.sources import (
    SourceEnvelopeError,
    parse_weworkremotely_rss,
)

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def test_wwr_rss_requires_preflight_approval() -> None:
    xml_text = (FIXTURES / "wwr_valid.xml").read_text(encoding="utf-8")
    with pytest.raises(SourceEnvelopeError, match="preflight"):
        parse_weworkremotely_rss(xml_text, NOW, preflight_approved=False)


def test_parses_valid_wwr_rss_when_preflight_approved() -> None:
    xml_text = (FIXTURES / "wwr_valid.xml").read_text(encoding="utf-8")
    items = parse_weworkremotely_rss(xml_text, NOW, preflight_approved=True)
    assert len(items) == 1

    item = items[0]
    assert item.source_name == "weworkremotely"
    assert item.title == "AI Automation Architect"
    assert item.company == "CognitiveWorks"
    assert (
        str(item.url)
        == "https://weworkremotely.com/remote-jobs/cognitiveworks-ai-automation-architect"
    )
    assert item.authority is SourceAuthority.DISCOVERY_HINT
    assert item.published_at is not None
    assert item.published_at.tzinfo is not None


def test_wwr_rss_malformed_fails_closed() -> None:
    with pytest.raises(SourceEnvelopeError):
        parse_weworkremotely_rss("<invalid xml", NOW, preflight_approved=True)

    with pytest.raises(SourceEnvelopeError):
        parse_weworkremotely_rss("<rss><channel></channel></rss>", NOW, preflight_approved=True)
