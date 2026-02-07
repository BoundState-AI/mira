#!/usr/bin/env python3
"""
Module: Llm Decision Guardrails
Purpose: from typing import Dict, Any, List, Optional

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


# ============================================================================
# SYSTEM PROMPT
# ============================================================================

DECISION_SYSTEM_PROMPT = """You are a safety-critical material compatibility expert for aerospace applications.

HARD RULES - DO NOT VIOLATE:

1. UNIT INTEGRITY:
   - Do NOT guess or "fix" units
   - If units are missing or inconsistent, explicitly flag this as unreliable
   - If unit_status != "ok", state that the value CANNOT be used as a limit
   - Never convert units unless both source and target units are explicitly confirmed
   - Examples of FORBIDDEN inferences:
     * "760 could be 760 Torr = 14.7 psia" ❌
     * "This looks like it should be in psi" ❌
     * "Assuming Celsius since it's NASA" ❌

2. ENVIRONMENT COMPATIBILITY:
   - Do NOT infer oxygen compatibility from non-oxygen environments
   - Testing in air does NOT prove oxygen compatibility
   - Testing in vacuum does NOT prove oxygen compatibility
   - Testing in inert gas does NOT prove oxygen compatibility
   - Only accept oxygen compatibility if explicitly tested in oxygen (GOX/LOX)
   - Examples of FORBIDDEN inferences:
     * "Tested in air, should work in oxygen" ❌
     * "Vacuum-rated, probably OK in oxygen" ❌
     * "Nitrogen service, close enough to oxygen" ❌

3. DATA RELIABILITY:
   - If evidence is ambiguous, incomplete, or conflicting: say so
   - Do NOT fill gaps with assumptions
   - Do NOT "round up" compatibility based on similarity
   - Err on the side of NEEDS_REVIEW when data quality is poor

4. MARGIN REQUIREMENTS:
   - Only consider a material inside the envelope if BOTH:
     a) Same environment as tested (see rule 2)
     b) Clear numeric margins with confirmed units (see rule 1)
   - "Gently outside" is acceptable ONLY if:
     a) Overage is <5% for pressure or <10°C for temperature
     b) Strong precedent exists (multiple approved MUAs)
     c) You explicitly call out the overage

OUTPUT FORMAT:
When analyzing a material candidate, structure your response as:

DECISION: [YES / YES_WITH_CAVEATS / NO / NEEDS_REVIEW]

REASONING:
- Environment compatibility: [statement]
- Unit reliability: [statement]
- Margin analysis: [statement with numbers]
- BOK/MUA precedent: [statement]

FLAGS:
- Any unit ambiguities detected
- Any environment mismatches detected
- Any data quality issues

CITATIONS:
- [spec_id] § [section] - [description]
- MUA [mua_number] - [system type, conditions]
"""


# ============================================================================
# EVIDENCE BUNDLE FORMATTER
# ============================================================================

@dataclass
class EvidenceBundle:
    """
    Formatted evidence bundle for LLM decision-making.

    Pre-formatted with:
    - Rounded numeric values
    - Explicit unit fields
    - Unit status flags
    - Environment compatibility flags
    """
    material_id: str
    material_name: str

    # Requirements
    required_env: Optional[str]
    required_pressure_psia: Optional[float]
    required_temp_c: Optional[float]

    # Test data (pre-formatted)
    tested_env: Optional[str]
    tested_pressure_psia: Optional[float]
    tested_temp_c: Optional[float]

    # Unit status
    unit_status: Dict[str, str]  # "ok" / "missing" / "ambiguous"

    # Flags
    env_mismatch: bool
    unit_ambiguous: bool

    # Supporting evidence
    bok_requirements: List[Dict[str, Any]]
    mua_precedents: List[Dict[str, Any]]

    def to_llm_prompt(self) -> str:
        """
        Format evidence bundle as LLM prompt.

        Includes explicit warnings about unit status and environment mismatch.
        """
        lines = []

        lines.append(f"MATERIAL: {self.material_name} (ID: {self.material_id})")
        lines.append("")

        lines.append("REQUIREMENTS:")
        lines.append(f"  Environment: {self.required_env or 'not specified'}")

        if self.required_pressure_psia is not None:
            lines.append(f"  Max Pressure: {self.required_pressure_psia:.1f} psia")
        else:
            lines.append(f"  Max Pressure: not specified")

        if self.required_temp_c is not None:
            lines.append(f"  Max Temperature: {self.required_temp_c:.1f} °C")
        else:
            lines.append(f"  Max Temperature: not specified")
        lines.append("")

        lines.append("TEST DATA:")
        lines.append(f"  Tested Environment: {self.tested_env or 'UNKNOWN'}")

        if self.tested_pressure_psia is not None:
            lines.append(f"  Tested Pressure: {self.tested_pressure_psia:.1f} psia")
        else:
            lines.append(f"  Tested Pressure: MISSING")

        if self.tested_temp_c is not None:
            lines.append(f"  Tested Temperature: {self.tested_temp_c:.1f} °C")
        else:
            lines.append(f"  Tested Temperature: MISSING")
        lines.append("")

        # CRITICAL: Unit status warnings
        lines.append("UNIT STATUS:")
        for field, status in self.unit_status.items():
            if status != "ok":
                lines.append(f"  ⚠️  {field}: {status.upper()}")
                lines.append(f"      → Cannot use as reliable limit!")
            else:
                lines.append(f"  ✓ {field}: {status}")
        lines.append("")

        # CRITICAL: Environment mismatch warning
        if self.env_mismatch:
            lines.append("⚠️  ENVIRONMENT MISMATCH DETECTED")
            lines.append(f"    Tested in: {self.tested_env}")
            lines.append(f"    Required for: {self.required_env}")
            lines.append(f"    → Do NOT infer compatibility across environments")
            lines.append("")

        # BOK requirements
        if self.bok_requirements:
            lines.append("BOK REQUIREMENTS:")
            for req in self.bok_requirements:
                spec_id = req.get('spec_id', 'UNKNOWN')
                section = req.get('section_number', '')
                summary = req.get('summary', '')
                lines.append(f"  • {spec_id} § {section}: {summary}")
            lines.append("")

        # MUA precedents
        if self.mua_precedents:
            lines.append("MUA PRECEDENTS:")
            for mua in self.mua_precedents:
                mua_num = mua.get('mua_number', 'UNKNOWN')
                system = mua.get('system_type', '')
                env = mua.get('environment', '')
                pressure = mua.get('pressure_max_psia', 'N/A')
                status = mua.get('approval_status', 'unknown')
                lines.append(f"  • {mua_num} - {system} in {env}")
                lines.append(f"    Pressure: {pressure} psia, Status: {status}")
            lines.append("")

        return "\n".join(lines)


def build_evidence_bundle(
    candidate: Dict[str, Any],
    constraints: Dict[str, Any],
    unit_status: Dict[str, str],
    env_mismatch: bool,
    bok_requirements: Optional[List[Dict[str, Any]]] = None,
    mua_precedents: Optional[List[Dict[str, Any]]] = None,
) -> EvidenceBundle:
    """
    Build evidence bundle from candidate and constraints.

    Args:
        candidate: Material candidate dict with test data
        constraints: User constraints dict
        unit_status: Unit status dict from MaterialDecider
        env_mismatch: Environment mismatch flag from MaterialDecider
        bok_requirements: List of applicable BOK requirements
        mua_precedents: List of MUA precedents

    Returns:
        EvidenceBundle ready for LLM prompt
    """
    # Pre-format numeric fields (round to sensible precision)
    tested_pressure_pa = candidate.get('pressure_max_tested_pa')
    tested_pressure_psia = round(tested_pressure_pa / 6894.76, 1) if tested_pressure_pa else None

    tested_temp_c = candidate.get('temp_max_tested_c')
    tested_temp_c = round(tested_temp_c, 1) if tested_temp_c is not None else None

    required_pressure_pa = constraints.get('pressure_max_pa')
    required_pressure_psia = round(required_pressure_pa / 6894.76, 1) if required_pressure_pa else None

    required_temp_c = constraints.get('temp_max_c')
    required_temp_c = round(required_temp_c, 1) if required_temp_c is not None else None

    # Check if units are ambiguous
    unit_ambiguous = any(status != 'ok' for status in unit_status.values())

    return EvidenceBundle(
        material_id=str(candidate.get('material_id', '')),
        material_name=candidate.get('material_name', 'Unknown'),
        required_env=constraints.get('environment'),
        required_pressure_psia=required_pressure_psia,
        required_temp_c=required_temp_c,
        tested_env=candidate.get('environment'),
        tested_pressure_psia=tested_pressure_psia,
        tested_temp_c=tested_temp_c,
        unit_status=unit_status,
        env_mismatch=env_mismatch,
        unit_ambiguous=unit_ambiguous,
        bok_requirements=bok_requirements or [],
        mua_precedents=mua_precedents or [],
    )


# ============================================================================
# TESTS
# ============================================================================

def test_evidence_bundle_formatting():
    """Test evidence bundle formatting"""
    candidate = {
        'material_id': 'mat_viton_a',
        'material_name': 'Viton A Fluoroelastomer',
        'environment': 'oxygen',
        'pressure_max_tested_pa': 20684280,  # 3000 psia
        'temp_max_tested_c': 150.0,
    }

    constraints = {
        'environment': 'oxygen',
        'pressure_max_pa': 13789520,  # 2000 psia
        'temp_max_c': 120.0,
    }

    unit_status = {
        'temperature': 'ok',
        'pressure': 'ok',
    }

    bundle = build_evidence_bundle(
        candidate=candidate,
        constraints=constraints,
        unit_status=unit_status,
        env_mismatch=False,
    )

    prompt = bundle.to_llm_prompt()

    assert 'Viton A' in prompt
    assert '3000.0 psia' in prompt
    assert '150.0 °C' in prompt
    assert 'oxygen' in prompt

    print("✓ Evidence bundle formatting works")
    print("\nSample prompt:")
    print("=" * 80)
    print(prompt)
    print("=" * 80)


def test_environment_mismatch_warning():
    """Test environment mismatch warning in prompt"""
    candidate = {
        'material_id': 'mat_test',
        'material_name': 'Test Material',
        'environment': 'air',
        'pressure_max_tested_pa': 20684280,
        'temp_max_tested_c': 150.0,
    }

    constraints = {
        'environment': 'oxygen',
        'pressure_max_pa': 13789520,
        'temp_max_c': 120.0,
    }

    unit_status = {
        'temperature': 'ok',
        'pressure': 'ok',
    }

    bundle = build_evidence_bundle(
        candidate=candidate,
        constraints=constraints,
        unit_status=unit_status,
        env_mismatch=True,  # Environment mismatch!
    )

    prompt = bundle.to_llm_prompt()

    assert 'ENVIRONMENT MISMATCH DETECTED' in prompt
    assert 'Do NOT infer compatibility' in prompt

    print("✓ Environment mismatch warning works")


def test_unit_ambiguity_warning():
    """Test unit ambiguity warning in prompt"""
    candidate = {
        'material_id': 'mat_test',
        'material_name': 'Test Material',
        'environment': 'oxygen',
        'pressure_max_tested_pa': None,  # Missing!
        'temp_max_tested_c': 150.0,
    }

    constraints = {
        'environment': 'oxygen',
        'pressure_max_pa': 13789520,
        'temp_max_c': 120.0,
    }

    unit_status = {
        'temperature': 'ok',
        'pressure': 'missing',  # Missing pressure!
    }

    bundle = build_evidence_bundle(
        candidate=candidate,
        constraints=constraints,
        unit_status=unit_status,
        env_mismatch=False,
    )

    prompt = bundle.to_llm_prompt()

    assert 'MISSING' in prompt
    assert 'Cannot use as reliable limit' in prompt

    print("✓ Unit ambiguity warning works")


def run_tests():
    """Run all tests"""
    print("=" * 80)
    print("TESTING LLM DECISION GUARDRAILS")
    print("=" * 80)

    tests = [
        test_evidence_bundle_formatting,
        test_environment_mismatch_warning,
        test_unit_ambiguity_warning,
    ]

    for test_func in tests:
        try:
            test_func()
        except AssertionError as e:
            print(f"✗ {test_func.__name__} FAILED: {e}")
            return False
        except Exception as e:
            print(f"✗ {test_func.__name__} ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False

    print("\n" + "=" * 80)
    print("ALL TESTS PASSED")
    print("=" * 80)
    return True


if __name__ == '__main__':
    import sys
    sys.exit(0 if run_tests() else 1)
