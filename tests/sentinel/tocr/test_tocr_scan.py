#!/usr/bin/env python3
"""Tests for TOCR standalone compliance scan — give it a TO, get compliance or findings."""

import pytest
from pathlib import Path

from sentinel.tocr.engine.scan_engine import ScanEngine, TaskOrderContext
from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import (
    ComplianceSeverity,
    ComplianceVerdict,
    ContractType,
    RevisionStatus,
)
from sentinel.tocr.models.task_order import (
    FundingEntry,
    QualityPlan,
    SubTask,
    TaskOrder,
)


def _make_compliant_to() -> TaskOrder:
    """A fully compliant task order — should produce zero findings."""
    return TaskOrder(
        task_order_number="TO-9999",
        revision_number="Rev 1",
        revision_status=RevisionStatus.RELEASED,
        title="Compliant Task Order",
        task_order_description="Engineering analysis and documentation support.",
        scope_text="Engineering analysis and documentation support.",
        summary_of_changes="Initial release of task order.",
        sub_tasks=[
            SubTask(
                sub_task_id="ST-001",
                description="Engineering analysis for thermal systems",
                skills=["mechanical engineer", "thermal analyst"],
                labor_categories=["Engineer III"],
                funding=150000.0,
                wbs_code="WBS-100",
                charge_code="CC-100",
                participating_team=["Amentum"],
                deliverables=["Monthly status report", "Final analysis report"],
            ),
        ],
        funding_table=[
            FundingEntry(sub_task_id="ST-001", amount=150000.0, wbs_code="WBS-100"),
        ],
        total_funding=150000.0,
        quality_plan=QualityPlan(text="Standard QMS applies."),
    )


def _make_noncompliant_to() -> TaskOrder:
    """A task order with multiple compliance issues."""
    return TaskOrder(
        task_order_number="TO-BAD",
        revision_number="Rev 3",
        revision_status=RevisionStatus.DRAFT,
        title="Problem Task Order",
        task_order_description=(
            "MAPTIS-II Development Support including development of Software Tools "
            "for integration of AI solutions and machine learning pipelines."
        ),
        scope_text=(
            "MAPTIS-II Development Support including development of Software Tools "
            "for integration of AI solutions and machine learning pipelines."
        ),
        summary_of_changes="",  # Empty!
        sub_tasks=[
            SubTask(
                sub_task_id="ST-001",
                description="MAPTIS database maintenance",
                skills=["database admin"],  # No software skills despite software scope
                labor_categories=[],
                funding=0,  # Unfunded
                wbs_code=None,  # No WBS
                charge_code=None,  # No charge code
                participating_team=["Amentum"],
                deliverables=[],  # No deliverables
            ),
            SubTask(
                sub_task_id="ST-002",
                description="",  # No description
                skills=[],
                labor_categories=[],
                funding=None,
                wbs_code=None,
                charge_code=None,
                participating_team=[],
                deliverables=[],
            ),
        ],
        total_funding=0,
        quality_plan=QualityPlan(text="TBD"),  # No QMS despite software scope
    )


def _make_retroactive_to() -> TaskOrder:
    """A task order with retroactive scope language."""
    return TaskOrder(
        task_order_number="TO-RETRO",
        revision_number="Rev 5",
        revision_status=RevisionStatus.RELEASED,
        title="Retroactive TO",
        task_order_description=(
            "This task captures work previously performed under verbal direction "
            "for the AI tools integration effort already completed in Q4."
        ),
        summary_of_changes="Added retroactive scope.",
        sub_tasks=[
            SubTask(
                sub_task_id="ST-001",
                description="AI tools integration (work already done)",
                skills=["software engineer"],
                funding=100000.0,
                wbs_code="WBS-500",
                charge_code="CC-500",
                deliverables=["Final report"],
            ),
        ],
        total_funding=100000.0,
    )


def _make_emergency_no_justification() -> TaskOrder:
    """Emergency designated but no justification."""
    return TaskOrder(
        task_order_number="TO-EMERG",
        revision_number="Rev 1",
        revision_status=RevisionStatus.RELEASED,
        title="Emergency TO",
        task_order_description="Emergency hardware repair support.",
        summary_of_changes="Emergency designation.",
        emergency_designation=True,
        emergency_justification="",  # Empty!
        sub_tasks=[
            SubTask(
                sub_task_id="ST-001",
                description="Emergency repair",
                skills=["technician"],
                funding=50000.0,
                wbs_code="WBS-E01",
                charge_code="CC-E01",
                deliverables=["Repair completion report"],
            ),
        ],
        total_funding=50000.0,
    )


def _nasa_config() -> ContractConfig:
    return ContractConfig(
        contract_type=[ContractType.IDIQ, ContractType.TASK_ORDER],
        agency="NASA",
        vehicle="ESSCA",
        local_policy_pack="ESSCA-MSFC",
        clauses_present=["FAR 52.232-22"],
        revision_status=RevisionStatus.DRAFT,
    )


def _scan_rules_path() -> Path:
    return Path(__file__).parent.parent.parent.parent / "sentinel" / "tocr" / "data" / "scan_rules.json"


class TestTaskOrderContext:
    """Test signal computation from a single task order."""

    def test_compliant_to_signals(self):
        ctx = TaskOrderContext(_make_compliant_to(), _nasa_config())
        assert "has_scope" in ctx.signals
        assert "sub_task_completely_unfunded" not in ctx.signals
        assert "software_scope_present" not in ctx.signals
        assert "no_sub_tasks" not in ctx.signals

    def test_noncompliant_to_signals(self):
        ctx = TaskOrderContext(_make_noncompliant_to(), _nasa_config())
        assert "software_scope_present" in ctx.signals
        assert "software_without_qms" in ctx.signals
        assert "sub_task_completely_unfunded" in ctx.signals
        assert "sub_task_no_deliverables" in ctx.signals
        assert "sub_task_no_description" in ctx.signals
        assert "no_summary_of_changes" in ctx.signals
        assert "zero_total_funding" in ctx.signals
        assert "revision_is_draft" in ctx.signals

    def test_retroactive_signals(self):
        ctx = TaskOrderContext(_make_retroactive_to(), _nasa_config())
        assert "retroactive_scope_language" in ctx.signals

    def test_emergency_signals(self):
        ctx = TaskOrderContext(_make_emergency_no_justification(), _nasa_config())
        assert "emergency_designated" in ctx.signals
        assert "emergency_no_justification" in ctx.signals


class TestScanEngine:
    def _load_engine(self) -> ScanEngine:
        path = _scan_rules_path()
        if not path.exists():
            pytest.skip("scan_rules.json not found")
        engine = ScanEngine()
        engine.load_rules_from_json(path)
        return engine

    def test_compliant_to_no_findings(self):
        engine = self._load_engine()
        config = ContractConfig(
            agency="NASA",
            clauses_present=["FAR 52.232-22"],
            revision_status=RevisionStatus.RELEASED,
        )
        findings = engine.run(_make_compliant_to(), config)
        assert len(findings) == 0, f"Expected 0 findings, got: {[f.rule_id for f in findings]}"

    def test_noncompliant_to_multiple_findings(self):
        engine = self._load_engine()
        config = _nasa_config()
        findings = engine.run(_make_noncompliant_to(), config)

        rule_ids = {f.rule_id for f in findings}
        # Should catch unfunded sub-task, missing deliverables, software w/o QMS,
        # empty summary, zero total funding, sub-task no description, draft status
        assert "SCAN-001" in rule_ids, "Should catch unfunded sub-task"
        assert "SCAN-002" in rule_ids, "Should catch missing deliverables"
        assert "SCAN-003" in rule_ids, "Should catch software without QMS"
        assert "SCAN-011" in rule_ids, "Should catch zero total funding"
        assert "SCAN-012" in rule_ids, "Should catch empty summary"
        assert "SCAN-013" in rule_ids, "Should catch sub-task no description"

    def test_retroactive_scope_finding(self):
        engine = self._load_engine()
        config = ContractConfig(revision_status=RevisionStatus.RELEASED)
        findings = engine.run(_make_retroactive_to(), config)

        rule_ids = {f.rule_id for f in findings}
        assert "SCAN-005" in rule_ids, "Should catch retroactive scope"

    def test_emergency_no_justification_finding(self):
        engine = self._load_engine()
        config = ContractConfig(revision_status=RevisionStatus.RELEASED)
        findings = engine.run(_make_emergency_no_justification(), config)

        rule_ids = {f.rule_id for f in findings}
        assert "SCAN-004" in rule_ids, "Should catch emergency without justification"

    def test_unfunded_rule_fires_without_clause_config(self):
        """SCAN-001 should fire regardless of clause configuration.

        Unfunded scope is always a compliance issue. The clause is the legal
        basis, not a precondition — removing the clause gate was a deliberate
        fix to prevent silent under-reporting of CRITICAL findings.
        """
        engine = self._load_engine()
        config = ContractConfig(
            agency="NASA",
            clauses_present=[],  # No limitation of funds clause
            revision_status=RevisionStatus.DRAFT,
        )
        findings = engine.run(_make_noncompliant_to(), config)
        rule_ids = {f.rule_id for f in findings}
        assert "SCAN-001" in rule_ids, "SCAN-001 must fire even without FAR 52.232-22 clause configured"

    def test_all_scan_rules_load(self):
        engine = self._load_engine()
        assert len(engine.rules) == 14

    def test_finding_has_evidence_detail(self):
        engine = self._load_engine()
        config = _nasa_config()
        findings = engine.run(_make_noncompliant_to(), config)

        for f in findings:
            assert f.finding_id
            assert f.rule_id.startswith("SCAN-")
            assert f.finding_text
            assert f.guidance
            assert f.remediation
            assert f.evidence is not None


class TestConductorScanMode:
    """Test the conductor's scan() method — the primary user-facing API."""

    def test_scan_compliant(self):
        config = ContractConfig(
            agency="NASA",
            clauses_present=["FAR 52.232-22"],
            revision_status=RevisionStatus.RELEASED,
        )
        conductor = TOCRConductor(config=config)
        report = conductor.scan(_make_compliant_to())

        assert report.report_id.startswith("SCAN-")
        assert report.score is not None
        assert report.score.verdict == ComplianceVerdict.CLEAN
        assert len(report.findings) == 0

    def test_scan_noncompliant(self):
        config = _nasa_config()
        conductor = TOCRConductor(config=config)
        report = conductor.scan(_make_noncompliant_to())

        assert report.score is not None
        assert report.score.verdict == ComplianceVerdict.FATAL
        assert len(report.findings) > 0

        critical = [f for f in report.findings if f.severity == ComplianceSeverity.CRITICAL]
        assert len(critical) > 0

    def test_scan_report_structure(self):
        config = _nasa_config()
        conductor = TOCRConductor(config=config)
        report = conductor.scan(_make_noncompliant_to())

        assert report.proposed_revision == "Rev 3"
        assert "NASA" in report.contract_config_summary
        assert report.rules_evaluated > 0
        assert report.rules_fired > 0
        assert isinstance(report.assumptions, list)
        assert any("Standalone scan" in a for a in report.assumptions)

    def test_scan_then_review_both_work(self):
        """Conductor supports both scan() and review() on same instance."""
        config = _nasa_config()
        conductor = TOCRConductor(config=config)

        # Scan mode
        scan_report = conductor.scan(_make_noncompliant_to())
        assert scan_report.report_id.startswith("SCAN-")

        # Review mode (same conductor)
        review_report = conductor.review(_make_compliant_to(), _make_noncompliant_to())
        assert review_report.report_id.startswith("TOCR-")


class TestScanWithTextExport:
    def test_text_export_scan_report(self):
        from sentinel.tocr.exports.text_export import export_text

        config = _nasa_config()
        conductor = TOCRConductor(config=config)
        report = conductor.scan(_make_noncompliant_to())
        text = export_text(report)

        assert "SENTINEL-TOCR COMPLIANCE REPORT" in text
        assert "FATAL" in text
        assert "SCAN-" in text
