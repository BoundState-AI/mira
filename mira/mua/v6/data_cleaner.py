#!/usr/bin/env python3
"""
Module: Data Cleaner
Purpose: V6 Data Cleaner - Clean and normalize parsed MUA records.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation)
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .precedent_models import (
    IssueCategory,
    EnvironmentType,
    MaterialFamily,
    NormalizedEnvironment,
    CleanedMUARecord,
)

logger = logging.getLogger(__name__)

__all__ = ["V6DataCleaner", "RationaleSynthesizer", "clean_mua_records"]


# =============================================================================
# Rationale Synthesizer - Zero Hallucination Extractive Approach
# =============================================================================

class RationaleSynthesizer:
    """
    Extract rationale-like statements from application text.

    CRITICAL: This class NEVER generates new claims - it only extracts
    and restructures existing text from the source document.

    Used for records where:
    - rationale field is NULL
    - application field contains rationale-worthy content
    - We need searchable text without hallucinating technical claims

    All synthesized rationale is clearly prefixed to indicate source.
    """

    # Patterns that indicate rationale-worthy content in application text
    # These capture existing justifications, not generate new ones
    RATIONALE_INDICATORS = [
        # Causal explanations
        (r"because\s+(.{20,300}?)(?:[.;]|$)", "CAUSAL"),
        (r"due\s+to\s+(.{20,300}?)(?:[.;]|$)", "CAUSAL"),
        (r"since\s+(.{20,300}?)(?:[.;]|$)", "CAUSAL"),
        (r"therefore\s+(.{20,300}?)(?:[.;]|$)", "CAUSAL"),

        # Acceptability statements
        (r"acceptable\s+(?:for|because)\s*(.{20,300}?)(?:[.;]|$)", "ACCEPTABLE"),
        (r"will\s+not\s+(?:present|pose|cause)\s+(.{20,300}?)(?:[.;]|$)", "SAFETY"),
        (r"does\s+not\s+(?:present|pose|cause)\s+(.{20,300}?)(?:[.;]|$)", "SAFETY"),

        # Quantity/exposure mitigations
        (r"(?:small|negligible|minimal)\s+(?:amount|quantity|area)\s*(.{10,200}?)(?:[.;]|$)", "QUANTITY"),
        (r"limited\s+(?:amount|quantity|exposure)\s*(.{10,200}?)(?:[.;]|$)", "QUANTITY"),

        # Isolation/containment mitigations
        (r"(?:enclosed|sealed|contained|isolated)\s*(.{10,200}?)(?:[.;]|$)", "ISOLATION"),
        (r"totally\s+enclosed\s*(.{10,200}?)(?:[.;]|$)", "ISOLATION"),
        (r"not\s+(?:located\s+)?(?:near|adjacent\s+to)\s+(?:an?\s+)?ignition\s+source(.{0,100}?)(?:[.;]|$)", "ISOLATION"),

        # Test/compliance statements
        (r"(?:tested|passed|meets|complies)\s+(?:with\s+)?(.{10,200}?)(?:[.;]|$)", "COMPLIANCE"),
        (r"per\s+(?:MSFC|NASA|MIL|AMS|ASTM)[-\s]?(.{10,150}?)(?:[.;]|$)", "COMPLIANCE"),

        # Prior approval/usage
        (r"(?:previously|already)\s+(?:approved|accepted|used)\s*(.{10,200}?)(?:[.;]|$)", "PRECEDENT"),
        (r"has\s+been\s+(?:approved|accepted|used)\s*(.{10,200}?)(?:[.;]|$)", "PRECEDENT"),

        # Protective measures
        (r"(?:protective|conformal)\s+coating\s*(.{10,200}?)(?:[.;]|$)", "PROTECTION"),
        (r"will\s+(?:be\s+)?(?:coated|protected|anodized)\s*(.{10,200}?)(?:[.;]|$)", "PROTECTION"),
    ]

    def __init__(self):
        self._patterns = [
            (re.compile(pattern, re.IGNORECASE | re.DOTALL), category)
            for pattern, category in self.RATIONALE_INDICATORS
        ]

    def synthesize(self, record: Dict) -> Optional[str]:
        """
        Extract rationale-like content from application field.

        Args:
            record: Raw MUA record with application field

        Returns:
            Synthesized rationale with clear provenance prefix, or None
        """
        app = record.get("application", "")
        if not app or len(app) < 30:
            return None

        # Try to extract existing rationale-like statements
        extracted = []
        categories_found = set()

        for pattern, category in self._patterns:
            matches = pattern.findall(app)
            for match in matches:
                # Clean up the match
                text = match.strip() if isinstance(match, str) else match[0].strip()
                text = re.sub(r'\s+', ' ', text)  # Normalize whitespace

                if len(text) >= 15 and category not in categories_found:
                    extracted.append((category, text))
                    categories_found.add(category)

                    # Limit to 3 extractions to keep it concise
                    if len(extracted) >= 3:
                        break

            if len(extracted) >= 3:
                break

        if extracted:
            # Format with clear provenance
            parts = [f"[{cat}] {text}" for cat, text in extracted[:2]]
            return f"[EXTRACTED FROM APPLICATION] {'; '.join(parts)}"

        # Fallback: use truncated application as searchable context
        # This does NOT claim it's a rationale, just provides context
        truncated = app[:350].strip()
        if truncated:
            # Cut at last sentence boundary if possible
            last_period = truncated.rfind('.')
            if last_period > 100:
                truncated = truncated[:last_period + 1]
            return f"[APPLICATION CONTEXT] {truncated}"

        return None

    def can_synthesize(self, record: Dict) -> bool:
        """Check if record has synthesizable content."""
        app = record.get("application", "")
        if not app or len(app) < 30:
            return False

        # Quick check for any rationale indicators
        app_lower = app.lower()
        keywords = ["because", "due to", "since", "therefore", "acceptable",
                   "will not", "enclosed", "sealed", "tested", "passed",
                   "meets", "approved", "coating", "protected"]
        return any(kw in app_lower for kw in keywords)


# =============================================================================
# Issue Category Mapping
# =============================================================================

ISSUE_PATTERNS: Dict[IssueCategory, List[str]] = {
    IssueCategory.FLAMMABILITY: [
        r"flam", r"ignit", r"fire", r"burn", r"a-rat", r"upward\s*prop",
    ],
    IssueCategory.TOXICITY: [
        r"toxic", r"tox\b", r"poison", r"hazard.*health", r"t-rat",
    ],
    IssueCategory.OFFGASSING: [
        r"offgas", r"outgas", r"tvs", r"cvcm", r"tml", r"volatile",
    ],
    IssueCategory.STRESS_CORROSION_CRACKING: [
        r"\bscc\b", r"stress.*corr", r"crack", r"intergranular",
    ],
    IssueCategory.CORROSION: [
        r"corros", r"rust", r"oxid", r"galvan",
    ],
    IssueCategory.DISSIMILAR_METALS: [
        r"dissimilar", r"galvanic", r"electrolytic", r"couple",
    ],
    IssueCategory.OXYGEN_COMPATIBILITY: [
        r"oxygen.*compat", r"o2.*compat", r"lox", r"gox", r"moc",
        r"oxygen.*service", r"promoted.*ignit",
    ],
    IssueCategory.THERMAL_VACUUM_STABILITY: [
        r"thermal.*vacuum", r"vacuum.*stab", r"tvs", r"space.*env",
    ],
    IssueCategory.PROCESS_SPECIFICATION: [
        r"process.*spec", r"proc.*dev", r"manufacturing", r"non.?standard",
    ],
    IssueCategory.WORKMANSHIP: [
        r"workmanship", r"solder", r"crimp", r"assembly", r"deviation",
    ],
    IssueCategory.FLUID_COMPATIBILITY: [
        r"fluid.*compat", r"hydrazine", r"propellant", r"coolant",
        r"hydraulic", r"mmh", r"nto",
    ],
    IssueCategory.FRACTURE_CONTROL: [
        r"fracture", r"fatigue", r"crack.*growth", r"flaw",
    ],
}


# =============================================================================
# Environment Type Mapping
# =============================================================================

ENVIRONMENT_PATTERNS: Dict[EnvironmentType, List[str]] = {
    EnvironmentType.VACUUM: [
        r"vacuum", r"unpressur", r"eva", r"external",
    ],
    EnvironmentType.CABIN_AIR: [
        r"cabin", r"habitable", r"crew\s*cabin", r"21%", r"air\b",
        r"ambient.*air", r"module\s*air",
    ],
    EnvironmentType.ENRICHED_O2: [
        r"enrich", r"25%", r"26%", r"27%", r"28%", r"29%", r"30%",
        r"34\.?7", r"partial\s*press",
    ],
    EnvironmentType.PURE_O2: [
        r"100%\s*o2", r"pure\s*o(2|xygen)", r"100%\s*oxygen",
    ],
    EnvironmentType.LOX_GOX: [
        r"\blox\b", r"\bgox\b", r"liquid\s*oxygen", r"gaseous\s*oxygen",
        r"oxygen\s*service", r"o2\s*service",
    ],
    EnvironmentType.WATER: [
        r"water", r"aqueous", r"humidity", r"condensat",
    ],
    EnvironmentType.CO2: [
        r"\bco2\b", r"carbon\s*dioxide", r"fire\s*suppress",
    ],
    EnvironmentType.CRYOGENIC: [
        r"cryogen", r"ln2", r"lh2", r"lhe", r"liquid\s*nitrogen",
        r"liquid\s*hydrogen", r"liquid\s*helium", r"-\d{3}",
    ],
    EnvironmentType.HIGH_PRESSURE: [
        r"high\s*press", r"\d{3,4}\s*psi", r">.*200.*psi",
    ],
}


# =============================================================================
# Material Family Mapping
# =============================================================================

MATERIAL_FAMILY_PATTERNS: Dict[MaterialFamily, List[str]] = {
    MaterialFamily.STAINLESS_STEEL: [
        r"stainless", r"cres", r"304", r"316", r"321", r"347",
        r"17-4", r"17-7", r"15-5", r"a-286", r"ph\s*steel",
    ],
    MaterialFamily.CARBON_STEEL: [
        r"carbon\s*steel", r"low\s*alloy\s*steel", r"1018", r"4130", r"4340",
    ],
    MaterialFamily.ALUMINUM: [
        r"aluminum", r"aluminium", r"\bal\b", r"2024", r"6061", r"7075",
    ],
    MaterialFamily.TITANIUM: [
        r"titanium", r"\bti\b", r"ti-6al", r"ti-6-4",
    ],
    MaterialFamily.NICKEL_ALLOY: [
        r"inconel", r"hastelloy", r"monel", r"waspaloy", r"nimonic",
        r"nickel", r"625\b", r"718\b", r"x-750",
    ],
    MaterialFamily.COPPER_ALLOY: [
        r"copper", r"brass", r"bronze", r"beryllium.*copper", r"be-cu",
    ],
    MaterialFamily.POLYMER: [
        r"polymer", r"plastic", r"nylon", r"peek", r"pei", r"kapton",
        r"teflon", r"ptfe", r"delrin", r"acetal", r"polycarbonate",
        r"polyimide", r"polyethylene", r"polypropylene",
    ],
    MaterialFamily.ELASTOMER: [
        r"elastomer", r"rubber", r"silicone", r"viton", r"epdm",
        r"buna", r"neoprene", r"o-ring", r"seal",
    ],
    MaterialFamily.COATING: [
        r"coating", r"paint", r"primer", r"anodize", r"plate",
        r"chem.*film", r"conversion", r"passiv",
    ],
    MaterialFamily.ADHESIVE: [
        r"adhesive", r"epoxy", r"glue", r"bond", r"cement",
    ],
    MaterialFamily.LUBRICANT: [
        r"lubricant", r"grease", r"oil", r"lube", r"dry.*film",
    ],
    MaterialFamily.SEALANT: [
        r"sealant", r"rtv", r"potting", r"encapsulant",
    ],
    MaterialFamily.CERAMIC: [
        r"ceramic", r"glass", r"frit",
    ],
    MaterialFamily.COMPOSITE: [
        r"composite", r"cfrp", r"gfrp", r"fiber.*reinforce", r"laminate",
    ],
}


# =============================================================================
# V6 Data Cleaner
# =============================================================================

class V6DataCleaner:
    """Clean and normalize raw parsed MUA records."""

    def __init__(self, min_confidence: float = 0.5, synthesize_rationale: bool = True):
        """
        Args:
            min_confidence: Minimum extraction confidence threshold (default 0.5)
            synthesize_rationale: Whether to extract rationale from application
                                  for records with NULL rationale (default True)
        """
        self.min_confidence = min_confidence
        self.synthesize_rationale = synthesize_rationale
        self._rationale_synthesizer = RationaleSynthesizer() if synthesize_rationale else None
        self._issue_patterns = {
            cat: [re.compile(p, re.IGNORECASE) for p in patterns]
            for cat, patterns in ISSUE_PATTERNS.items()
        }
        self._env_patterns = {
            env: [re.compile(p, re.IGNORECASE) for p in patterns]
            for env, patterns in ENVIRONMENT_PATTERNS.items()
        }
        self._material_patterns = {
            fam: [re.compile(p, re.IGNORECASE) for p in patterns]
            for fam, patterns in MATERIAL_FAMILY_PATTERNS.items()
        }

    def clean_record(self, raw: Dict) -> Optional[CleanedMUARecord]:
        """Clean a single raw MUA record.

        Args:
            raw: Raw record from mua_v6_parsed_results.jsonl

        Returns:
            CleanedMUARecord or None if filtered out
        """
        # Skip failed extractions
        if not raw.get("success", False):
            return None

        # Check confidence threshold
        confidence = raw.get("confidence", 0.0)
        if confidence < self.min_confidence:
            return None

        # Skip records without material designation
        material = raw.get("material_designation", "")
        if not material or material.lower() in ("none", "n/a", "unknown", ""):
            return None

        # Extract MUA number (use filename if missing)
        mua_number = raw.get("mua_number") or Path(raw.get("file", "")).stem

        # Normalize environment
        env = self._normalize_environment(raw)

        # Classify issues
        issues = self._classify_issues(raw)

        # Classify material family
        material_family = self._classify_material(material)

        # Normalize determination
        determination = self._normalize_determination(raw.get("determination", ""))

        # Get rationale - synthesize from application if NULL and synthesizer enabled
        rationale = raw.get("rationale", "") or ""
        extraction_mode = raw.get("extraction_mode", "unknown")

        if not rationale and self._rationale_synthesizer:
            synthesized = self._rationale_synthesizer.synthesize(raw)
            if synthesized:
                rationale = synthesized
                extraction_mode = "synthesized"

        return CleanedMUARecord(
            mua_number=mua_number,
            source_file=raw.get("file", ""),
            material_designation=material,
            material_family=material_family,
            specification=raw.get("specification"),
            manufacturer=raw.get("manufacturer"),
            trade_name=raw.get("trade_name"),
            environment=env,
            category=raw.get("category"),
            issues=issues,
            determination=determination,
            application=raw.get("application", "") or "",
            rationale=rationale,
            test_reports=raw.get("test_reports") or [],
            confidence=confidence,
            extraction_mode=extraction_mode,
        )

    def _normalize_environment(self, raw: Dict) -> NormalizedEnvironment:
        """Normalize environment from raw record."""
        env_text = raw.get("environment", "") or ""
        location = raw.get("location", "") or ""

        # Determine environment type
        env_type = EnvironmentType.UNKNOWN
        for etype, patterns in self._env_patterns.items():
            if any(p.search(env_text) for p in patterns):
                env_type = etype
                break

        # Extract O2 percentage (filter invalid values > 100)
        o2_percent = self._extract_o2_percent(env_text)
        if o2_percent is not None and (o2_percent < 0 or o2_percent > 100):
            o2_percent = None  # Invalid value

        # Determine habitability
        is_habitable = "habitable" in location.lower() and "non" not in location.lower()

        # Extract pressure (filter out invalid values)
        pressure = raw.get("max_pressure")
        if pressure is not None:
            try:
                pressure = float(pressure)
                if pressure < 0:  # Invalid negative pressure
                    pressure = None
            except (ValueError, TypeError):
                pressure = None

        # Extract temperature (allow any value - can be negative for cryo)
        temperature = raw.get("max_temperature_f")
        if temperature is not None:
            try:
                temperature = float(temperature)
            except (ValueError, TypeError):
                temperature = None

        return NormalizedEnvironment(
            type=env_type,
            o2_percent=o2_percent,
            pressure_psia=pressure,
            temperature_f=temperature,
            is_habitable=is_habitable,
            raw_text=env_text if env_text else None,
        )

    def _extract_o2_percent(self, text: str) -> Optional[float]:
        """Extract O2 percentage from environment text."""
        if not text:
            return None

        # Pattern: XX% O2 or XX% oxygen
        match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:o2|oxygen)", text, re.IGNORECASE)
        if match:
            return float(match.group(1))

        # Pattern: O2 XX% or oxygen XX%
        match = re.search(r"(?:o2|oxygen)\s*(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
        if match:
            return float(match.group(1))

        # Check for known values
        if "100%" in text and ("o2" in text.lower() or "oxygen" in text.lower()):
            return 100.0
        if "vacuum" in text.lower():
            return 0.0
        if "cabin" in text.lower() or "habitable" in text.lower():
            return 21.0  # Assume standard cabin air

        return None

    def _classify_issues(self, raw: Dict) -> List[IssueCategory]:
        """Classify issues from raw record."""
        issues = set()

        # Check issue field
        issue_text = raw.get("issue", "") or ""
        for category, patterns in self._issue_patterns.items():
            if any(p.search(issue_text) for p in patterns):
                issues.add(category)

        # Also check rationale for additional issues
        rationale = raw.get("rationale", "") or ""
        for category, patterns in self._issue_patterns.items():
            if category not in issues:
                if any(p.search(rationale) for p in patterns):
                    issues.add(category)

        # Default to OTHER if no issues found
        if not issues:
            issues.add(IssueCategory.OTHER)

        return list(issues)

    def _classify_material(self, material: str) -> MaterialFamily:
        """Classify material into a family."""
        for family, patterns in self._material_patterns.items():
            if any(p.search(material) for p in patterns):
                return family
        return MaterialFamily.UNKNOWN

    def _normalize_determination(self, determination: str) -> str:
        """Normalize determination string."""
        if not determination:
            return "UNKNOWN"

        det_upper = determination.upper().strip()

        if "APPROVED" in det_upper or "ACCEPT" in det_upper:
            return "APPROVED"
        elif "CANCEL" in det_upper:
            return "CANCELLED"
        elif "DEFER" in det_upper:
            return "DEFERRED"
        elif "REJECT" in det_upper or "DENIED" in det_upper:
            return "REJECTED"
        else:
            return det_upper or "UNKNOWN"

    def clean_all(self, records: List[Dict]) -> Tuple[List[CleanedMUARecord], Dict]:
        """Clean all records and return stats.

        Args:
            records: List of raw records

        Returns:
            Tuple of (cleaned_records, stats_dict)
        """
        cleaned = []
        stats = {
            "total_input": len(records),
            "filtered_failed": 0,
            "filtered_low_confidence": 0,
            "filtered_no_material": 0,
            "cleaned": 0,
            "with_original_rationale": 0,
            "with_synthesized_rationale": 0,
            "without_rationale": 0,
        }

        for raw in records:
            if not raw.get("success", False):
                stats["filtered_failed"] += 1
                continue

            confidence = raw.get("confidence", 0.0)
            if confidence < self.min_confidence:
                stats["filtered_low_confidence"] += 1
                continue

            material = raw.get("material_designation", "")
            if not material or material.lower() in ("none", "n/a", "unknown", ""):
                stats["filtered_no_material"] += 1
                continue

            record = self.clean_record(raw)
            if record:
                cleaned.append(record)
                stats["cleaned"] += 1

                # Track rationale source
                if record.extraction_mode == "synthesized":
                    stats["with_synthesized_rationale"] += 1
                elif record.rationale:
                    stats["with_original_rationale"] += 1
                else:
                    stats["without_rationale"] += 1

        return cleaned, stats


def clean_mua_records(
    input_path: Path,
    output_path: Path,
    min_confidence: float = 0.5,
    synthesize_rationale: bool = True,
) -> Tuple[int, Dict]:
    """Clean MUA records from JSONL file.

    Args:
        input_path: Path to input mua_v6_parsed_results.jsonl
        output_path: Path to output cleaned JSONL
        min_confidence: Minimum confidence threshold
        synthesize_rationale: Whether to extract rationale from application
                              for records with NULL rationale

    Returns:
        Tuple of (records_cleaned, stats)
    """
    cleaner = V6DataCleaner(
        min_confidence=min_confidence,
        synthesize_rationale=synthesize_rationale,
    )

    # Load records
    logger.info(f"Loading records from {input_path}")
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    # Clean
    logger.info(f"Cleaning {len(records)} records...")
    cleaned, stats = cleaner.clean_all(records)

    # Save
    logger.info(f"Saving {len(cleaned)} cleaned records to {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for record in cleaned:
            f.write(record.model_dump_json() + "\n")

    return len(cleaned), stats


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Clean MUA V6 parsed data")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(r"C:\BoundState\data\mua_v6_parsed_results.jsonl"),
        help="Input JSONL file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(r"C:\BoundState\data\mua_v6_cleaned.jsonl"),
        help="Output JSONL file",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="Minimum extraction confidence (default: 0.5)",
    )
    parser.add_argument(
        "--no-synthesize",
        action="store_true",
        help="Disable rationale synthesis from application text",
    )

    args = parser.parse_args()

    count, stats = clean_mua_records(
        args.input, args.output, args.min_confidence,
        synthesize_rationale=not args.no_synthesize,
    )

    print(f"\n{'='*50}")
    print("Cleaning Complete")
    print(f"{'='*50}")
    print(f"Input records:           {stats['total_input']:,}")
    print(f"Filtered (failed):       {stats['filtered_failed']:,}")
    print(f"Filtered (low conf):     {stats['filtered_low_confidence']:,}")
    print(f"Filtered (no material):  {stats['filtered_no_material']:,}")
    print(f"Output records:          {stats['cleaned']:,}")
    print(f"\n--- Rationale Coverage ---")
    print(f"With original rationale: {stats['with_original_rationale']:,}")
    print(f"With synthesized:        {stats['with_synthesized_rationale']:,}")
    print(f"Without rationale:       {stats['without_rationale']:,}")
    print(f"\nOutput: {args.output}")
