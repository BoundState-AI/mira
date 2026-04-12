import pytest

from mira.core.session_store import reset_session_store
from mira.oca.engine import create_case, get_case_decision, get_case_precheck
from mira.oca.models import CreateOcaCaseRequest


def _base_request(material_name: str = "316L") -> CreateOcaCaseRequest:
    return CreateOcaCaseRequest(
        service_context={
            "oxidizer_type": "gox",
            "o2_fraction": 1.0,
            "total_pressure_min_psia": 14.7,
            "total_pressure_max_psia": 500.0,
            "phase": "gas",
            "temp_min_c": 20.0,
            "temp_max_c": 25.0,
            "velocity_m_s": 12.0,
            "cleanliness_verified": True,
        },
        materials=[{"material_name": material_name, "product_form": "bar"}],
        components=[
            {
                "component_id": "cmp-1",
                "component_class": "valve",
                "geometry_class": "bulk",
                "design_function": "pressure control",
                "seal_type": "polymer",
            }
        ],
    )


@pytest.fixture(autouse=True)
def _reset_session_store_fixture():
    reset_session_store()
    yield
    reset_session_store()


@pytest.mark.anyio
async def test_titanium_gox_triggers_governing_prohibition() -> None:
    created = await create_case(_base_request("Ti-6Al-4V"))
    precheck = await get_case_precheck(created.case_id)
    decision = await get_case_decision(created.case_id)

    mpr67 = next(item for item in precheck.triggered_requirements if item.requirement_id == "MPR_67")
    assert mpr67.triggered is True
    assert mpr67.status.value == "prohibited"
    assert decision.decision.final_disposition.value == "prohibited"
    assert "MPR 67" in (decision.decision.governing_prohibition or "")


@pytest.mark.anyio
async def test_high_pressure_non_exempt_component_triggers_acceptance_test() -> None:
    created = await create_case(_base_request("316L"))
    precheck = await get_case_precheck(created.case_id)
    decision = await get_case_decision(created.case_id)

    mpr53 = next(item for item in precheck.triggered_requirements if item.requirement_id == "MPR_53")
    assert mpr53.triggered is True
    assert mpr53.status.value == "action_required"
    assert decision.decision.final_disposition.value == "requires_acceptance_test"


@pytest.mark.anyio
async def test_missing_service_context_sets_blocked_state() -> None:
    request = _base_request("316L")
    request.service_context.total_pressure_max_psia = None
    request.service_context.phase = None

    created = await create_case(request)

    blocked_codes = {item.code.value for item in created.blocked_states}
    assert "SERVICE_ENVELOPE_INCOMPLETE" in blocked_codes
