#!/usr/bin/env python3
"""Judge MUA drafts with a rubric and rewrite low-scoring outputs once."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

JUDGE_PROMPT = """You are a senior NASA M&P reviewer.
Score the draft on a 0-5 scale for each criterion:
1) deficiency_coverage
2) context_grounding
3) evidence_usage
4) no_hallucination
5) engineering_defensibility

Return ONLY strict JSON with keys:
{
  "deficiency_coverage": <0-5 int>,
  "context_grounding": <0-5 int>,
  "evidence_usage": <0-5 int>,
  "no_hallucination": <0-5 int>,
  "engineering_defensibility": <0-5 int>,
  "summary": "<short critique>",
  "must_fix": ["<item1>", "..."]
}
"""

REWRITE_PROMPT = """You are a NASA materials and processes engineer revising a draft.
Revise the draft to address reviewer findings while preserving technical facts from input.
Use EXACTLY this section structure:

Deficiency:
Application Context:
Engineering Argument:
Evidence and Controls:
Limits and Conditions:

Rules:
- Do not invent evidence.
- Be specific and concise.
- Explicitly address each must-fix item.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts-file", type=Path, required=True, help="JSONL from mua_generate_template_openai.py")
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--model", type=str, default="gpt-4.1-2025-04-14")
    parser.add_argument("--threshold-total", type=int, default=18, help="Rewrite if total score < threshold.")
    parser.add_argument("--threshold-min-criterion", type=int, default=3, help="Rewrite if any criterion below this.")
    parser.add_argument("--max-output-tokens", type=int, default=280)
    parser.add_argument("--judge-max-output-tokens", type=int, default=420)
    parser.add_argument("--sample-prints", type=int, default=3)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def parse_judge_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def score_total(j: dict[str, Any]) -> int:
    keys = [
        "deficiency_coverage",
        "context_grounding",
        "evidence_usage",
        "no_hallucination",
        "engineering_defensibility",
    ]
    total = 0
    for key in keys:
        total += int(j.get(key, 0))
    return total


def needs_rewrite(judge: dict[str, Any], total_threshold: int, min_criterion: int) -> bool:
    keys = [
        "deficiency_coverage",
        "context_grounding",
        "evidence_usage",
        "no_hallucination",
        "engineering_defensibility",
    ]
    total = score_total(judge)
    if total < total_threshold:
        return True
    return any(int(judge.get(k, 0)) < min_criterion for k in keys)


def main() -> None:
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")
    if not args.drafts_file.exists():
        raise FileNotFoundError(args.drafts_file)

    client = OpenAI()
    rows = load_jsonl(args.drafts_file)
    outputs: list[dict[str, Any]] = []
    rewrites = 0

    for idx, row in enumerate(rows, start=1):
        user_prompt = row.get("input_user", "")
        draft = row.get("draft", "")

        judge = None
        judge_text = ""
        for attempt in range(2):
            user_suffix = (
                "\n\nReturn ONLY compact JSON, no markdown, no prose."
                if attempt == 1
                else ""
            )
            judge_resp = client.responses.create(
                model=args.model,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": JUDGE_PROMPT}]},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f"Input:\n{user_prompt}\n\nDraft:\n{draft}{user_suffix}",
                            }
                        ],
                    },
                ],
                max_output_tokens=args.judge_max_output_tokens,
                temperature=0,
            )
            judge_text = (judge_resp.output_text or "").strip()
            try:
                judge = parse_judge_json(judge_text)
                break
            except Exception:
                judge = None
                continue
        if judge is None:
            # Fall back to a conservative failing score if parser still fails.
            judge = {
                "deficiency_coverage": 0,
                "context_grounding": 0,
                "evidence_usage": 0,
                "no_hallucination": 0,
                "engineering_defensibility": 0,
                "summary": "Judge JSON parse failed; forced rewrite.",
                "must_fix": ["Provide complete rubric-scored rationale with all required sections."],
                "raw_judge_text": judge_text[:2000],
            }
        total = score_total(judge)
        rewrite = needs_rewrite(judge, args.threshold_total, args.threshold_min_criterion)

        final_text = draft
        if rewrite:
            rewrites += 1
            must_fix = judge.get("must_fix", [])
            rewrite_user = (
                f"Input:\n{user_prompt}\n\nDraft:\n{draft}\n\n"
                f"Reviewer summary:\n{judge.get('summary', '')}\n\n"
                f"Must-fix items:\n- " + "\n- ".join(str(x) for x in must_fix)
            )
            rewrite_resp = client.responses.create(
                model=args.model,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": REWRITE_PROMPT}]},
                    {"role": "user", "content": [{"type": "input_text", "text": rewrite_user}]},
                ],
                max_output_tokens=args.max_output_tokens,
                temperature=0,
            )
            final_text = (rewrite_resp.output_text or "").strip()

        out = {
            **row,
            "judge": judge,
            "judge_total": total,
            "rewritten": rewrite,
            "final_text": final_text,
        }
        outputs.append(out)

        if idx <= args.sample_prints:
            print(f"--- Judge Sample {idx} ---")
            print("total:", total, "rewritten:", rewrite)
            print("summary:", judge.get("summary", ""))
            print("final:", final_text[:450])
        if idx % 10 == 0 or idx == len(rows):
            print(f"Judged {idx}/{len(rows)}", flush=True)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    with args.output_file.open("w", encoding="utf-8") as handle:
        for out in outputs:
            handle.write(json.dumps(out, ensure_ascii=True))
            handle.write("\n")

    print(f"Rows: {len(outputs)}")
    print(f"Rewrites applied: {rewrites}")
    print(f"Wrote judged/revised drafts: {args.output_file}")


if __name__ == "__main__":
    main()
