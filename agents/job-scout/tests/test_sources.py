from datetime import datetime, timezone

import pytest

from hermes_job_scout.models import SourceAuthority
from hermes_job_scout.sources import (
    SourceEnvelopeError,
    classify_source_authority,
    parse_extract_envelope,
    parse_search_envelope,
)

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def test_parses_hermes_search_success_envelope() -> None:
    payload = {
        "success": True,
        "data": {
            "web": [
                {
                    "title": " AI Automation Engineer ",
                    "url": "https://jobs.example.com/roles/123",
                    "description": " Build workflows. ",
                    "position": 1,
                }
            ]
        },
    }
    hints = parse_search_envelope(payload, "tavily", "ai automation", NOW)
    assert len(hints) == 1
    assert hints[0].title == "AI Automation Engineer"
    assert hints[0].description == "Build workflows."
    assert hints[0].authority is SourceAuthority.DISCOVERY_HINT


def test_search_failures_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(SourceEnvelopeError):
        parse_search_envelope("not-a-mapping", "tavily", "q", NOW)
    with pytest.raises(SourceEnvelopeError):
        parse_search_envelope({"success": False, "data": {"web": []}}, "tavily", "q", NOW)
    with pytest.raises(SourceEnvelopeError):
        parse_search_envelope({"success": True, "data": {"web": {}}}, "tavily", "q", NOW)
    with pytest.raises(SourceEnvelopeError):
        parse_search_envelope(
            {"success": True, "data": {"web": ["not-a-mapping"]}}, "tavily", "q", NOW
        )
    with pytest.raises(SourceEnvelopeError):
        parse_search_envelope({"success": False, "error": "quota"}, "tavily", "q", NOW)
    with pytest.raises(SourceEnvelopeError):
        parse_search_envelope(
            {
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "x",
                            "url": "not-a-url",
                            "description": "",
                            "position": 1,
                        }
                    ]
                },
            },
            "tavily",
            "q",
            NOW,
        )
    with pytest.raises(SourceEnvelopeError):
        parse_search_envelope(
            {"success": True, "data": {"web": []}, "unexpected": True}, "tavily", "q", NOW
        )
    with pytest.raises(SourceEnvelopeError):
        parse_search_envelope({"success": True, "data": {"web": []}}, "tavily", "q", None)


def test_parses_extract_results_and_rejects_oversized_content() -> None:
    payload = {
        "results": [
            {
                "url": "https://jobs.example.com/roles/123",
                "title": " AI Automation Engineer ",
                "content": "  Build workflows.  ",
                "metadata": {"lang": "en"},
            }
        ]
    }
    sources = parse_extract_envelope(payload, "firecrawl", NOW)
    assert sources[0].content == "Build workflows."
    assert sources[0].content_sha256
    with pytest.raises(SourceEnvelopeError):
        parse_extract_envelope(
            {
                "results": [
                    {"url": "https://jobs.example.com", "title": "x", "content": "a" * 20_001}
                ]
            },
            "firecrawl",
            NOW,
        )
    with pytest.raises(SourceEnvelopeError):
        parse_extract_envelope(
            {"success": False, "error": "provider unavailable"}, "firecrawl", NOW
        )
    with pytest.raises(SourceEnvelopeError):
        parse_extract_envelope({"results": {}}, "firecrawl", NOW)
    with pytest.raises(SourceEnvelopeError):
        parse_extract_envelope({"results": ["not-a-mapping"]}, "firecrawl", NOW)
    with pytest.raises(SourceEnvelopeError):
        parse_extract_envelope({"results": [{"url": "https://example.com"}]}, "firecrawl", NOW)
    with pytest.raises(SourceEnvelopeError):
        parse_extract_envelope(
            {
                "results": [
                    {
                        "url": "https://example.com",
                        "title": "x",
                        "content": "",
                        "error": "blocked",
                    }
                ]
            },
            "firecrawl",
            NOW,
        )


def test_authority_rules_are_conservative() -> None:
    assert (
        classify_source_authority("https://www.linkedin.com/jobs/view/1")
        is SourceAuthority.DISCOVERY_HINT
    )
    assert (
        classify_source_authority("https://www.indeed.com/viewjob?jk=1")
        is SourceAuthority.DISCOVERY_HINT
    )
    assert (
        classify_source_authority("https://boards.greenhouse.io/example/jobs/1")
        is SourceAuthority.ATS
    )
    assert (
        classify_source_authority("https://ashbyhq.com/privacy")
        is SourceAuthority.NEEDS_VERIFICATION
    )
    assert (
        classify_source_authority("https://foo.icims.com/anything")
        is SourceAuthority.NEEDS_VERIFICATION
    )
    assert (
        classify_source_authority("https://www.smartrecruiters.com/resources/blog")
        is SourceAuthority.NEEDS_VERIFICATION
    )
    assert (
        classify_source_authority("https://jobs.smartrecruiters.com/Example/123-title")
        is SourceAuthority.ATS
    )
    assert (
        classify_source_authority("https://example.com/privacy")
        is SourceAuthority.NEEDS_VERIFICATION
    )
    unknown = classify_source_authority("https://careers.unknown.test/jobs/1")
    assert unknown is SourceAuthority.NEEDS_VERIFICATION
    with pytest.raises(SourceEnvelopeError):
        classify_source_authority("not-a-url")
