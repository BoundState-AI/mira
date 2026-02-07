#!/usr/bin/env python3
"""
Module: Read Miul Excel
Purpose: Read MIUL Excel file and output details for verification.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import pandas as pd
import sys
import io

# Set stdout to UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def safe_str(val):
    """Convert value to ASCII-safe string."""
    if pd.isna(val):
        return ''
    s = str(val)
    # Replace special Unicode characters
    s = s.replace('\u2300', 'DIA')  # diameter symbol
    return s.encode('ascii', 'replace').decode('ascii')

def main():
    excel_path = r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_enriched (21).xlsx"

    try:
        df = pd.read_excel(excel_path)
        print(f"Shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        print()

        # Show all rows with key columns
        key_cols = ['Index', 'Parent', 'NHA', 'Designation', 'Material Specification',
                    'Material Code', 'FLAM', 'SCC', 'CORR', 'TVS', 'TOX', 'FS',
                    'MUA Rationale', 'Part Number', 'Part Description']

        # Filter to columns that exist
        existing_cols = [c for c in key_cols if c in df.columns]
        print(f"Key columns found: {existing_cols}")
        print()

        # Show material code summary
        print("=== MATERIAL CODE SUMMARY ===")
        print()
        if 'Designation' in df.columns and 'Material Code' in df.columns:
            for idx, row in df.iterrows():
                desig = row.get('Designation', '')
                mat_code = row.get('Material Code', '')
                mat_spec = row.get('Material Specification', '')
                part_num = row.get('Part Number', '')
                flam = row.get('FLAM', '')
                scc = row.get('SCC', '')
                corr = row.get('CORR', '')
                tvs = row.get('TVS', '')
                tox = row.get('TOX', '')
                fs = row.get('FS', '')
                index_val = row.get('Index', '')
                parent = row.get('Parent', '')

                # Only show rows with designations (materials)
                if pd.notna(desig) and str(desig).strip():
                    print(f"Row {idx}:")
                    print(f"  Index: {safe_str(index_val)}, Parent: {safe_str(parent)}")
                    print(f"  Part: {safe_str(part_num)}")
                    print(f"  Designation: {safe_str(desig)}")
                    print(f"  Material Spec: {safe_str(mat_spec)}")
                    print(f"  Material Code: {safe_str(mat_code)}")
                    print(f"  Ratings: FLAM={safe_str(flam)} SCC={safe_str(scc)} CORR={safe_str(corr)} TVS={safe_str(tvs)} TOX={safe_str(tox)} FS={safe_str(fs)}")
                    print()

        # Show full structure for validation
        print("\n=== FULL INDEX/PARENT STRUCTURE ===")
        for idx, row in df.iterrows():
            index_val = row.get('Index', '')
            parent = row.get('Parent', '')
            part_num = row.get('Part Number', '')
            desig = row.get('Designation', '')
            mat_code = row.get('Material Code', '')
            print(f"{idx}: Index={safe_str(index_val)} Parent={safe_str(parent)} Part={safe_str(part_num)} Desig={safe_str(desig)} Code={safe_str(mat_code)}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
