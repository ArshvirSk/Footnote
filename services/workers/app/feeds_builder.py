"""Feeds Static Site Builder.

Generates pre-rendered static HTML articles, an index hub page, and a sitemap.xml
styled using the client's brand theme (theme_html, theme_css) with embedded
Schema.org JSON-LD structured data.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from services.api.app.db import engine
from services.api.app.logging import get_logger
from services.workers.app.wordpress_client import (
    build_article_jsonld,
    markdown_to_html,
    slugify,
)
from sqlalchemy import text

logger = get_logger(__name__)

# Default directory for static site builds
FEEDS_BUILD_BASE = Path(__file__).resolve().parents[4] / "scratch" / "feeds"


DEFAULT_THEME_CSS = """
:root {
  --primary: #10b981;
  --bg: #090a0f;
  --card: #131722;
  --text: #f3f4f6;
  --muted: #9ca3af;
  --border: #1f293d;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background-color: var(--bg);
  color: var(--text);
  margin: 0;
  padding: 0;
  line-height: 1.6;
}
.feeds-container {
  max-width: 860px;
  margin: 0 auto;
  padding: 2.5rem 1.5rem;
}
header.feeds-header {
  border-bottom: 1px solid var(--border);
  padding-bottom: 2rem;
  margin-bottom: 2.5rem;
}
header.feeds-header h1 {
  font-size: 2.25rem;
  margin: 0 0 0.5rem 0;
  color: #fff;
}
.article-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  transition: transform 0.2s, border-color 0.2s;
}
.article-card:hover {
  border-color: var(--primary);
  transform: translateY(-2px);
}
.article-card h2 {
  margin: 0 0 0.5rem 0;
  font-size: 1.5rem;
}
.article-card h2 a {
  color: #fff;
  text-decoration: none;
}
.article-card h2 a:hover {
  color: var(--primary);
}
.meta {
  font-size: 0.875rem;
  color: var(--muted);
  margin-bottom: 1rem;
}
.content-body {
  font-size: 1.1rem;
  line-height: 1.75;
}
.content-body h2 {
  margin-top: 2rem;
  color: #fff;
}
.content-body blockquote {
  border-left: 4px solid var(--primary);
  margin: 1.5rem 0;
  padding: 0.5rem 1rem;
  background: var(--card);
  font-style: italic;
}
footer.feeds-footer {
  margin-top: 4rem;
  border-top: 1px solid var(--border);
  padding-top: 2rem;
  text-align: center;
  color: var(--muted);
  font-size: 0.875rem;
}
"""


class FeedsBuilder:
    """Renders client content into a static edge-distributable site."""

    def __init__(self, client_id: UUID | str, output_dir: Path | None = None) -> None:
        self.client_id = str(client_id)
        self.output_dir = output_dir or (FEEDS_BUILD_BASE / self.client_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def build(self) -> dict[str, Any]:
        """Fetch client profile and published content, and render full static site."""
        logger.info("feeds_build_started", client_id=self.client_id)

        async with engine.begin() as conn:
            # 1. Fetch client, brand profile, feeds settings
            res = await conn.execute(
                text(
                    """
                    SELECT c.name as client_name, c.primary_domain as domain,
                           bp.theme_html, bp.theme_css, bp.positioning,
                           fs.mount_path, fs.custom_domain
                    FROM clients c
                    LEFT JOIN brand_profiles bp ON bp.client_id = c.id
                    LEFT JOIN feeds_sites fs ON fs.client_id = c.id
                    WHERE c.id = :cid
                    """
                ),
                {"cid": self.client_id},
            )
            client_row = res.first()
            if not client_row:
                raise ValueError(f"Client {self.client_id} not found")

            # 2. Fetch published content items
            items_res = await conn.execute(
                text(
                    """
                    SELECT ci.id, cv.title, ci.published_url, ci.published_at,
                           cv.body_md, cv.word_count, cv.reading_time_min, cv.claims
                    FROM content_items ci
                    JOIN content_versions cv ON cv.id = ci.current_version_id
                    WHERE ci.client_id = :cid
                      AND ci.status = 'published'
                    ORDER BY ci.published_at DESC NULLS LAST
                    """
                ),
                {"cid": self.client_id},
            )
            items = items_res.fetchall()

        client_name = client_row.client_name or "Footnote Client"
        domain = client_row.custom_domain or client_row.domain or "feeds.footnote.ai"
        mount_path = (client_row.mount_path or "/feeds").rstrip("/")
        theme_css = client_row.theme_css or DEFAULT_THEME_CSS
        base_url = f"https://{domain}{mount_path}"

        rendered_pages: list[dict[str, str]] = []

        # 3. Render individual article pages
        for item in items:
            slug = slugify(item.title)
            article_url = f"{base_url}/{slug}.html"
            pub_date = item.published_at.isoformat() if item.published_at else datetime.now(UTC).isoformat()
            html_content = markdown_to_html(item.body_md or "")
            jsonld_obj = build_article_jsonld(
                title=item.title,
                canonical_url=article_url,
                brand_name=client_name,
                published_date=pub_date,
            )

            page_html = self._render_article_page(
                title=item.title,
                article_html=html_content,
                canonical_url=article_url,
                client_name=client_name,
                theme_css=theme_css,
                pub_date=pub_date,
                reading_time=item.reading_time_min,
                jsonld_data=jsonld_obj,
                hub_url=f"{base_url}/index.html",
            )

            file_path = self.output_dir / f"{slug}.html"
            file_path.write_text(page_html, encoding="utf-8")
            rendered_pages.append({"slug": slug, "title": item.title, "url": article_url, "pub_date": pub_date})

        # 4. Render Index / Hub page
        index_html = self._render_index_page(
            client_name=client_name,
            theme_css=theme_css,
            pages=rendered_pages,
            hub_url=f"{base_url}/index.html",
        )
        (self.output_dir / "index.html").write_text(index_html, encoding="utf-8")

        # 5. Render Sitemap XML
        sitemap_xml = self._render_sitemap_xml(
            hub_url=f"{base_url}/index.html",
            pages=rendered_pages,
        )
        (self.output_dir / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")

        # 6. Update database feeds_sites tracking
        origin_prefix = f"/feeds/{self.client_id}"
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO feeds_sites (client_id, mount_path, origin_prefix, last_build_at)
                    VALUES (:cid, :mount, :origin, now())
                    ON CONFLICT (client_id) DO UPDATE
                    SET origin_prefix = :origin, last_build_at = now()
                    """
                ),
                {"cid": self.client_id, "mount": mount_path or "/feeds", "origin": origin_prefix},
            )

        logger.info(
            "feeds_build_completed",
            client_id=self.client_id,
            pages_count=len(rendered_pages),
            output_dir=str(self.output_dir),
        )

        return {
            "client_id": self.client_id,
            "pages_count": len(rendered_pages),
            "hub_url": f"{base_url}/index.html",
            "sitemap_url": f"{base_url}/sitemap.xml",
            "output_dir": str(self.output_dir),
            "origin_prefix": origin_prefix,
            "built_at": datetime.now(UTC).isoformat(),
        }

    def _render_article_page(
        self,
        title: str,
        article_html: str,
        canonical_url: str,
        client_name: str,
        theme_css: str,
        pub_date: str,
        reading_time: float | None,
        jsonld_data: dict[str, Any],
        hub_url: str,
    ) -> str:
        esc_title = html.escape(title)
        esc_name = html.escape(client_name)
        time_str = f" • {reading_time} min read" if reading_time else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc_title} | {esc_name}</title>
  <link rel="canonical" href="{canonical_url}">
  <meta name="description" content="{esc_title}">
  <style>
{theme_css}
  </style>
  <script type="application/ld+json">
{json.dumps(jsonld_data, indent=2)}
  </script>
</head>
<body>
  <div class="feeds-container">
    <header class="feeds-header">
      <p><a href="{hub_url}" style="color:var(--primary);text-decoration:none;">&larr; Back to {esc_name} Knowledge Hub</a></p>
      <h1>{esc_title}</h1>
      <div class="meta">Published {pub_date[:10]} by {esc_name}{time_str}</div>
    </header>
    <main>
      <article class="content-body">
{article_html}
      </article>
    </main>
    <footer class="feeds-footer">
      <p>&copy; {pub_date[:4]} {esc_name}. Powered by Footnote Feeds.</p>
    </footer>
  </div>
</body>
</html>"""

    def _render_index_page(
        self,
        client_name: str,
        theme_css: str,
        pages: list[dict[str, str]],
        hub_url: str,
    ) -> str:
        esc_name = html.escape(client_name)
        now_year = datetime.now(UTC).year

        items_html: list[str] = []
        for p in pages:
            title = html.escape(p["title"])
            url = p["url"]
            date = p["pub_date"][:10]
            items_html.append(
                f"""
        <article class="article-card">
          <h2><a href="{url}">{title}</a></h2>
          <div class="meta">Published on {date}</div>
        </article>
                """
            )

        if not items_html:
            items_rendered = "<p style='color:var(--muted);'>No articles published yet.</p>"
        else:
            items_rendered = "\n".join(items_html)

        collection_jsonld = {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": f"{client_name} Knowledge Hub",
            "url": hub_url,
            "publisher": {"@type": "Organization", "name": client_name},
        }

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc_name} Knowledge Hub</title>
  <link rel="canonical" href="{hub_url}">
  <style>
{theme_css}
  </style>
  <script type="application/ld+json">
{json.dumps(collection_jsonld, indent=2)}
  </script>
</head>
<body>
  <div class="feeds-container">
    <header class="feeds-header">
      <h1>{esc_name} Knowledge Hub</h1>
      <p style="color:var(--muted);">Authoritative insights, answers, and analysis from {esc_name}.</p>
    </header>
    <main>
{items_rendered}
    </main>
    <footer class="feeds-footer">
      <p>&copy; {now_year} {esc_name}. Powered by Footnote Feeds.</p>
    </footer>
  </div>
</body>
</html>"""

    def _render_sitemap_xml(self, hub_url: str, pages: list[dict[str, str]]) -> str:
        now_iso = datetime.now(UTC).date().isoformat()
        xml_entries = [
            f"""  <url>
    <loc>{hub_url}</loc>
    <lastmod>{now_iso}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>"""
        ]
        for p in pages:
            date = p["pub_date"][:10]
            xml_entries.append(
                f"""  <url>
    <loc>{p['url']}</loc>
    <lastmod>{date}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>"""
            )

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(xml_entries)
            + "\n</urlset>"
        )
