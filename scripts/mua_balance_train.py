#!/usr/bin/env python3
"""Create a class-balanced MUA training JSONL by undersampling majority classes."""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

CATEGORY_RE = re.compile(r"Category:\s*(IV|III|II|I)\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-train", type=Path, default=Path("mua_train.jsonl"))
    parser.add_argument("--output-train", type=Path, default=Path("mua_train_balanced.jsonl"))
    parser.add_argument(
        "--max-cat-i",
        type=int,
        default=400,
        help="Maximum number of Category I records to retain.",
    )
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def extract_category(row: dict) -> str:
    assistant = row["messages"][-1]["content"]
    match = CATEGORY_RE.search(assistant)
    if not match:
        return ""
    return match.group(1).upper()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)

    rows = [json.loads(line) for line in args.input_train.read_text(encoding="utf-8").splitlines() if line]
    by_category: dict[str, list[dict]] = {"I": [], "II": [], "III": [], "IV": []}

    for row in rows:
        category = extract_category(row)
        if category in by_category:
            by_category[category].append(row)

    selected: list[dict] = []
    cat_i = by_category["I"]
    if len(cat_i) > args.max_cat_i:
        selected.extend(rng.sample(cat_i, args.max_cat_i))
    else:
        selected.extend(cat_i)

    selected.extend(by_category["II"])
    selected.extend(by_category["III"])
    selected.extend(by_category["IV"])
    rng.shuffle(selected)

    args.output_train.parent.mkdir(parents=True, exist_ok=True)
    with args.output_train.open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")

    counts = Counter(extract_category(row) for row in selected)
    print(f"Input rows: {len(rows)}")
    print(f"Output rows: {len(selected)}")
    print(f"Category counts: {dict(counts)}")
    print(f"Wrote: {args.output_train}")


if __name__ == "__main__":
    main()
