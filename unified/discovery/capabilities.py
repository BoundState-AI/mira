from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower()) if len(token) >= 3}


def _display_name(name: str) -> str:
    return name.split(".", 1)[-1]


class UnifiedCapabilities(BaseModel):
    db_tables: list[str] = Field(default_factory=list)
    db_columns: list[str] = Field(default_factory=list)
    doc_ids: list[str] = Field(default_factory=list)
    doc_entity_terms: list[str] = Field(default_factory=list)
    overlap_terms: list[str] = Field(default_factory=list)
    supported_sources: list[str] = Field(default_factory=list)
    supported_intents: list[str] = Field(default_factory=list)

    @classmethod
    def from_sources(cls, db_result: Any | None = None, document_features: list[Any] | None = None) -> "UnifiedCapabilities":
        features = document_features or []
        db_tables: list[str] = []
        db_columns: list[str] = []
        db_terms: set[str] = set()
        doc_ids: list[str] = []
        doc_terms: set[str] = set()
        supported_sources: list[str] = []
        supported_intents: set[str] = {"general_query"}

        if db_result is not None:
            supported_sources.append("db")
            manifest = getattr(db_result, "manifest", db_result)
            for table in getattr(manifest, "tables", []):
                table_name = _display_name(table.name)
                db_tables.append(table_name)
                db_terms.update(_tokenize(table_name))
                for column in getattr(table, "columns", []):
                    db_columns.append(f"{table_name}.{column.name}")
                    db_terms.update(_tokenize(column.name))
                    for sample in getattr(column, "sample_values", []):
                        db_terms.update(_tokenize(str(sample)))
            if db_tables:
                supported_intents.update({"material_lookup", "property_comparison"})

        if features:
            supported_sources.append("docs")
            for feature in features:
                doc_ids.append(feature.doc_id)
                doc_terms.update(_tokenize(feature.doc_type.value))
                doc_terms.update(_tokenize(" ".join(feature.tags)))
                entities = getattr(feature, "entities", None)
                if entities is not None:
                    for collection_name in ("materials", "standards", "hazards", "systems", "processes"):
                        values = getattr(entities, collection_name, [])
                        for value in values:
                            doc_terms.update(_tokenize(str(value)))
                flags = getattr(feature, "flags", None)
                if flags and getattr(flags, "has_measurements", False):
                    supported_intents.update({"compatibility_check", "compliance_check"})
                if getattr(feature, "spec_ref_count", 0) > 0:
                    supported_intents.add("compliance_check")

        overlap_terms = sorted(db_terms & doc_terms)
        if len(supported_sources) > 1:
            supported_sources.append("hybrid")
            supported_intents.update({"compatibility_check", "compliance_check"})

        return cls(
            db_tables=sorted(db_tables),
            db_columns=sorted(db_columns),
            doc_ids=sorted(doc_ids),
            doc_entity_terms=sorted(doc_terms),
            overlap_terms=overlap_terms,
            supported_sources=supported_sources,
            supported_intents=sorted(supported_intents),
        )
