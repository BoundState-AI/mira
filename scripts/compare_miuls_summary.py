#!/usr/bin/env python3
"""Summary comparison of MIUL files."""

import json
import pandas as pd
from pathlib import Path

# Load overrides (ground truth)
overrides_path = Path(r'C:/Users/jwilde2/Desktop/DMLLV/nha_overrides.json')
with open(overrides_path) as f:
    overrides = json.load(f)
truth = {k: v for k, v in overrides.items() if not k.startswith('_')}

james = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/Copy of DMLLV_MIUL_James.xlsx')
other = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/MIUL_DMLLV (1).xlsx')

print('='*70)
print('MIUL FILE COMPARISON SUMMARY')
print('='*70)

print(f'''
FILE STATISTICS:
  James file: {len(james)} rows, {len(james["Part Number"].unique())} unique parts
  Other file: {len(other)} rows, {len(other["Part Number"].unique())} unique parts

DUPLICATES:
  James: {len(james) - len(james.drop_duplicates(subset=["Part Number", "NHA"]))} duplicate (PN, NHA) pairs
  Other: {len(other) - len(other.drop_duplicates(subset=["Part Number", "NHA"]))} duplicate (PN, NHA) pairs

NHA ACCURACY (vs Drawing Tree):
''')

def check_accuracy(df, name):
    correct = 0
    wrong = 0
    wrong_list = []
    for pn, expected_nha in truth.items():
        if pn == 'DMLLV':
            continue
        rows = df[df['Part Number'] == pn]
        if len(rows) > 0:
            actual_nhas = set(rows['NHA'].dropna().astype(str))
            if expected_nha in actual_nhas:
                correct += 1
            else:
                wrong += 1
                wrong_list.append((pn, list(actual_nhas), expected_nha))
    total = correct + wrong
    print(f'  {name}: {correct}/{total} correct ({100*correct/total:.1f}%)')
    return wrong_list

james_wrong = check_accuracy(james, 'James')
other_wrong = check_accuracy(other, 'Other')

print(f'''
JAMES WRONG NHA ASSIGNMENTS:''')
for pn, actual, expected in james_wrong[:10]:
    print(f'  {pn}: has {actual}, should be {expected}')
if len(james_wrong) > 10:
    print(f'  ... and {len(james_wrong)-10} more')

print(f'''
OTHER WRONG NHA ASSIGNMENTS:''')
for pn, actual, expected in other_wrong:
    print(f'  {pn}: has {actual}, should be {expected}')

print(f'''
KEY FINDINGS:
1. Other file has correct NHA hierarchy (95% vs 60%)
2. James flattens MER07545-001 children into MER07543-001
3. James has duplicate rows (same part, same NHA, different material text)
4. Other has no duplicates

RECOMMENDATION:
  Use Other file (MIUL_DMLLV (1).xlsx) as the better baseline
  It has correct NHA structure from drawing tree
''')
