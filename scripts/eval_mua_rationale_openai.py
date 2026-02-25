#!/usr/bin/env python3
"""Evaluate MUA rationale generation using an OpenAI model via Responses API."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}

SECTION_RE = re.compile(
    r"Deficiency:\n(?P<deficiency>.*?)\n\nApplication:\n(?P<application>.*?)\n\nEnvironment:\n"
    r"(?P<environment>.*?)\n\nEvidence Cited:\n(?P<evidence>.*?)\n\nTask:",
    re.DOTALL | re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--val-file", type=Path, required=True)
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--predictions-out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--max-output-tokens", type=int, default=220)
    parser.add_argument("--sample-prints", type=int, default=3)
    return parser.parse_args()


def tokenize_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for tok in re.findall(r"[a-z0-9][a-z0-9_/-]{1,}", (text or "").lower()):
        if tok in STOPWORDS:
            continue
        if len(tok) < 3 and not re.search(r"\d", tok):
            continue
        terms.add(tok)
    return terms


def recall_score(reference: str, generated: str) -> float:
    ref_terms = tokenize_terms(reference)
    if not ref_terms:
        return 0.0
    gen_terms = tokenize_terms(generated)
    return len(ref_terms & gen_terms) / len(ref_terms)


def parse_sections(user_prompt: str) -> dict[str, str]:
    match = SECTION_RE.search(user_prompt or "")
    if not match:
        return {"deficiency": "", "application": "", "environment": "", "evidence": ""}
    return {
        "deficiency": match.group("deficiency").strip(),
        "application": match.group("application").strip(),
        "environment": match.group("environment").strip(),
        "evidence": match.group("evidence").strip(),
    }


def main() -> None:
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    rows = [json.loads(line) for line in args.val_file.read_text(encoding="utf-8").splitlines() if line]
    if args.limit > 0:
        rows = rows[: args.limit]

    client = OpenAI()
    preds: list[dict[str, Any]] = []

    def_scores: list[float] = []
    ctx_scores: list[float] = []
    ev_scores: list[float] = []
    tgt_scores: list[float] = []

    def_ok = 0
    ctx_ok = 0
    ev_ok = 0

    for idx, row in enumerate(rows, start=1):
        messages = row["messages"]
        system_msg = messages[0]["content"]
        user_msg = messages[1]["content"]
        target = messages[2]["content"]
        sections = parse_sections(user_msg)

        resp = client.responses.create(
            model=args.model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system_msg}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_msg}]},
            ],
            max_output_tokens=args.max_output_tokens,
            temperature=0,
        )
        generated = (resp.output_text or "").strip()

        def_recall = recall_score(sections["deficiency"], generated)
        ctx_recall = recall_score(f"{sections['application']} {sections['environment']}", generated)
        evidence_text = sections["evidence"]
        ev_recall = recall_score(evidence_text, generated) if "No explicit supporting evidence captured" not in evidence_text else 1.0
        tgt_recall = recall_score(target, generated)

        def_scores.append(def_recall)
        ctx_scores.append(ctx_recall)
        ev_scores.append(ev_recall)
        tgt_scores.append(tgt_recall)

        is_def_ok = def_recall >= 0.12
        is_ctx_ok = ctx_recall >= 0.10
        is_ev_ok = ev_recall >= 0.10
        def_ok += 1 if is_def_ok else 0
        ctx_ok += 1 if is_ctx_ok else 0
        ev_ok += 1 if is_ev_ok else 0

        preds.append(
            {
                "index": idx,
                "deficiency_recall": def_recall,
                "context_recall": ctx_recall,
                "evidence_recall": ev_recall,
                "target_overlap_recall": tgt_recall,
                "deficiency_ok": is_def_ok,
                "context_ok": is_ctx_ok,
                "evidence_ok": is_ev_ok,
                "generated_text": generated,
                "target_text": target,
            }
        )

        if idx <= args.sample_prints:
            print(f"--- Sample {idx} ---")
            print("Deficiency:", sections["deficiency"][:220])
            print("Generated:", generated[:420])
            print("Target:", target[:420])
            print(
                "Scores:",
                f"def={def_recall:.3f}",
                f"ctx={ctx_recall:.3f}",
                f"ev={ev_recall:.3f}",
                f"ovlp={tgt_recall:.3f}",
            )
        if idx % 10 == 0 or idx == len(rows):
            print(f"Evaluated {idx}/{len(rows)}", flush=True)

    total = len(rows)
    avg_def = sum(def_scores) / total if total else 0.0
    avg_ctx = sum(ctx_scores) / total if total else 0.0
    avg_ev = sum(ev_scores) / total if total else 0.0
    avg_tgt = sum(tgt_scores) / total if total else 0.0

    args.predictions_out.parent.mkdir(parents=True, exist_ok=True)
    with args.predictions_out.open("w", encoding="utf-8") as f:
        for pred in preds:
            f.write(json.dumps(pred, ensure_ascii=True))
            f.write("\n")

    print(f"Validation rows: {total}")
    print(f"Avg deficiency term recall: {avg_def:.4f}")
    print(f"Avg context term recall: {avg_ctx:.4f}")
    print(f"Avg evidence term recall: {avg_ev:.4f}")
    print(f"Avg target overlap recall: {avg_tgt:.4f}")
    print(f"Deficiency coverage pass rate: {def_ok/total:.4f} ({def_ok}/{total})")
    print(f"Context grounding pass rate: {ctx_ok/total:.4f} ({ctx_ok}/{total})")
    print(f"Evidence usage pass rate: {ev_ok/total:.4f} ({ev_ok}/{total})")
    print(f"Predictions written: {args.predictions_out}")


if __name__ == "__main__":
    main()
