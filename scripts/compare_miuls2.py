#!/usr/bin/env python3
"""Deep comparison of two MIUL files."""

import pandas as pd

james = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/Copy of DMLLV_MIUL_James.xlsx')
other = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/MIUL_DMLLV (1).xlsx')

# Check for duplicate part numbers in each file
print('=== DUPLICATE PART NUMBERS ===')
james_dups = james['Part Number'].value_counts()
james_dups = james_dups[james_dups > 1]
print(f'James has {len(james_dups)} part numbers appearing multiple times:')
for pn, count in james_dups.head(10).items():
    print(f'  {pn}: {count}x')

other_dups = other['Part Number'].value_counts()
other_dups = other_dups[other_dups > 1]
print(f'\nOther has {len(other_dups)} part numbers appearing multiple times:')
for pn, count in other_dups.head(10).items():
    print(f'  {pn}: {count}x')

# Look at a specific example - MER07543-001 has 36 vs 20 rows
print(f'\n=== MER07543-001 BREAKDOWN ===')
james_543 = james[james['NHA'] == 'MER07543-001']
other_543 = other[other['NHA'] == 'MER07543-001']

print(f'James parts under MER07543-001: {len(james_543)}')
print(f'Other parts under MER07543-001: {len(other_543)}')

# What parts does James have under 543?
james_543_parts = set(james_543['Part Number'].dropna().astype(str))
other_543_parts = set(other_543['Part Number'].dropna().astype(str))

only_james_543 = james_543_parts - other_543_parts
only_other_543 = other_543_parts - james_543_parts

print(f'\nParts under 543 only in James: {len(only_james_543)}')
for p in sorted(only_james_543):
    print(f'  {p}')

print(f'\nParts under 543 only in Other: {len(only_other_543)}')
for p in sorted(only_other_543):
    print(f'  {p}')

# Check MER07576 vs MER07576-001
print(f'\n=== MER07576 vs MER07576-001 ===')
james_576 = james[james['NHA'] == 'MER07576']
other_576 = other[other['NHA'] == 'MER07576-001']
print(f'James NHA=MER07576: {len(james_576)} rows')
print(f'Other NHA=MER07576-001: {len(other_576)} rows')

# Check MER07545-001 - Other has 8, James has 0
print(f'\n=== MER07545-001 (in Other but not James) ===')
other_545 = other[other['NHA'] == 'MER07545-001']
print(f'Parts under MER07545-001 in Other:')
for idx, row in other_545.iterrows():
    print(f"  {row['Part Number']}: {row['Part Description']}")

# Where does James put those parts?
other_545_parts = list(other_545['Part Number'].dropna().astype(str))
print(f'\nWhere James puts these parts:')
for pn in other_545_parts:
    james_rows = james[james['Part Number'] == pn]
    if len(james_rows) > 0:
        for idx, row in james_rows.iterrows():
            print(f"  {pn} -> NHA={row['NHA']}")
    else:
        print(f"  {pn} -> NOT FOUND in James")
