"""Parser service: mention judge (versioned), fuzzy brand detection, domain taxonomy.

Two judges are available and the version used for each answer is recorded in
``answers.judge_version``:

- ``rules-v2``  — deterministic, sentence-scoped rules (no API key needed).
  This is the default and the judge the golden-set harness gates.
- ``llm:<model>:v1`` — an OpenAI JSON judge, used when ``JUDGE_MODE=llm``.
  Any failure falls back to the rules judge (and records ``rules-v2``), so a
  missing/broken key can never silently fabricate labels.

The golden set lives in ``packages/evals/golden_set.json`` (>=30 hand-labelled
fixtures); ``packages/evals/judge_eval.py`` reports agreement.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field
from services.api.app.config import settings
from services.api.app.logging import get_logger

logger = get_logger(__name__)

JUDGE_RULES_VERSION = "rules-v2"


class DomainInfo(BaseModel):
    normalized_domain: str
    is_brand_owned: bool = False
    competitor_id: str | None = None


def normalize_domain(url: str) -> str:
    """Extract and normalize domain from URL. Strips www."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return "unknown"


def extract_citations(text: str, raw_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract citations from structured JSON if available, fallback to regex."""
    citations = []
    if "sources" in raw_json:
        for idx, src in enumerate(raw_json["sources"]):
            citations.append({"url": src["url"], "title": src.get("title", ""), "position": idx + 1})
        return citations

    # Fallback text regex for http(s) urls
    urls = re.findall(r'(https?://\S+)', text)
    for idx, u in enumerate(urls):
        clean_url = u.rstrip(').,"]')
        citations.append({"url": clean_url, "title": "", "position": idx + 1})

    return citations


# ───────────── Domain taxonomy (FR-12) ─────────────

_FORUM_DOMAINS = {
    "reddit.com", "quora.com", "stackoverflow.com", "stackexchange.com", "askubuntu.com",
    "serverfault.com", "superuser.com", "discourse.org", "discuss.huggingface.co",
}
_REVIEW_DOMAINS = {
    "g2.com", "capterra.com", "getapp.com", "softwareadvice.com", "trustpilot.com",
    "glassdoor.com", "clutch.co", "goodfirms.co", "sourceforge.net", "producthunt.com",
    "gartner.com", "g2crowd.co",
}
_WIKI_DOMAINS = {"wikipedia.org", "wikimedia.org", "wikidata.org", "wikihow.com", "fandom.com"}
_NEWS_DOMAINS = {
    "techcrunch.com", "reuters.com", "bbc.com", "bbc.co.uk", "cnn.com", "nytimes.com",
    "theguardian.com", "forbes.com", "bloomberg.com", "wsj.com", "wired.com",
    "theverge.com", "arstechnica.com", "businessinsider.com", "fastcompany.com",
    "inc.com", "entrepreneur.com", "zdnet.com", "venturebeat.com", "mashable.com",
    "economictimes.indiatimes.com", "timesofindia.indiatimes.com", "hindustantimes.com",
    "livemint.com", "business-standard.com", "ndtv.com", "indiatoday.in", "news18.com",
}
_PUBLISHER_DOMAINS = {"medium.com", "substack.com", "wordpress.com", "ghost.io", "blogger.com", "hubpages.com"}
_MARKETPLACE_DOMAINS = {
    "amazon.com", "amazon.in", "ebay.com", "etsy.com", "flipkart.com", "walmart.com",
    "aliexpress.com", "target.com", "bestbuy.com",
}


def classify_domain(domain: str) -> str:
    """Classify a citation domain into the ``domain_type_t`` taxonomy (FR-12).

    owned/competitor are assigned by the collector from client config; this
    covers the content-type buckets: forum, review_site, wiki, news, publisher,
    marketplace, gov_edu, other.
    """
    d = (domain or "").lower().strip()
    if not d or d == "unknown":
        return "other"
    if d.endswith(".gov") or ".gov." in d or d.endswith(".edu") or ".edu." in d:
        return "gov_edu"

    def matches(bucket: set[str]) -> bool:
        return any(d == root or d.endswith("." + root) for root in bucket)

    if matches(_WIKI_DOMAINS):
        return "wiki"
    if matches(_FORUM_DOMAINS):
        return "forum"
    if matches(_REVIEW_DOMAINS):
        return "review_site"
    if matches(_MARKETPLACE_DOMAINS):
        return "marketplace"
    if matches(_NEWS_DOMAINS):
        return "news"
    if matches(_PUBLISHER_DOMAINS):
        return "publisher"
    return "other"


# ───────────── Fuzzy brand/competitor mention detection ─────────────

_LEGAL_SUFFIX = re.compile(
    r"\b(?:pvt\.?|private|ltd\.?|llc|inc\.?|corp\.?|corporation|co\.?|company|gmbh|plc|s\.?a\.?|bv)\b\.?",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _normalize(text: str) -> str:
    return _NON_ALNUM.sub(" ", text.casefold()).strip()


def _sentence_variants(text: str) -> list[tuple[str, str]]:
    """(normalized sentence, original sentence) pairs."""
    out = []
    for sentence in _SENTENCE_SPLIT.split(text):
        norm = _normalize(sentence)
        if norm:
            out.append((norm, sentence))
    return out


def _name_patterns(name: str) -> list[re.Pattern[str]]:
    """Word-boundary patterns for a name: exact, plural-tolerant, separator-free.

    ``DBA Consultants`` matches "DBA Consultants", "DBA-Consultants" and
    "DBAConsultants"; legal suffixes are optional so "Acme Corp" matches
    "Acme Corporation".
    """
    cleaned = name.strip()
    if not cleaned:
        return []
    words = [w for w in _NON_ALNUM.split(cleaned.casefold()) if w]
    if not words:
        return []
    # tolerate plural/singular on each word, and any separator (incl. none)
    body = r"[\s\-_\.]*".join(rf"{re.escape(w)}s?" for w in words)
    suffix = _LEGAL_SUFFIX.pattern
    patterns = [
        re.compile(rf"\b{body}\b", re.IGNORECASE),
        re.compile(rf"\b{body}[\s\-_\.]*{suffix}", re.IGNORECASE),
    ]
    return patterns


def _fuzzy_word_match(name_words: list[str], sentence_words: list[str]) -> bool:
    """True when every name word appears in the sentence, edit distance <= 1 allowed."""
    if not name_words:
        return False
    remaining = list(sentence_words)
    for word in name_words:
        found_at = None
        for i, cand in enumerate(remaining):
            if cand == word or (len(word) >= 6 and _edit_distance_le1(word, cand)):
                found_at = i
                break
        if found_at is None:
            return False
        remaining.pop(found_at)
    return True


def _edit_distance_le1(a: str, b: str) -> bool:
    """Cheap Levenshtein <= 1 check (for words >= 6 chars)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = sum(1 for x, y in zip(a, b, strict=True) if x != y)
        return diffs <= 1
    short, long_ = (a, b) if la < lb else (b, a)
    i = j = 0
    edits = 0
    while i < len(short) and j < len(long_):
        if short[i] == long_[j]:
            i += 1
            j += 1
        else:
            edits += 1
            if edits > 1:
                return False
            j += 1
    return True


class MentionMatch(BaseModel):
    name: str
    excerpt: str


def find_mention(text: str, *names: str) -> MentionMatch | None:
    """Find the first mention of any name/alias in ``text`` (exact then fuzzy).

    Returns the matched surface name and the sentence containing it, or None.
    Used for brand detection input and competitor mention detection (FR-12/13).
    """
    candidates = sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True)
    if not candidates or not text:
        return None

    sentences = _SENTENCE_SPLIT.split(text)
    normalized_sentences = _sentence_variants(text)

    for name in candidates:
        for pattern in _name_patterns(name):
            match = pattern.search(text)
            if match:
                # sentence containing the match
                excerpt = next(
                    (s for s in sentences if match.group(0).casefold() in s.casefold()),
                    match.group(0),
                )
                return MentionMatch(name=name, excerpt=excerpt.strip()[:500])

    # Fuzzy pass: token-level match with plural + 1-edit tolerance, per sentence.
    for name in candidates:
        name_words = [w for w in _normalize(_LEGAL_SUFFIX.sub(" ", name)).split() if w]
        if len(name_words) == 1 and len(name_words[0]) < 5:
            continue  # short single words are too risky to fuzzy-match
        for norm_sentence, original in normalized_sentences:
            if _fuzzy_word_match(name_words, norm_sentence.split()):
                return MentionMatch(name=name, excerpt=original.strip()[:500])
    return None


# ───────────── Mention judge ─────────────

class JudgeResult(BaseModel):
    recommended: bool
    sentiment: str = Field(pattern="^(positive|neutral|negative|mixed)$")
    rank_in_answer: int | None
    excerpt: str
    judge_version: str = JUDGE_RULES_VERSION


# Recommendation is denied when negation targets "recommend" near the brand mention,
# or when the answer recommends *against* the brand.
_NEGATED_RECOMMEND = re.compile(
    r"(?:"
    r"\b(?:do(?:es)?n['\u2019]t|do(?:es)? not|did(?:n['\u2019]t| not)|never|not|no|can(?:not|['\u2019]t)"
    r"|should(?:n['\u2019]t| not)|would(?:n['\u2019]t| not)|avoid|\w+n['\u2019]t)\b"
    r"[^.!?]{0,60}\brecommend(?:ed|s|ing)?\b"
    r"|"
    r"\brecommend(?:ed|s|ing)?\s+(?:against|not\b|avoiding)"
    r")",
    re.IGNORECASE,
)
# Explicit non-recommendation / failure phrasing around the mention.
_ADVERSE = re.compile(
    r"\b(?:lacks?|poor|weak|worst|overpriced|slow|buggy|limited|avoid|unreliable|difficult|expensive"
    r"|does(?:n['\u2019]t| not) deliver|fails? to|disappointing|not worth|worse|broken|underwhelming)\b",
    re.IGNORECASE,
)
# Contrast markers that make an answer mixed rather than positive.
_CONTRAST = re.compile(r"\b(?:while|although|though|however|despite|whereas|but|except)\b", re.IGNORECASE)
# Comparative preference toward another option in the same sentence.
_PREFERENCE_ELSEWHERE = re.compile(
    r"\b(?:prefer(?:red|s)?|better|superior|instead(?: of)?|rather(?: than)?|more capable|best for"
    r"|pick(?:s|ed|ing)?|choos(?:e|es|ing))\b",
    re.IGNORECASE,
)
_POSITIVE = re.compile(
    r"\b(?:leading|best|better|excellent|great|comprehensive|strong(?:er|est)?|top|highly recommended"
    r"|recommend(?:ed|s)?|widely considered|ideal|reliable|powerful|improved|improving"
    r"|outperform(?:s|ed)?|wins over|edges out)\b",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"\b(?:don['\u2019]t recommend|does(?:n['\u2019]t| not) recommend|not recommend|isn['\u2019]t recommended"
    r"|lacks?|worst|poor|avoid|overpriced|unreliable|difficult|worse)\b",
    re.IGNORECASE,
)


def _mention_pattern(*names: str) -> re.Pattern[str] | None:
    """Word-boundary pattern for the brand and its aliases (longest first)."""
    cleaned = sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True)
    if not cleaned:
        return None
    alternation = "|".join(re.escape(n) for n in cleaned)
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


async def evaluate_mention(text: str, brand_name: str, brand_aliases: list[str]) -> JudgeResult | None:
    """Rules judge (versioned): sentence-scoped detection of negated
    recommendations, adverse wording, contrast + alternative preference, and
    positive framing. Returns None when the brand is not mentioned at all.

    This is the deterministic judge the golden-set harness gates; the LLM
    judge (below) reuses its fallback behaviour.
    """
    pattern = _mention_pattern(brand_name, *brand_aliases)
    if pattern is None:
        return None
    match = pattern.search(text)
    if not match:
        # Fuzzy pass for alias/brand variants the exact pattern misses.
        fuzzy = find_mention(text, brand_name, *brand_aliases)
        if fuzzy is None:
            return None
        excerpt_target = fuzzy.excerpt
        match_surface = fuzzy.name
    else:
        match_surface = match.group(0)
        excerpt_target = ""

    # Judge the sentences that actually mention the brand.
    sentences = _SENTENCE_SPLIT.split(text)
    mentioning = [s for s in sentences if pattern.search(s)]
    if not mentioning and excerpt_target:
        mentioning = [excerpt_target]
    context = " ".join(mentioning) if mentioning else text

    negated = bool(_NEGATED_RECOMMEND.search(context))
    adverse = bool(_ADVERSE.search(context))
    contrast = bool(_CONTRAST.search(context))
    other_preferred = bool(_PREFERENCE_ELSEWHERE.search(context))

    recommended = not (negated or (contrast and other_preferred) or adverse)

    if _NEGATIVE.search(context) or negated or adverse:
        sentiment = "negative"
    elif contrast and other_preferred:
        sentiment = "mixed"
    elif _POSITIVE.search(context):
        sentiment = "positive"
    else:
        sentiment = "neutral"

    excerpt = mentioning[0].strip() if mentioning else match_surface
    return JudgeResult(
        recommended=recommended,
        sentiment=sentiment,
        rank_in_answer=1 if recommended else None,
        excerpt=excerpt[:500],
        judge_version=JUDGE_RULES_VERSION,
    )


_LLM_JUDGE_SYSTEM = (
    "You are a strict brand-visibility judge. Given an AI answer and a brand, decide: "
    "mentioned (brand/alias appears), recommended (the answer endorses choosing it), "
    "sentiment (positive|neutral|negative|mixed), and a short excerpt of the mentioning "
    "sentence. 'recommended' is false for negated or adverse mentions. "
    "Reply with JSON only: {\"mentioned\": bool, \"recommended\": bool, "
    "\"sentiment\": \"positive|neutral|negative|mixed\", \"excerpt\": str}."
)


async def _llm_judge(
    text: str,
    brand_name: str,
    brand_aliases: list[str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> JudgeResult | None:
    """OpenAI JSON judge (``JUDGE_MODE=llm``). Raises on any failure so the
    caller can fall back to the rules judge and record that version instead."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    payload = {
        "model": settings.judge_model,
        "messages": [
            {"role": "system", "content": _LLM_JUDGE_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {"brand": brand_name, "aliases": brand_aliases, "answer": text},
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(transport=transport, timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if not parsed.get("mentioned"):
        return None
    sentiment = str(parsed.get("sentiment", "neutral"))
    if sentiment not in ("positive", "neutral", "negative", "mixed"):
        sentiment = "neutral"
    return JudgeResult(
        recommended=bool(parsed.get("recommended", False)),
        sentiment=sentiment,
        rank_in_answer=1 if parsed.get("recommended") else None,
        excerpt=str(parsed.get("excerpt", ""))[:500],
        judge_version=f"llm:{settings.judge_model}:v1",
    )


async def judge_mention(
    text: str,
    brand_name: str,
    brand_aliases: list[str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> JudgeResult | None:
    """Configured judge (``JUDGE_MODE``): rules by default, LLM when opted in.

    The LLM judge falls back to the rules judge on any error, and the returned
    ``judge_version`` always says which judge actually produced the label.
    """
    if settings.judge_mode != "llm":
        return await evaluate_mention(text, brand_name, brand_aliases)
    try:
        result = await _llm_judge(text, brand_name, brand_aliases, transport=transport)
        return result
    except Exception as exc:  # fallback is the contract, never fabricate
        logger.warning("llm_judge_fallback", error=str(exc)[:200])
        return await evaluate_mention(text, brand_name, brand_aliases)


def judge_version_for(result: JudgeResult | None) -> str | None:
    return result.judge_version if result else None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


__all__ = [
    "JUDGE_RULES_VERSION",
    "DomainInfo",
    "JudgeResult",
    "MentionMatch",
    "classify_domain",
    "evaluate_mention",
    "extract_citations",
    "find_mention",
    "judge_mention",
    "judge_version_for",
    "normalize_domain",
]
