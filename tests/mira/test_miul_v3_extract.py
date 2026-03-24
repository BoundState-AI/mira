from __future__ import annotations

import importlib
import sys
from types import ModuleType

import mira.miul.v3.extract as miul_v3_extract


def test_miul_v3_vision_client_uses_bedrock_only(monkeypatch) -> None:
    captured: dict[str, str] = {}

    fake_anthropic = ModuleType("anthropic")

    class FakeAnthropicBedrock:
        def __init__(self, *, aws_region: str) -> None:
            captured["region"] = aws_region

    fake_anthropic.AnthropicBedrock = FakeAnthropicBedrock

    with monkeypatch.context() as context:
        for env_key in (
            "MIUL_V3_VISION_BEDROCK_REGION",
            "MIUL_V3_VISION_MODEL_BEDROCK",
            "BEDROCK_REGION",
            "AWS_REGION",
            "LLM_SONNET_MODEL",
        ):
            context.delenv(env_key, raising=False)
        context.setenv("AWS_DEFAULT_REGION", "us-gov-west-1")
        context.setenv("LLM_PROVIDER", "bedrock-converse")
        context.setitem(sys.modules, "anthropic", fake_anthropic)

        reloaded = importlib.reload(miul_v3_extract)
        client = reloaded.VisionClient(api_key="unused-direct-key")

        client.client

        assert reloaded.BEDROCK_REGION == "us-gov-west-1"
        assert client.bedrock_region == "us-gov-west-1"
        assert client.model == reloaded.SONNET_MODEL
        assert captured["region"] == "us-gov-west-1"

    importlib.reload(miul_v3_extract)
