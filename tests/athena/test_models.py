#!/usr/bin/env python3
"""
Module: Test Models
Purpose: Tests for athena.models module.

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

from __future__ import annotations

import pytest
from datetime import datetime
from uuid import UUID

from athena.models.enums import (
    DeploymentMode,
    DocumentStatus,
    RoutingDecision,
    EntityType,
    EntityLinkStatus,
    QualityIssue,
    BoundarySignal,
)
from athena.models.evidence import (
    BoundingBox,
    Evidence,
    ExtractedValue,
    EvidencePolicy,
)
from athena.models.document import (
    FieldSpec,
    EntityBag,
    ProcessingEvent,
    TriageResult,
    Document,
)


class TestEnums:
    """Tests for athena enumeration types."""

    def test_deployment_mode_values(self):
        """DeploymentMode has expected values."""
        assert DeploymentMode.CLOUD.value == "cloud"
        assert DeploymentMode.GOVCLOUD.value == "govcloud"
        assert DeploymentMode.ON_PREM.value == "on_prem"

    def test_document_status_values(self):
        """DocumentStatus has expected values."""
        assert DocumentStatus.PENDING.value == "pending"
        assert DocumentStatus.TRIAGED.value == "triaged"
        assert DocumentStatus.EXTRACTED.value == "extracted"
        assert DocumentStatus.FAILED.value == "failed"

    def test_routing_decision_values(self):
        """RoutingDecision has expected values."""
        assert RoutingDecision.EXTRACT_FULL.value == "extract_full"
        assert RoutingDecision.EXTRACT_LIGHT.value == "extract_light"
        assert RoutingDecision.MANUAL_REVIEW.value == "manual_review"
        assert RoutingDecision.RESCAN.value == "rescan"
        assert RoutingDecision.SKIP.value == "skip"

    def test_quality_issue_values(self):
        """QualityIssue has expected values."""
        assert QualityIssue.FADED.value == "faded"
        assert QualityIssue.BLURRY.value == "blurry"
        assert QualityIssue.HANDWRITTEN.value == "handwritten"

    def test_entity_type_values(self):
        """EntityType has expected values."""
        assert EntityType.PERSON.value == "person"
        assert EntityType.EQUIPMENT.value == "equipment"
        assert EntityType.MATERIAL.value == "material"


class TestBoundingBox:
    """Tests for BoundingBox model."""

    def test_create_valid_bbox(self):
        """BoundingBox can be created with valid coordinates."""
        bbox = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.8, y_max=0.9)
        assert bbox.x_min == 0.1
        assert bbox.y_min == 0.2
        assert bbox.x_max == 0.8
        assert bbox.y_max == 0.9

    def test_bbox_width_property(self):
        """BoundingBox.width calculates correctly."""
        bbox = BoundingBox(x_min=0.2, y_min=0.0, x_max=0.7, y_max=1.0)
        assert bbox.width == pytest.approx(0.5)

    def test_bbox_height_property(self):
        """BoundingBox.height calculates correctly."""
        bbox = BoundingBox(x_min=0.0, y_min=0.3, x_max=1.0, y_max=0.8)
        assert bbox.height == pytest.approx(0.5)

    def test_bbox_area_property(self):
        """BoundingBox.area calculates correctly."""
        bbox = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.5, y_max=0.5)
        assert bbox.area == pytest.approx(0.25)

    def test_bbox_contains_point_inside(self):
        """BoundingBox.contains returns True for point inside."""
        bbox = BoundingBox(x_min=0.2, y_min=0.2, x_max=0.8, y_max=0.8)
        assert bbox.contains(0.5, 0.5) is True

    def test_bbox_contains_point_outside(self):
        """BoundingBox.contains returns False for point outside."""
        bbox = BoundingBox(x_min=0.2, y_min=0.2, x_max=0.8, y_max=0.8)
        assert bbox.contains(0.1, 0.5) is False
        assert bbox.contains(0.5, 0.1) is False

    def test_bbox_contains_point_on_edge(self):
        """BoundingBox.contains returns True for point on edge."""
        bbox = BoundingBox(x_min=0.2, y_min=0.2, x_max=0.8, y_max=0.8)
        assert bbox.contains(0.2, 0.5) is True
        assert bbox.contains(0.8, 0.5) is True

    def test_bbox_overlaps_true(self):
        """BoundingBox.overlaps returns True for overlapping boxes."""
        bbox1 = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.5, y_max=0.5)
        bbox2 = BoundingBox(x_min=0.3, y_min=0.3, x_max=0.8, y_max=0.8)
        assert bbox1.overlaps(bbox2) is True
        assert bbox2.overlaps(bbox1) is True

    def test_bbox_overlaps_false(self):
        """BoundingBox.overlaps returns False for non-overlapping boxes."""
        bbox1 = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.3, y_max=0.3)
        bbox2 = BoundingBox(x_min=0.5, y_min=0.5, x_max=0.8, y_max=0.8)
        assert bbox1.overlaps(bbox2) is False

    def test_bbox_overlaps_adjacent(self):
        """BoundingBox.overlaps returns True for adjacent (touching) boxes."""
        bbox1 = BoundingBox(x_min=0.0, y_min=0.0, x_max=0.5, y_max=0.5)
        bbox2 = BoundingBox(x_min=0.5, y_min=0.0, x_max=1.0, y_max=0.5)
        # Adjacent boxes share an edge - implementation treats as overlap
        assert bbox1.overlaps(bbox2) is True

    def test_bbox_validation_min_max(self):
        """BoundingBox validates coordinate ranges."""
        with pytest.raises(ValueError):
            BoundingBox(x_min=-0.1, y_min=0.0, x_max=0.5, y_max=0.5)
        with pytest.raises(ValueError):
            BoundingBox(x_min=0.0, y_min=0.0, x_max=1.5, y_max=0.5)


class TestEvidence:
    """Tests for Evidence model."""

    def test_create_evidence(self):
        """Evidence can be created with required fields."""
        bbox = BoundingBox(x_min=0.1, y_min=0.1, x_max=0.9, y_max=0.9)
        evidence = Evidence(
            page=1,
            bbox=bbox,
            snippet_hash="abc123",
            confidence=0.95,
        )
        assert evidence.page == 1
        assert evidence.confidence == 0.95
        assert evidence.raw_text is None

    def test_evidence_with_all_fields(self):
        """Evidence can include optional fields."""
        bbox = BoundingBox(x_min=0.1, y_min=0.1, x_max=0.9, y_max=0.9)
        evidence = Evidence(
            page=2,
            bbox=bbox,
            snippet_hash="def456",
            snippet_path="/path/to/snippet.png",
            raw_text="Extracted text here",
            confidence=0.88,
        )
        assert evidence.snippet_path == "/path/to/snippet.png"
        assert evidence.raw_text == "Extracted text here"


class TestExtractedValue:
    """Tests for ExtractedValue model."""

    def test_create_extracted_value(self):
        """ExtractedValue can be created with required fields."""
        bbox = BoundingBox(x_min=0.1, y_min=0.1, x_max=0.9, y_max=0.9)
        evidence = Evidence(page=1, bbox=bbox, snippet_hash="abc", confidence=0.9)

        value = ExtractedValue(
            value="Inconel 718",
            value_type="string",
            evidence=evidence,
            confidence=0.92,
        )
        assert value.value == "Inconel 718"
        assert value.value_type == "string"
        assert value.validated is False

    def test_extracted_value_requires_evidence(self):
        """ExtractedValue cannot be created without evidence."""
        with pytest.raises(ValueError):
            ExtractedValue(
                value="Test",
                value_type="string",
                confidence=0.9,
                # Missing evidence - should fail
            )


class TestEntityBag:
    """Tests for EntityBag model."""

    def test_empty_entity_bag(self):
        """EntityBag can be created empty."""
        bag = EntityBag()
        assert bag.equipment == []
        assert bag.people == []
        assert bag.references == []

    def test_entity_bag_with_values(self):
        """EntityBag stores entity lists."""
        bag = EntityBag(
            equipment=["Pump A", "Valve B"],
            people=["John Doe"],
            references=["SN-12345"],
        )
        assert len(bag.equipment) == 2
        assert "Pump A" in bag.equipment


class TestProcessingEvent:
    """Tests for ProcessingEvent model."""

    def test_create_processing_event(self):
        """ProcessingEvent can be created with required fields."""
        event = ProcessingEvent(
            stage="triage",
            status="completed",
            duration_ms=1500,
        )
        assert event.stage == "triage"
        assert event.status == "completed"
        assert isinstance(event.event_id, UUID)
        assert isinstance(event.timestamp, datetime)

    def test_processing_event_defaults(self):
        """ProcessingEvent has correct defaults."""
        event = ProcessingEvent(stage="extract", status="started")
        assert event.tokens_used == 0
        assert event.cost_usd == 0.0
        assert event.error is None


class TestTriageResult:
    """Tests for TriageResult model."""

    def test_create_triage_result(self):
        """TriageResult can be created with required fields."""
        result = TriageResult(
            document_type="report",
            quality_score=0.85,
            confidence=0.92,
            routing=RoutingDecision.EXTRACT_FULL,
            routing_reason="Clear technical document",
            model_used="claude-3-5-haiku",
            tokens_in=1000,
            tokens_out=200,
            latency_ms=1500,
            cost_usd=0.005,
        )
        assert result.document_type == "report"
        assert result.routing == RoutingDecision.EXTRACT_FULL
        assert result.language == "en"  # default


class TestDocument:
    """Tests for Document model."""

    def test_create_document(self):
        """Document can be created with required fields."""
        doc = Document(
            tenant_id="tenant-123",
            batch_id="batch-456",
            source_file="test.pdf",
            source_path="/path/to/test.pdf",
            source_hash="sha256hash",
            page_range=(1, 10),
            page_count=10,
            pipeline_version="1.0.0",
        )
        assert doc.tenant_id == "tenant-123"
        assert doc.status == DocumentStatus.PENDING
        assert isinstance(doc.document_id, UUID)

    def test_document_defaults(self):
        """Document has correct defaults."""
        doc = Document(
            tenant_id="t1",
            batch_id="b1",
            source_file="f.pdf",
            source_path="/f.pdf",
            source_hash="hash",
            page_range=(1, 1),
            page_count=1,
            pipeline_version="1.0",
        )
        assert doc.triage_result is None
        assert doc.extraction_result is None
        assert doc.total_cost_usd == 0.0
        assert doc.processing_log == []
