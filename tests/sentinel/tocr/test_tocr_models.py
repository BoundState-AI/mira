#!/usr/bin/env python3
"""Tests for TOCR data models."""

import pytest

from sentinel.tocr.models.enums import (
    ChangeClassification,
    ChangeType,
    ComplianceSeverity,
    ComplianceVerdict,
    ContractType,
    ParserConfidence,
    ReviewPriority,
    RevisionStatus,
)
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.diff import FieldChange, StructuralDiff
from sentinel.tocr.models.evidence import TOCREvidence, TOCRFinding
from sentinel.tocr.models.report import ComplianceScore
from sentinel.tocr.models.task_order import TaskOrder, SubTask, QualityPlan


class TestContractConfig:
    def test_default_config(self):
        config = ContractConfig()
        assert config.agency == "NASA"
        assert ContractType.IDIQ in config.contract_type

    def test_has_clause(self):
        config = ContractConfig(clauses_present=["FAR 52.232-22"])
        assert config.has_clause("FAR 52.232-22")
        assert not config.has_clause("FAR 99.999")

    def test_matches_agency(self):
        config = ContractConfig(agency="NASA")
        assert config.matches_agency("NASA")
        assert config.matches_agency("nasa")
        assert config.matches_agency(None)
        assert not config.matches_agency("DoD")

    def test_matches_contract_type(self):
        config = ContractConfig(contract_type=[ContractType.IDIQ, ContractType.TASK_ORDER])
        assert config.matches_contract_type(["IDIQ"])
        assert config.matches_contract_type(["Task Order"])
        assert config.matches_contract_type(None)
        assert not config.matches_contract_type(["FFP"])

    def test_matches_local_pack(self):
        config = ContractConfig(local_policy_pack="ESSCA-MSFC")
        assert config.matches_local_pack("ESSCA-MSFC")
        assert config.matches_local_pack("essca-msfc")
        assert config.matches_local_pack(None)

    def test_matches_revision_status(self):
        config = ContractConfig(revision_status=RevisionStatus.DRAFT)
        assert config.matches_revision_status(["draft"])
        assert config.matches_revision_status(None)
        assert not config.matches_revision_status(["released"])


class TestFieldChange:
    def test_is_formatting_only(self):
        fc = FieldChange(
            field_path="test",
            change_type=ChangeType.MODIFICATION,
            classification=ChangeClassification.FORMATTING,
        )
        assert fc.is_formatting_only

    def test_is_scope_related(self):
        fc = FieldChange(
            field_path="test",
            change_type=ChangeType.INSERTION,
            classification=ChangeClassification.SCOPE_LANGUAGE,
        )
        assert fc.is_scope_related

        fc2 = FieldChange(
            field_path="test",
            change_type=ChangeType.MODIFICATION,
            classification=ChangeClassification.ADMINISTRATIVE,
        )
        assert not fc2.is_scope_related


class TestComplianceScore:
    def test_clean_score(self):
        score = ComplianceScore.compute([])
        assert score.raw_score == 100
        assert score.verdict == ComplianceVerdict.CLEAN

    def test_fatal_with_critical(self):
        findings = [
            TOCRFinding(
                finding_id="F-001",
                rule_id="TOCR-001",
                rule_title="Test",
                severity=ComplianceSeverity.CRITICAL,
                review_priority=ReviewPriority.CO,
            )
        ]
        score = ComplianceScore.compute(findings)
        assert score.raw_score == 80
        assert score.verdict == ComplianceVerdict.FATAL
        assert score.critical_count == 1

    def test_flagged_with_high(self):
        findings = [
            TOCRFinding(
                finding_id="F-001",
                rule_id="TOCR-003",
                rule_title="Test",
                severity=ComplianceSeverity.HIGH,
                review_priority=ReviewPriority.CO,
            )
        ]
        score = ComplianceScore.compute(findings)
        assert score.raw_score == 90
        assert score.verdict == ComplianceVerdict.FLAGGED

    def test_multiple_findings(self):
        findings = [
            TOCRFinding(
                finding_id="F-001", rule_id="TOCR-001", rule_title="T",
                severity=ComplianceSeverity.CRITICAL, review_priority=ReviewPriority.CO,
            ),
            TOCRFinding(
                finding_id="F-002", rule_id="TOCR-003", rule_title="T",
                severity=ComplianceSeverity.HIGH, review_priority=ReviewPriority.CO,
            ),
            TOCRFinding(
                finding_id="F-003", rule_id="TOCR-009", rule_title="T",
                severity=ComplianceSeverity.MEDIUM, review_priority=ReviewPriority.ADVISORY,
            ),
            TOCRFinding(
                finding_id="F-004", rule_id="TOCR-012", rule_title="T",
                severity=ComplianceSeverity.LOW, review_priority=ReviewPriority.ADVISORY,
            ),
        ]
        score = ComplianceScore.compute(findings)
        # 100 - (1*20 + 1*10 + 1*5 + 1*1) = 64
        assert score.raw_score == 64
        assert score.verdict == ComplianceVerdict.FATAL  # Has critical


class TestTOCRFinding:
    def test_severity_score(self):
        f = TOCRFinding(
            finding_id="F-001", rule_id="TOCR-001", rule_title="T",
            severity=ComplianceSeverity.CRITICAL, review_priority=ReviewPriority.CO,
        )
        assert f.severity_score == 20
        assert f.is_critical

    def test_not_critical(self):
        f = TOCRFinding(
            finding_id="F-001", rule_id="TOCR-009", rule_title="T",
            severity=ComplianceSeverity.MEDIUM, review_priority=ReviewPriority.ADVISORY,
        )
        assert f.severity_score == 5
        assert not f.is_critical


class TestTaskOrder:
    def test_basic_task_order(self):
        to = TaskOrder(
            task_order_number="TO-001",
            revision_number="Rev 35",
            title="Test TO",
            sub_tasks=[
                SubTask(sub_task_id="ST-001", description="Test sub-task")
            ],
        )
        assert to.task_order_number == "TO-001"
        assert len(to.sub_tasks) == 1
        assert to.parser_confidence == ParserConfidence.HIGH
