#!/usr/bin/env python3
"""Generate MUA rationale drafts with a strict engineering template."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

TEMPLATE_SYSTEM_PROMPT = """You are a NASA materials and processes engineer.
Write a technically defensible MUA rationale using EXACTLY this section structure and headings:

Deficiency:
- State the specific screening gap or non-conformance.

Application Context:
- State where/how the material is used and relevant environment constraints.

Engineering Argument:
- Explain why usage is acceptable in this specific context.

Evidence and Controls:
- Cite provided evidence and state controls/mitigations.

Limits and Conditions:
- State explicit limits, assumptions, and conditions for continued acceptability.

Rules:
- Use only information from the prompt; do not invent tests, ratings, or heritage.
- Be concise and specific; avoid generic filler.
- If evidence is missing, say that explicitly and rely on conservative controls.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", type=Path, required=True, help="Chat-format JSONL input.")
    parser.add_argument("--output-file", type=Path, required=True, help="Output JSONL with drafts.")
    parser.add_argument("--model", type=str, default="gpt-4.1-2025-04-14")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on rows (0 = all).")
    parser.add_argument("--max-output-tokens", type=int, default=260)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--sample-prints", type=int, default=3)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")
    if not args.input_file.exists():
        raise FileNotFoundError(args.input_file)

    rows = load_rows(args.input_file)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    client = OpenAI()
    outputs: list[dict[str, Any]] = []

    for idx, row in enumerate(rows, start=1):
        messages = row.get("messages") or []
        if len(messages) < 2:
            continue
        user_msg = messages[1]["content"]
        target_msg = messages[2]["content"] if len(messages) > 2 else ""

        resp = client.responses.create(
            model=args.model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": TEMPLATE_SYSTEM_PROMPT}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_msg}]},
            ],
            max_output_tokens=args.max_output_tokens,
            temperature=args.temperature,
        )
        draft = (resp.output_text or "").strip()

        out = {
            "index": idx,
            "model": args.model,
            "input_user": user_msg,
            "draft": draft,
            "target_text": target_msg,
        }
        outputs.append(out)

        if idx <= args.sample_prints:
            print(f"--- Draft Sample {idx} ---")
            print(draft[:700])
        if idx % 10 == 0 or idx == len(rows):
            print(f"Generated {idx}/{len(rows)}", flush=True)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    with args.output_file.open("w", encoding="utf-8") as handle:
        for out in outputs:
            handle.write(json.dumps(out, ensure_ascii=True))
            handle.write("\n")

    print(f"Wrote drafts: {len(outputs)} -> {args.output_file}")


if __name__ == "__main__":
    main()
