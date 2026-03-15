#!/usr/bin/env python3
"""Tests for TOCR Conductor — full pipeline integration tests."""

import pytest

from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import (
    ComplianceSeverity,
    ComplianceVerdict,
    ContractType,
    RevisionStatus,
)
from sentinel.tocr.models.rules import RuleApplicability, RuleTrigger, TOCRRule
from sentinel.tocr.models.task_order import (
    FundingEntry,
    QualityPlan,
    SubTask,
    TaskOrder,
)
from sentinel.tocr.models.enums import BasisType, ReviewPriority


def _make_prior() -> TaskOrder:
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


def _make_undisclosed_scope_expansion() -> TaskOrder:
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


def _get_minimal_rules() -> list[TOCRRule]:
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
            guidance="Disclose all changes.",
            remediation="Add to Summary of Changes.",
        ),
    ]


class TestTOCRConductor:
    def test_full_pipeline_undisclosed_scope(self):
        """Test the spec example: undisclosed scope expansion triggers TOCR-001."""
        config = ContractConfig(
            contract_type=[ContractType.IDIQ, ContractType.TASK_ORDER],
            agency="NASA",
            vehicle="ESSCA",
            local_policy_pack="ESSCA-MSFC",
            clauses_present=["FAR 52.232-22"],
            revision_status=RevisionStatus.DRAFT,
        )

        conductor = TOCRConductor(config=config, rules=_get_minimal_rules())
        report = conductor.review(_make_prior(), _make_undisclosed_scope_expansion())

        assert report.report_id.startswith("TOCR-")
        assert report.total_changes_detected > 0
        assert report.material_changes_detected > 0
        assert report.undisclosed_changes > 0

        # Should have at least one CRITICAL finding
        critical = [f for f in report.findings if f.severity == ComplianceSeverity.CRITICAL]
        assert len(critical) > 0

        # Score should be FATAL
        assert report.score is not None
        assert report.score.verdict == ComplianceVerdict.FATAL

    def test_full_pipeline_no_changes(self):
        """Test pipeline with identical revisions — should be CLEAN."""
        config = ContractConfig(agency="NASA")
        conductor = TOCRConductor(config=config, rules=_get_minimal_rules())
        prior = _make_prior()
        report = conductor.review(prior, prior)

        assert report.total_changes_detected == 0
        assert len(report.findings) == 0
        assert report.score.verdict == ComplianceVerdict.CLEAN

    def test_revision_chain(self):
        """Test multi-revision chain analysis (Section 14.3)."""
        config = ContractConfig(agency="NASA")
        conductor = TOCRConductor(config=config, rules=_get_minimal_rules())

        rev34 = _make_prior()
        rev35 = _make_undisclosed_scope_expansion()
        rev36 = _make_undisclosed_scope_expansion()
        rev36.revision_number = "Rev 36"

        reports = conductor.review_chain([rev34, rev35, rev36])
        assert len(reports) == 2

    def test_report_has_assumptions(self):
        """Test that the report includes assumption drawer."""
        config = ContractConfig(agency="NASA")
        conductor = TOCRConductor(config=config, rules=_get_minimal_rules())
        report = conductor.review(_make_prior(), _make_undisclosed_scope_expansion())

        # Report should have assumptions list (may be empty for high-confidence parse)
        assert isinstance(report.assumptions, list)

    def test_report_contract_config_summary(self):
        """Test that contract config summary is populated."""
        config = ContractConfig(
            agency="NASA",
            vehicle="ESSCA",
            local_policy_pack="ESSCA-MSFC",
        )
        conductor = TOCRConductor(config=config, rules=_get_minimal_rules())
        report = conductor.review(_make_prior(), _make_undisclosed_scope_expansion())

        assert "NASA" in report.contract_config_summary
        assert "ESSCA" in report.contract_config_summary


class TestTOCRConductorWithDefaultRules:
    def test_load_default_rules_from_json(self):
        """Test conductor loads default rule pack."""
        from pathlib import Path
        rules_path = Path(__file__).parent.parent.parent.parent / "sentinel" / "tocr" / "data" / "tocr_rules.json"
        if not rules_path.exists():
            pytest.skip("Default rules not found")

        config = ContractConfig(
            agency="NASA",
            clauses_present=["FAR 52.232-22"],
            local_policy_pack="ESSCA-MSFC",
        )
        conductor = TOCRConductor(config=config, rules_path=rules_path)
        assert len(conductor.rule_engine.rules) == 15

    def test_full_pipeline_with_all_rules(self):
        """Integration test with all 14 rules."""
        from pathlib import Path
        rules_path = Path(__file__).parent.parent.parent.parent / "sentinel" / "tocr" / "data" / "tocr_rules.json"
        if not rules_path.exists():
            pytest.skip("Default rules not found")

        config = ContractConfig(
            contract_type=[ContractType.IDIQ, ContractType.TASK_ORDER],
            agency="NASA",
            vehicle="ESSCA",
            local_policy_pack="ESSCA-MSFC",
            clauses_present=["FAR 52.232-22"],
            revision_status=RevisionStatus.DRAFT,
        )

        conductor = TOCRConductor(config=config, rules_path=rules_path)
        report = conductor.review(_make_prior(), _make_undisclosed_scope_expansion())

        # With all rules and undisclosed scope expansion, should have multiple findings
        assert len(report.findings) > 0
        assert report.score is not None

        # Verify finding structure
        for f in report.findings:
            assert f.finding_id
            assert f.rule_id.startswith("TOCR-")
            assert f.rule_title
            assert f.severity
            assert f.review_priority
