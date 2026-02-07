#!/usr/bin/env python3
"""Check NHA hierarchy against drawing tree."""

import json
import pandas as pd
from pathlib import Path

# Load overrides (ground truth from drawing tree)
overrides_path = Path(r'C:/Users/jwilde2/Desktop/DMLLV/nha_overrides.json')
with open(overrides_path) as f:
    overrides = json.load(f)

# Ground truth NHA mapping
truth = {}
for k, v in overrides.items():
    if not k.startswith('_'):
        truth[k] = v

james = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/Copy of DMLLV_MIUL_James.xlsx')
other = pd.read_excel(r'C:/Users/jwilde2/Desktop/DMLLV/MIUL_DMLLV (1).xlsx')

# Check 545 children
print('=== MER07545-001 CHILDREN (from drawing tree) ===')
children_of_545 = [k for k, v in truth.items() if v == 'MER07545-001']
print(f'Parts that should be under MER07545-001:')
for c in sorted(children_of_545):
    print(f'  {c}')

# Check what NHA each file assigns
print(f'\n=== NHA ASSIGNMENTS FOR 545 CHILDREN ===')
for pn in sorted(children_of_545):
    james_rows = james[james['Part Number'] == pn]
    other_rows = other[other['Part Number'] == pn]

    james_nhas = list(james_rows['NHA'].dropna().astype(str).unique())
    other_nhas = list(other_rows['NHA'].dropna().astype(str).unique())

    print(f'{pn}:')
    print(f'  Truth:  MER07545-001')
    print(f'  James:  {james_nhas}')
    print(f'  Other:  {other_nhas}')

# Check overall NHA accuracy
print(f'\n=== OVERALL NHA ACCURACY ===')
def check_accuracy(df, name):
    correct = 0
    wrong = 0
    missing = 0
    for pn, expected_nha in truth.items():
        if pn == 'DMLLV':
            continue
        rows = df[df['Part Number'] == pn]
        if len(rows) == 0:
            missing += 1
        else:
            # Check if any row has correct NHA
            actual_nhas = set(rows['NHA'].dropna().astype(str))
            if expected_nha in actual_nhas:
                correct += 1
            else:
                wrong += 1
    total = correct + wrong + missing
    print(f'{name}: {correct}/{total} correct NHA ({100*correct/total:.1f}%)')
    print(f'  Wrong: {wrong}, Missing: {missing}')

check_accuracy(james, 'James')
check_accuracy(other, 'Other')

# Check for key structural differences
print(f'\n=== CHILDREN OF MER07543-001 (from truth) ===')
children_543 = [k for k, v in truth.items() if v == 'MER07543-001']
for c in sorted(children_543):
    print(f'  {c}')
