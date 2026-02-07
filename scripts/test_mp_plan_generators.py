#!/usr/bin/env python3
"""Quick test script for M&P Plan generators."""

import sys
sys.path.insert(0, "c:/BoundState")

from mira.mp_plan.models import (
    PlanGeneratorSession,
    EnvironmentDefinition,
    MaterialEntry,
    MaterialResolutionResult,
    NonconformanceSignal,
    MinorQuantityAggregation,
    MinorQuantityGroup,
)
from mira.compliance.models.enums import FailureMode, GapSeverity

# Create a test session
print("Creating test session...")
session = PlanGeneratorSession(
    session_id="test-001",
    program_name="Test Program",
    program_phase="Phase A",
    source="test_script",
)

# Add environment
print("Adding environment...")
env = EnvironmentDefinition(
    name="Crew Cabin",
    o2_pct=30.0,
    pressure_psia=10.2,
    temp_range_c=(18.0, 27.0),
    habitable=True,
    source="test",
)
session.environments.append(env)

# Add material
print("Adding material...")
material = MaterialEntry(
    name="Test Polymer",
    application="Insulation",
    quantity=5,
    maptis_code="POLY-001",
    mass_g=150.0,
    surface_area_cm2=45.0,
    source="test",
)
session.materials.append(material)

# Add resolution
print("Adding MAPTIS resolution...")
resolution = MaterialResolutionResult(
    material_id=material.id,
    maptis_code="POLY-001",
    flam_rating="C",
    tvs_rating="B",
    tox_rating="A",
    test_o2_pct=23.5,
    source="test",
)
session.maptis_resolutions.append(resolution)

# Add a nonconformance
print("Adding nonconformance...")
nc = NonconformanceSignal(
    material_id=material.id,
    environment_id=env.environment_id,
    gap_type=FailureMode.FLAM,
    failing_requirement="MPR 44(a)",
    failing_value="C @ 23.5% O2",
    required_value="A @ 30% O2",
    severity=GapSeverity.MEDIUM,
    confidence=0.9,
    affected_mprs=["MPR44"],
    source_adapter="test",
)
session.nonconformances.append(nc)

# Add minor quantity aggregation
print("Adding minor quantity aggregation...")
group = MinorQuantityGroup(
    environment_id=env.environment_id,
    ignition_source_class="low_energy",
    adjacency_group="zone_1",
    material_ids=[material.id],
    total_mass_g=150.0,
    total_surface_area_cm2=45.0,
    eligible=True,
    eligibility_rationale="Below 250g threshold per MPR 44(c)",
)
session.minor_quantity_aggregation = MinorQuantityAggregation(
    groups=[group],
    program_total_mass_g=150.0,
    program_total_area_cm2=45.0,
)

print(f"Session can_generate: {session.can_generate()}")

# Test generators
print("\n--- Testing Generators ---\n")

# 1. Test Section Builder
print("1. Testing SectionBuilder...")
try:
    from mira.mp_plan.generation import SectionBuilder
    builder = SectionBuilder(session)
    sections = builder.build_all_sections()
    print(f"   SUCCESS: Built {len(sections)} sections")
    for s in sections:
        print(f"      - {s.section_number} {s.section_title}")
except Exception as e:
    print(f"   FAILED: {e}")

# 2. Test DOCX Generator
print("\n2. Testing DOCX Generator...")
try:
    from mira.mp_plan.generation import generate_mp_plan_docx
    docx_bytes = generate_mp_plan_docx(session)
    print(f"   SUCCESS: Generated {len(docx_bytes)} bytes")
except Exception as e:
    print(f"   FAILED: {e}")
    import traceback
    traceback.print_exc()

# 3. Test MIUL Excel Generator
print("\n3. Testing MIUL Excel Generator...")
try:
    from mira.mp_plan.generation import generate_miul_xlsx
    xlsx_bytes = generate_miul_xlsx(session)
    print(f"   SUCCESS: Generated {len(xlsx_bytes)} bytes")
except Exception as e:
    print(f"   FAILED: {e}")
    import traceback
    traceback.print_exc()

# 4. Test Review Packet Generator
print("\n4. Testing Review Packet Generator...")
try:
    from mira.mp_plan.generation import generate_review_packet
    packet = generate_review_packet(session)
    print(f"   SUCCESS: Generated packet with {len(packet.predicted_questions)} predicted questions")
    print(f"      - Test deltas: {len(packet.test_deltas)}")
    print(f"      - Key findings: {len(packet.key_findings)}")
except Exception as e:
    print(f"   FAILED: {e}")
    import traceback
    traceback.print_exc()

print("\n--- All tests complete ---")
