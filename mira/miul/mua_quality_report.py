#!/usr/bin/env python3
"""
Module: Mua Quality Report
Purpose: MUA Extraction Quality Report.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List

# Add project root to path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def analyze_mua_extraction_quality(jsonl_path: str) -> Dict[str, Any]:
    """Analyze extraction quality from JSONL results.

    Args:
        jsonl_path: Path to the JSONL file with MUA extraction results

    Returns:
        Dictionary with quality metrics
    """
    records = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    if not records:
        return {"error": "No records found in file"}

    # Basic stats
    total = len(records)
    successful = sum(1 for r in records if r.get("success"))
    failed = total - successful

    # Confidence distribution
    confidences = [r.get("confidence", 0) for r in records if r.get("success")]

    # Field completeness
    fields = [
        "material_designation", "rationale", "application", "mua_number",
        "category", "determination", "environment", "issue", "test_reports",
        "specification", "manufacturer", "location"
    ]

    completeness = {}
    for field in fields:
        filled = sum(
            1 for r in records
            if r.get(field) and r.get(field) not in [None, "", [], "N/A", "TBD"]
        )
        completeness[field] = round(filled / total * 100, 1)

    # Category distribution
    categories = Counter(r.get("category") for r in records if r.get("category"))

    # Determination distribution
    determinations = Counter(r.get("determination") for r in records)

    # Location distribution
    locations = Counter(r.get("location") for r in records if r.get("location"))

    # Extraction mode distribution
    extraction_modes = Counter(r.get("extraction_mode") for r in records)

    # Confidence tiers
    high_conf = sum(1 for c in confidences if c >= 0.9)
    med_conf = sum(1 for c in confidences if 0.7 <= c < 0.9)
    low_conf = sum(1 for c in confidences if c < 0.7)

    return {
        "total": total,
        "successful": successful,
        "failed": failed,
        "success_rate": round(successful / total * 100, 1),
        "confidence": {
            "mean": round(mean(confidences), 3) if confidences else 0,
            "stdev": round(stdev(confidences), 3) if len(confidences) > 1 else 0,
            "min": round(min(confidences), 3) if confidences else 0,
            "max": round(max(confidences), 3) if confidences else 0,
            "high_count": high_conf,
            "medium_count": med_conf,
            "low_count": low_conf,
        },
        "field_completeness": completeness,
        "categories": dict(categories),
        "determinations": dict(determinations),
        "locations": dict(locations),
        "extraction_modes": dict(extraction_modes),
    }


def find_problem_cases(jsonl_path: str) -> List[Dict[str, Any]]:
    """Identify MUAs with potential quality issues.

    Args:
        jsonl_path: Path to the JSONL file

    Returns:
        List of problem cases with details
    """
    problems = []
    garbage_values = {
        "MANUFACTURER", "CONTRACTOR", "BOEING", "NASA", "TBD", "N/A",
        "SEE APPLICATION", "VARIOUS", "SEVERAL", "ATTACHMENT"
    }

    with open(jsonl_path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            r = json.loads(line)

            issues = []

            # Check confidence
            conf = r.get("confidence", 0)
            if conf < 0.7:
                issues.append(f"low_confidence ({conf})")

            # Check critical fields
            if not r.get("material_designation"):
                issues.append("missing_material_designation")
            elif r.get("material_designation", "").upper() in garbage_values:
                issues.append(f"garbage_material ({r.get('material_designation')})")

            if not r.get("rationale"):
                issues.append("missing_rationale")

            if not r.get("mua_number"):
                issues.append("missing_mua_number")

            if not r.get("determination"):
                issues.append("missing_determination")

            # Check for failed extraction
            if not r.get("success"):
                issues.append("extraction_failed")

            if issues:
                problems.append({
                    "line": i,
                    "file": r.get("file", "unknown"),
                    "mua_number": r.get("mua_number"),
                    "confidence": conf,
                    "issues": issues,
                })

    return problems


def print_quality_report(stats: Dict[str, Any], problems: List[Dict[str, Any]]) -> None:
    """Print formatted quality report to stdout."""
    print("=" * 70)
    print("MUA EXTRACTION QUALITY REPORT")
    print("=" * 70)

    print(f"\n{'BASIC STATISTICS':^70}")
    print("-" * 70)
    print(f"  Total Records:     {stats['total']}")
    print(f"  Successful:        {stats['successful']}")
    print(f"  Failed:            {stats['failed']}")
    print(f"  Success Rate:      {stats['success_rate']}%")

    print(f"\n{'CONFIDENCE DISTRIBUTION':^70}")
    print("-" * 70)
    conf = stats['confidence']
    print(f"  Mean:              {conf['mean']}")
    print(f"  Std Dev:           {conf['stdev']}")
    print(f"  Min:               {conf['min']}")
    print(f"  Max:               {conf['max']}")
    print(f"  High (>=0.9):      {conf['high_count']} ({conf['high_count']/stats['total']*100:.1f}%)")
    print(f"  Medium (0.7-0.9):  {conf['medium_count']} ({conf['medium_count']/stats['total']*100:.1f}%)")
    print(f"  Low (<0.7):        {conf['low_count']} ({conf['low_count']/stats['total']*100:.1f}%)")

    print(f"\n{'FIELD COMPLETENESS':^70}")
    print("-" * 70)
    for field, pct in sorted(stats['field_completeness'].items(), key=lambda x: -x[1]):
        bar = "#" * int(pct / 5) + "-" * (20 - int(pct / 5))
        status = "[OK]" if pct >= 90 else "[WARN]" if pct >= 70 else "[LOW]"
        print(f"  {field:25} {bar} {pct:5.1f}% {status}")

    print(f"\n{'DETERMINATION DISTRIBUTION':^70}")
    print("-" * 70)
    for det, count in sorted(stats['determinations'].items(), key=lambda x: -x[1]):
        pct = count / stats['total'] * 100
        print(f"  {str(det):20} {count:5} ({pct:5.1f}%)")

    print(f"\n{'CATEGORY DISTRIBUTION':^70}")
    print("-" * 70)
    for cat, count in sorted(stats['categories'].items(), key=lambda x: -x[1]):
        pct = count / stats['total'] * 100
        print(f"  Category {str(cat):10} {count:5} ({pct:5.1f}%)")

    print(f"\n{'EXTRACTION MODES':^70}")
    print("-" * 70)
    for mode, count in stats['extraction_modes'].items():
        pct = count / stats['total'] * 100
        print(f"  {str(mode):15} {count:5} ({pct:5.1f}%)")

    print(f"\n{'PROBLEM CASES':^70}")
    print("-" * 70)
    print(f"  Total Problems:    {len(problems)}")

    if problems:
        print(f"\n  Top 10 Problem Cases:")
        for p in problems[:10]:
            print(f"    [{p['line']:4}] {p['file'][:30]:30} conf={p['confidence']:.2f}")
            print(f"           Issues: {', '.join(p['issues'])}")

    # Quality verdict
    print(f"\n{'QUALITY VERDICT':^70}")
    print("=" * 70)

    go_criteria = [
        stats['success_rate'] >= 95,
        conf['mean'] >= 0.8,
        stats['field_completeness'].get('material_designation', 0) >= 90,
        stats['field_completeness'].get('rationale', 0) >= 90,
        stats['field_completeness'].get('mua_number', 0) >= 90,
    ]

    if all(go_criteria):
        print("  VERDICT: [GO] - Quality thresholds met")
        print("  Ready to resume extraction")
    else:
        print("  VERDICT: [HOLD] - Quality review needed")
        if stats['success_rate'] < 95:
            print(f"    - Success rate {stats['success_rate']}% < 95%")
        if conf['mean'] < 0.8:
            print(f"    - Mean confidence {conf['mean']} < 0.8")
        for field in ['material_designation', 'rationale', 'mua_number']:
            if stats['field_completeness'].get(field, 0) < 90:
                print(f"    - {field} completeness {stats['field_completeness'].get(field, 0)}% < 90%")

    print("=" * 70)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m mira.miul.mua_quality_report <jsonl_path>")
        print("Example: python -m mira.miul.mua_quality_report data/mua_v6_parsed_results.jsonl")
        sys.exit(1)

    jsonl_path = sys.argv[1]

    if not Path(jsonl_path).exists():
        print(f"Error: File not found: {jsonl_path}")
        sys.exit(1)

    # Run analysis
    stats = analyze_mua_extraction_quality(jsonl_path)
    problems = find_problem_cases(jsonl_path)

    # Print report
    print_quality_report(stats, problems)


if __name__ == "__main__":
    main()
