"""
MUA v6 Missing Material Designation Diagnostic
================================================
Analyzes why 52.2% of v6_parsed records have no material_designation,
cross-references with historic_mua, v6_cleaned, and FAISS metadata
to determine recoverability.
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Force UTF-8 output to avoid Windows cp1252 encoding errors
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ─── File paths ───
V6_PARSED = "C:/BoundState/data/mua_v6_parsed_results.jsonl"
HISTORIC_MUA = "C:/maptis-nlp/mira/databases/mua_faiss_db/historic_mua.jsonl"
V6_CLEANED = "C:/BoundState/data/mua_v6_cleaned.jsonl"
FAISS_META = "C:/BoundState/data/mua_rag_precedents/metadata.jsonl"


def load_jsonl(path):
    """Load a JSONL file into a list of dicts."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def is_empty(val):
    """Check if a value is effectively empty."""
    if val is None:
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False


def has_material(record):
    """Check if a v6_parsed record has a material_designation."""
    return not is_empty(record.get("material_designation"))


def print_separator(char="=", width=80):
    print(char * width)


def main():
    print_separator()
    print("MUA v6 MISSING MATERIAL DESIGNATION DIAGNOSTIC")
    print_separator()
    print()

    # ─── Load all datasets ───
    print("Loading datasets...")
    v6_parsed = load_jsonl(V6_PARSED)
    historic = load_jsonl(HISTORIC_MUA)
    v6_cleaned = load_jsonl(V6_CLEANED)
    faiss_meta = load_jsonl(FAISS_META)

    print(f"  v6_parsed:    {len(v6_parsed):,} records")
    print(f"  historic_mua: {len(historic):,} records")
    print(f"  v6_cleaned:   {len(v6_cleaned):,} records")
    print(f"  faiss_meta:   {len(faiss_meta):,} records")
    print()

    # ─── Split v6_parsed into has-material vs no-material ───
    with_mat = [r for r in v6_parsed if has_material(r)]
    no_mat = [r for r in v6_parsed if not has_material(r)]

    print(f"v6_parsed breakdown:")
    print(f"  WITH material_designation:  {len(with_mat):,} ({100*len(with_mat)/len(v6_parsed):.1f}%)")
    print(f"  WITHOUT material_designation: {len(no_mat):,} ({100*len(no_mat)/len(v6_parsed):.1f}%)")
    print()

    # ═══════════════════════════════════════════════════════════════
    # ANALYSIS 1: Are "(no material)" records completely empty?
    # ═══════════════════════════════════════════════════════════════
    print_separator()
    print("ANALYSIS 1: Are '(no material)' records empty failed extractions?")
    print_separator()
    print()

    # Check key content fields
    content_fields = ["material_designation", "rationale", "application", "issue"]
    extended_fields = ["material_designation", "rationale", "application", "issue",
                       "manufacturer", "trade_name", "specification", "mua_number",
                       "category", "determination", "environment"]

    # Count records where ALL core content fields are empty
    all_core_empty = 0
    all_extended_empty = 0
    has_some_content = 0

    for r in no_mat:
        core_empty = all(is_empty(r.get(f)) for f in content_fields)
        ext_empty = all(is_empty(r.get(f)) for f in extended_fields)

        if core_empty:
            all_core_empty += 1
        else:
            has_some_content += 1
        if ext_empty:
            all_extended_empty += 1

    print(f"Of {len(no_mat):,} records with no material_designation:")
    print(f"  ALL 4 core fields empty (material, rationale, application, issue): {all_core_empty:,} ({100*all_core_empty/len(no_mat):.1f}%)")
    print(f"  ALL 11 extended fields empty:                                      {all_extended_empty:,} ({100*all_extended_empty/len(no_mat):.1f}%)")
    print(f"  Have SOME content (rationale/application/issue present):           {has_some_content:,} ({100*has_some_content/len(no_mat):.1f}%)")
    print()

    # Show first 20 no-material records with their content status
    print("First 20 '(no material)' records:")
    print(f"  {'#':>3}  {'File':<20} {'Conf':>5}  {'MUA#':<15} {'Rationale?':>10} {'Application?':>12} {'Issue?':>7}")
    print(f"  {'---':>3}  {'----':<20} {'----':>5}  {'----':<15} {'----------':>10} {'------------':>12} {'------':>7}")
    for i, r in enumerate(no_mat[:20]):
        fname = r.get("file", "?")[:20]
        conf = r.get("confidence", 0)
        mua = str(r.get("mua_number", ""))[:15]
        has_rat = "Yes" if not is_empty(r.get("rationale")) else "No"
        has_app = "Yes" if not is_empty(r.get("application")) else "No"
        has_iss = "Yes" if not is_empty(r.get("issue")) else "No"
        print(f"  {i+1:>3}  {fname:<20} {conf:>5.2f}  {mua:<15} {has_rat:>10} {has_app:>12} {has_iss:>7}")
    print()

    # Breakdown of which content fields ARE present in no-material records
    print("Field presence in no-material records:")
    check_fields = ["rationale", "application", "issue", "mua_number", "category",
                    "determination", "environment", "manufacturer", "specification",
                    "trade_name", "location"]
    for f in check_fields:
        present = sum(1 for r in no_mat if not is_empty(r.get(f)))
        print(f"  {f:<25} present: {present:>6,} ({100*present/len(no_mat):>5.1f}%)")
    print()

    # ═══════════════════════════════════════════════════════════════
    # ANALYSIS 2: Cross-reference with historic_mua.jsonl
    # ═══════════════════════════════════════════════════════════════
    print_separator()
    print("ANALYSIS 2: Cross-reference with historic_mua.jsonl")
    print_separator()
    print()

    # Build lookup by file_name from historic
    historic_by_file = {}
    historic_mat_count = 0
    historic_no_mat = 0
    for r in historic:
        fname = r.get("file_name", "")
        mat_name = r.get("data", {}).get("material_name", "")
        historic_by_file[fname] = mat_name
        if not is_empty(mat_name):
            historic_mat_count += 1
        else:
            historic_no_mat += 1

    print(f"historic_mua.jsonl: {len(historic):,} records")
    print(f"  With material_name:    {historic_mat_count:,} ({100*historic_mat_count/len(historic):.1f}%)")
    print(f"  Without material_name: {historic_no_mat:,} ({100*historic_no_mat/len(historic):.1f}%)")
    print()

    # For no-material v6_parsed records, check if historic has a material
    recoverable_from_historic = 0
    no_match_in_historic = 0
    match_but_no_mat_historic = 0

    recovery_examples = []

    for r in no_mat:
        fname = r.get("file", "")
        if fname in historic_by_file:
            hist_mat = historic_by_file[fname]
            if not is_empty(hist_mat):
                recoverable_from_historic += 1
                if len(recovery_examples) < 10:
                    recovery_examples.append((fname, hist_mat))
            else:
                match_but_no_mat_historic += 1
        else:
            no_match_in_historic += 1

    print(f"Of {len(no_mat):,} no-material v6_parsed records:")
    print(f"  Recoverable from historic (file match + has material_name): {recoverable_from_historic:,} ({100*recoverable_from_historic/len(no_mat):.1f}%)")
    print(f"  File match but historic also has no material:               {match_but_no_mat_historic:,} ({100*match_but_no_mat_historic/len(no_mat):.1f}%)")
    print(f"  No file match in historic at all:                           {no_match_in_historic:,} ({100*no_match_in_historic/len(no_mat):.1f}%)")
    print()

    if recovery_examples:
        print("  Examples of recoverable materials from historic:")
        for fname, mat in recovery_examples:
            print(f"    {fname:<25} -> \"{mat}\"")
    print()

    # Also check: for WITH-material records, how many have a historic match?
    with_mat_in_historic = sum(1 for r in with_mat if r.get("file", "") in historic_by_file)
    print(f"  (For reference: {with_mat_in_historic:,} of {len(with_mat):,} WITH-material records also exist in historic)")
    print()

    # ═══════════════════════════════════════════════════════════════
    # ANALYSIS 3: Cross-reference with v6_cleaned.jsonl
    # ═══════════════════════════════════════════════════════════════
    print_separator()
    print("ANALYSIS 3: Cross-reference with v6_cleaned.jsonl")
    print_separator()
    print()

    # v6_cleaned uses "source_file" field
    cleaned_with_mat = 0
    cleaned_no_mat = 0
    cleaned_by_file = {}
    for r in v6_cleaned:
        fname = r.get("source_file", "")
        mat = r.get("material_designation", "")
        mat_fam = r.get("material_family", "")
        cleaned_by_file[fname] = {"material_designation": mat, "material_family": mat_fam}
        if not is_empty(mat):
            cleaned_with_mat += 1
        else:
            cleaned_no_mat += 1

    print(f"v6_cleaned.jsonl: {len(v6_cleaned):,} records")
    print(f"  With material_designation:    {cleaned_with_mat:,} ({100*cleaned_with_mat/len(v6_cleaned):.1f}%)")
    print(f"  Without material_designation: {cleaned_no_mat:,} ({100*cleaned_no_mat/len(v6_cleaned):.1f}%)")
    print()

    # How many no-material v6_parsed records exist in v6_cleaned?
    recovered_from_cleaned = 0
    in_cleaned_but_still_no_mat = 0
    not_in_cleaned = 0
    cleaned_recovery_examples = []

    for r in no_mat:
        fname = r.get("file", "")
        if fname in cleaned_by_file:
            c = cleaned_by_file[fname]
            if not is_empty(c["material_designation"]):
                recovered_from_cleaned += 1
                if len(cleaned_recovery_examples) < 10:
                    cleaned_recovery_examples.append((fname, c["material_designation"], c["material_family"]))
            else:
                in_cleaned_but_still_no_mat += 1
        else:
            not_in_cleaned += 1

    print(f"Of {len(no_mat):,} no-material v6_parsed records:")
    print(f"  In v6_cleaned WITH material:    {recovered_from_cleaned:,} ({100*recovered_from_cleaned/len(no_mat):.1f}%)")
    print(f"  In v6_cleaned WITHOUT material: {in_cleaned_but_still_no_mat:,} ({100*in_cleaned_but_still_no_mat/len(no_mat):.1f}%)")
    print(f"  Not in v6_cleaned at all:       {not_in_cleaned:,} ({100*not_in_cleaned/len(no_mat):.1f}%)")
    print()

    if cleaned_recovery_examples:
        print("  Examples of v6_cleaned records (these should NOT exist since cleaned = parsed with material):")
        for fname, mat, fam in cleaned_recovery_examples:
            print(f"    {fname:<25} -> \"{mat}\" (family: {fam})")
    print()

    # ═══════════════════════════════════════════════════════════════
    # ANALYSIS 4: FAISS metadata check
    # ═══════════════════════════════════════════════════════════════
    print_separator()
    print("ANALYSIS 4: FAISS RAG metadata.jsonl")
    print_separator()
    print()

    faiss_with_mat = 0
    faiss_no_mat = 0
    faiss_by_id = {}
    faiss_mat_names = []

    for r in faiss_meta:
        mua_id = r.get("mua_id", "")
        mat_name = r.get("material_name")
        faiss_by_id[mua_id] = mat_name
        if not is_empty(mat_name):
            faiss_with_mat += 1
            faiss_mat_names.append(mat_name)
        else:
            faiss_no_mat += 1

    print(f"FAISS metadata.jsonl: {len(faiss_meta):,} records")
    print(f"  With material_name:    {faiss_with_mat:,} ({100*faiss_with_mat/len(faiss_meta):.1f}%)")
    print(f"  Without material_name: {faiss_no_mat:,} ({100*faiss_no_mat/len(faiss_meta):.1f}%)")
    print()

    # Cross-reference: no-material v6_parsed by mua_id
    # v6_parsed has "mua_number", faiss has "mua_id"
    # But also try matching by file stem (e.g., "1000-0003.pdf" -> "1000-0003")
    recovered_from_faiss_by_mua = 0
    recovered_from_faiss_by_file = 0
    faiss_recovery_examples = []

    for r in no_mat:
        mua_num = r.get("mua_number", "")
        fname = r.get("file", "")
        file_stem = fname.replace(".pdf", "") if fname else ""

        # Try matching by mua_number
        if mua_num and mua_num in faiss_by_id:
            if not is_empty(faiss_by_id[mua_num]):
                recovered_from_faiss_by_mua += 1
                if len(faiss_recovery_examples) < 5:
                    faiss_recovery_examples.append(("mua_num", mua_num, faiss_by_id[mua_num]))
                continue

        # Try matching by file stem
        if file_stem and file_stem in faiss_by_id:
            if not is_empty(faiss_by_id[file_stem]):
                recovered_from_faiss_by_file += 1
                if len(faiss_recovery_examples) < 10:
                    faiss_recovery_examples.append(("file_stem", file_stem, faiss_by_id[file_stem]))

    print(f"Of {len(no_mat):,} no-material v6_parsed records:")
    print(f"  Recoverable via mua_number match:  {recovered_from_faiss_by_mua:,}")
    print(f"  Recoverable via file stem match:   {recovered_from_faiss_by_file:,}")
    print(f"  Total recoverable from FAISS:      {recovered_from_faiss_by_mua + recovered_from_faiss_by_file:,}")
    print()

    if faiss_recovery_examples:
        print("  Examples:")
        for match_type, key, mat in faiss_recovery_examples:
            print(f"    [{match_type}] {key:<20} -> \"{mat}\"")
    print()

    # ═══════════════════════════════════════════════════════════════
    # ANALYSIS 5: Characterize the empty records
    # ═══════════════════════════════════════════════════════════════
    print_separator()
    print("ANALYSIS 5: Characterize the no-material records")
    print_separator()
    print()

    # 5a: Confidence score distribution
    print("5a. Confidence score distribution (no-material records):")
    conf_buckets = Counter()
    conf_values = []
    for r in no_mat:
        c = r.get("confidence", 0)
        if c is None:
            c = 0
        conf_values.append(c)
        if c == 0:
            conf_buckets["0.0 (zero)"] += 1
        elif c <= 0.2:
            conf_buckets["0.01-0.20"] += 1
        elif c <= 0.4:
            conf_buckets["0.21-0.40"] += 1
        elif c <= 0.6:
            conf_buckets["0.41-0.60"] += 1
        elif c <= 0.8:
            conf_buckets["0.61-0.80"] += 1
        elif c < 1.0:
            conf_buckets["0.81-0.99"] += 1
        else:
            conf_buckets["1.0 (perfect)"] += 1

    for bucket in ["0.0 (zero)", "0.01-0.20", "0.21-0.40", "0.41-0.60",
                    "0.61-0.80", "0.81-0.99", "1.0 (perfect)"]:
        count = conf_buckets.get(bucket, 0)
        pct = 100 * count / len(no_mat)
        bar = "#" * int(pct / 2)
        print(f"  {bucket:<15} {count:>6,} ({pct:>5.1f}%)  {bar}")

    avg_conf = sum(conf_values) / len(conf_values) if conf_values else 0
    print(f"  Average confidence: {avg_conf:.3f}")
    print()

    # Compare with WITH-material confidence
    print("  For comparison - confidence of WITH-material records:")
    with_conf = [r.get("confidence", 0) or 0 for r in with_mat]
    avg_with = sum(with_conf) / len(with_conf) if with_conf else 0
    conf_buckets_with = Counter()
    for c in with_conf:
        if c == 0:
            conf_buckets_with["0.0 (zero)"] += 1
        elif c <= 0.2:
            conf_buckets_with["0.01-0.20"] += 1
        elif c <= 0.4:
            conf_buckets_with["0.21-0.40"] += 1
        elif c <= 0.6:
            conf_buckets_with["0.41-0.60"] += 1
        elif c <= 0.8:
            conf_buckets_with["0.61-0.80"] += 1
        elif c < 1.0:
            conf_buckets_with["0.81-0.99"] += 1
        else:
            conf_buckets_with["1.0 (perfect)"] += 1
    for bucket in ["0.0 (zero)", "0.01-0.20", "0.21-0.40", "0.41-0.60",
                    "0.61-0.80", "0.81-0.99", "1.0 (perfect)"]:
        count = conf_buckets_with.get(bucket, 0)
        pct = 100 * count / len(with_mat)
        bar = "#" * int(pct / 2)
        print(f"  {bucket:<15} {count:>6,} ({pct:>5.1f}%)  {bar}")
    print(f"  Average confidence: {avg_with:.3f}")
    print()

    # 5b: Extraction mode distribution
    print("5b. Extraction mode distribution:")
    mode_no = Counter(r.get("extraction_mode", "unknown") or "unknown" for r in no_mat)
    mode_with = Counter(r.get("extraction_mode", "unknown") or "unknown" for r in with_mat)

    print("  No-material records:")
    for mode, count in mode_no.most_common():
        print(f"    {mode:<20} {count:>6,} ({100*count/len(no_mat):>5.1f}%)")
    print("  With-material records:")
    for mode, count in mode_with.most_common():
        print(f"    {mode:<20} {count:>6,} ({100*count/len(with_mat):>5.1f}%)")
    print()

    # 5c: Do they have ANY text at all?
    print("5c. Text content presence in no-material records:")
    text_fields = ["rationale", "application", "issue"]
    has_any_text = 0
    has_no_text = 0
    total_text_lengths = []

    for r in no_mat:
        text_parts = []
        for f in text_fields:
            val = r.get(f, "")
            if val and isinstance(val, str):
                text_parts.append(val)
        combined = " ".join(text_parts).strip()
        total_text_lengths.append(len(combined))
        if len(combined) > 10:  # more than trivial text
            has_any_text += 1
        else:
            has_no_text += 1

    print(f"  Records with meaningful text (>10 chars in rationale/application/issue): {has_any_text:,} ({100*has_any_text/len(no_mat):.1f}%)")
    print(f"  Records with NO meaningful text:                                         {has_no_text:,} ({100*has_no_text/len(no_mat):.1f}%)")

    # Text length distribution
    len_buckets = Counter()
    for tl in total_text_lengths:
        if tl == 0:
            len_buckets["0 chars"] += 1
        elif tl <= 10:
            len_buckets["1-10 chars"] += 1
        elif tl <= 100:
            len_buckets["11-100 chars"] += 1
        elif tl <= 500:
            len_buckets["101-500 chars"] += 1
        elif tl <= 1000:
            len_buckets["501-1000 chars"] += 1
        else:
            len_buckets["1000+ chars"] += 1

    print("  Combined text length distribution:")
    for bucket in ["0 chars", "1-10 chars", "11-100 chars", "101-500 chars",
                    "501-1000 chars", "1000+ chars"]:
        count = len_buckets.get(bucket, 0)
        pct = 100 * count / len(no_mat) if no_mat else 0
        bar = "#" * int(pct / 2)
        print(f"    {bucket:<16} {count:>6,} ({pct:>5.1f}%)  {bar}")
    print()

    # 5d: success=True breakdown
    print("5d. success field distribution in no-material records:")
    success_counter = Counter(r.get("success") for r in no_mat)
    for val, count in success_counter.most_common():
        print(f"  success={val!s:<8} {count:>6,} ({100*count/len(no_mat):>5.1f}%)")
    print()

    # ═══════════════════════════════════════════════════════════════
    # COMBINED RECOVERY ANALYSIS
    # ═══════════════════════════════════════════════════════════════
    print_separator()
    print("COMBINED RECOVERY ANALYSIS")
    print_separator()
    print()

    # Build set of files recoverable from any source
    recoverable_file_set = set()

    # Historic recoverable files
    for r in no_mat:
        fname = r.get("file", "")
        if fname in historic_by_file and not is_empty(historic_by_file[fname]):
            recoverable_file_set.add(fname)
    historic_file_set = set(recoverable_file_set)

    # FAISS recoverable files (additive)
    faiss_file_set = set()
    for r in no_mat:
        fname = r.get("file", "")
        if fname in recoverable_file_set:
            continue
        mua_num = r.get("mua_number", "")
        file_stem = fname.replace(".pdf", "") if fname else ""
        if (mua_num and mua_num in faiss_by_id and not is_empty(faiss_by_id[mua_num])):
            recoverable_file_set.add(fname)
            faiss_file_set.add(fname)
        elif (file_stem and file_stem in faiss_by_id and not is_empty(faiss_by_id[file_stem])):
            recoverable_file_set.add(fname)
            faiss_file_set.add(fname)

    # v6_cleaned recoverable files (additive)
    cleaned_file_set = set()
    for r in no_mat:
        fname = r.get("file", "")
        if fname in recoverable_file_set:
            continue
        if fname in cleaned_by_file and not is_empty(cleaned_by_file[fname]["material_designation"]):
            recoverable_file_set.add(fname)
            cleaned_file_set.add(fname)

    # Now count RECORDS (not unique files) per source
    from_historic_records = sum(1 for r in no_mat if r.get("file", "") in historic_file_set)
    from_faiss_records = sum(1 for r in no_mat if r.get("file", "") in faiss_file_set)
    from_cleaned_records = sum(1 for r in no_mat if r.get("file", "") in cleaned_file_set)
    total_recovered_records = sum(1 for r in no_mat if r.get("file", "") in recoverable_file_set)

    total_no_mat = len(no_mat)
    unrecoverable = total_no_mat - total_recovered_records

    # Also show unique file counts
    no_mat_unique_files = len(set(r.get("file", "") for r in no_mat))
    print(f"NOTE: {total_no_mat:,} records correspond to {no_mat_unique_files:,} unique filenames")
    print(f"      (some PDFs may have multiple extraction records)")
    print()

    print(f"Total records missing material_designation: {total_no_mat:,}")
    print(f"  (Unique files: {no_mat_unique_files:,})")
    print()
    print(f"  Recoverable from historic_mua:   {from_historic_records:,} records ({len(historic_file_set):,} unique files)")
    print(f"  Additional from FAISS metadata:   {from_faiss_records:,} records ({len(faiss_file_set):,} unique files)")
    print(f"  Additional from v6_cleaned:       {from_cleaned_records:,} records ({len(cleaned_file_set):,} unique files)")
    print(f"  ----------------------------------------")
    print(f"  TOTAL RECOVERABLE (union):        {total_recovered_records:,} records ({100*total_recovered_records/total_no_mat:.1f}%) [{len(recoverable_file_set):,} unique files]")
    print(f"  TRULY UNRECOVERABLE:              {unrecoverable:,} records ({100*unrecoverable/total_no_mat:.1f}%)")
    print()

    # Characterize the truly unrecoverable ones
    unrecoverable_records = [r for r in no_mat if r.get("file", "") not in recoverable_file_set]

    if unrecoverable_records:
        print(f"Characterizing {len(unrecoverable_records):,} truly unrecoverable records:")

        # How many are completely empty?
        truly_empty = sum(1 for r in unrecoverable_records
                         if all(is_empty(r.get(f)) for f in content_fields))
        has_context = len(unrecoverable_records) - truly_empty

        print(f"  Completely empty (no rationale/application/issue): {truly_empty:,} ({100*truly_empty/len(unrecoverable_records):.1f}%)")
        print(f"  Has context but no material name:                  {has_context:,} ({100*has_context/len(unrecoverable_records):.1f}%)")
        print()

        # Confidence distribution of unrecoverable
        unrec_conf = [r.get("confidence", 0) or 0 for r in unrecoverable_records]
        avg_unrec = sum(unrec_conf) / len(unrec_conf) if unrec_conf else 0
        low_conf = sum(1 for c in unrec_conf if c <= 0.3)
        print(f"  Average confidence: {avg_unrec:.3f}")
        print(f"  Low confidence (<=0.3): {low_conf:,} ({100*low_conf/len(unrecoverable_records):.1f}%)")
        print()

        # The "has context" ones are the most interesting - these are real MUAs without extractable material
        context_records = [r for r in unrecoverable_records
                          if not all(is_empty(r.get(f)) for f in content_fields)]
        if context_records:
            print(f"  Sample of {min(10, len(context_records))} 'has context but no material' records:")
            for r in context_records[:10]:
                fname = r.get("file", "?")
                conf = r.get("confidence", 0)
                issue = (r.get("issue", "") or "")[:50]
                app_snip = (r.get("application", "") or "")[:60]
                print(f"    {fname:<25} conf={conf:.2f} issue=\"{issue}\" app=\"{app_snip}...\"")
        print()

    # ═══════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ═══════════════════════════════════════════════════════════════
    print_separator()
    print("FINAL SUMMARY")
    print_separator()
    print()
    print(f"Total v6_parsed records:                  {len(v6_parsed):,}")
    print(f"Records WITH material:                    {len(with_mat):,} ({100*len(with_mat)/len(v6_parsed):.1f}%)")
    print(f"Records WITHOUT material:                 {len(no_mat):,} ({100*len(no_mat)/len(v6_parsed):.1f}%)")
    print()
    print(f"Of the {len(no_mat):,} missing-material records:")
    print(f"  - Completely empty extractions:          {all_core_empty:,} (failed extractions marked success=True)")
    print(f"  - Have context but no material:          {has_some_content:,}")
    print()
    print(f"Recovery potential:")
    print(f"  - Recoverable from ANY source:           {total_recovered_records:,} ({100*total_recovered_records/len(no_mat):.1f}%)")
    print(f"  - Truly not recoverable:                 {unrecoverable:,} ({100*unrecoverable/len(no_mat):.1f}%)")
    print()

    # What percentage of the FULL dataset can we achieve material coverage for?
    full_coverage = len(with_mat) + total_recovered_records
    print(f"Potential full-dataset coverage:")
    print(f"  Current:    {len(with_mat):,} / {len(v6_parsed):,} = {100*len(with_mat)/len(v6_parsed):.1f}%")
    print(f"  With recovery: {full_coverage:,} / {len(v6_parsed):,} = {100*full_coverage/len(v6_parsed):.1f}%")
    print()


if __name__ == "__main__":
    main()
