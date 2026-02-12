#!/usr/bin/env python3
"""
Test Module: MIRA v4 Domain Scope Gate
Purpose: Verify intelligent out-of-scope bouncer behavior.
"""

import sys
sys.path.insert(0, r"C:\BoundState")

import asyncio
import pytest

from mira.api.routers import mira_v4 as v4_router


class TestDomainScopeHelpers:
    def test_normalize_domain_scope(self):
        assert v4_router._normalize_domain_scope("in_scope") == "in_scope"
        assert v4_router._normalize_domain_scope("OUT_OF_SCOPE") == "out_of_scope"
        assert v4_router._normalize_domain_scope("uncertain") == "uncertain"
        assert v4_router._normalize_domain_scope("weird_label") == "uncertain"
        assert v4_router._normalize_domain_scope(None) == "uncertain"

    def test_is_out_of_scope(self):
        assert v4_router._is_out_of_scope({"domain_scope": "out_of_scope"}) is True
        assert v4_router._is_out_of_scope({"domain_scope": "in_scope"}) is False
        assert v4_router._is_out_of_scope({}) is False


class TestOutOfScopeShortCircuit:
    def test_query_v4_short_circuits_on_out_of_scope(self, monkeypatch):
        async def _fake_parse(_: str):
            return {
                "intent": "general_search",
                "safety_context": "general",
                "domain_scope": "out_of_scope",
                "scope_reason": "Prompt is not related to materials and processes.",
                "material_key": None,
                "candidate_materials": [],
                "material_families": [],
                "material_type": None,
                "environment": {},
                "filters": {},
            }

        monkeypatch.setattr(v4_router, "_parse_query_with_sonnet", _fake_parse)

        request = v4_router.V4QueryRequest(
            query="how much wood would a woodchuck chuck if a woodchuck could chuck wood?"
        )
        response = asyncio.run(v4_router.query_v4(request))

        assert response.search_source == "out_of_scope"
        assert response.materials == []
        assert response.all_materials == []
        assert response.all_material_count == 0
        assert response.materials_focus_applied is False
        assert response.material_families == []
        assert response.parsed_query["intent"] == "out_of_scope"
        assert response.parsed_query["filters"]["domain_scope"] == "out_of_scope"
        assert "Out of Scope" in response.answer


class TestAnswerScopeAnchoring:
    def test_select_answer_materials_for_focus_anchors_on_requested_alloy(self):
        materials = [
            {"designation": "MONEL 400 PLATE ANNEALED", "total_tests": 30},
            {"designation": "INCONEL 718 BAR AGED", "total_tests": 29},
            {"designation": "AL 6061-T6 BRAZED WITH INCONEL 718 FILLER", "total_tests": 5},
            {"designation": "INCONEL 625 BAR ANNEALED", "total_tests": 20},
            {"designation": "INCONEL 718 AS CAST", "total_tests": 1},
        ]

        selected = v4_router._select_answer_materials_for_focus(
            materials, "Inconel 718"
        )

        assert len(selected) == 2
        assert all("718" in m["designation"] for m in selected)
        assert all(m["designation"].lower().startswith("inconel 718") for m in selected)

    def test_select_answer_materials_for_focus_falls_back_when_no_match(self):
        materials = [
            {"designation": "MONEL 400 PLATE ANNEALED", "total_tests": 30},
            {"designation": "CRES 316L BAR ANNEALED", "total_tests": 10},
        ]

        selected = v4_router._select_answer_materials_for_focus(
            materials, "Inconel 718"
        )

        assert selected == materials
