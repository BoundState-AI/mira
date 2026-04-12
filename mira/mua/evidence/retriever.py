"""Evidence retrieval for MUA runtime synthesis."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Optional

from mira.core.db_config import get_db_connection_params
from mira.mua.matchmaker.models import PrecedentMatch
from mira.mua.matchmaker.rationale_extractor import extract_rationale_phrases
from mira.mua.precedent.lookup import lookup_precedent_with_ring, normalize_media_category
from mira.mua.precedent.models import PrecedentExemplar

from .models import EvidenceBundle

if TYPE_CHECKING:
    from mira.mua.classifier.models import ClassifierResult

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency behavior
    import psycopg2
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    psycopg2 = None


def retrieve_evidence_bundle(
    result: "ClassifierResult",
    alloy_family: str = "",
) -> EvidenceBundle:
    """Retrieve precedent counts, exemplar MUAs, and extracted phrases.

    Any retrieval failure degrades to an empty evidence bundle and never raises.
    """
    issue = str(result.issue_key or "").upper().strip()
    rating = str(result.rating or "").upper().strip()
    media = str(result.media or "").strip()
    media_category = normalize_media_category(media)
    material_class = result.material_class.value

    precedent_summary = result.precedent
    precedent_ring = result.precedent_ring
    family_key = (alloy_family or "").strip().lower()

    if precedent_summary is None:
        try:
            precedent_summary, precedent_ring = lookup_precedent_with_ring(
                issue=issue,
                media_category=media_category,
                material_class=material_class,
                alloy_family=family_key,
            )
        except Exception as exc:  # pragma: no cover - guardrail
            LOGGER.warning("Precedent summary lookup failed: %s", exc)
            precedent_summary, precedent_ring = None, None

    exemplars: list[PrecedentExemplar] = []
    phrases = []

    try:
        exemplars = _lookup_exemplars(
            issue=issue,
            media_category=media_category,
            material_class=material_class,
            alloy_family=family_key,
        )
    except Exception as exc:  # pragma: no cover - guardrail
        LOGGER.warning("Precedent exemplar lookup failed: %s", exc)
        exemplars = []

    if exemplars:
        try:
            phrases = _extract_phrases(issue=issue, exemplars=exemplars)
        except Exception as exc:  # pragma: no cover - guardrail
            LOGGER.warning("Rationale phrase extraction failed: %s", exc)
            phrases = []

    evidence_hash = _compute_evidence_hash(
        issue=issue,
        rating=rating,
        media=media,
        material_class=material_class,
        exemplar_ids=[ex.mua_number for ex in exemplars],
    )

    return EvidenceBundle(
        issue=issue,
        rating=rating,
        mua_type=result.mua_type.value,
        material_class=material_class,
        media=media,
        precedent_summary=precedent_summary,
        precedent_ring=precedent_ring,
        exemplars=exemplars,
        phrases=phrases,
        evidence_hash=evidence_hash,
    )


def _lookup_exemplars(
    issue: str,
    media_category: str,
    material_class: str,
    alloy_family: str,
) -> list[PrecedentExemplar]:
    if psycopg2 is None:
        LOGGER.warning("Exemplar lookup unavailable: psycopg2 not installed")
        return []

    params = get_db_connection_params(database="mira")
    params.setdefault("connect_timeout", 2)

    try:
        conn = psycopg2.connect(**params)
    except Exception as exc:  # pragma: no cover - env specific
        LOGGER.warning("Exemplar lookup DB unavailable: %s", exc)
        return []

    try:
        with conn.cursor() as cur:
            ring = "exact"
            rows = _query_ring(
                cur,
                ring=ring,
                issue=issue,
                media_category=media_category,
                material_class=material_class,
                alloy_family=alloy_family,
            )

            if len(rows) < 3:
                ring = "family"
                rows = _query_ring(
                    cur,
                    ring=ring,
                    issue=issue,
                    media_category=media_category,
                    material_class=material_class,
                    alloy_family=alloy_family,
                )

            if len(rows) < 3:
                ring = "broad"
                rows = _query_ring(
                    cur,
                    ring=ring,
                    issue=issue,
                    media_category=media_category,
                    material_class=material_class,
                    alloy_family=alloy_family,
                )

            exemplars = [_row_to_exemplar(row=row, ring=ring, requested_family=alloy_family) for row in rows]
            exemplars.sort(key=lambda item: item.match_score, reverse=True)
            return exemplars[:5]
    except Exception as exc:  # pragma: no cover - env specific
        LOGGER.warning("Exemplar query failed: %s", exc)
        return []
    finally:
        try:
            conn.close()
        except Exception as close_exc:
            LOGGER.debug("Connection close error (non-critical): %s", close_exc)


def _query_ring(
    cursor,
    *,
    ring: str,
    issue: str,
    media_category: str,
    material_class: str,
    alloy_family: str,
) -> list[tuple]:
    base_select = """
        SELECT
            mua_number,
            COALESCE(material_name, '') AS material_name,
            COALESCE(alloy_family, '') AS alloy_family,
            COALESCE(media_category, '') AS media_category,
            COALESCE(disposition, '') AS disposition,
            COALESCE(category, '') AS category,
            COALESCE(rationale_text, '') AS rationale_text,
            COALESCE(confidence, 0)::float AS confidence,
            approved
        FROM mua_precedent.mua_records
        WHERE issue = %s
          AND material_class = %s
          AND COALESCE(rationale_text, '') <> ''
          AND LENGTH(COALESCE(rationale_text, '')) > 100
          AND COALESCE(confidence, 0) >= 0.5
    """

    params: list[object] = [issue, material_class]

    if ring == "exact":
        base_select += "\n          AND media_category = %s\n          AND COALESCE(alloy_family, '') = %s\n"
        params.extend([media_category, alloy_family])
    elif ring == "family":
        base_select += "\n          AND COALESCE(alloy_family, '') = %s\n"
        params.append(alloy_family)

    base_select += """
        ORDER BY
          CASE WHEN approved IS TRUE THEN 0
               WHEN approved IS NULL THEN 1
               ELSE 2 END,
          COALESCE(confidence, 0) DESC,
          LENGTH(COALESCE(rationale_text, '')) DESC
        LIMIT 40
    """

    cursor.execute(base_select, params)
    rows = cursor.fetchall() or []
    return list(rows)


def _row_to_exemplar(row: tuple, ring: str, requested_family: str) -> PrecedentExemplar:
    mua_number = str(row[0] or "")
    material_name = str(row[1] or "")
    alloy_family = str(row[2] or "")
    media_category = str(row[3] or "")
    disposition = str(row[4] or "")
    category = str(row[5] or "")
    rationale_text = str(row[6] or "")
    confidence = float(row[7] or 0.0)
    approved = row[8]

    determination = "CONDITIONAL"
    if approved is True:
        determination = "APPROVED"
    elif approved is False:
        determination = "REJECTED"
    elif "reject" in disposition.lower():
        determination = "REJECTED"

    match_score = confidence
    if requested_family and alloy_family and requested_family == alloy_family.lower():
        match_score += 0.3
    if approved is True:
        match_score += 0.1
    match_score += min(len(rationale_text) / 1000.0, 0.2)

    return PrecedentExemplar(
        mua_number=mua_number,
        material_name=material_name,
        alloy_family=alloy_family,
        media_category=media_category,
        determination=determination,
        category=category,
        rationale_text=rationale_text,
        confidence=confidence,
        match_ring=ring,
        match_score=round(match_score, 6),
    )


def _extract_phrases(issue: str, exemplars: list[PrecedentExemplar]):
    precedents: list[PrecedentMatch] = []
    for exemplar in exemplars:
        precedents.append(
            PrecedentMatch(
                mua_number=exemplar.mua_number,
                determination=exemplar.determination.lower(),
                rationale_text=exemplar.rationale_text,
                material_designation=exemplar.material_name,
                material_family=exemplar.alloy_family,
                environment=exemplar.media_category,
                relevance_score=max(min(exemplar.confidence, 1.0), 0.0),
            )
        )

    return extract_rationale_phrases(precedents, issue, limit=8)


def _compute_evidence_hash(
    *,
    issue: str,
    rating: str,
    media: str,
    material_class: str,
    exemplar_ids: list[str],
) -> str:
    key = "|".join(
        [
            issue,
            rating,
            media,
            material_class,
            ",".join(sorted(exemplar_ids)),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
