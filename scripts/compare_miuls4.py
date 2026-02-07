#!/usr/bin/env python3
"""Analyze row count differences - duplicates and EPL parts."""

import pandas as pd

james = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/Copy of DMLLV_MIUL_James.xlsx')
other = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/MIUL_DMLLV (1).xlsx')

print('=== ROW COUNT ANALYSIS ===')
print(f'James total rows: {len(james)}')
print(f'Other total rows: {len(other)}')
print(f'Difference: {len(james) - len(other)} extra rows in James')

# How many are duplicates in James?
james_unique = james.drop_duplicates(subset=['Part Number', 'NHA'])
print(f'\nJames after dedup on (Part Number, NHA): {len(james_unique)} rows')
print(f'  Duplicates removed: {len(james) - len(james_unique)}')

# Look at duplicates in detail
print(f'\n=== DUPLICATE ROWS IN JAMES ===')
dup_mask = james.duplicated(subset=['Part Number', 'NHA'], keep=False)
dups = james[dup_mask].sort_values(['Part Number', 'NHA'])
print(f'Total duplicate rows: {len(dups)}')

# Group duplicates
for (pn, nha), group in dups.groupby(['Part Number', 'NHA']):
    if len(group) > 1:
        print(f'\n{pn} under {nha}: {len(group)} copies')
        for idx, row in group.iterrows():
            desc = str(row['Part Description'])[:40] if pd.notna(row['Part Description']) else 'N/A'
            mat = str(row['Designation'])[:30] if pd.notna(row['Designation']) else 'N/A'
            print(f'  Row {row["Index"]}: {desc} | Mat: {mat}')

# Check for EPL-sourced parts (standard parts, hardware)
print(f'\n=== EPL/STANDARD PARTS ===')
# Look for MS, NAS, AN prefixes
standard_prefixes = ['MS', 'NAS', 'AN', 'WHM', 'WSM', 'EH-', 'M12133', '6.', '5.']
james_standard = james[james['Part Number'].astype(str).str.contains('|'.join(standard_prefixes), na=False, case=False)]
other_standard = other[other['Part Number'].astype(str).str.contains('|'.join(standard_prefixes), na=False, case=False)]

print(f'James standard/hardware parts: {len(james_standard)}')
print(f'Other standard/hardware parts: {len(other_standard)}')

# List them
print(f'\nJames standard parts:')
for pn in sorted(james_standard['Part Number'].unique()):
    count = len(james_standard[james_standard['Part Number'] == pn])
    print(f'  {pn}: {count}x')

print(f'\nOther standard parts:')
for pn in sorted(other_standard['Part Number'].unique()):
    count = len(other_standard[other_standard['Part Number'] == pn])
    print(f'  {pn}: {count}x')
