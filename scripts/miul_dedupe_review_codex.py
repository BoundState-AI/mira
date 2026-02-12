#!/usr/bin/env python3
"""
Intelligent duplicate review for MIUL output by Drawing Source.

Rules:
1) Deduplicate exact source+part_number duplicates by merging best field values.
2) Deduplicate source+description duplicates only when one row has an invalid/garbage part number.
3) Keep legitimate duplicates where part numbers are distinct and valid.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd


TEXT_FIELDS = [
    "Part Description",
    "Nomenclature",
    "NHA",
    "Drawing Source",
    "Designation",
    "Material Specification",
    "Process Specification",
    "Material Form",
]


def _blank(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def _norm_part_number(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+\d+\.$", "", text)
    return text


def _norm_description(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text


def _norm_source(value: Any) -> str:
    return str(value or "").strip().upper()


def _norm_text(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"\s+", " ", text)
    return text


def _split_pn_numeric_suffix(part_number: str) -> Tuple[str, int | None]:
    """
    Split PN like MER07576-003 into (MER07576, 3).
    Returns (PN, None) when no numeric suffix pattern is present.
    """
    match = re.fullmatch(r"(.+)-(\d{2,})", part_number)
    if not match:
        return part_number, None
    base = match.group(1).strip().upper()
    suffix = int(match.group(2))
    return base, suffix


def _is_invalid_part_number(part_number: str) -> bool:
    if not part_number:
        return True
    if re.fullmatch(r"\d+\.?", part_number):
        return True
    if part_number.startswith("NOTE") or re.fullmatch(r"NOTE-?\d+", part_number):
        return True
    if part_number in {"UNKNOWN", "TBD", "N/A"}:
        return True
    return False


def _row_quality_score(row: pd.Series) -> int:
    score = 0
    for field in TEXT_FIELDS:
        if field in row.index and not _blank(row[field]):
            score += 1
    return score


def _best_value(rows: pd.DataFrame, field: str) -> Any:
    """Pick best value for a field from duplicate rows."""
    candidates: List[Tuple[int, int, str, Any]] = []
    for idx, row in rows.iterrows():
        value = row.get(field, "")
        if _blank(value):
            continue
        text = str(value).strip()
        quality = _row_quality_score(row)
        candidates.append((quality, len(text), -int(row.get("Index", idx) or 0), value))
    if not candidates:
        return rows.iloc[0].get(field, "")
    candidates.sort(reverse=True)
    return candidates[0][3]


def _merge_duplicate_group(rows: pd.DataFrame) -> pd.Series:
    """Merge duplicate rows keeping best values across textual fields."""
    # Representative row: highest overall quality, then lowest Index.
    ranked = []
    for _, row in rows.iterrows():
        ranked.append((_row_quality_score(row), -(int(row.get("Index", 0) or 0)), row))
    ranked.sort(reverse=True, key=lambda x: (x[0], x[1]))
    merged = ranked[0][2].copy()

    for field in TEXT_FIELDS:
        if field in merged.index:
            merged[field] = _best_value(rows, field)
    return merged


def review_and_dedupe(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    data_mask = (df["Index"] > 2) & (df["Index"] != -1)
    data = df[data_mask].copy()
    headers = df[(df["Index"] <= 2) & (df["Index"] != -1)].copy()
    eof = df[df["Index"] == -1].copy()

    data["_src"] = data["Drawing Source"].map(_norm_source)
    data["_pn"] = data["Part Number"].map(_norm_part_number)
    data["_desc"] = data["Part Description"].map(_norm_description)
    data["_invalid_pn"] = data["_pn"].map(_is_invalid_part_number)

    report: Dict[str, Any] = {
        "source_part_number_duplicates": [],
        "source_description_duplicates": [],
        "actions": [],
    }

    rows_out = data.copy()
    drop_indices = set()

    # Stage 1: Deduplicate by (Drawing Source, Part Number)
    grouped = rows_out.groupby(["_src", "_pn"], dropna=False)
    for (src, pn), group in grouped:
        if len(group) <= 1:
            continue
        if _blank(pn):
            continue
        report["source_part_number_duplicates"].append(
            {
                "drawing_source": src,
                "part_number": pn,
                "count": int(len(group)),
                "indices": [int(x) for x in group["Index"].tolist()],
            }
        )
        merged = _merge_duplicate_group(group)
        keep_idx = group.index[0]
        rows_out.loc[keep_idx] = merged
        for idx in group.index[1:]:
            drop_indices.add(idx)
        report["actions"].append(
            {
                "type": "merge_source_part_number",
                "drawing_source": src,
                "part_number": pn,
                "dropped_rows": [int(rows_out.loc[i, "Index"]) for i in group.index[1:]],
                "kept_row": int(rows_out.loc[keep_idx, "Index"]),
            }
        )

    if drop_indices:
        rows_out = rows_out.drop(index=list(drop_indices))
    drop_indices.clear()

    # Stage 2: Review by (Drawing Source, Part Description)
    grouped_desc = rows_out.groupby(["_src", "_desc"], dropna=False)
    for (src, desc), group in grouped_desc:
        if len(group) <= 1:
            continue
        if _blank(desc):
            continue
        part_numbers = sorted(set(group["_pn"].tolist()))
        invalid_count = int(group["_invalid_pn"].sum())

        report["source_description_duplicates"].append(
            {
                "drawing_source": src,
                "part_description": desc,
                "count": int(len(group)),
                "part_numbers": part_numbers,
                "invalid_part_number_count": invalid_count,
            }
        )

        # Intelligent dedupe for desc duplicates:
        # Only drop rows where PN is invalid and at least one valid PN exists.
        if invalid_count > 0 and invalid_count < len(group):
            invalid_rows = group[group["_invalid_pn"]]
            for idx in invalid_rows.index:
                drop_indices.add(idx)
            report["actions"].append(
                {
                    "type": "drop_invalid_pn_in_desc_duplicate",
                    "drawing_source": src,
                    "part_description": desc,
                    "dropped_rows": [int(rows_out.loc[i, "Index"]) for i in invalid_rows.index],
                    "kept_part_numbers": [pn for pn in part_numbers if not _is_invalid_part_number(pn)],
                }
            )

        remaining = group[~group.index.isin(drop_indices)]
        if len(remaining) <= 1:
            continue

        # Intelligent collapse:
        # If duplicates only differ by numeric PN suffix and technical fields are identical,
        # keep one canonical row (lowest suffix) and drop the rest.
        signature_fields = [
            "Designation",
            "Material Specification",
            "Process Specification",
            "Material Form",
            "NHA",
        ]
        signatures = set()
        pn_bases = set()
        suffix_rows: List[Tuple[int, int, str]] = []

        all_have_numeric_suffix = True
        for idx, row in remaining.iterrows():
            signatures.add(tuple(_norm_text(row.get(field)) for field in signature_fields))
            base, suffix = _split_pn_numeric_suffix(str(row["_pn"]))
            if suffix is None:
                all_have_numeric_suffix = False
                break
            pn_bases.add(base)
            suffix_rows.append((idx, suffix, str(row["_pn"])))

        if (
            all_have_numeric_suffix
            and len(pn_bases) == 1
            and len(signatures) == 1
            and next(iter(pn_bases)) == src
        ):
            ranked = sorted(
                (
                    suffix,
                    -_row_quality_score(rows_out.loc[idx]),
                    int(rows_out.loc[idx].get("Index", 0) or 0),
                    idx,
                    pn,
                )
                for idx, suffix, pn in suffix_rows
            )
            keep_idx = ranked[0][3]
            keep_pn = str(rows_out.loc[keep_idx, "Part Number"])
            merged = _merge_duplicate_group(remaining)
            merged["Part Number"] = keep_pn
            merged["Index"] = rows_out.loc[keep_idx, "Index"]
            rows_out.loc[keep_idx] = merged

            dropped_rows = []
            merged_part_numbers = []
            for idx, _, pn in suffix_rows:
                if idx == keep_idx:
                    continue
                drop_indices.add(idx)
                dropped_rows.append(int(rows_out.loc[idx, "Index"]))
                merged_part_numbers.append(pn)

            if dropped_rows:
                report["actions"].append(
                    {
                        "type": "collapse_suffix_variant_desc_duplicates",
                        "drawing_source": src,
                        "part_description": desc,
                        "base_part_number": next(iter(pn_bases)),
                        "kept_part_number": keep_pn,
                        "merged_part_numbers": sorted(merged_part_numbers),
                        "dropped_rows": dropped_rows,
                    }
                )

    if drop_indices:
        rows_out = rows_out.drop(index=list(drop_indices))

    rows_out = rows_out.drop(columns=["_src", "_pn", "_desc", "_invalid_pn"], errors="ignore")

    # Preserve original order by Index.
    rows_out = rows_out.sort_values("Index")
    headers = headers.sort_values("Index")
    eof = eof.sort_values("Index")
    deduped = pd.concat([headers, rows_out, eof], ignore_index=True)

    report["summary"] = {
        "input_rows": int(len(df)),
        "input_data_rows": int(len(data)),
        "output_rows": int(len(deduped)),
        "output_data_rows": int(len(rows_out)),
        "rows_removed": int(len(df) - len(deduped)),
        "source_part_number_duplicate_groups": int(len(report["source_part_number_duplicates"])),
        "source_description_duplicate_groups": int(len(report["source_description_duplicates"])),
        "actions_taken": int(len(report["actions"])),
    }
    return deduped, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Review/dedupe MIUL by Drawing Source.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("miul_codex/MIUL_codex.xlsx"),
        help="Input MIUL workbook path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("miul_codex/MIUL_codex_deduped.xlsx"),
        help="Output deduped MIUL workbook path.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("miul_codex/dedupe_report_codex.json"),
        help="JSON dedupe report output path.",
    )
    parser.add_argument(
        "--report-txt",
        type=Path,
        default=Path("miul_codex/dedupe_report_codex.txt"),
        help="Text dedupe report output path.",
    )
    args = parser.parse_args()

    df = pd.read_excel(args.input, sheet_name="MIUL")
    deduped, report = review_and_dedupe(df)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        deduped.to_excel(writer, sheet_name="MIUL", index=False)

    args.report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = []
    lines.append("MIUL Dedupe Review (by Drawing Source)")
    lines.append("")
    lines.append(json.dumps(report["summary"], indent=2))
    lines.append("")
    lines.append("Description duplicate groups:")
    for entry in report["source_description_duplicates"][:50]:
        lines.append(
            f"- {entry['drawing_source']} | {entry['part_description']} | "
            f"count={entry['count']} | part_numbers={entry['part_numbers']}"
        )
    lines.append("")
    lines.append("Actions taken:")
    for action in report["actions"][:100]:
        lines.append(f"- {json.dumps(action)}")
    args.report_txt.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
