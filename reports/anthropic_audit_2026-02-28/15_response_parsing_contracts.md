# Claude Response Parsing Contracts

This section focuses on places where model swaps can break behavior.

## Contract patterns in use

1. **Direct JSON parse from text block**
- Pattern: `json.loads(response.content[0].text[...])`
- Common in ATHENA pipeline/extraction modules and many MIUL/MUA modules.

2. **Regex JSON extraction (object/array) then parse**
- Object pattern: `re.search(r"\{[\s\S]*\}", text)` then `json.loads(...)`
- Array pattern: `re.search(r"\[[\s\S]*\]", text)` then `json.loads(...)`
- Heavily used in BSMH bouncer/service, MIRA v4 parser, MIUL legacy modules, MUA validator, SENTINEL client fallback parser.

3. **Markdown fence stripping before parse**
- Pattern: split on ``` fences and parse interior.
- Seen in ATHENA pipeline (`triage`, `extract`, `boundary`, `discovery`) and SENTINEL client.

4. **Pydantic validation after parse**
- Example: `FractureContextInput.model_validate(parsed)` in BSMH service.
- Example: ParsedQuery model build in MIRA v4 path.

5. **Retry-on-parse-failure wrappers**
- SENTINEL `BaseClaudeClient.call_json` retries with explicit “JSON only” clarification.
- BSMH bouncer retries JSON extraction then deterministic fallback.

## High-risk callsites (examples)

- `mira/api/routers/mira_v4.py:338-340` regex object extraction from Sonnet output.
- `mira/bsmh/bouncer.py:397-401` regex object extraction and JSON parse.
- `mira/bsmh/service.py:926-932` regex object extraction + Pydantic validate.
- `mira/mua/v6/logic_validator.py:294-330` multi-path JSON salvage/parsing.
- `mira/miul/material_code_selector.py:240-268` JSON parse + regex fallback.
- `sentinel-main/gptl/claude_client.py:350-376` layered extraction (direct, codefence, brace-span).

## Structured API controls

- `stop_sequences` / `stop_sequence`: not found in Anthropic call paths.
- Anthropic structured response controls (`response_format`/JSON schema/tool-use): not found at callsites.
- XML output contracts for Claude responses: not found in Anthropic call paths.

## Practical swap risk

The codebase relies predominantly on **prompted JSON discipline + parser heuristics** rather than hard schema-enforced response modes. Any model with different verbosity/fencing behavior can regress parsing success rates.
