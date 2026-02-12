#!/usr/bin/env python3
"""Check FC tables structure and data."""
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

# Check fluid_compatibility_tests schema
print("fluid_compatibility_tests columns:")
cur.execute("""
    SELECT column_name, data_type, character_maximum_length
    FROM information_schema.columns
    WHERE table_schema='maptis' AND table_name='fluid_compatibility_tests'
    ORDER BY ordinal_position
""")
for col, dtype, max_len in cur.fetchall():
    if max_len:
        print(f"  {col}: {dtype}({max_len})")
    else:
        print(f"  {col}: {dtype}")

# Check fluid_compatibility_results schema
print("\nfluid_compatibility_results columns:")
cur.execute("""
    SELECT column_name, data_type, character_maximum_length
    FROM information_schema.columns
    WHERE table_schema='maptis' AND table_name='fluid_compatibility_results'
    ORDER BY ordinal_position
""")
for col, dtype, max_len in cur.fetchall():
    if max_len:
        print(f"  {col}: {dtype}({max_len})")
    else:
        print(f"  {col}: {dtype}")

# Check row counts
cur.execute("SELECT COUNT(*) FROM fluid_compatibility_tests")
fc_tests = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM fluid_compatibility_results")
fc_results = cur.fetchone()[0]

print(f"\nCurrent data:")
print(f"  fluid_compatibility_tests: {fc_tests:,} rows")
print(f"  fluid_compatibility_results: {fc_results:,} rows")

# Sample data
if fc_tests > 0:
    print("\nSample test data:")
    cur.execute("SELECT * FROM fluid_compatibility_tests LIMIT 3")
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]
    for row in rows:
        print(f"  {dict(zip(cols, row))}")

cur.close()
conn.close()
