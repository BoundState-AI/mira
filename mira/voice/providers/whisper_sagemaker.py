"""SageMaker-hosted faster-whisper STT provider.

The endpoint is expected to accept a JSON payload of the form
``{"audio_b64": "...", "sample_rate": 16000}`` and return
``{"text": "...", "confidence": 0.97}``.

For the demo a single warm endpoint is sufficient; production scales out via
SageMaker auto-scaling targeting GPU utilization.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .base import STTProvider, STTResult

LOGGER = logging.getLogger(__name__)


class WhisperSageMakerSTT(STTProvider):
    def __init__(self, endpoint_name: str, region: str) -> None:
        if not endpoint_name:
            raise ValueError("WhisperSageMakerSTT requires endpoint_name")
        self._endpoint = endpoint_name
        self._region = region
        self._client = boto3.client("sagemaker-runtime", region_name=region)

    @property
    def provider_id(self) -> str:
        return f"whisper-sagemaker:{self._endpoint}"

    async def transcribe(self, pcm16_16k_mono: bytes) -> STTResult:
        payload = json.dumps(
            {
                "audio_b64": base64.b64encode(pcm16_16k_mono).decode("ascii"),
                "sample_rate": 16000,
                "encoding": "pcm_s16le",
            }
        ).encode("utf-8")

        def _invoke() -> dict:
            response = self._client.invoke_endpoint(
                EndpointName=self._endpoint,
                ContentType="application/json",
                Accept="application/json",
                Body=payload,
            )
            body = response["Body"].read()
            return json.loads(body.decode("utf-8"))

        try:
            result = await asyncio.to_thread(_invoke)
        except (BotoCoreError, ClientError) as exc:
            LOGGER.exception("SageMaker invoke_endpoint failed: %s", exc)
            return STTResult(text="", is_final=True, confidence=0.0)

        text = str(result.get("text") or "").strip()
        confidence = result.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        return STTResult(text=text, is_final=True, confidence=confidence_value)
