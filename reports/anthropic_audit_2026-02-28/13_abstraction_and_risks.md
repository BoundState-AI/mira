# Abstraction Layer Assessment

## Centralized adapters that exist
- ATHENA: `LLMProvider` protocol with `BedrockProvider` and `AnthropicProvider`.
- SENTINEL: `BaseClaudeClient` / `AnthropicClaudeClient` with tier mapping and JSON extraction retry.

## Scattered direct Anthropic callsites
- MIRA API: `mira/api/routers/mira_v4.py` directly creates Anthropic/AnthropicBedrock clients.
- BSMH: direct calls in `bouncer.py`, `service.py`, `response_formatter.py`.
- MIUL/MUA/Knowledge twins: many per-module direct clients.
- H2: raw HTTP requests to `api.anthropic.com` bypass SDK.
- Precedent engine: direct Bedrock `invoke_model` calls.

## Call graph (high-level)
- API/business routers -> domain service/orchestrator -> provider/client instantiation -> Anthropic/Bedrock call.
- ATHENA path: `PipelineOrchestrator` -> stage (`triage`/`extract`/`boundary`/`discovery`) -> `LLMProvider.complete_*` -> provider `messages.create`.
- SENTINEL path: engine components (`feature_extractor`/`intent_framing`/`negative_selection`/`signal_extraction`/`synthesis`) -> `gptl.claude_client` -> `messages.create`.

## Parsing-contract risk concentration
- Heavy dependence on text-contract JSON and regex extraction (`{...}` / `[...]`) across modules.
- Limited structured API enforcement (`response_format` / tool schemas absent in Anthropic calls).
- No active `stop_sequences` use in Anthropic call paths.
