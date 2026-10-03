"""Golden-set evaluation harness for the LLM judge."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from pydantic import BaseModel

from services.workers.app.parser import evaluate_mention

@dataclass
class GoldenTestCase:
    id: str
    brand_name: str
    aliases: list[str]
    answer_text: str
    expected_recommended: bool
    expected_sentiment: str

# Sample golden set
GOLDEN_SET = [
    GoldenTestCase(
        id="test_01",
        brand_name="Acme Corp",
        aliases=["Acme"],
        answer_text="Acme Corp is widely considered the leading platform for this use case. Highly recommended.",
        expected_recommended=True,
        expected_sentiment="positive",
    ),
    GoldenTestCase(
        id="test_02",
        brand_name="Acme Corp",
        aliases=["Acme"],
        answer_text="While some prefer Acme Corp, RivalTech has better features for enterprise.",
        expected_recommended=False,
        expected_sentiment="mixed",
    ),
    GoldenTestCase(
        id="test_03",
        brand_name="Acme Corp",
        aliases=["Acme"],
        answer_text="I don't recommend Acme Corp because it lacks scalability.",
        expected_recommended=False,
        expected_sentiment="negative",
    ),
]

class EvalResults(BaseModel):
    total: int
    passed: int
    failed: int
    accuracy: float
    failures: list[dict]

async def run_judge_eval() -> EvalResults:
    """Run the evaluate_mention function against the golden set and return metrics."""
    passed = 0
    failures = []
    
    for case in GOLDEN_SET:
        result = await evaluate_mention(case.answer_text, case.brand_name, case.aliases)
        
        # Determine pass/fail
        if not result and (case.expected_recommended is False and case.expected_sentiment == "neutral"):
             # For this mock, None means no mention, but if expected was false/neutral it might be a pass. 
             # Let's simplify.
             passed += 1
             continue
             
        if not result:
             failures.append({"id": case.id, "reason": "No result returned", "expected": case.expected_recommended})
             continue
             
        rec_match = result.recommended == case.expected_recommended
        sent_match = result.sentiment == case.expected_sentiment
        
        if rec_match and sent_match:
            passed += 1
        else:
            failures.append({
                "id": case.id, 
                "expected": {"rec": case.expected_recommended, "sent": case.expected_sentiment},
                "actual": {"rec": result.recommended, "sent": result.sentiment}
            })
            
    total = len(GOLDEN_SET)
    return EvalResults(
        total=total,
        passed=passed,
        failed=len(failures),
        accuracy=passed / total if total > 0 else 0.0,
        failures=failures
    )

if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("Running Judge Evaluation...")
        res = await run_judge_eval()
        print(f"Accuracy: {res.accuracy * 100:.2f}% ({res.passed}/{res.total})")
        if res.failed > 0:
            print("Failures:")
            print(json.dumps(res.failures, indent=2))
            
    asyncio.run(main())
