"""Part 4: Duplicate analysis and drawing-level issues in V4."""
import pandas as pd
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

old_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_test.xlsx"
new_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_V4_v4.xlsx"

df_old = pd.read_excel(old_path, sheet_name='MIUL')
df_new = pd.read_excel(new_path, sheet_name='MIUL')

# Duplicate analysis in V4
print("="*80)
print("  V4 DUPLICATE PART NUMBER ANALYSIS")
print("="*80)
new_pn_counts = df_new['Part Number'].value_counts()
dupes = new_pn_counts[new_pn_counts > 1]
print(f"\nPart numbers appearing more than once: {len(dupes)}")
for pn, count in dupes.items():
    print(f"\n  {pn} appears {count} times:")
    rows = df_new[df_new['Part Number'] == pn]
    for idx, row in rows.iterrows():
        desc = str(row.get('Description', ''))[:60]
        desig = str(row.get('Designation', ''))
        matspec = str(row.get('Material Specification', ''))[:50]
        procspec = str(row.get('Process Specification', ''))[:50]
        qty = str(row.get('Quantity', ''))
        print(f"    Row {idx}: Desc='{desc}' Desig='{desig}' MatSpec='{matspec}' Qty={qty}")

# OLD duplicate analysis
print("\n\n" + "="*80)
print("  OLD DUPLICATE PART NUMBER ANALYSIS")
print("="*80)
old_pn_counts = df_old['Part Number'].value_counts()
old_dupes = old_pn_counts[old_pn_counts > 1]
print(f"\nPart numbers appearing more than once: {len(old_dupes)}")
for pn, count in old_dupes.items():
    print(f"  {pn} appears {count} times")

# Check if V4 has repeated "blocks" of data
print("\n\n" + "="*80)
print("  V4 DATA PATTERN ANALYSIS - REPEATED BLOCKS?")
print("="*80)
# Check if rows 0-N repeat at some point
if len(df_new) >= 40:
    first_20_pns = df_new['Part Number'].iloc[:20].tolist()
    print(f"First 20 PNs: {first_20_pns}")

    # Find where the pattern repeats
    first_pn = str(df_new['Part Number'].iloc[0])
    repeat_indices = df_new.index[df_new['Part Number'].astype(str) == first_pn].tolist()
    print(f"\n'{first_pn}' appears at indices: {repeat_indices}")

    # Check blocks
    if len(repeat_indices) > 1:
        block_sizes = []
        for i in range(len(repeat_indices) - 1):
            block_sizes.append(repeat_indices[i+1] - repeat_indices[i])
        block_sizes.append(len(df_new) - repeat_indices[-1])
        print(f"Block sizes: {block_sizes}")

        # Show first few PNs of each block
        for bi, start_idx in enumerate(repeat_indices):
            end_idx = repeat_indices[bi+1] if bi+1 < len(repeat_indices) else len(df_new)
            block_pns = df_new['Part Number'].iloc[start_idx:min(start_idx+5, end_idx)].tolist()
            print(f"\nBlock {bi} (rows {start_idx}-{end_idx-1}, size {end_idx-start_idx}):")
            print(f"  First 5 PNs: {block_pns}")

# Check if V4 rows are truly exact duplicates
print("\n\n" + "="*80)
print("  V4 EXACT DUPLICATE ROW CHECK")
print("="*80)
exact_dupes = df_new.duplicated(keep=False)
print(f"Total rows: {len(df_new)}")
print(f"Exact duplicate rows: {exact_dupes.sum()}")
print(f"Unique rows: {len(df_new.drop_duplicates())}")

# Are duplicates near-duplicates? (same PN, slightly different data)
print("\n\n" + "="*80)
print("  V4 NEAR-DUPLICATE ANALYSIS (by Part Number)")
print("="*80)
for pn, count in dupes.head(10).items():
    rows = df_new[df_new['Part Number'] == pn]
    # Check which columns differ between the duplicate rows
    if len(rows) > 1:
        r0 = rows.iloc[0]
        for i in range(1, len(rows)):
            ri = rows.iloc[i]
            diffs = []
            for col in df_new.columns:
                v0 = str(r0[col])
                vi = str(ri[col])
                if v0 != vi:
                    diffs.append(f"{col}: '{v0[:40]}' vs '{vi[:40]}'")
            if diffs:
                print(f"\n  {pn} - row 0 vs row {i} DIFFERS:")
                for d in diffs:
                    print(f"    {d}")
            else:
                print(f"\n  {pn} - row 0 vs row {i}: EXACT DUPLICATE")

# Designation naming comparison
print("\n\n" + "="*80)
print("  DESIGNATION NAMING DIFFERENCES")
print("="*80)
print("\nOLD designations (all unique):")
for d in sorted(df_old['Designation'].dropna().unique()):
    print(f"  '{d}'")
print("\nNEW designations (all unique):")
for d in sorted(df_new['Designation'].dropna().unique()):
    print(f"  '{d}'")

# Sheets in new file
xls_new = pd.ExcelFile(new_path)
print(f"\n\nNEW file sheets: {xls_new.sheet_names}")
for sheet in xls_new.sheet_names:
    if sheet != 'MIUL':
        df_sheet = pd.read_excel(new_path, sheet_name=sheet)
        print(f"\n--- Sheet '{sheet}' ({df_sheet.shape}) ---")
        print(df_sheet.head(20).to_string())
