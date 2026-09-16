from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from hermes_job_scout.models import JobRecord, SourceAuthority, WorkType
from hermes_job_scout.normalize import (
    canonicalize_url,
    content_fingerprint,
    deduplicate,
    normalize_job,
)

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def _raw(
    url: str = "https://boards.greenhouse.io/example/jobs/123?utm_source=x",
) -> dict[str, object]:
    return {
        "job_id": "  req-123 ",
        "stable_url": url,
        "company": "  Example   Automation Labs ",
        "role": " AI  Automation Engineer ",
        "work_type": "full_time",
        "location": " Remote   (Worldwide) ",
        "remote_region": " Global ",
        "experience": " 0-3 years ",
        "description": "Build   reliable workflows.\n",
    }


def test_canonicalizes_tracking_without_losing_job_id() -> None:
    assert (
        canonicalize_url(
            "HTTPS://Boards.Greenhouse.io/example/jobs/123?utm_source=x&job_id=123&ref=feed#about"
        )
        == "https://boards.greenhouse.io/example/jobs/123?job_id=123"
    )


def test_canonicalizes_ipv6_without_dropping_required_brackets() -> None:
    assert canonicalize_url("HTTP://[2001:0DB8::1]:8080/jobs/1#x") == (
        "http://[2001:db8::1]:8080/jobs/1"
    )


def test_normalizes_unicode_whitespace_and_fingerprints_stably() -> None:
    record = normalize_job(_raw(), NOW)
    assert record.company == "Example Automation Labs"
    assert record.role == "AI Automation Engineer"
    assert str(record.stable_url) == "https://boards.greenhouse.io/example/jobs/123"
    assert record.authority is SourceAuthority.ATS
    assert record.work_type is WorkType.FULL_TIME
    assert record.fingerprint == content_fingerprint(record)
    assert record.fingerprint == content_fingerprint(normalize_job(_raw(), NOW))


def test_fingerprint_survives_json_round_trip_without_hidden_state() -> None:
    record = normalize_job(_raw(), NOW)
    restored = JobRecord.model_validate_json(record.model_dump_json())
    assert "_description_hash" not in record.__dict__
    assert content_fingerprint(restored) == record.fingerprint


def test_conflicting_source_type_fails_closed() -> None:
    with pytest.raises(ValueError, match="failed strict normalization"):
        normalize_job({**_raw(), "source_type": "official"}, NOW)


@pytest.mark.parametrize(
    ("raw", "retrieved_at"),
    [
        ("not-a-mapping", NOW),
        (_raw(), datetime(2026, 9, 15, 8, 0)),
        ({**_raw(), "unexpected": True}, NOW),
        ({key: value for key, value in _raw().items() if key != "role"}, NOW),
        ({**_raw(), "skills": ["valid", 7]}, NOW),
    ],
)
def test_malformed_normalization_inputs_fail_closed(raw: object, retrieved_at: datetime) -> None:
    with pytest.raises(ValueError):
        normalize_job(raw, retrieved_at)  # type: ignore[arg-type]


def test_fingerprint_and_dedup_require_typed_records() -> None:
    with pytest.raises(ValueError, match="JobRecord"):
        content_fingerprint("not-a-record")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sequence"):
        deduplicate("not-records")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="JobRecord"):
        deduplicate(["not-a-record"])  # type: ignore[list-item]


def test_frozen_record_and_stale_fingerprint_cannot_collapse_distinct_jobs() -> None:
    first = normalize_job(_raw(), NOW)
    with pytest.raises(ValidationError):
        first.company = "Different Company"
    stale = first.model_copy(update={"company": "Different Company"})
    with pytest.raises(ValueError, match="collision|stale"):
        deduplicate([first, stale])


def test_duplicate_listing_is_collapsed() -> None:
    first = normalize_job(_raw(), NOW)
    alias = normalize_job(_raw("https://boards.greenhouse.io/example/jobs/123?trk=abc"), NOW)
    result = deduplicate([first, alias])
    assert len(result.records) == 1
    assert len(result.duplicate_groups) == 1
    assert len(result.duplicate_groups[0].aliases) == 2


def test_same_company_different_requisition_ids_are_separate() -> None:
    one = normalize_job(_raw(), NOW)
    two = normalize_job(
        {
            **_raw(),
            "job_id": "req-124",
            "stable_url": "https://boards.greenhouse.io/example/jobs/124",
        },
        NOW,
    )
    assert one.fingerprint != two.fingerprint
    assert len(deduplicate([one, two]).records) == 2


def test_discovery_hint_stays_unverified_and_needs_owner() -> None:
    record = normalize_job(_raw("https://www.linkedin.com/jobs/view/123?trk=synthetic"), NOW)
    assert record.authority is SourceAuthority.DISCOVERY_HINT
    assert record.state.value == "discovered"
    assert record.owner_decision.value == "needs_victor"
