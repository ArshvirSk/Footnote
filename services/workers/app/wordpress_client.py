"""WordPress REST API Publisher Client.

Interacts with the WordPress REST API (/wp-json/wp/v2/posts) using
WordPress Application Passwords (HTTP Basic Auth).
Converts Markdown to semantic HTML and embeds schema.org JSON-LD structured data.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from services.api.app.logging import get_logger

logger = get_logger(__name__)


def slugify(text: str) -> str:
    """Generate a clean URL slug from a title string."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "post"


def markdown_to_html(md: str) -> str:
    """Convert Markdown text into clean, semantic HTML.

    Handles headings, paragraphs, lists, blockquotes, code blocks, bold, italic, and links.
    """
    if not md:
        return ""

    lines = md.split("\n")
    html_lines: list[str] = []
    in_list = False
    in_code_block = False
    code_buffer: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Code block fence
        if stripped.startswith("```"):
            if in_code_block:
                html_lines.append(f"<pre><code>{'<br>'.join(code_buffer)}</code></pre>")
                code_buffer = []
                in_code_block = False
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                in_code_block = True
            continue

        if in_code_block:
            code_buffer.append(line.replace("<", "&lt;").replace(">", "&gt;"))
            continue

        # Blank line
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        # Headings
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            content = _format_inline(stripped[4:])
            html_lines.append(f"<h3>{content}</h3>")
            continue
        if stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            content = _format_inline(stripped[3:])
            html_lines.append(f"<h2>{content}</h2>")
            continue
        if stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            content = _format_inline(stripped[2:])
            html_lines.append(f"<h1>{content}</h1>")
            continue

        # Blockquote
        if stripped.startswith("> "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            content = _format_inline(stripped[2:])
            html_lines.append(f"<blockquote><p>{content}</p></blockquote>")
            continue

        # Bullet list
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = _format_inline(stripped[2:])
            html_lines.append(f"<li>{content}</li>")
            continue

        # Regular paragraph
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        content = _format_inline(stripped)
        html_lines.append(f"<p>{content}</p>")

    if in_list:
        html_lines.append("</ul>")
    if in_code_block:
        html_lines.append(f"<pre><code>{'<br>'.join(code_buffer)}</code></pre>")

    return "\n".join(html_lines)


def _format_inline(text: str) -> str:
    """Format bold, italic, code, and markdown links."""
    # Bold **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic *text*
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Inline code `code`
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    # Links [anchor](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def build_article_jsonld(
    title: str,
    canonical_url: str,
    brand_name: str = "Footnote",
    description: str | None = None,
    published_date: str | None = None,
) -> dict[str, Any]:
    """Generate Schema.org Article JSON-LD metadata graph."""
    now_iso = published_date or datetime.now(UTC).isoformat()
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description or title,
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": canonical_url,
        },
        "author": {
            "@type": "Organization",
            "name": brand_name,
        },
        "publisher": {
            "@type": "Organization",
            "name": brand_name,
        },
        "datePublished": now_iso,
        "dateModified": now_iso,
    }


class WordPressClientError(Exception):
    """Base error for WordPress publishing operations."""


class WordPressAuthError(WordPressClientError):
    """Authentication or authorization failure with Application Passwords."""


class WordPressPublishClient:
    """Client for WordPress REST API publishing using Application Passwords."""

    def __init__(self, endpoint: str, username: str, app_password: str, timeout: float = 15.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.username = username.strip()
        self.app_password = app_password.strip()
        self.timeout = timeout
        parsed = urlparse(self.endpoint)
        if not parsed.scheme or not parsed.netloc:
            raise WordPressClientError(f"Invalid WordPress endpoint URL: '{endpoint}'")

    async def verify_connection(self) -> dict[str, Any]:
        """Test authentication via GET /wp-json/wp/v2/users/me."""
        api_url = f"{self.endpoint}/wp-json/wp/v2/users/me"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                resp = await client.get(
                    api_url,
                    auth=(self.username, self.app_password),
                    headers={"User-Agent": "Footnote-Publisher/1.0"},
                )
            except Exception as exc:
                raise WordPressClientError(f"Failed to connect to WordPress endpoint: {exc}") from exc

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (401, 403):
            raise WordPressAuthError(
                f"WordPress authentication failed ({resp.status_code}): Invalid username or application password."
            )
        raise WordPressClientError(f"WordPress connection check returned status {resp.status_code}: {resp.text[:200]}")

    async def publish_post(
        self,
        title: str,
        body_md: str,
        slug: str | None = None,
        post_status: str = "publish",
        brand_name: str = "Footnote",
        categories: list[int] | None = None,
        tags: list[int] | None = None,
    ) -> dict[str, Any]:
        """Publish an article to WordPress as a post.

        Converts Markdown to HTML and injects JSON-LD Schema.org structured data.
        Returns a dict containing:
          - external_id: str
          - url: str (live URL)
          - status: str ('publish' or 'draft')
          - title: str
        """
        post_slug = slug or slugify(title)
        html_body = markdown_to_html(body_md)

        # Build approximate canonical URL for the post
        canonical_url = f"{self.endpoint}/{post_slug}"
        jsonld_data = build_article_jsonld(
            title=title,
            canonical_url=canonical_url,
            brand_name=brand_name,
        )
        jsonld_script = (
            f'\n<!-- Footnote Schema.org Structured Data -->\n'
            f'<script type="application/ld+json">\n{json.dumps(jsonld_data, indent=2)}\n</script>\n'
        )

        full_content = html_body + jsonld_script

        payload: dict[str, Any] = {
            "title": title,
            "content": full_content,
            "status": post_status,
            "slug": post_slug,
            "format": "standard",
        }
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags

        api_url = f"{self.endpoint}/wp-json/wp/v2/posts"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            try:
                resp = await client.post(
                    api_url,
                    auth=(self.username, self.app_password),
                    headers={
                        "User-Agent": "Footnote-Publisher/1.0",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except Exception as exc:
                logger.error("wordpress_publish_request_failed", endpoint=self.endpoint, error=str(exc))
                raise WordPressClientError(f"Network error communicating with WordPress: {exc}") from exc

        if resp.status_code in (200, 201):
            data = resp.json()
            external_id = str(data.get("id"))
            live_url = data.get("link") or canonical_url
            actual_status = data.get("status") or post_status

            logger.info(
                "wordpress_post_published",
                external_id=external_id,
                live_url=live_url,
                status=actual_status,
            )
            return {
                "external_id": external_id,
                "url": live_url,
                "status": actual_status,
                "title": title,
                "slug": data.get("slug", post_slug),
            }

        if resp.status_code in (401, 403):
            raise WordPressAuthError(f"WordPress publication unauthorized ({resp.status_code}): {resp.text[:200]}")

        raise WordPressClientError(f"WordPress publication failed ({resp.status_code}): {resp.text[:300]}")
