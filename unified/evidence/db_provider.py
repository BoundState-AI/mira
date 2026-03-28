from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import create_engine, inspect, text

from unified.schema import AuthorityClass, EvidenceSourceType, ICEvidenceItem, ProvenanceRecord


def _tokenize(text_value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", text_value.lower()) if len(token) >= 2]


class DBEvidenceProvider:
    def __init__(
        self,
        db_url: str,
        tables: list[str] | None = None,
        row_scan_limit: int = 200,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        self._engine = create_engine(db_url, future=True, **kwargs)
        self._tables = tables
        self._row_scan_limit = row_scan_limit

    def get_evidence(self, query: str, limit: int = 20, intent: str | None = None) -> list[ICEvidenceItem]:
        query_terms = set(_tokenize(query))
        inspector = inspect(self._engine)
        tables = self._tables or inspector.get_table_names()
        scored: list[ICEvidenceItem] = []

        with self._engine.connect() as connection:
            for table_name in tables:
                rows = connection.execute(
                    text(f'SELECT * FROM "{table_name}" LIMIT :lim'),
                    {"lim": self._row_scan_limit},
                ).mappings()
                for index, row in enumerate(rows):
                    row_dict = dict(row)
                    row_text = " ".join("" if value is None else str(value) for value in row_dict.values())
                    row_terms = set(_tokenize(row_text))
                    overlap = query_terms & row_terms
                    if not overlap:
                        continue
                    score = min(1.0, len(overlap) / max(1, len(query_terms)))
                    authority_value = str(row_dict.get("authority_class", "")).lower()
                    authority_class = AuthorityClass(authority_value) if authority_value in AuthorityClass._value2member_map_ else AuthorityClass.PRIMARY_TEST_DATA
                    primary_key = row_dict.get("id") or row_dict.get("record_id") or row_dict.get("name") or str(index)
                    scored.append(
                        ICEvidenceItem(
                            evidence_id=f"db:{table_name}:{primary_key}",
                            source_type=EvidenceSourceType.DB,
                            source_label=table_name,
                            source_id=str(primary_key),
                            content=json.dumps(row_dict, default=str, sort_keys=True),
                            snippet=row_text[:240],
                            score=score,
                            authority_class=authority_class,
                            provenance=ProvenanceRecord(
                                source_doc_id=f"db://{table_name}/{primary_key}",
                                location=table_name,
                                extraction_method="db_query",
                                extraction_confidence=1.0,
                                authority_class=authority_class,
                            ),
                            claim_key=str(row_dict.get("property_name") or row_dict.get("name") or table_name),
                            claim_value=row_dict.get("value") or row_dict.get("requirement") or row_dict.get("name"),
                            metadata={"table": table_name, "row": row_dict, "intent": intent},
                        )
                    )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]

