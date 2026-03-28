from __future__ import annotations

import pytest
from pydantic import ValidationError

from unified.canonical_store import CanonicalStore


def test_store_rejects_measurements_missing_mandatory_provenance_fields() -> None:
    store = CanonicalStore()
    with pytest.raises(ValidationError):
        store.insert_measurement(
            {
                "measurement_id": "m-1",
                "chunk_id": "chunk-1",
                "property_name": "density",
                "value": 1.23,
                "unit": "g/cm3",
                "provenance": {
                    "source_doc_id": "",
                    "extraction_confidence": 0.9,
                },
            }
        )

