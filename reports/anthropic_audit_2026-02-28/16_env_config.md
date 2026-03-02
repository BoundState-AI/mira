# Environment Variables and Config Surface (Anthropic/Bedrock)

## Key runtime environment variables

- API keys/endpoints:
  - `ANTHROPIC_API_KEY`
  - Direct endpoint usage in H2 modules: `https://api.anthropic.com/v1/messages`

- Bedrock toggles/regions/models:
  - `USE_BEDROCK`
  - `AWS_REGION`
  - `BEDROCK_REGION`
  - `BEDROCK_MODEL`

- Model selectors (examples):
  - `BOK_EXTRACTOR_MODEL`
  - `BSMH_BOUNCER_HAIKU_MODEL`, `BSMH_BOUNCER_MODEL`, `BSMH_BOUNCER_LOCAL_MODEL`
  - `BSMH_HAIKU_BEDROCK_MODEL`, `BSMH_HAIKU_DIRECT_MODEL`
  - `BSMH_SONNET_BEDROCK_MODEL`, `BSMH_SONNET_DIRECT_MODEL`, `BSMH_SONNET_MODEL`
  - `MIRA_H2_CONDITION_RESOLVER_HAIKU_MODEL`, `MIRA_H2_HAIKU_MODEL`
  - `MIRA_H2_CONDITION_RESOLVER_PROVIDER`, `MIRA_H2_NLG_PROVIDER`

- Relevant config classes/files:
  - `athena/config/pipeline_config.py` (deployment-mode model maps, `.env` load)
  - `sentinel-main/gptl/api/deps.py` (settings alias `ANTHROPIC_API_KEY`, `.env` load)
  - `mira/utils/config.py` (`anthropic_api_key`, `.env` load)
  - `mira/api/app.py` and `mira/api/app_codex.py` load root `.env` if present
  - `mira/precedent_engine/models/config.py` default Bedrock model ID

## .env and template files

- `.env` files checked into repo root: **none found**.
- Environment templates present:
  - `auth.env.example`
  - `frontend/auth.env.example`
- These templates are auth-focused and do not include Anthropic keys.

## Full reference indexes

- `03_env_vars_all.txt` (all env vars discovered)
- `04_env_model_refs_filtered.txt` (file:line matches for Anthropic/Bedrock/model env refs)

## Secrets manager references

- No active Anthropic secret retrieval path via AWS Secrets Manager/Vault was found in scanned runtime modules.
- One TODO note references future secrets management: `mira/core/db_config.py:30`.
