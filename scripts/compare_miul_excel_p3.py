"""Part 3: Row-by-row comparison with correct column names."""
import pandas as pd
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

old_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_test.xlsx"
new_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_V4_v4.xlsx"

df_old = pd.read_excel(old_path, sheet_name='MIUL')
df_new = pd.read_excel(new_path, sheet_name='MIUL')

# Part Number row-by-row (using correct column names)
print("="*80)
print("  PART NUMBER + KEY FIELDS ROW-BY-ROW (first 30 rows)")
print("="*80)

# OLD uses "Part Description", NEW uses "Description"
for i in range(min(30, max(len(df_old), len(df_new)))):
    old_pn = str(df_old.iloc[i]['Part Number']) if i < len(df_old) else 'N/A'
    new_pn = str(df_new.iloc[i]['Part Number']) if i < len(df_new) else 'N/A'
    old_desc = str(df_old.iloc[i]['Part Description']) if i < len(df_old) else 'N/A'
    new_desc = str(df_new.iloc[i]['Description']) if i < len(df_new) else 'N/A'
    old_desig = str(df_old.iloc[i]['Designation']) if i < len(df_old) else 'N/A'
    new_desig = str(df_new.iloc[i]['Designation']) if i < len(df_new) else 'N/A'
    old_nha = str(df_old.iloc[i]['NHA']) if i < len(df_old) else 'N/A'
    new_nha = str(df_new.iloc[i]['NHA']) if i < len(df_new) else 'N/A'

    print(f"\nRow {i}:")
    print(f"  OLD PN: {old_pn:30s} | NEW PN: {new_pn}")
    print(f"  OLD Desc: {old_desc[:60]:60s}")
    print(f"  NEW Desc: {new_desc[:60]:60s}")
    print(f"  OLD Desig: {old_desig:30s} | NEW Desig: {new_desig}")
    print(f"  OLD NHA: {old_nha:30s} | NEW NHA: {new_nha}")

# Check if part numbers match between files even if ordering differs
print("\n\n" + "="*80)
print("  PART NUMBER SET COMPARISON")
print("="*80)
old_pns = set(df_old['Part Number'].dropna().astype(str).unique())
new_pns = set(df_new['Part Number'].dropna().astype(str).unique())
print(f"\nOLD unique part numbers: {len(old_pns)}")
print(f"NEW unique part numbers: {len(new_pns)}")
print(f"\nPart numbers only in OLD ({len(old_pns - new_pns)}):")
for pn in sorted(old_pns - new_pns):
    print(f"  {pn}")
print(f"\nPart numbers only in NEW ({len(new_pns - old_pns)}):")
for pn in sorted(new_pns - old_pns):
    print(f"  {pn}")
print(f"\nPart numbers in BOTH: {len(old_pns & new_pns)}")

# For matching part numbers, compare field values
print("\n\n" + "="*80)
print("  FIELD-BY-FIELD COMPARISON FOR MATCHING PART NUMBERS")
print("="*80)
common_pns = sorted(old_pns & new_pns)
for pn in common_pns[:25]:
    old_rows = df_old[df_old['Part Number'].astype(str) == pn]
    new_rows = df_new[df_new['Part Number'].astype(str) == pn]

    if len(old_rows) != len(new_rows):
        print(f"\n  {pn}: OLD has {len(old_rows)} rows, NEW has {len(new_rows)} rows")

    # Compare first row of each
    if len(old_rows) > 0 and len(new_rows) > 0:
        or0 = old_rows.iloc[0]
        nr0 = new_rows.iloc[0]

        diffs = []
        # Designation
        if str(or0.get('Designation', 'N/A')) != str(nr0.get('Designation', 'N/A')):
            diffs.append(f"    Designation: OLD='{or0.get('Designation', 'N/A')}' | NEW='{nr0.get('Designation', 'N/A')}'")
        # Material Spec
        if str(or0.get('Material Specification', 'N/A')) != str(nr0.get('Material Specification', 'N/A')):
            diffs.append(f"    Mat Spec: OLD='{or0.get('Material Specification', 'N/A')}' | NEW='{nr0.get('Material Specification', 'N/A')}'")
        # Process Spec
        if str(or0.get('Process Specification', 'N/A')) != str(nr0.get('Process Specification', 'N/A')):
            diffs.append(f"    Proc Spec: OLD='{str(or0.get('Process Specification', 'N/A'))[:80]}' | NEW='{str(nr0.get('Process Specification', 'N/A'))[:80]}'")
        # Material Form
        if str(or0.get('Material Form', 'N/A')) != str(nr0.get('Material Form', 'N/A')):
            diffs.append(f"    Mat Form: OLD='{or0.get('Material Form', 'N/A')}' | NEW='{nr0.get('Material Form', 'N/A')}'")

        if diffs:
            print(f"\n  {pn} DIFFERENCES:")
            for d in diffs:
                print(d)

# Tree structure analysis
print("\n\n" + "="*80)
print("  TREE STRUCTURE (OLD FILE - Index/Parent)")
print("="*80)
for i in range(min(30, len(df_old))):
    row = df_old.iloc[i]
    idx = row['Index']
    par = row['Parent']
    pn = row['Part Number']
    desc = str(row['Part Description'])[:50]
    nha = row['NHA']
    print(f"  Idx={idx:3.0f} Parent={str(par):5s} PN={str(pn):20s} NHA={str(nha):15s} {desc}")

print("\n\n" + "="*80)
print("  NEW FILE - ROW ORDER (no tree structure)")
print("="*80)
for i in range(min(30, len(df_new))):
    row = df_new.iloc[i]
    pn = row['Part Number']
    desc = str(row['Description'])[:50]
    nha = row['NHA']
    qty = row.get('Quantity', 'N/A')
    print(f"  Row={i:3d} PN={str(pn):20s} NHA={str(nha):15s} Qty={str(qty):5s} {desc}")

# Summary statistics
print("\n\n" + "="*80)
print("  SUMMARY STATISTICS")
print("="*80)

# Material data completeness
for col in ['Designation', 'Material Specification', 'Process Specification', 'Material Form', 'Material Code']:
    old_filled = df_old[col].dropna().shape[0]
    new_filled = df_new[col].dropna().shape[0]
    print(f"  {col:25s}: OLD filled={old_filled:3d}/{len(df_old):3d} ({100*old_filled/len(df_old):5.1f}%), NEW filled={new_filled:3d}/{len(df_new):3d} ({100*new_filled/len(df_new):5.1f}%)")

# Cure code columns
for col in ['FLAM', 'SCC', 'CORR', 'TVS', 'TOX', 'FS']:
    old_filled = df_old[col].dropna().shape[0]
    new_filled = df_new[col].dropna().shape[0]
    print(f"  {col:25s}: OLD filled={old_filled:3d}/{len(df_old):3d} ({100*old_filled/len(df_old):5.1f}%), NEW filled={new_filled:3d}/{len(df_new):3d} ({100*new_filled/len(df_new):5.1f}%)")
