#!/usr/bin/env python3
"""
Demo: V8 MUA 80/20 Workflow

Shows the complete workflow:
1. AI builds draft from session data + precedents
2. Engineer reviews each section (simulated)
3. Final document rendered
"""

import sys
sys.path.insert(0, "/home/user/mira-dev")

from mira.mua.v8.models import (
    MUAEnvironment,
    MUAEvidenceStrength,
    MUAGap,
    MUAPrecedent,
    MUASessionData,
)
from mira.mua.v8.draft_builder import MUADraftBuilder
from mira.mua.v8.renderer import MUADocumentRenderer
from mira.mua.v8.workflow import ReviewAction


# --- Step 1: Session data (from v7 engine) ---
session = MUASessionData(
    mua_id="MUA-MIRA-2026-0001",
    session_id="e3abb10c-4f76-4cb2-936c-2efc30e97339",
    finalized_at="2026-02-09",
    material_name="Aluminum 6061-T6",
    maptis_code="MAT-A00601",
    material_class="metal",
    category="II",
    center="MSFC",
    applied_standard="NASA-STD-6016C",
    reviewer="J. Smith",
    environment=MUAEnvironment(
        medium="Air",
        o2_percent=21.0,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=85.0,
        location="habitable",
        application="equipment rack for ISS payload integration",
    ),
    ratings=[],
    gaps=[
        MUAGap(
            gap_id="gap-tox-bc50508d",
            dimension="toxicity",
            severity="critical",
            description="Habitable environment requires current toxicity (TOX) test data, which is absent or expired.",
            disposition="Accept With Rationale",
            rationale="Material has extensive ISS heritage per MUA 90-A-430. Aluminum 6061-T6 is a well-characterized metallic alloy with no significant offgassing or toxicity concerns in ambient air environments.",
        ),
        MUAGap(
            gap_id="gap-test-flamm-7350c8a9",
            dimension="flammability",
            severity="high",
            description="No current FLAMM test data available. This test class is required for the queried environment.",
            disposition="Accept With Rationale",
            rationale="6061-T6 aluminum is a non-flammable metallic alloy. Metals in this family do not support combustion in ambient air at the operating pressures and temperatures specified.",
        ),
        MUAGap(
            gap_id="gap-test-tox-13d49b7c",
            dimension="toxicity testing",
            severity="medium",
            description="No current TOX test data available. This test class is required for the queried environment.",
            disposition="Accept With Rationale",
            rationale="Per ISS heritage, 6061-T6 aluminum offgassing products are within SMAC limits for habitable crew cabin environments.",
        ),
    ],
    evidence_strength=MUAEvidenceStrength(
        band="LIMITED",
        score=0.35,
    ),
    banners=["Novel material with limited precedent data."],
    # Precedents pre-loaded (would normally come from Postgres)
    precedents=[
        MUAPrecedent(
            mua_number="90-A-430",
            material_name="6061-T6 Aluminum",
            determination="APPROVED",
            rationale=(
                "Material has extensive flight heritage in ambient air habitable "
                "environments per numerous ISS rack assemblies. Toxicity and "
                "flammability testing per NASA-STD-6001 Test 7 confirmed acceptable "
                "offgassing products within SMAC limits for the crew cabin volume. "
                "6061-T6 is a well-characterized wrought aluminum alloy that has been "
                "used extensively in aerospace applications for structural members, "
                "brackets, and equipment enclosures."
            ),
            relevance_score=0.92,
        ),
        MUAPrecedent(
            mua_number="WCE-2019-0042",
            material_name="6061-T651 Aluminum",
            determination="APPROVED",
            rationale=(
                "6061-T651 aluminum alloy is acceptable for use in the habitable "
                "environment based on extensive test history and heritage usage on "
                "ISS and Shuttle programs."
            ),
            relevance_score=0.85,
        ),
    ],
)

# --- Step 2: Build draft ---
builder = MUADraftBuilder(use_llm=False)
workflow = builder.build_draft(session)

print("=" * 70)
print("V8 MUA DRAFT WORKFLOW")
print("=" * 70)
print(f"\nReview Progress: {workflow.review_progress}")
print(f"\nSections ({len(workflow.sections)}):")
for s in workflow.sections:
    marker = "[NEEDS REVIEW]" if s.needs_review else "[OK]"
    attr_info = f" ({len(s.attributions)} precedent citations)" if s.attributions else ""
    print(f"  {s.section_number}. {s.section_title} {marker}{attr_info}")

print("\n" + "=" * 70)
print("DRAFT DOCUMENT (before engineer review)")
print("=" * 70)

# Render with header/footer
renderer = MUADocumentRenderer()
header = renderer._render_header(session)
body = workflow.render_final()
footer = renderer._render_footer(session)
print(f"{header}\n{body}\n{footer}")

# --- Step 3: Simulate engineer review ---
print("\n" + "=" * 70)
print("ENGINEER REVIEW (simulated)")
print("=" * 70)

# Accept all AI sections
for s in workflow.sections:
    if s.section_number != 4:  # Accept all except rationale
        workflow.review_section(s.section_number, ReviewAction.ACCEPT, reviewer="J. Smith")

# Engineer edits the rationale section
workflow.review_section(
    section_number=4,
    action=ReviewAction.EDIT,
    content=(
        "    4. ENGINEERING RATIONALE\n"
        "\n"
        "    Aluminum 6061-T6 (MAPTIS: MAT-A00601) is a well-characterized\n"
        "    wrought aluminum alloy with extensive flight heritage in NASA\n"
        "    habitable environments. Per precedent MUA 90-A-430, this material\n"
        "    has been approved for numerous ISS rack assemblies in ambient air\n"
        "    cabin environments.\n"
        "\n"
        "    Toxicity and flammability testing per NASA-STD-6001 Test 7 has\n"
        "    confirmed that offgassing products are within Spacecraft Maximum\n"
        "    Allowable Concentration (SMAC) limits for crew cabin volumes.\n"
        "    As a non-flammable metallic alloy, 6061-T6 does not support\n"
        "    combustion in ambient air at the specified operating conditions\n"
        "    (14.7 psia, 21% O2, 60-85 degF).\n"
        "\n"
        "    Based on 2 precedent MUAs (90-A-430, WCE-2019-0042) and\n"
        "    the material's established heritage, the available evidence\n"
        "    supports continued use in the habitable environment for the\n"
        "    specified equipment rack application.\n"
        "\n"
        "    Evidence Strength: LIMITED (0.350) - heritage-based assessment.\n"
    ),
    reviewer="J. Smith",
    notes="Expanded rationale with specific heritage and test references.",
)

print(f"\nFinal Progress: {workflow.review_progress}")
print(f"Ready to finalize: {workflow.is_ready_to_finalize}")

print("\n" + "=" * 70)
print("FINAL DOCUMENT (after engineer review)")
print("=" * 70)

final_body = workflow.render_final()
print(f"{header}\n{final_body}\n{footer}")
