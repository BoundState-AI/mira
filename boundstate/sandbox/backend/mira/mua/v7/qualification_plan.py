"""Qualification Plan Mode for novel materials.

When a material has zero precedents and no current MAPTIS test data,
generating an MUA is not meaningful.  Instead, generate a test plan
recommendation that tells the engineer what tests are needed.

Output: "Usage Agreement Pending Test" -- actionable, not a dead end.

Background
----------
NASA-STD-6001 defines test methods for flammability, offgassing, and
fluid compatibility.  NASA-STD-6016 (formerly NHB 8060.1C) governs
the Material Usage Agreement process itself.  When no existing data
covers the proposed use-case, the engineer needs a concrete list of
which tests to run, under what conditions, and per which standards.

This module encodes the knowledge of which tests are required for
each environment class and renders a human-readable plan.

Test numbering follows NASA-STD-6001 (Rev. B or later):
    Test  1  -- Upward Flame Propagation
    Test  2  -- Heat and Visible Smoke Release Rates
    Test  3  -- (Reserved)
    Test  4  -- Electrical Wire Insulation Flammability
    Test  5  -- (Reserved)
    Test  6  -- (Reserved)
    Test  7  -- Determination of Offgassed Products
    Test  8  -- Flammability, Odor, and Offgassing Assessment (screening)
    Test 11  -- Wire Bundle Flammability (reserved / center-specific)
    Test 12  -- Promoted Combustion of Metallic Materials (LOX/GOX)
    Test 13  -- Mechanical Impact for Metallic Materials in LOX/GOX
    Test 14  -- Pneumatic Impact for Non-metallic Materials in GOX
    Test 15  -- Auto-ignition Temperature
    Test 17  -- Upward Flammability of Materials in Pressurized Oxygen
    Test 19  -- Heat of Combustion

ASTM standards commonly referenced:
    ASTM G63   -- Standard Guide for Evaluating Nonmetallic Materials
                   for Oxygen Service
    ASTM G88   -- Standard Guide for Designing Systems for Oxygen Service
    ASTM G94   -- Standard Guide for Evaluating Metals for Oxygen Service
    ASTM G124  -- Standard Test Method for Determining the Combustion
                   Behavior of Metallic Materials in Oxygen-Enriched
                   Atmospheres (promoted ignition)
    ASTM G136  -- Standard Practice for Determination of Metals
                   Susceptibility to Embrittlement in Hydrogen
    ASTM E595  -- Standard Test Method for Total Mass Loss and Collected
                   Volatile Condensable Materials from Outgassing in a
                   Vacuum Environment
    ASTM G142  -- Standard Test Method for Determination of Susceptibility
                   of Metals to Embrittlement in Hydrogen Containing
                   Environments at High Pressure, High Temperature, or Both
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .models import EnvironmentSpec, MaterialResolution, QualificationPlanResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test catalog -- canonical knowledge base
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TestRequirement:
    """A single required or recommended test."""

    name: str
    standard: str
    test_number: Optional[str]  # e.g. "Test 1", "ASTM G124", None
    description: str
    rationale: str
    is_mandatory: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "standard": self.standard,
            "test_number": self.test_number,
            "description": self.description,
            "rationale": self.rationale,
            "is_mandatory": self.is_mandatory,
        }


@dataclass(frozen=True)
class TestCondition:
    """A condition under which testing should be performed."""

    parameter: str
    value: str
    unit: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "parameter": self.parameter,
            "value": self.value,
            "unit": self.unit,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Pre-defined test requirements by environment class
# ---------------------------------------------------------------------------

# Habitable atmosphere -- crew compartments, pressurized modules.
_HABITABLE_TESTS: list[TestRequirement] = [
    TestRequirement(
        name="Upward Flame Propagation",
        standard="NASA-STD-6001",
        test_number="Test 1",
        description=(
            "Determine if a material, in the intended use configuration, "
            "will self-extinguish after ignition by a standard ignition "
            "source in the specified atmosphere."
        ),
        rationale=(
            "Primary flammability screening for all materials used inside "
            "habitable volumes.  Required per NASA-STD-6016C Section 4.2."
        ),
    ),
    TestRequirement(
        name="Offgassing Products Determination",
        standard="NASA-STD-6001",
        test_number="Test 7",
        description=(
            "Identify and quantify volatile organic compounds (VOCs) and "
            "other offgassed products from the material at the intended "
            "use temperature."
        ),
        rationale=(
            "Required for all non-metallic materials in habitable volumes "
            "to ensure crew air quality.  Compounds compared against "
            "spacecraft maximum allowable concentrations (SMACs)."
        ),
    ),
    TestRequirement(
        name="Toxicity Assessment",
        standard="NASA-STD-6001 / NHB 8060.1",
        test_number="Test 7 (toxicological evaluation)",
        description=(
            "Toxicological evaluation of offgassing products by JSC "
            "Toxicology Group.  Determines if offgassed products are "
            "within acceptable limits for crew exposure duration."
        ),
        rationale=(
            "Mandatory companion to Test 7 for habitable volumes.  "
            "The Toxicology Group must sign off on offgas results before "
            "a material can receive a flammability / toxicity rating."
        ),
    ),
    TestRequirement(
        name="Heat and Visible Smoke Release Rates",
        standard="NASA-STD-6001",
        test_number="Test 2",
        description=(
            "Measure heat release rate and smoke generation rate using "
            "cone calorimetry per NASA-STD-6001."
        ),
        rationale=(
            "Required when the material is used in quantities exceeding "
            "the exempt amount or in configurations where smoke generation "
            "could impact crew egress."
        ),
        is_mandatory=False,
    ),
    TestRequirement(
        name="Total Mass Loss (TML) / Outgassing Screening",
        standard="ASTM E595",
        test_number="ASTM E595",
        description=(
            "Determine total mass loss (TML) and collected volatile "
            "condensable materials (CVCM) under vacuum conditions at "
            "125 degC for 24 hours."
        ),
        rationale=(
            "Required for materials near optical surfaces, sensors, or "
            "in configurations where condensable volatiles could degrade "
            "neighboring components.  Often used as an early screening "
            "test in conjunction with Test 7."
        ),
        is_mandatory=False,
    ),
]

# Oxygen-enriched or oxygen service environments.
_O2_SERVICE_TESTS: list[TestRequirement] = [
    TestRequirement(
        name="Upward Flammability in Pressurized Oxygen",
        standard="NASA-STD-6001",
        test_number="Test 17",
        description=(
            "Determine flammability of non-metallic materials in oxygen-enriched "
            "atmospheres at elevated pressures using upward flame propagation."
        ),
        rationale=(
            "Primary flammability test for non-metallic materials in O2 service.  "
            "Must be performed at worst-case use pressure and O2 concentration "
            "per NASA-STD-6016C Section 4.3."
        ),
    ),
    TestRequirement(
        name="Promoted Combustion (Metallic Materials)",
        standard="NASA-STD-6001 / ASTM G124",
        test_number="Test 12",
        description=(
            "Determine if a metallic material will sustain combustion in "
            "oxygen when ignited by a standard promoter at the intended "
            "use pressure."
        ),
        rationale=(
            "Required for metallic materials in LOX/GOX systems.  Metals "
            "that would not normally burn in air can sustain combustion "
            "in enriched oxygen.  Per ASTM G94 and NASA-STD-6016C."
        ),
    ),
    TestRequirement(
        name="Mechanical Impact (LOX/GOX Metals)",
        standard="NASA-STD-6001",
        test_number="Test 13",
        description=(
            "Evaluate susceptibility of metallic materials to ignition "
            "by mechanical impact in liquid or gaseous oxygen."
        ),
        rationale=(
            "LOX/GOX systems may experience mechanical impact during "
            "operation or maintenance.  This test determines if the "
            "material is susceptible to impact-induced ignition."
        ),
    ),
    TestRequirement(
        name="Pneumatic Impact (Non-metallic, GOX)",
        standard="NASA-STD-6001",
        test_number="Test 14",
        description=(
            "Evaluate susceptibility of non-metallic materials to "
            "ignition by rapid pressurization (adiabatic compression) "
            "in gaseous oxygen."
        ),
        rationale=(
            "Non-metallic seals, seats, and lubricants in GOX systems "
            "can be ignited by rapid pressurization.  Required for all "
            "non-metals in GOX flow paths."
        ),
    ),
    TestRequirement(
        name="Auto-ignition Temperature",
        standard="NASA-STD-6001",
        test_number="Test 15",
        description=(
            "Determine the lowest temperature at which a material will "
            "spontaneously ignite in the specified oxygen atmosphere "
            "without an external ignition source."
        ),
        rationale=(
            "Ensures the material's auto-ignition temperature exceeds "
            "the maximum expected service temperature with adequate margin."
        ),
    ),
    TestRequirement(
        name="Oxygen Compatibility Assessment (Non-metallic)",
        standard="ASTM G63",
        test_number="ASTM G63",
        description=(
            "Systematic evaluation of non-metallic materials for oxygen "
            "service, including review of ignition mechanisms (particle "
            "impact, friction, static discharge, etc.)."
        ),
        rationale=(
            "Comprehensive screening methodology required by NASA-STD-6016C "
            "for non-metallic materials in O2-enriched environments."
        ),
    ),
    TestRequirement(
        name="Oxygen Compatibility Assessment (Metallic)",
        standard="ASTM G94",
        test_number="ASTM G94",
        description=(
            "Systematic evaluation of metallic materials for oxygen "
            "service, including promoted ignition, auto-ignition, "
            "and reaction severity analysis."
        ),
        rationale=(
            "Required companion to promoted combustion testing.  Provides "
            "the framework for selecting acceptable metals for O2 systems."
        ),
    ),
]

# Hydrogen service environments (GH2, LH2).
_H2_SERVICE_TESTS: list[TestRequirement] = [
    TestRequirement(
        name="Hydrogen Embrittlement Evaluation",
        standard="ASTM G142 / ASTM G136",
        test_number="ASTM G142",
        description=(
            "Determine susceptibility of metallic materials to hydrogen "
            "embrittlement (HEE) by measuring tensile properties in "
            "high-pressure hydrogen vs. inert reference gas."
        ),
        rationale=(
            "Metallic materials in GH2/LH2 service may suffer loss of "
            "ductility and premature fracture due to hydrogen ingress.  "
            "High-strength steels, titanium alloys, and nickel superalloys "
            "are particularly susceptible."
        ),
    ),
    TestRequirement(
        name="Stress Corrosion Cracking (SCC) Susceptibility",
        standard="NASA-MSFC-SPEC-522 / ASTM G49",
        test_number="MSFC-SPEC-522",
        description=(
            "Evaluate sustained-load cracking susceptibility in the "
            "intended hydrogen environment.  Applicable to materials "
            "under sustained tensile stress."
        ),
        rationale=(
            "Hydrogen can accelerate stress corrosion cracking in "
            "susceptible alloys.  Required for structural applications "
            "in propellant systems."
        ),
        is_mandatory=False,
    ),
    TestRequirement(
        name="Hydrogen Compatibility Assessment",
        standard="NASA-TM-1997-207964 / Center-specific",
        test_number=None,
        description=(
            "Comprehensive review of material's hydrogen compatibility "
            "including permeation rates, embrittlement indices, and "
            "historical service data."
        ),
        rationale=(
            "Umbrella assessment that may invoke additional tests "
            "depending on service conditions (temperature, pressure, "
            "exposure duration)."
        ),
    ),
]

# External environments (space-facing, EVA, unpressurized).
_EXTERNAL_TESTS: list[TestRequirement] = [
    TestRequirement(
        name="UV Degradation Resistance",
        standard="ASTM G154 / ASTM G90",
        test_number="ASTM G154",
        description=(
            "Evaluate material degradation under simulated solar UV "
            "exposure using fluorescent UV lamps or concentrated "
            "natural sunlight."
        ),
        rationale=(
            "External surfaces receive unfiltered solar UV radiation.  "
            "Polymeric and organic materials are particularly susceptible "
            "to UV-induced chain scission and embrittlement."
        ),
    ),
    TestRequirement(
        name="Atomic Oxygen Erosion",
        standard="ASTM E2089",
        test_number="ASTM E2089",
        description=(
            "Measure erosion yield of materials exposed to atomic "
            "oxygen flux representative of low Earth orbit (LEO) "
            "conditions."
        ),
        rationale=(
            "Atomic oxygen in LEO aggressively erodes many polymers, "
            "composites, and thin-film coatings.  Erosion rates must be "
            "known to predict service life."
        ),
    ),
    TestRequirement(
        name="Thermal Cycling Resistance",
        standard="Center-specific / ASTM E2218",
        test_number="ASTM E2218",
        description=(
            "Subject material to repeated thermal cycles spanning the "
            "expected on-orbit temperature range (shadow to direct sun) "
            "and evaluate for cracking, delamination, or property loss."
        ),
        rationale=(
            "External surfaces experience extreme thermal cycling "
            "(approximately -250 degF to +250 degF in LEO).  Repeated "
            "cycling can cause fatigue, delamination, and seal failure."
        ),
    ),
    TestRequirement(
        name="Outgassing (Vacuum Stability)",
        standard="ASTM E595",
        test_number="ASTM E595",
        description=(
            "Determine total mass loss and collected volatile condensable "
            "materials under vacuum to verify the material will not "
            "contaminate optical surfaces or neighboring hardware."
        ),
        rationale=(
            "In vacuum, materials offgas volatile constituents that can "
            "condense on cold optical surfaces, solar cells, or thermal "
            "control coatings, degrading performance."
        ),
    ),
]

# Cryogenic environments (temp_min <= -150 degF).
_CRYOGENIC_TESTS: list[TestRequirement] = [
    TestRequirement(
        name="Low-Temperature Mechanical Properties",
        standard="ASTM E1450 / ASTM E8 (at cryogenic temp)",
        test_number="ASTM E1450",
        description=(
            "Tensile, fracture toughness, and Charpy impact testing at "
            "the minimum service temperature to verify adequate ductility "
            "and strength retention."
        ),
        rationale=(
            "Many materials experience a ductile-to-brittle transition "
            "at cryogenic temperatures.  Mechanical properties must be "
            "verified at worst-case temperature."
        ),
    ),
    TestRequirement(
        name="Thermal Contraction Compatibility",
        standard="ASTM E228 / ASTM E831",
        test_number="ASTM E228",
        description=(
            "Measure the coefficient of thermal expansion (CTE) from "
            "ambient to the minimum service temperature to verify "
            "compatibility with mating components."
        ),
        rationale=(
            "Differential thermal contraction between dissimilar "
            "materials can cause seal failures, joint loosening, or "
            "stress concentrations at cryogenic temperatures."
        ),
    ),
    TestRequirement(
        name="Cryogenic Seal/Joint Leakage",
        standard="Center-specific",
        test_number=None,
        description=(
            "Leak testing of seals, joints, and interfaces at cryogenic "
            "temperature and pressure to verify containment integrity."
        ),
        rationale=(
            "Seals that perform adequately at ambient temperature may "
            "leak at cryogenic temperatures due to CTE mismatch, "
            "hardening, or loss of resilience."
        ),
        is_mandatory=False,
    ),
]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class QualificationPlanGenerator:
    """Generate a test qualification plan for novel materials.

    When MIRA finds zero precedents AND no current MAPTIS test data
    for a material/environment combination, this generator produces a
    structured plan of required tests, conditions, and applicable
    standards.

    The output is a ``QualificationPlanResponse`` (defined in models.py)
    containing both structured data and a rendered text document.
    """

    def generate(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
    ) -> QualificationPlanResponse:
        """Generate a qualification test plan.

        Parameters
        ----------
        material:
            The resolved (or unresolved) material identity.
        environment:
            The target use environment.

        Returns
        -------
        QualificationPlanResponse
            Structured plan with required tests, conditions, standards,
            and rendered output text.
        """
        required_tests = self._determine_required_tests(environment, material)
        conditions = self._determine_conditions(environment)
        standards = self._collect_applicable_standards(required_tests)
        output_text = self._render_plan_text(
            material, environment, required_tests, conditions, standards,
        )

        logger.info(
            "Generated qualification plan for material=%r env_location=%s: "
            "%d required tests, %d conditions",
            material.resolved_name or material.input_text,
            environment.location,
            len(required_tests),
            len(conditions),
        )

        return QualificationPlanResponse(
            material=material.resolved_name or material.input_text,
            required_tests=[t.to_dict() for t in required_tests],
            recommended_conditions=[c.to_dict() for c in conditions],
            applicable_standards=standards,
            output_text=output_text,
        )

    # -- Internal: test determination ---------------------------------------

    def _determine_required_tests(
        self,
        environment: EnvironmentSpec,
        material: MaterialResolution,
    ) -> list[TestRequirement]:
        """Determine which tests are required based on environment and material.

        The logic layers requirements by environment class.  A single
        material/environment combination may trigger tests from multiple
        categories (e.g., a polymer in a cryogenic LOX feed line needs
        O2 tests AND cryogenic tests AND habitable tests if the line
        passes through a habitable volume).

        Parameters
        ----------
        environment:
            Target use environment.
        material:
            Resolved material information.

        Returns
        -------
        list[TestRequirement]
            De-duplicated, ordered list of required tests.
        """
        tests: list[TestRequirement] = []
        seen_names: set[str] = set()

        def _add(test_list: list[TestRequirement]) -> None:
            for t in test_list:
                if t.name not in seen_names:
                    tests.append(t)
                    seen_names.add(t.name)

        # Habitable volume -- always requires flammability and offgassing.
        if environment.location == "habitable":
            _add(_HABITABLE_TESTS)

        # Enriched oxygen or oxygen medium.
        if environment.is_enriched_o2 or environment.medium.upper() in (
            "GOX", "LOX", "O2",
        ):
            _add(_O2_SERVICE_TESTS)

        # Hydrogen service.
        if environment.is_hydrogen_service:
            _add(_H2_SERVICE_TESTS)

        # External (space-facing, EVA, unpressurized).
        if environment.location == "external":
            _add(_EXTERNAL_TESTS)

        # Cryogenic temperatures.
        if environment.is_cryogenic:
            _add(_CRYOGENIC_TESTS)

        # Process-sensitive materials always need outgassing at a minimum.
        if material.is_process_sensitive:
            outgas = TestRequirement(
                name="Process-Cure Verification (Outgassing)",
                standard="ASTM E595",
                test_number="ASTM E595",
                description=(
                    "Verify that the cured material meets outgassing "
                    "requirements under the specified cure schedule.  "
                    "Variations in cure temperature, time, or mix ratio "
                    "can significantly affect offgassing performance."
                ),
                rationale=(
                    "Process-sensitive materials (adhesives, potting "
                    "compounds, sealants, composites) have properties "
                    "that depend heavily on processing parameters.  "
                    "Test data from a different cure schedule may not "
                    "be applicable."
                ),
            )
            _add([outgas])

        # Non-habitable pressurized volume -- still needs flammability
        # but may skip full toxicity.
        if environment.location == "non_habitable" and not tests:
            _add([
                TestRequirement(
                    name="Upward Flame Propagation",
                    standard="NASA-STD-6001",
                    test_number="Test 1",
                    description=(
                        "Determine if the material will self-extinguish "
                        "after ignition in the specified atmosphere."
                    ),
                    rationale=(
                        "Even non-habitable pressurized volumes require "
                        "flammability screening to prevent fire propagation "
                        "to adjacent compartments."
                    ),
                ),
            ])

        # Fallback: if no environment matched, require at minimum Test 1.
        if not tests:
            _add([
                TestRequirement(
                    name="Upward Flame Propagation (Baseline)",
                    standard="NASA-STD-6001",
                    test_number="Test 1",
                    description=(
                        "Baseline flammability assessment in worst-case "
                        "use atmosphere."
                    ),
                    rationale=(
                        "All materials used in NASA applications require "
                        "at minimum a flammability assessment."
                    ),
                ),
            ])

        return tests

    # -- Internal: conditions -----------------------------------------------

    def _determine_conditions(
        self,
        environment: EnvironmentSpec,
    ) -> list[TestCondition]:
        """Determine test conditions derived from the environment spec.

        NASA-STD-6001 requires testing at worst-case use conditions.
        These conditions are passed to the testing lab so they can
        configure the test apparatus appropriately.

        Parameters
        ----------
        environment:
            Target use environment.

        Returns
        -------
        list[TestCondition]
            Conditions under which testing should be performed.
        """
        conditions: list[TestCondition] = []

        # Oxygen concentration.
        conditions.append(TestCondition(
            parameter="Oxygen concentration",
            value=str(environment.o2_percent),
            unit="% by volume",
            rationale=(
                "Test at worst-case O2 concentration.  Higher O2 increases "
                "flammability.  Per NASA-STD-6001, test at the maximum "
                "expected O2 concentration."
            ),
        ))

        # Pressure.
        conditions.append(TestCondition(
            parameter="Total pressure",
            value=str(environment.pressure_psia),
            unit="psia",
            rationale=(
                "Test at worst-case pressure for the intended application.  "
                "Higher pressure generally increases flammability severity "
                "in oxygen-enriched atmospheres."
            ),
        ))

        # Temperature range.
        conditions.append(TestCondition(
            parameter="Temperature range",
            value=f"{environment.temp_min_f} to {environment.temp_max_f}",
            unit="degF",
            rationale=(
                "Mechanical and flammability properties are temperature-"
                "dependent.  Test at both extremes of the expected range."
            ),
        ))

        # Medium.
        conditions.append(TestCondition(
            parameter="Service medium",
            value=environment.medium,
            unit="",
            rationale=(
                f"Material will be exposed to {environment.medium}.  "
                f"Testing must be performed in or simulating this medium."
            ),
        ))

        # Location-specific conditions.
        if environment.location == "external":
            conditions.append(TestCondition(
                parameter="Vacuum exposure",
                value="<1e-5",
                unit="torr",
                rationale=(
                    "External surfaces are exposed to hard vacuum.  "
                    "Outgassing and material stability tests must be "
                    "performed under representative vacuum conditions."
                ),
            ))

        if environment.is_cryogenic:
            conditions.append(TestCondition(
                parameter="Cryogenic soak",
                value=str(environment.temp_min_f),
                unit="degF",
                rationale=(
                    "Material must be thermally soaked at minimum "
                    "service temperature before mechanical testing to "
                    "ensure equilibrium."
                ),
            ))

        return conditions

    # -- Internal: standard collection --------------------------------------

    def _collect_applicable_standards(
        self,
        tests: list[TestRequirement],
    ) -> list[str]:
        """Extract de-duplicated list of referenced standards.

        Parameters
        ----------
        tests:
            List of required tests.

        Returns
        -------
        list[str]
            Sorted, de-duplicated standard identifiers.
        """
        standards: set[str] = set()
        # Always include the governing standards.
        standards.add("NASA-STD-6001B")
        standards.add("NASA-STD-6016C")

        for test in tests:
            # A test may reference multiple standards separated by " / ".
            for part in test.standard.split(" / "):
                standards.add(part.strip())

        return sorted(standards)

    # -- Internal: rendering ------------------------------------------------

    def _render_plan_text(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
        required_tests: list[TestRequirement],
        conditions: list[TestCondition],
        standards: list[str],
    ) -> str:
        """Render the qualification plan as formatted text.

        Parameters
        ----------
        material:
            Material identity.
        environment:
            Target environment.
        required_tests:
            Tests determined to be required.
        conditions:
            Conditions under which tests should be performed.
        standards:
            Applicable standard identifiers.

        Returns
        -------
        str
            Human-readable qualification plan document.
        """
        mat_name = material.resolved_name or material.input_text
        mat_class = (
            material.material_class.value if material.material_class else "Unknown"
        )
        lines: list[str] = []

        # Header.
        lines.append("=" * 72)
        lines.append("USAGE AGREEMENT PENDING TEST")
        lines.append("Qualification Test Plan Recommendation")
        lines.append("=" * 72)
        lines.append("")
        lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"Status:    PENDING TEST -- This is NOT an approved MUA.")
        lines.append("")

        # Material identification.
        lines.append("-" * 72)
        lines.append("1. MATERIAL IDENTIFICATION")
        lines.append("-" * 72)
        lines.append(f"  Material:       {mat_name}")
        if material.material_code:
            lines.append(f"  MAPTIS Code:    {material.material_code}")
        lines.append(f"  Class:          {mat_class}")
        if material.family:
            lines.append(f"  Family:         {material.family}")
        if material.is_process_sensitive:
            lines.append(f"  Process-Sensitive: YES -- cure/process parameters affect properties.")
        lines.append("")

        # Environment.
        lines.append("-" * 72)
        lines.append("2. INTENDED USE ENVIRONMENT")
        lines.append("-" * 72)
        lines.append(f"  Location:       {environment.location}")
        lines.append(f"  Medium:         {environment.medium}")
        lines.append(f"  O2 Conc:        {environment.o2_percent}%")
        lines.append(f"  Pressure:       {environment.pressure_psia} psia")
        lines.append(f"  Temp Range:     {environment.temp_min_f} to {environment.temp_max_f} degF")
        lines.append(f"  Application:    {environment.application}")

        flags: list[str] = []
        if environment.is_enriched_o2:
            flags.append("ENRICHED OXYGEN")
        if environment.is_cryogenic:
            flags.append("CRYOGENIC")
        if environment.is_hydrogen_service:
            flags.append("HYDROGEN SERVICE")
        if flags:
            lines.append(f"  Flags:          {', '.join(flags)}")
        lines.append("")

        # Required tests.
        lines.append("-" * 72)
        lines.append("3. REQUIRED TESTS")
        lines.append("-" * 72)
        mandatory = [t for t in required_tests if t.is_mandatory]
        recommended = [t for t in required_tests if not t.is_mandatory]

        if mandatory:
            lines.append("")
            lines.append("  3a. MANDATORY TESTS")
            lines.append("")
            for i, test in enumerate(mandatory, 1):
                test_ref = f" ({test.test_number})" if test.test_number else ""
                lines.append(f"  {i}. {test.name}{test_ref}")
                lines.append(f"     Standard:   {test.standard}")
                lines.append(f"     Description: {test.description}")
                lines.append(f"     Rationale:  {test.rationale}")
                lines.append("")

        if recommended:
            lines.append("  3b. RECOMMENDED (CONDITIONAL) TESTS")
            lines.append("")
            for i, test in enumerate(recommended, 1):
                test_ref = f" ({test.test_number})" if test.test_number else ""
                lines.append(f"  {i}. {test.name}{test_ref}")
                lines.append(f"     Standard:   {test.standard}")
                lines.append(f"     Description: {test.description}")
                lines.append(f"     Rationale:  {test.rationale}")
                lines.append("")

        # Test conditions.
        lines.append("-" * 72)
        lines.append("4. TEST CONDITIONS")
        lines.append("-" * 72)
        lines.append("")
        lines.append("  Testing must be performed at the following conditions:")
        lines.append("")
        for cond in conditions:
            unit_str = f" {cond.unit}" if cond.unit else ""
            lines.append(f"  - {cond.parameter}: {cond.value}{unit_str}")
            lines.append(f"    ({cond.rationale})")
            lines.append("")

        # Applicable standards.
        lines.append("-" * 72)
        lines.append("5. APPLICABLE STANDARDS")
        lines.append("-" * 72)
        lines.append("")
        for std in standards:
            lines.append(f"  - {std}")
        lines.append("")

        # Notes and caveats.
        lines.append("-" * 72)
        lines.append("6. NOTES")
        lines.append("-" * 72)
        lines.append("")
        lines.append(
            "  a. This plan is a RECOMMENDATION generated by MIRA based on the "
            "specified material and environment.  It does not replace engineering "
            "judgment or center-specific requirements."
        )
        lines.append("")
        lines.append(
            "  b. The reviewing engineer and responsible NASA center MIUL "
            "authority must approve the final test matrix before testing begins."
        )
        lines.append("")
        lines.append(
            "  c. Test results must be entered into MAPTIS before an MUA "
            "can be generated for this material/environment combination."
        )
        lines.append("")
        lines.append(
            "  d. Additional tests beyond those listed may be required based on "
            "the specific hardware application, program requirements, or "
            "center-specific policies."
        )
        lines.append("")
        lines.append("=" * 72)
        lines.append("END OF QUALIFICATION PLAN")
        lines.append("=" * 72)

        return "\n".join(lines)
