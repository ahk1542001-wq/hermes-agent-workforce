import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hermes_job_scout.models import SourceAuthority
from hermes_job_scout.sources import SourceEnvelopeError, parse_himalayas_feed

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def test_parses_valid_himalayas_feed() -> None:
    data = json.loads((FIXTURES / "himalayas_valid.json").read_text(encoding="utf-8"))
    items = parse_himalayas_feed(data, NOW)
    assert len(items) == 2

    first = items[0]
    assert first.source_name == "himalayas"
    assert first.source_item_id == "ai-automation-engineer-123"
    assert first.title == "AI Automation Engineer"
    assert first.company == "Acme Corp"
    assert str(first.url) == "https://himalayas.app/jobs/acme-corp/ai-automation-engineer-123"
    assert str(first.apply_url) == "https://jobs.lever.co/acme/123"
    assert first.authority is SourceAuthority.DISCOVERY_HINT
    assert first.retrieved_at == NOW
    assert first.published_at is not None
    assert first.published_at.tzinfo is not None

    second = items[1]
    assert second.source_name == "himalayas"
    assert second.company == "Beta Labs"
    assert str(second.apply_url) == "https://boards.greenhouse.io/betalabs/jobs/456"
    assert second.location == "APAC Remote"


def test_himalayas_malformed_and_missing_fields_fail_closed() -> None:
    malformed = json.loads((FIXTURES / "himalayas_malformed.json").read_text(encoding="utf-8"))
    with pytest.raises(SourceEnvelopeError):
        parse_himalayas_feed(malformed, NOW)

    with pytest.raises(SourceEnvelopeError):
        parse_himalayas_feed("not-a-dict", NOW)  # type: ignore[arg-type]

    with pytest.raises(SourceEnvelopeError):
        parse_himalayas_feed({"data": [{"title": "Missing slug"}]}, NOW)

    with pytest.raises(SourceEnvelopeError):
        parse_himalayas_feed({"data": []}, datetime(2026, 9, 20, 9, 0))  # naive datetime


def test_himalayas_url_slug_fallbacks() -> None:
    # missing url, has companySlug
    payload1 = {
        "data": [
            {
                "title": "Engineer",
                "companyName": "Acme",
                "slug": "eng-1",
                "companySlug": "acme",
            }
        ]
    }
    items1 = parse_himalayas_feed(payload1, NOW)
    assert str(items1[0].url) == "https://himalayas.app/jobs/acme/eng-1"

    # missing url, missing companySlug
    payload2 = {
        "data": [
            {
                "title": "Engineer",
                "companyName": "Acme",
                "slug": "eng-2",
            }
        ]
    }
    items2 = parse_himalayas_feed(payload2, NOW)
    assert str(items2[0].url) == "https://himalayas.app/jobs/eng-2"
