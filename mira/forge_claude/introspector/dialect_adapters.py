"""Dialect adapters for PostgreSQL, MySQL, and SQLite.

Normalizes type names, sampling queries, and constraint extraction
across database dialects.

Spec reference: Section 3.1
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Type normalization
# ---------------------------------------------------------------------------

# Canonical type families
_PG_TYPE_MAP = {
    "serial": "INTEGER",
    "bigserial": "BIGINT",
    "smallserial": "SMALLINT",
    "int2": "SMALLINT",
    "int4": "INTEGER",
    "int8": "BIGINT",
    "float4": "REAL",
    "float8": "DOUBLE",
    "numeric": "NUMERIC",
    "decimal": "DECIMAL",
    "bool": "BOOLEAN",
    "boolean": "BOOLEAN",
    "varchar": "VARCHAR",
    "character varying": "VARCHAR",
    "char": "CHAR",
    "character": "CHAR",
    "text": "TEXT",
    "bytea": "BLOB",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "timestamp without time zone": "TIMESTAMP",
    "timestamp with time zone": "TIMESTAMP",
    "timestamptz": "TIMESTAMP",
    "time": "TIME",
    "time without time zone": "TIME",
    "time with time zone": "TIME",
    "interval": "INTERVAL",
    "json": "JSON",
    "jsonb": "JSON",
    "uuid": "VARCHAR",
    "inet": "VARCHAR",
    "cidr": "VARCHAR",
    "macaddr": "VARCHAR",
    "point": "VARCHAR",
    "polygon": "VARCHAR",
    "array": "TEXT",
    "tsvector": "TEXT",
}

_MYSQL_TYPE_MAP = {
    "tinyint": "SMALLINT",
    "mediumint": "INTEGER",
    "int": "INTEGER",
    "bigint": "BIGINT",
    "float": "REAL",
    "double": "DOUBLE",
    "decimal": "DECIMAL",
    "bit": "BOOLEAN",
    "tinytext": "TEXT",
    "mediumtext": "TEXT",
    "longtext": "TEXT",
    "tinyblob": "BLOB",
    "mediumblob": "BLOB",
    "longblob": "BLOB",
    "enum": "VARCHAR",
    "set": "VARCHAR",
    "datetime": "TIMESTAMP",
    "year": "INTEGER",
    "json": "JSON",
}

_SQLITE_TYPE_MAP = {
    "integer": "INTEGER",
    "real": "REAL",
    "text": "TEXT",
    "blob": "BLOB",
    "numeric": "NUMERIC",
}


def normalize_type(raw_type: str, dialect: str) -> str:
    """Normalize a database-specific type to a canonical form.

    Args:
        raw_type: The raw type string from SQLAlchemy inspection.
        dialect: One of "sqlite", "postgresql", "mysql".

    Returns:
        Normalized type string.
    """
    lower = raw_type.lower().strip()

    # Strip length/precision specifiers: VARCHAR(100) -> varchar
    base = lower.split("(")[0].strip()

    type_map: dict[str, str] = {}
    if dialect == "postgresql":
        type_map = _PG_TYPE_MAP
    elif dialect == "mysql":
        type_map = _MYSQL_TYPE_MAP
    elif dialect == "sqlite":
        type_map = _SQLITE_TYPE_MAP

    if base in type_map:
        return type_map[base]

    # Fallback: return the original in uppercase
    return raw_type.upper()


def detect_dialect(db_url: str) -> str:
    """Detect database dialect from connection URL."""
    lower = db_url.lower()
    if lower.startswith("postgresql") or lower.startswith("postgres"):
        return "postgresql"
    if lower.startswith("mysql"):
        return "mysql"
    if lower.startswith("sqlite"):
        return "sqlite"
    return "unknown"


def get_sample_query(
    dialect: str,
    table_name: str,
    column_name: str,
    limit: int = 5,
) -> str:
    """Get a dialect-appropriate sampling query.

    Returns a parameterized SQL string with :limit parameter.
    """
    # All three dialects support this basic form
    return (
        f'SELECT DISTINCT "{column_name}" FROM "{table_name}" '
        f'WHERE "{column_name}" IS NOT NULL LIMIT :limit'
    )


def get_full_text_search_support(dialect: str) -> dict:
    """Report full-text search capabilities per dialect."""
    if dialect == "postgresql":
        return {
            "supported": True,
            "method": "tsvector",
            "index_type": "GIN",
            "query_syntax": "to_tsvector('english', col) @@ plainto_tsquery(:query)",
        }
    if dialect == "sqlite":
        return {
            "supported": True,
            "method": "FTS5",
            "index_type": "virtual_table",
            "query_syntax": "table_fts MATCH :query",
        }
    if dialect == "mysql":
        return {
            "supported": True,
            "method": "FULLTEXT",
            "index_type": "FULLTEXT",
            "query_syntax": "MATCH(col) AGAINST(:query IN BOOLEAN MODE)",
        }
    return {"supported": False}
