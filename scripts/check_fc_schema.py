#!/usr/bin/env python3
"""Check database schema for FC compatibility data."""
import psycopg2

conn = psycopg2.connect(
    host='localhost',
    port=5432,
    database='mira',
    user='postgres',
    password='postgres',
    options='-c search_path=maptis,public'
)

cur = conn.cursor()

# Check materials table columns
print("Materials table columns:")
cur.execute("""
    SELECT column_name, data_type, character_maximum_length
    FROM information_schema.columns
    WHERE table_schema='maptis' AND table_name='materials'
    ORDER BY ordinal_position
""")
for col, dtype, max_len in cur.fetchall():
    if max_len:
        print(f"  {col}: {dtype}({max_len})")
    else:
        print(f"  {col}: {dtype}")

# Check for FC-related tables
print("\nFC-related tables:")
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema='maptis'
    AND (table_name LIKE '%fluid%' OR table_name LIKE '%compat%' OR table_name LIKE '%fc%')
""")
fc_tables = cur.fetchall()
if fc_tables:
    for (table,) in fc_tables:
        print(f"  {table}")
else:
    print("  None found")

# Check all tables in maptis schema
print("\nAll MAPTIS tables:")
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema='maptis'
    ORDER BY table_name
""")
for (table,) in cur.fetchall():
    print(f"  {table}")

cur.close()
conn.close()
