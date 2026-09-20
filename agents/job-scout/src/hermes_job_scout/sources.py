"""Offline parsing and source-authority gates for Hermes web envelopes."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl, ValidationError

from .models import DiscoveryHint, ExtractedSource, SourceAuthority
from .normalize import canonicalize_url


class SourceEnvelopeError(ValueError):
    """A copied Hermes envelope is malformed or failed closed validation."""


_SEARCH_KEYS = {"success", "data"}
_SEARCH_DATA_KEYS = {"web"}
_SEARCH_ITEM_KEYS = {"title", "url", "description", "position"}
_EXTRACT_KEYS = {"results"}
_EXTRACT_ITEM_KEYS = {"url", "title", "content", "metadata", "error"}
AUTHORITY_RULES_VERSION = "2026-09-v1"
_ATS_JOB_PATHS = {
    "boards.greenhouse.io": re.compile(r"^/[^/]+/jobs/[^/]+/?$", re.IGNORECASE),
    "jobs.lever.co": re.compile(r"^/[^/]+/[^/]+/?$", re.IGNORECASE),
    "jobs.ashbyhq.com": re.compile(r"^/[^/]+/[^/]+/?$", re.IGNORECASE),
    "myworkdayjobs.com": re.compile(r"^/.*/job/[^/]+(?:/[^/]+)?/?$", re.IGNORECASE),
    "jobs.smartrecruiters.com": re.compile(r"^/[^/]+/[^/]+/?$", re.IGNORECASE),
    "boards.jobvite.com": re.compile(r"^/[^/]+/job/[^/]+/?$", re.IGNORECASE),
    "bamboohr.com": re.compile(r"^/careers/[^/]+/?$", re.IGNORECASE),
    "icims.com": re.compile(r"^/jobs/[^/]+(?:/[^/]+)?/?$", re.IGNORECASE),
    "recruitee.com": re.compile(r"^/o/[^/]+/?$", re.IGNORECASE),
    "applytojob.com": re.compile(r"^/apply/[^/]+(?:/[^/]+)?/?$", re.IGNORECASE),
}
_VERIFIED_EMPLOYER_JOB_PATHS = {
    "example.com": re.compile(r"^/(?:jobs|roles)/[^/]+/?$", re.IGNORECASE),
}
_DISCOVERY_HOSTS = {
    "linkedin.com",
    "indeed.com",
    "wellfound.com",
    "remoteok.com",
    "remoteok.io",
    "weworkremotely.com",
    "jobstreet.com",
    "jobsdb.com",
    "jobthai.com",
    "ycombinator.com",
    "builtin.com",
    "himalayas.app",
    "remotive.com",
}


@dataclass(frozen=True, slots=True)
class SourceCatalogEntry:
    source_id: str
    name: str
    feed_type: str
    base_url: str
    initial_authority: SourceAuthority = SourceAuthority.DISCOVERY_HINT
    attribution_required: bool = True
    is_delayed: bool = False
    delay_hours: int = 0
    rate_limit_per_minute: int = 30
    preflight_required: bool = False


SOURCE_CATALOG: dict[str, SourceCatalogEntry] = {
    "himalayas": SourceCatalogEntry(
        source_id="himalayas",
        name="Himalayas",
        feed_type="json_api",
        base_url="https://himalayas.app/jobs/api",
        initial_authority=SourceAuthority.DISCOVERY_HINT,
        attribution_required=True,
        is_delayed=False,
        delay_hours=0,
        rate_limit_per_minute=20,
    ),
    "remoteok": SourceCatalogEntry(
        source_id="remoteok",
        name="Remote OK",
        feed_type="json_or_rss",
        base_url="https://remoteok.com/api",
        initial_authority=SourceAuthority.DISCOVERY_HINT,
        attribution_required=True,
        is_delayed=False,
        delay_hours=0,
        rate_limit_per_minute=10,
    ),
    "remotive": SourceCatalogEntry(
        source_id="remotive",
        name="Remotive",
        feed_type="delayed_api_or_rss",
        base_url="https://remotive.com/api/remote-jobs",
        initial_authority=SourceAuthority.DISCOVERY_HINT,
        attribution_required=True,
        is_delayed=True,
        delay_hours=24,
        rate_limit_per_minute=20,
    ),
    "weworkremotely": SourceCatalogEntry(
        source_id="weworkremotely",
        name="We Work Remotely",
        feed_type="conditional_rss",
        base_url="https://weworkremotely.com/categories/remote-programming-jobs.rss",
        initial_authority=SourceAuthority.DISCOVERY_HINT,
        attribution_required=True,
        is_delayed=False,
        delay_hours=0,
        rate_limit_per_minute=10,
        preflight_required=True,
    ),
}


def get_source_catalog_entry(source_id: str) -> SourceCatalogEntry:
    if source_id not in SOURCE_CATALOG:
        raise KeyError(f"Unknown source ID in catalog: {source_id}")
    return SOURCE_CATALOG[source_id]


def _clean_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _require_aware(value: datetime | None) -> datetime:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise SourceEnvelopeError("retrieved_at must be a timezone-aware datetime")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceEnvelopeError(f"{label} must be a mapping")
    return value


def _exact_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    if set(value) != allowed:
        raise SourceEnvelopeError(f"{label} has an unsupported or missing field")


def parse_search_envelope(
    payload: Mapping[str, Any], provider: str, query: str, retrieved_at: datetime
) -> list[DiscoveryHint]:
    """Parse Hermes ``web_search_tool``'s ``success/data.web`` envelope."""

    retrieved_at = _require_aware(retrieved_at)
    envelope = _mapping(payload, "search envelope")
    _exact_keys(envelope, _SEARCH_KEYS, "search envelope")
    if type(envelope["success"]) is not bool or envelope["success"] is not True:
        raise SourceEnvelopeError("search provider did not return success")
    data = _mapping(envelope["data"], "search data")
    _exact_keys(data, _SEARCH_DATA_KEYS, "search data")
    if not isinstance(data["web"], list):
        raise SourceEnvelopeError("search data.web must be a list")
    hints: list[DiscoveryHint] = []
    for item in data["web"]:
        result = _mapping(item, "search result")
        _exact_keys(result, _SEARCH_ITEM_KEYS, "search result")
        try:
            hints.append(
                DiscoveryHint(
                    provider=provider,
                    query=query,
                    title=_clean_text(result["title"]),
                    url=HttpUrl(canonicalize_url(result["url"])),
                    description=_clean_text(result["description"]),
                    position=result["position"],
                    retrieved_at=retrieved_at,
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceEnvelopeError("search result failed validation") from exc
    return hints


def parse_extract_envelope(
    payload: Mapping[str, Any], provider: str, retrieved_at: datetime
) -> list[ExtractedSource]:
    """Parse Hermes ``web_extract_tool``'s ``results`` envelope."""

    retrieved_at = _require_aware(retrieved_at)
    envelope = _mapping(payload, "extract envelope")
    _exact_keys(envelope, _EXTRACT_KEYS, "extract envelope")
    if not isinstance(envelope["results"], list):
        raise SourceEnvelopeError("extract results must be a list")
    sources: list[ExtractedSource] = []
    for item in envelope["results"]:
        result = _mapping(item, "extract result")
        keys = set(result)
        if not {"url", "title", "content"}.issubset(keys) or not keys.issubset(_EXTRACT_ITEM_KEYS):
            raise SourceEnvelopeError("extract result has an unsupported or missing field")
        if result.get("error"):
            raise SourceEnvelopeError("extract result contains a provider error")
        content = _clean_text(result["content"])
        try:
            sources.append(
                ExtractedSource(
                    provider=provider,
                    url=HttpUrl(canonicalize_url(result["url"])),
                    title=_clean_text(result["title"]),
                    content=content,
                    retrieved_at=retrieved_at,
                    content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    metadata=result.get("metadata", {}),
                    authority=classify_source_authority(result["url"]),
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceEnvelopeError("extract result failed validation") from exc
    return sources


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _is_ats_job_url(host: str, path: str) -> bool:
    return any(
        _host_matches(host, domain) and pattern.fullmatch(path)
        for domain, pattern in _ATS_JOB_PATHS.items()
    )


def _is_verified_employer_job_url(host: str, path: str) -> bool:
    return any(
        _host_matches(host, domain) and pattern.fullmatch(path)
        for domain, pattern in _VERIFIED_EMPLOYER_JOB_PATHS.items()
    )


def classify_source_authority(url: str) -> SourceAuthority:
    """Classify a URL using conservative, versioned public-host rules."""

    try:
        canonical = canonicalize_url(url)
        parts = urlsplit(canonical)
        host = (parts.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError) as exc:
        raise SourceEnvelopeError("source URL is malformed") from exc
    if any(_host_matches(host, domain) for domain in _DISCOVERY_HOSTS):
        return SourceAuthority.DISCOVERY_HINT
    if _is_ats_job_url(host, parts.path):
        return SourceAuthority.ATS
    if _is_verified_employer_job_url(host, parts.path):
        return SourceAuthority.OFFICIAL
    return SourceAuthority.NEEDS_VERIFICATION
