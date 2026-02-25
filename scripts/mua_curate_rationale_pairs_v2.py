#!/usr/bin/env python3
"""Curate high-signal MUA rationale chat pairs for safer fine-tuning."""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter, defaultdict
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

PREFIX_BANLIST = (
    "see attached",
    "see attached.",
    "revise to reflect current drawing numbers",
    "the above certifications are based on",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-files",
        type=Path,
        nargs="+",
        default=[Path("mua_rationale_train.jsonl"), Path("mua_rationale_val.jsonl")],
        help="Input chat-format JSONL files to pool before curation.",
    )
    parser.add_argument(
        "--train-out",
        type=Path,
        default=Path("mua_rationale_train_v2_curated.jsonl"),
    )
    parser.add_argument(
        "--val-out",
        type=Path,
        default=Path("mua_rationale_val_v2_curated.jsonl"),
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("docs/mua_rationale_v2_curation_report.md"),
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-total", type=int, default=900)
    parser.add_argument("--val-fraction", type=float, default=0.2)
    parser.add_argument("--min-words", type=int, default=25)
    parser.add_argument("--max-words", type=int, default=140)
    parser.add_argument("--max-uppercase-ratio", type=float, default=0.65)
    parser.add_argument("--min-deficiency-recall", type=float, default=0.20)
    parser.add_argument("--min-context-recall", type=float, default=0.06)
    parser.add_argument("--min-evidence-recall", type=float, default=0.08)
    return parser.parse_args()


def normalize_spaces(text: str) -> str:
    return " ".join((text or "").split())


def uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


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


def deficiency_bucket(deficiency: str) -> str:
    tokens = [
        tok
        for tok in re.findall(r"[a-z0-9]+", (deficiency or "").lower())
        if tok not in STOPWORDS
    ]
    return tokens[0] if tokens else "other"


def allocate_counts(group_sizes: dict[str, int], target_size: int) -> dict[str, int]:
    if target_size <= 0 or not group_sizes:
        return {key: 0 for key in group_sizes}
    total = sum(group_sizes.values())
    alloc = {key: 0 for key in group_sizes}
    ideal: dict[str, float] = {}
    for key, size in group_sizes.items():
        share = (target_size * size) / total
        ideal[key] = share
        alloc[key] = min(size, math.floor(share))

    remaining = target_size - sum(alloc.values())
    order = sorted(
        group_sizes.keys(),
        key=lambda key: (ideal[key] - math.floor(ideal[key]), group_sizes[key]),
        reverse=True,
    )
    while remaining > 0:
        moved = False
        for key in order:
            if alloc[key] < group_sizes[key]:
                alloc[key] += 1
                remaining -= 1
                moved = True
                if remaining == 0:
                    break
        if not moved:
            break
    return alloc


def stratified_sample(
    rows: list[dict[str, Any]], key_name: str, sample_size: int, rng: random.Random
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row[key_name]].append(row)
    group_sizes = {k: len(v) for k, v in grouped.items()}
    alloc = allocate_counts(group_sizes, sample_size)
    sampled: list[dict[str, Any]] = []
    for k, count in alloc.items():
        if count <= 0:
            continue
        sampled.extend(rng.sample(grouped[k], count))
    rng.shuffle(sampled)
    return sampled


def row_quality(row: dict[str, Any], args: argparse.Namespace) -> tuple[bool, str, dict[str, float]]:
    messages = row.get("messages") or []
    if len(messages) < 3:
        return False, "malformed_messages", {}
    user_prompt = messages[-2].get("content", "")
    target = normalize_spaces(messages[-1].get("content", ""))
    sections = parse_sections(user_prompt)
    if not sections["deficiency"]:
        return False, "missing_sections", {}

    word_count = len(target.split())
    up_ratio = uppercase_ratio(target)
    d_recall = recall_score(sections["deficiency"], target)
    c_recall = recall_score(f"{sections['application']} {sections['environment']}", target)
    needs_evidence = "No explicit supporting evidence captured" not in sections["evidence"]
    e_recall = recall_score(sections["evidence"], target) if needs_evidence else 1.0

    prefix = " ".join(target.lower().split()[:8])
    if word_count < args.min_words:
        return False, "too_short", {}
    if word_count > args.max_words:
        return False, "too_long", {}
    if up_ratio > args.max_uppercase_ratio:
        return False, "all_caps_style", {}
    if d_recall < args.min_deficiency_recall:
        return False, "low_deficiency_grounding", {}
    if c_recall < args.min_context_recall:
        return False, "low_context_grounding", {}
    if needs_evidence and e_recall < args.min_evidence_recall:
        return False, "low_evidence_grounding", {}
    if prefix in PREFIX_BANLIST:
        return False, "boilerplate_prefix", {}

    quality_score = 0.50 * d_recall + 0.30 * c_recall + 0.20 * e_recall
    metrics = {
        "word_count": float(word_count),
        "uppercase_ratio": up_ratio,
        "deficiency_recall": d_recall,
        "context_recall": c_recall,
        "evidence_recall": e_recall,
        "quality_score": quality_score,
    }
    return True, "", metrics


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)

    pooled_rows: list[dict[str, Any]] = []
    for path in args.input_files:
        if not path.exists():
            raise FileNotFoundError(f"Missing input file: {path}")
        pooled_rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    total_input = len(pooled_rows)
    fail_counts: Counter[str] = Counter()
    dedupe_seen: set[str] = set()
    accepted: list[dict[str, Any]] = []

    for row in pooled_rows:
        ok, reason, metrics = row_quality(row, args)
        if not ok:
            fail_counts[reason] += 1
            continue

        target = normalize_spaces(row["messages"][-1]["content"]).lower()
        if target in dedupe_seen:
            fail_counts["duplicate_target"] += 1
            continue
        dedupe_seen.add(target)

        user_sections = parse_sections(row["messages"][-2]["content"])
        bucket = deficiency_bucket(user_sections["deficiency"])

        enriched = {
            "row": row,
            "bucket": bucket,
            **metrics,
        }
        accepted.append(enriched)

    accepted.sort(key=lambda x: x["quality_score"], reverse=True)

    target_total = min(args.target_total, len(accepted))
    selected = accepted[:target_total]
    selected_rows = [item["row"] for item in selected]

    val_size = max(1, int(round(target_total * args.val_fraction))) if target_total else 0
    val_size = min(val_size, target_total - 1) if target_total > 1 else 0
    train_size = target_total - val_size

    train_selected = stratified_sample(selected, "bucket", train_size, rng) if train_size else []
    train_ids = {id(item) for item in train_selected}
    val_selected = [item for item in selected if id(item) not in train_ids]

    train_rows = [item["row"] for item in train_selected]
    val_rows = [item["row"] for item in val_selected]

    write_jsonl(args.train_out, train_rows)
    write_jsonl(args.val_out, val_rows)

    def avg(name: str, rows: list[dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        return sum(row[name] for row in rows) / len(rows)

    all_metrics = selected
    train_metrics = train_selected
    val_metrics = val_selected

    bucket_counts = Counter(item["bucket"] for item in selected)
    train_buckets = Counter(item["bucket"] for item in train_selected)
    val_buckets = Counter(item["bucket"] for item in val_selected)

    lines = [
        "# MUA Rationale V2 Curation Report",
        "",
        f"- Input rows: **{total_input}**",
        f"- Rows passing quality filters (pre-cap): **{len(accepted)}**",
        f"- Rows selected after quality ranking cap (`target_total={args.target_total}`): **{target_total}**",
        f"- Train rows written: **{len(train_rows)}** -> `{args.train_out}`",
        f"- Val rows written: **{len(val_rows)}** -> `{args.val_out}`",
        "",
        "## Filter Thresholds",
        "",
        f"- min_words: `{args.min_words}`",
        f"- max_words: `{args.max_words}`",
        f"- max_uppercase_ratio: `{args.max_uppercase_ratio}`",
        f"- min_deficiency_recall: `{args.min_deficiency_recall}`",
        f"- min_context_recall: `{args.min_context_recall}`",
        f"- min_evidence_recall (when explicit evidence exists): `{args.min_evidence_recall}`",
        "",
        "## Quality Metrics (Selected Pool)",
        "",
        f"- avg quality_score: `{avg('quality_score', all_metrics):.4f}`",
        f"- avg deficiency_recall: `{avg('deficiency_recall', all_metrics):.4f}`",
        f"- avg context_recall: `{avg('context_recall', all_metrics):.4f}`",
        f"- avg evidence_recall: `{avg('evidence_recall', all_metrics):.4f}`",
        f"- avg word_count: `{avg('word_count', all_metrics):.2f}`",
        "",
        "## Quality Metrics (Train)",
        "",
        f"- avg quality_score: `{avg('quality_score', train_metrics):.4f}`",
        f"- avg deficiency_recall: `{avg('deficiency_recall', train_metrics):.4f}`",
        f"- avg context_recall: `{avg('context_recall', train_metrics):.4f}`",
        f"- avg evidence_recall: `{avg('evidence_recall', train_metrics):.4f}`",
        f"- avg word_count: `{avg('word_count', train_metrics):.2f}`",
        "",
        "## Quality Metrics (Validation)",
        "",
        f"- avg quality_score: `{avg('quality_score', val_metrics):.4f}`",
        f"- avg deficiency_recall: `{avg('deficiency_recall', val_metrics):.4f}`",
        f"- avg context_recall: `{avg('context_recall', val_metrics):.4f}`",
        f"- avg evidence_recall: `{avg('evidence_recall', val_metrics):.4f}`",
        f"- avg word_count: `{avg('word_count', val_metrics):.2f}`",
        "",
        "## Top Deficiency Buckets (Selected)",
        "",
    ]
    for bucket, count in bucket_counts.most_common(20):
        lines.append(f"- {bucket}: {count}")

    lines.extend(["", "## Top Deficiency Buckets (Train)", ""])
    for bucket, count in train_buckets.most_common(20):
        lines.append(f"- {bucket}: {count}")

    lines.extend(["", "## Top Deficiency Buckets (Validation)", ""])
    for bucket, count in val_buckets.most_common(20):
        lines.append(f"- {bucket}: {count}")

    lines.extend(["", "## Filter Drop Reasons", ""])
    for key, count in fail_counts.most_common():
        lines.append(f"- {key}: {count}")

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Input rows: {total_input}")
    print(f"Accepted rows (pre-cap): {len(accepted)}")
    print(f"Selected rows: {target_total}")
    print(f"Train rows: {len(train_rows)} -> {args.train_out}")
    print(f"Val rows: {len(val_rows)} -> {args.val_out}")
    print(f"Report: {args.report_out}")
    print(
        "Selected quality averages: "
        f"def={avg('deficiency_recall', all_metrics):.4f}, "
        f"ctx={avg('context_recall', all_metrics):.4f}, "
        f"ev={avg('evidence_recall', all_metrics):.4f}, "
        f"words={avg('word_count', all_metrics):.2f}"
    )


if __name__ == "__main__":
    main()
