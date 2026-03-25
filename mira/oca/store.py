"""Shared case-store backends for OCA snapshots."""

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

from .models import AssessmentSnapshot


class OcaCaseStore(Protocol):
    def save(self, snapshot: AssessmentSnapshot) -> None:
        ...

    def get(self, case_id: str) -> AssessmentSnapshot:
        ...


class FileOcaCaseStore:
    def __init__(self, storage_dir: Path | None = None) -> None:
        default_dir = Path(tempfile.gettempdir()) / "mira_oca_cases"
        self._storage_dir = Path(
            os.getenv("MIRA_OCA_CASE_STORE_DIR", str(storage_dir or default_dir))
        ).expanduser()
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, case_id: str) -> Path:
        return self._storage_dir / f"{case_id}.json"

    def save(self, snapshot: AssessmentSnapshot) -> None:
        path = self._path_for(snapshot.case_id)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def get(self, case_id: str) -> AssessmentSnapshot:
        path = self._path_for(case_id)
        if not path.exists():
            raise KeyError(case_id)
        return AssessmentSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


class DynamoDbOcaCaseStore:
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
    def _encode_payload(snapshot: AssessmentSnapshot) -> str:
        raw = snapshot.model_dump_json().encode("utf-8")
        compressed = gzip.compress(raw, compresslevel=6)
        return base64.b64encode(compressed).decode("ascii")

    @staticmethod
    def _decode_payload(payload: str) -> AssessmentSnapshot:
        compressed = base64.b64decode(payload.encode("ascii"))
        raw = gzip.decompress(compressed).decode("utf-8")
        return AssessmentSnapshot.model_validate_json(raw)

    def save(self, snapshot: AssessmentSnapshot) -> None:
        expires_at = int(time.time()) + self._ttl_seconds
        try:
            self._client.put_item(
                TableName=self._table_name,
                Item={
                    "case_id": {"S": snapshot.case_id},
                    "payload": {"S": self._encode_payload(snapshot)},
                    "payload_encoding": {"S": "gzip+base64"},
                    "revision": {"N": str(snapshot.revision)},
                    "created_at": {"S": snapshot.created_at.isoformat()},
                    "expires_at": {"N": str(expires_at)},
                },
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to save OCA case {snapshot.case_id}: {exc}") from exc

    def get(self, case_id: str) -> AssessmentSnapshot:
        try:
            response = self._client.get_item(
                TableName=self._table_name,
                Key={"case_id": {"S": case_id}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Failed to load OCA case {case_id}: {exc}") from exc

        item = response.get("Item")
        if not item:
            raise KeyError(case_id)

        payload = item.get("payload", {}).get("S")
        if not payload:
            raise KeyError(case_id)
        return self._decode_payload(payload)


_STORE: OcaCaseStore | None = None
_STORE_LOCK = threading.Lock()


def get_oca_case_store() -> OcaCaseStore:
    global _STORE

    if _STORE is not None:
        return _STORE

    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE

        backend = os.getenv("MIRA_OCA_CASE_STORE_BACKEND", "file").strip().lower()
        if backend == "dynamodb":
            table_name = os.getenv("MIRA_OCA_DDB_TABLE", "").strip()
            if not table_name:
                raise RuntimeError("MIRA_OCA_DDB_TABLE is required when using the DynamoDB OCA case store")
            ttl_hours = int(os.getenv("MIRA_OCA_CASE_TTL_HOURS", "168"))
            _STORE = DynamoDbOcaCaseStore(table_name=table_name, ttl_hours=ttl_hours)
        else:
            _STORE = FileOcaCaseStore()

        return _STORE

