"""Shared storage backends for OCA system-builder assemblies."""

from __future__ import annotations

import base64
import gzip
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .system_models import OCASystemAssembly


class OcaSystemStore(Protocol):
    def save(self, system: OCASystemAssembly) -> None:
        ...

    def get(self, system_id: str) -> OCASystemAssembly:
        ...

    def delete(self, system_id: str) -> None:
        ...


class FileOcaSystemStore:
    def __init__(self, storage_dir: Path | None = None) -> None:
        default_dir = Path(tempfile.gettempdir()) / "mira_oca_systems"
        self._storage_dir = Path(
            os.getenv("MIRA_OCA_SYSTEM_STORE_DIR", str(storage_dir or default_dir))
        ).expanduser()
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, system_id: str) -> Path:
        return self._storage_dir / f"{system_id}.json"

    def save(self, system: OCASystemAssembly) -> None:
        path = self._path_for(system.system_id)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(system.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def get(self, system_id: str) -> OCASystemAssembly:
        path = self._path_for(system_id)
        if not path.exists():
            raise KeyError(system_id)
        return OCASystemAssembly.model_validate_json(path.read_text(encoding="utf-8"))

    def delete(self, system_id: str) -> None:
        path = self._path_for(system_id)
        if not path.exists():
            raise KeyError(system_id)
        path.unlink()


class DynamoDbOcaSystemStore:
    def __init__(
        self,
        table_name: str,
        *,
        region_name: str | None = None,
        ttl_hours: int = 168,
        client=None,
    ) -> None:
        self._table_name = table_name
        self._ttl_seconds = max(1, ttl_hours) * 3600
        self._client = client or boto3.client(
            "dynamodb",
            region_name=region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        )

    @staticmethod
    def _encode_payload(system: OCASystemAssembly) -> str:
        raw = system.model_dump_json().encode("utf-8")
        compressed = gzip.compress(raw, compresslevel=6)
        return base64.b64encode(compressed).decode("ascii")

    @staticmethod
    def _decode_payload(payload: str) -> OCASystemAssembly:
        compressed = base64.b64decode(payload.encode("ascii"))
        raw = gzip.decompress(compressed).decode("utf-8")
        return OCASystemAssembly.model_validate_json(raw)

    def save(self, system: OCASystemAssembly) -> None:
        expires_at = int(time.time()) + self._ttl_seconds
        try:
            self._client.put_item(
                TableName=self._table_name,
                Item={
                    "system_id": {"S": system.system_id},
                    "payload": {"S": self._encode_payload(system)},
                    "payload_encoding": {"S": "gzip+base64"},
                    "owner_username": {"S": system.owner_username or ""},
                    "updated_at": {"S": system.updated_at.isoformat()},
                    "expires_at": {"N": str(expires_at)},
                },
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to save OCA system {system.system_id}: {exc}") from exc

    def get(self, system_id: str) -> OCASystemAssembly:
        try:
            response = self._client.get_item(
                TableName=self._table_name,
                Key={"system_id": {"S": system_id}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to load OCA system {system_id}: {exc}") from exc

        item = response.get("Item")
        if not item:
            raise KeyError(system_id)

        payload = item.get("payload", {}).get("S")
        if not payload:
            raise KeyError(system_id)
        return self._decode_payload(payload)

    def delete(self, system_id: str) -> None:
        try:
            self._client.delete_item(
                TableName=self._table_name,
                Key={"system_id": {"S": system_id}},
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to delete OCA system {system_id}: {exc}") from exc


_STORE: OcaSystemStore | None = None
_STORE_LOCK = threading.Lock()


def get_oca_system_store() -> OcaSystemStore:
    global _STORE

    if _STORE is not None:
        return _STORE

    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE

        backend = os.getenv("MIRA_OCA_SYSTEM_STORE_BACKEND", "file").strip().lower()
        if backend == "dynamodb":
            table_name = os.getenv("MIRA_OCA_SYSTEM_DDB_TABLE", "").strip()
            if not table_name:
                raise RuntimeError("MIRA_OCA_SYSTEM_DDB_TABLE is required when using the DynamoDB OCA system store")
            ttl_hours = int(os.getenv("MIRA_OCA_SYSTEM_TTL_HOURS", "168"))
            _STORE = DynamoDbOcaSystemStore(table_name=table_name, ttl_hours=ttl_hours)
        else:
            _STORE = FileOcaSystemStore()

        return _STORE


def reset_oca_system_store_for_tests() -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = None
