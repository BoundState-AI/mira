# MIRA Anthropic Dependency Audit (2026-02-28)

This bundle contains the complete audit artifacts.

## Files
- `10_callsite_inventory.md`: All SDK/Bedrock call files (53) with status, line, model ref, purpose.
- `11_additional_direct_http_calls.md`: Raw HTTP Anthropic callsites (2).
- `02_calls_prompts_parsing_raw.txt`: Per-file extracted sections: CALLS / MODELS / PROMPTS / PARSING.
- `03_env_vars_all.txt`: All env vars detected in scan.
- `04_env_model_refs_filtered.txt`: Anthropic/Bedrock/model/env reference hits with file:line.
- `12_dependencies.md`: Anthropic-related package dependency chain.
- `13_abstraction_and_risks.md`: Adapter assessment, call graph, swap-risk summary.
- `00_call_files.txt`, `01_calls_models_categorized.tsv`, `05_anthropic_keyword_hits.txt`, `06_prompt_keyword_hits.txt`: raw indexes.

## Key counts
- Direct SDK/Bedrock call files: 53
- Additional direct HTTP Anthropic call files: 2
- Total call files: 55
- Categorization of 53 call files: active=33, legacy_or_script=19, sentinel=1

## Prompt inventory note
`02_calls_prompts_parsing_raw.txt` includes prompt constants and inline prompt loci for each direct call file.
Shared prompt registries are primarily in:
- `athena/prompts/*.py`
- `athena/extraction/prompts*.py`
- `data_laundering/domain_pack.py`
- `sentinel-main/gptl/prompts.py`
- `14_prompt_inventory.md`: Prompt template catalog with purpose and target model/tier.
- `15_response_parsing_contracts.md`: Output parsing contracts and swap-risk hotspots.
- `16_env_config.md`: Anthropic/Bedrock env/config inventory and `.env` status.
