# MIRA Model Evaluation Harness

Repeatable harness for comparing non-Anthropic LLM candidates against MIRA P0 production behaviors.
Used to select Monday default models for `LLM_SONNET_MODEL` and `LLM_HAIKU_MODEL`.

## Quick Start

```bash
# Dry run — validate config without calling any models
python -m tests.model_eval.eval_runner --dry-run

# Run against OpenAI-compatible endpoint (default)
export EVAL_OPENAI_API_KEY=sk-...
python -m tests.model_eval.eval_runner

# Evaluate specific models on a single tier
python -m tests.model_eval.eval_runner --tier sonnet --models gpt-4o,mistral-large-latest

# Use AWS Bedrock
python -m tests.model_eval.eval_runner --provider bedrock --tier haiku
```

## Architecture

```
tests/model_eval/
├── eval_runner.py       # Main harness — provider abstraction, scoring, output
├── test_cases.json      # 27 test cases across 5 prompt types
├── README.md            # This file
└── results/             # Output directory (gitignored)
    ├── results.json     # Machine-readable per-case scores
    ├── leaderboard.csv  # Ranked model summary
    └── summary.md       # Human-readable winner recommendation
```

## What It Tests

The harness replays the exact system prompts from MIRA production against candidate models:

| Prompt Type | Production Source | Tier | Cases |
|-------------|-------------------|------|-------|
| `query_parse` | `mira_v4.py::_PARSE_SYSTEM_PROMPT` | Sonnet | 13 |
| `bouncer` | `bouncer.py::_BOUNCER_SYSTEM_PROMPT` | Haiku | 7 |
| `fracture_parse` | `service.py::_FC_CONTEXT_PARSE_PROMPT` | Sonnet | 3 |
| `response_format` | `response_formatter.py::_FORMATTER_SYSTEM_PROMPT` | Sonnet | 3 |
| `fc_format` | `response_formatter.py::_FC_FORMATTER_SYSTEM_PROMPT` | Sonnet | 1 |

Test case categories:
- **Pass/fail/conditional** — O2 compatible, H2 conditional, insufficient data
- **Out-of-scope** — jokes, coding questions, jailbreak attempts
- **Parse/intent extraction** — environment params, material types, unit conversion
- **Null discipline** — fields the model must leave as null (not hallucinate)

## Scoring Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|------------------|
| Parseable by current parser | 30% | Can `extract_json(text, expect="object")` extract valid JSON? |
| Classification correctness | 25% | Do intent, safety_context, domain_scope, verdict match expected values? |
| Key facts present | 20% | Are critical fields populated (candidate_materials, environment, etc.)? |
| Uncertainty discipline | 15% | Are null-expected fields actually null? No hallucinated values? |
| Latency | 5% | Response time (<2s = 1.0, <5s = 0.7, <10s = 0.4, >10s = 0.1) |
| Token cost | 5% | Normalized against a 500-token budget baseline |

## Provider Support

The harness uses a provider abstraction layer. No Anthropic-specific interfaces.

| Provider | How to Configure | Notes |
|----------|-----------------|-------|
| `openai` | `EVAL_OPENAI_API_KEY` + `EVAL_OPENAI_BASE_URL` | Default. Works with OpenAI, Azure, Mistral, Groq, Together, vLLM |
| `bedrock` | AWS credentials + `EVAL_BEDROCK_REGION` | For GovCloud candidate testing |
| `ollama` | `EVAL_OPENAI_BASE_URL=http://localhost:11434/v1` | Local models via Ollama's OpenAI compat layer |

## Default Candidates

### Sonnet Tier (heavy reasoning, parsing)
| Model ID | Provider | GovCloud |
|----------|----------|----------|
| `gpt-4o` | OpenAI | No |
| `gpt-4o-mini` | OpenAI | No |
| `mistral-large-latest` | Mistral | Yes (via Bedrock) |
| `us.meta.llama3-3-70b-instruct-v1:0` | Bedrock | Yes |
| `us.amazon.nova-pro-v1:0` | Bedrock | Yes |

### Haiku Tier (gate/bouncer, lightweight formatting)
| Model ID | Provider | GovCloud |
|----------|----------|----------|
| `gpt-4o-mini` | OpenAI | No |
| `mistral-small-latest` | Mistral | Yes (via Bedrock) |
| `gpt-3.5-turbo` | OpenAI | No |
| `us.meta.llama3-2-3b-instruct-v1:0` | Bedrock | Yes |
| `us.amazon.nova-lite-v1:0` | Bedrock | Yes |

Override via CLI `--models` or env vars `EVAL_MODELS_SONNET` / `EVAL_MODELS_HAIKU` (comma-separated).

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `EVAL_OPENAI_API_KEY` | — | API key for OpenAI-compatible provider |
| `EVAL_OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL for OpenAI-compatible provider |
| `EVAL_BEDROCK_REGION` | `us-east-1` | AWS Bedrock region |
| `EVAL_PROVIDER` | `openai` | Default provider |
| `EVAL_MODELS_SONNET` | (see defaults) | Comma-separated Sonnet-tier model IDs |
| `EVAL_MODELS_HAIKU` | (see defaults) | Comma-separated Haiku-tier model IDs |

## Interpreting Results

### results.json
Machine-readable. Contains per-model, per-case breakdown of all scoring dimensions plus raw token counts and latency.

### leaderboard.csv
Quick-scan ranked table. Import into a spreadsheet for sorting/filtering.

### summary.md
Human-readable report with:
- Ranked table per tier with recommended winner
- Explicit `LLM_SONNET_MODEL=...` and `LLM_HAIKU_MODEL=...` values
- Failure diagnostics (which cases failed and why)
- Parse failure analysis (cases where JSON extraction failed)
- Tradeoff notes for GovCloud, latency, cost, determinism

## Adding Test Cases

Edit `test_cases.json`. Each case needs:

```json
{
  "id": "QP-013",
  "name": "Descriptive name",
  "prompt_type": "query_parse",
  "target_tier": "sonnet",
  "input": "The user query to send",
  "expected": {
    "classification_fields": ["intent", "safety_context", "domain_scope"],
    "intent": "compatibility_query",
    "safety_context": "oxygen",
    "domain_scope": "in_scope",
    "key_fields": ["candidate_materials", "material_key"],
    "null_fields": ["material_key"],
    "hallucination_traps": ["design_life_cycles"]
  }
}
```

Fields:
- `classification_fields`: Which fields to check for exact match
- `key_fields`: Which fields must be non-null/non-empty
- `null_fields`: Which fields must be null (uncertainty discipline)
- `hallucination_traps`: Fields the model should NOT fill in because the input doesn't mention them

For formatter cases (`response_format`, `fc_format`):
```json
{
  "expected": {
    "expected_verdict": "COMPATIBLE",
    "required_phrases": ["monel 400", "verdict_exact"],
    "prohibited_phrases": ["signal", "0.87"]
  }
}
```

## Production Mapping

The harness results map directly to these env vars in the MIRA backend:

| Env Var | Current Default | Set By Eval |
|---------|----------------|-------------|
| `BSMH_SONNET_MODEL` | `claude-sonnet-4-5-20250929` | `LLM_SONNET_MODEL` winner |
| `BSMH_SONNET_DIRECT_MODEL` | `claude-sonnet-4-5-20250929` | `LLM_SONNET_MODEL` winner |
| `BSMH_HAIKU_MODEL` | `claude-haiku-4-5-20251001` | `LLM_HAIKU_MODEL` winner |
| `BSMH_BOUNCER_HAIKU_MODEL` | `claude-haiku-4-5-20251001` | `LLM_HAIKU_MODEL` winner |
| `MIRA_H2_HAIKU_MODEL` | `claude-haiku-4-5-20251001` | `LLM_HAIKU_MODEL` winner |
| `MIRA_H2_CONDITION_RESOLVER_HAIKU_MODEL` | `claude-haiku-4-5-20251001` | `LLM_HAIKU_MODEL` winner |

## Swap Risk Notes

From the audit (`15_response_parsing_contracts.md`):

> The codebase relies predominantly on **prompted JSON discipline + parser heuristics**
> rather than hard schema-enforced response modes. Any model with different
> verbosity/fencing behavior can regress parsing success rates.

Key patterns the candidate must follow:
1. Return raw JSON (fences/preamble tolerated; object must be extractable by `extract_json`)
2. Use `null` for missing fields, not empty strings or omitted keys
3. First line of formatter output must be `VERDICT_EXACT: <verdict>` or `FC_VERDICT: <verdict>`
4. No preamble text before JSON in parse-type prompts
