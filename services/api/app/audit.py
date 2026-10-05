"""Site audit engine: crawl a live website and produce AEO/SEO findings.

Fetches the homepage plus robots.txt, sitemap.xml and llms.txt, parses the
HTML with the stdlib HTMLParser (no extra dependencies), and derives findings
in the categories declared by ``audit_findings.category``:

    schema | meta | robots | llms_txt | sitemap | speed | entity

Milestone 3 additions:

- **robots.txt rules per AI crawler** (GPTBot, OAI-SearchBot, ChatGPT-User,
  ClaudeBot, PerplexityBot, Google-Extended, plus secondary agents): groups are
  parsed, matched against ``/`` with longest-match-wins semantics, and recorded
  per bot in ``summary["robots_rules"]``.
- **JSON-LD validity** (parse errors, missing @context/@type, Organization
  completeness, ``sameAs``) and **entity drift** against the client's brand
  name/aliases when ``entity_names`` is supplied.
- **PageSpeed Insights** (mobile Lighthouse scores for the homepage) when a
  ``pagespeed_key`` is provided; without one the summary records an explicit
  ``{"status": "not_configured"}`` instead of guessing.
- Every finding carries a `suggested_fix` (rule -> remediation text) so the
  dev brief export is deterministic.

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
from datetime import UTC, datetime
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
PAGESPEED_TIMEOUT = 45.0
PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# ── AI crawlers ──────────────────────────────────────────────────────────────
# Primary agents decide whether answer engines can read and cite the site.
PRIMARY_AI_BOTS: tuple[str, ...] = (
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "PerplexityBot",
    "Google-Extended",
)
# Secondary agents: relevant for training/model pipelines that surface brands.
SECONDARY_AI_BOTS: tuple[str, ...] = (
    "CCBot",
    "Bytespider",
    "meta-externalagent",
    "Applebot-Extended",
    "Amazonbot",
    "cohere-ai",
)

# ── Suggested fixes (rule -> PR-ready remediation text for the dev brief) ────
SUGGESTED_FIXES: dict[str, str] = {
    "missing_title": "Add a unique <title> (50-60 chars) naming the entity and the primary service.",
    "title_too_long": "Trim the <title> to ≤65 characters; put the brand name last.",
    "missing_description": "Add a 140-165 char meta description with the offer, audience and a proof point.",
    "description_too_long": "Trim the meta description to ≤165 characters so engines don't truncate it.",
    "missing_canonical": "Add <link rel=\"canonical\" href=\"…\"> pointing at the preferred absolute URL.",
    "missing_og_title": "Add og:title and og:description so shares and AI previews render correctly.",
    "missing_lang_attr": "Set lang on the <html> element (e.g. <html lang=\"en\">).",
    "missing_json_ld": "Add JSON-LD (Organization at minimum) describing the entity, services and sameAs profiles.",
    "missing_org_schema": "Add an Organization/LocalBusiness JSON-LD node with name, url, logo and contactPoint.",
    "missing_faq_schema": "Add FAQPage or HowTo JSON-LD for the questions this page answers.",
    "missing_h1": "Add exactly one <h1> that states the entity and the page topic.",
    "multiple_h1": "Keep one <h1> per page; demote the rest to <h2>/<h3>.",
    "thin_content": "Expand to at least 250 words of answer-first content with concrete claims and sources.",
    "slow_response": "Investigate server response time / TTFB; aim under 1.5s from the audited region.",
    "unreachable_homepage": "Fix the homepage — it must return HTTP 200 to be crawlable at all.",
    "missing_robots": "Publish /robots.txt with User-agent groups and a Sitemap directive.",
    "robots_disallow_all": "Remove the site-wide Disallow: / (or scope it to staging paths only).",
    "robots_missing_sitemap": "Add a Sitemap: line to robots.txt pointing at the XML sitemap.",
    "ai_bot_blocked": "Unblock the named AI crawlers with an explicit Allow block in robots.txt.",
    "missing_sitemap": "Publish /sitemap.xml listing canonical pages with lastmod dates.",
    "empty_sitemap": "Populate the sitemap with <loc> entries for every canonical page.",
    "site_wide_missing_descriptions": "Add unique meta descriptions across page templates.",
    "missing_llms_txt": "Add /llms.txt summarising the entity, key pages and canonical answers for LLMs.",
    "pagespeed_score_low": "Work through the Lighthouse opportunities in the PageSpeed report (images, JS, fonts).",
    "slow_lcp": "Improve LCP: compress/right-size the hero image, preload it, and reduce render-blocking JS/CSS.",
    "high_cls": "Reserve space for images/ads/embeds (width/height, aspect-ratio) to stop layout shift.",
    "jsonld_parse_error": "Fix the JSON syntax inside the application/ld+json block — engines discard invalid JSON-LD.",
    "jsonld_missing_context": "Add \"@context\": \"https://schema.org\" to the JSON-LD root.",
    "jsonld_missing_type": "Give every JSON-LD node an \"@type\" so engines can interpret it.",
    "organization_missing_name": "Add the legal/trading name to the Organization JSON-LD node.",
    "organization_missing_sameAs": "Add sameAs URLs (LinkedIn, Crunchbase, Wikipedia…) so engines disambiguate the entity.",
    "entity_name_mismatch": "Align the Organization JSON-LD name with the brand name used on the site and profiles.",
}


def suggested_fix(rule: str) -> str:
    """PR-ready remediation text for a rule code (empty when unknown)."""
    return SUGGESTED_FIXES.get(rule, "")


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


# ── robots.txt parsing (FR-16) ────────────────────────────────────────────────


@dataclass
class RobotsGroup:
    """One robots.txt user-agent group: agents plus their allow/disallow rules."""

    agents: list[str]
    rules: list[tuple[str, str]]  # (directive, path) with directive allow|disallow


@dataclass
class RobotsBotRule:
    """Effective decision for one AI crawler against path ``/``."""

    bot: str
    group: str  # matched user-agent (bot name or "*"), "none" when no group
    allowed: bool
    rule: str | None  # matched rule text, e.g. "Disallow: /blog"

    def as_dict(self) -> dict[str, Any]:
        return {"bot": self.bot, "group": self.group, "allowed": self.allowed, "rule": self.rule}


def parse_robots(text: str) -> list[RobotsGroup]:
    """Parse robots.txt into user-agent groups (comments/blanks ignored)."""
    groups: list[RobotsGroup] = []
    current: RobotsGroup | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        directive, _, value = line.partition(":")
        directive = directive.strip().lower()
        value = value.strip()
        if directive == "user-agent":
            if current is None or current.rules:
                # A new user-agent line after rules starts a new group; repeated
                # user-agent lines before any rule extend the current group.
                current = RobotsGroup(agents=[], rules=[])
                groups.append(current)
            current.agents.append(value)
        elif directive in ("allow", "disallow") and current is not None:
            current.rules.append((directive, value))
    return groups


def _group_for_bot(groups: list[RobotsGroup], bot: str) -> tuple[RobotsGroup | None, str]:
    """Exact (case-insensitive) agent match wins; then the ``*`` group."""
    for group in groups:
        if any(agent.lower() == bot.lower() for agent in group.agents):
            return group, bot
    for group in groups:
        if any(agent.strip() == "*" for agent in group.agents):
            return group, "*"
    return None, "none"


def _pattern_matches(path: str, pattern: str) -> bool:
    """robots.txt path pattern match (``*`` wildcard, ``$`` end anchor)."""
    if not pattern:
        return False
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "^" + re.escape(body).replace(r"\*", ".*") + ("$" if anchored else "")
    return re.match(regex, path, re.IGNORECASE) is not None


def _effective_rule(group: RobotsGroup | None, path: str = "/") -> tuple[bool, str | None]:
    """Longest match wins; on equal length Allow beats Disallow (RFC 9309)."""
    if group is None or not group.rules:
        return True, None
    matches: list[tuple[int, str, str]] = []
    for directive, pattern in group.rules:
        if _pattern_matches(path, pattern):
            matches.append((len(pattern.rstrip("$")), directive, pattern))
    if not matches:
        return True, None
    longest = max(length for length, _d, _p in matches)
    top = [(d, p) for length, d, p in matches if length == longest]
    for directive, pattern in top:
        if directive == "allow":
            return True, f"Allow: {pattern}"
    directive, pattern = top[0]
    return False, f"Disallow: {pattern}"


def effective_bot_rules(groups: list[RobotsGroup]) -> list[RobotsBotRule]:
    """Effective ``/`` decision for every tracked AI crawler."""
    rules: list[RobotsBotRule] = []
    for bot in (*PRIMARY_AI_BOTS, *SECONDARY_AI_BOTS):
        group, matched = _group_for_bot(groups, bot)
        allowed, rule = _effective_rule(group)
        rules.append(RobotsBotRule(bot=bot, group=matched, allowed=allowed, rule=rule))
    return rules


def _audit_robots(
    base: str,
    robots_status: int | None,
    robots_text: str,
    findings: list[Finding],
) -> list[dict[str, Any]]:
    """robots.txt: reachability, site-wide blocks and per-AI-bot rules."""
    if robots_status != 200:
        findings.append(Finding("robots", "high", "missing_robots", "robots.txt missing or unreachable", f"{base}/robots.txt"))
        return []

    groups = parse_robots(robots_text)
    # The `*` group decides for everyone without a specific group.
    global_group, _ = _group_for_bot(groups, "__none__")
    global_allowed, _ = _effective_rule(global_group)
    if not global_allowed:
        findings.append(Finding("robots", "critical", "robots_disallow_all", "robots.txt disallows all crawlers", f"{base}/robots.txt"))
    else:
        bot_rules = effective_bot_rules(groups)
        blocked = [r for r in bot_rules if r.bot in PRIMARY_AI_BOTS and not r.allowed]
        if blocked:
            all_blocked = len(blocked) == len(PRIMARY_AI_BOTS)
            names = ", ".join(r.bot for r in blocked)
            findings.append(
                Finding(
                    "robots",
                    "critical" if all_blocked else "high",
                    "ai_bot_blocked",
                    f"AI crawlers blocked: {names}",
                    f"{base}/robots.txt",
                )
            )

    if "sitemap:" not in robots_text.lower():
        findings.append(Finding("robots", "low", "robots_missing_sitemap", "robots.txt declares no Sitemap", f"{base}/robots.txt", fix_owner="client_dev"))

    return [rule.as_dict() for rule in effective_bot_rules(groups)]


# ── JSON-LD validity + entity drift (FR-16/17) ───────────────────────────────

_ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "Person", "EducationalOrganization"}


def _iter_nodes(node: Any) -> list[dict[str, Any]]:
    """Every dict node in a JSON-LD tree (including @graph children)."""
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_iter_nodes(item))
    elif isinstance(node, dict):
        found.append(node)
        graph = node.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                found.extend(_iter_nodes(item))
    return found


def _name_matches(found: str, expected: list[str]) -> bool:
    """Loose brand-name match: case/punctuation-insensitive substring either way."""
    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9 ]+", " ", value.casefold()).strip()

    f = norm(found)
    return any(e and (e in f or f in e) for e in (norm(name) for name in expected))


def validate_jsonld(jsonld: list[Any], expected_names: list[str] | None = None) -> list[tuple[str, str, str]]:
    """Return (rule, severity, detail) issues for one page's JSON-LD blocks.

    Checks validity (parse errors, @context, @type), Organization completeness
    (name, sameAs) and — when ``expected_names`` is supplied — entity drift
    between the JSON-LD Organization name and the client's brand/aliases.
    """
    issues: list[tuple[str, str, str]] = []
    names = [n for n in (expected_names or []) if n.strip()]

    errors = [n for n in jsonld if isinstance(n, dict) and n.get("_parse_error")]
    if errors:
        raw = str(errors[0].get("_raw", ""))[:120].replace("\n", " ")
        more = f" (+{len(errors) - 1} more blocks)" if len(errors) > 1 else ""
        issues.append(("jsonld_parse_error", "high", f"Invalid JSON-LD: {raw}{more}"))

    top_nodes = [n for n in jsonld if isinstance(n, dict) and not n.get("_parse_error")]
    if top_nodes and not any("@context" in n for n in top_nodes):
        issues.append(("jsonld_missing_context", "medium", "JSON-LD has no @context (schema.org)"))

    all_nodes: list[dict[str, Any]] = []
    for node in top_nodes:
        all_nodes.extend(_iter_nodes(node))

    if any("@type" not in n and "@graph" not in n for n in all_nodes):
        issues.append(("jsonld_missing_type", "medium", "A JSON-LD node has no @type"))

    name_missing = name_mismatch = same_as_missing = False
    for node in all_nodes:
        types = node.get("@type")
        type_set = {types} if isinstance(types, str) else set(types or [])
        if not type_set & _ORG_TYPES:
            continue
        name = node.get("name")
        if not isinstance(name, str) or not name.strip():
            name_missing = True
        elif names and not _name_matches(name, names) and not name_mismatch:
            name_mismatch = True
            issues.append(
                ("entity_name_mismatch", "medium",
                 f"JSON-LD name '{name}' does not match the brand ({', '.join(names[:3])}) — possible entity drift")
            )
        same_as = node.get("sameAs")
        if not same_as or (isinstance(same_as, list) and not any(same_as)):
            same_as_missing = True

    if name_missing:
        issues.append(("organization_missing_name", "medium", "Organization JSON-LD has no name"))
    if same_as_missing:
        issues.append(("organization_missing_sameAs", "low", "Organization JSON-LD has no sameAs profiles"))
    return issues


# ── Scoring / fetching ────────────────────────────────────────────────────────


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


async def _fetch_pagespeed(
    client: httpx.AsyncClient, base: str, api_key: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Mobile Lighthouse summary via the PageSpeed Insights API.

    Returns ``(payload, None)`` on success and ``(None, reason)`` on failure;
    without an API key the caller records ``not_configured`` instead of calling
    (the keyless endpoint shares an anonymous quota and returns 429).
    """
    try:
        resp = await client.get(
            PAGESPEED_ENDPOINT,
            params={"url": base, "strategy": "mobile", "category": "performance", "key": api_key},
            timeout=PAGESPEED_TIMEOUT,
        )
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:160]}"
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"

    lighthouse = data.get("lighthouseResult") or {}
    audits = lighthouse.get("audits") or {}
    categories = lighthouse.get("categories") or {}

    def _num(name: str) -> float | None:
        value = (audits.get(name) or {}).get("numericValue")
        return float(value) if isinstance(value, (int, float)) else None

    perf = (categories.get("performance") or {}).get("score")
    cls = _num("cumulative-layout-shift")
    payload: dict[str, Any] = {
        "status": "ok",
        "strategy": "mobile",
        "performance_score": round(float(perf) * 100) if isinstance(perf, (int, float)) else None,
        "lcp_ms": int(_num("largest-contentful-paint") or 0) or None,
        "cls": round(cls, 3) if cls is not None else None,
        "tbt_ms": int(_num("total-blocking-time") or 0) or None,
        "fcp_ms": int(_num("first-contentful-paint") or 0) or None,
        "si_ms": int(_num("speed-index") or 0) or None,
        "final_url": str(lighthouse.get("finalUrl") or base),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    return payload, None


def _speed_findings(payload: dict[str, Any], base: str, findings: list[Finding]) -> None:
    """Findings from a successful PageSpeed payload (Lighthouse thresholds)."""
    score = payload.get("performance_score")
    if isinstance(score, int):
        if score < 50:
            findings.append(Finding("speed", "high", "pagespeed_score_low", f"Lighthouse mobile performance {score}/100", base, fix_owner="client_dev"))
        elif score < 90:
            findings.append(Finding("speed", "medium", "pagespeed_score_low", f"Lighthouse mobile performance {score}/100", base, fix_owner="client_dev"))

    lcp = payload.get("lcp_ms")
    if isinstance(lcp, int):
        if lcp > 4000:
            findings.append(Finding("speed", "high", "slow_lcp", f"LCP {round(lcp / 1000, 1)}s on mobile (>4s)", base, fix_owner="client_dev"))
        elif lcp > 2500:
            findings.append(Finding("speed", "medium", "slow_lcp", f"LCP {round(lcp / 1000, 1)}s on mobile (>2.5s)", base, fix_owner="client_dev"))

    cls = payload.get("cls")
    if isinstance(cls, (int, float)):
        if cls > 0.25:
            findings.append(Finding("speed", "medium", "high_cls", f"CLS {cls} on mobile (>0.25)", base, fix_owner="client_dev"))
        elif cls > 0.1:
            findings.append(Finding("speed", "low", "high_cls", f"CLS {cls} on mobile (>0.1)", base, fix_owner="client_dev"))


def _audit_home_insights(
    url: str,
    html: str,
    findings: list[Finding],
    load_ms: int,
    expected_names: list[str] | None = None,
) -> None:
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
        if not types & _ORG_TYPES:
            findings.append(Finding("schema", "medium", "missing_org_schema", f"JSON-LD lacks an entity type (found: {sorted(types) or 'none'})", url))
        if "FAQPage" not in types and "HowTo" not in types:
            findings.append(Finding("schema", "low", "missing_faq_schema", "No FAQPage/HowTo schema (helps answer-engine citation)", url))
        for rule, severity, detail in validate_jsonld(ins.jsonld, expected_names):
            findings.append(Finding("schema", severity, rule, detail, url))

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
) -> tuple[int, list[dict[str, Any]]]:
    """Audit robots/sitemap/llms.txt; return (sitemap urls found, AI bot rules)."""
    robots_rules = _audit_robots(base, robots_status, robots_text, findings)

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

    return len(urls), robots_rules


async def run_site_audit(
    base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
    entity_names: list[str] | None = None,
    pagespeed_key: str = "",
) -> AuditResult:
    """Fetch a live site, derive findings, and return the scored result.

    Callers persist the result; this function has no database access so it
    stays unit-testable — pass an ``httpx.MockTransport`` as ``transport``.

    ``entity_names`` (brand name + aliases) enables entity-drift checks; a
    non-empty ``pagespeed_key`` enables the mobile PageSpeed Insights call.
    """
    base = base_url.rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    host = urlsplit(base).netloc

    findings: list[Finding] = []
    pages: list[PageRecord] = []
    robots_rules: list[dict[str, Any]] = []
    speed: dict[str, Any]

    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT, follow_redirects=True, transport=transport,
        headers={"User-Agent": "FootnoteAuditBot/0.1"},
    ) as client:
        # Homepage
        home_status, home_html, home_ms = await _fetch(client, base)
        if home_status is None or home_status >= 400:
            findings.append(Finding("meta", "critical", "unreachable_homepage", f"Homepage returned {home_status}", base))
        elif home_status == 200:
            _audit_home_insights(base, home_html, findings, home_ms, entity_names)
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
        sitemap_url_count, robots_rules = _audit_site_files(
            base, robots_status, robots_text, sitemap_status, sitemap_text, llms_status, findings
        )

        # PageSpeed Insights (mobile) — explicit not_configured without a key.
        if pagespeed_key:
            payload, reason = await _fetch_pagespeed(client, base, pagespeed_key)
            if payload is not None:
                speed = payload
                _speed_findings(payload, base, findings)
            else:
                speed = {"status": "error", "reason": (reason or "unknown")[:200]}
                logger.warning("pagespeed_failed", host=host, reason=(reason or "")[:200])
        else:
            speed = {"status": "not_configured", "reason": "PAGESPEED_API_KEY not set"}

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
    summary: dict[str, Any] = {
        "base_url": base,
        "host": host,
        "pages_crawled": len(pages),
        "page_urls": [p.url for p in pages],
        "sitemap_urls": sitemap_url_count,
        "robots_rules": robots_rules,
        "speed": speed,
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
