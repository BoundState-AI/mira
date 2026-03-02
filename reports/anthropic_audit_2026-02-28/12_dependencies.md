# Anthropic-Specific Dependency Chain

- `pyproject.toml:26` -> `anthropic>=0.40.0`
- `requirements.txt:14` -> `anthropic>=0.40.0`
- `requirements.api.txt:13` -> `anthropic>=0.40.0`
- `sentinel-main/pyproject.toml:18` -> `anthropic>=0.18.0`
- `pyproject.toml:35`, `requirements.txt:23`, `requirements.api.txt:20`, `mira/precedent_engine/pyproject.toml:39` -> `boto3` (Bedrock transport)
- `langchain` Anthropic provider packages: not found in inspected manifests.
