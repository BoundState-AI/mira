"""Tests for mira.providers.llm_provider — factory, model resolver, provider mapping."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from mira.providers.llm_provider import (
    MODEL_DEFAULTS,
    AnthropicProvider,
    BedrockConverseProvider,
    LLMProvider,
    LLMResponse,
    OpenAICompatProvider,
    get_provider,
    resolve_model,
)


# ---------------------------------------------------------------------------
# LLMResponse
# ---------------------------------------------------------------------------


class TestLLMResponse:
    def test_fields(self):
        r = LLMResponse(
            text="hello",
            input_tokens=10,
            output_tokens=5,
            model="test-model",
            latency_ms=42.5,
        )
        assert r.text == "hello"
        assert r.input_tokens == 10
        assert r.output_tokens == 5
        assert r.model == "test-model"
        assert r.latency_ms == 42.5

    def test_frozen(self):
        r = LLMResponse(text="x", input_tokens=0, output_tokens=0, model="m", latency_ms=0)
        with pytest.raises(AttributeError):
            r.text = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            assert resolve_model("sonnet") == MODEL_DEFAULTS["sonnet"]
            assert resolve_model("haiku") == MODEL_DEFAULTS["haiku"]

    def test_env_override_sonnet(self):
        with patch.dict(os.environ, {"LLM_SONNET_MODEL": "my-custom-sonnet"}, clear=True):
            assert resolve_model("sonnet") == "my-custom-sonnet"

    def test_env_override_haiku(self):
        with patch.dict(os.environ, {"LLM_HAIKU_MODEL": "my-custom-haiku"}, clear=True):
            assert resolve_model("haiku") == "my-custom-haiku"

    def test_passthrough_full_model_id(self):
        assert resolve_model("us.anthropic.claude-sonnet-4-5-20250929-v1:0") == (
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )

    def test_empty_env_falls_back_to_default(self):
        with patch.dict(os.environ, {"LLM_SONNET_MODEL": "  "}, clear=True):
            assert resolve_model("sonnet") == MODEL_DEFAULTS["sonnet"]


# ---------------------------------------------------------------------------
# get_provider factory
# ---------------------------------------------------------------------------


class TestGetProvider:
    @patch("mira.providers.llm_provider.BedrockConverseProvider.__init__", return_value=None)
    def test_default_is_bedrock(self, mock_init):
        with patch.dict(os.environ, {}, clear=True):
            p = get_provider()
            assert isinstance(p, BedrockConverseProvider)

    @patch("mira.providers.llm_provider.BedrockConverseProvider.__init__", return_value=None)
    def test_env_var_bedrock(self, mock_init):
        with patch.dict(os.environ, {"LLM_PROVIDER": "bedrock-converse"}, clear=True):
            p = get_provider()
            assert isinstance(p, BedrockConverseProvider)

    @patch("mira.providers.llm_provider.AnthropicProvider.__init__", return_value=None)
    def test_env_var_anthropic(self, mock_init):
        with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"}, clear=True):
            p = get_provider("anthropic")
            assert isinstance(p, AnthropicProvider)

    @patch("mira.providers.llm_provider.OpenAICompatProvider.__init__", return_value=None)
    def test_env_var_openai_compat(self, mock_init):
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai-compat"}, clear=True):
            p = get_provider("openai-compat")
            assert isinstance(p, OpenAICompatProvider)

    def test_explicit_name_overrides_env(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic"}, clear=True):
            with patch(
                "mira.providers.llm_provider.OpenAICompatProvider.__init__",
                return_value=None,
            ):
                p = get_provider("openai-compat")
                assert isinstance(p, OpenAICompatProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider("nonexistent")

    def test_case_insensitive(self):
        with patch(
            "mira.providers.llm_provider.BedrockConverseProvider.__init__",
            return_value=None,
        ):
            p = get_provider("Bedrock-Converse")
            assert isinstance(p, BedrockConverseProvider)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_bedrock_is_llm_provider(self):
        assert issubclass(BedrockConverseProvider, LLMProvider)

    def test_anthropic_is_llm_provider(self):
        assert issubclass(AnthropicProvider, LLMProvider)

    def test_openai_compat_is_llm_provider(self):
        assert issubclass(OpenAICompatProvider, LLMProvider)


# ---------------------------------------------------------------------------
# BedrockConverseProvider — request/response mapping
# ---------------------------------------------------------------------------


class TestBedrockConverseProvider:
    def _make_provider(self, mock_client=None):
        """Create a provider with a mocked boto3 client."""
        # boto3 is imported lazily inside __init__, so we mock it via sys.modules
        client = mock_client or MagicMock()
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            provider = BedrockConverseProvider(region="us-east-1", model_id="amazon.nova-lite-v1:0")
        return provider, client

    def test_converse_request_shape(self):
        """Verify the Converse API call uses correct wire format."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Inconel 718 is a nickel alloy."}],
                }
            },
            "usage": {"inputTokens": 20, "outputTokens": 8},
        }
        provider, _ = self._make_provider(mock_client)

        resp = provider.complete(
            system="You are a materials scientist.",
            messages=[{"role": "user", "content": "What is Inconel 718?"}],
            max_tokens=512,
            temperature=0.1,
        )

        # Verify the call args
        call_kwargs = mock_client.converse.call_args
        assert call_kwargs.kwargs["modelId"] == "amazon.nova-lite-v1:0"
        assert call_kwargs.kwargs["system"] == [{"text": "You are a materials scientist."}]
        assert call_kwargs.kwargs["messages"] == [
            {"role": "user", "content": [{"text": "What is Inconel 718?"}]}
        ]
        assert call_kwargs.kwargs["inferenceConfig"] == {
            "maxTokens": 512,
            "temperature": 0.1,
        }

    def test_converse_response_mapping(self):
        """Verify response fields are correctly extracted."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Test response."}],
                }
            },
            "usage": {"inputTokens": 15, "outputTokens": 4},
        }
        provider, _ = self._make_provider(mock_client)

        resp = provider.complete(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert isinstance(resp, LLMResponse)
        assert resp.text == "Test response."
        assert resp.input_tokens == 15
        assert resp.output_tokens == 4
        assert resp.model == "amazon.nova-lite-v1:0"
        assert resp.latency_ms >= 0

    def test_multi_turn_messages(self):
        """Verify multi-turn conversations are mapped correctly."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "usage": {"inputTokens": 30, "outputTokens": 1},
        }
        provider, _ = self._make_provider(mock_client)

        messages = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "follow up"},
        ]
        provider.complete(system="sys", messages=messages)

        call_msgs = mock_client.converse.call_args.kwargs["messages"]
        assert len(call_msgs) == 3
        assert call_msgs[0] == {"role": "user", "content": [{"text": "first question"}]}
        assert call_msgs[1] == {"role": "assistant", "content": [{"text": "first answer"}]}
        assert call_msgs[2] == {"role": "user", "content": [{"text": "follow up"}]}

    def test_json_response_format_appends_to_system(self):
        """Verify response_format='json' adds JSON instruction to system prompt."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"text": "{}"}]}},
            "usage": {"inputTokens": 5, "outputTokens": 1},
        }
        provider, _ = self._make_provider(mock_client)

        provider.complete(
            system="base prompt",
            messages=[{"role": "user", "content": "q"}],
            response_format="json",
        )

        sys_arg = mock_client.converse.call_args.kwargs["system"]
        assert sys_arg == [{"text": "base prompt\n\nYou MUST respond with valid JSON only."}]

    def test_empty_usage_defaults_to_zero(self):
        """Verify missing usage fields default to 0."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"role": "assistant", "content": [{"text": "x"}]}},
            "usage": {},
        }
        provider, _ = self._make_provider(mock_client)

        resp = provider.complete(system="s", messages=[{"role": "user", "content": "q"}])
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0

    def test_no_anthropic_specific_fields(self):
        """The Bedrock provider must NOT reference Anthropic-specific wire format."""
        import inspect

        source = inspect.getsource(BedrockConverseProvider)
        # Should NOT use Anthropic Messages API field names
        assert "input_tokens" not in source or "inputTokens" in source
        assert "anthropic-version" not in source
        assert "x-api-key" not in source


# ---------------------------------------------------------------------------
# AnthropicProvider — mock SDK
# ---------------------------------------------------------------------------


class TestAnthropicProvider:
    def test_complete_calls_sdk(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        # Mock response
        mock_block = MagicMock()
        mock_block.text = "Answer from Claude."
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage.input_tokens = 12
        mock_response.usage.output_tokens = 6
        mock_response.model = "claude-sonnet-4-5-20250929"
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            provider = AnthropicProvider(api_key="test-key", model_id="claude-sonnet-4-5-20250929")

        resp = provider.complete(
            system="sys",
            messages=[{"role": "user", "content": "hello"}],
        )

        assert resp.text == "Answer from Claude."
        assert resp.input_tokens == 12
        assert resp.output_tokens == 6
        assert resp.model == "claude-sonnet-4-5-20250929"

    def test_missing_api_key_raises(self):
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            with patch.dict(os.environ, {}, clear=True):
                with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                    AnthropicProvider()


# ---------------------------------------------------------------------------
# OpenAICompatProvider — mock HTTP
# ---------------------------------------------------------------------------


class TestOpenAICompatProvider:
    def test_complete_request_shape(self):
        provider = OpenAICompatProvider(
            base_url="http://test:8000/v1",
            api_key="sk-test",
            model_id="my-model",
        )

        response_body = json.dumps({
            "choices": [{"message": {"content": "compat answer"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            "model": "my-model",
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("mira.providers.llm_provider.urllib.request.urlopen", return_value=mock_resp):
            resp = provider.complete(
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert resp.text == "compat answer"
        assert resp.input_tokens == 7
        assert resp.output_tokens == 3

    def test_json_response_format_passed(self):
        provider = OpenAICompatProvider(
            base_url="http://test:8000/v1",
            api_key="sk-test",
            model_id="m",
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "model": "m",
        }).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        captured_request = {}

        def capture_urlopen(req, **kwargs):
            captured_request["data"] = json.loads(req.data.decode("utf-8"))
            return mock_resp

        with patch("mira.providers.llm_provider.urllib.request.urlopen", side_effect=capture_urlopen):
            provider.complete(
                system="s",
                messages=[{"role": "user", "content": "q"}],
                response_format="json",
            )

        assert captured_request["data"]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------


class TestImports:
    def test_package_import(self):
        """Verify the public API is importable from mira.providers."""
        from mira.providers import (
            LLMResponse,
            LLMProvider,
            BedrockConverseProvider,
            AnthropicProvider,
            OpenAICompatProvider,
            get_provider,
            resolve_model,
        )
        assert LLMResponse is not None
        assert callable(get_provider)
        assert callable(resolve_model)
