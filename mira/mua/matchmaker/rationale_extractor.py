"""Extract candidate rationale phrases from precedent text."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

from .models import IssueCode, PrecedentMatch, RationalePhrase, normalize_issue_code

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")

_KEYWORDS: dict[IssueCode, tuple[str, ...]] = {
    IssueCode.FLAM: ("flamm", "ignit", "propagat", "combust", "fire"),
    IssueCode.TOX: ("toxic", "smac", "offgas", "contamin", "cure"),
    IssueCode.O2: ("oxygen", "ignit", "oca", "promoted", "test"),
    IssueCode.HEE: ("hydrogen", "embritt", "astm g142", "microstructure", "heat treat"),
    IssueCode.SCC: ("stress", "corros", "yield", "mitigat"),
    IssueCode.CORR: ("corros", "finish", "coat", "galvanic", "exposure"),
    IssueCode.TVS: ("vcm", "vacuum", "outgas", "sealed", "encaps"),
    IssueCode.FLUID: ("fluid", "immersion", "compat", "propellant", "oxidizer"),
}


def extract_rationale_phrases(
    precedents: Iterable[PrecedentMatch],
    issue: str | IssueCode,
    limit: int = 8,
) -> list[RationalePhrase]:
    """Extract and rank phrase candidates from precedent rationale text."""

    issue_code = normalize_issue_code(issue)
    keywords = _KEYWORDS[issue_code]

    candidates: list[RationalePhrase] = []
    for precedent in precedents:
        text = (precedent.rationale_text or "").strip()
        if not text:
            continue

        for sentence in _split_sentences(text):
            score = _score_sentence(sentence, keywords)
            if score <= 0:
                continue
            candidates.append(
                RationalePhrase(
                    phrase=sentence,
                    mua_number=precedent.mua_number,
                    score=score,
                )
            )

    candidates.sort(key=lambda p: p.score, reverse=True)
    return _dedupe_phrases(candidates, limit=limit)


def _split_sentences(text: str) -> list[str]:
    sentences = []
    for chunk in _SENTENCE_SPLIT.split(text):
        cleaned = chunk.strip()
        if len(cleaned) < 24:
            continue
        sentences.append(cleaned)
    return sentences


def _score_sentence(sentence: str, keywords: tuple[str, ...]) -> float:
    lowered = sentence.lower()
    hits = sum(1 for keyword in keywords if keyword in lowered)
    if hits == 0:
        return 0.0

    length_bonus = min(len(sentence) / 180.0, 1.0)
    density_bonus = hits / max(1, len(keywords))
    return hits * 1.5 + length_bonus + density_bonus


def _dedupe_phrases(phrases: list[RationalePhrase], limit: int) -> list[RationalePhrase]:
    kept: list[RationalePhrase] = []
    normalized: list[str] = []

    for phrase in phrases:
        canon = _canonicalize(phrase.phrase)
        if not canon:
            continue

        if any(_similar(canon, prev) >= 0.85 for prev in normalized):
            continue

        kept.append(phrase)
        normalized.append(canon)
        if len(kept) >= limit:
            break

    return kept


def _canonicalize(text: str) -> str:
    lowered = _NON_ALNUM.sub(" ", text.lower())
    return " ".join(lowered.split())


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

