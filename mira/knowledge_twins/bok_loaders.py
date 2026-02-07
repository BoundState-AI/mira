#!/usr/bin/env python3
"""
Module: Bok Loaders
Purpose: bok_loaders

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel

from .compatibility_models import (
    CompatibilityClass,
    CompatibilityRecord,
    DataClass,
    EnvelopeEvidence,
    EnvironmentEnvelope,
    GasType,
    MaterialFamilyKey,
    Phase,
    PropertyEvidence,
    PropertyKey,
)

logger = logging.getLogger(__name__)

__all__ = [
    # Normalization helpers
    "clean_str",
    "clean_float",
    "canonical_maptis_material_key",
    # Resolver types
    "FluidInfo",
    "FluidsResolver",
    "FamilyResolver",
    "make_fluids_resolver_from_map",
    # Row mappers
    "map_flammability_row_to_record",
    "map_crack_growth_row_to_record",
    "map_fluid_compatibility_row_to_record",
    # Main entry point
    "maptis_rows_to_twin_records",
]


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def clean_str(x: Any) -> str:
    """Strip whitespace from any value, return empty string for None.

    Handles MAPTIS edge cases like "C " (rating with trailing space).
    """
    if x is None:
        return ""
    return str(x).strip()


def clean_float(x: Any) -> Optional[float]:
    """Parse float from potentially dirty MAPTIS value.

    Handles edge cases like:
    - " 10.2000" (leading whitespace)
    - "NULL" string
    - Empty strings
    """
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.upper() == "NULL":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def safe_upper(x: Any) -> str:
    """Uppercase after cleaning."""
    return clean_str(x).upper()


def canonical_maptis_material_key(material_key_int: Any) -> str:
    """Canonicalize MAPTIS material_key int to stable string.

    Format: "MAPTIS:{int}"

    NEVER use material_name for identity - always use this canonical form.
    """
    mk = clean_str(material_key_int)
    if mk == "" or mk.upper() == "NULL":
        return "MAPTIS:UNKNOWN"
    try:
        return f"MAPTIS:{int(float(mk))}"
    except ValueError:
        return f"MAPTIS:{mk}"


def build_record_id(prefix: str, row_uid: Any, idx: Any = None) -> str:
    """Build deterministic record ID from row_uid or fallback index."""
    uid = clean_str(row_uid)
    if uid:
        return f"{prefix}:{uid}"
    return f"{prefix}:IDX:{clean_str(idx)}"


def pick_first(*vals: Any) -> Any:
    """Return first non-null, non-empty value."""
    for v in vals:
        if v is None:
            continue
        s = clean_str(v)
        if s == "" or s.upper() == "NULL":
            continue
        return v
    return None


# ---------------------------------------------------------------------------
# Fluids join contract (CRITICAL - non-negotiable)
# ---------------------------------------------------------------------------


class FluidInfo(BaseModel):
    """Fluid lookup result from maptis.fluids table.

    Used to resolve fluid_compatibility records to H2/O2 twins.
    """

    fluid_key: str
    fluid_name: str


FluidsResolver = Callable[[str], Optional[FluidInfo]]
"""Type alias for fluid lookup function.

Resolves a fluid_key (fluc_reference) to FluidInfo via the fluids table.
Returns None if join fails (record must be excluded from twins).
"""

FamilyResolver = Callable[[str], Optional[MaterialFamilyKey]]
"""Type alias for material family resolver.

Resolves a material_key to its validated MaterialFamilyKey.
Must be from validated semantic tagging at ingestion time, NOT runtime inference.
"""


def make_fluids_resolver_from_map(fluids_map: Dict[str, FluidInfo]) -> FluidsResolver:
    """Create resolver function from pre-loaded fluids map.

    Args:
        fluids_map: Dict mapping fluid_key to FluidInfo

    Returns:
        FluidsResolver function
    """

    def _resolve(fluid_key: str) -> Optional[FluidInfo]:
        return fluids_map.get(clean_str(fluid_key))

    return _resolve


# ---------------------------------------------------------------------------
# Gas identity rules (deterministic - NO string matching for decisions)
# ---------------------------------------------------------------------------


H2_FLUID_KEYWORDS = {
    "HYDROGEN",
    "H2",
    "LH2",
    "GH2",
    "LIQUID HYDROGEN",
    "GASEOUS HYDROGEN",
}
"""Keywords that definitively identify hydrogen in test fluid fields."""

O2_FLUID_KEYWORDS = {
    "OXYGEN",
    "O2",
    "LOX",
    "GOX",
    "LIQUID OXYGEN",
    "GASEOUS OXYGEN",
}
"""Keywords that definitively identify oxygen in test fluid fields."""


def is_definitive_h2_from_crack_growth(payload: Dict[str, Any]) -> bool:
    """Check if crack_growth record is definitively H2-relevant.

    Uses crk_testfluid field - this is direct evidence of H2 testing.
    """
    fluid = safe_upper(payload.get("crk_testfluid"))
    return ("HYDROGEN" in fluid) or (fluid in H2_FLUID_KEYWORDS)


def is_definitive_o2_from_flammability(payload: Dict[str, Any]) -> bool:
    """Check if flammability record is O2-relevant.

    CRITICAL: Use flam_moc_o2_pct for oxygen signal - NOT flam_gasname.
    flam_gasname can be NITROGEN even in O2 flammability tests.
    """
    o2pct = clean_float(payload.get("flam_moc_o2_pct"))
    return o2pct is not None


def classify_fluid_name(fluid_name: str) -> Optional[GasType]:
    """Classify fluid name to GasType via fluids table join result.

    Args:
        fluid_name: Fluid name from fluids table join

    Returns:
        GasType.H2, GasType.O2, or None if not H2/O2 relevant
    """
    u = safe_upper(fluid_name)
    if any(k in u for k in H2_FLUID_KEYWORDS) or ("HYDROGEN" in u):
        return GasType.H2
    if any(k in u for k in O2_FLUID_KEYWORDS) or ("OXYGEN" in u):
        return GasType.O2
    return None


# ---------------------------------------------------------------------------
# MAPTIS -> CompatibilityRecord mappers
# ---------------------------------------------------------------------------


def map_flammability_row_to_record(
    row: Dict[str, Any],
    family_resolver: Optional[FamilyResolver] = None,
) -> CompatibilityRecord:
    """Map MAPTIS flammability record to O2 twin record.

    Handles MAPTIS edge cases:
    - Whitespace in rating ("C " -> "C")
    - Whitespace in pressure (" 10.2000" -> 10.2)
    - flam_gasname=NITROGEN but moc_o2_pct=30 -> gas_type O2, concentration_pct=30

    CRITICAL: Uses flam_moc_o2_pct over flam_gasname for O2 identity.
    """
    payload = row.get("payload") or {}
    material_key = canonical_maptis_material_key(row.get("material_key"))
    material_name = clean_str(
        row.get("designation") or row.get("name") or "UNKNOWN"
    )

    # Handle whitespace in rating field
    rating = clean_str(
        pick_first(payload.get("flam_rating_6001b"), payload.get("flam_rating"))
    )
    pressure = clean_float(payload.get("flam_pressure"))
    o2pct = clean_float(payload.get("flam_moc_o2_pct"))

    tmin = clean_float(
        pick_first(
            payload.get("temperatureminimum"), row.get("temperature_minimum")
        )
    )
    tmax = clean_float(
        pick_first(
            payload.get("temperaturemaximum"), row.get("temperature_maximum")
        )
    )

    testreport = clean_str(payload.get("testreportnumber"))
    std_ref = clean_str(
        pick_first(payload.get("flam_specification_spec"), "NASA-STD-6001B")
    )

    # Build environment envelope (all fields nullable)
    env = EnvironmentEnvelope(
        temp_min_f=tmin,
        temp_max_f=tmax,
        pressure_min_psia=pressure,
        pressure_max_psia=pressure,
        phase=Phase.GASEOUS if pressure is not None else Phase.UNKNOWN,
        concentration_pct=o2pct,
    )

    env_ev = EnvelopeEvidence(
        data_class=DataClass.DIRECT_TEST,
        source_ref=f"MAPTIS:{testreport}" if testreport else "MAPTIS:flammability_record",
        confidence=1.0,
    )

    props: List[PropertyEvidence] = []

    if rating:
        props.append(
            PropertyEvidence(
                property_key=PropertyKey.FLAMMABILITY_RATING,
                value_text=rating,
                units=None,
                test_method=clean_str(payload.get("flam_testtype")) or None,
                test_temp_f=None,
                test_pressure_psia=pressure,
                source_ref=f"{testreport} / {std_ref}".strip(" /"),
                data_class=DataClass.DIRECT_TEST,
                confidence=1.0,
            )
        )

    if o2pct is not None:
        props.append(
            PropertyEvidence(
                property_key=PropertyKey.OXYGEN_CONCENTRATION_PCT,
                value_numeric=o2pct,
                units="pct",
                test_method=None,
                test_temp_f=None,
                test_pressure_psia=pressure,
                source_ref=f"{testreport} / flam_moc_o2_pct".strip(" /"),
                data_class=DataClass.DIRECT_TEST,
                confidence=1.0,
            )
        )

    if pressure is not None:
        props.append(
            PropertyEvidence(
                property_key=PropertyKey.TEST_PRESSURE_PSIA,
                value_numeric=pressure,
                units="psia",
                test_method=None,
                test_temp_f=None,
                test_pressure_psia=pressure,
                source_ref=f"{testreport} / flam_pressure".strip(" /"),
                data_class=DataClass.DIRECT_TEST,
                confidence=1.0,
            )
        )

    if tmin is not None and tmax is not None:
        props.append(
            PropertyEvidence(
                property_key=PropertyKey.TEMP_MIN_F,
                value_numeric=tmin,
                units="F",
                source_ref=f"{testreport} / temperatureminimum".strip(" /"),
                data_class=DataClass.DIRECT_TEST,
                confidence=1.0,
            )
        )
        props.append(
            PropertyEvidence(
                property_key=PropertyKey.TEMP_MAX_F,
                value_numeric=tmax,
                units="F",
                source_ref=f"{testreport} / temperaturemaximum".strip(" /"),
                data_class=DataClass.DIRECT_TEST,
                confidence=1.0,
            )
        )

    family = family_resolver(material_key) if family_resolver else None
    family = family or MaterialFamilyKey.UNKNOWN

    return CompatibilityRecord(
        record_id=build_record_id("MAPTIS:FLAM", row.get("row_uid"), row.get("idx")),
        material_key=material_key,
        material_name=material_name,
        material_type_key=int(row.get("material_type_key")),
        material_family_key=family,
        gas_type=GasType.O2,
        environment=env,
        environment_evidence=env_ev,
        # CRITICAL: Do NOT infer verdict here - leave as INSUFFICIENT_DATA
        compatibility=CompatibilityClass.INSUFFICIENT_DATA,
        reason=(
            f"MAPTIS flammability test; rating={rating or 'UNKNOWN'}; "
            f"O2%={o2pct if o2pct is not None else 'UNKNOWN'}"
        ),
        mitigation=None,
        properties=props,
        standard_ref=std_ref or "NASA-STD-6001B",
        test_report_id=testreport or None,
        source="MAPTIS",
    )


def map_crack_growth_row_to_record(
    row: Dict[str, Any],
    family_resolver: Optional[FamilyResolver] = None,
) -> Optional[CompatibilityRecord]:
    """Map MAPTIS crack_growth record to H2 twin record.

    Only returns record if crk_testfluid contains HYDROGEN - this is
    direct evidence of H2 testing and should be routed to H2 twin.

    Args:
        row: MAPTIS row dict with test_type="crack_growth"
        family_resolver: Optional resolver for material family

    Returns:
        CompatibilityRecord for H2 twin, or None if not H2-relevant
    """
    payload = row.get("payload") or {}

    if clean_str(row.get("test_type")) != "crack_growth":
        return None

    # Only accept records with definitive H2 evidence
    if not is_definitive_h2_from_crack_growth(payload):
        return None

    material_key = canonical_maptis_material_key(row.get("material_key"))
    material_name = clean_str(
        row.get("designation") or row.get("name") or "UNKNOWN"
    )

    pressure = clean_float(payload.get("crk_pressure"))
    temp = clean_float(payload.get("crk_temperature"))
    fluid = clean_str(payload.get("crk_testfluid"))
    testreport = clean_str(payload.get("testreportnumber"))

    env = EnvironmentEnvelope(
        temp_min_f=temp,
        temp_max_f=temp,
        pressure_min_psia=pressure,
        pressure_max_psia=pressure,
        phase=Phase.UNKNOWN,  # Do NOT guess gas/liquid from pressure alone
        concentration_pct=None,
    )

    env_ev = EnvelopeEvidence(
        data_class=DataClass.DIRECT_TEST,
        source_ref=f"MAPTIS:{testreport}" if testreport else "MAPTIS:crack_growth_record",
        confidence=1.0,
    )

    props = [
        PropertyEvidence(
            property_key=PropertyKey.CRACK_GROWTH_FLUID,
            value_text=fluid,
            source_ref=f"{testreport} / crk_testfluid".strip(" /"),
            data_class=DataClass.DIRECT_TEST,
            confidence=1.0,
        )
    ]

    if pressure is not None:
        props.append(
            PropertyEvidence(
                property_key=PropertyKey.CRACK_GROWTH_PRESSURE_PSIA,
                value_numeric=pressure,
                units="psia",
                source_ref=f"{testreport} / crk_pressure".strip(" /"),
                data_class=DataClass.DIRECT_TEST,
                confidence=1.0,
            )
        )

    if temp is not None:
        props.append(
            PropertyEvidence(
                property_key=PropertyKey.CRACK_GROWTH_TEMPERATURE_F,
                value_numeric=temp,
                units="F",
                source_ref=f"{testreport} / crk_temperature".strip(" /"),
                data_class=DataClass.DIRECT_TEST,
                confidence=1.0,
            )
        )

    family = family_resolver(material_key) if family_resolver else None
    family = family or MaterialFamilyKey.UNKNOWN

    return CompatibilityRecord(
        record_id=build_record_id("MAPTIS:CRK", row.get("row_uid"), row.get("idx")),
        material_key=material_key,
        material_name=material_name,
        material_type_key=int(row.get("material_type_key")),
        material_family_key=family,
        gas_type=GasType.H2,
        environment=env,
        environment_evidence=env_ev,
        # No inferred verdict - leave as INSUFFICIENT_DATA
        compatibility=CompatibilityClass.INSUFFICIENT_DATA,
        reason=f"MAPTIS crack_growth test in H2 (fluid={fluid})",
        mitigation=None,
        properties=props,
        standard_ref="MAPTIS",
        test_report_id=testreport or None,
        source="MAPTIS",
    )


def map_fluid_compatibility_row_to_record(
    row: Dict[str, Any],
    fluids_resolver: FluidsResolver,
    family_resolver: Optional[FamilyResolver] = None,
) -> Optional[CompatibilityRecord]:
    """Map fluid_compatibility record to twin index.

    CRITICAL: MUST NOT be routed without fluids-table join.
    If join fails or fluid not H2/O2 -> return None (exclude from twins).

    Args:
        row: MAPTIS row dict with test_type="fluid_compatibility"
        fluids_resolver: REQUIRED - resolves fluc_reference to fluids table
        family_resolver: Optional resolver for material family

    Returns:
        CompatibilityRecord for appropriate twin, or None if excluded
    """
    if clean_str(row.get("test_type")) != "fluid_compatibility":
        return None

    payload = row.get("payload") or {}
    ref = clean_str(payload.get("fluc_reference"))

    if not ref:
        return None  # Forbidden: cannot identify fluid without reference

    # CRITICAL: Fluids table join is non-negotiable
    fluid_info = fluids_resolver(ref)
    if not fluid_info:
        return None  # Forbidden: join failed

    gas = classify_fluid_name(fluid_info.fluid_name)
    if gas not in (GasType.H2, GasType.O2):
        return None  # Exclude: not H2/O2 relevant

    material_key = canonical_maptis_material_key(row.get("material_key"))
    material_name = clean_str(
        row.get("designation") or row.get("name") or "UNKNOWN"
    )

    rating = clean_str(payload.get("fluc_rating"))
    samplecount = clean_float(payload.get("fluc_samplecount"))
    cleanflag = clean_str(payload.get("fluc_cleanflag"))
    testreport = clean_str(payload.get("testreportnumber"))

    tmin = clean_float(
        pick_first(
            payload.get("temperatureminimum"), row.get("temperature_minimum")
        )
    )
    tmax = clean_float(
        pick_first(
            payload.get("temperaturemaximum"), row.get("temperature_maximum")
        )
    )

    env = EnvironmentEnvelope(
        temp_min_f=tmin,
        temp_max_f=tmax,
        pressure_min_psia=None,
        pressure_max_psia=None,
        phase=Phase.UNKNOWN,
        concentration_pct=None,
    )

    env_ev = EnvelopeEvidence(
        data_class=DataClass.DIRECT_TEST,
        source_ref=(
            f"MAPTIS:{testreport}"
            if testreport
            else "MAPTIS:fluid_compatibility_record"
        ),
        confidence=1.0,
    )

    props: List[PropertyEvidence] = []

    if rating:
        # Reduced confidence if samplecount=0
        conf = 1.0 if (samplecount and samplecount > 0) else 0.7
        prop_key = (
            PropertyKey.H2_EMBRITTLEMENT_CLASS
            if gas == GasType.H2
            else PropertyKey.FLAMMABILITY_RATING
        )
        props.append(
            PropertyEvidence(
                property_key=prop_key,
                value_text=rating,
                source_ref=f"{testreport} / fluc_rating".strip(" /"),
                data_class=DataClass.DIRECT_TEST,
                confidence=conf,
            )
        )

    if cleanflag:
        props.append(
            PropertyEvidence(
                property_key=PropertyKey.CRACK_GROWTH_FLUID,
                value_text=(
                    f"fluid_key={ref}, fluid_name={fluid_info.fluid_name}, "
                    f"cleanflag={cleanflag}"
                ),
                source_ref=f"{testreport} / fluids_join".strip(" /"),
                data_class=DataClass.DERIVED,
                confidence=0.9,
            )
        )

    family = family_resolver(material_key) if family_resolver else None
    family = family or MaterialFamilyKey.UNKNOWN

    return CompatibilityRecord(
        record_id=build_record_id("MAPTIS:FLUC", row.get("row_uid"), row.get("idx")),
        material_key=material_key,
        material_name=material_name,
        material_type_key=int(row.get("material_type_key")),
        material_family_key=family,
        gas_type=gas,
        environment=env,
        environment_evidence=env_ev,
        compatibility=CompatibilityClass.INSUFFICIENT_DATA,
        reason=(
            f"MAPTIS fluid_compatibility test; fluid={fluid_info.fluid_name}; "
            f"rating={rating or 'UNKNOWN'}"
        ),
        mitigation=None,
        properties=props,
        standard_ref="MAPTIS",
        test_report_id=testreport or None,
        source="MAPTIS",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def maptis_rows_to_twin_records(
    rows: Iterable[Dict[str, Any]],
    fluids_resolver: Optional[FluidsResolver] = None,
    family_resolver: Optional[FamilyResolver] = None,
) -> Tuple[List[CompatibilityRecord], List[str]]:
    """Convert raw MAPTIS export rows into CompatibilityRecords for H2/O2 twins.

    Routing rules (from spec):
    - flammability -> O2 twin (uses flam_moc_o2_pct, NOT flam_gasname)
    - crack_growth -> H2 twin (if crk_testfluid contains HYDROGEN)
    - fluid_compatibility -> REQUIRES fluids table join, excluded without it

    Args:
        rows: Iterable of MAPTIS row dicts
        fluids_resolver: Required for fluid_compatibility records (join to fluids table)
        family_resolver: Optional resolver for material_family_key

    Returns:
        Tuple of (records, warnings)
    """
    out: List[CompatibilityRecord] = []
    warnings: List[str] = []

    for row in rows:
        test_type = clean_str(row.get("test_type"))

        try:
            if test_type == "flammability":
                rec = map_flammability_row_to_record(
                    row, family_resolver=family_resolver
                )
                out.append(rec)

            elif test_type == "crack_growth":
                rec = map_crack_growth_row_to_record(
                    row, family_resolver=family_resolver
                )
                if rec:
                    out.append(rec)

            elif test_type == "fluid_compatibility":
                if fluids_resolver is None:
                    # Hard rule: forbidden without join
                    warnings.append(
                        f"Skipped fluid_compatibility row_uid={clean_str(row.get('row_uid'))}: "
                        "fluids_resolver not provided (join required)."
                    )
                    continue

                rec = map_fluid_compatibility_row_to_record(
                    row,
                    fluids_resolver=fluids_resolver,
                    family_resolver=family_resolver,
                )
                if rec:
                    out.append(rec)
                else:
                    warnings.append(
                        f"Excluded fluid_compatibility row_uid={clean_str(row.get('row_uid'))}: "
                        "fluid not resolved to H2/O2 or join failed."
                    )

            else:
                # Ignore other test types for now (outgassing, tensile, etc.)
                continue

        except Exception as e:
            logger.error(
                f"Failed to parse row: {e}",
                extra={"row_uid": clean_str(row.get("row_uid"))},
            )
            warnings.append(
                f"Failed to parse row_uid={clean_str(row.get('row_uid'))}, "
                f"test_type={test_type}: {e}"
            )

    logger.info(f"Processed {len(out)} records, {len(warnings)} warnings")
    return out, warnings
