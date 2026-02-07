#!/usr/bin/env python3
"""
Module: Investigate Failures
Purpose: Investigate under-conservative failures in H2 engine.

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

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add h2 directory to path
h2_dir = Path(__file__).parent
sys.path.insert(0, str(h2_dir))

from engine_simple import H2Engine, Verdict
from aliases import normalize, get_canonical_name, extract_alloy_numbers, CANONICAL_NAMES

# Under-conservative failures - materials we're rating too safe
UNDER_CONSERVATIVE = [
    ("Inconel 706", "prohibited"),      # We say caution
    ("Incoloy 903", "prohibited"),      # We say caution
    ("Astroloy", "prohibited"),         # We say caution
    ("A-286", "prohibited"),            # We say acceptable
    ("304N", "prohibited"),             # We say caution
    ("310", "prohibited"),              # We say caution
    ("347", "prohibited"),              # We say caution
    ("21-6-9", "prohibited"),           # Nitronic 40
    ("22-13-5", "prohibited"),          # Nitronic 50
]


def main():
    # Load raw evidence
    evidence_path = Path(__file__).parent.parent.parent / "data" / "h2_evidence_merged.json"
    with open(evidence_path) as f:
        data = json.load(f)

    evidence = data.get("evidence", [])

    engine = H2Engine()

    print("=" * 80)
    print("UNDER-CONSERVATIVE FAILURE INVESTIGATION")
    print("Materials we rate too safe (ok/caution when NASA says prohibited)")
    print("=" * 80)

    for material, nasa_verdict in UNDER_CONSERVATIVE:
        print(f"\n{'='*80}")
        print(f"MATERIAL: {material}")
        print(f"NASA EXPECTED: {nasa_verdict}")
        print(f"{'='*80}")

        # Check what we return
        result = engine.query(material)
        print(f"\nOUR RESULT:")
        print(f"  Verdict: {result.verdict.value}")
        print(f"  HEE Band: {result.hee_band}")
        print(f"  Match type: {result.match_type}")
        print(f"  Canonical name: {result.canonical_name}")
        print(f"  Evidence count: {result.evidence_count}")
        print(f"  Band distribution: {result.band_distribution}")

        # Check alias lookup
        canonical = get_canonical_name(material)
        print(f"\nALIAS LOOKUP:")
        print(f"  Input: '{material}'")
        print(f"  Normalized: '{normalize(material)}'")
        print(f"  Canonical: {canonical}")

        # Search evidence database directly
        norm_query = normalize(material)
        query_numbers = extract_alloy_numbers(material)

        print(f"\nEVIDENCE DATABASE SEARCH:")
        print(f"  Alloy numbers extracted: {query_numbers}")

        # Find all evidence that might match
        matches = []
        for rec in evidence:
            mat_name = rec.get("material_name", "")
            norm_name = normalize(mat_name)

            # Check various match criteria
            exact = norm_query == norm_name
            substring = norm_query in norm_name or norm_name in norm_query
            numbers = extract_alloy_numbers(mat_name) & query_numbers if query_numbers else False

            if exact or substring or numbers:
                matches.append({
                    "name": mat_name,
                    "band": rec.get("hee_band"),
                    "source": rec.get("source", {}).get("document", "unknown"),
                    "match_reason": "exact" if exact else "substring" if substring else "numbers",
                })

        if matches:
            print(f"\n  Found {len(matches)} potential matches:")
            for m in matches:
                print(f"    - {m['name']}: {m['band']} ({m['source']}) [{m['match_reason']}]")
        else:
            print(f"\n  NO MATCHES FOUND IN DATABASE!")

            # Check if there's anything similar
            print(f"\n  Similar names in database:")
            for rec in evidence:
                mat_name = rec.get("material_name", "")
                if any(word in normalize(mat_name) for word in norm_query.split()):
                    print(f"    - {mat_name}: {rec.get('hee_band')}")

        print()

    print("\n" + "=" * 80)
    print("ANALYSIS SUMMARY")
    print("=" * 80)


if __name__ == "__main__":
    main()
