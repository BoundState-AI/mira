#!/usr/bin/env python3
"""Demo: Show v8 template-rendered MUA output for the same session data as v7."""

import sys
sys.path.insert(0, "/home/user/mira-dev")

from mira.mua.v8.models import (
    MUAEnvironment,
    MUAEvidenceStrength,
    MUAGap,
    MUAPrecedent,
    MUASessionData,
)
from mira.mua.v8.renderer import MUADocumentRenderer


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
    reviewer="Test",
    environment=MUAEnvironment(
        medium="Air",
        o2_percent=21.0,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=85.0,
        location="habitable",
        application="this is a equipment rack",
    ),
    ratings=[],
    gaps=[
        MUAGap(
            gap_id="gap-tox-bc50508d",
            dimension="toxicity",
            severity="critical",
            description="Habitable environment requires current toxicity (TOX) test data, which is absent or expired.",
            disposition="Accept With Rationale",
            rationale="test",
        ),
        MUAGap(
            gap_id="gap-test-flamm-7350c8a9",
            dimension="flammability",
            severity="high",
            description="No current FLAMM test data available. This test class is required for the queried environment.",
            disposition="Accept With Rationale",
            rationale="test",
        ),
        MUAGap(
            gap_id="gap-test-tox-13d49b7c",
            dimension="toxicity testing",
            severity="medium",
            description="No current TOX test data available. This test class is required for the queried environment.",
            disposition="Accept With Rationale",
            rationale="test",
        ),
    ],
    evidence_strength=MUAEvidenceStrength(
        band="INSUFFICIENT",
        score=0.0,
        components={
            "precedent_support": "0.000 (no supporting precedents)",
            "test_coverage": "0.000 (FLAMM: missing, TOX: missing)",
        },
    ),
    banners=["Novel material with limited precedent data."],
    precedents=[
        MUAPrecedent(
            mua_number="90-A-430",
            material_name="6061-T6 Aluminum",
            determination="APPROVED",
            rationale="Material has extensive flight heritage in ambient air habitable environments per numerous ISS rack assemblies. Toxicity and flammability testing per NASA-STD-6001 Test 7 confirmed acceptable offgassing products within SMAC limits for the crew cabin volume.",
        ),
    ],
)

renderer = MUADocumentRenderer()
doc = renderer.render_without_llm(session)
print(doc.document_text)
