#!/usr/bin/env python3
"""
Shared storage helpers for MIUL v4 extraction artifacts and queued inputs.

When ``MIUL_EXTRACTION_BUCKET`` is configured, session artifacts and queued
inputs are stored in S3 so API tasks and worker tasks do not need shared disk.
Without that bucket, storage falls back to the historical local filesystem path
for development and single-node operation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_DEFAULT_WINDOWS_SESSION_ROOT = Path("C:/BoundState/temp/miul_sessions")
_DEFAULT_POSIX_SESSION_ROOT = Path("/tmp/miul_sessions")
_PLACEHOLDER_VALUES = {"", "placeholder", "restored", "changeme", "null", "none", "undefined"}


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _aws_region() -> str | None:
    return _env("AWS_REGION") or _env("AWS_DEFAULT_REGION") or None


def _shared_bucket() -> str:
    return _env("MIUL_EXTRACTION_BUCKET")


def _shared_prefix() -> str:
    raw = _env("MIUL_EXTRACTION_PREFIX") or "miul/v4"
    return raw.strip("/")


def shared_storage_enabled() -> bool:
    return bool(_shared_bucket())


def queue_enabled() -> bool:
    return bool(_env("MIUL_EXTRACTION_QUEUE_URL"))


def get_session_root() -> Path:
    configured = _env("MIUL_SESSION_ROOT")
    if configured:
        root = Path(configured)
    elif os.name == "nt":
        root = _DEFAULT_WINDOWS_SESSION_ROOT
    else:
        root = _DEFAULT_POSIX_SESSION_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sanitize_name(name: str) -> str:
    cleaned = Path(name or "").name.strip()
    return cleaned or "payload.bin"


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, indent=2, default=str).encode("utf-8")


@lru_cache(maxsize=1)
def _s3_client():
    import boto3

    kwargs: dict[str, Any] = {}
    region = _aws_region()
    if region:
        kwargs["region_name"] = region
    return boto3.client("s3", **kwargs)


@lru_cache(maxsize=1)
def _sqs_client():
    import boto3

    kwargs: dict[str, Any] = {}
    region = _aws_region()
    if region:
        kwargs["region_name"] = region
    return boto3.client("sqs", **kwargs)


class MIULArtifactStore:
    """Persist MIUL v4 session artifacts and queued input files."""

    def __init__(self, extraction_id: str):
        self.extraction_id = extraction_id
        self._bucket = _shared_bucket()
        self._prefix = _shared_prefix()
        self._local_dir = get_session_root() / extraction_id
        if not self._bucket:
            self._local_dir.mkdir(parents=True, exist_ok=True)

    @property
    def local_dir(self) -> Path:
        return self._local_dir

    @property
    def bucket(self) -> str:
        return self._bucket

    def _session_key(self, name: str) -> str:
        return f"{self._prefix}/sessions/{self.extraction_id}/{_sanitize_name(name)}"

    def _input_key(self, name: str) -> str:
        return f"{self._prefix}/inputs/{self.extraction_id}/{_sanitize_name(name)}"

    def write_session_json(self, name: str, data: Any) -> None:
        if not self._bucket:
            path = self._local_dir / _sanitize_name(name)
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            return

        _s3_client().put_object(
            Bucket=self._bucket,
            Key=self._session_key(name),
            Body=_json_bytes(data),
            ContentType="application/json",
        )

    def read_session_json(self, name: str) -> Any | None:
        if not self._bucket:
            path = self._local_dir / _sanitize_name(name)
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                LOGGER.error("[MIUL-V4] Failed to read %s: %s", path, exc)
                return None

        try:
            response = _s3_client().get_object(Bucket=self._bucket, Key=self._session_key(name))
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404", "NotFound", "NoSuchBucket"}:
                return None
            LOGGER.error("[MIUL-V4] Failed to load S3 session object %s: %s", self._session_key(name), exc)
            return None
        try:
            return json.loads(response["Body"].read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            LOGGER.error("[MIUL-V4] Failed to decode S3 session object %s: %s", self._session_key(name), exc)
            return None

    def session_object_exists(self, name: str) -> bool:
        if not self._bucket:
            return (self._local_dir / _sanitize_name(name)).exists()
        try:
            _s3_client().head_object(Bucket=self._bucket, Key=self._session_key(name))
            return True
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if error_code in {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}:
                return False
            LOGGER.warning("[MIUL-V4] Unable to head session object %s: %s", self._session_key(name), exc)
            return False

    def session_exists(self) -> bool:
        if not self._bucket:
            return self._local_dir.exists()
        for name in ("metadata.json", "status.json", "extraction.json", "review.json"):
            if self.session_object_exists(name):
                return True
        return False

    def upload_input_bytes(
        self,
        name: str,
        payload: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        if not self._bucket:
            path = self._local_dir / _sanitize_name(name)
            path.write_bytes(payload)
            return str(path)

        key = self._input_key(name)
        _s3_client().put_object(
            Bucket=self._bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
        )
        return key

    def upload_input_json(self, name: str, data: Any) -> str:
        if not self._bucket:
            path = self._local_dir / _sanitize_name(name)
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            return str(path)

        key = self._input_key(name)
        _s3_client().put_object(
            Bucket=self._bucket,
            Key=key,
            Body=_json_bytes(data),
            ContentType="application/json",
        )
        return key

    def read_input_json(self, reference: str) -> Any | None:
        if not self._bucket:
            path = Path(reference)
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                LOGGER.error("[MIUL-V4] Failed to read local input json %s: %s", path, exc)
                return None

        try:
            response = _s3_client().get_object(Bucket=self._bucket, Key=reference)
            return json.loads(response["Body"].read().decode("utf-8"))
        except Exception as exc:
            LOGGER.error("[MIUL-V4] Failed to load queued dt json %s: %s", reference, exc)
            return None

    def download_input_file(self, reference: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not self._bucket:
            source = Path(reference)
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
            return destination

        _s3_client().download_file(self._bucket, reference, str(destination))
        return destination

    def delete(self) -> bool:
        if not self._bucket:
            if self._local_dir.exists():
                shutil.rmtree(self._local_dir, ignore_errors=False)
            return True

        prefixes = [
            f"{self._prefix}/sessions/{self.extraction_id}/",
            f"{self._prefix}/inputs/{self.extraction_id}/",
        ]
        client = _s3_client()
        for prefix in prefixes:
            continuation_token: str | None = None
            while True:
                params: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
                if continuation_token:
                    params["ContinuationToken"] = continuation_token
                response = client.list_objects_v2(**params)
                objects = response.get("Contents") or []
                if objects:
                    client.delete_objects(
                        Bucket=self._bucket,
                        Delete={
                            "Objects": [{"Key": obj["Key"]} for obj in objects],
                            "Quiet": True,
                        },
                    )
                if not response.get("IsTruncated"):
                    break
                continuation_token = response.get("NextContinuationToken")
        return True


def ensure_queue_storage_configuration() -> None:
    if queue_enabled() and not shared_storage_enabled():
        raise RuntimeError(
            "MIUL queue mode requires MIUL_EXTRACTION_BUCKET so worker and API tasks share inputs and session artifacts."
        )


def enqueue_extraction_job(payload: dict[str, Any]) -> dict[str, Any]:
    queue_url = _env("MIUL_EXTRACTION_QUEUE_URL")
    if not queue_url:
        raise RuntimeError("MIUL_EXTRACTION_QUEUE_URL is not configured")

    response = _sqs_client().send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(payload, default=str),
    )
    return {
        "message_id": response.get("MessageId", ""),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }


def list_session_ids(limit: int = 20) -> list[str]:
    if not shared_storage_enabled():
        root = get_session_root()
        if not root.exists():
            return []
        dirs = []
        for directory in root.iterdir():
            if directory.is_dir():
                try:
                    mtime = directory.stat().st_mtime
                except OSError:
                    mtime = 0.0
                dirs.append((mtime, directory.name))
        dirs.sort(key=lambda item: item[0], reverse=True)
        return [name for _, name in dirs[:limit]]

    bucket = _shared_bucket()
    prefix = f"{_shared_prefix()}/sessions/"
    client = _s3_client()
    latest: dict[str, float] = {}
    continuation_token: str | None = None

    while True:
        params: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**params)
        for obj in response.get("Contents") or []:
            key = str(obj.get("Key") or "")
            suffix = key.removeprefix(prefix)
            if "/" not in suffix:
                continue
            session_id, _, name = suffix.partition("/")
            if not session_id or not name:
                continue
            if name not in {"status.json", "extraction.json", "review.json", "metadata.json", "audit.json"}:
                continue
            last_modified = obj.get("LastModified")
            timestamp = float(last_modified.timestamp()) if last_modified is not None else 0.0
            latest[session_id] = max(latest.get(session_id, 0.0), timestamp)
        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")

    return [
        session_id
        for session_id, _ in sorted(latest.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]
