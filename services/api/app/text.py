"""Shared text helpers: chunking and HTML-to-text extraction.

Used by brand-memory ingestion (API) and the publication embedder (worker) so
chunking behaves identically in both paths.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_WHITESPACE = re.compile(r"\s+")


def chunk_text(text_content: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping word windows.

    ``chunk_size``/``overlap`` are in words. Whitespace is normalized first so
    chunks never contain double spaces or embedded newlines.
    """
    words = _WHITESPACE.sub(" ", text_content).strip().split()
    if not words:
        return []
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 5)
    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk:
            chunks.append(chunk)
        if i + chunk_size >= len(words):
            break
    return chunks


class _TextExtractor(HTMLParser):
    """Strip tags/scripts/styles and collect visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._parts.append(data.strip())

    @property
    def text(self) -> str:
        return _WHITESPACE.sub(" ", " ".join(self._parts)).strip()


def html_to_text(html: str) -> str:
    """Best-effort visible text from an HTML document."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text
