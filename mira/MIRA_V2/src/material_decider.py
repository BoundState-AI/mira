#!/usr/bin/env python3
"""
Module: Material Decider
Purpose: Material Decider - Make go/no-go decisions based on evidence

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

from typing import List, Dict
from dataclasses import dataclass, asdict


@dataclass
class MaterialDecision:
    """Material suitability decision with evidence."""
    material_name: str
    decision: str  # YES, YES_WITH_CAVEATS, NO, REQUIRES_TESTING
    rationale: str
    evidence_sources: List[str]
    caveats: List = None
    confidence: float = 0.0

    def to_dict(self):
        return asdict(self)


class MaterialDecider:
    """Make evidence-based material suitability decisions."""

    def decide_material_suitability(
        self,
        candidate: Dict,
        constraints: Dict,
        mua_precedents: List[Dict],
        test_evidence: List[Dict],
        requirements: List[Dict]
    ) -> MaterialDecision:
        """
        Make decision based on MUAs + test data + requirements.

        Decision hierarchy (evidence-first):
        1. MUA precedent APPROVED -> YES (highest confidence)
        2. MUA precedent CONDITIONAL -> YES_WITH_CAVEATS
        3. Test data meets requirements -> YES
        4. Test data with margins -> YES_WITH_CAVEATS
        5. No evidence -> REQUIRES_TESTING

        Args:
            candidate: Test result candidate
            constraints: Query constraints
            mua_precedents: Relevant MUA precedents (already filtered)
            test_evidence: Evidence rows for this material
            requirements: Applicable requirements from bok.requirements

        Returns:
            MaterialDecision with rationale and evidence sources
        """
        material_name = candidate.get('material_name', 'Unknown')
        environment = (constraints.get('environment') or '').lower()
        is_oxygen_case = 'oxygen' in environment or 'gox' in environment or 'lox' in environment or 'o2' in environment or 'o₂' in environment

        # Priority 1: Check MUA precedents FIRST (with environment matching)
        if mua_precedents:
            # Separate primary (matching environment) from secondary (non-matching)
            primary_muas = [m for m in mua_precedents if m.get('is_primary_for_env', False)]
            secondary_muas = [m for m in mua_precedents if not m.get('is_primary_for_env', False)]

            print(f"[DECIDER] {material_name}: primary={len(primary_muas)}, secondary={len(secondary_muas)}, oxygen_case={is_oxygen_case}")

            # CRITICAL SAFETY CHECK: For oxygen questions, ONLY primary oxygen MUAs count
            if is_oxygen_case and len(primary_muas) == 0 and len(secondary_muas) > 0:
                # Oxygen question but only non-oxygen MUAs found
                return MaterialDecision(
                    material_name=material_name,
                    decision='REQUIRES_TESTING',
                    rationale=f"Only non-oxygen MUAs found ({', '.join(m['mua_number'] for m in secondary_muas)}). Cannot infer oxygen compatibility from air/vacuum or other environment data.",
                    evidence_sources=[m['mua_number'] for m in secondary_muas],
                    caveats=["Non-matching environment MUA only", "Oxygen-specific testing required"],
                    confidence=0.3
                )

            # Multiple primary MUAs → APPROVED
            if len(primary_muas) >= 2:
                approved_primary = [m for m in primary_muas if m['determination'] == 'APPROVED']
                if approved_primary:
                    return MaterialDecision(
                        material_name=material_name,
                        decision='YES',
                        rationale=f"Approved per {len(approved_primary)} MUA precedents in matching environment",
                        evidence_sources=[m['mua_number'] for m in approved_primary],
                        confidence=0.88
                    )

            # Single primary MUA → CONDITIONAL (needs engineering review)
            if len(primary_muas) == 1:
                mua = primary_muas[0]
                if mua['determination'] == 'APPROVED':
                    return MaterialDecision(
                        material_name=material_name,
                        decision='YES_WITH_CAVEATS',
                        rationale=f"Single MUA {mua['mua_number']} in matching environment. Engineering review recommended.",
                        evidence_sources=[mua['mua_number']],
                        caveats=["Single precedent - recommend additional review"],
                        confidence=0.70
                    )
                elif mua['determination'] == 'CONDITIONAL':
                    mitigations = mua.get('mitigations', [])
                    return MaterialDecision(
                        material_name=material_name,
                        decision='YES_WITH_CAVEATS',
                        rationale=f"Conditionally approved per MUA {mua['mua_number']}",
                        caveats=mitigations if isinstance(mitigations, list) else [],
                        evidence_sources=[mua['mua_number']],
                        confidence=0.70
                    )

        # Priority 2: Check test evidence
        if test_evidence:
            # Count high-authority evidence
            tier_1_evidence = [e for e in test_evidence if e.get('authority_tier') == 1]

            if len(tier_1_evidence) >= 2:
                # Sufficient NASA test data
                sources = [e['source'] for e in tier_1_evidence[:3]]
                return MaterialDecision(
                    material_name=material_name,
                    decision='YES',
                    rationale=f"Meets requirements based on {len(tier_1_evidence)} NASA test reports",
                    evidence_sources=sources,
                    confidence=0.80
                )
            elif test_evidence:
                # Some evidence but not sufficient
                sources = [e['source'] for e in test_evidence[:3]]
                return MaterialDecision(
                    material_name=material_name,
                    decision='YES_WITH_CAVEATS',
                    rationale=f"Limited evidence from {len(test_evidence)} test reports - additional testing recommended",
                    evidence_sources=sources,
                    caveats=["Additional testing recommended for margin verification"],
                    confidence=0.60
                )

        # Priority 3: No evidence found
        return MaterialDecision(
            material_name=material_name,
            decision='REQUIRES_TESTING',
            rationale='Insufficient evidence - testing required per NASA-STD-6001B',
            evidence_sources=[],
            confidence=0.0
        )
