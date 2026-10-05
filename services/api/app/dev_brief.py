"""PR-ready dev brief generated from one audit snapshot (FR-17).

The brief is a markdown document an operator can paste into a PR/issue for the
client's developers: findings grouped by fix owner, every item rule-coded with
its suggested fix and affected URL, plus the AI-crawler access table and
PageSpeed summary from the same crawl. Because findings are rule-coded, the
"how to verify" section is mechanical: re-run the audit and the same rules are
checked again (resolved items are marked verified automatically).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

CATEGORY_LABELS: dict[str, str] = {
    "schema": "Structured data",
    "meta": "Meta tags",
    "robots": "robots.txt / AI crawlers",
    "llms_txt": "llms.txt",
    "sitemap": "Sitemap",
    "speed": "Speed",
    "entity": "Content / entity",
}

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class BriefFinding:
    """One finding row as needed by the brief (DB rows map directly)."""

    category: str
    severity: str
    rule: str
    detail: str
    url: str | None
    fix_owner: str
    status: str
    suggested_fix: str | None = None


def _severity_rank(finding: BriefFinding) -> tuple[int, str, str]:
    return (_SEVERITY_ORDER.get(finding.severity, 9), finding.category, finding.rule)


def _finding_lines(finding: BriefFinding) -> list[str]:
    label = CATEGORY_LABELS.get(finding.category, finding.category)
    lines = [f"- [ ] **{finding.severity.upper()} · {label.lower()} · `{finding.rule}`** — {finding.detail}"]
    if finding.url:
        lines.append(f"  - URL: {finding.url}")
    if finding.suggested_fix:
        lines.append(f"  - Fix: {finding.suggested_fix}")
    return lines


def _robots_section(summary: dict[str, Any]) -> list[str]:
    rules: list[dict[str, Any]] = list(summary.get("robots_rules") or [])
    if not rules:
        return ["_No robots.txt groups parsed (file missing or unreachable)._", ""]
    lines = ["| AI crawler | Matched group | Access | Rule |", "| --- | --- | --- | --- |"]
    for rule in rules:
        access = "✅ allowed" if rule.get("allowed") else "⛔ blocked"
        lines.append(
            f"| {rule.get('bot', '?')} | {rule.get('group', '—')} | {access} | {rule.get('rule') or '—'} |"
        )
    lines.append("")
    return lines


def _speed_section(summary: dict[str, Any]) -> list[str]:
    speed: dict[str, Any] = dict(summary.get("speed") or {})
    status = speed.get("status")
    if status == "ok":
        parts = []
        if speed.get("performance_score") is not None:
            parts.append(f"Performance **{speed['performance_score']}/100**")
        if speed.get("lcp_ms") is not None:
            parts.append(f"LCP {round(speed['lcp_ms'] / 1000, 1)}s")
        if speed.get("cls") is not None:
            parts.append(f"CLS {speed['cls']}")
        if speed.get("tbt_ms") is not None:
            parts.append(f"TBT {speed['tbt_ms']}ms")
        return ["Mobile PageSpeed Insights: " + " · ".join(parts) + ".", ""]
    if status == "not_configured":
        return ["Mobile PageSpeed Insights: _not configured — set `PAGESPEED_API_KEY` to include Lighthouse metrics._", ""]
    if status == "error":
        return [f"Mobile PageSpeed Insights: _unavailable — {speed.get('reason', 'unknown error')}_", ""]
    return []


def build_dev_brief(
    *,
    client_name: str,
    audit_id: str,
    finished_at: datetime | None,
    score: float | None,
    summary: dict[str, Any],
    findings: list[BriefFinding],
) -> str:
    """Render the markdown dev brief for one audit snapshot."""
    host = str(summary.get("host") or summary.get("base_url") or "—")
    finished = finished_at.isoformat() if finished_at else "in progress"
    open_items = [f for f in findings if f.status in ("open", "in_progress")]
    verified = [f for f in findings if f.status == "fixed"]
    ignored = [f for f in findings if f.status == "ignored"]
    team = sorted([f for f in open_items if f.fix_owner != "client_dev"], key=_severity_rank)
    client_dev = sorted([f for f in open_items if f.fix_owner == "client_dev"], key=_severity_rank)

    lines: list[str] = [
        f"# Site audit dev brief — {client_name}",
        "",
        f"**Site:** {host}  ",
        f"**Audit:** `{audit_id}` · {finished} · **score {round(score) if score is not None else '—'}/100**  ",
        f"**Crawl:** {summary.get('pages_crawled', 0)} pages · {summary.get('sitemap_urls', 0)} sitemap URLs",
        "",
        f"**Open items:** {len(open_items)} ({len(team)} team · {len(client_dev)} client dev) · "
        f"**verified fixed:** {len(verified)} · **ignored:** {len(ignored)}",
        "",
        "## How to verify these fixes",
        "",
        "Every finding is rule-coded. After a fix lands, open Footnote → Site Audit and run "
        "**Verify fixes (re-run)**; the same rules are re-checked and resolved items move to "
        "*verified* automatically.",
        "",
        "## AI crawler access",
        "",
    ]
    lines.extend(_robots_section(summary))
    lines.append("## PageSpeed (mobile)")
    lines.append("")
    lines.extend(_speed_section(summary))

    if team:
        lines.extend(["## Fix checklist — team", ""])
        for finding in team:
            lines.extend(_finding_lines(finding))
        lines.append("")
    if client_dev:
        lines.extend(["## Fix checklist — client dev", ""])
        for finding in client_dev:
            lines.extend(_finding_lines(finding))
        lines.append("")
    if not open_items:
        lines.extend(["_No open findings — clean audit._", ""])
    if verified:
        lines.extend(["## Verified fixed in this snapshot", ""])
        for finding in sorted(verified, key=_severity_rank):
            lines.append(
                f"- ✅ `{finding.rule}` — {finding.detail}"
                + (f" ({finding.url})" if finding.url else "")
            )
        lines.append("")
    if ignored:
        lines.extend(["## Ignored (accepted risk)", ""])
        for finding in sorted(ignored, key=_severity_rank):
            lines.append(f"- ⏭️ `{finding.rule}` — {finding.detail}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
