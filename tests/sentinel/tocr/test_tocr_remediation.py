#!/usr/bin/env python3
"""Tests for TOCR remediation advisor."""

import json
import pytest
from pathlib import Path

from sentinel.tocr.engine.remediation_advisor import RemediationAdvisor
from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.exports.text_export import export_text
from sentinel.tocr.exports.json_export import export_json
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import (
    BasisType,
    ChangeClassification,
    ChangeType,
    ComplianceSeverity,
    ConfidenceLevel,
    ParserConfidence,
    ReviewPriority,
    RevisionStatus,
)
from sentinel.tocr.models.evidence import TOCREvidence, TOCRFinding
from sentinel.tocr.models.remediation import RemediationPlan, RemediationStep
from sentinel.tocr.models.rules import RuleApplicability, RuleTrigger, TOCRRule
from sentinel.tocr.models.task_order import QualityPlan, SubTask, TaskOrder


def _make_finding(
    rule_id: str = "TOCR-001",
    title: str = "Undisclosed Material Change",
    severity: ComplianceSeverity = ComplianceSeverity.CRITICAL,
    review_priority: ReviewPriority = ReviewPriority.CO,
    field_path: str = "scope_text",
    proposed_text: str = "New AI development capability",
) -> TOCRFinding:
    """Helper to create a test finding."""
    finding_id = f"F-TEST01"
    return TOCRFinding(
        finding_id=finding_id,
        rule_id=rule_id,
        rule_title=title,
        severity=severity,
        review_priority=review_priority,
        confidence_method=ConfidenceLevel.DETERMINISTIC,
        finding_text=f"Test finding for {rule_id}.",
        guidance="Test guidance.",
        remediation="Test remediation.",
        authority_basis=["FAR 1.602-1"],
        evidence=TOCREvidence(
            finding_id=finding_id,
            rule_id=rule_id,
            prior_text="",
            proposed_text=proposed_text,
            field_path=field_path,
            change_type=ChangeType.INSERTION,
            classification=ChangeClassification.SCOPE_LANGUAGE,
            classification_confidence=ConfidenceLevel.DETERMINISTIC,
            classification_reason="Test",
            parser_confidence=ParserConfidence.HIGH,
        ),
    )


def _make_task_order(**kwargs) -> TaskOrder:
    """Helper to create a test task order."""
    defaults = dict(
        task_order_number="TO-1234",
        revision_number="Rev 35",
        revision_status=RevisionStatus.DRAFT,
        title="Test TO",
        task_order_description="Software development for AI systems",
        scope_text="Develop machine learning models and software applications",
        summary_of_changes="Updated scope.",
        sub_tasks=[
            SubTask(
                sub_task_id="ST-001",
                description="AI model development",
                funding=100000.0,
                wbs_code="WBS-001",
                charge_code="CC-001",
                skills=["Systems Engineer"],
                deliverables=["Monthly report"],
            ),
            SubTask(
                sub_task_id="ST-002",
                description="Data pipeline development",
                funding=0,
                skills=[],
                deliverables=[],
            ),
        ],
    )
    defaults.update(kwargs)
    return TaskOrder(**defaults)


class TestRemediationPlanModel:
    def test_empty_plan(self):
        plan = RemediationPlan()
        assert plan.is_empty
        assert not plan.has_blockers
        assert plan.total_steps == 0

    def test_plan_with_steps(self):
        step = RemediationStep(
            finding_id="F-001",
            rule_id="TOCR-001",
            rule_title="Test",
            severity=ComplianceSeverity.CRITICAL,
            review_priority=ReviewPriority.CO,
            what_to_fix="Fix this",
            how_to_fix="Do this",
        )
        plan = RemediationPlan(
            steps=[step],
            total_steps=1,
            critical_steps=1,
        )
        assert not plan.is_empty
        assert plan.has_blockers

    def test_plan_no_blockers(self):
        step = RemediationStep(
            finding_id="F-001",
            rule_id="TOCR-009",
            rule_title="Test",
            severity=ComplianceSeverity.MEDIUM,
            review_priority=ReviewPriority.ADVISORY,
            what_to_fix="Minor issue",
            how_to_fix="Small fix",
        )
        plan = RemediationPlan(
            steps=[step],
            total_steps=1,
            medium_steps=1,
        )
        assert not plan.has_blockers


class TestRemediationAdvisor:
    def test_empty_findings(self):
        advisor = RemediationAdvisor()
        plan = advisor.advise([])
        assert plan.is_empty
        assert plan.total_steps == 0

    def test_single_finding(self):
        advisor = RemediationAdvisor()
        finding = _make_finding()
        plan = advisor.advise([finding])

        assert plan.total_steps == 1
        assert plan.critical_steps == 1
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.finding_id == finding.finding_id
        assert step.rule_id == "TOCR-001"
        assert step.severity == ComplianceSeverity.CRITICAL
        assert step.priority_order == 1

    def test_priority_ordering(self):
        """CRITICAL findings should sort before HIGH, etc."""
        advisor = RemediationAdvisor()
        findings = [
            _make_finding(rule_id="TOCR-009", title="Draft", severity=ComplianceSeverity.MEDIUM,
                          review_priority=ReviewPriority.ADVISORY),
            _make_finding(rule_id="TOCR-001", title="Undisclosed", severity=ComplianceSeverity.CRITICAL),
            _make_finding(rule_id="TOCR-005", title="Missing Deliverables", severity=ComplianceSeverity.HIGH,
                          review_priority=ReviewPriority.SUPERVISORY),
        ]
        plan = advisor.advise(findings)

        assert plan.steps[0].severity == ComplianceSeverity.CRITICAL
        assert plan.steps[1].severity == ComplianceSeverity.HIGH
        assert plan.steps[2].severity == ComplianceSeverity.MEDIUM
        assert plan.steps[0].priority_order == 1
        assert plan.steps[1].priority_order == 2
        assert plan.steps[2].priority_order == 3

    def test_guidance_enrichment(self):
        """Steps should pull from guidance.json when available."""
        advisor = RemediationAdvisor()
        finding = _make_finding(rule_id="TOCR-001")
        plan = advisor.advise([finding])
        step = plan.steps[0]

        # Should have plain-English what_to_fix from guidance.json, not generic finding text
        assert "Summary of Changes" in step.what_to_fix or "change" in step.what_to_fix.lower()
        assert step.owner  # Should have an owner

    def test_context_undisclosed_change(self):
        """Undisclosed change should include field path in fix instructions."""
        advisor = RemediationAdvisor()
        finding = _make_finding(
            rule_id="TOCR-001",
            field_path="sub_tasks.ST-001.description",
            proposed_text="New AI model development capability",
        )
        to = _make_task_order()
        plan = advisor.advise([finding], task_order=to)
        step = plan.steps[0]

        assert "sub_tasks.ST-001.description" in step.how_to_fix
        assert "Summary of Changes" in step.how_to_fix

    def test_context_unfunded_scope(self):
        """Unfunded scope should identify specific sub-tasks."""
        advisor = RemediationAdvisor()
        finding = _make_finding(
            rule_id="TOCR-004",
            title="Unfunded Scope",
            field_path="scope_text",
        )
        to = _make_task_order(
            sub_tasks=[
                SubTask(sub_task_id="ST-003", description="Unfunded work", funding=0),
            ],
        )
        plan = advisor.advise([finding], task_order=to)
        step = plan.steps[0]

        assert "ST-003" in step.how_to_fix

    def test_context_missing_deliverables(self):
        """Missing deliverables should identify sub-tasks without them."""
        advisor = RemediationAdvisor()
        finding = _make_finding(
            rule_id="TOCR-005",
            title="Missing Deliverables",
            severity=ComplianceSeverity.HIGH,
            review_priority=ReviewPriority.SUPERVISORY,
        )
        to = _make_task_order()  # ST-002 has no deliverables
        plan = advisor.advise([finding], task_order=to)
        step = plan.steps[0]

        assert "ST-002" in step.how_to_fix

    def test_context_software_qms(self):
        """Software QMS finding should identify software keywords."""
        advisor = RemediationAdvisor()
        finding = _make_finding(
            rule_id="TOCR-008",
            title="Software QMS Trigger",
            field_path="scope_text",
        )
        to = _make_task_order()
        plan = advisor.advise([finding], task_order=to)
        step = plan.steps[0]

        assert "software" in step.how_to_fix.lower() or "QMS" in step.how_to_fix

    def test_owner_resolution(self):
        """Each step should have an owner based on review priority or guidance."""
        advisor = RemediationAdvisor()
        findings = [
            _make_finding(rule_id="TOCR-001", review_priority=ReviewPriority.CO),
            _make_finding(rule_id="TOCR-005", title="Missing Deliverables",
                          severity=ComplianceSeverity.HIGH,
                          review_priority=ReviewPriority.SUPERVISORY),
        ]
        plan = advisor.advise(findings)

        assert len(plan.estimated_owners) >= 1
        for step in plan.steps:
            assert step.owner  # Every step should have an owner

    def test_severity_counts(self):
        advisor = RemediationAdvisor()
        findings = [
            _make_finding(severity=ComplianceSeverity.CRITICAL),
            _make_finding(rule_id="TOCR-005", title="Deliverables",
                          severity=ComplianceSeverity.HIGH,
                          review_priority=ReviewPriority.SUPERVISORY),
            _make_finding(rule_id="TOCR-009", title="Draft",
                          severity=ComplianceSeverity.MEDIUM,
                          review_priority=ReviewPriority.ADVISORY),
        ]
        plan = advisor.advise(findings)

        assert plan.critical_steps == 1
        assert plan.high_steps == 1
        assert plan.medium_steps == 1
        assert plan.low_steps == 0
        assert plan.total_steps == 3


class TestConductorRemediation:
    def test_review_includes_remediation_plan(self):
        """Conductor.review() should produce a report with a remediation plan."""
        prior = TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 34",
            revision_status=RevisionStatus.RELEASED,
            title="Test TO",
            task_order_description="Original scope text",
            summary_of_changes="Initial.",
            sub_tasks=[SubTask(sub_task_id="ST-001", description="Original task", funding=100000.0)],
        )
        proposed = TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 35",
            revision_status=RevisionStatus.DRAFT,
            title="Test TO",
            task_order_description="Expanded scope with new software development capabilities",
            summary_of_changes="Updated revision.",
            sub_tasks=[SubTask(sub_task_id="ST-001", description="Original task", funding=100000.0)],
        )

        rules = [
            TOCRRule(
                rule_id="TOCR-001",
                title="Undisclosed Material Change",
                basis_type=BasisType.INTERNAL_CONTROL,
                authority_basis=["FAR 1.602-1"],
                applicability=RuleApplicability(revision_status=["draft", "released"]),
                trigger=RuleTrigger(all=["material_change_detected", "not_listed_in_summary_of_changes"]),
                finding="Material change not disclosed.",
                severity=ComplianceSeverity.CRITICAL,
                review_priority=ReviewPriority.CO,
                guidance="Disclose all changes.",
                remediation="Add to Summary of Changes.",
            ),
        ]

        config = ContractConfig(agency="NASA", revision_status=RevisionStatus.DRAFT)
        conductor = TOCRConductor(config=config, rules=rules)
        report = conductor.review(prior, proposed)

        assert report.remediation_plan is not None
        assert report.findings, "Review must produce findings for this test to be valid"
        assert report.remediation_plan.total_steps == len(report.findings)
        assert report.remediation_plan.total_steps > 0

    def test_scan_includes_remediation_plan(self):
        """Conductor.scan() should produce a report with a remediation plan."""
        to = TaskOrder(
            task_order_number="TO-5678",
            revision_number="Rev 1",
            revision_status=RevisionStatus.DRAFT,
            title="Scan Test",
            task_order_description="Software development for AI systems",
            summary_of_changes="",
            sub_tasks=[
                SubTask(sub_task_id="ST-001", description="AI work", funding=0),
            ],
        )

        config = ContractConfig(agency="NASA", revision_status=RevisionStatus.DRAFT)
        conductor = TOCRConductor(config=config)
        report = conductor.scan(to)

        assert report.remediation_plan is not None
        # Should have findings (unfunded, no deliverables, etc.) and matching steps
        assert report.findings, "Scan must produce findings for this test to be valid"
        assert report.remediation_plan.total_steps == len(report.findings)


class TestExportsWithRemediation:
    def test_text_export_includes_remediation(self):
        """Text export should include HOW TO FIX section when there are findings."""
        prior = TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 34",
            revision_status=RevisionStatus.RELEASED,
            title="Test TO",
            task_order_description="Original scope",
            summary_of_changes="Initial.",
            sub_tasks=[SubTask(sub_task_id="ST-001", description="Original", funding=100000.0)],
        )
        proposed = TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 35",
            revision_status=RevisionStatus.DRAFT,
            title="Test TO",
            task_order_description="Expanded with new software development",
            summary_of_changes="Updated.",
            sub_tasks=[SubTask(sub_task_id="ST-001", description="Original", funding=100000.0)],
        )
        rules = [
            TOCRRule(
                rule_id="TOCR-001",
                title="Undisclosed Material Change",
                basis_type=BasisType.INTERNAL_CONTROL,
                authority_basis=["FAR 1.602-1"],
                applicability=RuleApplicability(revision_status=["draft", "released"]),
                trigger=RuleTrigger(all=["material_change_detected", "not_listed_in_summary_of_changes"]),
                finding="Material change not disclosed.",
                severity=ComplianceSeverity.CRITICAL,
                review_priority=ReviewPriority.CO,
                guidance="Disclose all changes.",
                remediation="Add to Summary of Changes.",
            ),
        ]

        config = ContractConfig(agency="NASA", revision_status=RevisionStatus.DRAFT)
        conductor = TOCRConductor(config=config, rules=rules)
        report = conductor.review(prior, proposed)
        text = export_text(report)

        assert report.findings, "Review must produce findings for this test to be valid"
        assert "HOW TO FIX" in text
        assert "REMEDIATION PLAN" in text
        assert "Problem:" in text
        assert "Fix:" in text
        assert "Owner:" in text

    def test_json_export_includes_remediation(self):
        """JSON export should include remediation_plan field."""
        prior = TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 34",
            revision_status=RevisionStatus.RELEASED,
            title="Test TO",
            task_order_description="Original scope",
            summary_of_changes="Initial.",
            sub_tasks=[SubTask(sub_task_id="ST-001", description="Original", funding=100000.0)],
        )
        proposed = TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 35",
            revision_status=RevisionStatus.DRAFT,
            title="Test TO",
            task_order_description="Expanded with new software development",
            summary_of_changes="Updated.",
            sub_tasks=[SubTask(sub_task_id="ST-001", description="Original", funding=100000.0)],
        )
        rules = [
            TOCRRule(
                rule_id="TOCR-001",
                title="Undisclosed Material Change",
                basis_type=BasisType.INTERNAL_CONTROL,
                authority_basis=["FAR 1.602-1"],
                applicability=RuleApplicability(revision_status=["draft", "released"]),
                trigger=RuleTrigger(all=["material_change_detected", "not_listed_in_summary_of_changes"]),
                finding="Material change not disclosed.",
                severity=ComplianceSeverity.CRITICAL,
                review_priority=ReviewPriority.CO,
                guidance="Disclose all changes.",
                remediation="Add to Summary of Changes.",
            ),
        ]

        config = ContractConfig(agency="NASA", revision_status=RevisionStatus.DRAFT)
        conductor = TOCRConductor(config=config, rules=rules)
        report = conductor.review(prior, proposed)
        json_str = export_json(report)
        data = json.loads(json_str)

        assert "remediation_plan" in data
        assert report.findings, "Review must produce findings for this test to be valid"
        assert data["remediation_plan"] is not None
        assert "steps" in data["remediation_plan"]
        assert len(data["remediation_plan"]["steps"]) > 0


class TestRemediationWithNoGuidance:
    def test_fallback_without_guidance_file(self, tmp_path):
        """Advisor should still work when guidance.json doesn't exist."""
        advisor = RemediationAdvisor(guidance_path=tmp_path / "nonexistent.json")
        finding = _make_finding()
        plan = advisor.advise([finding])

        assert plan.total_steps == 1
        step = plan.steps[0]
        # Should fall back to finding text / rule remediation
        assert step.what_to_fix  # Non-empty
        assert step.how_to_fix  # Non-empty
