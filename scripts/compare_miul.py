"""Compare two MIUL Excel files: Human-verified vs V3 output."""
import pandas as pd
import numpy as np
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUMAN_PATH = "C:/Users/jwilde2/Desktop/DMLLV/Copy of DMLLV_MIUL_James.xlsx"
V3_PATH    = "C:/Users/jwilde2/Desktop/DMLLV/MIUL_DMLLV_v3_graph.xlsx"
KEY_COL = "Part Number"
COMPARE_COLS = ["Designation", "Material Specification", "Part Description",
                "NHA", "Drawing Source", "Change Letter", "Process Specification"]

def norm(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    return str(val).strip()

def norm_d(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "<empty>"
    s = str(val).strip()
    return s if s else "<empty>"

def sep(c="=", w=100):
    print(c * w)

def hdr(title, c="=", w=100):
    print()
    sep(c, w)
    print("  " + title)
    sep(c, w)

print("Loading Excel files...")
df_h = pd.read_excel(HUMAN_PATH)
df_v = pd.read_excel(V3_PATH)
print("  Human: " + HUMAN_PATH)
print("  V3:    " + V3_PATH)

hdr("1. ROW COUNTS")
print("  Human rows:  %d" % len(df_h))
print("  V3 rows:     %d" % len(df_v))
print("  Difference:  %+d" % (len(df_v) - len(df_h)))

hdr("2. UNIQUE PART NUMBERS")
hp = set(df_h[KEY_COL].dropna().astype(str).str.strip())
vp = set(df_v[KEY_COL].dropna().astype(str).str.strip())
print("  Unique in Human: %d" % len(hp))
print("  Unique in V3:    %d" % len(vp))
print("  In common:       %d" % len(hp & vp))

oh = sorted(hp - vp)
ov = sorted(vp - hp)

print("\n  Parts in HUMAN but NOT in V3 (%d):" % len(oh))
for p in oh:
    rows = df_h[df_h[KEY_COL].astype(str).str.strip() == p]
    desc = "; ".join(str(d) for d in rows["Part Description"].dropna().unique()[:2])
    nha_s = "; ".join(str(n) for n in rows["NHA"].dropna().unique()[:2])
    print("    - %-30s  Desc: %-50s  NHA: %s" % (p, desc, nha_s))
if not oh:
    print("    (none)")

print("\n  Parts in V3 but NOT in HUMAN (%d):" % len(ov))
for p in ov:
    rows = df_v[df_v[KEY_COL].astype(str).str.strip() == p]
    desc = "; ".join(str(d) for d in rows["Part Description"].dropna().unique()[:2])
    nha_s = "; ".join(str(n) for n in rows["NHA"].dropna().unique()[:2])
    print("    - %-30s  Desc: %-50s  NHA: %s" % (p, desc, nha_s))
if not ov:
    print("    (none)")

hdr("3. DUPLICATE PART NUMBERS")
hdc = df_h[KEY_COL].astype(str).str.strip().value_counts()
vdc = df_v[KEY_COL].astype(str).str.strip().value_counts()
print("  Human: %d part numbers appear >1 time" % len(hdc[hdc > 1]))
print("  V3:    %d part numbers appear >1 time" % len(vdc[vdc > 1]))

hdr("4. ROW-LEVEL MATCHING (key: PN + NHA + Designation)")
def mk(row):
    return norm(row["Part Number"]) + "||" + norm(row["NHA"]) + "||" + norm(row["Designation"])
df_h["_k"] = df_h.apply(mk, axis=1)
df_v["_k"] = df_v.apply(mk, axis=1)

def addseq(df):
    c = {}
    s = []
    for k in df["_k"]:
        c[k] = c.get(k, 0) + 1
        s.append(c[k])
    df["_s"] = s
    df["_fk"] = df["_k"] + "||" + df["_s"].astype(str)
    return df

df_h = addseq(df_h)
df_v = addseq(df_v)
hk = set(df_h["_fk"])
vk = set(df_v["_fk"])
mk2 = hk & vk
print("  Matched rows (same key):  %d" % len(mk2))
print("  Unmatched human rows:     %d" % len(hk - vk))
print("  Unmatched v3 rows:        %d" % len(vk - hk))

hdr("5. FIELD-BY-FIELD COMPARISON")
print("  Strategy: For each common PN, match rows by NHA+Designation, then compare.\n")
common = sorted(hp & vp)
mis = {c: [] for c in COMPARE_COLS}
mc_d = {c: 0 for c in COMPARE_COLS}
tc_d = {c: 0 for c in COMPARE_COLS}
hmvn = []
vmhn = []
umh = []
umv = []

for pn in common:
    hr = df_h[df_h[KEY_COL].astype(str).str.strip() == pn].copy()
    vr = df_v[df_v[KEY_COL].astype(str).str.strip() == pn].copy()
    def ik(row):
        return norm(row["NHA"]) + "||" + norm(row["Designation"])
    hr["_ik"] = hr.apply(ik, axis=1)
    vr["_ik"] = vr.apply(ik, axis=1)
    va = list(vr.index)
    mpairs = []
    for hi, hrow in hr.iterrows():
        hk2 = hrow["_ik"]
        best = None
        for vi in va:
            if vr.loc[vi, "_ik"] == hk2:
                best = vi
                break
        if best is not None:
            mpairs.append((hi, best))
            va.remove(best)
        else:
            umh.append(hrow)
    for vi in va:
        umv.append(vr.loc[vi])
    for hi, vi in mpairs:
        hrow = df_h.loc[hi]
        vrow = df_v.loc[vi]
        for col in COMPARE_COLS:
            hval = norm(hrow[col])
            vval = norm(vrow[col])
            tc_d[col] += 1
            if hval.lower() == vval.lower():
                mc_d[col] += 1
            else:
                mis[col].append({"pn": pn, "nha": norm_d(hrow["NHA"]),
                                 "h": norm_d(hrow[col]), "v": norm_d(vrow[col])})
        hd = norm(hrow["Designation"])
        vd = norm(vrow["Designation"])
        if hd and not vd:
            hmvn.append({"pn": pn, "nha": norm_d(hrow["NHA"]),
                         "hd": norm_d(hrow["Designation"]),
                         "hm": norm_d(hrow["Material Specification"])})
        elif vd and not hd:
            vmhn.append({"pn": pn, "nha": norm_d(hrow["NHA"]),
                         "vd": norm_d(vrow["Designation"]),
                         "vm": norm_d(vrow["Material Specification"])})

hdr("5a. MATCH RATES PER FIELD", c="-")
print("  %-30s %8s / %6s  %7s" % ("Field", "Match", "Total", "Rate"))
print("  " + "-"*30 + " " + "-"*8 + "   " + "-"*6 + "  " + "-"*7)
for col in COMPARE_COLS:
    t = tc_d[col]
    m = mc_d[col]
    r = (m / t * 100) if t > 0 else 0
    print("  %-30s %8d / %6d  %6.1f%%" % (col, m, t, r))

hdr("5b. ALL MISMATCHES BY FIELD", c="-")
for col in COMPARE_COLS:
    ml = mis[col]
    print("\n  --- %s (%d mismatches) ---" % (col, len(ml)))
    if not ml:
        print("    (all matched!)")
        continue
    for mm in ml:
        print("    Part: %-25s  NHA: %-18s" % (mm["pn"], mm["nha"]))
        print("      Human: %s" % mm["h"])
        print("      V3:    %s" % mm["v"])
        print()

hdr("6. MATERIAL COVERAGE GAPS")
print("\n  6a. Human has Designation but V3 does NOT (%d):" % len(hmvn))
for item in hmvn:
    print("    Part: %-25s  NHA: %-18s" % (item["pn"], item["nha"]))
    print("      Human Designation: %s" % item["hd"])
    print("      Human Mat Spec:    %s" % item["hm"])
    print()
if not hmvn:
    print("    (none)")

print("\n  6b. V3 has Designation but HUMAN does NOT (%d):" % len(vmhn))
for item in vmhn:
    print("    Part: %-25s  NHA: %-18s" % (item["pn"], item["nha"]))
    print("      V3 Designation: %s" % item["vd"])
    print("      V3 Mat Spec:    %s" % item["vm"])
    print()
if not vmhn:
    print("    (none)")

hdr("7. UNMATCHED ROWS")
print("\n  7a. Human rows with no V3 match (%d):" % len(umh))
for row in umh:
    print("    Part: %-25s  NHA: %-18s  Desig: %-20s  DrawSrc: %s" % (
        norm_d(row["Part Number"]), norm_d(row["NHA"]),
        norm_d(row["Designation"]), norm_d(row["Drawing Source"])))
if not umh:
    print("    (none)")

print("\n  7b. V3 rows with no Human match (%d):" % len(umv))
for row in umv:
    print("    Part: %-25s  NHA: %-18s  Desig: %-20s  DrawSrc: %s" % (
        norm_d(row["Part Number"]), norm_d(row["NHA"]),
        norm_d(row["Designation"]), norm_d(row["Drawing Source"])))
if not umv:
    print("    (none)")

hdr("8. SUMMARY")
tf = sum(tc_d[c] for c in COMPARE_COLS)
tm = sum(mc_d[c] for c in COMPARE_COLS)
tmm = tf - tm
orr = (tm / tf * 100) if tf > 0 else 0
print("  Total row-pairs compared:       %d" % (max(tc_d.values()) if tc_d else 0))
print("  Total field comparisons:        %d" % tf)
print("  Total field matches:            %d" % tm)
print("  Total field mismatches:         %d" % tmm)
print("  Overall field match rate:       %.1f%%" % orr)
print()
print("  Parts only in Human:            %d" % len(oh))
print("  Parts only in V3:               %d" % len(ov))
print("  Human rows unmatched:           %d" % len(umh))
print("  V3 rows unmatched:              %d" % len(umv))
print("  Human has material, V3 missing: %d" % len(hmvn))
print("  V3 has material, Human missing: %d" % len(vmhn))
print()
sep()
print("  Report complete.")
sep()

