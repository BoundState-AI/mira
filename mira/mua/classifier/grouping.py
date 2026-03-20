"""MUA Grouping Logic — BS-SPEC-MUA-003.

One MUA per unique combination of MAPTIS code + issue key. All parts
sharing the same MAPTIS code and issue get one MUA, because the rationale
is identical — the physics don't change between a drive link and a nut
made of the same alloy in the same valve in the same environment.

Example: 50 A286 FS=U part occurrences -> 1 MUA.

This reduces ~130 potential MUAs to ~15-20. The prior system was
generating per-part, which would have produced 130 documents with
identical rationale.

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .classifier import classify_mua
from .models import (
    ClassifierResult,
    MaterialClassEnum,
    MUAGroup,
    MUAType,
)


def group_by_maptis_issue(
    miul_rows: list[dict[str, Any]],
) -> list[MUAGroup]:
    """Group MIUL rows by MAPTIS code + issue key for MUA generation.

    Each input row must contain:
    - maptis_code: str
    - issue_key: str
    - rating: str
    - material_class: str ("metal" or "nonmetallic")
    - media: str
    - designation: str (human-readable material name)
    - environment: str (optional, defaults to "non-habitable")
    - o2_percent: float (optional)
    - batch_verified: bool (optional)
    - part_number: str (optional)
    - material_specification: str (optional)
    - pressure: str (optional)
    - temperature: str (optional)
    - location: str (optional)
    - application: str (optional)

    Returns a list of MUAGroup, one per unique (maptis_code, issue_key).
    Groups where no MUA is needed (STANDARD type with screening not
    applicable) are excluded.
    """
    # Accumulate rows by (maptis_code, issue_key)
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in miul_rows:
        code = str(row.get("maptis_code") or "").strip()
        issue = str(row.get("issue_key") or "").strip().upper()
        if not code or not issue:
            continue
        buckets[(code, issue)].append(row)

    groups: list[MUAGroup] = []
    for (code, issue), rows in sorted(buckets.items()):
        # Use first row as representative for classification
        first = rows[0]
        result = classify_mua(
            maptis_code=code,
            issue_key=issue,
            rating=first.get("rating", ""),
            material_class=first.get("material_class", "metal"),
            media=first.get("media", ""),
            environment=first.get("environment", "non-habitable"),
            o2_percent=first.get("o2_percent"),
            batch_verified=first.get("batch_verified", False),
        )

        # Skip groups that need no MUA
        if result.mua_type == MUAType.STANDARD and not result.screening_applicable:
            continue

        # Collect part numbers
        part_numbers = sorted({
            str(r.get("part_number", "")).strip()
            for r in rows
            if r.get("part_number")
        })

        # Aggregate environment info
        media_set = {str(r.get("media", "")).strip().upper() for r in rows if r.get("media")}
        pressures = [str(r.get("pressure", "")).strip() for r in rows if r.get("pressure")]
        temps = [str(r.get("temperature", "")).strip() for r in rows if r.get("temperature")]
        locations = {str(r.get("location", "")).strip() for r in rows if r.get("location")}
        applications = {str(r.get("application", "")).strip() for r in rows if r.get("application")}

        # Build pressure/temp range strings
        pressure_range = None
        if pressures:
            pressure_range = ", ".join(sorted(set(pressures)))
        temp_range = None
        if temps:
            temp_range = ", ".join(sorted(set(temps)))

        group = MUAGroup(
            maptis_code=code,
            issue_key=issue,
            material_designation=str(first.get("designation", "")).strip(),
            material_class=result.material_class,
            rating=result.rating,
            mua_type=result.mua_type,
            category=result.category,
            confidence=result.confidence,
            part_numbers=part_numbers,
            part_count=len(rows),
            media=", ".join(sorted(media_set)) if media_set else "",
            pressure_range=pressure_range,
            temp_range=temp_range,
            location=", ".join(sorted(locations)) if locations else "non-habitable",
            application=", ".join(sorted(applications)) if applications else "",
            material_specification=str(first.get("material_specification", "")).strip() or None,
            companion_mua_ref=result.companion_mua_ref,
        )
        groups.append(group)

    return groups
