from __future__ import annotations

import importlib
import io
import sys
from types import ModuleType, SimpleNamespace

from PIL import Image
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


def _png_bytes(*, mode: str = "RGBA") -> bytes:
    image = Image.new(mode, (32, 32), (255, 0, 0, 128) if "A" in mode else (255, 0, 0))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class _FakeMessagesAPI:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._responses.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(text=text)])


def test_oca_system_vision_normalizes_supported_image_variants() -> None:
    fake_messages = _FakeMessagesAPI([
        '{"suggested_inputs_patch": {}, "components": [], "connections": [], "questions": [], "warnings": []}'
    ])
    service = system_vision.OCASystemVisionService(use_bedrock=False, model_id="test-model")
    service._client = SimpleNamespace(messages=fake_messages)

    result = service.build_mockup(
        system_id="sys-1",
        image_bytes=_png_bytes(),
        media_type="image/jpg",
        filename="diagram.jpg",
        flow_direction_hint="left_to_right",
        notes="",
        current_inputs=None,
    )

    request_image = fake_messages.calls[0]["messages"][0]["content"][1]["source"]
    assert request_image["media_type"] == "image/png"
    assert result.model_used == "test-model"


def test_oca_system_vision_retries_once_for_non_json_response() -> None:
    fake_messages = _FakeMessagesAPI([
        "I think this is a tank and a valve.",
        '{"suggested_inputs_patch": {}, "components": [], "connections": [], "questions": [], "warnings": []}',
    ])
    service = system_vision.OCASystemVisionService(use_bedrock=False, model_id="test-model")
    service._client = SimpleNamespace(messages=fake_messages)

    result = service.build_mockup(
        system_id="sys-2",
        image_bytes=_png_bytes(mode="RGB"),
        media_type="image/png",
        filename="diagram.png",
        flow_direction_hint="unknown",
        notes="",
        current_inputs=None,
    )

    assert len(fake_messages.calls) == 2
    assert result.system_id == "sys-2"
