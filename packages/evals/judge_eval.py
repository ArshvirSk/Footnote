"""Golden-set evaluation harness + agreement report for the mention judge.

Fixtures live in ``golden_set.json`` (hand-labelled: mention, recommendation,
sentiment per answer). The report shows overall accuracy plus per-axis
agreement (mention detection / recommendation / sentiment) and a sentiment
confusion matrix, so a judge change can be reviewed rather than eyeballed.

Run:  PYTHONPATH=. python packages/evals/judge_eval.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from services.workers.app.parser import JUDGE_RULES_VERSION, evaluate_mention

GOLDEN_PATH = Path(__file__).with_name("golden_set.json")
MIN_GOLDEN_CASES = 30


@dataclass
class GoldenTestCase:
    id: str
    brand_name: str
    aliases: list[str]
    answer_text: str
    expected_recommended: bool
    expected_sentiment: str
    expect_none: bool = False  # brand not mentioned at all


def load_golden_set(path: Path = GOLDEN_PATH) -> list[GoldenTestCase]:
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return [
        GoldenTestCase(
            id=item["id"],
            brand_name=item["brand_name"],
            aliases=list(item.get("aliases") or []),
            answer_text=item["answer_text"],
            expected_recommended=bool(item.get("expected_recommended", False)),
            expected_sentiment=str(item.get("expected_sentiment", "neutral")),
            expect_none=bool(item.get("expect_none", False)),
        )
        for item in raw
    ]


# Backwards-compatible name: the fixtures used to live inline here.
GOLDEN_SET: list[GoldenTestCase] = load_golden_set()


class SentimentConfusion(BaseModel):
    expected: str
    predicted: str
    count: int


class EvalResults(BaseModel):
    total: int
    passed: int
    failed: int
    accuracy: float
    judge_version: str
    # Per-axis agreement (each axis is only scored where it applies).
    mention_agreement: float
    recommendation_agreement: float
    sentiment_agreement: float
    confusion: list[SentimentConfusion]
    failures: list[dict[str, Any]]


async def run_judge_eval(cases: list[GoldenTestCase] | None = None) -> EvalResults:
    """Run the rules judge over the golden set and compute the agreement report."""
    golden = cases if cases is not None else GOLDEN_SET
    passed = 0
    failures: list[dict[str, Any]] = []

    mention_hits = mention_total = 0
    rec_hits = rec_total = 0
    sent_hits = sent_total = 0
    confusion_counts: dict[tuple[str, str], int] = {}

    for case in golden:
        result = await evaluate_mention(case.answer_text, case.brand_name, case.aliases)
        predicted_none = result is None
        expected_none = case.expect_none

        # Mention detection axis
        mention_total += 1
        if predicted_none == expected_none:
            mention_hits += 1

        if expected_none:
            if result is None:
                passed += 1
            else:
                failures.append(
                    {
                        "id": case.id,
                        "axis": "mention",
                        "reason": "Expected no mention, got a result",
                        "actual": {"rec": result.recommended, "sent": result.sentiment},
                    }
                )
            continue

        if result is None:
            failures.append(
                {"id": case.id, "axis": "mention", "reason": "Expected a mention, got None"}
            )
            continue

        rec_total += 1
        if result.recommended == case.expected_recommended:
            rec_hits += 1
        sent_total += 1
        if result.sentiment == case.expected_sentiment:
            sent_hits += 1
        confusion_counts[(case.expected_sentiment, result.sentiment)] = (
            confusion_counts.get((case.expected_sentiment, result.sentiment), 0) + 1
        )

        if result.recommended == case.expected_recommended and result.sentiment == case.expected_sentiment:
            passed += 1
        else:
            failures.append(
                {
                    "id": case.id,
                    "axis": "judgement",
                    "expected": {"rec": case.expected_recommended, "sent": case.expected_sentiment},
                    "actual": {"rec": result.recommended, "sent": result.sentiment},
                    "excerpt": result.excerpt[:120],
                }
            )

    total = len(golden)
    return EvalResults(
        total=total,
        passed=passed,
        failed=len(failures),
        accuracy=(passed / total) if total else 0.0,
        judge_version=JUDGE_RULES_VERSION,
        mention_agreement=(mention_hits / mention_total) if mention_total else 0.0,
        recommendation_agreement=(rec_hits / rec_total) if rec_total else 0.0,
        sentiment_agreement=(sent_hits / sent_total) if sent_total else 0.0,
        confusion=[
            SentimentConfusion(expected=exp, predicted=pred, count=count)
            for (exp, pred), count in sorted(confusion_counts.items())
        ],
        failures=failures,
    )


def format_report(results: EvalResults) -> str:
    lines = [
        f"Judge: {results.judge_version}",
        f"Golden set: {results.total} fixtures (min {MIN_GOLDEN_CASES})",
        f"Overall accuracy: {results.accuracy * 100:.1f}% ({results.passed}/{results.total})",
        f"Mention agreement:      {results.mention_agreement * 100:.1f}%",
        f"Recommendation agreement: {results.recommendation_agreement * 100:.1f}%",
        f"Sentiment agreement:    {results.sentiment_agreement * 100:.1f}%",
        "Sentiment confusion (expected -> predicted):",
    ]
    if results.confusion:
        for row in results.confusion:
            marker = "OK " if row.expected == row.predicted else "ERR"
            lines.append(f"  [{marker}] {row.expected:9s} -> {row.predicted:9s} x{row.count}")
    else:
        lines.append("  (no mentioned fixtures)")
    if results.failures:
        lines.append("Failures:")
        lines.append(json.dumps(results.failures, indent=2))
    return "\n".join(lines)


if __name__ == "__main__":
    print("Running Judge Evaluation...")
    res = asyncio.run(run_judge_eval())
    print(format_report(res))
    raise SystemExit(0 if res.failed == 0 else 1)
