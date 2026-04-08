"""
Module: MIRA Chat -- Oracle Standards Adapter
Purpose: Adapter bridging Oracle rule packs into the unified MIRA Chat
         envelope for standards-driven clause lookup and requirement triage.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

LOGGER = logging.getLogger(__name__)

_STOP_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "can",
    "clause",
    "compare",
    "comparison",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "paragraph",
    "part",
    "say",
    "section",
    "show",
    "standard",
    "table",
    "tell",
    "the",
    "this",
    "to",
    "vs",
    "what",
    "which",
    "with",
}
_STANDARD_REF_PATTERN = re.compile(
    r"\b("
    r"(?:NASA|MSFC|MIL)[-\s]?(?:STD|PRF|SPEC)[-\s]?\d+[A-Z]?"
    r"|(?:FAR|NFS|DFARS)\s+(?:Part\s+)?\d+(?:\.\d+)*"
    r"|ESSCA(?:[-\s]II)?[-\s]J[-\s]?\d+"
    r")\b",
    re.IGNORECASE,
)
_SECTION_PATTERN = re.compile(
    r"\b(?:section|sec\.?|clause|paragraph|para\.?)\s+([A-Z]?\d+(?:\.\d+)*(?:[a-z](?:\(\d+\))?)?)\b",
    re.IGNORECASE,
)
_TABLE_NOTE_PATTERN = re.compile(
    r"\btable\s+([IVXLCDM]+|\d+)\s+note\s+(\d+)\b",
    re.IGNORECASE,
)
_COMPARE_PATTERN = re.compile(r"\b(?:compare|comparison|versus|vs\.?)\b", re.IGNORECASE)
_APPROVAL_PATTERN = re.compile(
    r"\b(?:approve\s+this|certify|sign\s+off|waive|final\s+disposition)\b",
    re.IGNORECASE,
)


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_key(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", _normalize_space(value).upper())


def _tokenize(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value.lower())
    out: list[str] = []
    for token in tokens:
        if token in _STOP_WORDS:
            continue
        if len(token) <= 1:
            continue
        out.append(token)
    return out


def _extract_short_code(value: str | None) -> str | None:
    text = _normalize_space(value).upper()
    match = re.search(r"(\d{3,5}[A-Z]?)$", text)
    if match:
        return match.group(1)
    match = re.search(r"\b(J[-\s]?\d+)\b", text)
    if match:
        return _normalize_space(match.group(1)).replace(" ", "")
    if text in {"FAR", "NFS", "DFARS"}:
        return text
    return None


@dataclass(frozen=True)
class OracleRule:
    pack_id: str
    standard_id: str
    standard_title: str
    rule_id: str
    section: str
    page: int | None
    obligation_type: str
    obligation_keyword: str
    statement_text: str
    subject: str
    requirement: str
    keywords: tuple[str, ...]
    applies_to: tuple[str, ...]


@dataclass(frozen=True)
class OraclePack:
    pack_id: str
    standard_id: str
    standard_title: str
    aliases: tuple[str, ...]
    short_code: str | None
    rules: tuple[OracleRule, ...]


class OracleAdapter(EngineAdapter):
    """Standards-oriented chat adapter for Oracle rule packs."""

    engine_id: str = "oracle"
    engine_version: str = "1.0.0"
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    def __init__(self) -> None:
        self._loaded_from: tuple[str, ...] = ()
        self._packs: list[OraclePack] = []

    def refresh_packs(self) -> list[dict[str, Any]]:
        """Invalidate the in-memory pack cache and return fresh summaries."""
        self._loaded_from = ()
        self._packs = []
        return self.list_pack_summaries()

    def list_pack_summaries(self) -> list[dict[str, Any]]:
        """Return loaded Oracle packs as UI-friendly summary records."""
        packs = self._ensure_packs_loaded()
        summaries: list[dict[str, Any]] = []
        for pack in packs:
            obligations = {
                rule.obligation_type
                for rule in pack.rules
                if rule.obligation_type
            }
            summaries.append(
                {
                    "pack_id": pack.pack_id,
                    "standard_id": pack.standard_id,
                    "standard_title": pack.standard_title,
                    "short_code": pack.short_code,
                    "rule_count": len(pack.rules),
                    "obligation_types": sorted(obligations),
                }
            )
        return summaries

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        raw_query = _normalize_space(parsed_input.get("raw_query") or parsed_input.get("query"))
        if not raw_query:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    "Oracle needs a standards question to answer. Ask about a specific standard, "
                    "section, note, or requirement."
                ),
                missing_inputs=["standards question"],
            )

        if _APPROVAL_PATTERN.search(raw_query):
            return self.wrap_refusal(
                reason=(
                    "Oracle can surface governing requirements and evidence paths, but it does not "
                    "issue final approval, certification, waiver, or sign-off decisions."
                )
            )

        packs = self._ensure_packs_loaded()
        if not packs:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    "Oracle is available, but no rule packs are loaded for chat in this deployment. "
                    "Set ORACLE_CHAT_PACK_PATHS or place packs under the default Oracle pack directory."
                ),
                missing_inputs=["oracle rule pack"],
                domain_payload={"packs_loaded": 0},
            )

        selected_packs = self._select_packs(
            raw_query=raw_query,
            parsed_standard_ref=_normalize_space(parsed_input.get("standard_ref")),
            extra_standard_refs=_as_str_list(
                (session_context.get("module_context") or {}).get("compare_standard_refs")
            ),
            packs=packs,
        )
        if not selected_packs:
            available = ", ".join(sorted(pack.standard_id for pack in packs[:8]))
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    "I need the governing standard to anchor this answer. Name the standard "
                    "explicitly, for example NASA-STD-5009C or MSFC-STD-3012A."
                ),
                missing_inputs=["standard_ref"],
                recommended_actions=[
                    "What does NASA-STD-5009C say about tin whisker mitigation?",
                    "Show me MSFC-STD-3012A Table V Note 6.",
                ],
                domain_payload={"available_standards": available, "advisory_only": True},
            )

        module_context = session_context.get("module_context") or {}
        compare_only = bool(module_context.get("compare_only"))
        is_compare = (compare_only and len(selected_packs) > 1) or len(selected_packs) > 1 or bool(_COMPARE_PATTERN.search(raw_query))
        if is_compare and len(selected_packs) > 1:
            return self._compare_packs(raw_query, selected_packs[:2])

        pack = selected_packs[0]
        matches = self._rank_rules(raw_query, pack.rules)
        if not matches:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    f"I found {pack.standard_id}, but I did not find a grounded requirement match for "
                    "the requested topic. Narrow this by section, table note, part family, or issue."
                ),
                authority_basis=[pack.standard_id],
                citations=[pack.standard_id],
                recommended_actions=[
                    f"Show me the exact section in {pack.standard_id}.",
                    f"List the top requirements in {pack.standard_id} for this topic.",
                ],
                domain_payload={"pack_id": pack.pack_id, "match_count": 0, "advisory_only": True},
            )

        top_matches = matches[:5]
        citations = [self._citation(rule) for rule, _score in top_matches]
        lines = [
            f"Oracle matched {len(top_matches)} governing requirement(s) in {pack.standard_id}.",
            "",
        ]
        for idx, (rule, _score) in enumerate(top_matches, start=1):
            lines.append(f"{idx}. {self._citation(rule)}")
            lines.append(f"   {rule.statement_text}")
            if rule.requirement and rule.requirement != rule.statement_text:
                lines.append(f"   Practical meaning: {rule.requirement}")
            if rule.subject:
                lines.append(f"   Topic: {rule.subject}")
            lines.append("")
        lines.append(
            "If you want a tighter answer, ask for a specific section, table note, appendix, or compare it against another standard."
        )

        return self.wrap_envelope(
            status=Status.PASS,
            response_text="\n".join(lines).strip(),
            authority_basis=[pack.standard_id],
            citations=citations,
            evidence=[
                {
                    "rule_id": rule.rule_id,
                    "section": rule.section,
                    "page": rule.page,
                    "statement_text": rule.statement_text,
                }
                for rule, _score in top_matches
            ],
            recommended_actions=[
                f"Show the exact requirement text from {self._citation(top_matches[0][0])}.",
                f"Compare {pack.standard_id} against another standard on this same topic.",
            ],
            domain_payload={
                "pack_id": pack.pack_id,
                "standard_id": pack.standard_id,
                "matched_rule_ids": [rule.rule_id for rule, _score in top_matches],
                "advisory_only": True,
            },
        )

    def _compare_packs(self, raw_query: str, packs: list[OraclePack]) -> EngineEnvelope:
        lines = ["Oracle comparison across loaded standards:", ""]
        citations: list[str] = []
        evidence: list[dict[str, Any]] = []
        for pack in packs:
            matches = self._rank_rules(raw_query, pack.rules)[:3]
            lines.append(f"{pack.standard_id}:")
            if not matches:
                lines.append("  No grounded requirement match found for this topic.")
                lines.append("")
                continue
            for rule, _score in matches:
                citation = self._citation(rule)
                citations.append(citation)
                evidence.append(
                    {
                        "standard_id": pack.standard_id,
                        "rule_id": rule.rule_id,
                        "section": rule.section,
                        "page": rule.page,
                    }
                )
                lines.append(f"  - {citation}")
                lines.append(f"    {rule.statement_text}")
            lines.append("")

        lines.append(
            "Use this as a clause-level comparison aid. Final tailoring or closure still needs an engineer to decide which authority governs the specific program context."
        )
        return self.wrap_envelope(
            status=Status.PASS if citations else Status.INSUFFICIENT_DATA,
            response_text="\n".join(lines).strip(),
            authority_basis=[pack.standard_id for pack in packs],
            citations=citations,
            evidence=evidence,
            recommended_actions=[
                "Show me the stricter clause between these two standards.",
                "Limit this comparison to one section or one issue.",
            ],
            domain_payload={
                "comparison": True,
                "standards": [pack.standard_id for pack in packs],
                "advisory_only": True,
            },
        )

    def _ensure_packs_loaded(self) -> list[OraclePack]:
        paths = tuple(str(path) for path in self._discover_pack_paths())
        if paths == self._loaded_from and self._packs:
            return self._packs

        packs: list[OraclePack] = []
        for path in self._discover_pack_paths():
            if path.is_file() and path.suffix.lower() == ".json":
                pack = self._load_pack(path)
                if pack is not None:
                    packs.append(pack)
                continue
            if not path.is_dir():
                continue
            for candidate in sorted(path.glob("*.json")):
                pack = self._load_pack(candidate)
                if pack is not None:
                    packs.append(pack)

        self._loaded_from = paths
        self._packs = packs
        LOGGER.info("OracleAdapter loaded %d pack(s) from %s", len(packs), paths)
        return self._packs

    def _discover_pack_paths(self) -> list[Path]:
        raw_paths = os.environ.get("ORACLE_CHAT_PACK_PATHS", "").strip()
        candidates: list[Path] = []
        if raw_paths:
            for raw in raw_paths.split(os.pathsep):
                cleaned = raw.strip()
                if cleaned:
                    candidates.append(Path(cleaned))

        repo_root = Path(__file__).resolve().parents[3]
        library_override = os.environ.get("ORACLE_CHAT_LIBRARY_DIR", "").strip()
        defaults = [
            Path(library_override) if library_override else repo_root / "oracle_packs",
            repo_root / ".tmp_oracle_main" / "oracle" / "builtin_packs",
        ]
        for path in defaults:
            if path not in candidates:
                candidates.append(path)
        return [path for path in candidates if path.exists()]

    def _load_pack(self, path: Path) -> OraclePack | None:
        try:
            pack_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.warning("Skipping unreadable Oracle pack %s: %s", path, exc)
            return None

        schema_version = str(pack_data.get("schema_version") or "")
        rules: list[OracleRule] = []
        pack_id = _normalize_space(pack_data.get("rule_pack_id") or path.stem)
        standard_id = _normalize_space(pack_data.get("standard_id") or pack_id)
        standard_title = _normalize_space(
            pack_data.get("standard_title") or pack_data.get("source_document") or standard_id
        )

        if schema_version == "gpcm_rulepack/v1" or pack_data.get("requirements"):
            for requirement in pack_data.get("requirements", []):
                if not isinstance(requirement, dict):
                    continue
                text = _normalize_space(requirement.get("shall_text"))
                if not text:
                    continue
                rules.append(
                    OracleRule(
                        pack_id=pack_id,
                        standard_id=standard_id,
                        standard_title=standard_title,
                        rule_id=_normalize_space(requirement.get("id")),
                        section=_normalize_space(requirement.get("section")),
                        page=_coerce_page(requirement.get("page")),
                        obligation_type="mandatory",
                        obligation_keyword="shall",
                        statement_text=text,
                        subject=_normalize_space(requirement.get("subject")),
                        requirement=_normalize_space(requirement.get("requirement")),
                        keywords=tuple(_as_str_list(requirement.get("keywords"))),
                        applies_to=tuple(_as_str_list(requirement.get("applies_to"))),
                    )
                )
        elif schema_version == "far_rulepack/v1" or pack_data.get("parts"):
            for part_rules in pack_data.get("parts", {}).values():
                if not isinstance(part_rules, list):
                    continue
                for item in part_rules:
                    if not isinstance(item, dict):
                        continue
                    text = _normalize_space(item.get("statement_text"))
                    if not text:
                        continue
                    rules.append(
                        OracleRule(
                            pack_id=pack_id,
                            standard_id=standard_id,
                            standard_title=standard_title,
                            rule_id=_normalize_space(item.get("id")),
                            section=_normalize_space(item.get("section")),
                            page=_coerce_page(item.get("page")),
                            obligation_type=_normalize_space(item.get("obligation_type")).lower() or "mandatory",
                            obligation_keyword=_normalize_space(item.get("obligation_keyword")).lower() or "shall",
                            statement_text=text,
                            subject=_normalize_space(item.get("subject")),
                            requirement=_normalize_space(item.get("requirement")),
                            keywords=tuple(_as_str_list(item.get("keywords"))),
                            applies_to=tuple(_as_str_list(item.get("applies_to"))),
                        )
                    )
        elif schema_version == "oracle_generic/v1" or pack_data.get("rules"):
            for item in pack_data.get("rules", []):
                if not isinstance(item, dict):
                    continue
                text = _normalize_space(item.get("statement_text"))
                if not text:
                    continue
                rules.append(
                    OracleRule(
                        pack_id=pack_id,
                        standard_id=standard_id,
                        standard_title=standard_title,
                        rule_id=_normalize_space(item.get("rule_id")),
                        section=_normalize_space(item.get("section")),
                        page=_coerce_page(item.get("page")),
                        obligation_type=_normalize_space(item.get("obligation_type")).lower() or "mandatory",
                        obligation_keyword=_normalize_space(item.get("obligation_keyword")).lower() or "shall",
                        statement_text=text,
                        subject=_normalize_space(item.get("subject")),
                        requirement=_normalize_space(item.get("requirement")),
                        keywords=tuple(_as_str_list(item.get("keywords"))),
                        applies_to=tuple(),
                    )
                )
        else:
            LOGGER.debug("Skipping non-Oracle pack shape: %s", path)
            return None

        if not rules:
            return None

        aliases = {
            _normalize_key(pack_id),
            _normalize_key(standard_id),
            _normalize_key(standard_title),
        }
        short_code = _extract_short_code(standard_id) or _extract_short_code(pack_id)
        if short_code:
            aliases.add(_normalize_key(short_code))
        return OraclePack(
            pack_id=pack_id,
            standard_id=standard_id,
            standard_title=standard_title,
            aliases=tuple(sorted(alias for alias in aliases if alias)),
            short_code=short_code,
            rules=tuple(rules),
        )

    def _select_packs(
        self,
        *,
        raw_query: str,
        parsed_standard_ref: str,
        extra_standard_refs: list[str],
        packs: list[OraclePack],
    ) -> list[OraclePack]:
        refs = self._extract_standard_refs(raw_query)
        if parsed_standard_ref:
            refs.insert(0, parsed_standard_ref)
        for ref in extra_standard_refs:
            if ref.strip():
                refs.append(ref)

        matched: list[OraclePack] = []
        seen: set[str] = set()
        for ref in refs:
            pack = self._match_pack(ref, packs)
            if pack and pack.pack_id not in seen:
                matched.append(pack)
                seen.add(pack.pack_id)

        if matched:
            return matched

        query_key = _normalize_key(raw_query)
        for pack in packs:
            if pack.short_code and _normalize_key(pack.short_code) in query_key:
                matched.append(pack)
        if matched:
            deduped: list[OraclePack] = []
            seen.clear()
            for pack in matched:
                if pack.pack_id in seen:
                    continue
                deduped.append(pack)
                seen.add(pack.pack_id)
            return deduped

        if len(packs) == 1:
            return [packs[0]]
        return []

    def _extract_standard_refs(self, raw_query: str) -> list[str]:
        refs = [_normalize_space(match.group(1)).upper() for match in _STANDARD_REF_PATTERN.finditer(raw_query)]
        if not refs:
            return []
        deduped: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            key = _normalize_key(ref)
            if key in seen:
                continue
            deduped.append(ref)
            seen.add(key)
        return deduped

    def _match_pack(self, ref: str, packs: list[OraclePack]) -> OraclePack | None:
        ref_key = _normalize_key(ref)
        for pack in packs:
            if ref_key in pack.aliases:
                return pack
        for pack in packs:
            if any(ref_key in alias or alias in ref_key for alias in pack.aliases):
                return pack
        return None

    def _rank_rules(self, raw_query: str, rules: tuple[OracleRule, ...]) -> list[tuple[OracleRule, float]]:
        query_tokens = set(_tokenize(raw_query))
        exact_section = self._extract_section_ref(raw_query)
        table_note = self._extract_table_note_ref(raw_query)
        scored: list[tuple[OracleRule, float]] = []
        for rule in rules:
            score = 0.0
            section_key = _normalize_key(rule.section)
            text_blob = " ".join(
                [
                    rule.statement_text,
                    rule.subject,
                    rule.requirement,
                    " ".join(rule.keywords),
                    " ".join(rule.applies_to),
                ]
            ).lower()
            text_tokens = set(_tokenize(text_blob))
            overlap = len(query_tokens & text_tokens)
            if overlap:
                score += overlap * 8.0
            keyword_overlap = len(query_tokens & {token.lower() for token in rule.keywords})
            if keyword_overlap:
                score += keyword_overlap * 10.0
            if exact_section and section_key == _normalize_key(exact_section):
                score += 90.0
            elif exact_section and section_key.startswith(_normalize_key(exact_section)):
                score += 55.0
            if table_note and _normalize_key(table_note) == section_key:
                score += 100.0
            if rule.obligation_type == "prohibition" and re.search(r"\b(?:prohibit|forbid|ban|not allow|shall not|may not)\b", raw_query, re.IGNORECASE):
                score += 12.0
            if rule.page is not None and re.search(rf"\bpage\s+{rule.page}\b", raw_query, re.IGNORECASE):
                score += 20.0
            if score > 0:
                scored.append((rule, score))
        scored.sort(
            key=lambda item: (
                -item[1],
                item[0].page if item[0].page is not None else 10**9,
                item[0].section,
            )
        )
        return scored

    def _extract_section_ref(self, raw_query: str) -> str | None:
        match = _SECTION_PATTERN.search(raw_query)
        if match:
            return match.group(1)
        return None

    def _extract_table_note_ref(self, raw_query: str) -> str | None:
        match = _TABLE_NOTE_PATTERN.search(raw_query)
        if not match:
            return None
        return f"Table {match.group(1).upper()} Note {match.group(2)}"

    def _citation(self, rule: OracleRule) -> str:
        section = rule.section or "unsectioned"
        if rule.page is None:
            return f"{rule.standard_id} §{section}"
        return f"{rule.standard_id} §{section} (p. {rule.page})"


def _coerce_page(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            return int(match.group(0))
    return None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _normalize_space(item)
        if text:
            out.append(text)
    return out
