from pathlib import Path
from unittest.mock import Mock

from mira.oca.system_models import OCASystemAssembly
from mira.oca.system_store import DynamoDbOcaSystemStore, FileOcaSystemStore


def test_oca_system_store_persists_across_file_store_instances(tmp_path: Path) -> None:
    system = OCASystemAssembly(name="Test System")
    store_a = FileOcaSystemStore(tmp_path)
    store_a.save(system)

    store_b = FileOcaSystemStore(tmp_path)
    reloaded = store_b.get(system.system_id)

    assert reloaded.system_id == system.system_id
    assert reloaded.name == "Test System"


def test_oca_system_store_round_trips_through_dynamodb_payload_encoding() -> None:
    system = OCASystemAssembly(name="DDB System")
    client = Mock()
    client.get_item.return_value = {
        "Item": {
            "system_id": {"S": system.system_id},
            "payload": {"S": DynamoDbOcaSystemStore._encode_payload(system)},
            "payload_encoding": {"S": "gzip+base64"},
        }
    }

    store = DynamoDbOcaSystemStore(table_name="mira-test-oca-systems", client=client)
    store.save(system)
    reloaded = store.get(system.system_id)

    client.put_item.assert_called_once()
    client.get_item.assert_called_once()
    assert reloaded.system_id == system.system_id
    assert reloaded.name == system.name
