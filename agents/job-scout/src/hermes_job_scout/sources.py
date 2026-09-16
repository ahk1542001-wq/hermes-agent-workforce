"""Offline parsing and source-authority gates for Hermes web envelopes."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping
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
_ATS_HOSTS = {
    "boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "boards.jobvite.com",
    "jobs.bamboohr.com",
    "icims.com",
    "recruitee.com",
    "applytojob.com",
}
_VERIFIED_EMPLOYER_DOMAINS = {"example.com"}
_DISCOVERY_HOSTS = {
    "linkedin.com",
    "indeed.com",
    "wellfound.com",
    "remoteok.com",
    "weworkremotely.com",
    "jobstreet.com",
    "jobsdb.com",
    "jobthai.com",
    "ycombinator.com",
    "builtin.com",
}


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


def classify_source_authority(url: str) -> SourceAuthority:
    """Classify a URL using conservative, versioned public-host rules."""

    try:
        canonical = canonicalize_url(url)
        host = (urlsplit(canonical).hostname or "").lower().rstrip(".")
    except (TypeError, ValueError) as exc:
        raise SourceEnvelopeError("source URL is malformed") from exc
    if any(_host_matches(host, domain) for domain in _DISCOVERY_HOSTS):
        return SourceAuthority.DISCOVERY_HINT
    if any(_host_matches(host, domain) for domain in _ATS_HOSTS):
        return SourceAuthority.ATS
    if any(_host_matches(host, domain) for domain in _VERIFIED_EMPLOYER_DOMAINS):
        return SourceAuthority.OFFICIAL
    return SourceAuthority.NEEDS_VERIFICATION
