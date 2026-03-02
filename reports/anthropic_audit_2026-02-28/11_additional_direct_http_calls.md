# Additional Direct HTTP Anthropic Calls

| File | Line | Endpoint | Model source | Purpose |
|---|---:|---|---|---|
| `mira/h2/condition_resolver.py` | 167 | `https://api.anthropic.com/v1/messages` | `MIRA_H2_CONDITION_RESOLVER_HAIKU_MODEL` default `claude-haiku-4-5-20251001` | Normalize heat-treatment condition labels to canonical JSON |
| `mira/h2/ft_temp.py` | 637 | `https://api.anthropic.com/v1/messages` | `MIRA_H2_HAIKU_MODEL` default `claude-haiku-4-5-20251001` | Rewrite deterministic H2 decision into engineer-facing narrative |
