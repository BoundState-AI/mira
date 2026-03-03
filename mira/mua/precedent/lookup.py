"""MUA precedent lookup against mua_precedent.precedent_counts."""

from __future__ import annotations

import logging
import re
from typing import Optional

from mira.core.db_config import get_db_connection_params

from .models import PrecedentSummary

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import availability is environment-dependent
    import psycopg2
except Exception:  # pragma: no cover
    psycopg2 = None


_MEDIA_CATEGORIES = {"hydrogen", "oxygen", "propellant", "inert", "air", "aqueous", "other"}

_H2_TERMS = ("H2", "GH2", "LH2", "HYDROGEN")
_O2_TERMS = ("O2", "GOX", "LOX", "OXYGEN", "ENRICHED", "OXY")
_PROPELLANT_TERMS = ("N2H4", "HYDRAZINE", "MMH", "MONOMETHYLHYDRAZINE", "N2O4", "NTO", "UDMH")
_INERT_TERMS = ("N2", "GN2", "LN2", "NITROGEN", "HE", "HELIUM", "ARGON", "AR", "NEON", "VACUUM", "SPACE")
_AIR_TERMS = ("AIR", "CABIN AIR", "AMBIENT", "ATMOSPHERE", "SEA LEVEL")
_AQUEOUS_TERMS = ("WATER", "H2O", "COOLANT", "DEIONIZED WATER")


def normalize_media_category(raw_media: str) -> str:
    """Normalize raw media string to category.

    Mirrors mua_precedent.normalize_media().
    """
    raw = (raw_media or "").strip()
    if not raw:
        return "other"

    media = raw.upper()
    lower = raw.lower()

    if lower in _MEDIA_CATEGORIES:
        return lower

    if any(term in media for term in _H2_TERMS):
        return "hydrogen"

    if any(term in media for term in _O2_TERMS):
        return "oxygen"
    if re.search(r"\b\d{1,3}\s*%\s*O2\b", media):
        return "oxygen"

    if any(term in media for term in _PROPELLANT_TERMS):
        return "propellant"

    if any(term in media for term in _INERT_TERMS):
        return "inert"

    if any(term in media for term in _AIR_TERMS):
        return "air"

    if any(term in media for term in _AQUEOUS_TERMS):
        return "aqueous"

    return "other"


def _row_to_summary(row: tuple) -> PrecedentSummary:
    return PrecedentSummary(
        issue=str(row[0] or ""),
        media_category=str(row[1] or ""),
        material_class=str(row[2] or ""),
        alloy_family=str(row[3] or ""),
        total_count=int(row[4] or 0),
        approved_count=int(row[5] or 0),
        rejected_count=int(row[6] or 0),
        distinct_materials=int(row[7] or 0),
        most_common_category=str(row[8] or ""),
    )


def _summary_from_records_ring(
    cur,
    *,
    issue_key: str,
    media_key: str,
    class_key: str,
    family_key: str,
    ring: str,
) -> Optional[PrecedentSummary]:
    sql = """
        SELECT
            COUNT(*)::int AS total_count,
            COUNT(*) FILTER (WHERE approved IS TRUE)::int AS approved_count,
            COUNT(*) FILTER (WHERE approved IS FALSE)::int AS rejected_count,
            COUNT(DISTINCT maptis_code)::int AS distinct_materials,
            COALESCE(
                (ARRAY_AGG(COALESCE(category, '') ORDER BY approval_date DESC NULLS LAST))[1],
                ''
            ) AS most_common_category
        FROM mua_precedent.mua_records
        WHERE issue = %s
          AND material_class = %s
          AND COALESCE(confidence, 0) >= 0.5
    """
    params: list[object] = [issue_key, class_key]

    if ring == "exact":
        sql += "\n          AND media_category = %s\n          AND COALESCE(alloy_family, '') = %s\n"
        params.extend([media_key, family_key])
    elif ring == "family":
        sql += "\n          AND COALESCE(alloy_family, '') = %s\n"
        params.append(family_key)

    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return None

    total_count = int(row[0] or 0)
    if total_count <= 0:
        return None

    return PrecedentSummary(
        issue=issue_key,
        media_category=media_key if ring == "exact" else "any",
        material_class=class_key,
        alloy_family=family_key if ring != "broad" else "",
        total_count=total_count,
        approved_count=int(row[1] or 0),
        rejected_count=int(row[2] or 0),
        distinct_materials=int(row[3] or 0),
        most_common_category=str(row[4] or ""),
    )


def lookup_precedent_with_ring(
    issue: str,
    media_category: str,
    material_class: str,
    alloy_family: str = "",
) -> tuple[Optional[PrecedentSummary], Optional[str]]:
    if psycopg2 is None:
        logger.warning("MUA precedent lookup unavailable: psycopg2 not installed.")
        return None, None

    issue_key = (issue or "").strip().upper()
    media_key = normalize_media_category(media_category)
    class_key = (material_class or "").strip().lower()
    family_key = (alloy_family or "").strip().lower()

    if not issue_key or not class_key:
        return None, None

    params = get_db_connection_params(database="mira")
    params.setdefault("connect_timeout", 2)

    ring1_sql = """
        SELECT
            issue,
            media_category,
            material_class,
            COALESCE(alloy_family, '') AS alloy_family,
            total_count,
            approved_count,
            rejected_count,
            distinct_materials,
            COALESCE(most_common_category, '') AS most_common_category
        FROM mua_precedent.precedent_counts
        WHERE issue = %s
          AND media_category = %s
          AND material_class = %s
          AND COALESCE(alloy_family, '') = %s
        LIMIT 1
    """

    ring2_sql = """
        SELECT
            issue,
            'any' AS media_category,
            material_class,
            COALESCE(alloy_family, '') AS alloy_family,
            SUM(total_count)::int AS total_count,
            SUM(approved_count)::int AS approved_count,
            SUM(rejected_count)::int AS rejected_count,
            SUM(distinct_materials)::int AS distinct_materials,
            COALESCE(
                (ARRAY_AGG(COALESCE(most_common_category, '') ORDER BY total_count DESC NULLS LAST))[1],
                ''
            ) AS most_common_category
        FROM mua_precedent.precedent_counts
        WHERE issue = %s
          AND material_class = %s
          AND COALESCE(alloy_family, '') = %s
        GROUP BY issue, material_class, COALESCE(alloy_family, '')
    """

    ring3_sql = """
        SELECT
            issue,
            'any' AS media_category,
            material_class,
            '' AS alloy_family,
            SUM(total_count)::int AS total_count,
            SUM(approved_count)::int AS approved_count,
            SUM(rejected_count)::int AS rejected_count,
            SUM(distinct_materials)::int AS distinct_materials,
            COALESCE(
                (ARRAY_AGG(COALESCE(most_common_category, '') ORDER BY total_count DESC NULLS LAST))[1],
                ''
            ) AS most_common_category
        FROM mua_precedent.precedent_counts
        WHERE issue = %s
          AND material_class = %s
        GROUP BY issue, material_class
    """

    try:
        conn = psycopg2.connect(**params)
    except Exception as exc:  # pragma: no cover - env-specific
        logger.warning("MUA precedent DB unavailable (%s). Proceeding without precedent.", exc)
        return None, None

    try:
        with conn.cursor() as cur:
            cur.execute(ring1_sql, (issue_key, media_key, class_key, family_key))
            row = cur.fetchone()
            if row:
                summary = _row_to_summary(row)
                if summary.total_count >= 3:
                    return summary, "exact"

            cur.execute(ring2_sql, (issue_key, class_key, family_key))
            row = cur.fetchone()
            if row:
                summary = _row_to_summary(row)
                if summary.total_count >= 3:
                    return summary, "family"

            cur.execute(ring3_sql, (issue_key, class_key))
            row = cur.fetchone()
            if row:
                return _row_to_summary(row), "broad"
    except Exception as exc:  # pragma: no cover - env-specific
        # Some local schemas aggregate precedent_counts differently. Fall back
        # to direct aggregation from mua_records to preserve availability.
        logger.warning(
            "MUA precedent query against materialized view failed (%s). "
            "Falling back to mua_precedent.mua_records aggregation.",
            exc,
        )
        try:
            with conn.cursor() as cur:
                summary = _summary_from_records_ring(
                    cur,
                    issue_key=issue_key,
                    media_key=media_key,
                    class_key=class_key,
                    family_key=family_key,
                    ring="exact",
                )
                if summary and summary.total_count >= 3:
                    return summary, "exact"

                summary = _summary_from_records_ring(
                    cur,
                    issue_key=issue_key,
                    media_key=media_key,
                    class_key=class_key,
                    family_key=family_key,
                    ring="family",
                )
                if summary and summary.total_count >= 3:
                    return summary, "family"

                summary = _summary_from_records_ring(
                    cur,
                    issue_key=issue_key,
                    media_key=media_key,
                    class_key=class_key,
                    family_key=family_key,
                    ring="broad",
                )
                if summary:
                    return summary, "broad"
        except Exception as fallback_exc:  # pragma: no cover - env-specific
            logger.warning(
                "MUA precedent fallback query failed (%s). Proceeding without precedent.",
                fallback_exc,
            )
            return None, None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    empty_summary = PrecedentSummary(
        issue=issue_key,
        media_category=media_key,
        material_class=class_key,
        alloy_family=family_key,
        total_count=0,
        approved_count=0,
        rejected_count=0,
        distinct_materials=0,
        most_common_category="",
    )
    return empty_summary, "broad"


def lookup_precedent(
    issue: str,
    media_category: str,
    material_class: str,
    alloy_family: str = "",
) -> Optional[PrecedentSummary]:
    """Query precedent database. Returns None if unavailable."""
    summary, _ = lookup_precedent_with_ring(
        issue=issue,
        media_category=media_category,
        material_class=material_class,
        alloy_family=alloy_family,
    )
    return summary
