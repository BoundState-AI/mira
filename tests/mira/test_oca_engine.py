from pathlib import Path
from unittest.mock import Mock

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


def test_titanium_gox_triggers_governing_prohibition() -> None:
    created = create_case(_base_request("Ti-6Al-4V"))
    precheck = get_case_precheck(created.case_id)
    decision = get_case_decision(created.case_id)

    mpr67 = next(item for item in precheck.triggered_requirements if item.requirement_id == "MPR_67")
    assert mpr67.triggered is True
    assert mpr67.status.value == "prohibited"
    assert decision.decision.final_disposition.value == "prohibited"
    assert "MPR 67" in (decision.decision.governing_prohibition or "")


def test_high_pressure_non_exempt_component_triggers_acceptance_test() -> None:
    created = create_case(_base_request("316L"))
    precheck = get_case_precheck(created.case_id)
    decision = get_case_decision(created.case_id)

    mpr53 = next(item for item in precheck.triggered_requirements if item.requirement_id == "MPR_53")
    assert mpr53.triggered is True
    assert mpr53.status.value == "action_required"
    assert decision.decision.final_disposition.value == "requires_acceptance_test"


def test_missing_service_context_sets_blocked_state() -> None:
    request = _base_request("316L")
    request.service_context.total_pressure_max_psia = None
    request.service_context.phase = None

    created = create_case(request)

    blocked_codes = {item.code.value for item in created.blocked_states}
    assert "SERVICE_ENVELOPE_INCOMPLETE" in blocked_codes


def test_oca_case_store_persists_across_store_instances(tmp_path: Path) -> None:
    from mira.oca.engine import _build_snapshot
    from mira.oca.store import FileOcaCaseStore

    snapshot = _build_snapshot("oca-test-file", _base_request("316L"), 1)
    store_a = FileOcaCaseStore(tmp_path)
    store_a.save(snapshot)

    store_b = FileOcaCaseStore(tmp_path)
    reloaded = store_b.get(snapshot.case_id)

    assert reloaded.case_id == snapshot.case_id
    assert reloaded.decision.final_disposition == snapshot.decision.final_disposition


def test_oca_case_store_round_trips_through_dynamodb_payload_encoding() -> None:
    from mira.oca.engine import _build_snapshot
    from mira.oca.store import DynamoDbOcaCaseStore

    snapshot = _build_snapshot("oca-test-ddb", _base_request("316L"), 1)
    client = Mock()
    client.get_item.return_value = {
        "Item": {
            "case_id": {"S": snapshot.case_id},
            "payload": {"S": DynamoDbOcaCaseStore._encode_payload(snapshot)},
            "payload_encoding": {"S": "gzip+base64"},
        }
    }

    store = DynamoDbOcaCaseStore(table_name="mira-test-oca", client=client)
    store.save(snapshot)
    reloaded = store.get(snapshot.case_id)

    client.put_item.assert_called_once()
    client.get_item.assert_called_once()
    assert reloaded.case_id == snapshot.case_id
    assert reloaded.revision == snapshot.revision
