"""
MUA Extraction Audit - Phase 1 Profiling
Pure observation. No transformation, no classification, no schema creation.

Reads all MUA extraction data and produces:
  1. mua_profile_report.md  — frequency distributions and summary stats
  2. mua_sample_50.md       — 50 stratified records for manual review
  3. mua_data_map.md        — where the data lives, what format, what fields
"""

import json
import os
import re
import random
from collections import Counter, defaultdict
from pathlib import Path

random.seed(42)  # reproducible sampling

# ─── Data sources ───────────────────────────────────────────────────────────
DATA_SOURCES = {
    "v6_parsed": Path(r"C:\BoundState\data\mua_v6_parsed_results.jsonl"),
    "v6_cleaned": Path(r"C:\BoundState\data\mua_v6_cleaned.jsonl"),
    "v6_parsed_alt": Path(r"C:\BoundState\data\MUA_json\mua_v6_parsed_results.jsonl"),
    "v6_cleaned_alt": Path(r"C:\BoundState\data\MUA_json\mua_v6_cleaned.jsonl"),
    "historic_mua": Path(r"C:\maptis-nlp\mira\databases\mua_faiss_db\historic_mua.jsonl"),
    "v5_results": Path(r"C:\MIRA backup full\11_01_2025\maptis-nlp\output\mua_v5_enriched_full\mua_v5_results_20251025_171636.ndjson"),
    "historic_v2_heavy": Path(r"C:\maptis-nlp\output\historic_muas_v2_heavy_cleaned.ndjson"),
    "rag_metadata": Path(r"C:\BoundState\data\mua_rag_precedents\metadata.jsonl"),
}

OUTPUT_DIR = Path(r"C:\BoundState\docs\mua_audit")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Keyword clusters for concern domain ────────────────────────────────────
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
    """Load a JSONL/NDJSON file, skipping bad lines."""
    records = []
    if not path.exists():
        return records
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # skip corrupt lines
    return records


def extract_field(rec, *field_names):
    """Try multiple field names, return first non-None value. Handles nested dicts."""
    for name in field_names:
        val = rec.get(name)
        if val is not None:
            return val
        # check nested 'data' dict (historic_mua format)
        if "data" in rec and isinstance(rec["data"], dict):
            val = rec["data"].get(name)
            if val is not None:
                return val
    return None


def get_text_blob(rec):
    """Concatenate all text fields for keyword search."""
    parts = []
    for field in ["rationale", "application", "issue", "environment", "conditions",
                  "determination", "specification", "trade_name", "material_designation",
                  "material_name"]:
        val = extract_field(rec, field)
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, dict):
            parts.append(json.dumps(val))
        elif isinstance(val, list):
            parts.append(" ".join(str(x) for x in val))
    return " ".join(parts).lower()


def get_material(rec):
    """Extract best material identifier."""
    mat = extract_field(rec, "material_designation", "material_name")
    if mat and isinstance(mat, str) and len(mat.strip()) > 0:
        return mat.strip()
    return "(no material)"


def get_source_file(rec):
    """Extract source file name."""
    f = extract_field(rec, "file", "source_file", "file_name", "source_path")
    if f:
        return str(f).split("/")[-1].split("\\")[-1]
    return "(unknown)"


def get_verbatim_text(rec):
    """Get the longest text field as verbatim content."""
    candidates = []
    for field in ["rationale", "application", "issue"]:
        val = extract_field(rec, field)
        if isinstance(val, str) and len(val) > 10:
            candidates.append((field, val))
    if not candidates:
        return "(no text)", "(no field)"
    candidates.sort(key=lambda x: len(x[1]), reverse=True)
    return candidates[0][1], candidates[0][0]


def match_clusters(text_blob):
    """Return set of cluster names that match."""
    matched = set()
    for cluster_name, keywords in KEYWORD_CLUSTERS.items():
        for kw in keywords:
            if kw in text_blob:
                matched.add(cluster_name)
                break
    return matched


# ─── STEP 1: Inventory all data sources ─────────────────────────────────────
print("=" * 60)
print("STEP 1: Inventorying data sources")
print("=" * 60)

source_info = {}
for name, path in DATA_SOURCES.items():
    exists = path.exists()
    size_mb = path.stat().st_size / 1024 / 1024 if exists else 0
    count = 0
    fields = set()
    sample = None
    if exists:
        recs = load_jsonl(path)
        count = len(recs)
        if recs:
            sample = recs[0]
            # collect all field names (including nested)
            for r in recs[:100]:
                fields.update(r.keys())
                if "data" in r and isinstance(r.get("data"), dict):
                    fields.update(f"data.{k}" for k in r["data"].keys())
                if "environment" in r and isinstance(r.get("environment"), dict):
                    fields.update(f"environment.{k}" for k in r["environment"].keys())
    source_info[name] = {
        "path": str(path),
        "exists": exists,
        "size_mb": round(size_mb, 1),
        "records": count,
        "fields": sorted(fields),
        "sample": sample,
    }
    status = f"  {name}: {count:,} records, {size_mb:.1f} MB" if exists else f"  {name}: NOT FOUND"
    print(status)

# ─── Pick primary dataset for profiling ─────────────────────────────────────
# Use v6_parsed as primary (most records), fall back to others
PRIMARY = "v6_parsed"
if source_info[PRIMARY]["records"] == 0:
    PRIMARY = "historic_mua"
primary_path = DATA_SOURCES[PRIMARY]
print(f"\nPrimary dataset: {PRIMARY} ({source_info[PRIMARY]['records']:,} records)")

records = load_jsonl(primary_path)
print(f"Loaded {len(records):,} records from {primary_path}")

# ─── STEP 2: Profile the data ───────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2: Profiling records")
print("=" * 60)

# 2a: Material frequency
material_counter = Counter()
for rec in records:
    mat = get_material(rec)
    material_counter[mat] += 1

print(f"Distinct materials: {len(material_counter):,}")
print(f"Top 20 materials:")
for mat, count in material_counter.most_common(20):
    print(f"  {count:>5}  {mat[:80]}")

# 2b: Keyword cluster frequency
cluster_counts = Counter()
cluster_records = defaultdict(list)  # cluster -> list of record indices
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

print(f"\nKeyword cluster frequencies:")
for cluster in ["FLAMM", "SCC", "CORR", "TOX", "FC", "TVS"]:
    print(f"  {cluster:>5}: {cluster_counts[cluster]:>5} records ({100*cluster_counts[cluster]/len(records):.1f}%)")
print(f"  {'NONE':>5}: {len(no_cluster_indices):>5} records ({100*len(no_cluster_indices)/len(records):.1f}%)")

# 2c: Source file distribution
source_counter = Counter()
for rec in records:
    src = get_source_file(rec)
    source_counter[src] += 1

print(f"\nSource files: {len(source_counter):,} distinct PDFs")
extractions_per_source = list(source_counter.values())
if extractions_per_source:
    avg_per = sum(extractions_per_source) / len(extractions_per_source)
    max_per = max(extractions_per_source)
    min_per = min(extractions_per_source)
    print(f"  Extractions per source: min={min_per}, avg={avg_per:.1f}, max={max_per}")
    multi = sum(1 for v in extractions_per_source if v > 1)
    print(f"  Sources with >1 extraction: {multi}")

# 2d: Text length analysis
rationale_lengths = []
application_lengths = []
issue_lengths = []
verbatim_lengths = []

for rec in records:
    r = extract_field(rec, "rationale")
    a = extract_field(rec, "application")
    iss = extract_field(rec, "issue")
    if isinstance(r, str):
        rationale_lengths.append(len(r))
    if isinstance(a, str):
        application_lengths.append(len(a))
    if isinstance(iss, str):
        issue_lengths.append(len(iss))
    vt, _ = get_verbatim_text(rec)
    if vt != "(no text)":
        verbatim_lengths.append(len(vt))

def stats(lengths, name):
    if not lengths:
        return f"  {name}: no data"
    lengths.sort()
    n = len(lengths)
    avg = sum(lengths) / n
    med = lengths[n // 2]
    p10 = lengths[int(n * 0.1)]
    p90 = lengths[int(n * 0.9)]
    return f"  {name}: n={n:,}, avg={avg:.0f}, med={med}, p10={p10}, p90={p90}, min={lengths[0]}, max={lengths[-1]}"

print(f"\nText field lengths (characters):")
print(stats(rationale_lengths, "rationale"))
print(stats(application_lengths, "application"))
print(stats(issue_lengths, "issue"))
print(stats(verbatim_lengths, "longest_text"))

# 2e: Category distribution
cat_counter = Counter()
for rec in records:
    cat = extract_field(rec, "category")
    cat_counter[str(cat) if cat else "(none)"] += 1

print(f"\nCategory distribution:")
for cat, count in cat_counter.most_common():
    print(f"  {cat:>10}: {count:>5}")

# 2f: Determination distribution
det_counter = Counter()
for rec in records:
    det = extract_field(rec, "determination")
    det_counter[str(det) if det else "(none)"] += 1

print(f"\nDetermination distribution:")
for det, count in det_counter.most_common():
    print(f"  {det:>15}: {count:>5}")

# 2g: Environment distribution
env_counter = Counter()
for rec in records:
    env = extract_field(rec, "environment")
    if isinstance(env, dict):
        env = env.get("type", env.get("raw_text", str(env)))
    env_counter[str(env)[:50] if env else "(none)"] += 1

print(f"\nEnvironment distribution:")
for env, count in env_counter.most_common(15):
    print(f"  {env:>50}: {count:>5}")

# 2h: Extraction mode
mode_counter = Counter()
for rec in records:
    mode = extract_field(rec, "extraction_mode", "extraction_method")
    mode_counter[str(mode) if mode else "(none)"] += 1

print(f"\nExtraction mode:")
for mode, count in mode_counter.most_common():
    print(f"  {mode:>20}: {count:>5}")

# 2i: Confidence distribution
confidences = []
for rec in records:
    c = extract_field(rec, "confidence")
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

# 2j: Success rate (v6_parsed has 'success' field)
success_counter = Counter()
for rec in records:
    s = rec.get("success")
    if s is not None:
        success_counter[str(s)] += 1

if success_counter:
    print(f"\nSuccess rate:")
    for s, count in success_counter.most_common():
        print(f"  {s:>10}: {count:>5}")


# ─── STEP 3: Stratified sample of 50 ────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3: Building stratified sample of 50")
print("=" * 60)

# Only use successful extractions for sampling
successful_indices = [i for i, rec in enumerate(records)
                      if rec.get("success", True) is True or rec.get("success") is None]
print(f"Successful records available for sampling: {len(successful_indices):,}")

sample_indices = set()

# 3a: 10 from most frequent materials
top_materials = [mat for mat, _ in material_counter.most_common(10)]
freq_mat_indices = []
for i in successful_indices:
    mat = get_material(records[i])
    if mat in top_materials and i not in sample_indices:
        freq_mat_indices.append(i)
chosen = random.sample(freq_mat_indices, min(10, len(freq_mat_indices)))
sample_indices.update(chosen)
print(f"10 from top materials: selected {len(chosen)}")

# 3b: 10 from each of top 3 concern domain clusters
top3_clusters = [c for c, _ in sorted(cluster_counts.items(), key=lambda x: x[1], reverse=True)[:3]]
print(f"Top 3 clusters: {top3_clusters}")

for cluster in top3_clusters:
    available = [i for i in cluster_records[cluster] if i not in sample_indices and i in set(successful_indices)]
    chosen = random.sample(available, min(10, len(available)))
    sample_indices.update(chosen)
    print(f"  {cluster}: selected {len(chosen)}")

# 3c: 10 from no-cluster (weird ones)
no_cluster_successful = [i for i in no_cluster_indices if i not in sample_indices and i in set(successful_indices)]
chosen = random.sample(no_cluster_successful, min(10, len(no_cluster_successful)))
sample_indices.update(chosen)
print(f"No cluster match: selected {len(chosen)}")

# 3d: 10 random from long tail (infrequent materials)
# Materials with count <= 3
longtail_materials = {mat for mat, count in material_counter.items() if count <= 3}
longtail_indices = [i for i in successful_indices
                    if get_material(records[i]) in longtail_materials and i not in sample_indices]
chosen = random.sample(longtail_indices, min(10, len(longtail_indices)))
sample_indices.update(chosen)
print(f"Long tail materials: selected {len(chosen)}")

# If we're short of 50, pad with random
if len(sample_indices) < 50:
    remaining = [i for i in successful_indices if i not in sample_indices]
    extra = random.sample(remaining, min(50 - len(sample_indices), len(remaining)))
    sample_indices.update(extra)
    print(f"Padding: added {len(extra)} random records")

# Trim to exactly 50 if over
sample_list = sorted(sample_indices)[:50]
print(f"Final sample size: {len(sample_list)}")


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT FILES
# ═══════════════════════════════════════════════════════════════════════════════

# ─── OUTPUT 1: mua_data_map.md ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("Writing mua_data_map.md")
print("=" * 60)

with open(OUTPUT_DIR / "mua_data_map.md", "w", encoding="utf-8") as f:
    f.write("# MUA Data Map\n\n")
    f.write(f"Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    f.write("## Data Sources Inventory\n\n")

    for name, info in source_info.items():
        f.write(f"### {name}\n\n")
        f.write(f"- **Path**: `{info['path']}`\n")
        f.write(f"- **Exists**: {'Yes' if info['exists'] else 'NO — file not found'}\n")
        if info['exists']:
            f.write(f"- **Size**: {info['size_mb']} MB\n")
            f.write(f"- **Records**: {info['records']:,}\n")
            f.write(f"- **Fields**: {', '.join(info['fields'])}\n")
        f.write("\n")

    f.write("## Additional Known Locations\n\n")
    f.write("| Location | Format | Est. Records | Notes |\n")
    f.write("|----------|--------|-------------|-------|\n")
    f.write("| `C:\\maptis-nlp\\mira\\databases\\mua_faiss_db\\` | FAISS + JSONL | 9,058 | Main vector DB, 768-dim all-mpnet-base-v2 |\n")
    f.write("| `C:\\maptis-nlp\\output\\historic_muas_v2_heavy.ndjson` | NDJSON | ~9,000+ | 122 MB, raw heavy extraction |\n")
    f.write("| `C:\\maptis-nlp\\output\\historic_muas_v2_heavy_cleaned.ndjson` | NDJSON | 5,958 | 73 MB, cleaned version |\n")
    f.write("| `C:\\BoundState\\data\\mua_rag_precedents\\` | FAISS + JSONL | 4,120 | 384-dim clip-ViT-B-32, RAG precedents |\n")
    f.write("| `C:\\BoundState\\data\\mua_v6_parsed_deduped.jsonl` | JSONL | 7,581 | Intermediate dedup stage |\n")
    f.write("| `C:\\maptis-nlp\\mira\\databases\\mua_bok_v2\\` | FAISS + JSON/PKL | varies | BOK v2 semantic index |\n")
    f.write("| `C:\\maptis-nlp\\mira\\databases\\mua_standards\\` | FAISS + JSON | 210 | Standards chunks (6016, JSC-27301F) |\n")
    f.write("| `C:\\MIRA backup full\\` | Multiple | varies | Full backup with multiple versions |\n")
    f.write("| `C:\\maptis-nlp\\mira\\databases\\mua_faiss_db_v5_clean\\` | FAISS | varies | v5 clean variant |\n")
    f.write("| `C:\\maptis-nlp\\mira\\databases\\mua_faiss_db_v5_nasa\\` | FAISS | varies | v5 NASA variant |\n")
    f.write("| `C:\\BoundState\\data\\mua_page_mapping.jsonl` | JSONL | 3,923 | Page-to-extraction mapping |\n")
    f.write("| `C:\\BoundState\\data\\mua_failed_page_mapping.jsonl` | JSONL | 3,609 | Failed extraction pages |\n")
    f.write("\n")

    f.write("## Primary Dataset Schema (v6_parsed)\n\n")
    f.write("The primary profiling dataset is `mua_v6_parsed_results.jsonl`.\n\n")
    f.write("| Field | Type | Description |\n")
    f.write("|-------|------|-------------|\n")
    f.write("| `file` | string | Source PDF filename (e.g., `1000-0003.pdf`) |\n")
    f.write("| `success` | bool | Whether extraction succeeded |\n")
    f.write("| `time_seconds` | float | Extraction time |\n")
    f.write("| `confidence` | float | 0.0–1.0 extraction confidence |\n")
    f.write("| `material_designation` | string | Material name/designation |\n")
    f.write("| `mua_number` | string | MUA document number |\n")
    f.write("| `category` | string | MUA category (I, II, etc.) |\n")
    f.write("| `determination` | string | APPROVED, CONDITIONAL, etc. |\n")
    f.write("| `environment` | string | Vacuum, Oxygen, Habitable, etc. |\n")
    f.write("| `location` | string | Habitable, Nonhabitable |\n")
    f.write("| `application` | string | What the material is used for (free text) |\n")
    f.write("| `rationale` | string | Why deviation is acceptable (free text) |\n")
    f.write("| `issue` | string | Concern domain description (free text) |\n")
    f.write("| `manufacturer` | string | Material manufacturer |\n")
    f.write("| `trade_name` | string | Commercial name |\n")
    f.write("| `specification` | string | Governing spec (MIL, AMS, etc.) |\n")
    f.write("| `max_pressure` | float | Max pressure (PSIA) |\n")
    f.write("| `pressure_units` | string | Pressure units |\n")
    f.write("| `max_temperature_f` | float | Max temperature (°F) |\n")
    f.write("| `test_reports` | array | Related test report references |\n")
    f.write("| `extraction_mode` | string | vision or text |\n")
    f.write("\n")

    f.write("## Cleaned Dataset Schema (v6_cleaned)\n\n")
    f.write("The `mua_v6_cleaned.jsonl` adds:\n\n")
    f.write("| Field | Type | Description |\n")
    f.write("|-------|------|-------------|\n")
    f.write("| `material_family` | string | Normalized family (aluminum, stainless_steel, adhesive, etc.) |\n")
    f.write("| `issues` | array | Parsed concern list: [\"scc\", \"flammability\", \"tvs\", ...] |\n")
    f.write("| `environment` | object | `{type, o2_percent, pressure_psia, temperature_f, is_habitable, raw_text}` |\n")
    f.write("| `source_file` | string | Source PDF (replaces `file`) |\n")
    f.write("\n")

    f.write("## Extraction Pipeline Lineage\n\n")
    f.write("```\n")
    f.write("MUA PDFs (C:\\BoundState\\data\\mua_pdfs\\)  [~700 files, 8.8 GB]\n")
    f.write("  ├─ mua_parser_v5 (vision extraction)\n")
    f.write("  │   └─ historic_mua.jsonl (9,058 records, nested format)\n")
    f.write("  ├─ v6 pipeline (vision + text extraction)\n")
    f.write("  │   ├─ mua_v6_parsed_results.jsonl (13,786 records, flat format)\n")
    f.write("  │   ├─ mua_v6_parsed_deduped.jsonl (7,581 records)\n")
    f.write("  │   └─ mua_v6_cleaned.jsonl (6,370 records, structured)\n")
    f.write("  ├─ FAISS indexing\n")
    f.write("  │   ├─ mua_faiss_db/ (768-dim, 9,058 vectors)\n")
    f.write("  │   ├─ mua_rag_precedents/ (384-dim, 4,120 vectors)\n")
    f.write("  │   └─ mua_bok_v2/ (semantic BOK index)\n")
    f.write("  └─ PostgreSQL mua_precedents_v7 (loaded from v6_cleaned)\n")
    f.write("```\n\n")

    f.write("## Key Scripts\n\n")
    f.write("| Script | Purpose |\n")
    f.write("|--------|--------|\n")
    f.write("| `sandbox/scripts/bok_ultimate_extract.py` | 3-phase universal extraction (page scan → normalize → extract) |\n")
    f.write("| `sandbox/scripts/universal_extract.py` | Schema discovery + extraction |\n")
    f.write("| `sandbox/scripts/build_mua_bok_index_v2.py` | Build FAISS index from v6 results |\n")
    f.write("| `scripts/migrate_mua_v7.py` | Load v6_cleaned into PostgreSQL |\n")
    f.write("| `scripts/test_mua_v6_pipeline.py` | v6 pipeline testing |\n")

print("  [OK] mua_data_map.md written")


# ─── OUTPUT 2: mua_profile_report.md ────────────────────────────────────────
print("Writing mua_profile_report.md")

with open(OUTPUT_DIR / "mua_profile_report.md", "w", encoding="utf-8") as f:
    f.write("# MUA Extraction Profile Report\n\n")
    f.write(f"Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    f.write(f"**Primary dataset**: `{primary_path}` ({len(records):,} records)\n\n")

    # Summary
    successful = sum(1 for r in records if r.get("success", True) is True)
    failed = len(records) - successful
    f.write("## Summary\n\n")
    f.write(f"| Metric | Value |\n")
    f.write(f"|--------|-------|\n")
    f.write(f"| Total records | {len(records):,} |\n")
    f.write(f"| Successful extractions | {successful:,} |\n")
    f.write(f"| Failed extractions | {failed:,} |\n")
    f.write(f"| Distinct materials | {len(material_counter):,} |\n")
    f.write(f"| Distinct source PDFs | {len(source_counter):,} |\n")
    if confidences:
        f.write(f"| Avg confidence | {sum(confidences)/len(confidences):.2f} |\n")
    f.write("\n")

    # Material frequency
    f.write("## Material Designation Frequency\n\n")
    f.write("### Top 40 Materials\n\n")
    f.write("| Rank | Material | Count | % |\n")
    f.write("|------|----------|-------|---|\n")
    for rank, (mat, count) in enumerate(material_counter.most_common(40), 1):
        pct = 100 * count / len(records)
        mat_display = mat[:80].replace("|", "\\|")
        f.write(f"| {rank} | {mat_display} | {count} | {pct:.1f}% |\n")
    f.write("\n")

    # Long tail
    tail_1 = sum(1 for c in material_counter.values() if c == 1)
    tail_2_3 = sum(1 for c in material_counter.values() if 2 <= c <= 3)
    tail_4_10 = sum(1 for c in material_counter.values() if 4 <= c <= 10)
    tail_gt10 = sum(1 for c in material_counter.values() if c > 10)
    f.write("### Material Frequency Distribution\n\n")
    f.write("| Frequency | # Materials | % of distinct |\n")
    f.write("|-----------|------------|---------------|\n")
    f.write(f"| Appears once | {tail_1} | {100*tail_1/len(material_counter):.1f}% |\n")
    f.write(f"| 2–3 times | {tail_2_3} | {100*tail_2_3/len(material_counter):.1f}% |\n")
    f.write(f"| 4–10 times | {tail_4_10} | {100*tail_4_10/len(material_counter):.1f}% |\n")
    f.write(f"| >10 times | {tail_gt10} | {100*tail_gt10/len(material_counter):.1f}% |\n")
    f.write("\n")

    # Keyword cluster frequency
    f.write("## Concern Domain Keyword Clusters\n\n")
    f.write("Each record's `rationale`, `application`, and `issue` fields were searched for keyword signals.\n\n")
    f.write("| Cluster | Keywords (sample) | Records | % |\n")
    f.write("|---------|-------------------|---------|---|\n")
    for cluster in ["FLAMM", "SCC", "CORR", "TOX", "FC", "TVS"]:
        kws = ", ".join(KEYWORD_CLUSTERS[cluster][:4])
        cnt = cluster_counts[cluster]
        pct = 100 * cnt / len(records)
        f.write(f"| {cluster} | {kws} | {cnt:,} | {pct:.1f}% |\n")
    f.write(f"| NONE | (no cluster match) | {len(no_cluster_indices):,} | {100*len(no_cluster_indices)/len(records):.1f}% |\n")
    f.write("\n")

    # Multi-cluster overlap
    f.write("### Multi-Cluster Records\n\n")
    multi_cluster_counts = Counter()
    for i in range(len(records)):
        blob = get_text_blob(records[i])
        matched = match_clusters(blob)
        multi_cluster_counts[len(matched)] += 1
    f.write("| # Clusters Matched | Records | % |\n")
    f.write("|-------------------|---------|---|\n")
    for n_clusters in sorted(multi_cluster_counts.keys()):
        cnt = multi_cluster_counts[n_clusters]
        f.write(f"| {n_clusters} | {cnt:,} | {100*cnt/len(records):.1f}% |\n")
    f.write("\n")

    # Source file distribution
    f.write("## Source File Distribution\n\n")
    f.write(f"- **Distinct source PDFs**: {len(source_counter):,}\n")
    if extractions_per_source:
        f.write(f"- **Extractions per source**: min={min_per}, avg={avg_per:.1f}, max={max_per}\n")
        f.write(f"- **Sources with >1 extraction**: {multi}\n\n")

    f.write("### Top 20 Source Files (by extraction count)\n\n")
    f.write("| Source PDF | Extractions |\n")
    f.write("|-----------|------------|\n")
    for src, count in source_counter.most_common(20):
        f.write(f"| {src} | {count} |\n")
    f.write("\n")

    # Extractions per source histogram
    hist_bins = [(1, 1), (2, 2), (3, 5), (6, 10), (11, 50), (51, 999)]
    f.write("### Extractions Per Source Histogram\n\n")
    f.write("| Range | # Sources | % |\n")
    f.write("|-------|----------|---|\n")
    for lo, hi in hist_bins:
        cnt = sum(1 for v in extractions_per_source if lo <= v <= hi)
        label = f"{lo}" if lo == hi else f"{lo}–{hi}"
        f.write(f"| {label} | {cnt} | {100*cnt/len(source_counter):.1f}% |\n")
    f.write("\n")

    # Text length
    f.write("## Text Field Lengths\n\n")
    f.write("Measured in characters.\n\n")
    f.write("| Field | N | Avg | Median | P10 | P90 | Min | Max |\n")
    f.write("|-------|---|-----|--------|-----|-----|-----|-----|\n")
    for name, lengths in [("rationale", rationale_lengths), ("application", application_lengths),
                          ("issue", issue_lengths)]:
        if lengths:
            lengths_sorted = sorted(lengths)
            n = len(lengths_sorted)
            avg = sum(lengths_sorted) / n
            med = lengths_sorted[n // 2]
            p10 = lengths_sorted[int(n * 0.1)]
            p90 = lengths_sorted[int(n * 0.9)]
            f.write(f"| {name} | {n:,} | {avg:.0f} | {med} | {p10} | {p90} | {lengths_sorted[0]} | {lengths_sorted[-1]} |\n")
    f.write("\n")

    f.write("### Assessment\n\n")
    if rationale_lengths:
        avg_rat = sum(rationale_lengths) / len(rationale_lengths)
        if avg_rat > 200:
            f.write("- Rationale texts are **full paragraphs** (avg > 200 chars) — good signal for WHY/HOW decomposition\n")
        else:
            f.write("- Rationale texts are **fragments** (avg < 200 chars) — may need to pull from multiple fields\n")
    if application_lengths:
        avg_app = sum(application_lengths) / len(application_lengths)
        if avg_app > 200:
            f.write("- Application texts are **full paragraphs** — good signal for WHAT decomposition\n")
        else:
            f.write("- Application texts are **fragments** — may need enrichment\n")
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

print("  [OK] mua_profile_report.md written")


# ─── OUTPUT 3: mua_sample_50.md ─────────────────────────────────────────────
print("Writing mua_sample_50.md")

with open(OUTPUT_DIR / "mua_sample_50.md", "w", encoding="utf-8") as f:
    f.write("# MUA Stratified Sample — 50 Records for Manual Audit\n\n")
    f.write(f"Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    f.write("## Sampling Strategy\n\n")
    f.write(f"- 10 from **most frequent materials** (top 10 by count)\n")
    f.write(f"- 10 from each of **top 3 concern domain clusters**: {', '.join(top3_clusters)}\n")
    f.write(f"- 10 from records matching **no keyword cluster** (the weird ones)\n")
    f.write(f"- Remainder from **long tail** materials (count ≤ 3)\n")
    f.write(f"- Total: {len(sample_list)} records\n\n")

    f.write("## Audit Instructions\n\n")
    f.write("For each record, manually tag:\n\n")
    f.write("1. **WHAT** — Can you identify a specific material? (Y/N, and what is it?)\n")
    f.write("2. **WHY** — Can you identify a concern domain? (FLAMM/SCC/CORR/TOX/FC/TVS/OTHER)\n")
    f.write("3. **HOW** — Is there a mitigation pattern? (test data, engineering rationale, usage limits, etc.)\n")
    f.write("4. **QUALITY** — Is the text coherent? (Good / Partial / Garbage)\n\n")
    f.write("---\n\n")

    for sample_num, idx in enumerate(sample_list, 1):
        rec = records[idx]
        material = get_material(rec)
        source = get_source_file(rec)
        mua_num = extract_field(rec, "mua_number") or "(unknown)"
        category = extract_field(rec, "category") or "(none)"
        issue = extract_field(rec, "issue") or "(none)"
        environment = extract_field(rec, "environment") or "(none)"
        if isinstance(environment, dict):
            environment = environment.get("raw_text", environment.get("type", str(environment)))
        determination = extract_field(rec, "determination") or "(none)"
        rationale = extract_field(rec, "rationale") or "(none)"
        application = extract_field(rec, "application") or "(none)"
        confidence = extract_field(rec, "confidence")
        confidence_str = f"{confidence:.2f}" if confidence else "(none)"

        # Determine which sample bucket this came from
        blob = get_text_blob(rec)
        matched = match_clusters(blob)
        bucket = "unknown"
        if material in top_materials:
            bucket = "TOP_MATERIAL"
        elif not matched:
            bucket = "NO_CLUSTER"
        elif material in longtail_materials:
            bucket = "LONG_TAIL"
        else:
            for c in top3_clusters:
                if c in matched:
                    bucket = c
                    break

        f.write(f"### Record {sample_num} of {len(sample_list)}\n\n")
        f.write(f"| Field | Value |\n")
        f.write(f"|-------|-------|\n")
        f.write(f"| **Record Index** | {idx} |\n")
        f.write(f"| **Sample Bucket** | {bucket} |\n")
        f.write(f"| **Source File** | `{source}` |\n")
        f.write(f"| **MUA Number** | {mua_num} |\n")
        f.write(f"| **Material** | {material[:100]} |\n")
        f.write(f"| **Category** | {category} |\n")
        f.write(f"| **Issue** | {str(issue)[:150]} |\n")
        f.write(f"| **Environment** | {str(environment)[:80]} |\n")
        f.write(f"| **Determination** | {determination} |\n")
        f.write(f"| **Confidence** | {confidence_str} |\n")
        f.write(f"| **Cluster Matches** | {', '.join(sorted(matched)) if matched else 'NONE'} |\n")
        f.write(f"\n")

        f.write(f"**Application (WHAT)**:\n")
        f.write(f"> {str(application)[:1000]}\n\n")

        f.write(f"**Rationale (WHY/HOW)**:\n")
        f.write(f"> {str(rationale)[:1000]}\n\n")

        f.write(f"**Issue (concern domain)**:\n")
        f.write(f"> {str(issue)[:500]}\n\n")

        # Manual audit fields
        f.write("**Manual Audit Tags**:\n")
        f.write("- WHAT: ___\n")
        f.write("- WHY: ___\n")
        f.write("- HOW: ___\n")
        f.write("- QUALITY: ___\n\n")
        f.write("---\n\n")

print("  [OK] mua_sample_50.md written")

print(f"\n{'=' * 60}")
print(f"DONE — All 3 files written to {OUTPUT_DIR}")
print(f"{'=' * 60}")
