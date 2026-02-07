#!/usr/bin/env python3
"""Check bok.mua_precedents table for 6061."""

import sys
sys.path.insert(0, r"C:\BoundState")

import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from mira.core.db_config import get_db_connection_params
    params = get_db_connection_params()
except ImportError:
    import os
    params = {
        "host": os.environ.get("POSTGRES_HOST", "localhost"),
        "port": int(os.environ.get("POSTGRES_PORT", "5432")),
        "database": os.environ.get("POSTGRES_DB", "mira"),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", "postgres"),
    }

conn = psycopg2.connect(**params)
cur = conn.cursor(cursor_factory=RealDictCursor)

print("=" * 70)
print("Checking bok.mua_precedents table")
print("=" * 70)

# Check if table exists
cur.execute("""
    SELECT COUNT(*) as cnt FROM information_schema.tables 
    WHERE table_schema = 'bok' AND table_name = 'mua_precedents'
""")
result = cur.fetchone()
if result['cnt'] == 0:
    print("ERROR: bok.mua_precedents table does not exist!")
    sys.exit(1)

# Count total records
cur.execute("SELECT COUNT(*) as cnt FROM bok.mua_precedents")
print(f"Total MUA precedents: {cur.fetchone()['cnt']}")

# Search for 6061
print("\n--- MUAs containing '6061' ---")
cur.execute("""
    SELECT mua_number, material_name, determination, 
           pressure_psi_max, o2_concentration_pct
    FROM bok.mua_precedents
    WHERE LOWER(material_name) LIKE '%6061%'
    ORDER BY parser_confidence DESC
    LIMIT 10
""")
rows = cur.fetchall()
print(f"Found {len(rows)} MUAs with '6061' in material_name:")
for row in rows:
    print(f"  {row['mua_number']}: {row['material_name']}")
    print(f"    Determination: {row['determination']}, O2%: {row['o2_concentration_pct']}")

# Check what's being returned for oxygen queries (top 10 approved)
print("\n--- Top 10 APPROVED MUAs for O2 queries ---")
cur.execute("""
    SELECT mua_number, material_name, determination, 
           pressure_psi_max, o2_concentration_pct, parser_confidence
    FROM bok.mua_precedents
    WHERE determination IN ('APPROVED', 'CONDITIONAL')
    ORDER BY is_reviewed DESC, parser_confidence DESC, parsed_date DESC
    LIMIT 10
""")
rows = cur.fetchall()
for row in rows:
    print(f"  {row['mua_number']}: {row['material_name'][:50]}")
    print(f"    Det: {row['determination']}, O2%: {row['o2_concentration_pct']}, Conf: {row['parser_confidence']}")

cur.close()
conn.close()
print("\nDone.")
