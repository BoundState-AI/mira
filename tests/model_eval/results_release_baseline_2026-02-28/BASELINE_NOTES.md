# Release Baseline — 2026-02-28

Source: `tests/model_eval/results_tuned`

Model defaults validated by this baseline:
- `LLM_SONNET_MODEL=amazon.nova-pro-v1:0`
- `LLM_HAIKU_MODEL=amazon.nova-lite-v1:0`

Topline metrics:
- Sonnet weighted: `0.867` (parse `0.850`, classification `0.771`, failures `0/20`)
- Haiku weighted: `1.000` (parse `1.000`, classification `1.000`, failures `0/7`)

Tuning impact vs prior post-migration run (`results_post`):
- Sonnet weighted delta: `+0.004`
- Haiku weighted delta: `+0.086`
- BN-006 recovered from `0.400 -> 1.000`

Use this directory as the pre-deploy reference set for Monday go-live.
