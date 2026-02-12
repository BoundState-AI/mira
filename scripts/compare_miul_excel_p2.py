"""Part 2: Detailed row-by-row comparison."""
import pandas as pd
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

old_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_test.xlsx"
new_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_V4_v4.xlsx"

df_old = pd.read_excel(old_path, sheet_name='MIUL')
df_new = pd.read_excel(new_path, sheet_name='MIUL')

pd.set_option('display.max_columns', None)
pd.set_option('display.max_colwidth', 60)
pd.set_option('display.width', 400)

print("="*80)
print("  NEW V4 FILE - First 15 rows")
print("="*80)
print(df_new.head(15).to_string())

print("\n\n" + "="*80)
print("  OLD FILE - First 15 rows")
print("="*80)
print(df_old.head(15).to_string())

print("\n\n" + "="*80)
print("  COLUMN-BY-COLUMN COMPARISON")
print("="*80)

old_cols = list(df_old.columns)
new_cols = list(df_new.columns)

print(f"\nOLD columns ({len(old_cols)}):")
for i, c in enumerate(old_cols):
    print(f"  [{i:2d}] {c}")

print(f"\nNEW columns ({len(new_cols)}):")
for i, c in enumerate(new_cols):
    print(f"  [{i:2d}] {c}")

print(f"\nColumns ONLY in OLD: {set(old_cols) - set(new_cols)}")
print(f"Columns ONLY in NEW: {set(new_cols) - set(old_cols)}")

# Check NHA column specifically
print("\n\n" + "="*80)
print("  NHA COLUMN COMPARISON")
print("="*80)
print(f"\nOLD NHA values (non-null): {df_old['NHA'].dropna().shape[0]}/{len(df_old)}")
print(f"OLD NHA unique: {df_old['NHA'].dropna().unique().tolist()}")
print(f"\nNEW NHA values (non-null): {df_new['NHA'].dropna().shape[0]}/{len(df_new)}")
print(f"NEW NHA unique: {df_new['NHA'].dropna().unique().tolist()}")

# Check Material Code column
print("\n\n" + "="*80)
print("  MATERIAL CODE COMPARISON")
print("="*80)
print(f"\nOLD Material Code (non-null): {df_old['Material Code'].dropna().shape[0]}/{len(df_old)}")
if df_old['Material Code'].dropna().shape[0] > 0:
    print(f"OLD Material Code values: {df_old['Material Code'].dropna().unique().tolist()}")
print(f"\nNEW Material Code (non-null): {df_new['Material Code'].dropna().shape[0]}/{len(df_new)}")
if df_new['Material Code'].dropna().shape[0] > 0:
    print(f"NEW Material Code values: {df_new['Material Code'].dropna().unique().tolist()}")

# Compare Part Numbers row by row
print("\n\n" + "="*80)
print("  PART NUMBER + DESIGNATION ROW-BY-ROW (first 30 rows)")
print("="*80)
for i in range(min(30, max(len(df_old), len(df_new)))):
    old_pn = df_old.iloc[i]['Part Number'] if i < len(df_old) else 'N/A'
    new_pn = df_new.iloc[i]['Part Number'] if i < len(df_new) else 'N/A'
    old_desc = df_old.iloc[i]['Part Description'] if i < len(df_old) else 'N/A'
    new_desc = df_new.iloc[i]['Part Description'] if i < len(df_new) else 'N/A'
    old_desig = df_old.iloc[i]['Designation'] if i < len(df_old) else 'N/A'
    new_desig = df_new.iloc[i]['Designation'] if i < len(df_new) else 'N/A'
    old_nha = df_old.iloc[i]['NHA'] if i < len(df_old) else 'N/A'
    new_nha = df_new.iloc[i]['NHA'] if i < len(df_new) else 'N/A'
    old_matspec = df_old.iloc[i]['Material Specification'] if i < len(df_old) else 'N/A'
    new_matspec = df_new.iloc[i]['Material Specification'] if i < len(df_new) else 'N/A'

    pn_match = "OK" if str(old_pn) == str(new_pn) else "DIFF"
    desc_match = "OK" if str(old_desc) == str(new_desc) else "DIFF"
    desig_match = "OK" if str(old_desig) == str(new_desig) else "DIFF"

    if pn_match != "OK" or desc_match != "OK" or desig_match != "OK":
        print(f"\nRow {i}: PN={pn_match} DESC={desc_match} DESIG={desig_match}")
        if pn_match != "OK":
            print(f"  Part Number:  OLD='{old_pn}' | NEW='{new_pn}'")
        if desc_match != "OK":
            print(f"  Description:  OLD='{old_desc}' | NEW='{new_desc}'")
        if desig_match != "OK":
            print(f"  Designation:  OLD='{old_desig}' | NEW='{new_desig}'")
        print(f"  NHA:          OLD='{old_nha}' | NEW='{new_nha}'")
        print(f"  Mat Spec:     OLD='{old_matspec}' | NEW='{new_matspec}'")

# Check sheets
print("\n\n" + "="*80)
print("  SHEETS COMPARISON")
print("="*80)
xls_old = pd.ExcelFile(old_path)
xls_new = pd.ExcelFile(new_path)
print(f"OLD sheets: {xls_old.sheet_names}")
print(f"NEW sheets: {xls_new.sheet_names}")

if 'Summary' in xls_old.sheet_names:
    df_old_summary = pd.read_excel(old_path, sheet_name='Summary')
    print(f"\nOLD Summary sheet ({df_old_summary.shape}):")
    print(df_old_summary.to_string())

if 'Summary' in xls_new.sheet_names:
    df_new_summary = pd.read_excel(new_path, sheet_name='Summary')
    print(f"\nNEW Summary sheet ({df_new_summary.shape}):")
    print(df_new_summary.to_string())

# Null analysis
print("\n\n" + "="*80)
print("  NULL/EMPTY VALUE ANALYSIS")
print("="*80)
for col in sorted(set(old_cols) & set(new_cols)):
    old_nulls = df_old[col].isnull().sum()
    new_nulls = df_new[col].isnull().sum()
    if old_nulls != new_nulls:
        print(f"  {col}: OLD nulls={old_nulls}/{len(df_old)}, NEW nulls={new_nulls}/{len(df_new)}")
