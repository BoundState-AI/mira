"""Compare old MIUL Excel output vs V4 output."""
import pandas as pd
import sys

def analyze_file(path, label):
    print(f"\n{'='*80}")
    print(f"  {label}: {path}")
    print(f"{'='*80}")

    # Read all sheets
    xls = pd.ExcelFile(path)
    print(f"\nSheets: {xls.sheet_names}")

    for sheet_name in xls.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet_name)
        print(f"\n--- Sheet: '{sheet_name}' ---")
        print(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
        print(f"\nColumn headers ({len(df.columns)}):")
        for i, col in enumerate(df.columns):
            print(f"  [{i}] {col}")

        print(f"\nFirst 10 rows:")
        pd.set_option('display.max_columns', None)
        pd.set_option('display.max_colwidth', 40)
        pd.set_option('display.width', 300)
        print(df.head(10).to_string())

        print(f"\n--- Data types ---")
        print(df.dtypes.to_string())

        print(f"\n--- Null counts ---")
        null_counts = df.isnull().sum()
        print(null_counts[null_counts > 0].to_string() if null_counts.any() else "No nulls")

        # Show unique values for key columns if they exist
        for col in df.columns:
            nunique = df[col].nunique()
            if nunique <= 20:
                print(f"\nUnique values in '{col}' ({nunique}):")
                print(f"  {df[col].dropna().unique().tolist()}")

def main():
    old_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_test.xlsx"
    new_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_V4_v4.xlsx"

    analyze_file(old_path, "OLD (MIUL_test.xlsx)")
    analyze_file(new_path, "NEW V4 (MIUL_V4_v4.xlsx)")

    # Now do side-by-side comparison
    print(f"\n{'='*80}")
    print(f"  SIDE-BY-SIDE COMPARISON")
    print(f"{'='*80}")

    df_old = pd.read_excel(old_path)
    df_new = pd.read_excel(new_path)

    old_cols = set(df_old.columns)
    new_cols = set(df_new.columns)

    print(f"\nColumns only in OLD: {old_cols - new_cols}")
    print(f"Columns only in NEW: {new_cols - old_cols}")
    print(f"Common columns: {old_cols & new_cols}")

    # Compare row counts
    print(f"\nRow count - OLD: {len(df_old)}, NEW: {len(df_new)}")

    # For common columns, compare values
    common = sorted(old_cols & new_cols)
    print(f"\n--- Value comparison for common columns ---")
    for col in common:
        old_vals = df_old[col].dropna().astype(str).tolist()
        new_vals = df_new[col].dropna().astype(str).tolist()

        old_set = set(old_vals)
        new_set = set(new_vals)

        if old_set != new_set:
            print(f"\n  Column '{col}' DIFFERS:")
            print(f"    OLD unique ({len(old_set)}): {sorted(old_set)[:10]}")
            print(f"    NEW unique ({len(new_set)}): {sorted(new_set)[:10]}")
            only_old = old_set - new_set
            only_new = new_set - old_set
            if only_old:
                print(f"    Only in OLD: {sorted(only_old)[:10]}")
            if only_new:
                print(f"    Only in NEW: {sorted(only_new)[:10]}")
        else:
            print(f"\n  Column '{col}': MATCH ({len(old_set)} unique values)")

    # Row-by-row comparison attempt
    # Try to match rows by some key
    print(f"\n--- Row-by-row detail (first 15 rows) ---")
    max_rows = min(15, max(len(df_old), len(df_new)))
    for i in range(max_rows):
        print(f"\n  Row {i}:")
        for col in sorted(set(list(df_old.columns) + list(df_new.columns))):
            old_val = df_old.iloc[i][col] if i < len(df_old) and col in df_old.columns else "N/A"
            new_val = df_new.iloc[i][col] if i < len(df_new) and col in df_new.columns else "N/A"
            marker = " ***DIFF***" if str(old_val) != str(new_val) else ""
            if marker or pd.isna(old_val) != pd.isna(new_val):
                print(f"    {col}: OLD='{old_val}' | NEW='{new_val}'{marker}")

if __name__ == "__main__":
    main()
