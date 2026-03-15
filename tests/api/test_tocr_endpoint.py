import importlib.util
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


MODULE_PATH = Path(__file__).resolve().parents[2] / "mira" / "api" / "routers" / "tocr.py"
SPEC = importlib.util.spec_from_file_location("tocr_router_module", MODULE_PATH)
assert SPEC and SPEC.loader
tocr_router_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tocr_router_module)
tocr_router = tocr_router_module.router


app = FastAPI()
app.include_router(tocr_router, prefix="/tocr")
client = TestClient(app)


def _prior_revision() -> dict:
    return {
        "task_order_number": "NNM12AA41T",
        "revision_number": "Rev 34",
        "revision_status": "released",
        "title": "MAPTIS II Support",
        "task_order_description": "MAPTIS-II Development Support, TIMs, MUAs",
        "scope_text": "MAPTIS-II Development Support, TIMs, MUAs",
        "summary_of_changes": "Initial release.",
        "sub_tasks": [
            {
                "sub_task_id": "ST-001",
                "description": "MAPTIS database maintenance",
                "skills": ["database admin", "SQL"],
                "funding": 100000.0,
                "wbs_code": "WBS-001",
                "charge_code": "CC-001",
                "deliverables": ["Monthly status report"],
            }
        ],
        "funding_table": [{"sub_task_id": "ST-001", "amount": 100000.0}],
        "total_funding": 100000.0,
    }


def _proposed_revision() -> dict:
    return {
        "task_order_number": "NNM12AA41T",
        "revision_number": "Rev 35",
        "revision_status": "draft",
        "title": "MAPTIS II Support",
        "task_order_description": (
            "MAPTIS-II Development Support including development of Software Tools "
            "for integration of AI solutions."
        ),
        "scope_text": (
            "MAPTIS-II Development Support including development of Software Tools "
            "for integration of AI solutions."
        ),
        "summary_of_changes": "Updated revision number only.",
        "sub_tasks": [
            {
                "sub_task_id": "ST-001",
                "description": "MAPTIS database maintenance",
                "skills": ["database admin", "SQL"],
                "funding": 100000.0,
                "wbs_code": "WBS-001",
                "charge_code": "CC-001",
                "deliverables": ["Monthly status report"],
            }
        ],
        "funding_table": [{"sub_task_id": "ST-001", "amount": 100000.0}],
        "total_funding": 100000.0,
    }


def _noncompliant_scan_revision() -> dict:
    return {
        "task_order_number": "TO-BAD",
        "revision_number": "Rev 3",
        "revision_status": "draft",
        "title": "Problem Task Order",
        "task_order_description": (
            "Development of Software Tools for integration of AI solutions and "
            "machine learning pipelines."
        ),
        "scope_text": (
            "Development of Software Tools for integration of AI solutions and "
            "machine learning pipelines."
        ),
        "summary_of_changes": "",
        "sub_tasks": [
            {
                "sub_task_id": "ST-001",
                "description": "AI tools integration",
                "skills": [],
                "funding": 0,
                "deliverables": [],
            }
        ],
        "total_funding": 0,
        "quality_plan": {"text": "TBD"},
    }


def test_tocr_endpoints_are_mounted():
    response = client.get("/tocr/ping")
    assert response.status_code == 200
    assert response.json()["domain"] == "tocr"


def test_tocr_guidance_endpoint_returns_pack():
    response = client.get("/tocr/guidance")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pack_id"] == "tocr-guidance-v1"


def test_tocr_scan_endpoint_returns_findings():
    response = client.post(
        "/tocr/scan",
        data={
            "parser_hint": "auto",
            "agency": "NASA",
            "vehicle": "ESSCA",
            "local_policy_pack": "ESSCA-MSFC",
            "contract_types": "IDIQ,Task Order",
            "clauses_present": "FAR 52.232-22",
        },
        files={
            "source_file": (
                "task-order.json",
                json.dumps(_noncompliant_scan_revision()).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "scan"
    assert payload["report"]["report_id"].startswith("SCAN-")
    assert len(payload["report"]["findings"]) > 0


def test_tocr_review_endpoint_returns_report():
    response = client.post(
        "/tocr/review",
        data={
            "agency": "NASA",
            "vehicle": "ESSCA",
            "local_policy_pack": "ESSCA-MSFC",
            "contract_types": "IDIQ,Task Order",
            "clauses_present": "FAR 52.232-22",
        },
        files={
            "prior_file": (
                "prior.json",
                json.dumps(_prior_revision()).encode("utf-8"),
                "application/json",
            ),
            "proposed_file": (
                "proposed.json",
                json.dumps(_proposed_revision()).encode("utf-8"),
                "application/json",
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "review"
    assert payload["report"]["report_id"].startswith("TOCR-")
    assert payload["proposed_task_order"]["revision_number"] == "Rev 35"
    assert isinstance(payload["guidance"], dict)
