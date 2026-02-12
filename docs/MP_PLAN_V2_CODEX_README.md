# M&P Plan v2 Codex

This is a non-breaking, versioned implementation path for M&P planning with:

- Full-index applicability over all entries in `mira/compliance/data/mprs_6016c.yaml`
- Deterministic compliance determinations with required citations/evidence
- Dynamic HITL targeting (uncertainty + risk driven)
- Re-openable recursive closure workflow
- Artifact outputs: DOCX + structured JSON

## Entrypoint

Run the Codex app entrypoint to enable the versioned router:

- `mira/api/app_codex.py`

Versioned API base:

- `/mp-plan/v2/*`

## Core Files

- Router: `mira/api/routers/mp_plan_v2_codex.py`
- Compute loop: `mira/mp_plan/compute_loop_codex.py`
- Applicability engine: `mira/mp_plan/engines/applicability_codex.py`
- Compliance engine: `mira/mp_plan/engines/compliance_eval_codex.py`
- DOCX generator: `mira/mp_plan/generation/mp_plan_docx_codex.py`
- JSON generator: `mira/mp_plan/generation/plan_json_codex.py`

## API Highlights

- `POST /mp-plan/v2/sessions`
- `POST /mp-plan/v2/sessions/{session_id}/materials`
- `POST /mp-plan/v2/sessions/{session_id}/environment`
- `POST /mp-plan/v2/sessions/{session_id}/compute`
- `GET /mp-plan/v2/sessions/{session_id}/questions`
- `GET /mp-plan/v2/sessions/{session_id}/citation-helper/{determination_id}`
- `POST /mp-plan/v2/sessions/{session_id}/answer`
- `POST /mp-plan/v2/sessions/{session_id}/closure`
- `POST /mp-plan/v2/sessions/{session_id}/accept-open`
- `POST /mp-plan/v2/sessions/{session_id}/reopen-gap/{gap_id}`
- `POST /mp-plan/v2/sessions/{session_id}/generate`
- `GET /mp-plan/v2/sessions/{session_id}/export/mp-plan-json`

## Test

- `py -3 -m pytest tests/mira/mp_plan/test_api_v2_codex.py -q`

## HITL Clarity

Unknown/flagged determinations now include:

- `human_meaning`: plain-English interpretation
- `human_action`: section-aware recommended next step
- `citation_helper`: one-click citation templates + quick action tokens
