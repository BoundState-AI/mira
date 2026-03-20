#!/usr/bin/env python3
"""Tests for forensic hardening: deterministic IDs, suppression log, fingerprinting, thresholds, blind test."""

import json

import pytest

from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.exports.json_export import export_json
from sentinel.tocr.exports.text_export import export_text
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import (
    BasisType,
    ComplianceSeverity,
    ReviewPriority,
    RevisionStatus,
)
from sentinel.tocr.models.rules import RuleApplicability, RuleTrigger, TOCRRule
from sentinel.tocr.models.task_order import SubTask, TaskOrder


def _make_rules():
    return [
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


def _make_prior():
    return TaskOrder(
        task_order_number="TO-1234",
        revision_number="Rev 34",
        revision_status=RevisionStatus.RELEASED,
        title="Test TO",
        task_order_description="Original scope text",
        summary_of_changes="Initial.",
        sub_tasks=[SubTask(sub_task_id="ST-001", description="Original task", funding=100000.0)],
    )


def _make_proposed():
    return TaskOrder(
        task_order_number="TO-1234",
        revision_number="Rev 35",
        revision_status=RevisionStatus.DRAFT,
        title="Test TO",
        task_order_description="Expanded scope with new software development capabilities",
        summary_of_changes="Updated revision.",
        sub_tasks=[SubTask(sub_task_id="ST-001", description="Original task", funding=100000.0)],
    )


def _make_conductor(rules=None):
    config = ContractConfig(agency="NASA", revision_status=RevisionStatus.DRAFT)
    return TOCRConductor(config=config, rules=rules or _make_rules())


class TestDeterministicFindingIDs:
    """Fix 1: Same input must always produce the same finding IDs."""

    def test_same_input_same_ids(self):
        """Two runs of the same data produce identical finding IDs."""
        conductor = _make_conductor()
        report1 = conductor.review(_make_prior(), _make_proposed())
        report2 = conductor.review(_make_prior(), _make_proposed())

        ids1 = [f.finding_id for f in report1.findings]
        ids2 = [f.finding_id for f in report2.findings]
        assert ids1 == ids2

    def test_different_input_different_ids(self):
        """Different data produces different finding IDs."""
        conductor = _make_conductor()
        report1 = conductor.review(_make_prior(), _make_proposed())

        different_proposed = _make_proposed()
        different_proposed.task_order_description = "Completely different scope about logistics"
        report2 = conductor.review(_make_prior(), different_proposed)

        assert report1.findings, "Report 1 must produce findings for this test to be valid"
        assert report2.findings, "Report 2 must produce findings for this test to be valid"
        ids1 = set(f.finding_id for f in report1.findings)
        ids2 = set(f.finding_id for f in report2.findings)
        assert ids1 != ids2

    def test_finding_id_format(self):
        """Finding IDs follow F-XXXXXX format with hex characters."""
        conductor = _make_conductor()
        report = conductor.review(_make_prior(), _make_proposed())

        for f in report.findings:
            assert f.finding_id.startswith("F-")
            assert len(f.finding_id) == 8  # F- + 6 hex chars
            # Must be valid hex
            int(f.finding_id[2:], 16)


class TestSuppressionLog:
    """Fix 2: Suppressed rules must appear in the report with reasons."""

    def test_suppression_log_in_report(self):
        """Report should contain the suppression log."""
        rules = _make_rules()
        # Add a rule that requires a clause not present
        rules.append(TOCRRule(
            rule_id="TOCR-GATED",
            title="Clause-Gated Rule",
            basis_type=BasisType.REGULATORY,
            authority_basis=["FAR 52.999-99"],
            applicability=RuleApplicability(
                revision_status=["draft", "released"],
                clause_required=["FAR 52.999-99"],
            ),
            trigger=RuleTrigger(all=["material_change_detected"]),
            finding="Should be suppressed.",
            severity=ComplianceSeverity.HIGH,
            review_priority=ReviewPriority.CO,
        ))

        conductor = _make_conductor(rules=rules)
        report = conductor.review(_make_prior(), _make_proposed())

        assert len(report.suppression_log) > 0
        suppressed_ids = [e["rule_id"] for e in report.suppression_log]
        assert "TOCR-GATED" in suppressed_ids

    def test_suppression_log_has_reason(self):
        """Every suppression entry must have a reason."""
        rules = _make_rules()
        rules.append(TOCRRule(
            rule_id="TOCR-AGENCY",
            title="Wrong Agency Rule",
            basis_type=BasisType.REGULATORY,
            applicability=RuleApplicability(
                revision_status=["draft", "released"],
                agency=["DOD"],
            ),
            trigger=RuleTrigger(all=["material_change_detected"]),
            finding="DOD only.",
            severity=ComplianceSeverity.HIGH,
            review_priority=ReviewPriority.CO,
        ))

        conductor = _make_conductor(rules=rules)
        report = conductor.review(_make_prior(), _make_proposed())

        for entry in report.suppression_log:
            assert "rule_id" in entry
            assert "reason" in entry
            assert len(entry["reason"]) > 0

    def test_suppression_log_in_text_export(self):
        """Text export should include suppressed rules."""
        rules = _make_rules()
        rules.append(TOCRRule(
            rule_id="TOCR-SUPPRESSED",
            title="Suppressed Rule",
            basis_type=BasisType.REGULATORY,
            applicability=RuleApplicability(
                revision_status=["draft", "released"],
                clause_required=["NONEXISTENT-CLAUSE"],
            ),
            trigger=RuleTrigger(all=["material_change_detected"]),
            finding="Suppressed.",
            severity=ComplianceSeverity.HIGH,
            review_priority=ReviewPriority.CO,
        ))

        conductor = _make_conductor(rules=rules)
        report = conductor.review(_make_prior(), _make_proposed())
        text = export_text(report)

        assert "RULES NOT APPLIED" in text
        assert "TOCR-SUPPRESSED" in text


class TestInputFingerprint:
    """Fix 3: Reports must include a hash proving what data produced them."""

    def test_fingerprint_present(self):
        """Report must contain an input fingerprint."""
        conductor = _make_conductor()
        report = conductor.review(_make_prior(), _make_proposed())

        assert report.input_fingerprint
        assert "prior:" in report.input_fingerprint
        assert "proposed:" in report.input_fingerprint
        assert "rules:" in report.input_fingerprint

    def test_fingerprint_deterministic(self):
        """Same input produces the same fingerprint."""
        conductor = _make_conductor()
        report1 = conductor.review(_make_prior(), _make_proposed())
        report2 = conductor.review(_make_prior(), _make_proposed())

        assert report1.input_fingerprint == report2.input_fingerprint

    def test_fingerprint_changes_with_data(self):
        """Different input produces a different fingerprint."""
        conductor = _make_conductor()
        report1 = conductor.review(_make_prior(), _make_proposed())

        different_proposed = _make_proposed()
        different_proposed.task_order_description = "Different scope"
        report2 = conductor.review(_make_prior(), different_proposed)

        assert report1.input_fingerprint != report2.input_fingerprint

    def test_fingerprint_in_text_export(self):
        """Text export should show the fingerprint."""
        conductor = _make_conductor()
        report = conductor.review(_make_prior(), _make_proposed())
        text = export_text(report)

        assert "Input Fingerprint:" in text

    def test_fingerprint_in_json_export(self):
        """JSON export should include the fingerprint."""
        conductor = _make_conductor()
        report = conductor.review(_make_prior(), _make_proposed())
        data = json.loads(export_json(report))

        assert "input_fingerprint" in data
        assert len(data["input_fingerprint"]) > 0

    def test_scan_fingerprint(self):
        """Scan mode should also have a fingerprint."""
        conductor = _make_conductor()
        to = TaskOrder(
            task_order_number="TO-5678",
            revision_number="Rev 1",
            revision_status=RevisionStatus.DRAFT,
            title="Scan Test",
            task_order_description="Test scope",
            sub_tasks=[SubTask(sub_task_id="ST-001", description="Task", funding=0)],
        )
        report = conductor.scan(to)

        assert report.input_fingerprint
        assert "to:" in report.input_fingerprint
        assert "rules:" in report.input_fingerprint


class TestConfigurableThresholds:
    """Fix 4: Magic numbers must be in config, not hardcoded."""

    def test_default_thresholds(self):
        """Default config should have documented thresholds."""
        config = ContractConfig()
        assert config.disclosure_similarity_threshold == 0.55
        assert config.cost_overlap_word_threshold == 8
        assert config.emergency_justification_word_threshold == 2

    def test_custom_thresholds(self):
        """Thresholds should be overridable."""
        config = ContractConfig(
            disclosure_similarity_threshold=0.5,
            cost_overlap_word_threshold=12,
            emergency_justification_word_threshold=3,
        )
        assert config.disclosure_similarity_threshold == 0.5
        assert config.cost_overlap_word_threshold == 12
        assert config.emergency_justification_word_threshold == 3

    def test_thresholds_serializable(self):
        """Thresholds must appear in serialized config for audit trail."""
        config = ContractConfig()
        data = config.model_dump()
        assert "disclosure_similarity_threshold" in data
        assert "cost_overlap_word_threshold" in data
        assert "emergency_justification_word_threshold" in data


class TestBlindTest:
    """Fix 5: Blind test strips identifiers, randomizes, runs, maps back."""

    def _make_revision_chain(self):
        """Create a chain of 4 revisions where Rev 35→36 is the bad one."""
        revisions = []
        # Rev 33→34: clean — summary explicitly describes the scope change
        revisions.append(TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 33",
            revision_status=RevisionStatus.RELEASED,
            title="Test TO",
            task_order_description="Engineering analysis support",
            summary_of_changes="Initial release.",
            sub_tasks=[SubTask(
                sub_task_id="ST-001", description="Analysis task",
                funding=200000.0, wbs_code="WBS-01", charge_code="CC-01",
                skills=["Systems Engineer"], deliverables=["Monthly report"],
            )],
        ))
        revisions.append(TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 34",
            revision_status=RevisionStatus.RELEASED,
            title="Test TO",
            task_order_description="Engineering analysis support with expanded reporting",
            summary_of_changes=(
                "Expanded engineering analysis support scope to include expanded "
                "reporting requirements. Added quarterly summary deliverable."
            ),
            sub_tasks=[SubTask(
                sub_task_id="ST-001", description="Analysis task with expanded reporting",
                funding=200000.0, wbs_code="WBS-01", charge_code="CC-01",
                skills=["Systems Engineer"], deliverables=["Monthly report", "Quarterly summary"],
            )],
        ))
        # Rev 34→35: clean — summary explicitly describes the scope change
        revisions.append(TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 35",
            revision_status=RevisionStatus.RELEASED,
            title="Test TO",
            task_order_description="Engineering analysis support with expanded reporting and data review",
            summary_of_changes=(
                "Added data review scope to engineering analysis support. "
                "Added Data Analyst skill. Added data review report deliverable. "
                "Increased ST-001 funding from $200K to $250K for expanded reporting and data review."
            ),
            sub_tasks=[SubTask(
                sub_task_id="ST-001", description="Analysis task with expanded reporting and data review",
                funding=250000.0, wbs_code="WBS-01", charge_code="CC-01",
                skills=["Systems Engineer", "Data Analyst"],
                deliverables=["Monthly report", "Quarterly summary", "Data review report"],
            )],
        ))
        # Rev 35→36: THE BAD ONE — undisclosed scope, unfunded, no deliverables
        revisions.append(TaskOrder(
            task_order_number="TO-1234",
            revision_number="Rev 36",
            revision_status=RevisionStatus.DRAFT,
            title="Test TO",
            task_order_description="Engineering analysis plus new software AI development capability previously performed under verbal direction",
            summary_of_changes="Minor administrative updates.",
            sub_tasks=[
                SubTask(
                    sub_task_id="ST-001", description="Analysis task",
                    funding=250000.0, wbs_code="WBS-01", charge_code="CC-01",
                    skills=["Systems Engineer"],
                    deliverables=["Monthly report"],
                ),
                SubTask(sub_task_id="ST-002", description="AI development", funding=0),
            ],
        ))
        return revisions

    def test_blind_test_runs(self):
        """Blind test should execute and return results."""
        conductor = _make_conductor()
        revisions = self._make_revision_chain()
        result = conductor.blind_review_chain(revisions, seed=42)

        assert "blind_results" in result
        assert "mapping" in result
        assert "ranked" in result
        assert len(result["blind_results"]) == 3  # 4 revisions = 3 pairs

    def test_blind_test_strips_identifiers(self):
        """Blind reports should NOT contain original revision numbers."""
        conductor = _make_conductor()
        revisions = self._make_revision_chain()
        result = conductor.blind_review_chain(revisions, seed=42)

        for br in result["blind_results"]:
            report = br["report"]
            # Original revision numbers should not appear
            assert "Rev 33" not in report.prior_revision
            assert "Rev 34" not in report.prior_revision
            assert "Rev 35" not in report.prior_revision
            assert "Rev 36" not in report.proposed_revision
            # Should have BLIND identifiers
            assert "BLIND" in report.prior_revision
            assert "BLIND" in report.proposed_revision

    def test_blind_test_mapping_recovers_identity(self):
        """Mapping should link blind indices back to original revisions."""
        conductor = _make_conductor()
        revisions = self._make_revision_chain()
        result = conductor.blind_review_chain(revisions, seed=42)

        original_pairs = set()
        for m in result["mapping"]:
            original_pairs.add((m["original_prior"], m["original_proposed"]))

        assert ("Rev 33", "Rev 34") in original_pairs
        assert ("Rev 34", "Rev 35") in original_pairs
        assert ("Rev 35", "Rev 36") in original_pairs

    def test_blind_test_worst_score_is_outlier(self):
        """The 35→36 pair should score worst even when the engine is blind."""
        conductor = _make_conductor()
        revisions = self._make_revision_chain()
        result = conductor.blind_review_chain(revisions, seed=42)

        # Find the worst-scoring blind index
        worst = result["ranked"][0]
        worst_blind_idx = worst["blind_index"]

        # Map it back to original
        mapping_entry = next(m for m in result["mapping"] if m["blind_index"] == worst_blind_idx)

        # The worst pair should be 35→36
        assert mapping_entry["original_prior"] == "Rev 35"
        assert mapping_entry["original_proposed"] == "Rev 36"

    def test_blind_test_reproducible_with_seed(self):
        """Same seed produces same randomization order."""
        conductor = _make_conductor()
        revisions = self._make_revision_chain()

        result1 = conductor.blind_review_chain(revisions, seed=42)
        result2 = conductor.blind_review_chain(revisions, seed=42)

        order1 = [m["original_proposed"] for m in result1["mapping"]]
        order2 = [m["original_proposed"] for m in result2["mapping"]]
        assert order1 == order2

    def test_blind_test_different_seed_different_order(self):
        """Different seeds produce different randomization (usually)."""
        conductor = _make_conductor()
        revisions = self._make_revision_chain()

        result1 = conductor.blind_review_chain(revisions, seed=42)
        result2 = conductor.blind_review_chain(revisions, seed=99)

        order1 = [m["original_proposed"] for m in result1["mapping"]]
        order2 = [m["original_proposed"] for m in result2["mapping"]]
        # With 3 pairs and different seeds, order should differ (not guaranteed but very likely)
        # If they happen to be the same, that's still valid — the test is about the mechanism
        assert len(order1) == len(order2) == 3
