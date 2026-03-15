#!/usr/bin/env python3
"""Tests for TOCR document parsers."""

import json
import pytest

from sentinel.tocr.parsers.atoms_parser import ATOMSParser
from sentinel.tocr.models.enums import ParserConfidence, RevisionStatus


class TestATOMSParser:
    def _sample_atoms_json(self) -> dict:
        return {
            "task_order_number": "NNM12AA41T",
            "revision_number": "Rev 35",
            "revision_status": "released",
            "title": "ESSCA Task Order - MAPTIS II",
            "task_order_description": "MAPTIS-II Development Support, TIMs, MUAs",
            "scope_text": "MAPTIS-II Development Support, TIMs, MUAs",
            "summary_of_changes": "Added AI tools scope under ST-002.",
            "sub_tasks": [
                {
                    "sub_task_id": "ST-001",
                    "description": "MAPTIS database maintenance",
                    "skills": ["database admin", "SQL"],
                    "labor_categories": ["Software Engineer III"],
                    "funding": 100000.0,
                    "wbs_code": "WBS-001",
                    "charge_code": "CC-001",
                    "participating_team": ["Amentum"],
                    "deliverables": ["Monthly status report"],
                },
                {
                    "sub_task_id": "ST-002",
                    "description": "AI Tools Development",
                    "skills": ["software engineering", "AI", "machine learning"],
                    "labor_categories": ["Software Engineer IV", "Data Scientist"],
                    "funding": 250000.0,
                    "wbs_code": "WBS-002",
                    "charge_code": "CC-002",
                    "participating_team": ["Amentum", "BoundState"],
                    "deliverables": ["AI tools prototype", "Test report"],
                },
            ],
            "funding_table": [
                {"sub_task_id": "ST-001", "amount": 100000.0, "wbs_code": "WBS-001"},
                {"sub_task_id": "ST-002", "amount": 250000.0, "wbs_code": "WBS-002"},
            ],
            "total_funding": 350000.0,
            "quality_plan": {
                "text": "QMS per NASA-STD-8739.8B for software scope.",
                "qms_required": True,
                "software_scope": True,
                "safety_critical": False,
            },
            "emergency_designation": False,
            "emergency_justification": "",
            "agency_comments": "Approved for release.",
        }

    def test_parse_dict(self):
        parser = ATOMSParser()
        to = parser.parse(self._sample_atoms_json())

        assert to.task_order_number == "NNM12AA41T"
        assert to.revision_number == "Rev 35"
        assert to.revision_status == RevisionStatus.RELEASED
        assert to.parser_confidence == ParserConfidence.HIGH
        assert to.source_format == "atoms_json"
        assert len(to.sub_tasks) == 2
        assert to.sub_tasks[0].sub_task_id == "ST-001"
        assert to.sub_tasks[1].sub_task_id == "ST-002"
        assert to.sub_tasks[1].funding == 250000.0
        assert "AI" in to.sub_tasks[1].skills
        assert to.total_funding == 350000.0
        assert len(to.funding_table) == 2
        assert to.quality_plan is not None
        assert to.quality_plan.qms_required is True

    def test_parse_json_string(self):
        parser = ATOMSParser()
        json_str = json.dumps(self._sample_atoms_json())
        to = parser.parse(json_str)

        assert to.task_order_number == "NNM12AA41T"
        assert len(to.sub_tasks) == 2

    def test_parse_minimal(self):
        parser = ATOMSParser()
        to = parser.parse({
            "task_order_number": "TO-MINIMAL",
            "revision_number": "Rev 1",
        })

        assert to.task_order_number == "TO-MINIMAL"
        assert to.revision_number == "Rev 1"
        assert len(to.sub_tasks) == 0
        assert to.parser_confidence == ParserConfidence.HIGH

    def test_parse_with_missing_optional_fields(self):
        parser = ATOMSParser()
        to = parser.parse({
            "task_order_number": "TO-001",
            "revision_number": "Rev 1",
            "sub_tasks": [
                {"sub_task_id": "ST-001", "description": "Test task"},
            ],
        })

        assert len(to.sub_tasks) == 1
        assert to.sub_tasks[0].funding is None
        assert to.sub_tasks[0].skills == []
