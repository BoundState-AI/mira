"""Pass 2 — LLM refinement of question templates.

Sends the schema manifest and Pass 1 question templates to Sonnet for
natural language refinement and domain-specific question discovery.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable

from mira.forge_claude.introspector.manifest import SchemaManifest
from mira.forge_claude.question_gen.question_map import QuestionMap, Question, QuestionCategory

LOGGER = logging.getLogger(__name__)

# Try MIRA's LLM provider (works when run from the project root)
try:
    from mira.providers.llm_provider import complete as llm_complete, resolve_model
except ImportError:
    llm_complete = None  # type: ignore[assignment]
    resolve_model = None  # type: ignore[assignment]


_SYSTEM_PROMPT = """\
You are a database intelligence analyst. You receive a database schema manifest \
and a set of auto-generated questions about what the database can answer.

Your job:
1. Rewrite each question's `natural_language` text into clear, concise English \
   that a non-technical stakeholder would understand. Keep the meaning identical.
2. Identify 3-8 NEW domain-specific questions that the schema patterns missed \
   but a domain expert would ask. Assign them appropriate `template_type`, \
   `target_table`, `target_columns`, `ui_component`, and `priority`.
3. Write a 1-2 sentence `domain_summary` describing what this database is about \
   and what kinds of decisions it can support.

Question quality rules:
- Prefer engineer-facing decision-support questions about material qualification, test outcomes, approvals, failures, environments, and evidence.
- Avoid CRUD-style boilerplate and lookup-only questions unless they are genuinely high-value.
- Avoid questions whose main value is searching by hash, source file, backup/archive record, or report identifier.
- Do not propose min/max/average questions for identifiers, keys, codes, revision numbers, or sample numbers unless they are clearly meaningful engineering measures.
- Prefer cross-table questions only when the join implies a real engineering question, not a generic "combined with" statement.

Respond with ONLY valid JSON matching this structure:
{
  "domain_summary": "...",
  "refined_questions": [
    {
      "id": "<original id>",
      "natural_language": "<rewritten text>"
    }
  ],
  "new_questions": [
    {
      "id": "llm_001",
      "natural_language": "...",
      "template_type": "aggregate|filter|search|trend|comparison|distribution",
      "target_table": "...",
      "target_columns": ["..."],
      "ui_component": "SearchBar|ResultsTable|StatsBar|FilterSidebar|DetailPanel|ComparisonView",
      "priority": "high|medium|low",
      "category": "..."
    }
  ]
}
"""

_BATCH_REWRITE_SYSTEM_PROMPT = """\
You are a database intelligence analyst.

You will receive a database schema subset and a batch of auto-generated questions.
Rewrite each question's `natural_language` text into clear, concise English that a \
non-technical stakeholder would understand. Keep the meaning identical.

Quality rules:
- Keep strong engineer-facing questions crisp and concrete.
- If a question is generic or CRUD-like, rewrite it toward decision support without inventing unsupported semantics.
- Avoid phrasing like "combined with" or "cross-reference" unless that language is truly required.

Respond with ONLY valid JSON matching this structure:
{
  "refined_questions": [
    {
      "id": "<original id>",
      "natural_language": "<rewritten text>"
    }
  ]
}
"""

_DISCOVERY_SYSTEM_PROMPT = """\
You are a database intelligence analyst. You receive a database schema manifest \
and a representative sample of auto-generated questions about what the database can answer.

Your job:
1. Identify 3-8 NEW domain-specific questions that the schema patterns missed \
   but a domain expert would ask. Assign them appropriate `template_type`, \
   `target_table`, `target_columns`, `ui_component`, and `priority`.
2. Write a 1-2 sentence `domain_summary` describing what this database is about \
   and what kinds of decisions it can support.

Question quality rules:
- Prefer engineer-facing decision-support questions about material qualification, approvals, failure patterns, test outcomes, environmental constraints, and supporting evidence.
- Avoid CRUD, ID lookup, report-number lookup, backup/archive browsing, and generic "combined with" join questions.
- Do not suggest min/max/average questions for identifiers, keys, codes, revision numbers, or sample numbers.

Respond with ONLY valid JSON matching this structure:
{
  "domain_summary": "...",
  "new_questions": [
    {
      "id": "llm_001",
      "natural_language": "...",
      "template_type": "aggregate|filter|search|trend|comparison|distribution",
      "target_table": "...",
      "target_columns": ["..."],
      "ui_component": "SearchBar|ResultsTable|StatsBar|FilterSidebar|DetailPanel|ComparisonView",
      "priority": "high|medium|low",
      "category": "..."
    }
  ]
}
"""


_MAX_QUESTIONS_PER_BATCH = 120
_MAX_REWRITE_QUESTIONS_PER_BATCH = 40
_ESTIMATED_CHARS_PER_QUESTION = 200
_MAX_USER_MESSAGE_CHARS = 120_000  # ~30K tokens, well under 200K limit
_DEFAULT_LLM_REFINEMENT_WORKERS = 3
_DEFAULT_LLM_RETRIES = 5
_DEFAULT_LLM_RETRY_BASE_DELAY_S = 2.0
_DEFAULT_LLM_TIMEOUT_S = 180


def _forge_provider() -> str:
    return (os.environ.get("FORGE_LLM_PROVIDER") or os.environ.get("LLM_PROVIDER") or "anthropic").strip().lower()


def _forge_model() -> str:
    explicit = (
        os.environ.get("FORGE_LLM_MODEL")
        or os.environ.get("FORGE_BSMS_MODEL")
        or os.environ.get("LLM_SONNET_MODEL")
        or ""
    ).strip()
    if explicit:
        return explicit
    if _forge_provider() == "anthropic":
        return "claude-sonnet-4-20250514"
    return resolve_model("sonnet")


def _forge_refinement_workers() -> int:
    raw = (os.environ.get("FORGE_LLM_REFINEMENT_WORKERS") or "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 8))
    return _DEFAULT_LLM_REFINEMENT_WORKERS


def _forge_rewrite_batch_size() -> int:
    raw = (os.environ.get("FORGE_LLM_REWRITE_BATCH_SIZE") or "").strip()
    if raw.isdigit():
        return max(10, min(int(raw), _MAX_QUESTIONS_PER_BATCH))
    return _MAX_REWRITE_QUESTIONS_PER_BATCH


def _forge_llm_retries() -> int:
    raw = (os.environ.get("FORGE_LLM_MAX_RETRIES") or "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 10))
    return _DEFAULT_LLM_RETRIES


def _forge_llm_timeout_s() -> int:
    raw = (os.environ.get("FORGE_LLM_TIMEOUT_S") or "").strip()
    if raw.isdigit():
        return max(30, min(int(raw), 900))
    return _DEFAULT_LLM_TIMEOUT_S


def _should_retry_llm_error(exc: Exception) -> bool:
    message = str(exc).lower()
    transient_markers = (
        "internal server error",
        "api_error",
        "overloaded",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "529",
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "service unavailable",
    )
    return any(marker in message for marker in transient_markers)


def _llm_complete_with_retry(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    temperature: float,
    provider: str,
    timeout_s: int | float,
) -> object:
    attempts = _forge_llm_retries()
    delay_s = _DEFAULT_LLM_RETRY_BASE_DELAY_S
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return llm_complete(
                system=system,
                user=user,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                provider=provider,
                timeout_s=timeout_s,
            )
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not _should_retry_llm_error(exc):
                raise
            LOGGER.warning(
                "Transient LLM failure on attempt %d/%d: %s; retrying in %.1fs",
                attempt,
                attempts,
                exc,
                delay_s,
            )
            time.sleep(delay_s)
            delay_s = min(delay_s * 2.0, 20.0)

    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM completion failed without raising an error")


def refine_questions_with_llm(
    manifest: SchemaManifest,
    question_map: QuestionMap,
    *,
    require_llm: bool = False,
    suppress_discovery: bool = False,
    progress_callback: Callable[[str, float], None] | None = None,
) -> QuestionMap:
    """Refine question templates using LLM (Sonnet).

    For large databases (>200 questions), batches by category to stay
    within token limits. Each batch gets its own LLM call.

    Args:
        manifest: The schema manifest for context.
        question_map: The deterministic pass output.

    Returns:
        Refined question map with better natural language and new questions.
        Falls back to input unchanged if LLM is unavailable.
    """
    if llm_complete is None:
        if require_llm:
            raise RuntimeError("LLM provider not available for required FORGE refinement")
        LOGGER.warning("LLM provider not available — returning deterministic output unchanged")
        return question_map

    schema_summary = _build_schema_summary(manifest)
    all_questions = _build_questions_payload(question_map)

    # Check if we need batching
    total_chars = len(json.dumps(schema_summary)) + len(json.dumps(all_questions))
    if total_chars > _MAX_USER_MESSAGE_CHARS or len(all_questions) > _MAX_QUESTIONS_PER_BATCH:
        LOGGER.info(
            "Large question set (%d questions, ~%dK chars) — using batched refinement",
            len(all_questions), total_chars // 1000,
        )
        return _refine_batched(
            manifest,
            question_map,
            schema_summary,
            require_llm=require_llm,
            suppress_discovery=suppress_discovery,
            progress_callback=progress_callback,
        )

    return _refine_single(
        question_map,
        schema_summary,
        all_questions,
        require_llm=require_llm,
        suppress_discovery=suppress_discovery,
        progress_callback=progress_callback,
    )


def _refine_single(
    question_map: QuestionMap,
    schema_summary: dict,
    questions_payload: list[dict],
    *,
    require_llm: bool,
    suppress_discovery: bool = False,
    progress_callback: Callable[[str, float], None] | None = None,
) -> QuestionMap:
    """Single-shot refinement for small question sets."""
    user_message = (
        f"## Database Schema\n```json\n{json.dumps(schema_summary, indent=2)}\n```\n\n"
        f"## Auto-Generated Questions\n```json\n{json.dumps(questions_payload, indent=2)}\n```"
    )

    # Use rewrite-only prompt when discovery is suppressed (curator mode)
    system_prompt = _BATCH_REWRITE_SYSTEM_PROMPT if suppress_discovery else _SYSTEM_PROMPT

    model = _forge_model()
    provider = _forge_provider()
    LOGGER.info("LLM refiner calling %s with %d questions (suppress_discovery=%s)",
                model, len(questions_payload), suppress_discovery)
    if progress_callback is not None:
        progress_callback("Calling Sonnet for question refinement.", 5.0)

    try:
        response = _llm_complete_with_retry(
            system=system_prompt,
            user=user_message,
            model=model,
            max_tokens=4096,
            temperature=0.2,
            provider=provider,
            timeout_s=_forge_llm_timeout_s(),
        )
    except Exception as e:
        if require_llm:
            raise RuntimeError(f"LLM refinement failed: {e}") from e
        LOGGER.error("LLM refinement failed: %s — returning deterministic output", e)
        return question_map

    LOGGER.info(
        "LLM response: %d input tokens, %d output tokens, %.0fms",
        response.input_tokens, response.output_tokens, response.latency_ms,
    )

    try:
        result = _parse_llm_response(response.text, model=model, provider=provider)
    except Exception as e:
        if require_llm:
            raise RuntimeError(f"Failed to parse required LLM refinement output: {e}") from e
        LOGGER.error("Failed to parse LLM response: %s — returning deterministic output", e)
        return question_map

    if progress_callback is not None:
        progress_callback("Sonnet refinement complete.", 100.0)
    return _apply_refinements(question_map, result)


def _refine_batched(
    manifest: SchemaManifest,
    question_map: QuestionMap,
    schema_summary: dict,
    *,
    require_llm: bool,
    suppress_discovery: bool = False,
    progress_callback: Callable[[str, float], None] | None = None,
) -> QuestionMap:
    """Batched refinement for large question sets.

    Splits questions into batches by category, processes each batch
    separately, and merges results.
    """
    model = _forge_model()
    provider = _forge_provider()
    table_lookup = {table["name"]: table for table in schema_summary.get("tables", [])}
    budget_per_batch = _MAX_USER_MESSAGE_CHARS - 500  # overhead

    # Build batches with schema scoped to the tables each batch actually touches.
    batches: list[dict] = []
    current_batch: list[dict] = []
    current_tables: set[str] = set()
    current_chars = 0

    for cat in question_map.question_categories:
        for q in cat.questions:
            q_payload = {
                "id": q.id,
                "natural_language": q.natural_language,
                "template_type": q.template_type,
                "target_table": q.target_table,
                "category": cat.category,
            }
            q_chars = len(json.dumps(q_payload))
            q_tables = _question_target_tables(q_payload, table_lookup)

            projected_tables = current_tables | q_tables
            projected_schema_json = json.dumps(
                _schema_summary_subset(schema_summary, table_lookup, projected_tables),
                indent=2,
            )
            projected_total_chars = len(projected_schema_json) + current_chars + q_chars

            if (
                projected_total_chars > budget_per_batch
                or len(current_batch) >= _forge_rewrite_batch_size()
            ) and current_batch:
                batches.append({
                    "questions": current_batch,
                    "schema_json": json.dumps(
                        _schema_summary_subset(schema_summary, table_lookup, current_tables),
                        indent=2,
                    ),
                })
                current_batch = []
                current_tables = set()
                current_chars = 0
                projected_tables = q_tables

            current_tables |= q_tables

            current_batch.append(q_payload)
            current_chars += q_chars

    if current_batch:
        batches.append({
            "questions": current_batch,
            "schema_json": json.dumps(
                _schema_summary_subset(schema_summary, table_lookup, current_tables),
                indent=2,
            ),
        })

    LOGGER.info("Split %d questions into %d batches for LLM refinement",
                sum(len(batch["questions"]) for batch in batches), len(batches))

    def _process_batch(batch_index: int, batch: dict) -> tuple[int, dict]:
        batch_questions = batch["questions"]
        batch_schema_json = batch["schema_json"]
        user_message = (
            f"## Database Schema\n```json\n{batch_schema_json}\n```\n\n"
            f"## Auto-Generated Questions (batch {batch_index+1}/{len(batches)})\n"
            f"```json\n{json.dumps(batch_questions, indent=2)}\n```"
        )
        response = _llm_complete_with_retry(
            system=_BATCH_REWRITE_SYSTEM_PROMPT,
            user=user_message,
            model=model,
            max_tokens=4096,
            temperature=0.2,
            provider=provider,
            timeout_s=_forge_llm_timeout_s(),
        )
        LOGGER.info(
            "Batch %d/%d: %d input tokens, %d output tokens",
            batch_index + 1,
            len(batches),
            response.input_tokens,
            response.output_tokens,
        )
        result = _parse_llm_response(response.text, model=model, provider=provider)
        return batch_index, result

    workers = min(_forge_refinement_workers(), len(batches)) or 1
    all_results: list[tuple[int, dict]] = []
    completed = 0
    if progress_callback is not None:
        progress_callback(
            f"Refining {sum(len(batch['questions']) for batch in batches)} questions across {len(batches)} Sonnet batches.",
            2.0,
        )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_process_batch, batch_index, batch): batch_index
            for batch_index, batch in enumerate(batches)
        }
        for future in as_completed(future_map):
            batch_index = future_map[future]
            try:
                all_results.append(future.result())
                completed += 1
                if progress_callback is not None:
                    progress_callback(
                        f"Completed Sonnet batch {completed}/{len(batches)}.",
                        min(100.0, (completed / len(batches)) * 100.0),
                    )
            except Exception as e:
                if require_llm:
                    raise RuntimeError(
                        f"LLM refinement batch {batch_index+1}/{len(batches)} failed: {e}"
                    ) from e
                LOGGER.warning("Batch %d/%d failed: %s — skipping", batch_index+1, len(batches), e)

    if not all_results:
        if require_llm:
            raise RuntimeError("All required LLM refinement batches failed")
        LOGGER.error("All batches failed — returning deterministic output")
        return question_map

    all_results.sort(key=lambda item: item[0])

    # Merge batch results
    merged = {
        "refined_questions": [],
        "new_questions": [],
        "domain_summary": "",
    }
    for _, result in all_results:
        merged["refined_questions"].extend(result.get("refined_questions", []))

    if not suppress_discovery:
        enrichment = _discover_domain_enrichment(
            schema_summary,
            question_map,
            model=model,
            provider=provider,
            require_llm=require_llm,
        )
        if enrichment:
            merged["new_questions"].extend(enrichment.get("new_questions", []))
            if enrichment.get("domain_summary"):
                merged["domain_summary"] = enrichment["domain_summary"]
    else:
        LOGGER.info("Discovery suppressed (curator mode) — skipping LLM question invention")

    LOGGER.info(
        "Merged %d refined + %d new questions from %d batches",
        len(merged["refined_questions"]), len(merged["new_questions"]), len(all_results),
    )

    return _apply_refinements(question_map, merged)


def _build_schema_summary(manifest: SchemaManifest) -> dict:
    """Build a compact schema summary to stay within token limits."""
    tables = []
    for table in manifest.tables:
        cols = []
        for col in table.columns:
            col_info: dict = {"name": col.name, "type": col.type}
            if col.primary_key:
                col_info["pk"] = True
            if col.nullable is False:
                col_info["required"] = True
            if getattr(col, "sample_values", None):
                col_info["samples"] = col.sample_values[:3]
            cols.append(col_info)

        table_info: dict = {
            "name": table.name,
            "columns": cols,
            "row_count": table.row_count,
        }
        if table.foreign_keys:
            table_info["foreign_keys"] = [
                {"from": fk.column, "to": f"{fk.references_table}.{fk.references_column}"}
                for fk in table.foreign_keys
            ]
        tables.append(table_info)

    return {
        "database": manifest.database_name,
        "type": manifest.database_type,
        "tables": tables,
    }


def _build_questions_payload(question_map: QuestionMap) -> list[dict]:
    """Flatten questions into a compact list for the LLM."""
    out = []
    for cat in question_map.question_categories:
        for q in cat.questions:
            out.append({
                "id": q.id,
                "natural_language": q.natural_language,
                "template_type": q.template_type,
                "target_table": q.target_table,
                "category": cat.category,
            })
    return out


def _discover_domain_enrichment(
    schema_summary: dict,
    question_map: QuestionMap,
    *,
    model: str,
    provider: str,
    require_llm: bool,
) -> dict:
    representative_questions = _build_questions_payload(question_map)[:200]
    user_message = (
        f"## Database Schema\n```json\n{json.dumps(schema_summary, indent=2)}\n```\n\n"
        f"## Representative Auto-Generated Questions\n"
        f"```json\n{json.dumps(representative_questions, indent=2)}\n```"
    )

    try:
        response = _llm_complete_with_retry(
            system=_DISCOVERY_SYSTEM_PROMPT,
            user=user_message,
            model=model,
            max_tokens=4096,
            temperature=0.2,
            provider=provider,
            timeout_s=_forge_llm_timeout_s(),
        )
        return _parse_llm_response(response.text, model=model, provider=provider)
    except Exception as exc:
        if require_llm:
            raise RuntimeError(f"LLM discovery refinement failed: {exc}") from exc
        LOGGER.warning("LLM discovery refinement failed: %s", exc)
        return {}


def _question_target_tables(question_payload: dict, table_lookup: dict[str, dict]) -> set[str]:
    target_table = str(question_payload.get("target_table", "")).strip()
    if not target_table:
        return set()

    tables = {target_table}
    table_info = table_lookup.get(target_table)
    if table_info:
        for fk in table_info.get("foreign_keys", []):
            ref = str(fk.get("to", ""))
            ref_table = ref.split(".", 1)[0].strip()
            if ref_table in table_lookup:
                tables.add(ref_table)
    return tables


def _schema_summary_subset(
    schema_summary: dict,
    table_lookup: dict[str, dict],
    target_tables: set[str],
) -> dict:
    if not target_tables:
        return schema_summary

    tables: list[dict] = []
    seen: set[str] = set()
    pending = list(target_tables)

    while pending:
        table_name = pending.pop()
        if table_name in seen:
            continue
        table_info = table_lookup.get(table_name)
        if not table_info:
            continue
        seen.add(table_name)
        tables.append(table_info)
        for fk in table_info.get("foreign_keys", []):
            ref = str(fk.get("to", ""))
            ref_table = ref.split(".", 1)[0].strip()
            if ref_table in table_lookup and ref_table not in seen:
                pending.append(ref_table)

    if not tables:
        return schema_summary

    tables.sort(key=lambda item: item.get("name", ""))
    return {
        "database": schema_summary.get("database"),
        "type": schema_summary.get("type"),
        "tables": tables,
    }


def _parse_llm_response(
    text: str,
    *,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """Extract JSON from LLM response, with one repair pass for malformed output."""
    last_error: Exception | None = None
    for candidate in _json_candidates(text):
        try:
            payload = _json_load_dict(candidate)
        except Exception as exc:
            last_error = exc
            continue
        return payload

    salvaged = _salvage_llm_payload(text)
    if salvaged is not None:
        return salvaged

    if llm_complete is not None and model and provider:
        repaired = _repair_json_via_llm(text, model=model, provider=provider)
        for candidate in _json_candidates(repaired):
            try:
                payload = _json_load_dict(candidate)
            except Exception as exc:
                last_error = exc
                continue
            return payload
        salvaged = _salvage_llm_payload(repaired)
        if salvaged is not None:
            return salvaged

    if last_error is not None:
        raise last_error
    raise ValueError("LLM response did not contain a JSON object")


def _json_candidates(text: str) -> list[str]:
    cleaned = text.strip()
    candidates = [cleaned]
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith("```")]
        candidates.append("\n".join(lines).strip())
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    candidates.extend(fenced)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(cleaned[start : end + 1])
    candidates.extend(_balanced_json_object_candidates(cleaned))

    normalized: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        normalized.append(candidate)
        normalized.append(re.sub(r",(\s*[}\]])", r"\1", candidate))

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in normalized:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _json_load_dict(candidate: str) -> dict:
    decoder = json.JSONDecoder()
    payload, _ = decoder.raw_decode(candidate)
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON root must be an object")
    return payload


def _balanced_json_object_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    in_string = False
    escape = False
    depth = 0
    start: int | None = None

    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : index + 1])
                start = None

    return candidates


def _salvage_llm_payload(text: str) -> dict | None:
    refined_questions = _salvage_refined_questions(text)
    if refined_questions:
        return {"refined_questions": refined_questions}

    domain_summary = _salvage_string_field(text, "domain_summary")
    new_questions = _salvage_object_array(text, "new_questions")
    if domain_summary is not None or new_questions:
        payload: dict = {"new_questions": new_questions}
        if domain_summary is not None:
            payload["domain_summary"] = domain_summary
        return payload

    return None


def _salvage_refined_questions(text: str) -> list[dict]:
    return _salvage_object_array(text, "refined_questions")


def _salvage_string_field(text: str, field_name: str) -> str | None:
    match = re.search(rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"', text, flags=re.DOTALL)
    if not match:
        return None
    raw = match.group(1)
    return json.loads(f'"{raw}"')


def _salvage_object_array(text: str, field_name: str) -> list[dict]:
    field_match = re.search(rf'"{re.escape(field_name)}"\s*:\s*\[', text)
    if not field_match:
        return []

    start = field_match.end()
    decoder = json.JSONDecoder()
    items: list[dict] = []
    index = start
    length = len(text)

    while index < length:
        while index < length and text[index] in " \r\n\t,":
            index += 1
        if index >= length or text[index] == "]":
            break
        if text[index] != "{":
            break
        try:
            item, consumed = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            break
        if not isinstance(item, dict):
            break
        items.append(item)
        index += consumed

    return items


def _repair_json_via_llm(text: str, *, model: str, provider: str) -> str:
    response = _llm_complete_with_retry(
        system=(
            "You repair malformed JSON. "
            "Rewrite the user's payload into valid JSON only. "
            "Do not summarize, explain, or change the intended fields."
        ),
        user=text,
        model=model,
        max_tokens=4096,
        temperature=0.0,
        provider=provider,
        timeout_s=_forge_llm_timeout_s(),
    )
    return response.text


def _apply_refinements(question_map: QuestionMap, result: dict) -> QuestionMap:
    """Apply LLM refinements to the question map."""
    # Build lookup of refined text by question ID
    refined_map: dict[str, str] = {}
    for item in result.get("refined_questions", []):
        qid = item.get("id", "")
        text = item.get("natural_language", "")
        if qid and text:
            refined_map[qid] = text

    # Apply refinements to existing questions
    refined_count = 0
    for cat in question_map.question_categories:
        for q in cat.questions:
            if q.id in refined_map:
                q.natural_language = refined_map[q.id]
                refined_count += 1

    LOGGER.info("Refined %d/%d existing questions", refined_count, len(refined_map))

    # Add new LLM-discovered questions
    new_questions = result.get("new_questions", [])
    if new_questions:
        # Group new questions by category
        cat_map: dict[str, list[Question]] = {}
        for nq in new_questions:
            cat_name = nq.get("category", "LLM Discovered")
            q = Question(
                id=nq.get("id", f"llm_{len(cat_map)}"),
                natural_language=nq.get("natural_language", ""),
                template_type=nq.get("template_type", "search"),
                target_table=nq.get("target_table", ""),
                target_columns=nq.get("target_columns", []),
                join_tables=[],
                ui_component=nq.get("ui_component", "SearchBar"),
                priority=nq.get("priority", "medium"),
                discovery_source="llm_refinement",
            )
            cat_map.setdefault(cat_name, []).append(q)

        # Merge into existing categories or create new ones
        existing_cats = {c.category: c for c in question_map.question_categories}
        for cat_name, questions in cat_map.items():
            if cat_name in existing_cats:
                existing_cats[cat_name].questions.extend(questions)
            else:
                question_map.question_categories.append(
                    QuestionCategory(category=cat_name, questions=questions)
                )

        LOGGER.info("Added %d new LLM-discovered questions", len(new_questions))

    # Update domain summary if provided
    domain_summary = result.get("domain_summary", "")
    if domain_summary:
        question_map.domain_summary = domain_summary

    # Update timestamp
    question_map.generated_at = datetime.utcnow().isoformat() + "Z"

    return question_map
