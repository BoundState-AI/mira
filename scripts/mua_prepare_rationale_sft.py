#!/usr/bin/env python3
"""Prepare MUA rationale-generation chat datasets for local QLoRA SFT."""

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
    "You are a NASA materials and processes engineer writing a Material Usage Agreement "
    "(MUA) rationale. Given a material deficiency, application context, environment, and "
    "evidence, write a concise, technically defensible engineering rationale that explains "
    "why use is acceptable with stated controls and limitations."
)

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
        default=Path("mua_rationale_train.jsonl"),
        help="Output training JSONL path.",
    )
    parser.add_argument(
        "--val-out",
        type=Path,
        default=Path("mua_rationale_val.jsonl"),
        help="Output validation JSONL path.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("docs/mua_rationale_sft_corpus_analysis.md"),
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
        default=4000,
        help="Requested training examples (no duplication).",
    )
    parser.add_argument(
        "--val-size",
        type=int,
        default=1000,
        help="Requested validation examples.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--max-rationale-tokens",
        type=int,
        default=1024,
        help="Maximum rationale token count using whitespace proxy.",
    )
    return parser.parse_args()


def clean_text(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "True" if value else "False"
    text = str(value).strip()
    return text if text else default


def normalize_issue(issue: Any) -> str:
    text = clean_text(issue, default="").strip().lower()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text


def truncate_rationale(text: str, max_tokens: int) -> tuple[str, bool]:
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text, False
    return " ".join(tokens[:max_tokens]), True


def infer_evidence_types(record: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    text_blob = (
        f"{clean_text(record.get('application'), default='')}\n"
        f"{clean_text(record.get('rationale'), default='')}"
    ).lower()

    test_reports = record.get("test_reports") or []
    if isinstance(test_reports, list):
        cleaned_reports = [clean_text(rep, default="") for rep in test_reports if clean_text(rep, "")]
    else:
        cleaned_reports = []
        if str(test_reports).strip():
            cleaned_reports = [clean_text(test_reports)]

    if cleaned_reports:
        evidence.append("Referenced test reports: " + "; ".join(cleaned_reports[:4]))
    if "heritage" in text_blob or "flight-proven" in text_blob:
        evidence.append("Flight heritage")
    if "analysis" in text_blob or "hazard" in text_blob:
        evidence.append("Engineering analysis")
    if "similar" in text_blob or "equivalent" in text_blob:
        evidence.append("Similarity to tested configuration")
    if "maptis" in text_blob:
        evidence.append("MAPTIS reference")
    if "rationale code" in text_blob or re.search(r"\bcode[s]?\s+\d{2,4}\b", text_blob):
        evidence.append("Rationale code references")
    if "test" in text_blob:
        evidence.append("Configuration or qualification testing")

    if not evidence:
        evidence.append("No explicit supporting evidence captured in parsed fields")
    # De-duplicate in order.
    return list(dict.fromkeys(evidence))


def build_deficiency(record: dict[str, Any]) -> str:
    issues = [normalize_issue(issue) for issue in (record.get("issues") or [])]
    issues = [issue for issue in issues if issue]
    if issues:
        return "; ".join(dict.fromkeys(issues))

    # Fallback for malformed rows; should be rare for this corpus.
    rationale = clean_text(record.get("rationale"), default="")
    match = re.search(r"(rating[^.]{0,80}|no\s+[^.]{0,60}\s+data|missing\s+[^.]{0,60}\s+data)", rationale, re.I)
    if match:
        return match.group(1).strip()
    return "Parsed record indicates a materials compliance deficiency requiring MUA rationale."


def material_block(record: dict[str, Any]) -> str:
    return (
        f"Designation: {clean_text(record.get('material_designation'))}\n"
        f"Family: {clean_text(record.get('material_family'))}\n"
        f"Specification: {clean_text(record.get('specification'))}\n"
        f"Manufacturer: {clean_text(record.get('manufacturer'))}\n"
        f"Trade Name: {clean_text(record.get('trade_name'))}"
    )


def environment_block(record: dict[str, Any]) -> str:
    environment = record.get("environment") or {}
    return (
        f"Raw Context: {clean_text(environment.get('raw_text'))}\n"
        f"Temperature (F): {clean_text(environment.get('temperature_f'))}\n"
        f"Pressure (PSIA): {clean_text(environment.get('pressure_psia'))}\n"
        f"Habitable: {clean_text(environment.get('is_habitable'))}"
    )


def format_user_prompt(record: dict[str, Any], deficiency: str, evidence: list[str]) -> str:
    return (
        f"Material:\n{material_block(record)}\n\n"
        f"Deficiency:\n{deficiency}\n\n"
        f"Application:\n{clean_text(record.get('application'))}\n\n"
        f"Environment:\n{environment_block(record)}\n\n"
        f"Evidence Cited:\n- " + "\n- ".join(evidence) + "\n\n"
        "Task: Write the MUA engineering rationale. Address the deficiency directly, "
        "ground the argument in application/environment constraints, and reference the "
        "provided evidence where applicable."
    )


def bucket_label(deficiency: str) -> str:
    tokens = [tok for tok in re.findall(r"[a-z0-9]+", deficiency.lower()) if tok not in STOPWORDS]
    if not tokens:
        return "other"
    return tokens[0]


def allocate_counts(group_sizes: dict[str, int], target_size: int) -> dict[str, int]:
    if target_size <= 0 or not group_sizes:
        return {key: 0 for key in group_sizes}
    total = sum(group_sizes.values())
    allocations = {key: 0 for key in group_sizes}
    ideals: dict[str, float] = {}
    for key, size in group_sizes.items():
        ideal = (target_size * size) / total
        ideals[key] = ideal
        allocations[key] = min(math.floor(ideal), size)

    remaining = target_size - sum(allocations.values())
    order = sorted(
        group_sizes.keys(),
        key=lambda key: (ideals[key] - math.floor(ideals[key]), group_sizes[key]),
        reverse=True,
    )
    while remaining > 0:
        progressed = False
        for key in order:
            if allocations[key] < group_sizes[key]:
                allocations[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break
    return allocations


def stratified_sample_ids(grouped_ids: dict[str, list[int]], target_size: int, rng: random.Random) -> list[int]:
    group_sizes = {key: len(values) for key, values in grouped_ids.items() if values}
    allocations = allocate_counts(group_sizes, target_size)
    sampled: list[int] = []
    for key, count in allocations.items():
        if count <= 0:
            continue
        sampled.extend(rng.sample(grouped_ids[key], count))
    rng.shuffle(sampled)
    return sampled


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")


def pct(count: int, total: int) -> float:
    return (count / total) * 100.0 if total else 0.0


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)

    total_records = 0
    usable_records: list[dict[str, Any]] = []
    missing_counts: Counter[str] = Counter()
    deficiency_counts: Counter[str] = Counter()
    evidence_type_counts: Counter[str] = Counter()
    truncated_rationale_count = 0

    with args.input.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if not line.strip():
                continue
            total_records += 1
            row = json.loads(line)

            rationale = clean_text(row.get("rationale"), default="")
            application = clean_text(row.get("application"), default="")
            confidence = row.get("confidence")
            issues = [normalize_issue(issue) for issue in (row.get("issues") or [])]
            issues = [issue for issue in issues if issue]

            usable = True
            if not rationale:
                usable = False
                missing_counts["rationale"] += 1
            if not application:
                usable = False
                missing_counts["application"] += 1
            if confidence is None or confidence < args.min_confidence:
                usable = False
                missing_counts[f"confidence_lt_{args.min_confidence}"] += 1
            if not issues:
                usable = False
                missing_counts["issues"] += 1

            if not usable:
                continue

            deficiency = build_deficiency(row)
            evidence = infer_evidence_types(row)
            truncated_rationale, was_truncated = truncate_rationale(rationale, args.max_rationale_tokens)
            if was_truncated:
                truncated_rationale_count += 1

            usable_row = dict(row)
            usable_row["_id"] = idx
            usable_row["_deficiency"] = deficiency
            usable_row["_evidence_cited"] = evidence
            usable_row["_rationale"] = truncated_rationale
            usable_records.append(usable_row)

            deficiency_counts[bucket_label(deficiency)] += 1
            for ev in evidence:
                prefix = ev.split(":", 1)[0].strip()
                evidence_type_counts[prefix] += 1

    if not usable_records:
        raise ValueError("No usable records found for rationale SFT dataset.")

    total_usable = len(usable_records)
    if args.val_size >= total_usable:
        raise ValueError(f"Validation size {args.val_size} must be smaller than usable records {total_usable}.")
    if args.train_size > (total_usable - args.val_size):
        raise ValueError(
            f"Requested train size ({args.train_size}) exceeds unique train pool "
            f"({total_usable - args.val_size}) after validation split. Upsampling is disabled."
        )

    records_by_id = {row["_id"]: row for row in usable_records}
    grouped_all: dict[str, list[int]] = defaultdict(list)
    for row in usable_records:
        grouped_all[bucket_label(row["_deficiency"])].append(row["_id"])

    val_ids = stratified_sample_ids(grouped_all, args.val_size, rng)
    val_set = set(val_ids)
    train_pool = [row for row in usable_records if row["_id"] not in val_set]

    grouped_train_pool: dict[str, list[int]] = defaultdict(list)
    for row in train_pool:
        grouped_train_pool[bucket_label(row["_deficiency"])].append(row["_id"])

    train_ids = stratified_sample_ids(grouped_train_pool, args.train_size, rng)

    def row_to_chat(row: dict[str, Any]) -> dict[str, Any]:
        user_content = format_user_prompt(row, row["_deficiency"], row["_evidence_cited"])
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": row["_rationale"]},
            ]
        }

    train_rows = [row_to_chat(records_by_id[rid]) for rid in train_ids]
    val_rows = [row_to_chat(records_by_id[rid]) for rid in val_ids]

    write_jsonl(args.train_out, train_rows)
    write_jsonl(args.val_out, val_rows)

    train_buckets: Counter[str] = Counter()
    val_buckets: Counter[str] = Counter()
    for rid in train_ids:
        train_buckets[bucket_label(records_by_id[rid]["_deficiency"])] += 1
    for rid in val_ids:
        val_buckets[bucket_label(records_by_id[rid]["_deficiency"])] += 1

    report_lines = [
        "# MUA Rationale SFT Corpus Analysis",
        "",
        f"- Source file: `{args.input}`",
        f"- Total records: **{total_records}**",
        (
            "- Usable records (rationale + application + issues + "
            f"confidence >= {args.min_confidence}): **{total_usable}**"
        ),
        (
            f"- Rationale truncated at {args.max_rationale_tokens} tokens "
            f"(whitespace proxy): **{truncated_rationale_count}** records"
        ),
        "",
        "## Deficiency Bucket Distribution (Usable)",
        "",
    ]
    for key, count in deficiency_counts.most_common(20):
        report_lines.append(f"- {key}: {count} ({pct(count, total_usable):.2f}%)")

    report_lines.extend(["", "## Evidence Type Coverage (Usable)", ""])
    for key, count in evidence_type_counts.most_common():
        report_lines.append(f"- {key}: {count} ({pct(count, total_usable):.2f}%)")

    report_lines.extend(["", "## Missing/Filter Failure Counts", ""])
    for key, count in sorted(missing_counts.items()):
        report_lines.append(f"- {key}: {count}")

    report_lines.extend(
        [
            "",
            "## Split Summary",
            "",
            f"- Training rows: {len(train_rows)}",
            f"- Validation rows: {len(val_rows)}",
            f"- Unique pool after val holdout: {len(train_pool)}",
            "",
            "### Train Deficiency Buckets (Top 20)",
            "",
        ]
    )
    for key, count in train_buckets.most_common(20):
        report_lines.append(f"- {key}: {count}")
    report_lines.extend(["", "### Validation Deficiency Buckets (Top 20)", ""])
    for key, count in val_buckets.most_common(20):
        report_lines.append(f"- {key}: {count}")

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"Total records: {total_records}")
    print(f"Usable rationale-task records: {total_usable}")
    print(f"Train rows written: {len(train_rows)} -> {args.train_out}")
    print(f"Val rows written: {len(val_rows)} -> {args.val_out}")
    print(f"Report written: {args.report_out}")
    print(f"Top deficiency buckets: {deficiency_counts.most_common(10)}")
    print(f"Evidence type coverage: {dict(evidence_type_counts)}")


if __name__ == "__main__":
    main()
