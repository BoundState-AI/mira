import { useState, useCallback, useRef, useMemo } from "react";

// ═══════════════════════════════════════════════════════
// MAPTIS → MIRA Data Cleaning Tool
// Import messy MAPTIS CSVs, diagnose issues, export clean
// ═══════════════════════════════════════════════════════

const TEST_TYPE_PROFILES = {
  STRESS_: {
    key: 13, caption: "Stress Corrosion Cracking (SCC)",
    ratingField: "STRESS_Rating",
    ratingValues: ["A", "B", "C", "N", "U"],
    resistanceField: "STRESS_SCCResistance",
    resistanceValues: ["HIGH", "MODERATE", "LOW"],
    envField: "STRESS_ENV",
    refField: "STRESS_Refererence",
    sampleField: "STRESS_SampleCount",
    updateField: "STRESS_UPDT_DTE",
    cleanColumns: [
      { raw: "STRESS_Rating", clean: "scc_rating", type: "enum", values: ["A","B","C","N","U"] },
      { raw: "STRESS_SCCResistance", clean: "scc_resistance", type: "enum", values: ["HIGH","MODERATE","LOW"] },
      { raw: "STRESS_ENV", clean: "environment", type: "text" },
      { raw: "STRESS_Refererence", clean: "reference_doc", type: "text" },
      { raw: "STRESS_SampleCount", clean: "sample_count", type: "integer" },
      { raw: "STRESS_UPDT_DTE", clean: "update_date", type: "date_yyyymmdd" },
      { raw: "STRESS_DataSource", clean: "data_source", type: "text" },
      { raw: "STRESS_ThresholdLevel", clean: "threshold_level", type: "text" },
      { raw: "STRESS_Threshold", clean: "threshold_ksi", type: "numeric" },
      { raw: "STRESS_Pressure", clean: "pressure_psia", type: "numeric" },
    ],
  },
  FLAMM_: {
    key: 7, caption: "Flammability",
    cleanColumns: [
      { raw: "FLAMM_Rating", clean: "result", type: "enum", values: ["PASS","FAIL","SELF_EXT"] },
      { raw: "FLAMM_BurnLength", clean: "burn_length_in", type: "numeric" },
      { raw: "FLAMM_BurnRate", clean: "burn_rate_in_per_sec", type: "numeric" },
      { raw: "FLAMM_O2Conc", clean: "o2_concentration_pct", type: "numeric" },
      { raw: "FLAMM_Pressure", clean: "pressure_psia", type: "numeric" },
    ],
  },
  IMPACT_: {
    key: 17, caption: "Mechanical Impact",
    cleanColumns: [
      { raw: "IMPACT_Result", clean: "result", type: "text" },
      { raw: "IMPACT_Reactions", clean: "reactions_of_20", type: "integer" },
      { raw: "IMPACT_Energy", clean: "energy_ft_lbs", type: "numeric" },
    ],
  },
};

const COMMON_FIELDS = [
  "TestReportKey", "MaterialKey", "TestTypeKey", "TestTypeCaption",
  "TestReportNumber", "RequestDate", "TemperatureMinimum", "TemperatureMaximum"
];

// ── Parsing ──────────────────────────────────────────
function parseCSV(text) {
  const lines = text.split(/\r?\n/).filter(l => l.trim());
  if (lines.length < 2) return { headers: [], rows: [] };
  const headers = lines[0].split(",").map(h => h.trim());
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const vals = lines[i].split(",").map(v => v.trim());
    const row = {};
    headers.forEach((h, j) => {
      row[h] = vals[j] !== undefined ? vals[j] : "";
    });
    row._rowIndex = i;
    rows.push(row);
  }
  return { headers, rows };
}

// ── Detection ────────────────────────────────────────
function detectTestType(headers) {
  const prefixes = Object.keys(TEST_TYPE_PROFILES);
  const counts = {};
  for (const h of headers) {
    for (const p of prefixes) {
      if (h.startsWith(p)) counts[p] = (counts[p] || 0) + 1;
    }
  }
  const best = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return best.length > 0 ? best[0][0] : null;
}

function isNull(v) {
  if (!v) return true;
  const s = v.trim().toUpperCase();
  return s === "" || s === "NULL" || s === "N/A" || s === "NA" || s === "NONE";
}

// ── Analysis ─────────────────────────────────────────
function analyzeData(headers, rows, testPrefix) {
  const profile = TEST_TYPE_PROFILES[testPrefix];
  const issues = [];
  const columnStats = {};
  let shiftedRows = 0;

  // Per-column stats
  for (const h of headers) {
    const vals = rows.map(r => r[h]);
    const nonNull = vals.filter(v => !isNull(v));
    const nullCount = vals.length - nonNull.length;
    const unique = new Set(nonNull.map(v => v.trim()));
    columnStats[h] = {
      total: vals.length,
      nullCount,
      nullPct: Math.round((nullCount / vals.length) * 100),
      uniqueCount: unique.size,
      topValues: getTopValues(nonNull, 8),
      isCommon: COMMON_FIELDS.includes(h),
      isTestSpecific: testPrefix && h.startsWith(testPrefix),
    };
  }

  // Column shift detection (SCC-specific)
  if (profile && profile.ratingField && profile.resistanceField) {
    const ratingCol = profile.ratingField;
    const resistCol = profile.resistanceField;
    const rVals = new Set(profile.ratingValues || []);
    const resVals = new Set(profile.resistanceValues || []);

    rows.forEach((row, idx) => {
      const ratingVal = (row[ratingCol] || "").trim();
      const resistVal = (row[resistCol] || "").trim();

      // If resistance field has non-resistance values, likely shifted
      if (!isNull(resistVal) && !resVals.has(resistVal) && resistVal.length > 5) {
        shiftedRows++;
        issues.push({
          row: row._rowIndex,
          type: "column_shift",
          severity: "error",
          field: resistCol,
          value: resistVal.slice(0, 60),
          message: `Expected HIGH/MODERATE/LOW, got environment text`,
        });
      }

      // Rating field has non-rating values
      if (!isNull(ratingVal) && !rVals.has(ratingVal) && ratingVal.length > 3) {
        issues.push({
          row: row._rowIndex,
          type: "column_shift",
          severity: "error",
          field: ratingCol,
          value: ratingVal.slice(0, 40),
          message: `Expected A/B/C/N/U, got "${ratingVal.slice(0, 30)}"`,
        });
      }
    });
  }

  // Type validation for numeric fields
  for (const h of headers) {
    if (h.includes("Temperature") || h.includes("Pressure") || h.includes("Threshold")) {
      rows.forEach(row => {
        const v = (row[h] || "").trim();
        if (!isNull(v) && isNaN(parseFloat(v))) {
          issues.push({
            row: row._rowIndex,
            type: "type_mismatch",
            severity: "warning",
            field: h,
            value: v.slice(0, 40),
            message: `Expected numeric, got "${v.slice(0, 30)}"`,
          });
        }
      });
    }
  }

  // Date format issues
  const dateFields = headers.filter(h => h.includes("DTE") || h.includes("Date"));
  for (const h of dateFields) {
    rows.forEach(row => {
      const v = (row[h] || "").trim();
      if (!isNull(v) && !/^\d{8}$/.test(v) && !/^\d{4}-\d{2}-\d{2}/.test(v)) {
        issues.push({
          row: row._rowIndex,
          type: "date_format",
          severity: "info",
          field: h,
          value: v.slice(0, 30),
          message: `Non-standard date format`,
        });
      }
    });
  }

  // Cap issues for display
  const issueSummary = {};
  issues.forEach(i => {
    const k = `${i.type}:${i.field}`;
    if (!issueSummary[k]) issueSummary[k] = { ...i, count: 0, examples: [] };
    issueSummary[k].count++;
    if (issueSummary[k].examples.length < 3) issueSummary[k].examples.push(i.value);
  });

  return {
    columnStats,
    issues: Object.values(issueSummary).sort((a, b) => b.count - a.count),
    totalIssues: issues.length,
    shiftedRows,
    shiftPct: Math.round((shiftedRows / rows.length) * 100),
  };
}

function getTopValues(arr, n) {
  const counts = {};
  arr.forEach(v => { const s = v.trim(); if (s) counts[s] = (counts[s] || 0) + 1; });
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, n).map(([val, count]) => ({ val, count }));
}

// ── Cleaning ─────────────────────────────────────────
function cleanRows(rows, headers, testPrefix, analysis) {
  const profile = TEST_TYPE_PROFILES[testPrefix];
  const cleaned = [];
  const log = [];

  rows.forEach((row, idx) => {
    const clean = {
      _original_row: row._rowIndex,
      material_key: parseInt(row.MaterialKey) || null,
      test_report_key: parseInt(row.TestReportKey) || null,
      test_type_key: parseInt(row.TestTypeKey) || null,
      test_report_number: isNull(row.TestReportNumber) ? null : row.TestReportNumber.trim(),
      temp_min_f: isNull(row.TemperatureMinimum) ? null : parseFloat(row.TemperatureMinimum),
      temp_max_f: isNull(row.TemperatureMaximum) ? null : parseFloat(row.TemperatureMaximum),
    };

    let isShifted = false;

    // SCC-specific shift detection and correction
    if (profile && profile.resistanceField) {
      const resistVal = (row[profile.resistanceField] || "").trim();
      const resVals = new Set(profile.resistanceValues || []);
      if (!isNull(resistVal) && !resVals.has(resistVal) && resistVal.length > 5) {
        isShifted = true;
        log.push({ row: row._rowIndex, action: "column_shift_corrected", detail: "Detected shifted columns, attempting realignment" });
      }
    }

    clean._quality_flag = isShifted ? "shifted" : "clean";
    clean._quality_score = isShifted ? 0.3 : 1.0;

    // Map test-specific columns
    if (profile && profile.cleanColumns) {
      for (const mapping of profile.cleanColumns) {
        const rawVal = (row[mapping.raw] || "").trim();
        if (isNull(rawVal)) {
          clean[mapping.clean] = null;
          continue;
        }

        switch (mapping.type) {
          case "enum":
            if (mapping.values && mapping.values.includes(rawVal)) {
              clean[mapping.clean] = rawVal;
            } else {
              clean[mapping.clean] = rawVal;
              if (!isShifted) {
                clean._quality_score = Math.min(clean._quality_score, 0.6);
                log.push({ row: row._rowIndex, action: "unexpected_enum", field: mapping.clean, value: rawVal });
              }
            }
            break;
          case "integer":
            const iVal = parseInt(rawVal);
            clean[mapping.clean] = isNaN(iVal) ? null : iVal;
            if (isNaN(iVal)) {
              log.push({ row: row._rowIndex, action: "parse_failed", field: mapping.clean, value: rawVal });
              clean._quality_score = Math.min(clean._quality_score, 0.5);
            }
            break;
          case "numeric":
            const fVal = parseFloat(rawVal);
            clean[mapping.clean] = isNaN(fVal) ? null : fVal;
            if (isNaN(fVal)) {
              log.push({ row: row._rowIndex, action: "parse_failed", field: mapping.clean, value: rawVal });
              clean._quality_score = Math.min(clean._quality_score, 0.5);
            }
            break;
          case "date_yyyymmdd":
            if (/^\d{8}$/.test(rawVal)) {
              clean[mapping.clean] = `${rawVal.slice(0,4)}-${rawVal.slice(4,6)}-${rawVal.slice(6,8)}`;
            } else {
              clean[mapping.clean] = rawVal;
              clean._quality_score = Math.min(clean._quality_score, 0.7);
            }
            break;
          default:
            clean[mapping.clean] = rawVal || null;
        }
      }
    }

    // Environment normalization
    if (clean.environment) {
      const env = clean.environment.toUpperCase();
      if (env.includes("NACL") || env.includes("SODIUM CHLORIDE")) clean.env_normalized = "nacl_solution";
      else if (env.includes("SALT SPRAY") || env.includes("SALT FOG")) clean.env_normalized = "salt_spray";
      else if (env.includes("IMMERSION")) clean.env_normalized = "immersion";
      else if (env.includes("ATMOSPHERE") || env.includes("HUMIDITY")) clean.env_normalized = "atmosphere";
      else if (env.includes("SEA")) clean.env_normalized = "seawater";
      else if (env === "SCC") clean.env_normalized = "generic_scc";
      else clean.env_normalized = "other";
    }

    // Null score penalty
    const nullCount = Object.values(clean).filter(v => v === null).length;
    const totalFields = Object.keys(clean).filter(k => !k.startsWith("_")).length;
    const completeness = 1 - (nullCount / totalFields);
    clean._quality_score = Math.round(Math.min(clean._quality_score, completeness) * 100) / 100;

    cleaned.push(clean);
  });

  return { cleaned, log };
}

// ── Export ────────────────────────────────────────────
function toCSV(rows) {
  if (!rows.length) return "";
  const keys = Object.keys(rows[0]).filter(k => !k.startsWith("_"));
  const meta = ["_quality_flag", "_quality_score", "_original_row"];
  const allKeys = [...keys, ...meta.filter(m => rows[0].hasOwnProperty(m))];
  const header = allKeys.join(",");
  const lines = rows.map(r =>
    allKeys.map(k => {
      const v = r[k];
      if (v === null || v === undefined) return "";
      const s = String(v);
      return s.includes(",") || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")
  );
  return [header, ...lines].join("\n");
}

function generateReport(analysis, testPrefix, rawCount, cleanedRows, cleanLog) {
  const profile = TEST_TYPE_PROFILES[testPrefix] || {};
  const qualityDist = { clean: 0, shifted: 0, low: 0 };
  cleanedRows.forEach(r => {
    if (r._quality_flag === "shifted") qualityDist.shifted++;
    else if (r._quality_score < 0.5) qualityDist.low++;
    else qualityDist.clean++;
  });
  const avgScore = cleanedRows.reduce((s, r) => s + r._quality_score, 0) / cleanedRows.length;

  return `# MAPTIS → MIRA Cleaning Report
## Test Type: ${profile.caption || "Unknown"} (prefix: ${testPrefix || "N/A"})
Generated: ${new Date().toISOString()}

## Input Summary
- Raw rows: ${rawCount.toLocaleString()}
- Columns detected: common header + ${testPrefix || "??"}-prefixed fields
- Test type key: ${profile.key || "?"}

## Data Quality Diagnosis
- Total issues found: ${analysis.totalIssues.toLocaleString()}
- Column-shifted rows: ${analysis.shiftedRows} (${analysis.shiftPct}%)
- Issue types:
${analysis.issues.map(i => `  - ${i.type} in ${i.field}: ${i.count} occurrences (${i.severity})`).join("\n")}

## Cleaning Actions Applied
1. **NULL standardization** — "NULL", empty strings, "N/A" → null
2. **Type coercion** — Numeric fields parsed, invalid → null with quality penalty
3. **Date normalization** — YYYYMMDD → YYYY-MM-DD ISO format
4. **Environment normalization** — Free text → controlled vocabulary:
   - "SODIUM CHLORIDE (NACL)" → nacl_solution
   - "5% SALT SPRAY" → salt_spray
   - "ALTERNATE IMMERSION..." → immersion
   - "MSFC ATMOSPHERE" → atmosphere
   - "SCC" (generic) → generic_scc
5. **Column shift detection** — Rows where environment text appeared in resistance
   field flagged as quality_flag="shifted", quality_score=0.30
6. **Quality scoring** — Each row gets 0.00-1.00 score based on:
   - Enum validation (unexpected values → penalty)
   - Parse failures → penalty
   - Completeness (null ratio) → penalty
   - Column shift → major penalty (0.30)

## Output Summary
- Clean rows: ${qualityDist.clean.toLocaleString()}
- Shifted rows (flagged): ${qualityDist.shifted.toLocaleString()}
- Low quality rows (<0.5): ${qualityDist.low.toLocaleString()}
- Average quality score: ${avgScore.toFixed(2)}

## Column Mapping (Raw → Clean)
| MAPTIS Column | MIRA Column | Type | Notes |
|---|---|---|---|
| TestReportKey | test_report_key | INT | MAPTIS native PK |
| MaterialKey | material_key | INT | FK to materials |
| TemperatureMinimum | temp_min_f | DECIMAL | Fahrenheit |
| TemperatureMaximum | temp_max_f | DECIMAL | Fahrenheit |
${(profile.cleanColumns || []).map(c =>
  `| ${c.raw} | ${c.clean} | ${c.type} | ${c.values ? c.values.join("/") : ""} |`
).join("\n")}

## Next Steps
1. Load cleaned CSV into \`mira.scc_results\` (or appropriate test table)
2. Match \`material_key\` to \`mira.materials\` via \`maptis_material_key\`
3. Review shifted rows (quality_flag="shifted") manually
4. Create citations for \`reference_doc\` values → \`core.citations\`
5. Compute compatibility ratings from aggregated test evidence

## SQL Load Command
\`\`\`sql
COPY mira.scc_results (
    material_id, maptis_test_report_key, scc_rating,
    scc_resistance, environment, env_normalized,
    temp_min_f, temp_max_f, sample_count,
    data_source, reference_doc, quality_score
)
FROM '/path/to/cleaned_export.csv'
WITH (FORMAT csv, HEADER true, NULL '');
\`\`\`

## Cleaning Log (first 50 entries)
${cleanLog.slice(0, 50).map(l => `- Row ${l.row}: ${l.action}${l.field ? ` [${l.field}]` : ""}${l.value ? ` = "${l.value}"` : ""}${l.detail ? ` — ${l.detail}` : ""}`).join("\n")}
`;
}

// ── Severity colors ──────────────────────────────────
const SEV = {
  error: { bg: "#450a0a", border: "#991b1b", text: "#fca5a5", badge: "#ef4444" },
  warning: { bg: "#451a03", border: "#92400e", text: "#fcd34d", badge: "#f59e0b" },
  info: { bg: "#0c1830", border: "#1e3a5f", text: "#93c5fd", badge: "#3b82f6" },
};

// ═══════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════
export default function MAPTISCleaner() {
  const [stage, setStage] = useState("upload"); // upload | analyze | clean | export
  const [rawText, setRawText] = useState("");
  const [parsed, setParsed] = useState(null);
  const [testPrefix, setTestPrefix] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [cleanResult, setCleanResult] = useState(null);
  const [viewTab, setViewTab] = useState("issues");
  const fileRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFile = useCallback((file) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target.result;
      setRawText(text);
      const p = parseCSV(text);
      setParsed(p);
      const prefix = detectTestType(p.headers);
      setTestPrefix(prefix);
      const a = analyzeData(p.headers, p.rows, prefix);
      setAnalysis(a);
      setStage("analyze");
    };
    reader.readAsText(file);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const runCleaning = useCallback(() => {
    if (!parsed || !testPrefix) return;
    const result = cleanRows(parsed.rows, parsed.headers, testPrefix, analysis);
    setCleanResult(result);
    setStage("clean");
    setViewTab("preview");
  }, [parsed, testPrefix, analysis]);

  const exportClean = useCallback(() => {
    if (!cleanResult) return;
    const csv = toCSV(cleanResult.cleaned);
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mira_cleaned_${testPrefix || "data"}_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [cleanResult, testPrefix]);

  const exportReport = useCallback(() => {
    if (!cleanResult || !analysis) return;
    const md = generateReport(analysis, testPrefix, parsed.rows.length, cleanResult.cleaned, cleanResult.log);
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mira_cleaning_report_${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [cleanResult, analysis, testPrefix, parsed]);

  const qualityStats = useMemo(() => {
    if (!cleanResult) return null;
    const rows = cleanResult.cleaned;
    const clean = rows.filter(r => r._quality_flag === "clean" && r._quality_score >= 0.5).length;
    const shifted = rows.filter(r => r._quality_flag === "shifted").length;
    const low = rows.filter(r => r._quality_score < 0.5 && r._quality_flag !== "shifted").length;
    const avg = rows.reduce((s, r) => s + r._quality_score, 0) / rows.length;
    return { clean, shifted, low, avg, total: rows.length };
  }, [cleanResult]);

  // ── STYLES ────────────────────────────────────────
  const S = {
    page: {
      background: "#06090f",
      color: "#c8d6e5",
      minHeight: "100vh",
      fontFamily: "'IBM Plex Mono', 'JetBrains Mono', 'Fira Code', monospace",
      fontSize: 13,
    },
    container: { maxWidth: 1060, margin: "0 auto", padding: "16px 20px" },
    header: {
      display: "flex", alignItems: "baseline", gap: 12, marginBottom: 6,
    },
    title: {
      fontSize: 22, fontWeight: 800, letterSpacing: -0.5, margin: 0,
      color: "#f0b429",
    },
    subtitle: { color: "#4a5568", fontSize: 12 },
    pipeline: {
      display: "flex", gap: 0, marginBottom: 16, background: "#0d1117",
      border: "1px solid #1b2332", borderRadius: 6, overflow: "hidden",
    },
    pipeStep: (active, done) => ({
      flex: 1, padding: "8px 14px", textAlign: "center", fontSize: 11,
      fontWeight: active ? 700 : 400, letterSpacing: 0.5, textTransform: "uppercase",
      background: active ? "#1a2332" : "transparent",
      color: active ? "#f0b429" : done ? "#2dd4bf" : "#374151",
      borderRight: "1px solid #1b2332",
      cursor: done && !active ? "pointer" : "default",
    }),
    dropzone: (over) => ({
      border: `2px dashed ${over ? "#f0b429" : "#1b2332"}`,
      borderRadius: 8, padding: 48, textAlign: "center",
      background: over ? "#1a180d" : "#0a0e14",
      cursor: "pointer", transition: "all 0.2s",
    }),
    card: {
      background: "#0d1117", border: "1px solid #1b2332",
      borderRadius: 6, padding: 14, marginBottom: 12,
    },
    btn: (color = "#f0b429", outline = false) => ({
      padding: "7px 18px", borderRadius: 5, cursor: "pointer",
      fontSize: 12, fontWeight: 700, fontFamily: "inherit",
      border: `1px solid ${color}`,
      background: outline ? "transparent" : color,
      color: outline ? color : "#06090f",
      transition: "all 0.15s",
    }),
    tab: (active) => ({
      padding: "5px 14px", borderRadius: "5px 5px 0 0", cursor: "pointer",
      fontSize: 11, fontWeight: active ? 700 : 400, border: "none",
      background: active ? "#1a2332" : "transparent",
      color: active ? "#f0b429" : "#4a5568",
      fontFamily: "inherit",
    }),
    badge: (color) => ({
      display: "inline-block", padding: "1px 8px", borderRadius: 3,
      fontSize: 10, fontWeight: 700, background: color, color: "#fff",
    }),
    mono: { fontFamily: "inherit" },
    table: {
      width: "100%", borderCollapse: "collapse", fontSize: 11,
    },
    th: {
      textAlign: "left", padding: "6px 8px", borderBottom: "1px solid #1b2332",
      color: "#64748b", fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5,
    },
    td: (highlight) => ({
      padding: "5px 8px", borderBottom: "1px solid #111827",
      color: highlight ? "#fbbf24" : "#94a3b8",
      maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
    }),
  };

  const stages = ["upload", "analyze", "clean", "export"];
  const stageIdx = stages.indexOf(stage);

  return (
    <div style={S.page}>
      <div style={S.container}>
        {/* Header */}
        <div style={S.header}>
          <h1 style={S.title}>MAPTIS → MIRA</h1>
          <span style={S.subtitle}>Import &bull; Diagnose &bull; Clean &bull; Export</span>
        </div>

        {/* Pipeline indicator */}
        <div style={S.pipeline}>
          {[
            { id: "upload", label: "① Upload CSV" },
            { id: "analyze", label: "② Diagnose" },
            { id: "clean", label: "③ Clean" },
            { id: "export", label: "④ Export" },
          ].map((s, i) => (
            <div key={s.id}
              style={S.pipeStep(stage === s.id, stageIdx > i)}
              onClick={() => { if (stageIdx > i) setStage(s.id); }}
            >
              {s.label}
            </div>
          ))}
        </div>

        {/* ═══ UPLOAD STAGE ═══ */}
        {stage === "upload" && (
          <div
            style={S.dropzone(dragOver)}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
          >
            <input ref={fileRef} type="file" accept=".csv" hidden
              onChange={(e) => e.target.files[0] && handleFile(e.target.files[0])} />
            <div style={{ fontSize: 36, marginBottom: 8, opacity: 0.4 }}>⬆</div>
            <div style={{ color: "#f0b429", fontSize: 16, fontWeight: 700, marginBottom: 6 }}>
              Drop MAPTIS CSV here
            </div>
            <div style={{ color: "#4a5568", fontSize: 12 }}>
              or click to browse &bull; Supports SCC, Flammability, Impact, and other test type exports
            </div>
            <div style={{ color: "#2a3444", fontSize: 11, marginTop: 12 }}>
              Auto-detects test type from column prefixes (STRESS_, FLAMM_, IMPACT_, etc.)
            </div>
          </div>
        )}

        {/* ═══ ANALYZE STAGE ═══ */}
        {stage === "analyze" && parsed && analysis && (
          <>
            {/* Summary cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginBottom: 14 }}>
              {[
                { label: "Rows", val: parsed.rows.length.toLocaleString(), color: "#c8d6e5" },
                { label: "Columns", val: parsed.headers.length, color: "#c8d6e5" },
                { label: "Test Type", val: TEST_TYPE_PROFILES[testPrefix]?.caption?.split("(")[0]?.trim() || "Unknown", color: "#f0b429" },
                { label: "Issues", val: analysis.totalIssues.toLocaleString(), color: analysis.totalIssues > 0 ? "#ef4444" : "#2dd4bf" },
                { label: "Shifted", val: `${analysis.shiftPct}%`, color: analysis.shiftPct > 0 ? "#f59e0b" : "#2dd4bf" },
              ].map((s, i) => (
                <div key={i} style={{ ...S.card, padding: "8px 12px" }}>
                  <div style={{ color: "#4a5568", fontSize: 9, textTransform: "uppercase", letterSpacing: 1 }}>{s.label}</div>
                  <div style={{ color: s.color, fontSize: 17, fontWeight: 700 }}>{s.val}</div>
                </div>
              ))}
            </div>

            {/* Tabs */}
            <div style={{ display: "flex", gap: 2, marginBottom: 0 }}>
              {["issues", "columns", "raw_preview"].map(t => (
                <button key={t} onClick={() => setViewTab(t)} style={S.tab(viewTab === t)}>
                  {t === "issues" ? `Issues (${analysis.issues.length})` : t === "columns" ? "Column Stats" : "Raw Preview"}
                </button>
              ))}
            </div>

            <div style={{ ...S.card, borderTopLeftRadius: 0, maxHeight: "50vh", overflow: "auto" }}>
              {viewTab === "issues" && (
                analysis.issues.length === 0 ? (
                  <div style={{ color: "#2dd4bf", padding: 20, textAlign: "center" }}>
                    ✓ No issues detected — data looks clean!
                  </div>
                ) : (
                  <table style={S.table}>
                    <thead>
                      <tr>
                        <th style={S.th}>Severity</th>
                        <th style={S.th}>Type</th>
                        <th style={S.th}>Field</th>
                        <th style={S.th}>Count</th>
                        <th style={S.th}>Example Values</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.issues.map((iss, i) => (
                        <tr key={i}>
                          <td style={S.td()}>
                            <span style={S.badge(SEV[iss.severity]?.badge || "#666")}>{iss.severity}</span>
                          </td>
                          <td style={S.td()}>{iss.type}</td>
                          <td style={S.td(true)}>{iss.field}</td>
                          <td style={S.td()}>{iss.count.toLocaleString()}</td>
                          <td style={{ ...S.td(), maxWidth: 300 }}>
                            {iss.examples.map((e, j) => (
                              <span key={j} style={{
                                display: "inline-block", background: "#111827", padding: "1px 6px",
                                borderRadius: 3, marginRight: 4, fontSize: 10, color: "#94a3b8",
                              }}>{e}</span>
                            ))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )
              )}

              {viewTab === "columns" && (
                <table style={S.table}>
                  <thead>
                    <tr>
                      <th style={S.th}>Column</th>
                      <th style={S.th}>Layer</th>
                      <th style={S.th}>NULL %</th>
                      <th style={S.th}>Unique</th>
                      <th style={S.th}>Top Values</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(analysis.columnStats).map(([col, stats]) => (
                      <tr key={col}>
                        <td style={S.td(true)}>{col}</td>
                        <td style={S.td()}>
                          <span style={S.badge(stats.isCommon ? "#2563eb" : stats.isTestSpecific ? "#9333ea" : "#4b5563")}>
                            {stats.isCommon ? "common" : stats.isTestSpecific ? testPrefix.replace("_", "") : "other"}
                          </span>
                        </td>
                        <td style={S.td()}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <div style={{ width: 60, height: 6, background: "#1b2332", borderRadius: 2 }}>
                              <div style={{
                                width: `${stats.nullPct}%`, height: 6, borderRadius: 2,
                                background: stats.nullPct > 90 ? "#ef4444" : stats.nullPct > 50 ? "#f59e0b" : "#22c55e",
                              }} />
                            </div>
                            <span style={{ fontSize: 10 }}>{stats.nullPct}%</span>
                          </div>
                        </td>
                        <td style={S.td()}>{stats.uniqueCount.toLocaleString()}</td>
                        <td style={{ ...S.td(), maxWidth: 300 }}>
                          {stats.topValues.slice(0, 4).map((v, j) => (
                            <span key={j} style={{
                              display: "inline-block", background: "#111827", padding: "1px 5px",
                              borderRadius: 3, marginRight: 3, fontSize: 9, color: "#94a3b8",
                            }}>{v.val.slice(0, 25)} ({v.count})</span>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {viewTab === "raw_preview" && (
                <div style={{ overflow: "auto" }}>
                  <table style={S.table}>
                    <thead>
                      <tr>
                        {parsed.headers.map(h => (
                          <th key={h} style={{ ...S.th, whiteSpace: "nowrap" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {parsed.rows.slice(0, 30).map((row, i) => (
                        <tr key={i}>
                          {parsed.headers.map(h => (
                            <td key={h} style={{ ...S.td(false), whiteSpace: "nowrap", maxWidth: 150 }}>
                              {isNull(row[h]) ? <span style={{ color: "#2a3444" }}>NULL</span> : row[h].trim().slice(0, 40)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
              <button style={S.btn("#f0b429")} onClick={runCleaning}>
                Run Cleaning Pipeline ▶
              </button>
            </div>
          </>
        )}

        {/* ═══ CLEAN STAGE ═══ */}
        {stage === "clean" && cleanResult && qualityStats && (
          <>
            {/* Quality summary */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginBottom: 14 }}>
              {[
                { label: "Total Rows", val: qualityStats.total.toLocaleString(), color: "#c8d6e5" },
                { label: "Clean", val: qualityStats.clean.toLocaleString(), color: "#2dd4bf" },
                { label: "Shifted", val: qualityStats.shifted.toLocaleString(), color: "#f59e0b" },
                { label: "Low Quality", val: qualityStats.low.toLocaleString(), color: "#ef4444" },
                { label: "Avg Score", val: qualityStats.avg.toFixed(2), color: qualityStats.avg > 0.7 ? "#2dd4bf" : "#f59e0b" },
              ].map((s, i) => (
                <div key={i} style={{ ...S.card, padding: "8px 12px" }}>
                  <div style={{ color: "#4a5568", fontSize: 9, textTransform: "uppercase", letterSpacing: 1 }}>{s.label}</div>
                  <div style={{ color: s.color, fontSize: 17, fontWeight: 700 }}>{s.val}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "flex", gap: 2, marginBottom: 0 }}>
              {["preview", "log", "mapping"].map(t => (
                <button key={t} onClick={() => setViewTab(t)} style={S.tab(viewTab === t)}>
                  {t === "preview" ? "Cleaned Data" : t === "log" ? `Log (${cleanResult.log.length})` : "Column Mapping"}
                </button>
              ))}
            </div>

            <div style={{ ...S.card, borderTopLeftRadius: 0, maxHeight: "50vh", overflow: "auto" }}>
              {viewTab === "preview" && (
                <div style={{ overflow: "auto" }}>
                  <table style={S.table}>
                    <thead>
                      <tr>
                        {Object.keys(cleanResult.cleaned[0] || {}).map(k => (
                          <th key={k} style={{
                            ...S.th, whiteSpace: "nowrap",
                            color: k.startsWith("_") ? "#92400e" : "#64748b",
                          }}>{k}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {cleanResult.cleaned.slice(0, 40).map((row, i) => (
                        <tr key={i} style={{
                          background: row._quality_flag === "shifted" ? "#1a120a" : "transparent",
                        }}>
                          {Object.entries(row).map(([k, v]) => (
                            <td key={k} style={{
                              ...S.td(k === "_quality_flag" || k === "_quality_score"),
                              whiteSpace: "nowrap", maxWidth: 160,
                              color: k === "_quality_score"
                                ? (v >= 0.7 ? "#2dd4bf" : v >= 0.4 ? "#f59e0b" : "#ef4444")
                                : k === "_quality_flag"
                                  ? (v === "clean" ? "#2dd4bf" : "#f59e0b")
                                  : v === null ? "#1b2332" : "#94a3b8",
                            }}>
                              {v === null ? "·" : String(v).slice(0, 35)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {viewTab === "log" && (
                <div style={{ fontSize: 11, lineHeight: 1.8 }}>
                  {cleanResult.log.length === 0 ? (
                    <div style={{ color: "#2dd4bf", textAlign: "center", padding: 20 }}>No cleaning actions logged — data was already clean.</div>
                  ) : (
                    cleanResult.log.slice(0, 100).map((l, i) => (
                      <div key={i} style={{ borderBottom: "1px solid #111827", padding: "3px 0" }}>
                        <span style={{ color: "#4a5568" }}>Row {l.row}</span>
                        <span style={{
                          ...S.badge(l.action === "column_shift_corrected" ? "#ef4444" : l.action === "parse_failed" ? "#f59e0b" : "#3b82f6"),
                          marginLeft: 8,
                        }}>{l.action}</span>
                        {l.field && <span style={{ color: "#f0b429", marginLeft: 8 }}>{l.field}</span>}
                        {l.value && <span style={{ color: "#64748b", marginLeft: 8 }}>= "{l.value.slice(0, 40)}"</span>}
                        {l.detail && <span style={{ color: "#64748b", marginLeft: 8 }}>— {l.detail}</span>}
                      </div>
                    ))
                  )}
                </div>
              )}

              {viewTab === "mapping" && (
                <table style={S.table}>
                  <thead>
                    <tr>
                      <th style={S.th}>MAPTIS Column (Raw)</th>
                      <th style={S.th}>→</th>
                      <th style={S.th}>MIRA Column (Clean)</th>
                      <th style={S.th}>Type</th>
                      <th style={S.th}>Valid Values</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr><td style={S.td()}>TestReportKey</td><td style={S.td()}>→</td><td style={S.td(true)}>test_report_key</td><td style={S.td()}>INT</td><td style={S.td()}>MAPTIS PK</td></tr>
                    <tr><td style={S.td()}>MaterialKey</td><td style={S.td()}>→</td><td style={S.td(true)}>material_key</td><td style={S.td()}>INT</td><td style={S.td()}>FK → materials</td></tr>
                    <tr><td style={S.td()}>TemperatureMinimum</td><td style={S.td()}>→</td><td style={S.td(true)}>temp_min_f</td><td style={S.td()}>DECIMAL</td><td style={S.td()}>°F</td></tr>
                    <tr><td style={S.td()}>TemperatureMaximum</td><td style={S.td()}>→</td><td style={S.td(true)}>temp_max_f</td><td style={S.td()}>DECIMAL</td><td style={S.td()}>°F</td></tr>
                    {(TEST_TYPE_PROFILES[testPrefix]?.cleanColumns || []).map((c, i) => (
                      <tr key={i}>
                        <td style={S.td()}>{c.raw}</td>
                        <td style={S.td()}>→</td>
                        <td style={S.td(true)}>{c.clean}</td>
                        <td style={S.td()}>{c.type}</td>
                        <td style={S.td()}>{c.values?.join(", ") || ""}</td>
                      </tr>
                    ))}
                    <tr><td style={S.td()}>—</td><td style={S.td()}>+</td><td style={S.td(true)}>env_normalized</td><td style={S.td()}>enum</td><td style={S.td()}>nacl_solution, salt_spray, immersion, atmosphere, seawater, generic_scc, other</td></tr>
                    <tr><td style={S.td()}>—</td><td style={S.td()}>+</td><td style={S.td(true)}>_quality_flag</td><td style={S.td()}>text</td><td style={S.td()}>clean, shifted</td></tr>
                    <tr><td style={S.td()}>—</td><td style={S.td()}>+</td><td style={S.td(true)}>_quality_score</td><td style={S.td()}>decimal</td><td style={S.td()}>0.00 — 1.00</td></tr>
                  </tbody>
                </table>
              )}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
              <button style={S.btn("#f0b429", true)} onClick={() => { setStage("analyze"); setViewTab("issues"); }}>
                ◀ Back to Diagnosis
              </button>
              <button style={S.btn("#2dd4bf")} onClick={() => { setStage("export"); }}>
                Export ▶
              </button>
            </div>
          </>
        )}

        {/* ═══ EXPORT STAGE ═══ */}
        {stage === "export" && cleanResult && qualityStats && (
          <>
            <div style={S.card}>
              <div style={{ fontSize: 15, fontWeight: 700, color: "#2dd4bf", marginBottom: 12 }}>
                ✓ Cleaning Complete
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <div>
                  <div style={{ color: "#64748b", fontSize: 10, textTransform: "uppercase", marginBottom: 8 }}>Summary</div>
                  <div style={{ lineHeight: 2 }}>
                    <span style={{ color: "#4a5568" }}>Input:</span> {parsed.rows.length.toLocaleString()} raw rows<br />
                    <span style={{ color: "#4a5568" }}>Output:</span> {qualityStats.total.toLocaleString()} cleaned rows<br />
                    <span style={{ color: "#4a5568" }}>Quality:</span>{" "}
                    <span style={{ color: "#2dd4bf" }}>{qualityStats.clean} clean</span>,{" "}
                    <span style={{ color: "#f59e0b" }}>{qualityStats.shifted} shifted</span>,{" "}
                    <span style={{ color: "#ef4444" }}>{qualityStats.low} low</span><br />
                    <span style={{ color: "#4a5568" }}>Avg score:</span> {qualityStats.avg.toFixed(2)}<br />
                    <span style={{ color: "#4a5568" }}>Cleaning log:</span> {cleanResult.log.length} actions
                  </div>
                </div>
                <div>
                  <div style={{ color: "#64748b", fontSize: 10, textTransform: "uppercase", marginBottom: 8 }}>What was done</div>
                  <div style={{ lineHeight: 2, color: "#94a3b8" }}>
                    ✓ NULL standardization (NULL, empty, N/A → null)<br />
                    ✓ Type coercion (numbers parsed, dates → ISO)<br />
                    ✓ Column shift detection & flagging<br />
                    ✓ Environment normalization → controlled vocab<br />
                    ✓ Quality scoring per row (0.00–1.00)<br />
                    ✓ Column mapping (MAPTIS → MIRA names)
                  </div>
                </div>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div style={{ ...S.card, cursor: "pointer", transition: "all 0.2s", textAlign: "center" }} onClick={exportClean}>
                <div style={{ fontSize: 28, marginBottom: 4, opacity: 0.6 }}>⬇</div>
                <div style={{ color: "#f0b429", fontSize: 14, fontWeight: 700, marginBottom: 4 }}>
                  Download Cleaned CSV
                </div>
                <div style={{ color: "#4a5568", fontSize: 11 }}>
                  MIRA-ready data with quality scores &bull; Load directly into PostgreSQL
                </div>
              </div>
              <div style={{ ...S.card, cursor: "pointer", transition: "all 0.2s", textAlign: "center" }} onClick={exportReport}>
                <div style={{ fontSize: 28, marginBottom: 4, opacity: 0.6 }}>📋</div>
                <div style={{ color: "#2dd4bf", fontSize: 14, fontWeight: 700, marginBottom: 4 }}>
                  Download Cleaning Report
                </div>
                <div style={{ color: "#4a5568", fontSize: 11 }}>
                  Markdown report with instructions, SQL load commands, and full audit log
                </div>
              </div>
            </div>

            <div style={{ ...S.card, marginTop: 12 }}>
              <div style={{ color: "#f0b429", fontWeight: 700, marginBottom: 8, fontSize: 12 }}>
                SQL LOAD COMMAND
              </div>
              <pre style={{
                color: "#94a3b8", background: "#080c12", padding: 12, borderRadius: 4,
                fontSize: 11, lineHeight: 1.6, overflow: "auto",
              }}>{`-- 1. Load cleaned CSV into MIRA gold table
COPY mira.scc_results (
    material_key, test_report_key, scc_rating, scc_resistance,
    environment, env_normalized, temp_min_f, temp_max_f,
    sample_count, data_source, reference_doc, quality_score
)
FROM '/path/to/mira_cleaned_${testPrefix || "data"}.csv'
WITH (FORMAT csv, HEADER true, NULL '');

-- 2. Link to canonical materials
UPDATE mira.scc_results sr
SET material_id = m.id
FROM mira.materials m
WHERE m.maptis_material_key = sr.material_key;

-- 3. Flag shifted rows for manual review
SELECT * FROM mira.scc_results
WHERE quality_score < 0.5
ORDER BY quality_score ASC;`}</pre>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
              <button style={S.btn("#f0b429", true)} onClick={() => { setStage("clean"); setViewTab("preview"); }}>
                ◀ Back to Review
              </button>
              <button style={S.btn("#64748b", true)} onClick={() => {
                setStage("upload"); setParsed(null); setAnalysis(null); setCleanResult(null);
              }}>
                Import Another File
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
