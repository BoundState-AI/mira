from __future__ import annotations

from pathlib import Path


class ConnectorHarnessGenerator:
    def generate(self, output_dir: str | Path, module_name: str = "ic_connector") -> dict[str, str]:
        output_path = Path(output_dir)
        pending = output_path / "pending"
        active = output_path / "active"
        pending.mkdir(parents=True, exist_ok=True)
        active.mkdir(parents=True, exist_ok=True)

        harness_path = pending / f"{module_name}.py"
        test_path = pending / f"test_{module_name}.py"

        harness_code = f'''from __future__ import annotations

from sqlalchemy import create_engine, event


def build_engine(db_url: str, allowed_hosts: set[str] | None = None):
    engine = create_engine(db_url, execution_options={{"readonly": True}})

    @event.listens_for(engine, "engine_connect")
    def _enforce_host(connection):
        if allowed_hosts is None:
            return
        host = connection.engine.url.host or "localhost"
        if host not in allowed_hosts:
            raise PermissionError(f"Host {{host}} is not whitelisted")

    return engine
'''

        test_code = f'''from __future__ import annotations

import pytest

from {module_name} import build_engine


def test_write_attempt_must_fail():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as connection:
        with pytest.raises(Exception):
            connection.exec_driver_sql("CREATE TABLE forbidden (id INTEGER)")
'''

        harness_path.write_text(harness_code, encoding="utf-8")
        test_path.write_text(test_code, encoding="utf-8")
        return {"harness": str(harness_path), "contract_test": str(test_path)}

