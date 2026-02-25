#!/usr/bin/env python3
"""Build an engineer-review gold set from curated MUA rationale pairs."""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

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
    parser.add_argument("--input-file", type=Path, default=Path("mua_rationale_train_v2_curated.jsonl"))
    parser.add_argument("--output-jsonl", type=Path, default=Path("mua_rationale_gold_review.jsonl"))
    parser.add_argument("--output-csv", type=Path, default=Path("mua_rationale_gold_review.csv"))
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


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


def deficiency_bucket(deficiency: str) -> str:
    toks = [
        tok
        for tok in re.findall(r"[a-z0-9]+", (deficiency or "").lower())
        if tok not in STOPWORDS
    ]
    return toks[0] if toks else "other"


def stratified_sample(rows: list[dict[str, Any]], n: int, rng: random.Random) -> list[dict[str, Any]]:
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_bucket[row["bucket"]].append(row)

    total = sum(len(v) for v in by_bucket.values())
    if n >= total:
        out = rows[:]
        rng.shuffle(out)
        return out

    # proportional allocation + remainder
    alloc: dict[str, int] = {}
    remainders: list[tuple[float, str]] = []
    used = 0
    for bucket, items in by_bucket.items():
        share = n * (len(items) / total)
        base = int(share)
        base = min(base, len(items))
        alloc[bucket] = base
        used += base
        remainders.append((share - base, bucket))
    remainders.sort(reverse=True)

    left = n - used
    for _, bucket in remainders:
        if left <= 0:
            break
        if alloc[bucket] < len(by_bucket[bucket]):
            alloc[bucket] += 1
            left -= 1

    sampled: list[dict[str, Any]] = []
    for bucket, count in alloc.items():
        sampled.extend(rng.sample(by_bucket[bucket], count))
    rng.shuffle(sampled)
    return sampled


def main() -> None:
    args = parse_args()
    if not args.input_file.exists():
        raise FileNotFoundError(args.input_file)
    rng = random.Random(args.seed)

    source_rows = load_jsonl(args.input_file)
    enriched: list[dict[str, Any]] = []
    for idx, row in enumerate(source_rows, start=1):
        messages = row.get("messages") or []
        if len(messages) < 3:
            continue
        user_prompt = messages[1]["content"]
        target = messages[2]["content"]
        sections = parse_sections(user_prompt)
        bucket = deficiency_bucket(sections["deficiency"])
        enriched.append(
            {
                "id": idx,
                "bucket": bucket,
                "deficiency": sections["deficiency"],
                "application": sections["application"],
                "environment": sections["environment"],
                "evidence": sections["evidence"],
                "user_prompt": user_prompt,
                "target_rationale": target,
            }
        )

    sample = stratified_sample(enriched, args.sample_size, rng)

    review_rows: list[dict[str, Any]] = []
    for order, row in enumerate(sample, start=1):
        review_rows.append(
            {
                "review_id": f"MUA-GOLD-{order:04d}",
                "bucket": row["bucket"],
                "deficiency": row["deficiency"],
                "application": row["application"],
                "environment": row["environment"],
                "evidence": row["evidence"],
                "candidate_rationale": row["target_rationale"],
                "review_status": "PENDING",
                "decision": "",
                "reviewer_notes": "",
                "revised_rationale": "",
            }
        )

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.output_jsonl.open("w", encoding="utf-8") as handle:
        for row in review_rows:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(review_rows[0].keys()))
        writer.writeheader()
        writer.writerows(review_rows)

    print(f"Source rows: {len(enriched)}")
    print(f"Gold review rows: {len(review_rows)}")
    print(f"Wrote JSONL: {args.output_jsonl}")
    print(f"Wrote CSV: {args.output_csv}")


if __name__ == "__main__":
    main()
