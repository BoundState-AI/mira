#!/usr/bin/env python3
"""
Module: Test Test Classes Endpoint
Purpose: Tests for Test Classes page API endpoints.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013
Safety Critical: True
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client for API."""
    from mira.api.app import app
    return TestClient(app)


class TestTestClassesCounts:
    """Tests for /api/test-classes/counts endpoint."""

    def test_counts_returns_dict(self, client):
        """Counts endpoint returns dictionary of test types."""
        response = client.get("/api/test-classes/counts")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_counts_has_flammability(self, client):
        """Counts include flammability test type."""
        response = client.get("/api/test-classes/counts")
        assert response.status_code == 200
        data = response.json()
        assert "flammability" in data
        assert isinstance(data["flammability"], int)
        assert data["flammability"] > 0

    def test_counts_has_tvs_outgassing(self, client):
        """Counts include TVS outgassing test type."""
        response = client.get("/api/test-classes/counts")
        data = response.json()
        assert "tvs-outgassing" in data
        assert data["tvs-outgassing"] > 0

    def test_counts_all_test_types_present(self, client):
        """All expected test types are present in counts."""
        expected_types = [
            "flammability", "tvs-outgassing", "toxicity", "corrosion",
            "mechanical-impact", "stress-corrosion-cracking"
        ]
        response = client.get("/api/test-classes/counts")
        data = response.json()
        for test_type in expected_types:
            assert test_type in data, f"Missing test type: {test_type}"


class TestTestRecords:
    """Tests for /api/test-records/{test_type} endpoint."""

    def test_get_flammability_records(self, client):
        """Get flammability records returns paginated data."""
        response = client.get("/api/test-records/flammability?page=1&per_page=10")
        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "pagination" in data
        assert isinstance(data["records"], list)

    def test_pagination_fields_present(self, client):
        """Pagination response has required fields."""
        response = client.get("/api/test-records/flammability?page=1&per_page=10")
        data = response.json()
        pagination = data["pagination"]
        assert "page" in pagination
        assert "per_page" in pagination
        assert "total_records" in pagination
        assert "total_pages" in pagination

    def test_record_has_material_fields(self, client):
        """Test records include material information."""
        response = client.get("/api/test-records/flammability?page=1&per_page=1")
        data = response.json()
        if data["records"]:
            record = data["records"][0]
            assert "material_key" in record or "material_code" in record
            assert "material_designation" in record

    def test_unknown_test_type_returns_404(self, client):
        """Unknown test type returns 404."""
        response = client.get("/api/test-records/nonexistent-test")
        assert response.status_code == 404

    def test_rating_filter(self, client):
        """Rating filter parameter works."""
        response = client.get("/api/test-records/flammability?page=1&per_page=50&rating=A")
        assert response.status_code == 200
        data = response.json()
        # All records should have rating A (if any returned)
        for record in data["records"]:
            if record.get("rating"):
                assert record["rating"] == "A"

    def test_search_filter(self, client):
        """Search filter parameter works."""
        response = client.get("/api/test-records/flammability?page=1&per_page=10&search=steel")
        assert response.status_code == 200


class TestTestRecordRatings:
    """Tests for /api/test-records/{test_type}/ratings endpoint."""

    def test_get_ratings_list(self, client):
        """Ratings endpoint returns list of available ratings."""
        response = client.get("/api/test-records/flammability/ratings")
        assert response.status_code == 200
        data = response.json()
        assert "ratings" in data
        assert isinstance(data["ratings"], list)

    def test_ratings_not_empty(self, client):
        """Ratings list is not empty for flammability."""
        response = client.get("/api/test-records/flammability/ratings")
        data = response.json()
        assert len(data["ratings"]) > 0


class TestTestRecordExport:
    """Tests for /api/test-records/{test_type}/export endpoint."""

    def test_export_returns_csv(self, client):
        """Export endpoint returns CSV content."""
        response = client.get("/api/test-records/flammability/export")
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    def test_export_has_content_disposition(self, client):
        """Export response has download filename."""
        response = client.get("/api/test-records/flammability/export")
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]


__safety_critical__ = True
