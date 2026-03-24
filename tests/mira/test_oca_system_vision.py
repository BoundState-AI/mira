from __future__ import annotations

import importlib
import sys
from types import ModuleType

import mira.oca.system_vision as system_vision


def test_oca_system_vision_uses_aws_default_region_for_bedrock(monkeypatch) -> None:
    captured: dict[str, str] = {}

    fake_anthropic = ModuleType("anthropic")

    class FakeAnthropicBedrock:
        def __init__(self, *, aws_region: str) -> None:
            captured["region"] = aws_region

    fake_anthropic.AnthropicBedrock = FakeAnthropicBedrock

    with monkeypatch.context() as context:
        for env_key in (
            "OCA_SYSTEM_VISION_BEDROCK_REGION",
            "BEDROCK_REGION",
            "AWS_REGION",
            "LLM_SONNET_MODEL",
            "OCA_SYSTEM_VISION_MODEL_BEDROCK",
        ):
            context.delenv(env_key, raising=False)
        context.setenv("AWS_DEFAULT_REGION", "us-gov-west-1")
        context.setenv("LLM_PROVIDER", "bedrock-converse")
        context.setitem(sys.modules, "anthropic", fake_anthropic)

        reloaded = importlib.reload(system_vision)
        service = reloaded.OCASystemVisionService()

        service._get_client()

        assert reloaded.BEDROCK_REGION == "us-gov-west-1"
        assert service._bedrock_region == "us-gov-west-1"
        assert captured["region"] == "us-gov-west-1"

    importlib.reload(system_vision)
