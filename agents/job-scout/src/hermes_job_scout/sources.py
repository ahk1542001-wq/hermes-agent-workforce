"""Offline parsing and source-authority gates for Hermes web envelopes."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl, ValidationError

from .models import DiscoveryHint, ExtractedSource, RawFeedItem, SourceAuthority
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


def _parse_published_timestamp(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(val, str) and val.strip():
        val = val.strip()
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            from email.utils import parsedate_to_datetime

            try:
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (TypeError, ValueError):
                return None
    return None


def parse_himalayas_feed(
    payload: Mapping[str, Any], retrieved_at: datetime
) -> list[RawFeedItem]:
    """Parse Himalayas public JSON API response into RawFeedItem list."""
    retrieved_at = _require_aware(retrieved_at)
    envelope = _mapping(payload, "Himalayas feed envelope")
    if "data" not in envelope or not isinstance(envelope["data"], list):
        raise SourceEnvelopeError("Himalayas feed missing or invalid 'data' list")

    items: list[RawFeedItem] = []
    for raw in envelope["data"]:
        item = _mapping(raw, "Himalayas job item")
        for req in ("title", "companyName", "slug"):
            if not item.get(req) or not isinstance(item[req], str):
                raise SourceEnvelopeError(f"Himalayas job item missing required field: {req}")

        slug = _clean_text(str(item["slug"]))
        company_slug = _clean_text(str(item.get("companySlug") or ""))
        if item.get("url"):
            item_url = canonicalize_url(str(item["url"]))
        elif company_slug:
            item_url = canonicalize_url(f"https://himalayas.app/jobs/{company_slug}/{slug}")
        else:
            item_url = canonicalize_url(f"https://himalayas.app/jobs/{slug}")

        apply_link = item.get("applicationLink")
        apply_url = canonicalize_url(str(apply_link)) if apply_link else None

        desc = _clean_text(str(item.get("description") or item.get("excerpt") or ""))
        published_at = _parse_published_timestamp(item.get("pubDate"))

        try:
            items.append(
                RawFeedItem(
                    source_name="himalayas",
                    source_item_id=slug,
                    title=_clean_text(str(item["title"])),
                    company=_clean_text(str(item["companyName"])),
                    url=HttpUrl(item_url),
                    apply_url=HttpUrl(apply_url) if apply_url else None,
                    description=desc,
                    location=_clean_text(str(item.get("location") or "Worldwide")),
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    is_delayed=False,
                    authority=SourceAuthority.DISCOVERY_HINT,
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceEnvelopeError("Himalayas feed item failed validation") from exc

    return items


def parse_remoteok_json(
    payload: Sequence[Any], retrieved_at: datetime
) -> list[RawFeedItem]:
    """Parse Remote OK public API JSON list into RawFeedItem list."""
    retrieved_at = _require_aware(retrieved_at)
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, Mapping)):
        raise SourceEnvelopeError("Remote OK payload must be a sequence")
    if not payload:
        raise SourceEnvelopeError("Remote OK payload is empty")

    items: list[RawFeedItem] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise SourceEnvelopeError("Remote OK item must be a mapping")
        # Skip legal disclaimer header object
        if "legal" in raw and "position" not in raw and "id" not in raw:
            continue
        for req in ("position", "company", "id"):
            if not raw.get(req) or not isinstance(raw[req], str):
                raise SourceEnvelopeError(f"Remote OK job item missing required field: {req}")

        item_id = _clean_text(str(raw["id"]))
        slug = _clean_text(str(raw.get("slug") or item_id))
        raw_url = raw.get("url")
        if raw_url:
            item_url = canonicalize_url(str(raw_url))
        else:
            item_url = canonicalize_url(f"https://remoteok.com/remote-jobs/{slug}")

        apply_link = raw.get("apply_url")
        apply_url = canonicalize_url(str(apply_link)) if apply_link else None

        desc = _clean_text(str(raw.get("description") or ""))
        published_at = _parse_published_timestamp(raw.get("epoch") or raw.get("date"))

        try:
            items.append(
                RawFeedItem(
                    source_name="remoteok",
                    source_item_id=item_id,
                    title=_clean_text(str(raw["position"])),
                    company=_clean_text(str(raw["company"])),
                    url=HttpUrl(item_url),
                    apply_url=HttpUrl(apply_url) if apply_url else None,
                    description=desc,
                    location=_clean_text(str(raw.get("location") or "Worldwide")),
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    is_delayed=False,
                    authority=SourceAuthority.DISCOVERY_HINT,
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceEnvelopeError("Remote OK feed item failed validation") from exc

    if not items:
        raise SourceEnvelopeError("Remote OK payload contains no valid jobs")
    return items


def parse_remoteok_rss(xml_text: str, retrieved_at: datetime) -> list[RawFeedItem]:
    """Parse Remote OK RSS XML into RawFeedItem list."""
    retrieved_at = _require_aware(retrieved_at)
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise SourceEnvelopeError("Remote OK RSS text must be non-empty")
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as exc:
        raise SourceEnvelopeError("Remote OK RSS XML is malformed") from exc

    channel = root.find("channel")
    if channel is None:
        raise SourceEnvelopeError("Remote OK RSS missing channel element")

    items: list[RawFeedItem] = []
    for item_elem in channel.findall("item"):
        title_elem = item_elem.find("title")
        link_elem = item_elem.find("link")
        if title_elem is None or not title_elem.text or link_elem is None or not link_elem.text:
            raise SourceEnvelopeError("Remote OK RSS item missing title or link")

        raw_title = _clean_text(title_elem.text)
        if ": " in raw_title:
            company, position = raw_title.split(": ", 1)
        else:
            company, position = "Unknown", raw_title

        guid_elem = item_elem.find("guid")
        item_id = (
            _clean_text(guid_elem.text)
            if guid_elem is not None and guid_elem.text
            else _clean_text(link_elem.text)
        )

        desc_elem = item_elem.find("description")
        desc = _clean_text(desc_elem.text) if desc_elem is not None and desc_elem.text else ""

        pubdate_elem = item_elem.find("pubDate")
        published_at = (
            _parse_published_timestamp(pubdate_elem.text)
            if pubdate_elem is not None
            else None
        )

        item_url = canonicalize_url(link_elem.text)

        try:
            items.append(
                RawFeedItem(
                    source_name="remoteok",
                    source_item_id=item_id,
                    title=_clean_text(position),
                    company=_clean_text(company),
                    url=HttpUrl(item_url),
                    apply_url=None,
                    description=desc,
                    location="Worldwide",
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    is_delayed=False,
                    authority=SourceAuthority.DISCOVERY_HINT,
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceEnvelopeError("Remote OK RSS item failed validation") from exc

    if not items:
        raise SourceEnvelopeError("Remote OK RSS contains no items")
    return items


def parse_remotive_api(
    payload: Mapping[str, Any], retrieved_at: datetime
) -> list[RawFeedItem]:
    """Parse Remotive public API response into RawFeedItem list with delay metadata."""
    retrieved_at = _require_aware(retrieved_at)
    envelope = _mapping(payload, "Remotive feed envelope")
    if "jobs" not in envelope or not isinstance(envelope["jobs"], list):
        raise SourceEnvelopeError("Remotive feed missing or invalid 'jobs' list")
    if not envelope["jobs"]:
        raise SourceEnvelopeError("Remotive feed contains no jobs")

    items: list[RawFeedItem] = []
    for raw in envelope["jobs"]:
        item = _mapping(raw, "Remotive job item")
        for req in ("id", "title", "company_name", "url"):
            if not item.get(req):
                raise SourceEnvelopeError(f"Remotive job item missing required field: {req}")

        item_id = _clean_text(str(item["id"]))
        item_url = canonicalize_url(str(item["url"]))
        published_at = _parse_published_timestamp(item.get("publication_date"))
        desc = _clean_text(str(item.get("description") or ""))
        loc = _clean_text(str(item.get("candidate_required_location") or "Worldwide"))

        metadata = {"source_delay": "documented_24h_delay"}
        salary = item.get("salary")
        if salary and isinstance(salary, str) and salary.strip():
            metadata["salary_hint"] = _clean_text(salary)

        try:
            items.append(
                RawFeedItem(
                    source_name="remotive",
                    source_item_id=item_id,
                    title=_clean_text(str(item["title"])),
                    company=_clean_text(str(item["company_name"])),
                    url=HttpUrl(item_url),
                    apply_url=None,
                    description=desc,
                    location=loc,
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    is_delayed=True,
                    authority=SourceAuthority.DISCOVERY_HINT,
                    metadata=metadata,
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceEnvelopeError("Remotive feed item failed validation") from exc

    return items


def parse_remotive_rss(xml_text: str, retrieved_at: datetime) -> list[RawFeedItem]:
    """Parse Remotive RSS XML into RawFeedItem list with delay metadata."""
    retrieved_at = _require_aware(retrieved_at)
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise SourceEnvelopeError("Remotive RSS text must be non-empty")
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as exc:
        raise SourceEnvelopeError("Remotive RSS XML is malformed") from exc

    channel = root.find("channel")
    if channel is None:
        raise SourceEnvelopeError("Remotive RSS missing channel element")

    items: list[RawFeedItem] = []
    for item_elem in channel.findall("item"):
        title_elem = item_elem.find("title")
        link_elem = item_elem.find("link")
        if title_elem is None or not title_elem.text or link_elem is None or not link_elem.text:
            raise SourceEnvelopeError("Remotive RSS item missing title or link")

        raw_title = _clean_text(title_elem.text)
        if ": " in raw_title:
            company, position = raw_title.split(": ", 1)
        else:
            company, position = "Unknown", raw_title

        guid_elem = item_elem.find("guid")
        item_id = (
            _clean_text(guid_elem.text)
            if guid_elem is not None and guid_elem.text
            else _clean_text(link_elem.text)
        )

        desc_elem = item_elem.find("description")
        desc = _clean_text(desc_elem.text) if desc_elem is not None and desc_elem.text else ""

        pubdate_elem = item_elem.find("pubDate")
        published_at = (
            _parse_published_timestamp(pubdate_elem.text)
            if pubdate_elem is not None
            else None
        )

        item_url = canonicalize_url(link_elem.text)

        try:
            items.append(
                RawFeedItem(
                    source_name="remotive",
                    source_item_id=item_id,
                    title=_clean_text(position),
                    company=_clean_text(company),
                    url=HttpUrl(item_url),
                    apply_url=None,
                    description=desc,
                    location="Worldwide",
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    is_delayed=True,
                    authority=SourceAuthority.DISCOVERY_HINT,
                    metadata={"source_delay": "documented_24h_delay"},
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceEnvelopeError("Remotive RSS item failed validation") from exc

    if not items:
        raise SourceEnvelopeError("Remotive RSS contains no items")
    return items


def parse_weworkremotely_rss(
    xml_text: str, retrieved_at: datetime, preflight_approved: bool = False
) -> list[RawFeedItem]:
    """Parse We Work Remotely RSS XML into RawFeedItem list after preflight check."""
    retrieved_at = _require_aware(retrieved_at)
    if not preflight_approved:
        raise SourceEnvelopeError(
            "We Work Remotely RSS requires explicit preflight approval of terms, "
            "schema, and rate behavior"
        )
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise SourceEnvelopeError("We Work Remotely RSS text must be non-empty")
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as exc:
        raise SourceEnvelopeError("We Work Remotely RSS XML is malformed") from exc

    channel = root.find("channel")
    if channel is None:
        raise SourceEnvelopeError("We Work Remotely RSS missing channel element")

    items: list[RawFeedItem] = []
    for item_elem in channel.findall("item"):
        title_elem = item_elem.find("title")
        link_elem = item_elem.find("link")
        if title_elem is None or not title_elem.text or link_elem is None or not link_elem.text:
            raise SourceEnvelopeError("We Work Remotely RSS item missing title or link")

        raw_title = _clean_text(title_elem.text)
        if ": " in raw_title:
            company, position = raw_title.split(": ", 1)
        else:
            company, position = "Unknown", raw_title

        guid_elem = item_elem.find("guid")
        item_id = (
            _clean_text(guid_elem.text)
            if guid_elem is not None and guid_elem.text
            else _clean_text(link_elem.text)
        )

        desc_elem = item_elem.find("description")
        desc = _clean_text(desc_elem.text) if desc_elem is not None and desc_elem.text else ""

        pubdate_elem = item_elem.find("pubDate")
        published_at = (
            _parse_published_timestamp(pubdate_elem.text)
            if pubdate_elem is not None
            else None
        )

        item_url = canonicalize_url(link_elem.text)

        try:
            items.append(
                RawFeedItem(
                    source_name="weworkremotely",
                    source_item_id=item_id,
                    title=_clean_text(position),
                    company=_clean_text(company),
                    url=HttpUrl(item_url),
                    apply_url=None,
                    description=desc,
                    location="Worldwide",
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    is_delayed=False,
                    authority=SourceAuthority.DISCOVERY_HINT,
                )
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceEnvelopeError("We Work Remotely RSS item failed validation") from exc

    if not items:
        raise SourceEnvelopeError("We Work Remotely RSS contains no items")
    return items




