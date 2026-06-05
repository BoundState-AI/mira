"""
Tests for the AM chat adapter registration and input gate.
BoundState AI 2026
"""

from __future__ import annotations

import json
import asyncio
from pathlib import Path

from mira.chat.adapters.am_adapter import AMAdapter
from mira.chat.models import Status


def test_am_adapter_missing_inputs_do_not_require_powder_dependency() -> None:
    envelope = asyncio.run(AMAdapter().execute({}, {}))

    assert envelope.status == Status.INSUFFICIENT_DATA
    assert "intended_class" in envelope.missing_inputs
    assert "consequence_of_failure" in envelope.missing_inputs
    assert "hazard_context" in envelope.missing_inputs
    assert "safety_critical_confirmed" in envelope.missing_inputs


def test_am_manifest_registers_adapter() -> None:
    manifest = json.loads(
        Path("mira/chat/manifests/am.json").read_text(encoding="utf-8")
    )

    assert manifest["engine_id"] == "am_knowledge_twin"
    assert manifest["adapter_module"] == "mira.chat.adapters.am_adapter"
    assert manifest["adapter_class"] == "AMAdapter"
    assert "safety_critical_confirmed" in manifest["required_inputs"]
