"""Site audit engine: crawl a live website and produce AEO/SEO findings.

Fetches the homepage plus robots.txt, sitemap.xml and llms.txt, parses the
HTML with the stdlib HTMLParser (no extra dependencies), and derives findings
in the categories declared by ``audit_findings.category``:

    schema | meta | robots | llms_txt | sitemap | speed | entity

Findings are scored (100 minus severity-weighted deductions, floored at 0)
and persisted into ``audits`` / ``audit_findings`` / ``site_pages`` by the
routes that call :func:`run_site_audit`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
from services.api.app.logging import get_logger

logger = get_logger(__name__)

# Severity deduction weights for the 0-100 score.
_SEVERITY_PENALTY = {"critical": 30, "high": 15, "medium": 7, "low": 3}

# Cap sitemap-derived page fetches so one audit can't crawl an unbounded site.
MAX_PAGES = 20
FETCH_TIMEOUT = 15.0


@dataclass
class Finding:
    category: str  # schema | meta | robots | llms_txt | sitemap | speed | entity
    severity: str  # critical | high | medium | low
    rule: str
    detail: str
    url: str | None = None
    fix_owner: str = "team"  # team | client_dev


@dataclass
class PageRecord:
    url: str
    status_code: int | None = None
    title: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    jsonld: list[Any] = field(default_factory=list)
    word_count: int | None = None
    content_hash: str | None = None
    load_ms: int | None = None


@dataclass
class AuditResult:
    score: float
    findings: list[Finding]
    pages: list[PageRecord]
    summary: dict[str, Any]


class _HtmlInsights(HTMLParser):
    """Extract the tags an AEO/SEO audit cares about from one HTML document."""

    _SKIP: ClassVar[set[str]] = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.description: str | None = None
        self.canonical: str | None = None
        self.og_title: str | None = None
        self.h1_count = 0
        self.lang: str | None = None
        self.jsonld: list[Any] = []
        self._in_title = False
        self._in_h1 = False
        self._skip_depth = 0
        self._jsonld_buf: list[str] = []
        self._in_jsonld = False
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        at = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = at.get("lang") or None
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (at.get("name") or at.get("property") or "").lower()
            content = at.get("content") or ""
            if name == "description" and content:
                self.description = content
            elif name in ("og:title", "twitter:title") and content:
                self.og_title = content
        elif tag == "link" and "canonical" in (at.get("rel") or "").lower():
            self.canonical = at.get("href") or None
        elif tag == "h1":
            self.h1_count += 1
            self._in_h1 = True
        elif tag == "script":
            if (at.get("type") or "").lower() == "application/ld+json":
                self._in_jsonld = True
                self._jsonld_buf = []
            self._skip_depth += 1
        elif tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "script":
            if self._in_jsonld:
                raw = "".join(self._jsonld_buf).strip()
                if raw:
                    try:
                        parsed = json.loads(raw)
                        self.jsonld.extend(parsed if isinstance(parsed, list) else [parsed])
                    except json.JSONDecodeError:
                        self.jsonld.append({"_parse_error": True, "_raw": raw[:500]})
                self._in_jsonld = False
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._in_jsonld and self._skip_depth <= 1:
            self._jsonld_buf.append(data)
            return
        if self._skip_depth > 0:
            return
        if self._in_title and self.title is None:
            self.title = data.strip()
        self._text_parts.append(data)

    @property
    def word_count(self) -> int:
        text = " ".join(self._text_parts)
        return len(re.findall(r"\S+", text))

    @property
    def h1_text(self) -> str:
        # Approximate: full visible text serves for entity checks below.
        return " ".join(self._text_parts)


def parse_html(html: str) -> _HtmlInsights:
    insights = _HtmlInsights()
    insights.feed(html)
    return insights


def _extract_schema_types(jsonld: list[Any]) -> set[str]:
    types: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.add(t)
            elif isinstance(t, list):
                types.update(str(x) for x in t)
            graph = node.get("@graph")
            if isinstance(graph, list):
                walk(graph)

    walk(jsonld)
    return types


def _score(findings: list[Finding]) -> float:
    deductions = sum(_SEVERITY_PENALTY.get(f.severity, 0) for f in findings)
    return float(max(0, 100 - deductions))


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[int | None, str, int]:
    """Return (status_code, text, elapsed_ms). status is None on network error."""
    started = time.monotonic()
    try:
        resp = await client.get(url)
        elapsed = int((time.monotonic() - started) * 1000)
        # Only parse text-ish bodies (skip accidental binary downloads).
        ctype = resp.headers.get("content-type", "")
        if ctype and not any(t in ctype for t in ("html", "xml", "text", "json")):
            return resp.status_code, "", elapsed
        raw = resp.content
        # Sitemap children are often served as raw gzip (.xml.gz) without a
        # Content-Encoding header — decompress manually.
        if raw[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                return resp.status_code, "", elapsed
        return resp.status_code, raw.decode("utf-8", "replace"), elapsed
    except (httpx.HTTPError, UnicodeDecodeError) as exc:
        logger.warning("audit_fetch_failed", url=url, error=str(exc))
        return None, "", 0


def _audit_home_insights(url: str, html: str, findings: list[Finding], load_ms: int) -> None:
    ins = parse_html(html)

    # ── meta ──
    if not ins.title:
        findings.append(Finding("meta", "critical", "missing_title", "Page has no <title> tag", url))
    elif len(ins.title) > 65:
        findings.append(Finding("meta", "low", "title_too_long", f"Title is {len(ins.title)} chars (aim ≤65)", url))
    if not ins.description:
        findings.append(Finding("meta", "high", "missing_description", "Page has no meta description", url))
    elif len(ins.description) > 165:
        findings.append(Finding("meta", "low", "description_too_long", f"Description is {len(ins.description)} chars", url))
    if not ins.canonical:
        findings.append(Finding("meta", "medium", "missing_canonical", "No <link rel=canonical>", url))
    if not ins.og_title:
        findings.append(Finding("meta", "medium", "missing_og_title", "No og:title (social/AI previews)", url, fix_owner="client_dev"))
    if not ins.lang:
        findings.append(Finding("meta", "low", "missing_lang_attr", "<html> has no lang attribute", url, fix_owner="client_dev"))

    # ── schema ──
    if not ins.jsonld:
        findings.append(Finding("schema", "high", "missing_json_ld", "No JSON-LD structured data", url))
    else:
        types = _extract_schema_types(ins.jsonld)
        if not types & {"Organization", "LocalBusiness", "Corporation", "Person"}:
            findings.append(Finding("schema", "medium", "missing_org_schema", f"JSON-LD lacks an entity type (found: {sorted(types) or 'none'})", url))
        if "FAQPage" not in types and "HowTo" not in types:
            findings.append(Finding("schema", "low", "missing_faq_schema", "No FAQPage/HowTo schema (helps answer-engine citation)", url))

    # ── entity / content ──
    if ins.h1_count == 0:
        findings.append(Finding("entity", "medium", "missing_h1", "Page has no <h1>", url))
    elif ins.h1_count > 1:
        findings.append(Finding("entity", "low", "multiple_h1", f"Page has {ins.h1_count} <h1> tags", url, fix_owner="client_dev"))
    if ins.word_count < 250:
        findings.append(Finding("entity", "medium", "thin_content", f"Only ~{ins.word_count} visible words (<250)", url))

    # ── speed (single-page proxy: full load time) ──
    if load_ms > 3000:
        findings.append(Finding("speed", "high", "slow_response", f"Homepage took {load_ms}ms to load", url))
    elif load_ms > 1500:
        findings.append(Finding("speed", "medium", "slow_response", f"Homepage took {load_ms}ms to load", url))


def _audit_site_files(
    base: str,
    robots_status: int | None,
    robots_text: str,
    sitemap_status: int | None,
    sitemap_text: str,
    llms_status: int | None,
    findings: list[Finding],
) -> int:
    """Audit robots/sitemap/llms.txt; return number of sitemap URLs found."""
    # ── robots ──
    if robots_status != 200:
        findings.append(Finding("robots", "high", "missing_robots", "robots.txt missing or unreachable", f"{base}/robots.txt"))
    else:
        disallow_all = any(
            line.strip().lower() == "disallow: /"
            for line in robots_text.splitlines()
            if not line.strip().lower().startswith(("user-agent", "#"))
        )
        if disallow_all:
            findings.append(Finding("robots", "critical", "robots_disallow_all", "robots.txt disallows all crawlers", f"{base}/robots.txt"))
        if "sitemap:" not in robots_text.lower():
            findings.append(Finding("robots", "low", "robots_missing_sitemap", "robots.txt declares no Sitemap", f"{base}/robots.txt", fix_owner="client_dev"))

    # ── sitemap ──
    urls: list[str] = []
    if sitemap_status != 200:
        findings.append(Finding("sitemap", "high", "missing_sitemap", "sitemap.xml missing or unreachable", f"{base}/sitemap.xml"))
    else:
        urls = [m for m in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_text) if m.startswith("http")]
        if not urls:
            findings.append(Finding("sitemap", "medium", "empty_sitemap", "sitemap.xml contains no <loc> URLs", f"{base}/sitemap.xml"))

    # ── llms.txt (AEO-specific) ──
    if llms_status != 200:
        findings.append(Finding("llms_txt", "medium", "missing_llms_txt", "llms.txt absent — no LLM-oriented site guide", f"{base}/llms.txt", fix_owner="client_dev"))

    return len(urls)


async def run_site_audit(base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> AuditResult:
    """Fetch a live site, derive findings, and return the scored result.

    Callers persist the result; this function has no database access so it
    stays unit-testable — pass an ``httpx.MockTransport`` as ``transport``.
    """
    base = base_url.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    host = urlsplit(base).netloc

    findings: list[Finding] = []
    pages: list[PageRecord] = []

    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT, follow_redirects=True, transport=transport,
        headers={"User-Agent": "FootnoteAuditBot/0.1"},
    ) as client:
        # Homepage
        home_status, home_html, home_ms = await _fetch(client, base)
        if home_status is None or home_status >= 400:
            findings.append(Finding("meta", "critical", "unreachable_homepage", f"Homepage returned {home_status}", base))
        elif home_status == 200:
            _audit_home_insights(base, home_html, findings, home_ms)
            ins = parse_html(home_html)
            pages.append(
                PageRecord(
                    url=base,
                    status_code=home_status,
                    title=ins.title,
                    meta={
                        "description": ins.description,
                        "canonical": ins.canonical,
                        "og_title": ins.og_title,
                        "lang": ins.lang,
                        "h1_count": ins.h1_count,
                    },
                    jsonld=ins.jsonld,
                    word_count=ins.word_count,
                    content_hash=hashlib.sha256(home_html.encode("utf-8", "ignore")).hexdigest(),
                    load_ms=home_ms,
                )
            )

        # Site files
        robots_status, robots_text, _ = await _fetch(client, f"{base}/robots.txt")
        sitemap_status, sitemap_text, _ = await _fetch(client, f"{base}/sitemap.xml")
        llms_status, _, _ = await _fetch(client, f"{base}/llms.txt")
        sitemap_url_count = _audit_site_files(base, robots_status, robots_text, sitemap_status, sitemap_text, llms_status, findings)

        # Resolve page URLs; if the sitemap is an index (common: .xml.gz
        # children), follow one bounded level of child sitemaps.
        page_candidates: list[str] = []
        if sitemap_status == 200:
            page_candidates.extend(_page_urls(sitemap_text))
            if "<sitemapindex" in sitemap_text:
                children = [loc for loc in _all_locs(sitemap_text) if loc.endswith((".xml", ".xml.gz"))][:3]
                for child in children:
                    status, text, _ = await _fetch(client, child)
                    if status == 200:
                        page_candidates.extend(_page_urls(text))

        if page_candidates:
            sample = [
                u for u in dict.fromkeys(page_candidates)
                if u.rstrip("/") != base.rstrip("/")
            ][:MAX_PAGES]
            for url in sample:
                status, html, ms = await _fetch(client, url)
                if status != 200:
                    continue
                page_ins = parse_html(html)
                pages.append(
                    PageRecord(
                        url=url,
                        status_code=status,
                        title=page_ins.title,
                        meta={
                            "description": page_ins.description,
                            "canonical": page_ins.canonical,
                            "og_title": page_ins.og_title,
                            "lang": page_ins.lang,
                            "h1_count": page_ins.h1_count,
                        },
                        jsonld=page_ins.jsonld,
                        word_count=page_ins.word_count,
                        content_hash=hashlib.sha256(html.encode("utf-8", "ignore")).hexdigest(),
                        load_ms=ms,
                    )
                )
            # Aggregate finding when most sampled pages lack descriptions.
            described = sum(1 for p in pages if p.meta.get("description"))
            if len(pages) >= 3 and described < len(pages) / 2:
                findings.append(
                    Finding("meta", "medium", "site_wide_missing_descriptions",
                            f"Only {described}/{len(pages)} sampled pages have meta descriptions", base)
                )

    score = _score(findings)
    summary = {
        "base_url": base,
        "host": host,
        "pages_crawled": len(pages),
        "page_urls": [p.url for p in pages],
        "sitemap_urls": sitemap_url_count,
        "findings_by_severity": {
            sev: sum(1 for f in findings if f.severity == sev) for sev in ("critical", "high", "medium", "low")
        },
        "homepage_ms": home_ms,
    }
    logger.info("site_audit_completed", host=host, score=score, findings=len(findings), pages=len(pages))
    return AuditResult(score=score, findings=findings, pages=pages, summary=summary)


# Suffixes that are definitely not crawlable HTML pages (assets, child
# sitemaps like .xml/.xml.gz, feeds, docs...).
_NON_HTML_SUFFIXES = (
    ".xml", ".xml.gz", ".gz", ".json", ".txt", ".pdf", ".zip",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".mp4", ".mp3",
)


def _looks_like_html(url: str) -> bool:
    path = urlsplit(url).path.lower()
    # Empty path = site root, still HTML.
    return not path.endswith(_NON_HTML_SUFFIXES)


def _all_locs(sitemap_text: str) -> list[str]:
    return [m.strip() for m in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_text)]


def _page_urls(sitemap_text: str) -> list[str]:
    """Page URLs from a sitemap (skips child sitemaps and non-HTML assets)."""
    return [u for u in _all_locs(sitemap_text) if u.startswith("http") and _looks_like_html(u)]
