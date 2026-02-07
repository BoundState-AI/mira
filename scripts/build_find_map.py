"""Build find number -> part number mapping for MER07543-001."""
import pandas as pd
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

df_v = pd.read_excel(r"C:\Users\jwilde2\Desktop\DMLLV\DMLLV_MIUL_v3_corrected.xlsx")
df_h = pd.read_excel(r"C:\Users\jwilde2\Desktop\DMLLV\Copy of DMLLV_MIUL_James.xlsx")

v3_rows = df_v[df_v["NHA"] == "MER07543-001"].copy()
h_rows = df_h[df_h["NHA"] == "MER07543-001"].copy()

print("MER07543-001 Find Number -> Part Number Mapping")
print("=" * 100)
print("%-6s  %-55s  %-20s" % ("Find#", "V3 Description", "James PN"))
print("-" * 100)

mapping = {}
for _, vr in v3_rows.iterrows():
    vpn = str(vr.get("Part Number", "")).strip()
    vdesc = str(vr.get("Part Description", "")).strip().upper()

    best = None
    best_score = 0
    for _, hr in h_rows.iterrows():
        hpn = str(hr.get("Part Number", "")).strip()
        hdesc = str(hr.get("Part Description", "")).strip().upper()
        if vdesc and hdesc:
            vwords = set(vdesc.replace(",", "").replace(".", "").split())
            hwords = set(hdesc.replace(",", "").replace(".", "").split())
            overlap = len(vwords & hwords) / max(len(vwords), len(hwords), 1)
            if overlap > best_score:
                best_score = overlap
                best = hpn

    if best and best_score > 0.4:
        mapping[vpn] = best
        print("%-6s  %-55s  %-20s  (%.0f%%)" % (vpn, vdesc[:55], best, best_score * 100))
    else:
        print("%-6s  %-55s  %-20s" % (vpn, vdesc[:55], "??? (no match)"))

print()
print("Python dict for FIND_NUMBER_MAP:")
print("FIND_NUMBER_MAP_MER07543 = {")
for fn, pn in sorted(mapping.items(), key=lambda x: int(x[0].rstrip(".")) if x[0].rstrip(".").isdigit() else 999):
    print('    "%s": "%s",' % (fn, pn))
print("}")
