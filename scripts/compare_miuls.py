#!/usr/bin/env python3
"""Compare two MIUL files to understand part count differences."""

import pandas as pd

james = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/Copy of DMLLV_MIUL_James.xlsx')
other = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/MIUL_DMLLV (1).xlsx')

# Row count per drawing (NHA)
print('=== ROWS PER DRAWING (James) ===')
james_by_nha = james.groupby('NHA').size().sort_values(ascending=False)
for nha, count in james_by_nha.head(15).items():
    print(f'  {nha}: {count} rows')

print(f'\n=== ROWS PER DRAWING (Other) ===')
other_by_nha = other.groupby('NHA').size().sort_values(ascending=False)
for nha, count in other_by_nha.head(15).items():
    print(f'  {nha}: {count} rows')

# Compare specific drawings
print(f'\n=== COMPARISON BY NHA (differences only) ===')
all_nha = set(james_by_nha.index) | set(other_by_nha.index)
for nha in sorted(all_nha):
    j = james_by_nha.get(nha, 0)
    o = other_by_nha.get(nha, 0)
    if j != o:
        print(f'  {nha}: James={j}, Other={o}, diff={j-o}')

# Look at rows with materials in both
print(f'\n=== MATERIAL COVERAGE ===')
james_with_mat = james[james['Designation'].notna() & (james['Designation'] != '')]
other_with_mat = other[other['Designation'].notna() & (other['Designation'] != '')]
print(f'James rows with Designation: {len(james_with_mat)}/{len(james)}')
print(f'Other rows with Designation: {len(other_with_mat)}/{len(other)}')

# Look at total parts (unique part numbers with materials)
print(f'\n=== UNIQUE PARTS WITH MATERIALS ===')
james_parts_mat = set(james_with_mat['Part Number'].dropna().astype(str))
other_parts_mat = set(other_with_mat['Part Number'].dropna().astype(str))
print(f'James unique parts with material: {len(james_parts_mat)}')
print(f'Other unique parts with material: {len(other_parts_mat)}')
