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
_EXPERIENCE_PATTERN = re.compile(
    r"\b\d+\s*(?:(?:-|–|to)\s*\d+|\+)?\s*years?\b(?:\s+required)?",
    re.IGNORECASE,
)
_EXPERIENCE_CONTEXT_PATTERN = re.compile(
    r"\b(?:required|minimum|at least|must have|preferred|qualifications?|candidate|applicant)\b",
    re.IGNORECASE,
)
_DIRECT_EXPERIENCE_PATTERN = re.compile(
    r"\b\d+\s*(?:(?:-|–|to)\s*\d+|\+)?\s*years?\s+experience\b",
    re.IGNORECASE,
)
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


_WORK_TYPE_MAP: dict[str, WorkType] = {
    "full_time": WorkType.FULL_TIME,
    "full-time": WorkType.FULL_TIME,
    "full time": WorkType.FULL_TIME,
    "permanent": WorkType.FULL_TIME,
    "direct_contract": WorkType.DIRECT_CONTRACT,
    "direct-contract": WorkType.DIRECT_CONTRACT,
    "contract": WorkType.DIRECT_CONTRACT,
    "freelance_contract": WorkType.FREELANCE_CONTRACT,
    "freelance": WorkType.FREELANCE_CONTRACT,
    "contractor": WorkType.FREELANCE_CONTRACT,
    "paid_internship": WorkType.PAID_INTERNSHIP,
    "internship": WorkType.PAID_INTERNSHIP,
}


def normalize_feed_item(
    item: RawFeedItem,
    retrieved_at: datetime,
    work_type: WorkType | None = None,
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
    experience_chunks = [
        chunk.strip()
        for chunk in re.split(r"[.;\n]+", description)
        if _EXPERIENCE_PATTERN.search(chunk)
        and (_EXPERIENCE_CONTEXT_PATTERN.search(chunk) or _DIRECT_EXPERIENCE_PATTERN.search(chunk))
    ]
    experience = "; ".join(experience_chunks)[:500] if experience_chunks else "Unknown"

    resolved_work_type = work_type
    if resolved_work_type is None and "work_type" in item.metadata:
        raw_wt = item.metadata["work_type"].strip().casefold()
        resolved_work_type = _WORK_TYPE_MAP.get(raw_wt)
        if resolved_work_type is None:
            try:
                resolved_work_type = WorkType(item.metadata["work_type"])
            except ValueError:
                resolved_work_type = None

    uncertainty_flags: list[str] = []
    if not experience_chunks:
        uncertainty_flags.append("EXPERIENCE_UNKNOWN")
    if item.published_at is None:
        uncertainty_flags.append("FRESHNESS_UNKNOWN")
    if resolved_work_type is None:
        uncertainty_flags.append("WORK_TYPE_UNKNOWN")

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
        work_type=resolved_work_type,
        location=location,
        remote_region=location,
        experience=experience,
        language=[],
        skills=[],
        salary_evidence=[],
        work_authorization_evidence=[],
        evidence_refs=evidence_refs,
        uncertainty_flags=uncertainty_flags,
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


def _extract_ats_url(record: JobRecord) -> str | None:
    from .sources import classify_source_authority, verify_feed_listing

    stable_str = str(record.stable_url)
    try:
        if classify_source_authority(stable_str) in (SourceAuthority.ATS, SourceAuthority.OFFICIAL):
            verified = verify_feed_listing(
                record,
                official_url=stable_str,
                verified_at=record.last_verified_at,
            )
            if verified is not record:
                return canonicalize_url(str(verified.stable_url))
    except Exception:
        pass

    for ref in record.evidence_refs:
        if ref.source_url:
            source_str = str(ref.source_url)
            try:
                if classify_source_authority(source_str) in (
                    SourceAuthority.ATS,
                    SourceAuthority.OFFICIAL,
                ):
                    verified = verify_feed_listing(
                        record,
                        official_url=source_str,
                        verified_at=ref.retrieved_at,
                    )
                    if verified.state is JobState.VERIFIED:
                        return canonicalize_url(str(verified.stable_url))
            except Exception:
                pass
    return None


def deduplicate(records: Sequence[JobRecord]) -> DeduplicationResult:
    """Collapse identical ATS requisitions or fingerprints while retaining strongest provenance."""

    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("records must be a sequence")
    grouped: dict[str, list[JobRecord]] = {}
    identities: dict[str, tuple[str, str, str, str]] = {}
    ats_to_group: dict[str, str] = {}
    fp_to_group: dict[str, str] = {}
    group_ats_url: dict[str, str] = {}
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

        ats_url = _extract_ats_url(record)
        group_key: str | None = None

        if ats_url is not None and ats_url in ats_to_group:
            group_key = ats_to_group[ats_url]
        elif record.fingerprint in fp_to_group:
            existing_key = fp_to_group[record.fingerprint]
            existing_ats = group_ats_url.get(existing_key)
            if existing_ats is None or ats_url is None or existing_ats == ats_url:
                group_key = existing_key

        if group_key is None:
            group_key = f"ats:{ats_url}" if ats_url else f"fp:{record.fingerprint}"
            grouped[group_key] = []
            order.append(group_key)
            if ats_url:
                group_ats_url[group_key] = ats_url

        if ats_url:
            ats_to_group[ats_url] = group_key
            group_ats_url[group_key] = ats_url
        fp_to_group[record.fingerprint] = group_key
        grouped[group_key].append(record)

    from .sources import verify_feed_listing

    retained_records: list[JobRecord] = []
    duplicate_groups: list[DuplicateGroup] = []
    for key in order:
        aliases = grouped[key]
        retained = max(
            aliases,
            key=lambda record: (_AUTHORITY_RANK.get(record.authority, 0), -aliases.index(record)),
        )

        combined_refs: list[EvidenceRef] = []
        seen_refs: set[tuple[str, str | None, str | None]] = set()
        for alias in aliases:
            discovery_ref = EvidenceRef(
                field="discovery_alias",
                source_url=AnyHttpUrl(str(alias.stable_url)),
                retrieved_at=alias.last_verified_at,
            )
            discovery_key = (
                discovery_ref.field,
                str(discovery_ref.source_url),
                discovery_ref.excerpt,
            )
            if discovery_key not in seen_refs:
                seen_refs.add(discovery_key)
                combined_refs.append(discovery_ref)
            for ref in alias.evidence_refs:
                ref_k = (ref.field, str(ref.source_url) if ref.source_url else None, ref.excerpt)
                if ref_k not in seen_refs:
                    seen_refs.add(ref_k)
                    combined_refs.append(ref)

        known_work_types = {alias.work_type for alias in aliases if alias.work_type is not None}
        merged_work_type = retained.work_type
        combined_flags = {flag for alias in aliases for flag in alias.uncertainty_flags}
        if len(known_work_types) == 1:
            merged_work_type = next(iter(known_work_types))
            combined_flags.discard("WORK_TYPE_UNKNOWN")
        elif len(known_work_types) > 1:
            merged_work_type = None
            combined_flags.add("WORK_TYPE_CONFLICT")
        known_posted = [alias.posted_at for alias in aliases if alias.posted_at is not None]
        if known_posted:
            combined_flags.discard("FRESHNESS_UNKNOWN")
        known_experience = [
            alias.experience
            for alias in aliases
            if "EXPERIENCE_UNKNOWN" not in alias.uncertainty_flags
        ]
        if known_experience:
            combined_flags.discard("EXPERIENCE_UNKNOWN")
        retained = JobRecord.model_validate(
            {
                **retained.model_dump(mode="python"),
                "evidence_refs": combined_refs,
                "uncertainty_flags": sorted(combined_flags),
                "work_type": merged_work_type,
                "experience": "; ".join(dict.fromkeys(known_experience))[:500]
                if known_experience
                else retained.experience,
                "first_seen_at": min(alias.first_seen_at for alias in aliases),
                "posted_at": min(known_posted, default=None),
            }
        )
        promoted = verify_feed_listing(retained)

        retained_records.append(promoted)
        if len(aliases) > 1:
            provenance: list[str] = []
            seen_urls: set[str] = set()
            for alias in aliases:
                u = str(alias.stable_url)
                if u not in seen_urls:
                    seen_urls.add(u)
                    provenance.append(u)
            duplicate_groups.append(
                DuplicateGroup(
                    retained=promoted,
                    aliases=list(aliases),
                    provenance=provenance,
                )
            )
    return DeduplicationResult(records=retained_records, duplicate_groups=duplicate_groups)
