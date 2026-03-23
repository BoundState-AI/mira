"""
Shared helpers for guidance-pack-backed module chat adapters.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

_WORD_RE = re.compile(r"[a-z0-9_]+")
_DEFAULT_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "do",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "module",
    "my",
    "of",
    "on",
    "or",
    "page",
    "show",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "we",
    "what",
    "which",
    "with",
    "workflow",
    "you",
}
_ENTRY_ID_KEYS = (
    "field_id",
    "concept_id",
    "rating_id",
    "verdict_id",
    "flag_id",
    "step_id",
    "question_type",
)
_ENTRY_TEXT_FIELDS = (
    "field_id",
    "flag_id",
    "concept_id",
    "rating_id",
    "verdict_id",
    "step_id",
    "label",
    "what",
    "why",
    "guidance",
    "source",
    "question_text",
)


@lru_cache(maxsize=16)
def load_guidance_sections(path_str: str) -> dict[str, list[dict[str, Any]]]:
    raw = json.loads(Path(path_str).read_text(encoding="utf-8"))
    return {key: value for key, value in raw.items() if isinstance(value, list)}


def tokenize(text: str, *, stop_words: Iterable[str] | None = None) -> set[str]:
    blocked = set(stop_words or ()) | _DEFAULT_STOP_WORDS
    return {
        token
        for token in _WORD_RE.findall((text or "").lower())
        if len(token) > 2 and token not in blocked
    }


def guidance_entry_id(entry: dict[str, Any]) -> str:
    for key in _ENTRY_ID_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def guidance_entry_title(entry: dict[str, Any]) -> str:
    for key in ("label", "what"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return guidance_entry_id(entry) or "Guidance"


def guidance_entry_source(entry: dict[str, Any]) -> str | None:
    value = str(entry.get("source") or "").strip()
    return value or None


def lookup_guidance_entries(path: Path, keys: Sequence[str]) -> list[dict[str, Any]]:
    if not keys:
        return []
    sections = load_guidance_sections(str(path))
    wanted = {key.strip() for key in keys if key.strip()}
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section, entries in sections.items():
        for entry in entries:
            entry_id = guidance_entry_id(entry)
            if entry_id not in wanted:
                continue
            dedupe_key = entry_id or guidance_entry_title(entry)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            enriched = dict(entry)
            enriched["_section"] = section
            hits.append(enriched)
    ordered_hits: list[dict[str, Any]] = []
    seen.clear()
    by_id = {guidance_entry_id(entry): entry for entry in hits}
    for key in keys:
        entry = by_id.get(key.strip())
        if entry is None:
            continue
        dedupe_key = guidance_entry_id(entry) or guidance_entry_title(entry)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ordered_hits.append(entry)
    return ordered_hits


def search_guidance(
    path: Path,
    query: str,
    *,
    limit: int = 3,
    sections: Sequence[str] | None = None,
    stop_words: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    tokens = tokenize(query, stop_words=stop_words)
    if not tokens:
        return []

    all_sections = load_guidance_sections(str(path))
    ordered_sections: list[str] = []
    seen_sections: set[str] = set()
    for section in sections or ():
        if section in all_sections and section not in seen_sections:
            ordered_sections.append(section)
            seen_sections.add(section)
    for section in all_sections:
        if section not in seen_sections:
            ordered_sections.append(section)

    matches: list[tuple[int, dict[str, Any]]] = []
    for section in ordered_sections:
        for entry in all_sections.get(section, []):
            haystack = " ".join(str(entry.get(field, "")) for field in _ENTRY_TEXT_FIELDS).lower()
            score = sum(1 for token in tokens if token in haystack)
            if score <= 0:
                continue
            enriched = dict(entry)
            enriched["_section"] = section
            matches.append((score, enriched))

    matches.sort(
        key=lambda item: (
            -item[0],
            guidance_entry_title(item[1]).lower(),
        ),
    )

    deduped: list[dict[str, Any]] = []
    seen_entries: set[str] = set()
    for _, entry in matches:
        dedupe_key = guidance_entry_id(entry) or guidance_entry_title(entry)
        if dedupe_key in seen_entries:
            continue
        seen_entries.add(dedupe_key)
        deduped.append(entry)
        if len(deduped) >= limit:
            break
    return deduped


def format_guidance_lines(hits: Sequence[dict[str, Any]], *, heading: str) -> list[str]:
    if not hits:
        return []
    lines = [heading]
    for entry in hits:
        title = guidance_entry_title(entry)
        guidance = str(entry.get("guidance") or entry.get("why") or entry.get("what") or "").strip()
        source = guidance_entry_source(entry)
        line = f"- {title}: {guidance}" if guidance else f"- {title}"
        if source:
            line = f"{line} [{source}]"
        lines.append(line)
    return lines

