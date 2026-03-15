#!/usr/bin/env python3
"""Tests for TOCR three-pass pipeline engine."""

import pytest

from sentinel.tocr.engine.diff_engine import DiffEngine
from sentinel.tocr.engine.disclosure_engine import DisclosureEngine
from sentinel.tocr.engine.rule_engine import RuleEngine
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import (
    BasisType,
    ChangeClassification,
    ChangeType,
    ComplianceSeverity,
    ConfidenceLevel,
    ContractType,
    ReviewPriority,
    RevisionStatus,
)
from sentinel.tocr.models.diff import FieldChange, StructuralDiff
from sentinel.tocr.models.report import DisclosureResult
from sentinel.tocr.models.rules import RuleApplicability, RuleTrigger, TOCRRule
from sentinel.tocr.models.task_order import (
    FundingEntry,
    QualityPlan,
    SubTask,
    TaskOrder,
)


def _make_prior() -> TaskOrder:
    """Create a baseline task order for testing."""
    return TaskOrder(
        task_order_number="TO-1234",
        revision_number="Rev 34",
        revision_status=RevisionStatus.RELEASED,
        title="MAPTIS-II Support",
        task_order_description="MAPTIS-II Development Support, TIMs, MUAs",
        scope_text="MAPTIS-II Development Support, TIMs, MUAs",
        summary_of_changes="Initial release.",
        sub_tasks=[
            SubTask(
                sub_task_id="ST-001",
                description="MAPTIS database maintenance",
                skills=["database admin", "SQL"],
                deliverables=["Monthly status report"],
                funding=100000.0,
                wbs_code="WBS-001",
                charge_code="CC-001",
                participating_team=["Amentum"],
            ),
        ],
        funding_table=[
            FundingEntry(sub_task_id="ST-001", amount=100000.0, wbs_code="WBS-001"),
        ],
        total_funding=100000.0,
        quality_plan=QualityPlan(text="Standard QMS procedures apply."),
    )


def _make_proposed_with_undisclosed_scope() -> TaskOrder:
    """Create a proposed revision with undisclosed scope expansion."""
    return TaskOrder(
        task_order_number="TO-1234",
        revision_number="Rev 35",
        revision_status=RevisionStatus.DRAFT,
        title="MAPTIS-II Support",
        task_order_description=(
            "MAPTIS-II Development Support including development of Software Tools "
            "for integration of AI solutions, TIMs, MUAs"
        ),
        scope_text=(
            "MAPTIS-II Development Support including development of Software Tools "
            "for integration of AI solutions, TIMs, MUAs"
        ),
        summary_of_changes="Updated revision number.",
        sub_tasks=[
            SubTask(
                sub_task_id="ST-001",
                description="MAPTIS database maintenance",
                skills=["database admin", "SQL"],
                deliverables=["Monthly status report"],
                funding=100000.0,
                wbs_code="WBS-001",
                charge_code="CC-001",
                participating_team=["Amentum"],
            ),
        ],
        funding_table=[
            FundingEntry(sub_task_id="ST-001", amount=100000.0, wbs_code="WBS-001"),
        ],
        total_funding=100000.0,
        quality_plan=QualityPlan(text="Standard QMS procedures apply."),
    )


def _make_proposed_clean() -> TaskOrder:
    """Create a proposed revision that is properly disclosed."""
    return TaskOrder(
        task_order_number="TO-1234",
        revision_number="Rev 35",
        revision_status=RevisionStatus.RELEASED,
        title="MAPTIS-II Support",
        task_order_description=(
            "MAPTIS-II Development Support including development of Software Tools "
            "for integration of AI solutions, TIMs, MUAs"
        ),
        scope_text=(
            "MAPTIS-II Development Support including development of Software Tools "
            "for integration of AI solutions, TIMs, MUAs"
        ),
        summary_of_changes=(
            "Added Software Tools scope for AI integration under ST-001. "
            "Added software development skills. Updated funding to include AI tools development."
        ),
        sub_tasks=[
            SubTask(
                sub_task_id="ST-001",
                description="MAPTIS database maintenance and AI tools development",
                skills=["database admin", "SQL", "software engineering", "AI"],
                deliverables=["Monthly status report", "AI tools prototype"],
                funding=200000.0,
                wbs_code="WBS-001",
                charge_code="CC-001",
                participating_team=["Amentum"],
            ),
        ],
        funding_table=[
            FundingEntry(sub_task_id="ST-001", amount=200000.0, wbs_code="WBS-001"),
        ],
        total_funding=200000.0,
        quality_plan=QualityPlan(
            text="Standard QMS procedures apply. Software QMS per NASA-STD-8739.8B.",
            qms_required=True,
            software_scope=True,
        ),
    )


class TestDiffEngine:
    def test_no_changes(self):
        prior = _make_prior()
        engine = DiffEngine()
        diff = engine.run(prior, prior)
        assert diff.total_changes == 0
        assert diff.material_changes == 0

    def test_scope_change_detected(self):
        prior = _make_prior()
        proposed = _make_proposed_with_undisclosed_scope()
        engine = DiffEngine()
        diff = engine.run(prior, proposed)

        assert diff.total_changes > 0
        assert diff.material_changes > 0

        scope_changes = diff.get_scope_changes()
        assert len(scope_changes) > 0

    def test_new_sub_task_detected(self):
        prior = _make_prior()
        proposed = _make_prior()
        proposed.revision_number = "Rev 35"
        proposed.sub_tasks.append(
            SubTask(sub_task_id="ST-002", description="New AI development task")
        )
        engine = DiffEngine()
        diff = engine.run(prior, proposed)

        assert "ST-002" in diff.new_sub_tasks
        assert diff.material_changes > 0

    def test_removed_sub_task_detected(self):
        prior = _make_prior()
        proposed = TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 35",
            title="MAPTIS-II Support",
            task_order_description="MAPTIS-II Development Support",
            sub_tasks=[],
        )
        engine = DiffEngine()
        diff = engine.run(prior, proposed)

        assert "ST-001" in diff.removed_sub_tasks

    def test_funding_change_detected(self):
        prior = _make_prior()
        proposed = _make_prior()
        proposed.revision_number = "Rev 35"
        proposed.total_funding = 200000.0
        engine = DiffEngine()
        diff = engine.run(prior, proposed)

        funding_changes = diff.get_changes_by_classification(ChangeClassification.FUNDING)
        assert len(funding_changes) > 0

    def test_formatting_only_filtered(self):
        prior = _make_prior()
        proposed = _make_prior()
        proposed.revision_number = "Rev 35"
        proposed.task_order_description = "MAPTIS-II  Development  Support,  TIMs,  MUAs"
        engine = DiffEngine()
        diff = engine.run(prior, proposed)

        # The extra spaces should be detected as formatting only
        formatting = [c for c in diff.field_changes if c.is_formatting_only]
        assert len(formatting) > 0, "Extra-whitespace changes must be classified as formatting-only"
        # None of these should be marked as material
        assert all(not c.is_material for c in formatting)


class TestDisclosureEngine:
    def test_undisclosed_change(self):
        prior = _make_prior()
        proposed = _make_proposed_with_undisclosed_scope()
        diff_engine = DiffEngine()
        diff = diff_engine.run(prior, proposed)

        engine = DisclosureEngine()
        results = engine.run(diff, proposed.summary_of_changes)

        undisclosed = [r for r in results if not r.disclosed]
        assert len(undisclosed) > 0

    def test_disclosed_change(self):
        prior = _make_prior()
        proposed = _make_proposed_clean()
        diff_engine = DiffEngine()
        diff = diff_engine.run(prior, proposed)

        engine = DisclosureEngine()
        results = engine.run(diff, proposed.summary_of_changes)

        disclosed = [r for r in results if r.disclosed]
        assert len(disclosed) > 0

    def test_empty_summary(self):
        prior = _make_prior()
        proposed = _make_proposed_with_undisclosed_scope()
        proposed.summary_of_changes = ""
        diff_engine = DiffEngine()
        diff = diff_engine.run(prior, proposed)

        engine = DisclosureEngine()
        results = engine.run(diff, proposed.summary_of_changes)

        # All should be undisclosed
        assert all(not r.disclosed for r in results)


class TestRuleEngine:
    def _get_test_rules(self) -> list[TOCRRule]:
        """Get minimal test rules."""
        return [
            TOCRRule(
                rule_id="TOCR-001",
                title="Undisclosed Material Change",
                basis_type=BasisType.INTERNAL_CONTROL,
                authority_basis=["FAR 1.602-1"],
                applicability=RuleApplicability(
                    contract_type=["IDIQ", "Task Order"],
                    agency=["NASA"],
                    revision_status=["draft", "released"],
                ),
                trigger=RuleTrigger(all=["material_change_detected", "not_listed_in_summary_of_changes"]),
                finding="Material change not disclosed.",
                severity=ComplianceSeverity.CRITICAL,
                review_priority=ReviewPriority.CO,
            ),
            TOCRRule(
                rule_id="TOCR-009",
                title="Unenforceable Draft Language",
                basis_type=BasisType.REGULATORY,
                authority_basis=["FAR 43.301"],
                applicability=RuleApplicability(
                    contract_type=["IDIQ", "Task Order"],
                    revision_status=["draft"],
                ),
                trigger=RuleTrigger(all=["scope_addition_detected", "revision_is_draft"]),
                finding="Scope in draft has no contractual force.",
                severity=ComplianceSeverity.MEDIUM,
                review_priority=ReviewPriority.ADVISORY,
            ),
        ]

    def test_undisclosed_change_fires_tocr001(self):
        prior = _make_prior()
        proposed = _make_proposed_with_undisclosed_scope()
        config = ContractConfig(
            contract_type=[ContractType.IDIQ, ContractType.TASK_ORDER],
            agency="NASA",
            revision_status=RevisionStatus.DRAFT,
        )

        diff = DiffEngine().run(prior, proposed)
        disclosures = DisclosureEngine().run(diff, proposed.summary_of_changes)

        engine = RuleEngine(rules=self._get_test_rules())
        findings = engine.run(diff, disclosures, proposed, config)

        tocr001_findings = [f for f in findings if f.rule_id == "TOCR-001"]
        assert len(tocr001_findings) > 0
        assert tocr001_findings[0].severity == ComplianceSeverity.CRITICAL

    def test_applicability_filters_by_agency(self):
        nasa_rule = TOCRRule(
            rule_id="TEST-NASA",
            title="NASA Only Rule",
            basis_type=BasisType.REGULATORY,
            applicability=RuleApplicability(agency=["NASA"]),
            trigger=RuleTrigger(all=["material_change_detected"]),
            finding="Test",
            severity=ComplianceSeverity.LOW,
            review_priority=ReviewPriority.ADVISORY,
        )

        dod_config = ContractConfig(agency="DoD")
        engine = RuleEngine(rules=[nasa_rule])
        diff = StructuralDiff(prior_revision="1", proposed_revision="2")
        findings = engine.run(diff, [], TaskOrder(task_order_number="T", revision_number="1"), dod_config)

        assert len(findings) == 0
        assert len(engine.suppression_log) > 0

    def test_applicability_filters_by_clause(self):
        clause_rule = TOCRRule(
            rule_id="TEST-CLAUSE",
            title="Clause-Gated Rule",
            basis_type=BasisType.REGULATORY,
            applicability=RuleApplicability(clause_required=["FAR 52.999-99"]),
            trigger=RuleTrigger(all=["material_change_detected"]),
            finding="Test",
            severity=ComplianceSeverity.CRITICAL,
            review_priority=ReviewPriority.CO,
        )

        # Config WITHOUT the required clause
        config = ContractConfig(clauses_present=[])
        engine = RuleEngine(rules=[clause_rule])
        diff = StructuralDiff(prior_revision="1", proposed_revision="2")
        findings = engine.run(diff, [], TaskOrder(task_order_number="T", revision_number="1"), config)

        assert len(findings) == 0
        suppressed = [s for s in engine.suppression_log if s["rule_id"] == "TEST-CLAUSE"]
        assert len(suppressed) > 0

    def test_draft_rule_fires_on_draft(self):
        prior = _make_prior()
        # Create a draft with a genuine scope INSERTION (new sub-task)
        proposed = _make_prior()
        proposed.revision_number = "Rev 35"
        proposed.revision_status = RevisionStatus.DRAFT
        proposed.summary_of_changes = "Updated revision number."
        proposed.sub_tasks.append(
            SubTask(sub_task_id="ST-002", description="New AI development task")
        )
        config = ContractConfig(revision_status=RevisionStatus.DRAFT)

        diff = DiffEngine().run(prior, proposed)
        disclosures = DisclosureEngine().run(diff, proposed.summary_of_changes)

        engine = RuleEngine(rules=self._get_test_rules())
        findings = engine.run(diff, disclosures, proposed, config)

        tocr009 = [f for f in findings if f.rule_id == "TOCR-009"]
        assert len(tocr009) > 0, "TOCR-009 should fire on draft revision with scope additions"
        assert tocr009[0].severity == ComplianceSeverity.MEDIUM


class TestRuleEngineDataPack:
    def test_load_default_rules(self):
        """Test loading the full rule pack from JSON."""
        from pathlib import Path
        rules_path = Path(__file__).parent.parent.parent.parent / "sentinel" / "tocr" / "data" / "tocr_rules.json"
        if not rules_path.exists():
            pytest.skip("Rules JSON not found")

        engine = RuleEngine()
        engine.load_rules_from_json(rules_path)
        assert len(engine.rules) == 15

        # Verify all rule IDs
        rule_ids = {r.rule_id for r in engine.rules}
        for i in range(1, 16):
            assert f"TOCR-{i:03d}" in rule_ids

    def test_all_rules_have_required_fields(self):
        """Verify every rule has the required schema fields."""
        from pathlib import Path
        rules_path = Path(__file__).parent.parent.parent.parent / "sentinel" / "tocr" / "data" / "tocr_rules.json"
        if not rules_path.exists():
            pytest.skip("Rules JSON not found")

        engine = RuleEngine()
        engine.load_rules_from_json(rules_path)

        for rule in engine.rules:
            assert rule.rule_id
            assert rule.title
            assert rule.basis_type
            assert rule.severity
            assert rule.review_priority
            assert rule.finding
            assert rule.guidance
            assert rule.remediation
            assert rule.trigger.all or rule.trigger.any
