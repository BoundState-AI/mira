"""
MUA Merge + Clean Re-Profile

1. Load v6_parsed (13,786 records)
2. Filter out ghosts (success=True but empty content)
3. Backfill material names from historic_mua.jsonl (v5) as material_name_v5
4. Backfill from v6_cleaned as material_designation_v6 where v6_parsed was empty
5. Write merged dataset: mua_merged_clean.jsonl
6. Re-run full profile on clean data
7. Re-pull 50 stratified samples (no blanks)

Preserves both v5 and v6 material names — never overwrites.
"""

import json
import os
import re
import random
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

random.seed(42)

# ─── Paths ──────────────────────────────────────────────────────────────────
V6_PARSED = Path(r"C:\BoundState\data\mua_v6_parsed_results.jsonl")
V6_CLEANED = Path(r"C:\BoundState\data\mua_v6_cleaned.jsonl")
HISTORIC = Path(r"C:\maptis-nlp\mira\databases\mua_faiss_db\historic_mua.jsonl")
OUTPUT_DIR = Path(r"C:\BoundState\docs\mua_audit")
MERGED_OUT = Path(r"C:\BoundState\data\mua_merged_clean.jsonl")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

KEYWORD_CLUSTERS = {
    "FLAMM": ["flammability", "flammable", "ignition", "combustion", "test 1", "test 17",
              "oxygen compatible", "lox", "gox"],
    "SCC": ["stress corrosion", "cracking", "msfc-std-3029", "sustained load", "cracking agent",
            "msfc-spec-522"],
    "CORR": ["corrosion", "galvanic", "plating", "coating", "dissimilar metal", "electrolyte"],
    "TOX": ["toxicity", "offgassing", "offgas", "test 7", "tlv", "crew exposure"],
    "FC": ["fracture", "fatigue", "crack growth", "safe life", "fail safe", "msfc-std-1249"],
    "TVS": ["thermal vacuum", "outgassing", "tml", "cvcm", "astm e595"],
}


def load_jsonl(path):
    records = []
    if not path.exists():
        print(f"  WARNING: {path} not found")
        return records
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def is_ghost(rec):
    """A ghost record: success=True but no actual content extracted."""
    mat = rec.get("material_designation") or ""
    rat = rec.get("rationale") or ""
    app = rec.get("application") or ""
    iss = rec.get("issue") or ""
    return not any([mat.strip(), rat.strip(), app.strip(), iss.strip()])


def get_text_blob(rec):
    parts = []
    for field in ["rationale", "application", "issue", "environment", "specification",
                  "trade_name", "material_designation", "material_name_v5"]:
        val = rec.get(field)
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, dict):
            parts.append(json.dumps(val))
        elif isinstance(val, list):
            parts.append(" ".join(str(x) for x in val))
    return " ".join(parts).lower()


def match_clusters(text_blob):
    matched = set()
    for cluster_name, keywords in KEYWORD_CLUSTERS.items():
        for kw in keywords:
            if kw in text_blob:
                matched.add(cluster_name)
                break
    return matched


def best_material(rec):
    """Best material name: prefer v6 designation, fall back to v5 name."""
    v6 = rec.get("material_designation") or ""
    v5 = rec.get("material_name_v5") or ""
    if v6.strip() and v6.strip().lower() not in ("(no material)", "n/a", "see below",
                                                   "see attached", "see miul attached",
                                                   "see miul", "various", "several",
                                                   "see below"):
        return v6.strip()
    if v5.strip():
        return v5.strip()
    return "(no material)"


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: Load all sources
# ═══════════════════════════════════════════════════════════════════════════════
print("=" * 70)
print("STEP 1: Loading data sources")
print("=" * 70)

v6_parsed = load_jsonl(V6_PARSED)
print(f"  v6_parsed: {len(v6_parsed):,} records")

v6_cleaned = load_jsonl(V6_CLEANED)
print(f"  v6_cleaned: {len(v6_cleaned):,} records")

historic = load_jsonl(HISTORIC)
print(f"  historic_mua: {len(historic):,} records")

# Build lookup indexes by source filename
v5_by_file = {}
for rec in historic:
    fn = rec.get("file_name", "")
    if fn and "data" in rec and isinstance(rec["data"], dict):
        mat_name = rec["data"].get("material_name") or ""
        if mat_name.strip():
            v5_by_file[fn] = mat_name.strip()

v6c_by_file = {}
for rec in v6_cleaned:
    fn = rec.get("source_file", "")
    if fn:
        mat = rec.get("material_designation") or ""
        fam = rec.get("material_family") or ""
        issues = rec.get("issues") or []
        env = rec.get("environment") or {}
        if mat.strip():
            v6c_by_file[fn] = {
                "material_designation": mat.strip(),
                "material_family": fam,
                "issues_cleaned": issues,
                "environment_structured": env,
            }

print(f"  v5 material index: {len(v5_by_file):,} files with material names")
print(f"  v6_cleaned index: {len(v6c_by_file):,} files with material data")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: Filter ghosts and merge
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 2: Filtering ghosts and merging material backfill")
print("=" * 70)

merged = []
ghost_count = 0
v5_backfill_count = 0
v6c_backfill_count = 0
v6c_family_backfill = 0
already_had_material = 0

for rec in v6_parsed:
    # Ghost filter: skip records with zero content
    if is_ghost(rec):
        ghost_count += 1
        continue

    fn = rec.get("file", "")

    # Preserve original v6 designation
    rec["material_designation_v6"] = rec.get("material_designation") or ""

    # Backfill v5 material name (always add if available, never overwrite v6)
    if fn in v5_by_file:
        rec["material_name_v5"] = v5_by_file[fn]
        if not (rec.get("material_designation") or "").strip():
            v5_backfill_count += 1
    else:
        rec["material_name_v5"] = ""

    # Backfill from v6_cleaned (structured fields)
    if fn in v6c_by_file:
        c = v6c_by_file[fn]
        # Only backfill material_designation if v6_parsed had nothing
        if not (rec.get("material_designation") or "").strip() and c["material_designation"]:
            rec["material_designation"] = c["material_designation"]
            v6c_backfill_count += 1
        # Always add material_family and structured issues if available
        if c.get("material_family"):
            rec["material_family"] = c["material_family"]
            v6c_family_backfill += 1
        if c.get("issues_cleaned"):
            rec["issues_cleaned"] = c["issues_cleaned"]
        if c.get("environment_structured"):
            rec["environment_structured"] = c["environment_structured"]

    # Track material coverage
    if best_material(rec) != "(no material)":
        already_had_material += 1

    # Fix success field retroactively
    has_content = bool(
        (rec.get("material_designation") or "").strip()
        or (rec.get("rationale") or "").strip()
        or (rec.get("application") or "").strip()
    )
    rec["success"] = has_content

    merged.append(rec)

print(f"  Ghosts filtered: {ghost_count:,}")
print(f"  Clean records: {len(merged):,}")
print(f"  v5 material backfills: {v5_backfill_count:,}")
print(f"  v6_cleaned material backfills: {v6c_backfill_count:,}")
print(f"  v6_cleaned family backfills: {v6c_family_backfill:,}")
print(f"  Records with material (any source): {already_had_material:,} / {len(merged):,} "
      f"({100*already_had_material/len(merged):.1f}%)")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: Write merged dataset
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\nWriting merged dataset to {MERGED_OUT}")
with open(MERGED_OUT, "w", encoding="utf-8") as f:
    for rec in merged:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"  [OK] {len(merged):,} records written")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: Re-profile on clean data
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 4: Profiling clean merged data")
print("=" * 70)

records = merged

# 4a: Material frequency (using best_material which prefers v6 > v5)
material_counter = Counter()
for rec in records:
    material_counter[best_material(rec)] += 1

print(f"Distinct materials: {len(material_counter):,}")
no_mat = material_counter.get("(no material)", 0)
print(f"Still missing material: {no_mat:,} ({100*no_mat/len(records):.1f}%)")
print(f"Top 25 materials:")
for mat, count in material_counter.most_common(25):
    print(f"  {count:>5}  {mat[:80]}")

# 4b: Keyword cluster frequency
cluster_counts = Counter()
cluster_records = defaultdict(list)
no_cluster_indices = []

for i, rec in enumerate(records):
    blob = get_text_blob(rec)
    matched = match_clusters(blob)
    if matched:
        for c in matched:
            cluster_counts[c] += 1
            cluster_records[c].append(i)
    else:
        no_cluster_indices.append(i)

print(f"\nKeyword cluster frequencies (clean data):")
for cluster in ["FLAMM", "SCC", "CORR", "TOX", "FC", "TVS"]:
    print(f"  {cluster:>5}: {cluster_counts[cluster]:>5} records ({100*cluster_counts[cluster]/len(records):.1f}%)")
print(f"  {'NONE':>5}: {len(no_cluster_indices):>5} records ({100*len(no_cluster_indices)/len(records):.1f}%)")

# 4c: Source file distribution
source_counter = Counter()
for rec in records:
    source_counter[rec.get("file", "(unknown)")] += 1
extractions_per_source = list(source_counter.values())
avg_per = sum(extractions_per_source) / len(extractions_per_source) if extractions_per_source else 0
max_per = max(extractions_per_source) if extractions_per_source else 0

print(f"\nSource files: {len(source_counter):,} distinct PDFs")
print(f"  Extractions per source: avg={avg_per:.1f}, max={max_per}")

# 4d: Text length analysis
rationale_lengths = []
application_lengths = []
issue_lengths = []
for rec in records:
    r = rec.get("rationale")
    a = rec.get("application")
    iss = rec.get("issue")
    if isinstance(r, str) and r.strip():
        rationale_lengths.append(len(r))
    if isinstance(a, str) and a.strip():
        application_lengths.append(len(a))
    if isinstance(iss, str) and iss.strip():
        issue_lengths.append(len(iss))

def stat_line(lengths, name):
    if not lengths:
        return f"  {name}: no data"
    lengths_sorted = sorted(lengths)
    n = len(lengths_sorted)
    avg = sum(lengths_sorted) / n
    med = lengths_sorted[n // 2]
    p10 = lengths_sorted[int(n * 0.1)]
    p90 = lengths_sorted[int(n * 0.9)]
    return (f"  {name}: n={n:,}, avg={avg:.0f}, med={med}, p10={p10}, p90={p90}, "
            f"min={lengths_sorted[0]}, max={lengths_sorted[-1]}")

print(f"\nText field lengths (characters):")
print(stat_line(rationale_lengths, "rationale"))
print(stat_line(application_lengths, "application"))
print(stat_line(issue_lengths, "issue"))

# 4e: Category
cat_counter = Counter()
for rec in records:
    cat = rec.get("category")
    cat_counter[str(cat) if cat else "(none)"] += 1
print(f"\nCategory distribution:")
for cat, count in cat_counter.most_common():
    print(f"  {cat:>10}: {count:>5}")

# 4f: Determination
det_counter = Counter()
for rec in records:
    det = rec.get("determination")
    det_counter[str(det) if det else "(none)"] += 1
print(f"\nDetermination distribution:")
for det, count in det_counter.most_common():
    print(f"  {det:>25}: {count:>5}")

# 4g: Environment
env_counter = Counter()
for rec in records:
    env = rec.get("environment")
    if isinstance(env, dict):
        env = env.get("type", env.get("raw_text", str(env)))
    env_counter[str(env)[:50] if env else "(none)"] += 1
print(f"\nEnvironment distribution (top 15):")
for env, count in env_counter.most_common(15):
    print(f"  {env:>50}: {count:>5}")

# 4h: Extraction mode
mode_counter = Counter()
for rec in records:
    mode = rec.get("extraction_mode")
    mode_counter[str(mode) if mode else "(none)"] += 1
print(f"\nExtraction mode:")
for mode, count in mode_counter.most_common():
    print(f"  {mode:>20}: {count:>5}")

# 4i: Confidence
confidences = []
for rec in records:
    c = rec.get("confidence")
    if c is not None:
        try:
            confidences.append(float(c))
        except (ValueError, TypeError):
            pass
if confidences:
    confidences.sort()
    n = len(confidences)
    print(f"\nConfidence: n={n:,}, avg={sum(confidences)/n:.2f}, med={confidences[n//2]:.2f}, "
          f"min={confidences[0]:.2f}, max={confidences[-1]:.2f}")

# 4j: Material family (from v6_cleaned backfill)
family_counter = Counter()
for rec in records:
    fam = rec.get("material_family") or "(none)"
    family_counter[fam] += 1
print(f"\nMaterial family (from v6_cleaned enrichment):")
for fam, count in family_counter.most_common(20):
    print(f"  {fam:>25}: {count:>5}")

# 4k: Multi-cluster
multi_cluster_counts = Counter()
for i in range(len(records)):
    blob = get_text_blob(records[i])
    matched = match_clusters(blob)
    multi_cluster_counts[len(matched)] += 1


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5: Stratified sample of 50 (no blanks)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 5: Building stratified sample of 50 (no blanks)")
print("=" * 70)

# Quality filter: must have at least rationale OR application with >50 chars
quality_indices = [
    i for i, rec in enumerate(records)
    if (len((rec.get("rationale") or "").strip()) > 50
        or len((rec.get("application") or "").strip()) > 50)
]
print(f"Quality-filtered records (>50 char text): {len(quality_indices):,}")

quality_set = set(quality_indices)
sample_indices = set()

# 5a: 10 from most frequent materials (excluding junk names)
junk_names = {"(no material)", "n/a", "see below", "see attached", "see miul attached",
              "various", "several", "see miul", "see below"}
real_materials = Counter()
for rec in records:
    mat = best_material(rec).lower()
    if mat not in junk_names:
        real_materials[best_material(rec)] += 1

top_materials_list = [mat for mat, _ in real_materials.most_common(10)]
print(f"Top 10 real materials: {top_materials_list}")

freq_mat_indices = [i for i in quality_indices if best_material(records[i]) in top_materials_list]
chosen = random.sample(freq_mat_indices, min(10, len(freq_mat_indices)))
sample_indices.update(chosen)
print(f"  Top materials: selected {len(chosen)}")

# 5b: 10 from each of top 3 clusters
top3_clusters = [c for c, _ in sorted(cluster_counts.items(), key=lambda x: x[1], reverse=True)[:3]]
print(f"  Top 3 clusters: {top3_clusters}")

for cluster in top3_clusters:
    available = [i for i in cluster_records[cluster]
                 if i not in sample_indices and i in quality_set]
    chosen = random.sample(available, min(10, len(available)))
    sample_indices.update(chosen)
    print(f"    {cluster}: selected {len(chosen)}")

# 5c: 10 from no-cluster (weird ones) — must have quality text
no_cluster_quality = [i for i in no_cluster_indices
                      if i not in sample_indices and i in quality_set]
chosen = random.sample(no_cluster_quality, min(10, len(no_cluster_quality)))
sample_indices.update(chosen)
print(f"  No cluster: selected {len(chosen)}")

# 5d: 10 from long tail materials (count <= 3)
longtail_mats = {mat for mat, count in real_materials.items() if count <= 3}
longtail_indices = [i for i in quality_indices
                    if best_material(records[i]) in longtail_mats and i not in sample_indices]
chosen = random.sample(longtail_indices, min(10, len(longtail_indices)))
sample_indices.update(chosen)
print(f"  Long tail: selected {len(chosen)}")

# Pad to 50 if needed
if len(sample_indices) < 50:
    remaining = [i for i in quality_indices if i not in sample_indices]
    extra = random.sample(remaining, min(50 - len(sample_indices), len(remaining)))
    sample_indices.update(extra)
    print(f"  Padding: added {len(extra)}")

sample_list = sorted(sample_indices)[:50]
print(f"  Final sample size: {len(sample_list)}")


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT: Write all 3 files
# ═══════════════════════════════════════════════════════════════════════════════

# ─── mua_profile_report.md (CLEAN) ──────────────────────────────────────────
print("\n" + "=" * 70)
print("Writing output files")
print("=" * 70)

with open(OUTPUT_DIR / "mua_profile_report.md", "w", encoding="utf-8") as f:
    f.write("# MUA Extraction Profile Report (Clean Merged Data)\n\n")
    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    f.write(f"**Source**: `mua_v6_parsed_results.jsonl` filtered + merged with v5 material backfill\n\n")

    f.write("## Data Pipeline\n\n")
    f.write("```\n")
    f.write(f"v6_parsed raw:       13,786 records\n")
    f.write(f"Ghost records:       -{ghost_count:,} (success=True but all fields empty)\n")
    f.write(f"Clean records:       {len(records):,}\n")
    f.write(f"v5 material backfill: +{v5_backfill_count:,} material names recovered\n")
    f.write(f"v6_cleaned backfill:  +{v6c_backfill_count:,} material names recovered\n")
    f.write(f"v6_cleaned families:  +{v6c_family_backfill:,} material_family tags added\n")
    f.write("```\n\n")

    # Summary
    f.write("## Summary\n\n")
    f.write("| Metric | Value |\n")
    f.write("|--------|-------|\n")
    f.write(f"| Total clean records | {len(records):,} |\n")
    f.write(f"| Ghosts removed | {ghost_count:,} |\n")
    f.write(f"| Distinct materials | {len(material_counter):,} |\n")
    f.write(f"| Material coverage | {already_had_material:,} / {len(records):,} ({100*already_had_material/len(records):.1f}%) |\n")
    f.write(f"| Still missing material | {no_mat:,} ({100*no_mat/len(records):.1f}%) |\n")
    f.write(f"| Distinct source PDFs | {len(source_counter):,} |\n")
    if confidences:
        f.write(f"| Avg confidence | {sum(confidences)/len(confidences):.2f} |\n")
    f.write("\n")

    # Material frequency
    f.write("## Material Frequency (best available name)\n\n")
    f.write("Uses v6 designation when available, v5 name as fallback.\n\n")
    f.write("### Top 40 Materials\n\n")
    f.write("| Rank | Material | Count | % |\n")
    f.write("|------|----------|-------|---|\n")
    for rank, (mat, count) in enumerate(material_counter.most_common(40), 1):
        pct = 100 * count / len(records)
        f.write(f"| {rank} | {mat[:80].replace('|', '/')} | {count} | {pct:.1f}% |\n")
    f.write("\n")

    # Material freq dist
    tail_1 = sum(1 for c in material_counter.values() if c == 1)
    tail_2_3 = sum(1 for c in material_counter.values() if 2 <= c <= 3)
    tail_4_10 = sum(1 for c in material_counter.values() if 4 <= c <= 10)
    tail_gt10 = sum(1 for c in material_counter.values() if c > 10)
    f.write("### Material Frequency Distribution\n\n")
    f.write("| Frequency | # Materials | % of distinct |\n")
    f.write("|-----------|------------|---------------|\n")
    f.write(f"| Appears once | {tail_1} | {100*tail_1/len(material_counter):.1f}% |\n")
    f.write(f"| 2-3 times | {tail_2_3} | {100*tail_2_3/len(material_counter):.1f}% |\n")
    f.write(f"| 4-10 times | {tail_4_10} | {100*tail_4_10/len(material_counter):.1f}% |\n")
    f.write(f"| >10 times | {tail_gt10} | {100*tail_gt10/len(material_counter):.1f}% |\n")
    f.write("\n")

    # Material family
    f.write("## Material Family Distribution\n\n")
    f.write("From v6_cleaned enrichment (not all records have this).\n\n")
    f.write("| Family | Count | % |\n")
    f.write("|--------|-------|---|\n")
    for fam, count in family_counter.most_common(20):
        f.write(f"| {fam} | {count:,} | {100*count/len(records):.1f}% |\n")
    f.write("\n")

    # Keyword clusters
    f.write("## Concern Domain Keyword Clusters\n\n")
    f.write("| Cluster | Keywords (sample) | Records | % |\n")
    f.write("|---------|-------------------|---------|---|\n")
    for cluster in ["FLAMM", "SCC", "CORR", "TOX", "FC", "TVS"]:
        kws = ", ".join(KEYWORD_CLUSTERS[cluster][:4])
        cnt = cluster_counts[cluster]
        pct = 100 * cnt / len(records)
        f.write(f"| {cluster} | {kws} | {cnt:,} | {pct:.1f}% |\n")
    f.write(f"| NONE | (no cluster match) | {len(no_cluster_indices):,} | {100*len(no_cluster_indices)/len(records):.1f}% |\n")
    f.write("\n")

    f.write("### Multi-Cluster Records\n\n")
    f.write("| # Clusters | Records | % |\n")
    f.write("|-----------|---------|---|\n")
    for n_cl in sorted(multi_cluster_counts.keys()):
        cnt = multi_cluster_counts[n_cl]
        f.write(f"| {n_cl} | {cnt:,} | {100*cnt/len(records):.1f}% |\n")
    f.write("\n")

    # Source distribution
    f.write("## Source File Distribution\n\n")
    f.write(f"- **Distinct source PDFs**: {len(source_counter):,}\n")
    f.write(f"- **Extractions per source**: avg={avg_per:.1f}, max={max_per}\n")
    multi_src = sum(1 for v in extractions_per_source if v > 1)
    f.write(f"- **Sources with >1 extraction**: {multi_src}\n\n")

    f.write("### Top 20 Source Files\n\n")
    f.write("| Source PDF | Extractions |\n")
    f.write("|-----------|------------|\n")
    for src, count in source_counter.most_common(20):
        f.write(f"| {src} | {count} |\n")
    f.write("\n")

    # Text lengths
    f.write("## Text Field Lengths\n\n")
    f.write("| Field | N | Avg | Median | P10 | P90 | Min | Max |\n")
    f.write("|-------|---|-----|--------|-----|-----|-----|-----|\n")
    for name, lengths in [("rationale", rationale_lengths), ("application", application_lengths),
                          ("issue", issue_lengths)]:
        if lengths:
            ls = sorted(lengths)
            n = len(ls)
            avg = sum(ls) / n
            med = ls[n // 2]
            p10 = ls[int(n * 0.1)]
            p90 = ls[int(n * 0.9)]
            f.write(f"| {name} | {n:,} | {avg:.0f} | {med} | {p10} | {p90} | {ls[0]} | {ls[-1]} |\n")
    f.write("\n")

    if rationale_lengths:
        avg_rat = sum(rationale_lengths) / len(rationale_lengths)
        if avg_rat > 200:
            f.write("Rationale texts are **full paragraphs** (avg > 200 chars).\n")
        else:
            f.write("Rationale texts are **fragments** (avg < 200 chars).\n")
    if application_lengths:
        avg_app = sum(application_lengths) / len(application_lengths)
        if avg_app > 200:
            f.write("Application texts are **full paragraphs**.\n")
        else:
            f.write("Application texts are **fragments**.\n")
    f.write("\n")

    # Category
    f.write("## Category Distribution\n\n")
    f.write("| Category | Count | % |\n")
    f.write("|----------|-------|---|\n")
    for cat, count in cat_counter.most_common():
        f.write(f"| {cat} | {count:,} | {100*count/len(records):.1f}% |\n")
    f.write("\n")

    # Determination
    f.write("## Determination Distribution\n\n")
    f.write("| Determination | Count | % |\n")
    f.write("|---------------|-------|---|\n")
    for det, count in det_counter.most_common():
        f.write(f"| {det} | {count:,} | {100*count/len(records):.1f}% |\n")
    f.write("\n")

    # Environment
    f.write("## Environment Distribution\n\n")
    f.write("| Environment | Count | % |\n")
    f.write("|-------------|-------|---|\n")
    for env, count in env_counter.most_common(15):
        f.write(f"| {env} | {count:,} | {100*count/len(records):.1f}% |\n")
    f.write("\n")

    # Extraction mode
    f.write("## Extraction Mode\n\n")
    f.write("| Mode | Count | % |\n")
    f.write("|------|-------|---|\n")
    for mode, count in mode_counter.most_common():
        f.write(f"| {mode} | {count:,} | {100*count/len(records):.1f}% |\n")
    f.write("\n")

    # Confidence
    if confidences:
        f.write("## Confidence Distribution\n\n")
        bins = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
        f.write("| Range | Count | % |\n")
        f.write("|-------|-------|---|\n")
        for lo, hi in bins:
            cnt = sum(1 for c in confidences if lo <= c < hi)
            label = f"{lo:.1f}-{hi:.1f}" if hi < 1.01 else f"{lo:.1f}-1.0"
            f.write(f"| {label} | {cnt:,} | {100*cnt/len(confidences):.1f}% |\n")
        f.write("\n")

print("  [OK] mua_profile_report.md")


# ─── mua_sample_50.md (CLEAN) ───────────────────────────────────────────────
with open(OUTPUT_DIR / "mua_sample_50.md", "w", encoding="utf-8") as f:
    f.write("# MUA Stratified Sample v2 -- 50 Records for Manual Audit\n\n")
    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    f.write("**Dataset**: Clean merged (ghosts removed, v5 material backfill applied)\n\n")

    f.write("## Sampling Strategy\n\n")
    f.write(f"- 10 from **most frequent real materials**: {', '.join(top_materials_list[:5])}...\n")
    f.write(f"- 10 from each of **top 3 concern clusters**: {', '.join(top3_clusters)}\n")
    f.write(f"- 10 from records matching **no keyword cluster** (the weird ones)\n")
    f.write(f"- Remainder from **long tail** materials (count <= 3)\n")
    f.write(f"- Quality filter: all records have >50 chars of rationale or application\n")
    f.write(f"- Total: {len(sample_list)} records\n\n")

    f.write("## Audit Instructions\n\n")
    f.write("For each record, manually tag:\n\n")
    f.write("1. **WHAT** -- Can you identify a specific material? (Y/N, and what is it?)\n")
    f.write("2. **WHY** -- Can you identify a concern domain? (FLAMM/SCC/CORR/TOX/FC/TVS/OTHER)\n")
    f.write("3. **HOW** -- Is there a mitigation pattern? (test data, engineering rationale, usage limits, etc.)\n")
    f.write("4. **QUALITY** -- Is the text coherent? (Good / Partial / Garbage)\n\n")
    f.write("---\n\n")

    for sample_num, idx in enumerate(sample_list, 1):
        rec = records[idx]
        material = best_material(rec)
        mat_v6 = rec.get("material_designation_v6", "") or ""
        mat_v5 = rec.get("material_name_v5", "") or ""
        source = rec.get("file", "(unknown)")
        mua_num = rec.get("mua_number") or "(unknown)"
        category = rec.get("category") or "(none)"
        issue = rec.get("issue") or "(none)"
        environment = rec.get("environment") or "(none)"
        if isinstance(environment, dict):
            environment = environment.get("raw_text", environment.get("type", str(environment)))
        determination = rec.get("determination") or "(none)"
        rationale = rec.get("rationale") or "(none)"
        application = rec.get("application") or "(none)"
        confidence = rec.get("confidence")
        confidence_str = f"{confidence:.2f}" if confidence is not None else "(none)"
        mat_family = rec.get("material_family") or ""
        issues_cleaned = rec.get("issues_cleaned") or []

        blob = get_text_blob(rec)
        matched = match_clusters(blob)

        # Determine bucket
        bucket = "RANDOM"
        mat_lower = material.lower()
        if material in top_materials_list:
            bucket = "TOP_MATERIAL"
        elif not matched:
            bucket = "NO_CLUSTER"
        elif mat_lower not in junk_names and real_materials.get(material, 0) <= 3:
            bucket = "LONG_TAIL"
        else:
            for c in top3_clusters:
                if c in matched:
                    bucket = c
                    break

        f.write(f"### Record {sample_num} of {len(sample_list)}\n\n")
        f.write("| Field | Value |\n")
        f.write("|-------|-------|\n")
        f.write(f"| **Record Index** | {idx} |\n")
        f.write(f"| **Sample Bucket** | {bucket} |\n")
        f.write(f"| **Source File** | `{source}` |\n")
        f.write(f"| **MUA Number** | {mua_num} |\n")
        f.write(f"| **Material (best)** | {material[:100]} |\n")
        f.write(f"| **Material v6** | {mat_v6[:100]} |\n")
        f.write(f"| **Material v5** | {mat_v5[:100]} |\n")
        if mat_family:
            f.write(f"| **Material Family** | {mat_family} |\n")
        f.write(f"| **Category** | {category} |\n")
        f.write(f"| **Issue** | {str(issue)[:150]} |\n")
        if issues_cleaned:
            f.write(f"| **Issues (cleaned)** | {', '.join(issues_cleaned)} |\n")
        f.write(f"| **Environment** | {str(environment)[:80]} |\n")
        f.write(f"| **Determination** | {determination} |\n")
        f.write(f"| **Confidence** | {confidence_str} |\n")
        f.write(f"| **Cluster Matches** | {', '.join(sorted(matched)) if matched else 'NONE'} |\n")
        f.write("\n")

        f.write("**Application (WHAT)**:\n")
        f.write(f"> {str(application)[:1000]}\n\n")
        f.write("**Rationale (WHY/HOW)**:\n")
        f.write(f"> {str(rationale)[:1000]}\n\n")
        f.write("**Issue (concern domain)**:\n")
        f.write(f"> {str(issue)[:500]}\n\n")

        f.write("**Manual Audit Tags**:\n")
        f.write("- WHAT: ___\n")
        f.write("- WHY: ___\n")
        f.write("- HOW: ___\n")
        f.write("- QUALITY: ___\n\n")
        f.write("---\n\n")

print("  [OK] mua_sample_50.md")


# ─── mua_data_map.md (updated) ──────────────────────────────────────────────
with open(OUTPUT_DIR / "mua_data_map.md", "w", encoding="utf-8") as f:
    f.write("# MUA Data Map (Updated)\n\n")
    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

    f.write("## Canonical Dataset\n\n")
    f.write(f"**`{MERGED_OUT}`** -- {len(merged):,} records\n\n")
    f.write("This is the clean merged dataset. Ghost records removed, v5 material names backfilled.\n\n")

    f.write("### Schema\n\n")
    f.write("| Field | Type | Source | Description |\n")
    f.write("|-------|------|--------|-------------|\n")
    f.write("| `file` | string | v6_parsed | Source PDF filename |\n")
    f.write("| `success` | bool | Recomputed | True only if actual content was extracted |\n")
    f.write("| `confidence` | float | v6_parsed | 0.0-1.0 extraction confidence |\n")
    f.write("| `material_designation` | string | v6_parsed (backfilled from v6_cleaned) | Best v6 material name |\n")
    f.write("| `material_designation_v6` | string | v6_parsed | Original v6 extraction (may be empty) |\n")
    f.write("| `material_name_v5` | string | historic_mua.jsonl | v5 parser material name (cruder but wider coverage) |\n")
    f.write("| `material_family` | string | v6_cleaned | Normalized family (aluminum, stainless_steel, etc.) |\n")
    f.write("| `issues_cleaned` | array | v6_cleaned | Parsed concern list [\"scc\", \"flammability\", ...] |\n")
    f.write("| `environment_structured` | object | v6_cleaned | `{type, o2_percent, pressure_psia, ...}` |\n")
    f.write("| `mua_number` | string | v6_parsed | MUA document number |\n")
    f.write("| `category` | string | v6_parsed | I, II, III |\n")
    f.write("| `determination` | string | v6_parsed | APPROVED, DEFERRED, REJECTED, etc. |\n")
    f.write("| `environment` | string | v6_parsed | Raw environment text |\n")
    f.write("| `location` | string | v6_parsed | Habitable/Nonhabitable |\n")
    f.write("| `application` | string | v6_parsed | What the material is used for (max 500 chars) |\n")
    f.write("| `rationale` | string | v6_parsed | Why deviation is acceptable (max 500 chars) |\n")
    f.write("| `issue` | string | v6_parsed | Concern domain description (max 200 chars) |\n")
    f.write("| `manufacturer` | string | v6_parsed | Material manufacturer |\n")
    f.write("| `trade_name` | string | v6_parsed | Commercial name |\n")
    f.write("| `specification` | string | v6_parsed | Governing spec |\n")
    f.write("| `extraction_mode` | string | v6_parsed | vision or unknown |\n")
    f.write("\n")

    f.write("## Source Lineage\n\n")
    f.write("```\n")
    f.write(f"v6_parsed (13,786 raw) --> filter ghosts (-{ghost_count:,})\n")
    f.write(f"                      --> backfill v5 materials (+{v5_backfill_count:,})\n")
    f.write(f"                      --> backfill v6_cleaned (+{v6c_backfill_count:,} mat, +{v6c_family_backfill:,} family)\n")
    f.write(f"                      --> recompute success field\n")
    f.write(f"                      = mua_merged_clean.jsonl ({len(merged):,} records)\n")
    f.write("```\n\n")

    f.write("## Pipeline Bug Fix\n\n")
    f.write("**File**: `sandbox/scripts/batch_parse_muas_v6.py` line 146\n\n")
    f.write("**Before**: `success: True` (unconditional)\n\n")
    f.write("**After**: Validation gate checks `doc.parse_success AND has_content`. ")
    f.write("A parse that returns no material, no rationale, AND no application is now `success=False`.\n\n")

    f.write("## Raw Data Sources\n\n")
    f.write("| Source | Path | Records | Role |\n")
    f.write("|--------|------|---------|------|\n")
    f.write(f"| v6_parsed | `C:\\BoundState\\data\\mua_v6_parsed_results.jsonl` | 13,786 | Primary extraction |\n")
    f.write(f"| v6_cleaned | `C:\\BoundState\\data\\mua_v6_cleaned.jsonl` | 6,370 | Structured enrichment |\n")
    f.write(f"| historic_mua | `C:\\maptis-nlp\\mira\\databases\\mua_faiss_db\\historic_mua.jsonl` | 9,058 | v5 material backfill |\n")
    f.write(f"| rag_precedents | `C:\\BoundState\\data\\mua_rag_precedents\\metadata.jsonl` | 4,120 | FAISS semantic index |\n")
    f.write(f"| **merged** | **`C:\\BoundState\\data\\mua_merged_clean.jsonl`** | **{len(merged):,}** | **Canonical for audit** |\n")
    f.write("\n")

    f.write("## Key Scripts\n\n")
    f.write("| Script | Purpose |\n")
    f.write("|--------|--------|\n")
    f.write("| `scripts/mua_merge_and_reprofile.py` | This script: merge, filter, profile, sample |\n")
    f.write("| `scripts/mua_phase1_profile.py` | Original profiling (superseded) |\n")
    f.write("| `scripts/mua_diagnose_missing_materials.py` | Ghost diagnosis |\n")
    f.write("| `sandbox/scripts/batch_parse_muas_v6.py` | v6 extraction pipeline (bug fixed) |\n")
    f.write("| `mira/miul/mua_parser_v6.py` | Core parser with confidence calculation |\n")

print("  [OK] mua_data_map.md")

print(f"\n{'=' * 70}")
print(f"DONE -- All files written to {OUTPUT_DIR}")
print(f"Merged dataset: {MERGED_OUT}")
print(f"{'=' * 70}")
