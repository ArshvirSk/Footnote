"""Tests for the site audit engine (live-site crawler), with a mocked transport."""

from __future__ import annotations

import httpx
from services.api.app.audit import (
    SUGGESTED_FIXES,
    effective_bot_rules,
    parse_html,
    parse_robots,
    run_site_audit,
    validate_jsonld,
)

BASE = "https://example-shop.com"

GOOD_HTML = """<!doctype html>
<html lang="en">
<head>
  <title>Example Shop — Best shoes online</title>
  <meta name="description" content="Example Shop sells comfortable shoes with free returns and fast shipping.">
  <meta property="og:title" content="Example Shop">
  <link rel="canonical" href="https://example-shop.com/">
  <script type="application/ld+json">{"@type": "Organization", "name": "Example Shop"}</script>
  <script type="application/ld+json">{"@type": "FAQPage"}</script>
  <style>.x { color: red }</style>
</head>
<body>
  <h1>Welcome to Example Shop</h1>
  """ + ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore. " * 10) + """
</body>
</html>"""

BAD_HTML = """<!doctype html>
<html>
<head></head>
<body><p>thin</p></body>
</html>"""

SITEMAP = f"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{BASE}/</loc></url>
  <url><loc>{BASE}/shoes</loc></url>
  <url><loc>{BASE}/boots</loc></url>
</urlset>"""

ROBOTS = "User-agent: *\nAllow: /\nSitemap: https://example-shop.com/sitemap.xml\n"


def _transport(home: str = GOOD_HTML, robots: int = 200, sitemap: int = 200, llms: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in ("", "/"):
            return httpx.Response(200, text=home, headers={"content-type": "text/html"})
        if path == "/robots.txt":
            return httpx.Response(robots, text=ROBOTS if robots == 200 else "not found")
        if path == "/sitemap.xml":
            return httpx.Response(sitemap, text=SITEMAP if sitemap == 200 else "not found",
                                  headers={"content-type": "application/xml"})
        if path == "/llms.txt":
            return httpx.Response(llms, text="# Example Shop" if llms == 200 else "not found")
        # sitemap sample pages
        return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})

    return httpx.MockTransport(handler)


class TestHtmlParsing:
    def test_extracts_meta_and_schema(self) -> None:
        ins = parse_html(GOOD_HTML)
        assert ins.title == "Example Shop — Best shoes online"
        assert ins.description is not None and "free returns" in ins.description
        assert ins.canonical == "https://example-shop.com/"
        assert ins.og_title == "Example Shop"
        assert ins.lang == "en"
        assert ins.h1_count == 1
        assert {t["@type"] for t in ins.jsonld} == {"Organization", "FAQPage"}
        assert ins.word_count > 100

    def test_style_content_is_not_counted(self) -> None:
        ins = parse_html("<html><head><style>.x { color: red }</style></head><body><p>one two three</p></body></html>")
        assert "color" not in (ins.title or "")
        assert ins.word_count == 3

    def test_bad_page_yields_nothing(self) -> None:
        ins = parse_html(BAD_HTML)
        assert ins.title is None
        assert ins.description is None
        assert ins.jsonld == []
        assert ins.h1_count == 0


class TestRunSiteAudit:
    async def test_clean_site_scores_high_with_few_findings(self) -> None:
        result = await run_site_audit(BASE, transport=_transport())
        assert result.score >= 80
        rules = {f.rule for f in result.findings}
        # Clean page has title/description/canonical/jsonld/h1/robots/sitemap — no criticals.
        assert "missing_title" not in rules
        assert "missing_robots" not in rules
        assert "missing_sitemap" not in rules
        assert "missing_json_ld" not in rules
        assert result.summary["sitemap_urls"] == 3
        # homepage + 2 sample pages
        assert result.summary["pages_crawled"] == 3
        assert all(p.status_code == 200 for p in result.pages)

    async def test_broken_site_is_penalized(self) -> None:
        # Thin page, missing site files.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path in ("", "/"):
                return httpx.Response(200, text=BAD_HTML, headers={"content-type": "text/html"})
            return httpx.Response(404, text="not found")

        result = await run_site_audit(BASE, transport=httpx.MockTransport(handler))
        assert result.score < 50
        rules = {f.rule for f in result.findings}
        assert {"missing_title", "missing_description", "missing_json_ld", "missing_robots",
                "missing_sitemap", "missing_llms_txt", "thin_content"} <= rules
        # Scoring is bounded at 0 even with many deductions.
        assert result.score >= 0

    async def test_unreachable_homepage_is_critical(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="server error")

        result = await run_site_audit(BASE, transport=httpx.MockTransport(handler))
        assert any(f.rule == "unreachable_homepage" and f.severity == "critical" for f in result.findings)
        assert result.score <= 70

    async def test_robots_disallow_all_is_critical(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path in ("", "/"):
                return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})
            if path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
            if path == "/sitemap.xml":
                return httpx.Response(200, text=SITEMAP, headers={"content-type": "application/xml"})
            if path == "/llms.txt":
                return httpx.Response(200, text="# hi")
            return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})

        result = await run_site_audit(BASE, transport=httpx.MockTransport(handler))
        assert any(f.rule == "robots_disallow_all" and f.severity == "critical" for f in result.findings)

    async def test_sitemap_assets_are_not_crawled_as_pages(self) -> None:
        """Sitemap index entries (.xml.gz) and assets must not become page records."""
        bad_sitemap = f"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{BASE}/</loc></url>
  <url><loc>{BASE}/sitemaps/de/sitemap.xml.gz</loc></url>
  <url><loc>{BASE}/logo.png</loc></url>
  <url><loc>{BASE}/shoes</loc></url>
</urlset>"""
        fetched: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            fetched.append(path)
            if path in ("", "/"):
                return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})
            if path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS)
            if path == "/sitemap.xml":
                return httpx.Response(200, text=bad_sitemap, headers={"content-type": "application/xml"})
            if path == "/llms.txt":
                return httpx.Response(404, text="no")
            return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})

        result = await run_site_audit(BASE, transport=httpx.MockTransport(handler))
        # Only homepage + /shoes fetched — never the .xml.gz or .png.
        assert "/sitemaps/de/sitemap.xml.gz" not in fetched
        assert "/logo.png" not in fetched
        assert "/shoes" in fetched
        assert result.summary["pages_crawled"] == 2

    async def test_sitemap_index_children_are_followed(self) -> None:
        """A sitemapindex (.xml.gz children) must still yield crawlable pages."""
        index = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example-shop.com/sitemaps/en.xml.gz</loc></sitemap>
</sitemapindex>"""
        child = f"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{BASE}/shoes</loc></url>
  <url><loc>{BASE}/boots</loc></url>
</urlset>"""

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path in ("", "/"):
                return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})
            if path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS)
            if path == "/sitemap.xml":
                return httpx.Response(200, text=index, headers={"content-type": "application/xml"})
            if path == "/sitemaps/en.xml.gz":
                return httpx.Response(200, content=child.encode(), headers={"content-type": "application/xml"})
            if path == "/llms.txt":
                return httpx.Response(404, text="no")
            return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})

        result = await run_site_audit(BASE, transport=httpx.MockTransport(handler))
        crawled = {p.url for p in result.pages}
        assert f"{BASE}/shoes" in crawled
        assert f"{BASE}/boots" in crawled
        # index itself is not a page
        assert not any(u.endswith(".xml.gz") for u in crawled)

    async def test_defaults_to_https_scheme(self) -> None:
        # httpx MockTransport resolves relative to the request URL; passing a
        # bare host must still produce a fetchable absolute URL.
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path in ("", "/"):
                return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})
            return httpx.Response(404, text="no")

        await run_site_audit("example-shop.com", transport=httpx.MockTransport(handler))
        assert seen[0].startswith("https://example-shop.com")


class TestRobotsAiBots:
    def test_parse_robots_groups_agents_and_rules(self) -> None:
        groups = parse_robots(
            "# comment\nUser-agent: GPTBot\nUser-agent: OAI-SearchBot\nDisallow: /private\n"
            "\nUser-agent: *\nAllow: /\nDisallow: /admin\n"
        )
        assert len(groups) == 2
        assert groups[0].agents == ["GPTBot", "OAI-SearchBot"]
        assert groups[0].rules == [("disallow", "/private")]
        assert groups[1].agents == ["*"]
        assert ("allow", "/") in groups[1].rules

    def test_specific_group_wins_over_wildcard(self) -> None:
        groups = parse_robots(
            "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
        )
        rules = {r.bot: r for r in effective_bot_rules(groups)}
        assert rules["GPTBot"].allowed is False
        assert rules["GPTBot"].group == "GPTBot"
        assert rules["ClaudeBot"].allowed is True
        assert rules["ClaudeBot"].group == "*"

    async def test_blocked_ai_bot_yields_finding_and_summary(self) -> None:
        robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\nSitemap: https://example-shop.com/sitemap.xml\n"

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path in ("", "/"):
                return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})
            if path == "/robots.txt":
                return httpx.Response(200, text=robots)
            if path == "/sitemap.xml":
                return httpx.Response(200, text=SITEMAP, headers={"content-type": "application/xml"})
            if path == "/llms.txt":
                return httpx.Response(200, text="# hi")
            return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})

        result = await run_site_audit(BASE, transport=httpx.MockTransport(handler))
        finding = next(f for f in result.findings if f.rule == "ai_bot_blocked")
        assert finding.severity == "high"
        assert "GPTBot" in finding.detail
        rules = {r["bot"]: r for r in result.summary["robots_rules"]}
        assert rules["GPTBot"]["allowed"] is False
        assert rules["PerplexityBot"]["allowed"] is True
        assert rules["PerplexityBot"]["group"] == "*"

    async def test_all_primary_bots_blocked_is_critical(self) -> None:
        bots = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "PerplexityBot", "Google-Extended"]
        robots = "".join(f"User-agent: {b}\nDisallow: /\n\n" for b in bots) + "User-agent: *\nAllow: /\n"

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path in ("", "/"):
                return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})
            if path == "/robots.txt":
                return httpx.Response(200, text=robots)
            if path == "/sitemap.xml":
                return httpx.Response(200, text=SITEMAP, headers={"content-type": "application/xml"})
            if path == "/llms.txt":
                return httpx.Response(200, text="# hi")
            return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})

        result = await run_site_audit(BASE, transport=httpx.MockTransport(handler))
        finding = next(f for f in result.findings if f.rule == "ai_bot_blocked")
        assert finding.severity == "critical"
        # robots_disallow_all must not double-count when only specific bots are blocked.
        assert not any(f.rule == "robots_disallow_all" for f in result.findings)


class TestJsonLdValidity:
    def test_parse_error_is_high(self) -> None:
        issues = validate_jsonld([{"_parse_error": True, "_raw": "{'@type': 'Organization'}"}])
        assert issues[0][0] == "jsonld_parse_error"
        assert issues[0][1] == "high"

    def test_missing_context_and_type_and_sameas(self) -> None:
        issues = validate_jsonld([{"@type": "Organization", "name": "Example Shop"}])
        rules = {rule for rule, _sev, _detail in issues}
        assert "jsonld_missing_context" in rules
        assert "organization_missing_sameAs" in rules
        assert "organization_missing_name" not in rules

    def test_entity_name_mismatch_against_expected_names(self) -> None:
        block = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Totally Different Co",
            "sameAs": ["https://linkedin.com/company/x"],
        }
        issues = validate_jsonld([block], expected_names=["Example Shop", "ExampleShop"])
        mismatch = next(i for i in issues if i[0] == "entity_name_mismatch")
        assert "Totally Different Co" in mismatch[2]
        # Matching (case/substring-loose) names raise no drift finding.
        assert not any(
            rule == "entity_name_mismatch"
            for rule, _s, _d in validate_jsonld([block | {"name": "Example Shop Pvt Ltd"}], ["Example Shop"])
        )

    async def test_audit_reports_schema_validity_findings(self) -> None:
        html = GOOD_HTML.replace(
            '<script type="application/ld+json">{"@type": "Organization", "name": "Example Shop"}</script>',
            '<script type="application/ld+json">{"@type": "Organization"}</script>',
        )

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path in ("", "/"):
                return httpx.Response(200, text=html, headers={"content-type": "text/html"})
            if path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS)
            if path == "/sitemap.xml":
                return httpx.Response(200, text=SITEMAP, headers={"content-type": "application/xml"})
            if path == "/llms.txt":
                return httpx.Response(200, text="# hi")
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})

        result = await run_site_audit(
            BASE, transport=httpx.MockTransport(handler), entity_names=["Example Shop"]
        )
        rules = {f.rule for f in result.findings}
        assert "organization_missing_name" in rules
        assert "entity_name_mismatch" not in rules  # name absent, not drifting


PSI_PAYLOAD = {
    "lighthouseResult": {
        "finalUrl": BASE,
        "categories": {"performance": {"score": 0.35}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 5200},
            "cumulative-layout-shift": {"numericValue": 0.31},
            "total-blocking-time": {"numericValue": 800},
            "first-contentful-paint": {"numericValue": 2100},
            "speed-index": {"numericValue": 4800},
        },
    }
}


def _psi_transport(psi: httpx.Response) -> httpx.MockTransport:
    """Site responds normally; the PageSpeed endpoint returns ``psi``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.googleapis.com":
            return psi
        path = request.url.path
        if path in ("", "/"):
            return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if path == "/sitemap.xml":
            return httpx.Response(200, text=SITEMAP, headers={"content-type": "application/xml"})
        if path == "/llms.txt":
            return httpx.Response(200, text="# hi")
        return httpx.Response(200, text=GOOD_HTML, headers={"content-type": "text/html"})

    return httpx.MockTransport(handler)


class TestPageSpeed:
    async def test_metrics_findings_and_summary(self) -> None:
        psi = httpx.Response(200, json=PSI_PAYLOAD, headers={"content-type": "application/json"})
        result = await run_site_audit(BASE, transport=_psi_transport(psi), pagespeed_key="test-key")
        speed = result.summary["speed"]
        assert speed["status"] == "ok"
        assert speed["performance_score"] == 35
        assert speed["lcp_ms"] == 5200
        assert speed["cls"] == 0.31
        rules = {f.rule: f for f in result.findings}
        assert rules["pagespeed_score_low"].severity == "high"
        assert rules["slow_lcp"].severity == "high"
        assert rules["high_cls"].severity == "medium"
        assert rules["high_cls"].fix_owner == "client_dev"

    async def test_no_key_records_not_configured(self) -> None:
        result = await run_site_audit(BASE, transport=_transport())
        assert result.summary["speed"]["status"] == "not_configured"
        assert not any(f.rule.startswith("pagespeed") or f.rule in ("slow_lcp", "high_cls") for f in result.findings)

    async def test_api_error_is_recorded_without_finding(self) -> None:
        psi = httpx.Response(429, text="quota exceeded", headers={"content-type": "text/plain"})
        result = await run_site_audit(BASE, transport=_psi_transport(psi), pagespeed_key="test-key")
        assert result.summary["speed"]["status"] == "error"
        assert "429" in result.summary["speed"]["reason"]
        assert not any(f.rule in ("pagespeed_score_low", "slow_lcp", "high_cls") for f in result.findings)

    def test_every_rule_has_a_suggested_fix(self) -> None:
        for rule in (
            "ai_bot_blocked", "jsonld_parse_error", "jsonld_missing_context", "jsonld_missing_type",
            "organization_missing_name", "organization_missing_sameAs", "entity_name_mismatch",
            "pagespeed_score_low", "slow_lcp", "high_cls",
        ):
            assert SUGGESTED_FIXES.get(rule), f"missing suggested fix for {rule}"
