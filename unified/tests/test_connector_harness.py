from __future__ import annotations

from pathlib import Path

from unified.harness.connector_gen import ConnectorHarnessGenerator


def test_connector_generator_writes_readonly_harness_and_contract_test(tmp_path: Path) -> None:
    paths = ConnectorHarnessGenerator().generate(tmp_path, module_name="demo_connector")
    harness = Path(paths["harness"]).read_text(encoding="utf-8")
    contract_test = Path(paths["contract_test"]).read_text(encoding="utf-8")

    assert 'execution_options={"readonly": True}' in harness
    assert "write_attempt_must_fail" in contract_test

