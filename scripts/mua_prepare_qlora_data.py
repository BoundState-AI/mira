#!/usr/bin/env python3
"""Prepare MUA chat-format datasets for local QLoRA experiments."""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SYSTEM_PROMPT = (
    "You are a NASA materials compliance expert. Given a material, its application, "
    "environment, and issue, determine the correct MUA category (I, II, III, or IV), "
    "the determination (APPROVED, APPROVED_WITH_LIMITS, or DENIED), and write the "
    "engineering rationale."
)

ALLOWED_CATEGORIES = ("I", "II", "III", "IV")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("/mnt/d/BoundState/BoundState_other/BoundState/data/mua_v6_cleaned.jsonl"),
        help="Path to source MUA JSONL.",
    )
    parser.add_argument(
        "--train-out",
        type=Path,
        default=Path("mua_train.jsonl"),
        help="Output training JSONL path.",
    )
    parser.add_argument(
        "--val-out",
        type=Path,
        default=Path("mua_val.jsonl"),
        help="Output validation JSONL path.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("docs/mua_qlora_corpus_analysis.md"),
        help="Analysis report output path.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.7,
        help="Minimum confidence threshold for usable records.",
    )
    parser.add_argument(
        "--train-size",
        type=int,
        default=1400,
        help="Requested training examples (after split).",
    )
    parser.add_argument(
        "--val-size",
        type=int,
        default=553,
        help="Requested validation examples.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--max-rationale-tokens",
        type=int,
        default=1024,
        help="Maximum token count for rationale using whitespace token proxy.",
    )
    return parser.parse_args()


def normalize_category(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip().upper()
    if text in ALLOWED_CATEGORIES:
        return text
    match = re.search(r"\b(IV|III|II|I)\b", text)
    if match:
        cat = match.group(1)
        return cat if cat in ALLOWED_CATEGORIES else ""
    return ""


def normalize_determination(raw: Any) -> str:
    value = str(raw or "").strip().upper()
    if value == "APPROVED":
        return "APPROVED"
    if value in {"DENIED", "REJECTED", "CANCELLED"}:
        return "DENIED"
    return "APPROVED_WITH_LIMITS"


def clean_text(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "True" if value else "False"
    text = str(value).strip()
    return text if text else default


def truncate_rationale(text: str, max_tokens: int) -> tuple[str, bool]:
    # Dependency-free proxy tokenization: whitespace tokens.
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text, False
    return " ".join(tokens[:max_tokens]), True


def format_user_prompt(record: dict[str, Any]) -> str:
    environment = record.get("environment") or {}
    issues = record.get("issues") or []
    issues_text = ", ".join(str(issue).strip() for issue in issues if str(issue).strip()) or "N/A"
    return (
        f"Material: {clean_text(record.get('material_designation'))}\n"
        f"Family: {clean_text(record.get('material_family'))}\n"
        f"Specification: {clean_text(record.get('specification'))}\n"
        f"Environment: {clean_text(environment.get('raw_text'))}\n"
        f"Temperature: {clean_text(environment.get('temperature_f'))}°F\n"
        f"Pressure: {clean_text(environment.get('pressure_psia'))} PSIA\n"
        f"Habitable: {clean_text(environment.get('is_habitable'))}\n"
        f"Issue: {issues_text}\n"
        f"Application: {clean_text(record.get('application'))}"
    )


def format_assistant_response(record: dict[str, Any], rationale: str) -> str:
    return (
        f"Category: {record['category']}\n"
        f"Determination: {record['determination_3class']}\n"
        f"Rationale: {rationale}"
    )


def allocate_counts(group_sizes: dict[str, int], target_size: int, allow_exceed: bool) -> dict[str, int]:
    if target_size <= 0 or not group_sizes:
        return {key: 0 for key in group_sizes}

    total = sum(group_sizes.values())
    allocations = {key: 0 for key in group_sizes}
    ideals: dict[str, float] = {}
    for key, size in group_sizes.items():
        ideal = (target_size * size) / total
        ideals[key] = ideal
        base = math.floor(ideal)
        if not allow_exceed:
            base = min(base, size)
        allocations[key] = base

    remaining = target_size - sum(allocations.values())
    if remaining <= 0:
        return allocations

    order = sorted(
        group_sizes.keys(),
        key=lambda key: (ideals[key] - math.floor(ideals[key]), group_sizes[key]),
        reverse=True,
    )

    while remaining > 0:
        progressed = False
        for key in order:
            cap = math.inf if allow_exceed else group_sizes[key]
            if allocations[key] < cap:
                allocations[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break

    return allocations


def stratified_sample_ids(
    grouped_ids: dict[str, list[int]],
    target_size: int,
    rng: random.Random,
) -> list[int]:
    group_sizes = {key: len(values) for key, values in grouped_ids.items() if values}
    if not group_sizes or target_size <= 0:
        return []

    allocations = allocate_counts(group_sizes, target_size, allow_exceed=False)
    sampled: list[int] = []
    for key, count in allocations.items():
        if count <= 0:
            continue
        choices = grouped_ids[key]
        sampled.extend(rng.sample(choices, count))
    rng.shuffle(sampled)
    return sampled


def pct(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return (count / total) * 100.0


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)

    records_by_id: dict[int, dict[str, Any]] = {}
    all_category_counts: Counter[str] = Counter()
    usable_category_counts: Counter[str] = Counter()
    all_issue_counts: Counter[str] = Counter()
    usable_issue_counts: Counter[str] = Counter()
    raw_determination_counts: Counter[str] = Counter()
    determination_3class_counts: Counter[str] = Counter()
    missing_counts: Counter[str] = Counter()

    total_records = 0
    usable_ids: list[int] = []
    truncated_rationale_count = 0

    with args.input.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            total_records += 1
            row = json.loads(line)
            category = normalize_category(row.get("category"))
            determination_raw = clean_text(row.get("determination"), default="UNKNOWN").upper()
            determination_3class = normalize_determination(determination_raw)
            rationale = clean_text(row.get("rationale"), default="")
            application = clean_text(row.get("application"), default="")
            confidence = row.get("confidence")

            if category:
                all_category_counts[category] += 1
            raw_determination_counts[determination_raw] += 1
            for issue in (row.get("issues") or []):
                issue_norm = clean_text(issue).lower()
                if issue_norm != "n/a":
                    all_issue_counts[issue_norm] += 1

            usable = True
            if not category:
                missing_counts["category"] += 1
                usable = False
            if not rationale:
                missing_counts["rationale"] += 1
                usable = False
            if not application:
                missing_counts["application"] += 1
                usable = False
            if confidence is None or confidence < args.min_confidence:
                missing_counts[f"confidence_lt_{args.min_confidence}"] += 1
                usable = False

            if not usable:
                continue

            truncated_rationale, was_truncated = truncate_rationale(
                rationale, args.max_rationale_tokens
            )
            if was_truncated:
                truncated_rationale_count += 1

            normalized_record = dict(row)
            normalized_record["_id"] = idx
            normalized_record["category"] = category
            normalized_record["determination_3class"] = determination_3class
            normalized_record["rationale"] = truncated_rationale

            records_by_id[idx] = normalized_record
            usable_ids.append(idx)
            usable_category_counts[category] += 1
            determination_3class_counts[determination_3class] += 1
            for issue in (row.get("issues") or []):
                issue_norm = clean_text(issue).lower()
                if issue_norm != "n/a":
                    usable_issue_counts[issue_norm] += 1

    grouped_all: dict[str, list[int]] = defaultdict(list)
    for rid in usable_ids:
        grouped_all[records_by_id[rid]["category"]].append(rid)

    effective_val_size = min(args.val_size, len(usable_ids))
    val_ids = stratified_sample_ids(grouped_all, effective_val_size, rng)
    val_id_set = set(val_ids)
    pool_ids = [rid for rid in usable_ids if rid not in val_id_set]

    grouped_pool: dict[str, list[int]] = defaultdict(list)
    for rid in pool_ids:
        grouped_pool[records_by_id[rid]["category"]].append(rid)

    requested_train_size = args.train_size
    unique_pool_size = len(pool_ids)
    if requested_train_size > unique_pool_size:
        raise ValueError(
            f"Requested train size ({requested_train_size}) exceeds unique train pool "
            f"({unique_pool_size}) after validation split. Upsampling is disabled."
        )
    effective_train_size = requested_train_size

    train_ids = stratified_sample_ids(
        grouped_pool,
        effective_train_size,
        rng,
    )

    train_rows: list[dict[str, Any]] = []
    val_rows: list[dict[str, Any]] = []

    for rid in train_ids:
        record = records_by_id[rid]
        train_rows.append(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": format_user_prompt(record)},
                    {
                        "role": "assistant",
                        "content": format_assistant_response(record, record["rationale"]),
                    },
                ]
            }
        )

    for rid in val_ids:
        record = records_by_id[rid]
        val_rows.append(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": format_user_prompt(record)},
                    {
                        "role": "assistant",
                        "content": format_assistant_response(record, record["rationale"]),
                    },
                ]
            }
        )

    write_jsonl(args.train_out, train_rows)
    write_jsonl(args.val_out, val_rows)

    train_category_counts: Counter[str] = Counter()
    for rid in train_ids:
        train_category_counts[records_by_id[rid]["category"]] += 1

    val_category_counts: Counter[str] = Counter()
    for rid in val_ids:
        val_category_counts[records_by_id[rid]["category"]] += 1

    report_lines = [
        "# MUA QLoRA Corpus Analysis",
        "",
        f"- Source file: `{args.input}`",
        f"- Total records: **{total_records}**",
        (
            f"- Usable records (category + rationale + application + confidence >= "
            f"{args.min_confidence}): **{len(usable_ids)}**"
        ),
        f"- Rationale truncated at {args.max_rationale_tokens} tokens (whitespace proxy): **{truncated_rationale_count}** records",
        "",
        "## Category Distribution (All Records with Category)",
        "",
    ]

    for cat in ALLOWED_CATEGORIES:
        count = all_category_counts.get(cat, 0)
        report_lines.append(f"- {cat}: {count}")

    report_lines.extend(
        [
            "",
            "## Category Distribution (Usable Records)",
            "",
        ]
    )
    for cat in ALLOWED_CATEGORIES:
        count = usable_category_counts.get(cat, 0)
        report_lines.append(f"- {cat}: {count} ({pct(count, len(usable_ids)):.2f}%)")

    report_lines.extend(
        [
            "",
            "## Determination Distribution (Usable, 3-Class Mapping)",
            "",
        ]
    )
    for key in ("APPROVED", "APPROVED_WITH_LIMITS", "DENIED"):
        count = determination_3class_counts.get(key, 0)
        report_lines.append(f"- {key}: {count} ({pct(count, len(usable_ids)):.2f}%)")

    report_lines.extend(
        [
            "",
            "## Top Issues (All Records)",
            "",
        ]
    )
    for issue, count in all_issue_counts.most_common(15):
        report_lines.append(f"- {issue}: {count}")

    report_lines.extend(
        [
            "",
            "## Top Issues (Usable Records)",
            "",
        ]
    )
    for issue, count in usable_issue_counts.most_common(15):
        report_lines.append(f"- {issue}: {count}")

    report_lines.extend(
        [
            "",
            "## Missing/Filter Failure Counts",
            "",
        ]
    )
    for key, count in sorted(missing_counts.items()):
        report_lines.append(f"- {key}: {count}")

    report_lines.extend(
        [
            "",
            "## Split Summary",
            "",
            f"- Validation size requested/effective: {args.val_size}/{effective_val_size}",
            f"- Training size requested/effective: {requested_train_size}/{effective_train_size}",
            f"- Unique train pool after val holdout: {unique_pool_size}",
            "",
            "### Train Category Counts",
            "",
        ]
    )
    for cat in ALLOWED_CATEGORIES:
        report_lines.append(f"- {cat}: {train_category_counts.get(cat, 0)}")

    report_lines.extend(["", "### Validation Category Counts", ""])
    for cat in ALLOWED_CATEGORIES:
        report_lines.append(f"- {cat}: {val_category_counts.get(cat, 0)}")

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"Total records: {total_records}")
    print(f"Usable records: {len(usable_ids)}")
    print(f"Train rows written: {len(train_rows)} -> {args.train_out}")
    print(f"Val rows written: {len(val_rows)} -> {args.val_out}")
    print(f"Report written: {args.report_out}")
    print(f"Train category counts: {dict(train_category_counts)}")
    print(f"Val category counts: {dict(val_category_counts)}")
    print(f"Determination 3-class counts (usable): {dict(determination_3class_counts)}")


if __name__ == "__main__":
    main()
