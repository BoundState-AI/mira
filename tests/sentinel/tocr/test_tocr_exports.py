#!/usr/bin/env python3
"""Tests for TOCR export formatters."""

import json
import pytest

from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.exports.json_export import export_json
from sentinel.tocr.exports.text_export import export_text
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import (
    BasisType,
    ComplianceSeverity,
    ContractType,
    ReviewPriority,
    RevisionStatus,
)
from sentinel.tocr.models.report import ComplianceReport, ComplianceScore
from sentinel.tocr.models.rules import RuleApplicability, RuleTrigger, TOCRRule
from sentinel.tocr.models.task_order import (
    FundingEntry,
    QualityPlan,
    SubTask,
    TaskOrder,
)


def _make_sample_report() -> ComplianceReport:
    """Generate a sample report via the conductor."""
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
    return conductor.review(prior, proposed)


class TestJSONExport:
    def test_export_json_string(self):
        report = _make_sample_report()
        json_str = export_json(report)

        data = json.loads(json_str)
        assert "report_id" in data
        assert "findings" in data
        assert "score" in data

    def test_export_json_roundtrip(self):
        report = _make_sample_report()
        json_str = export_json(report)
        data = json.loads(json_str)

        assert data["prior_revision"] == "Rev 34"
        assert data["proposed_revision"] == "Rev 35"


class TestTextExport:
    def test_export_text(self):
        report = _make_sample_report()
        text = export_text(report)

        assert "SENTINEL-TOCR COMPLIANCE REPORT" in text
        assert "VERDICT:" in text
        assert "Rev 34" in text
        assert "Rev 35" in text

    def test_export_clean_report(self):
        report = ComplianceReport(
            report_id="TOCR-TEST",
            prior_revision="Rev 1",
            proposed_revision="Rev 2",
            score=ComplianceScore.compute([]),
        )
        text = export_text(report)

        assert "CLEAN" in text
        assert "No findings" in text
