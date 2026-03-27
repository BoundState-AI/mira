from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

import mira.miul.v3.extract as miul_v3_extract


def test_miul_v3_vision_client_uses_active_aws_session_region(monkeypatch) -> None:
    captured: dict[str, str] = {}

    fake_anthropic = ModuleType("anthropic")
    fake_boto3 = ModuleType("boto3")

    class FakeAnthropicBedrock:
        def __init__(self, *, aws_region: str) -> None:
            captured["region"] = aws_region

    class FakeSession:
        region_name = "us-gov-west-1"

    fake_anthropic.AnthropicBedrock = FakeAnthropicBedrock
    fake_boto3.Session = lambda: FakeSession()

    with monkeypatch.context() as context:
        for env_key in (
            "MIUL_V3_VISION_BEDROCK_REGION",
            "MIUL_V3_VISION_MODEL_BEDROCK",
            "BEDROCK_REGION",
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
            "LLM_SONNET_MODEL",
        ):
            context.delenv(env_key, raising=False)
        context.setenv("LLM_PROVIDER", "bedrock-converse")
        context.setitem(sys.modules, "anthropic", fake_anthropic)
        context.setitem(sys.modules, "boto3", fake_boto3)

        reloaded = importlib.reload(miul_v3_extract)
        client = reloaded.VisionClient(api_key="unused-direct-key")

        client.client

        assert reloaded.BEDROCK_REGION == "us-gov-west-1"
        assert reloaded.SONNET_MODEL.startswith("us-gov.")
        assert client.bedrock_region == "us-gov-west-1"
        assert client.model == reloaded.SONNET_MODEL
        assert captured["region"] == "us-gov-west-1"

    importlib.reload(miul_v3_extract)


def test_miul_v3_vision_client_raises_auth_error_for_invalid_bedrock_token(monkeypatch) -> None:
    fake_anthropic = ModuleType("anthropic")

    class FakeAnthropicBedrock:
        def __init__(self, *, aws_region: str) -> None:
            self.aws_region = aws_region
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            raise RuntimeError("The security token included in the request is invalid.")

    fake_anthropic.AnthropicBedrock = FakeAnthropicBedrock

    with monkeypatch.context() as context:
        context.setenv("MIUL_V3_VISION_BEDROCK_REGION", "us-gov-west-1")
        context.setenv(
            "MIUL_V3_VISION_MODEL_BEDROCK",
            "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0",
        )
        context.setitem(sys.modules, "anthropic", fake_anthropic)

        reloaded = importlib.reload(miul_v3_extract)
        client = reloaded.VisionClient()

        with pytest.raises(reloaded.VisionAuthError, match="Bedrock auth failed"):
            client.call_vision("ZmFrZS1pbWFnZQ==", "prompt")

    importlib.reload(miul_v3_extract)
