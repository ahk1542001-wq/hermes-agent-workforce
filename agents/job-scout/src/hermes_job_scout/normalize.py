"""Deterministic URL, JobRecord normalization, fingerprinting, and dedup."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AnyHttpUrl, HttpUrl, ValidationError

from .models import (
    Decision,
    EvidenceRef,
    JobRecord,
    JobState,
    RawFeedItem,
    SourceAuthority,
    WorkType,
)

_TRACKING_KEY_RE = re.compile(r"^utm_", re.IGNORECASE)
_TRACKING_KEYS = {"trk", "trackingid", "ref"}
_REQUIRED_RAW = {
    "job_id",
    "stable_url",
    "company",
    "role",
    "work_type",
    "location",
    "remote_region",
    "experience",
    "description",
}
_OPTIONAL_RAW = {
    "source_type",
    "first_seen_at",
    "last_verified_at",
    "posted_at",
    "closes_at",
    "language",
    "skills",
    "salary_evidence",
    "work_authorization_evidence",
    "evidence_refs",
    "uncertainty_flags",
}


def _clean_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def canonicalize_url(url: str) -> str:
    """Return a stable HTTP(S) URL with fragments and tracking keys removed."""

    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("URL must use http or https and include a hostname")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URLs with embedded credentials are not accepted")
    host = parts.hostname.lower().rstrip(".")
    if ":" in host:
        try:
            host = ipaddress.IPv6Address(host).compressed
        except ipaddress.AddressValueError as exc:
            raise ValueError("URL hostname is malformed") from exc
        rendered_host = f"[{host}]"
    else:
        try:
            rendered_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("URL hostname is malformed") from exc
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("URL port is malformed") from exc
    netloc = rendered_host if port is None else f"{rendered_host}:{port}"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_KEY_RE.match(key) and key.lower() not in _TRACKING_KEYS
    ]
    query_pairs.sort(key=lambda pair: (pair[0], pair[1]))
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, urlencode(query_pairs), ""))


def normalize_job(raw: Mapping[str, Any], retrieved_at: datetime) -> JobRecord:
    """Normalize one provider-neutral mapping into a conservative JobRecord."""

    if not isinstance(raw, Mapping):
        raise ValueError("job input must be a mapping")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must include a timezone")
    unknown = set(raw) - _REQUIRED_RAW - _OPTIONAL_RAW
    missing = _REQUIRED_RAW - set(raw)
    if unknown:
        raise ValueError("job input contains unsupported fields")
    if missing:
        raise ValueError("job input is missing required fields")
    try:
        stable_url = canonicalize_url(raw["stable_url"])
        authority = _authority_for_url(stable_url)
        supplied_source_type = raw.get("source_type")
        if supplied_source_type is not None and supplied_source_type != authority.value:
            raise ValueError("source_type conflicts with classified source authority")
        description = _clean_text(raw["description"])
        record = JobRecord(
            job_id=_clean_text(raw["job_id"]),
            stable_url=HttpUrl(stable_url),
            source_type=authority.value,
            authority=authority,
            company=_clean_text(raw["company"]),
            role=_clean_text(raw["role"]),
            first_seen_at=raw.get("first_seen_at", retrieved_at),
            last_verified_at=raw.get("last_verified_at", retrieved_at),
            posted_at=raw.get("posted_at"),
            closes_at=raw.get("closes_at"),
            work_type=WorkType(raw["work_type"]),
            location=_clean_text(raw["location"]),
            remote_region=_clean_text(raw["remote_region"]),
            experience=_clean_text(raw["experience"]),
            language=_clean_list(raw.get("language", [])),
            skills=_clean_list(raw.get("skills", [])),
            salary_evidence=raw.get("salary_evidence", []),
            work_authorization_evidence=raw.get("work_authorization_evidence", []),
            evidence_refs=raw.get("evidence_refs", []),
            uncertainty_flags=_clean_list(raw.get("uncertainty_flags", [])),
            fingerprint="0" * 64,
            state=JobState.DISCOVERED,
            owner_decision=Decision.NEEDS_VICTOR,
            work_auth_label=None,
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError("job input failed strict normalization") from exc
    description_hash = hashlib.sha256(description.encode("utf-8")).hexdigest()
    fingerprint = _fingerprint_parts(record, description_hash)
    return record.model_copy(update={"fingerprint": fingerprint})


def normalize_feed_item(
    item: RawFeedItem,
    retrieved_at: datetime,
    work_type: WorkType = WorkType.FULL_TIME,
) -> JobRecord:
    """Normalize a RawFeedItem into a conservative JobRecord."""

    if not isinstance(item, RawFeedItem):
        raise ValueError("item must be a RawFeedItem")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must include a timezone")

    stable_url = canonicalize_url(str(item.url))
    company = _clean_text(item.company)
    role = _clean_text(item.title)
    job_id = _clean_text(item.source_item_id)
    location = _clean_text(item.location) if item.location else "Worldwide"
    description = _clean_text(item.description)

    evidence_refs: list[EvidenceRef] = []
    if item.apply_url is not None:
        canonical_apply = canonicalize_url(str(item.apply_url))
        evidence_refs.append(
            EvidenceRef(
                field="apply_url",
                source_url=AnyHttpUrl(canonical_apply),
                retrieved_at=retrieved_at,
            )
        )

    first_seen = (
        min(item.published_at, retrieved_at) if item.published_at is not None else retrieved_at
    )

    record = JobRecord(
        job_id=job_id,
        stable_url=HttpUrl(stable_url),
        source_type=item.authority.value,
        authority=item.authority,
        company=company,
        role=role,
        first_seen_at=first_seen,
        last_verified_at=retrieved_at,
        posted_at=item.published_at,
        closes_at=None,
        work_type=work_type,
        location=location,
        remote_region=location,
        experience="0-3 years",
        language=[],
        skills=[],
        salary_evidence=[],
        work_authorization_evidence=[],
        evidence_refs=evidence_refs,
        uncertainty_flags=[],
        fingerprint="0" * 64,
        state=JobState.DISCOVERED,
        owner_decision=Decision.NEEDS_VICTOR,
        work_auth_label=None,
    )
    description_hash = hashlib.sha256(description.encode("utf-8")).hexdigest()
    fingerprint = _fingerprint_parts(record, description_hash)
    return record.model_copy(update={"fingerprint": fingerprint})


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("list fields must contain strings")
    return [_clean_text(item) for item in value]


def _authority_for_url(url: str) -> SourceAuthority:
    from .sources import classify_source_authority

    return classify_source_authority(url)


def _fingerprint_parts(record: JobRecord, description_hash: str) -> str:
    parts = {
        "company": _clean_text(record.company).casefold(),
        "role": _clean_text(record.role).casefold(),
        "location": _clean_text(record.location).casefold(),
        "source_job_id": _clean_text(record.job_id).casefold(),
        "description_sha256": description_hash,
    }
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def content_fingerprint(record: JobRecord) -> str:
    """Return the persisted content identity for an already-normalized record."""

    if not isinstance(record, JobRecord):
        raise ValueError("record must be a JobRecord")
    return record.fingerprint


@dataclass(frozen=True)
class DuplicateGroup:
    retained: JobRecord
    aliases: list[JobRecord]
    provenance: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DeduplicationResult:
    records: list[JobRecord]
    duplicate_groups: list[DuplicateGroup]


_AUTHORITY_RANK = {
    SourceAuthority.OFFICIAL: 5,
    SourceAuthority.ATS: 4,
    SourceAuthority.API: 4,
    SourceAuthority.RSS: 3,
    SourceAuthority.USER_PROVIDED: 3,
    SourceAuthority.AGGREGATOR: 2,
    SourceAuthority.DISCOVERY_HINT: 1,
}


def deduplicate(records: Sequence[JobRecord]) -> DeduplicationResult:
    """Collapse identical fingerprints while retaining strongest provenance."""

    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("records must be a sequence")
    grouped: dict[str, list[JobRecord]] = {}
    identities: dict[str, tuple[str, str, str, str]] = {}
    order: list[str] = []
    for record in records:
        if not isinstance(record, JobRecord):
            raise ValueError("records must contain JobRecord values")
        identity = (
            _clean_text(record.company).casefold(),
            _clean_text(record.role).casefold(),
            _clean_text(record.location).casefold(),
            _clean_text(record.job_id).casefold(),
        )
        prior_identity = identities.get(record.fingerprint)
        if prior_identity is not None and prior_identity != identity:
            raise ValueError("fingerprint collision or stale normalized record")
        identities[record.fingerprint] = identity
        if record.fingerprint not in grouped:
            grouped[record.fingerprint] = []
            order.append(record.fingerprint)
        grouped[record.fingerprint].append(record)
    retained_records: list[JobRecord] = []
    duplicate_groups: list[DuplicateGroup] = []
    for key in order:
        aliases = grouped[key]
        retained = max(
            aliases,
            key=lambda record: (_AUTHORITY_RANK.get(record.authority, 0), -aliases.index(record)),
        )
        retained_records.append(retained)
        if len(aliases) > 1:
            duplicate_groups.append(
                DuplicateGroup(
                    retained=retained,
                    aliases=list(aliases),
                    provenance=[str(alias.stable_url) for alias in aliases],
                )
            )
    return DeduplicationResult(records=retained_records, duplicate_groups=duplicate_groups)
