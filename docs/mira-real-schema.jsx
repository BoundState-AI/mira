import { useState, useCallback } from "react";

// ============================================================
// REAL MIRA SCHEMA — derived from actual MAPTIS SCC export
// ============================================================

const SCHEMA = {
  maptis_raw: {
    label: "MAPTIS Raw Ingest",
    desc: "Direct mirror of how MAPTIS actually exports data",
    color: "#92400e",
    accent: "#fbbf24",
    bg: "#1c1208",
    tables: [
      {
        name: "maptis_materials",
        desc: "~37,765 materials from MAPTIS UI. Keyed by their integer MaterialKey.",
        x: 40, y: 0,
        columns: [
          { name: "material_key", type: "INT", pk: true, note: "MAPTIS native PK (e.g. 60381)" },
          { name: "designation", type: "VARCHAR(300)", note: "Material name/alloy" },
          { name: "category_code", type: "VARCHAR(20)", note: "MAPTIS internal category" },
          { name: "spec_reference", type: "VARCHAR(200)", note: "MIL-STD, ASTM, AMS, etc." },
          { name: "manufacturer", type: "VARCHAR(300)" },
          { name: "trade_name", type: "VARCHAR(300)" },
          { name: "form", type: "VARCHAR(100)", note: "bar, sheet, wire, tube, etc." },
          { name: "condition_temper", type: "VARCHAR(100)", note: "T6, annealed, CW, etc." },
          { name: "raw_metadata", type: "JSONB", note: "Everything else MAPTIS gives us" },
          { name: "ingested_at", type: "TIMESTAMPTZ" },
        ],
      },
      {
        name: "maptis_test_reports",
        desc: "~90K reports. Common header across all 24 test types. This is MAPTIS's real shape.",
        x: 40, y: 330,
        columns: [
          { name: "test_report_key", type: "INT", pk: true, note: "MAPTIS native PK (e.g. 78137)" },
          { name: "material_key", type: "INT", fk: "maptis_materials.material_key", note: "FK to material" },
          { name: "test_type_key", type: "INT", note: "1-24 test type code" },
          { name: "test_type_caption", type: "VARCHAR(50)", note: "'Stress Corr', 'Flammability', etc." },
          { name: "test_report_number", type: "VARCHAR(200)", note: "65% NULL in SCC" },
          { name: "request_date", type: "VARCHAR(100)", note: "93% NULL, mixed formats" },
          { name: "temperature_min_f", type: "DECIMAL(10,4)", note: "Range: -425 to 75°F" },
          { name: "temperature_max_f", type: "DECIMAL(10,4)", note: "Range: -425 to 1600°F" },
          { name: "ingested_at", type: "TIMESTAMPTZ" },
          { name: "data_quality_flag", type: "VARCHAR(20)", note: "'clean'|'shifted'|'suspect'" },
        ],
      },
      {
        name: "maptis_test_details",
        desc: "Test-type-specific fields. MAPTIS prefixes these per type (STRESS_, FLAMM_, IMPACT_, etc.)",
        x: 40, y: 680,
        columns: [
          { name: "id", type: "SERIAL", pk: true },
          { name: "test_report_key", type: "INT", fk: "maptis_test_reports.test_report_key" },
          { name: "detail_key", type: "INT", note: "STRESS_Key, FLAMM_Key, etc." },
          { name: "data_source", type: "VARCHAR(100)", note: "'MSFC', 'PENDING', 'MSFC-STD-3029'" },
          { name: "nhb_test", type: "VARCHAR(50)", note: "'SCC', 'MSFC', etc." },
          { name: "test_subtype", type: "VARCHAR(50)", note: "STRESS_TestType → 'SCC'" },
          { name: "environment", type: "TEXT", note: "NaCl solutions, salt spray, etc." },
          { name: "rating", type: "VARCHAR(10)", note: "A/B/C/N/U (NASA SCC rating)" },
          { name: "resistance_level", type: "VARCHAR(20)", note: "HIGH/MODERATE/LOW" },
          { name: "reference_number", type: "VARCHAR(100)", note: "Misspelled 'Refererence' in MAPTIS" },
          { name: "update_date", type: "VARCHAR(20)", note: "YYYYMMDD string, not a real date" },
          { name: "sample_count", type: "INT", note: "94% populated for SCC" },
          { name: "raw_fields", type: "JSONB", note: "All remaining type-specific columns" },
          { name: "column_shift_detected", type: "BOOLEAN", note: "~7% of SCC rows are shifted" },
        ],
      },
      {
        name: "maptis_test_types",
        desc: "The 24 test categories from MAPTIS with their report counts.",
        x: 520, y: 0,
        columns: [
          { name: "test_type_key", type: "INT", pk: true, note: "1-24" },
          { name: "caption", type: "VARCHAR(50)", note: "'Stress Corr', 'Flammability', etc." },
          { name: "column_prefix", type: "VARCHAR(20)", note: "'STRESS_', 'FLAMM_', etc." },
          { name: "report_count", type: "INT", note: "6,430 for SCC" },
          { name: "expected_columns", type: "JSONB", note: "Schema template per test type" },
        ],
      },
      {
        name: "maptis_data_quality_log",
        desc: "Track every data quality issue found during ingest.",
        x: 520, y: 220,
        columns: [
          { name: "id", type: "SERIAL", pk: true },
          { name: "test_report_key", type: "INT", fk: "maptis_test_reports.test_report_key" },
          { name: "issue_type", type: "VARCHAR(30)", note: "'column_shift'|'null_required'|'type_mismatch'" },
          { name: "column_name", type: "VARCHAR(50)" },
          { name: "raw_value", type: "TEXT" },
          { name: "expected_pattern", type: "VARCHAR(100)" },
          { name: "severity", type: "VARCHAR(10)", note: "'error'|'warning'|'info'" },
          { name: "detected_at", type: "TIMESTAMPTZ" },
        ],
      },
    ],
  },
  mira_gold: {
    label: "MIRA Gold (Cleaned + Enriched)",
    desc: "Cleaned, normalized, evidence-linked data ready for the translation layer",
    color: "#0f766e",
    accent: "#2dd4bf",
    bg: "#061f1c",
    tables: [
      {
        name: "materials",
        desc: "Canonical material records with normalized families, enriched from MAPTIS + knowledge base.",
        x: 40, y: 0,
        columns: [
          { name: "id", type: "UUID", pk: true },
          { name: "maptis_material_key", type: "INT", fk: "maptis_materials.material_key", note: "Link back to raw" },
          { name: "designation", type: "VARCHAR(300)" },
          { name: "material_family", type: "VARCHAR(80)", note: "'austenitic_ss', 'ni_alloy', 'fluoropolymer'" },
          { name: "category", type: "VARCHAR(80)", note: "Normalized: 'metal', 'polymer', 'ceramic'" },
          { name: "alloy_system", type: "VARCHAR(80)", note: "'Fe-Cr-Ni', 'Ni-Cr-Mo', etc." },
          { name: "spec_reference", type: "VARCHAR(200)" },
          { name: "form", type: "VARCHAR(100)" },
          { name: "condition_temper", type: "VARCHAR(100)" },
          { name: "status", type: "VARCHAR(20)", note: "'active'|'legacy'|'restricted'" },
          { name: "updated_at", type: "TIMESTAMPTZ" },
        ],
      },
      {
        name: "scc_results",
        desc: "Cleaned SCC test data. 6,430 records from MAPTIS with column-shift corrections applied.",
        x: 40, y: 340,
        columns: [
          { name: "id", type: "UUID", pk: true },
          { name: "material_id", type: "UUID", fk: "materials.id" },
          { name: "maptis_test_report_key", type: "INT", fk: "raw.maptis_test_reports.test_report_key" },
          { name: "scc_rating", type: "CHAR(1)", note: "A/B/C — NASA rating" },
          { name: "scc_resistance", type: "VARCHAR(20)", note: "HIGH/MODERATE/LOW" },
          { name: "environment", type: "TEXT", note: "NaCl, salt spray, etc." },
          { name: "env_normalized", type: "VARCHAR(50)", note: "'nacl_immersion'|'salt_spray'|'atmosphere'" },
          { name: "temp_min_f", type: "DECIMAL(10,2)" },
          { name: "temp_max_f", type: "DECIMAL(10,2)" },
          { name: "sample_count", type: "INT" },
          { name: "threshold_level", type: "VARCHAR(10)", note: "D/E/F/B/C when available" },
          { name: "threshold_ksi", type: "DECIMAL(10,2)" },
          { name: "data_source", type: "VARCHAR(50)", note: "MSFC, MSFC-STD-3029, etc." },
          { name: "reference_doc", type: "VARCHAR(200)" },
          { name: "citation_id", type: "UUID", fk: "core.citations.id" },
          { name: "quality_score", type: "DECIMAL(3,2)", note: "0-1, from data quality checks" },
        ],
      },
      {
        name: "flammability_results",
        desc: "17,838 flammability test records. Largest test category in MAPTIS.",
        x: 520, y: 0,
        columns: [
          { name: "id", type: "UUID", pk: true },
          { name: "material_id", type: "UUID", fk: "materials.id" },
          { name: "maptis_test_report_key", type: "INT" },
          { name: "test_method", type: "VARCHAR(50)", note: "NASA-STD-6001 Test 1, etc." },
          { name: "o2_concentration_pct", type: "DECIMAL(5,2)" },
          { name: "pressure_psia", type: "DECIMAL(10,2)" },
          { name: "result", type: "VARCHAR(20)", note: "'pass'|'fail'|'self_extinguish'" },
          { name: "burn_length_in", type: "DECIMAL(8,4)" },
          { name: "burn_rate_in_per_sec", type: "DECIMAL(8,6)" },
          { name: "sample_config", type: "VARCHAR(30)", note: "'rod'|'sheet'|'mesh'" },
          { name: "sample_dimension", type: "DECIMAL(8,4)" },
          { name: "citation_id", type: "UUID", fk: "core.citations.id" },
          { name: "quality_score", type: "DECIMAL(3,2)" },
        ],
      },
      {
        name: "mech_impact_results",
        desc: "13,789 mechanical impact test records.",
        x: 520, y: 340,
        columns: [
          { name: "id", type: "UUID", pk: true },
          { name: "material_id", type: "UUID", fk: "materials.id" },
          { name: "maptis_test_report_key", type: "INT" },
          { name: "test_method", type: "VARCHAR(50)", note: "Test 13A, Test 13B" },
          { name: "o2_concentration_pct", type: "DECIMAL(5,2)" },
          { name: "pressure_psia", type: "DECIMAL(10,2)" },
          { name: "result", type: "VARCHAR(20)", note: "'reaction'|'no_reaction'" },
          { name: "reactions_of_20", type: "INT", note: "X out of 20 strikes" },
          { name: "energy_ft_lbs", type: "DECIMAL(10,2)" },
          { name: "sample_config", type: "VARCHAR(30)" },
          { name: "citation_id", type: "UUID", fk: "core.citations.id" },
          { name: "quality_score", type: "DECIMAL(3,2)" },
        ],
      },
      {
        name: "promoted_combustion_results",
        desc: "956 promoted combustion (Test 17) records.",
        x: 520, y: 620,
        columns: [
          { name: "id", type: "UUID", pk: true },
          { name: "material_id", type: "UUID", fk: "materials.id" },
          { name: "maptis_test_report_key", type: "INT" },
          { name: "o2_concentration_pct", type: "DECIMAL(5,2)" },
          { name: "pressure_psia", type: "DECIMAL(10,2)" },
          { name: "result", type: "VARCHAR(20)", note: "'burn'|'no_burn'" },
          { name: "burn_length_in", type: "DECIMAL(8,4)" },
          { name: "rod_diameter_in", type: "DECIMAL(8,4)" },
          { name: "citation_id", type: "UUID", fk: "core.citations.id" },
          { name: "quality_score", type: "DECIMAL(3,2)" },
        ],
      },
      {
        name: "compatibility_ratings",
        desc: "Computed O2/H2 ratings with evidence chains and severity modifiers.",
        x: 40, y: 680,
        columns: [
          { name: "id", type: "UUID", pk: true },
          { name: "material_id", type: "UUID", fk: "materials.id" },
          { name: "fluid_type", type: "VARCHAR(10)", note: "'LOX'|'GOX'|'LH2'|'GH2'" },
          { name: "rating", type: "VARCHAR(20)", note: "'preferred'|'acceptable'|'restricted'|'prohibited'" },
          { name: "pressure_psia", type: "DECIMAL(10,2)" },
          { name: "concentration_pct", type: "DECIMAL(5,2)" },
          { name: "severity_modifier", type: "DECIMAL(3,2)", note: "100%→1.0, 30%→0.75, 21%→0.30" },
          { name: "config_derating", type: "DECIMAL(5,4)", note: "rod=1.0, mesh=0.3, sheet=0.5" },
          { name: "confidence", type: "DECIMAL(3,2)" },
          { name: "evidence_chain", type: "JSONB", note: "Array of citation_ids" },
          { name: "computation_trace", type: "JSONB", note: "How we got this rating" },
          { name: "assessed_at", type: "TIMESTAMPTZ" },
        ],
      },
      {
        name: "mua_records",
        desc: "Material Usage Agreements per NASA-STD-6016C.",
        x: 40, y: 990,
        columns: [
          { name: "id", type: "UUID", pk: true },
          { name: "material_id", type: "UUID", fk: "materials.id" },
          { name: "mua_number", type: "VARCHAR(50)" },
          { name: "category", type: "CHAR(1)", note: "A/B/C/D per 6016C" },
          { name: "envelope", type: "JSONB", note: "{pressure, temp, conc, config}" },
          { name: "rationale", type: "TEXT" },
          { name: "restrictions", type: "TEXT" },
          { name: "status", type: "VARCHAR(20)" },
          { name: "expires_at", type: "DATE" },
          { name: "approved_by", type: "VARCHAR(100)" },
          { name: "program", type: "VARCHAR(100)" },
        ],
      },
    ],
  },
};

// Data quality stats from the actual SCC file
const DATA_QUALITY = {
  total_rows: 6430,
  unique_materials: 5903,
  column_shift_pct: 7,
  null_heavy_fields: [
    { field: "DisregardFlag", null_pct: 100 },
    { field: "MaxTemp50mil", null_pct: 99 },
    { field: "TEMP2", null_pct: 99 },
    { field: "Pressure", null_pct: 98 },
    { field: "CureSequence", null_pct: 93 },
    { field: "RequestDate", null_pct: 93 },
    { field: "ThresholdLevel", null_pct: 92 },
    { field: "DataSource", null_pct: 76 },
    { field: "TestReportNumber", null_pct: 65 },
    { field: "TempMin", null_pct: 72 },
    { field: "TempMax", null_pct: 61 },
    { field: "Environment", null_pct: 60 },
    { field: "SCCResistance", null_pct: 61 },
  ],
  rating_distribution: [
    { val: "A", count: 3231, desc: "High resistance" },
    { val: "B", count: 669, desc: "Moderate resistance" },
    { val: "C", count: 811, desc: "Low resistance" },
    { val: "U", count: 679, desc: "Unknown/untested" },
    { val: "N", count: 612, desc: "Not applicable" },
  ],
  scc_resistance: [
    { val: "HIGH", count: 1295 },
    { val: "MODERATE", count: 470 },
    { val: "LOW", count: 342 },
  ],
  top_environments: [
    { val: "Sodium Chloride (NaCl)", count: 1733 },
    { val: "SCC (generic)", count: 419 },
    { val: "3.5% NaCl alt. immersion", count: 182 },
    { val: "Seacoast at KSC", count: 39 },
    { val: "5% salt spray", count: 30 },
  ],
  test_type_counts: [
    { type: "Flammability", count: 17838 },
    { type: "TVS Outgassing", count: 16178 },
    { type: "Mech Impact", count: 13789 },
    { type: "Toxicity", count: 13099 },
    { type: "Stress Corr (SCC)", count: 6427 },
    { type: "Corrosion", count: 5777 },
    { type: "Odor", count: 3319 },
    { type: "Fluid Compat", count: 3987 },
    { type: "Flash Fire", count: 2256 },
    { type: "Tensile Strength", count: 2053 },
    { type: "Pneumatic Impact", count: 1252 },
    { type: "Promoted Combustion", count: 956 },
    { type: "Particle Impact", count: 559 },
    { type: "Elec Overload", count: 405 },
    { type: "VCM Optical", count: 353 },
    { type: "Elec Wire Insulation", count: 283 },
    { type: "Low Cycle Fatigue", count: 161 },
    { type: "Fungus", count: 102 },
    { type: "Flammability/MOC", count: 59 },
    { type: "Fracture Mechanics", count: 44 },
    { type: "Creep Rupture", count: 42 },
    { type: "High Cycle Fatigue", count: 29 },
    { type: "Crack Growth", count: 24 },
    { type: "Friction Heat", count: 24 },
    { type: "Arc Tracking", count: 12 },
  ],
};

const TABLE_W = 430;
const ROW_H = 24;
const HDR_H = 44;
const NOTE_SIZE = 9;

function getH(t) { return HDR_H + t.columns.length * ROW_H + 12; }

function Table({ table, schema, selected, onSelect, ox, oy }) {
  const h = getH(table);
  const x = table.x + ox;
  const y = table.y + oy;
  const s = SCHEMA[schema];
  const isSel = selected === `${schema}.${table.name}`;

  return (
    <g onClick={() => onSelect(`${schema}.${table.name}`)} style={{ cursor: "pointer" }}>
      <rect x={x} y={y} width={TABLE_W} height={h} rx={5}
        fill={isSel ? s.bg : "#0c1017"} stroke={isSel ? s.accent : "#1e293b"} strokeWidth={isSel ? 2 : 1} />
      <rect x={x} y={y} width={TABLE_W} height={HDR_H} rx={5} fill={s.color} />
      <rect x={x} y={y + HDR_H - 5} width={TABLE_W} height={5} fill={s.color} />
      <text x={x + 12} y={y + 18} fill="#fff" fontSize={13} fontWeight="bold"
        fontFamily="'JetBrains Mono', monospace">{table.name}</text>
      <text x={x + 12} y={y + 34} fill="rgba(255,255,255,0.6)" fontSize={10}
        fontFamily="system-ui, sans-serif">{table.desc?.slice(0, 70)}</text>
      {table.columns.map((col, i) => {
        const cy = y + HDR_H + 16 + i * ROW_H;
        return (
          <g key={col.name}>
            <text x={x + 10} y={cy} fill={col.pk ? s.accent : col.fk ? "#64748b" : "#cbd5e1"}
              fontSize={11.5} fontFamily="'JetBrains Mono', monospace"
              fontWeight={col.pk ? "bold" : "normal"}>
              {col.pk ? "⚷ " : col.fk ? "↗ " : "  "}{col.name}
            </text>
            <text x={x + 220} y={cy} fill="#475569" fontSize={10.5}
              fontFamily="'JetBrains Mono', monospace">{col.type}</text>
            {col.note && (
              <text x={x + TABLE_W - 8} y={cy} textAnchor="end" fill="#374151"
                fontSize={NOTE_SIZE} fontFamily="system-ui, sans-serif" fontStyle="italic">
                {col.note.slice(0, 40)}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}

function BarChart({ data, labelKey, valueKey, maxW, color, height }) {
  const maxVal = Math.max(...data.map(d => d[valueKey]));
  const barH = Math.min(22, (height - 10) / data.length);
  return (
    <svg width={maxW + 200} height={data.length * barH + 4} style={{ display: "block" }}>
      {data.map((d, i) => (
        <g key={i}>
          <rect x={120} y={i * barH + 2} width={(d[valueKey] / maxVal) * maxW} height={barH - 4}
            rx={2} fill={color} opacity={0.8} />
          <text x={116} y={i * barH + barH / 2 + 4} textAnchor="end" fill="#9ca3af"
            fontSize={10} fontFamily="'JetBrains Mono', monospace">{d[labelKey]}</text>
          <text x={124 + (d[valueKey] / maxVal) * maxW} y={i * barH + barH / 2 + 4}
            fill="#64748b" fontSize={9} fontFamily="'JetBrains Mono', monospace">
            {d[valueKey].toLocaleString()}
          </text>
        </g>
      ))}
    </svg>
  );
}

function DataQualityPanel() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div style={{ background: "#0c1017", border: "1px solid #1e293b", borderRadius: 8, padding: 16 }}>
        <h3 style={{ color: "#fbbf24", fontSize: 13, margin: "0 0 12px", fontFamily: "'JetBrains Mono', monospace" }}>
          ⚠ NULL Density (SCC Export)
        </h3>
        <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>
          {DATA_QUALITY.total_rows.toLocaleString()} rows • {DATA_QUALITY.unique_materials.toLocaleString()} unique materials • {DATA_QUALITY.column_shift_pct}% column-shifted
        </div>
        {DATA_QUALITY.null_heavy_fields.map((f, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ width: 120, fontSize: 10, color: "#9ca3af", fontFamily: "'JetBrains Mono', monospace", textAlign: "right" }}>
              {f.field}
            </span>
            <div style={{ flex: 1, background: "#1e293b", borderRadius: 2, height: 10 }}>
              <div style={{
                width: `${f.null_pct}%`, background: f.null_pct > 90 ? "#ef4444" : f.null_pct > 70 ? "#f59e0b" : "#3b82f6",
                borderRadius: 2, height: 10
              }} />
            </div>
            <span style={{ width: 35, fontSize: 9, color: "#64748b", fontFamily: "'JetBrains Mono', monospace" }}>
              {f.null_pct}%
            </span>
          </div>
        ))}
      </div>

      <div style={{ background: "#0c1017", border: "1px solid #1e293b", borderRadius: 8, padding: 16 }}>
        <h3 style={{ color: "#2dd4bf", fontSize: 13, margin: "0 0 12px", fontFamily: "'JetBrains Mono', monospace" }}>
          SCC Rating Distribution
        </h3>
        {DATA_QUALITY.rating_distribution.map((r, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span style={{
              width: 24, height: 24, borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 13, fontWeight: "bold", fontFamily: "'JetBrains Mono', monospace",
              background: r.val === "A" ? "#166534" : r.val === "B" ? "#854d0e" : r.val === "C" ? "#991b1b" : "#1e293b",
              color: r.val === "A" ? "#4ade80" : r.val === "B" ? "#fbbf24" : r.val === "C" ? "#fca5a5" : "#64748b",
            }}>{r.val}</span>
            <div style={{ flex: 1, background: "#1e293b", borderRadius: 2, height: 14 }}>
              <div style={{
                width: `${(r.count / 6430) * 100}%`, borderRadius: 2, height: 14,
                background: r.val === "A" ? "#22c55e" : r.val === "B" ? "#eab308" : r.val === "C" ? "#ef4444" : "#475569",
              }} />
            </div>
            <span style={{ width: 80, fontSize: 10, color: "#9ca3af", fontFamily: "'JetBrains Mono', monospace" }}>
              {r.count.toLocaleString()} — {r.desc}
            </span>
          </div>
        ))}

        <h3 style={{ color: "#2dd4bf", fontSize: 13, margin: "20px 0 12px", fontFamily: "'JetBrains Mono', monospace" }}>
          Top Environments
        </h3>
        {DATA_QUALITY.top_environments.map((e, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#9ca3af", marginBottom: 3, fontFamily: "'JetBrains Mono', monospace" }}>
            <span>{e.val}</span>
            <span>{e.count.toLocaleString()}</span>
          </div>
        ))}
      </div>

      <div style={{ gridColumn: "1 / -1", background: "#0c1017", border: "1px solid #1e293b", borderRadius: 8, padding: 16 }}>
        <h3 style={{ color: "#a78bfa", fontSize: 13, margin: "0 0 12px", fontFamily: "'JetBrains Mono', monospace" }}>
          All 24 MAPTIS Test Types (~89,778 total reports)
        </h3>
        <BarChart data={DATA_QUALITY.test_type_counts} labelKey="type" valueKey="count"
          maxW={400} color="#7c3aed" height={600} />
      </div>
    </div>
  );
}

function generateRealSQL() {
  return `-- ================================================================
-- MIRA SCHEMA — Grounded in Real MAPTIS Data
-- Derived from actual SCC export: 6,430 rows, 26 columns
-- Two-tier: Raw ingest (bronze) → Cleaned gold
-- PostgreSQL 16+ with pgvector
-- ================================================================

CREATE EXTENSION IF NOT EXISTS "pgvector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================
-- TIER 1: MAPTIS RAW INGEST (Bronze)
-- Mirror of how MAPTIS actually exports data
-- ============================================

-- 24 test type definitions
CREATE TABLE mira.maptis_test_types (
    test_type_key           INT PRIMARY KEY,
    caption                 VARCHAR(50) NOT NULL,       -- 'Stress Corr', 'Flammability'
    column_prefix           VARCHAR(20),                -- 'STRESS_', 'FLAMM_', 'IMPACT_'
    report_count            INT DEFAULT 0,
    expected_columns        JSONB DEFAULT '[]'          -- template for this test type
);

-- Seed the 24 test types
INSERT INTO mira.maptis_test_types (test_type_key, caption, column_prefix, report_count) VALUES
    (1,  'Arc Tracking',           'ARC_',     12),
    (2,  'Corrosion',              'CORR_',    5777),
    (3,  'Crack Growth',           'CRACK_',   24),
    (4,  'Creep Rupture',          'CREEP_',   42),
    (5,  'Elec Overload',          'ELOAD_',   405),
    (6,  'Elec Wire Insulation',   'EWIRE_',   283),
    (7,  'Flammability',           'FLAMM_',   17838),
    (8,  'Flammability/MOC',       'FMOC_',    59),
    (9,  'Flash Fire',             'FLASH_',   2256),
    (10, 'Fluid Compatibility',    'FLUID_',   3987),
    (11, 'Fracture Mechanics',     'FRACT_',   44),
    (12, 'Friction Heat',          'FHEAT_',   24),
    (13, 'Stress Corr',            'STRESS_',  6427),
    (14, 'Fungus',                 'FUNG_',    102),
    (15, 'High Cycle Fatigue',     'HCF_',     29),
    (16, 'Low Cycle Fatigue',      'LCF_',     161),
    (17, 'Mech Impact',            'IMPACT_',  13789),
    (18, 'Odor',                   'ODOR_',    3319),
    (19, 'Particle Impact',        'PIMP_',    559),
    (20, 'Pneumatic Impact',       'PNIMP_',   1252),
    (21, 'Promoted Combustion',    'PCOMB_',   956),
    (22, 'Tensile Strength',       'TENS_',    2053),
    (23, 'Toxicity',               'TOX_',     13099),
    (24, 'TVS Outgassing',         'TVS_',     16178),
    (25, 'VCM Optical',            'VCM_',     353);

-- ~37,765 materials as MAPTIS sees them
CREATE TABLE mira.maptis_materials (
    material_key            INT PRIMARY KEY,             -- MAPTIS native key
    designation             VARCHAR(300) NOT NULL,
    category_code           VARCHAR(20),
    spec_reference          VARCHAR(200),
    manufacturer            VARCHAR(300),
    trade_name              VARCHAR(300),
    form                    VARCHAR(100),                -- bar, sheet, wire, tube
    condition_temper        VARCHAR(100),                -- T6, annealed, CW
    raw_metadata            JSONB DEFAULT '{}',
    ingested_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_maptis_mat_desig ON mira.maptis_materials
    USING GIN(designation gin_trgm_ops);

-- ~90K test reports: common header across all 24 types
CREATE TABLE mira.maptis_test_reports (
    test_report_key         INT PRIMARY KEY,             -- MAPTIS native key
    material_key            INT NOT NULL REFERENCES mira.maptis_materials(material_key),
    test_type_key           INT NOT NULL REFERENCES mira.maptis_test_types(test_type_key),
    test_report_number      VARCHAR(200),                -- 65% NULL for SCC
    request_date            VARCHAR(100),                -- 93% NULL, mixed format
    temperature_min_f       DECIMAL(10,4),               -- -425 to +75°F
    temperature_max_f       DECIMAL(10,4),               -- -425 to +1600°F
    data_quality_flag       VARCHAR(20) DEFAULT 'pending',
    ingested_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_maptis_tr_mat ON mira.maptis_test_reports(material_key);
CREATE INDEX idx_maptis_tr_type ON mira.maptis_test_reports(test_type_key);

-- Test-type-specific fields in a flexible structure
-- MAPTIS prefixes these per type: STRESS_, FLAMM_, IMPACT_, etc.
CREATE TABLE mira.maptis_test_details (
    id                      SERIAL PRIMARY KEY,
    test_report_key         INT NOT NULL REFERENCES mira.maptis_test_reports(test_report_key),
    detail_key              INT,                         -- STRESS_Key, FLAMM_Key, etc.
    data_source             VARCHAR(100),                -- 'MSFC', 'PENDING'
    nhb_test                VARCHAR(50),                 -- 'SCC', 'MSFC'
    test_subtype            VARCHAR(50),                 -- echoes test type
    environment             TEXT,                        -- test environment description
    result_primary          VARCHAR(100),                -- rating/resistance/pass-fail
    result_secondary        VARCHAR(100),                -- secondary classification
    reference_number        VARCHAR(100),                -- doc reference
    update_date_raw         VARCHAR(20),                 -- YYYYMMDD string
    sample_count            INT,
    raw_fields              JSONB DEFAULT '{}',          -- all remaining type-specific cols
    column_shift_detected   BOOLEAN DEFAULT false,
    UNIQUE(test_report_key, detail_key)
);

CREATE INDEX idx_details_tr ON mira.maptis_test_details(test_report_key);

-- Data quality tracking
CREATE TABLE mira.maptis_data_quality_log (
    id                      SERIAL PRIMARY KEY,
    test_report_key         INT REFERENCES mira.maptis_test_reports(test_report_key),
    issue_type              VARCHAR(30) NOT NULL,        -- 'column_shift', 'null_required', 'type_mismatch'
    column_name             VARCHAR(50),
    raw_value               TEXT,
    expected_pattern        VARCHAR(100),
    severity                VARCHAR(10) DEFAULT 'warning',
    detected_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_dq_report ON mira.maptis_data_quality_log(test_report_key);
CREATE INDEX idx_dq_type ON mira.maptis_data_quality_log(issue_type);


-- ============================================
-- TIER 2: MIRA GOLD (Cleaned + Enriched)
-- Schema the translation layer actually queries
-- ============================================

-- Canonical materials with normalized families
CREATE TABLE mira.materials (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    maptis_material_key     INT UNIQUE REFERENCES mira.maptis_materials(material_key),
    designation             VARCHAR(300) NOT NULL,
    material_family         VARCHAR(80),                 -- 'austenitic_ss', 'ni_alloy', 'fluoropolymer'
    category                VARCHAR(80),                 -- 'metal', 'polymer', 'ceramic', 'composite'
    alloy_system            VARCHAR(80),                 -- 'Fe-Cr-Ni', 'Ni-Cr-Mo'
    spec_reference          VARCHAR(200),
    form                    VARCHAR(100),
    condition_temper        VARCHAR(100),
    status                  VARCHAR(20) DEFAULT 'active',
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mat_family ON mira.materials(material_family);
CREATE INDEX idx_mat_category ON mira.materials(category);
CREATE INDEX idx_mat_desig ON mira.materials USING GIN(designation gin_trgm_ops);

-- SCC results: cleaned from the 6,430 MAPTIS records
CREATE TABLE mira.scc_results (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    maptis_test_report_key  INT REFERENCES mira.maptis_test_reports(test_report_key),
    scc_rating              CHAR(1) NOT NULL,            -- A/B/C per MSFC-STD-3029
    scc_resistance          VARCHAR(20),                 -- HIGH/MODERATE/LOW
    environment             TEXT,
    env_normalized          VARCHAR(50),                 -- 'nacl_immersion', 'salt_spray', 'atmosphere'
    temp_min_f              DECIMAL(10,2),
    temp_max_f              DECIMAL(10,2),
    sample_count            INT,
    threshold_level         VARCHAR(10),                 -- D/E/F/B/C
    threshold_ksi           DECIMAL(10,2),
    data_source             VARCHAR(50),
    reference_doc           VARCHAR(200),
    citation_id             UUID,                        -- FK to core.citations
    quality_score           DECIMAL(3,2) DEFAULT 0.50    -- 0-1 from ingest QA
);

CREATE INDEX idx_scc_mat ON mira.scc_results(material_id);
CREATE INDEX idx_scc_rating ON mira.scc_results(scc_rating);
CREATE INDEX idx_scc_resist ON mira.scc_results(scc_resistance);

-- Flammability results: 17,838 records (largest category)
CREATE TABLE mira.flammability_results (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    maptis_test_report_key  INT,
    test_method             VARCHAR(50),                 -- 'NASA-STD-6001 Test 1', etc.
    o2_concentration_pct    DECIMAL(5,2),
    pressure_psia           DECIMAL(10,2),
    result                  VARCHAR(20) NOT NULL,        -- 'pass', 'fail', 'self_extinguish'
    burn_length_in          DECIMAL(8,4),
    burn_rate_in_per_sec    DECIMAL(8,6),
    sample_config           VARCHAR(30),                 -- 'rod', 'sheet', 'mesh'
    sample_dimension_in     DECIMAL(8,4),
    citation_id             UUID,
    quality_score           DECIMAL(3,2) DEFAULT 0.50
);

CREATE INDEX idx_flamm_mat ON mira.flammability_results(material_id);
CREATE INDEX idx_flamm_result ON mira.flammability_results(result);
CREATE INDEX idx_flamm_o2 ON mira.flammability_results(o2_concentration_pct);
CREATE INDEX idx_flamm_pressure ON mira.flammability_results(pressure_psia);

-- Mech impact results: 13,789 records
CREATE TABLE mira.mech_impact_results (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    maptis_test_report_key  INT,
    test_method             VARCHAR(50),                 -- 'Test 13A', 'Test 13B'
    o2_concentration_pct    DECIMAL(5,2),
    pressure_psia           DECIMAL(10,2),
    result                  VARCHAR(20) NOT NULL,        -- 'reaction', 'no_reaction'
    reactions_of_20         INT,                         -- X/20 strikes
    energy_ft_lbs           DECIMAL(10,2),
    sample_config           VARCHAR(30),
    citation_id             UUID,
    quality_score           DECIMAL(3,2) DEFAULT 0.50
);

CREATE INDEX idx_impact_mat ON mira.mech_impact_results(material_id);
CREATE INDEX idx_impact_result ON mira.mech_impact_results(result);

-- Promoted combustion (Test 17): 956 records
CREATE TABLE mira.promoted_combustion_results (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    maptis_test_report_key  INT,
    o2_concentration_pct    DECIMAL(5,2),
    pressure_psia           DECIMAL(10,2),
    result                  VARCHAR(20) NOT NULL,        -- 'burn', 'no_burn'
    burn_length_in          DECIMAL(8,4),
    rod_diameter_in         DECIMAL(8,4),
    citation_id             UUID,
    quality_score           DECIMAL(3,2) DEFAULT 0.50
);

CREATE INDEX idx_pcomb_mat ON mira.promoted_combustion_results(material_id);

-- Outgassing results: 16,178 records
CREATE TABLE mira.outgassing_results (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    maptis_test_report_key  INT,
    tml_pct                 DECIMAL(6,3),                -- Total Mass Loss %
    cvcm_pct                DECIMAL(6,3),                -- Collected Volatile Condensable Material %
    wvr_pct                 DECIMAL(6,3),                -- Water Vapor Regained %
    test_temperature_c      DECIMAL(8,2),
    citation_id             UUID,
    quality_score           DECIMAL(3,2) DEFAULT 0.50
);

CREATE INDEX idx_outgas_mat ON mira.outgassing_results(material_id);

-- Toxicity results: 13,099 records
CREATE TABLE mira.toxicity_results (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    maptis_test_report_key  INT,
    toxicity_rating         VARCHAR(20),                 -- T-rating
    off_gas_products        JSONB DEFAULT '[]',
    citation_id             UUID,
    quality_score           DECIMAL(3,2) DEFAULT 0.50
);

CREATE INDEX idx_tox_mat ON mira.toxicity_results(material_id);

-- Generic test results: catch-all for the smaller test types
-- (corrosion, crack growth, creep, fatigue, fungus, etc.)
CREATE TABLE mira.generic_test_results (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    maptis_test_report_key  INT,
    test_type_key           INT REFERENCES mira.maptis_test_types(test_type_key),
    result_primary          VARCHAR(100),
    result_secondary        VARCHAR(100),
    conditions              JSONB DEFAULT '{}',
    measurements            JSONB DEFAULT '{}',
    citation_id             UUID,
    quality_score           DECIMAL(3,2) DEFAULT 0.50
);

CREATE INDEX idx_generic_mat ON mira.generic_test_results(material_id);
CREATE INDEX idx_generic_type ON mira.generic_test_results(test_type_key);

-- O2/H2 compatibility ratings: computed from test evidence
CREATE TABLE mira.compatibility_ratings (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    fluid_type              VARCHAR(10) NOT NULL,        -- 'LOX', 'GOX', 'LH2', 'GH2'
    rating                  VARCHAR(20) NOT NULL,        -- 'preferred', 'acceptable', 'restricted', 'prohibited'
    pressure_psia           DECIMAL(10,2),
    concentration_pct       DECIMAL(5,2),
    temp_range_f            VARCHAR(50),
    severity_modifier       DECIMAL(3,2) DEFAULT 1.00,   -- concentration-dependent
    config_derating         DECIMAL(5,4),                -- rod=1.0, mesh=0.3
    confidence              DECIMAL(3,2) DEFAULT 0.50,
    evidence_chain          JSONB DEFAULT '[]',          -- citation_id array
    computation_trace       JSONB DEFAULT '{}',          -- reproducible reasoning
    assessed_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_compat_mat ON mira.compatibility_ratings(material_id);
CREATE INDEX idx_compat_fluid ON mira.compatibility_ratings(fluid_type);
CREATE INDEX idx_compat_rating ON mira.compatibility_ratings(rating);

-- MUA records: Material Usage Agreements
CREATE TABLE mira.mua_records (
    id                      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_id             UUID NOT NULL REFERENCES mira.materials(id) ON DELETE CASCADE,
    mua_number              VARCHAR(50) UNIQUE,
    category                CHAR(1),                     -- A/B/C/D per NASA-STD-6016C
    envelope                JSONB NOT NULL,              -- {pressure, temp, conc, config}
    rationale               TEXT,
    restrictions            TEXT,
    status                  VARCHAR(20) DEFAULT 'draft',
    expires_at              DATE,
    approved_by             VARCHAR(100),
    program                 VARCHAR(100),
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mua_mat ON mira.mua_records(material_id);
CREATE INDEX idx_mua_status ON mira.mua_records(status);

-- ============================================
-- MATERIALIZED VIEW: Material safety dashboard
-- ============================================
CREATE MATERIALIZED VIEW mira.mv_material_safety AS
SELECT
    m.id,
    m.designation,
    m.material_family,
    m.category,
    (SELECT scc_rating FROM mira.scc_results WHERE material_id = m.id
     ORDER BY quality_score DESC LIMIT 1) AS best_scc_rating,
    (SELECT COUNT(*) FROM mira.flammability_results WHERE material_id = m.id) AS flamm_tests,
    (SELECT COUNT(*) FROM mira.flammability_results WHERE material_id = m.id AND result = 'fail') AS flamm_fails,
    (SELECT COUNT(*) FROM mira.mech_impact_results WHERE material_id = m.id) AS impact_tests,
    (SELECT rating FROM mira.compatibility_ratings
     WHERE material_id = m.id AND fluid_type = 'GOX'
     ORDER BY confidence DESC LIMIT 1) AS gox_rating,
    (SELECT rating FROM mira.compatibility_ratings
     WHERE material_id = m.id AND fluid_type = 'GH2'
     ORDER BY confidence DESC LIMIT 1) AS gh2_rating
FROM mira.materials m;

-- Refresh nightly or on demand
-- REFRESH MATERIALIZED VIEW mira.mv_material_safety;
`;
}

export default function MIRASchema() {
  const [tab, setTab] = useState("erd");
  const [activeLayer, setActiveLayer] = useState("both");
  const [selected, setSelected] = useState(null);

  const tabs = [
    { id: "erd", label: "ERD" },
    { id: "quality", label: "Data Quality" },
    { id: "sql", label: "SQL DDL" },
  ];

  const layers = [
    { id: "both", label: "Both Tiers" },
    { id: "maptis_raw", label: "Raw Ingest (Bronze)" },
    { id: "mira_gold", label: "Gold (Cleaned)" },
  ];

  return (
    <div style={{
      background: "#030712", color: "#e2e8f0", minHeight: "100vh",
      fontFamily: "system-ui, -apple-system, sans-serif", padding: 20,
    }}>
      <div style={{ maxWidth: 1050, margin: "0 auto" }}>
        <div style={{ marginBottom: 16 }}>
          <h1 style={{
            fontSize: 26, fontWeight: 800, margin: 0, letterSpacing: -0.5,
            background: "linear-gradient(135deg, #fbbf24, #2dd4bf)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>
            MIRA Schema — Grounded in Real MAPTIS Data
          </h1>
          <p style={{ color: "#475569", margin: "4px 0 0", fontSize: 13 }}>
            Derived from actual SCC export • 6,430 rows • 26 columns • Two-tier: Raw Ingest → Gold
          </p>
        </div>

        {/* Stats bar */}
        <div style={{ display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
          {[
            { label: "Materials", val: "37,765", color: "#fbbf24" },
            { label: "Test Reports", val: "89,778", color: "#2dd4bf" },
            { label: "Test Types", val: "24", color: "#a78bfa" },
            { label: "SCC Records", val: "6,430", color: "#fb923c" },
            { label: "Column Shift", val: "~7%", color: "#ef4444" },
          ].map((s, i) => (
            <div key={i} style={{
              background: "#0c1017", border: "1px solid #1e293b", borderRadius: 6, padding: "6px 14px",
            }}>
              <div style={{ color: "#64748b", fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}>{s.label}</div>
              <div style={{ color: s.color, fontSize: 18, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{s.val}</div>
            </div>
          ))}
        </div>

        {/* Tab bar */}
        <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding: "5px 14px", borderRadius: 5, cursor: "pointer", fontSize: 12,
              border: `1px solid ${tab === t.id ? "#2dd4bf" : "#1e293b"}`,
              background: tab === t.id ? "#0d3d38" : "#0c1017",
              color: tab === t.id ? "#2dd4bf" : "#64748b", fontWeight: tab === t.id ? 700 : 400,
            }}>{t.label}</button>
          ))}
          {tab === "erd" && (
            <>
              <span style={{ color: "#1e293b", margin: "0 4px", lineHeight: "28px" }}>│</span>
              {layers.map(l => (
                <button key={l.id} onClick={() => setActiveLayer(l.id)} style={{
                  padding: "5px 14px", borderRadius: 5, cursor: "pointer", fontSize: 12,
                  border: `1px solid ${activeLayer === l.id ? "#fbbf24" : "#1e293b"}`,
                  background: activeLayer === l.id ? "#1c1208" : "#0c1017",
                  color: activeLayer === l.id ? "#fbbf24" : "#64748b",
                  fontWeight: activeLayer === l.id ? 700 : 400,
                }}>{l.label}</button>
              ))}
            </>
          )}
        </div>

        {/* Content */}
        {tab === "erd" && (
          <div style={{
            background: "#060a10", border: "1px solid #1e293b", borderRadius: 8,
            overflow: "auto", maxHeight: "72vh",
          }}>
            <svg width={1000} height={
              activeLayer === "both" ? 2400
              : activeLayer === "maptis_raw" ? 1050
              : 1350
            } style={{ display: "block" }}>
              {(activeLayer === "both" || activeLayer === "maptis_raw") && (
                <g>
                  <rect x={0} y={0} width={1000} height={30} fill={SCHEMA.maptis_raw.bg} />
                  <text x={14} y={20} fill={SCHEMA.maptis_raw.accent} fontSize={13} fontWeight="bold"
                    fontFamily="'JetBrains Mono', monospace">▪ {SCHEMA.maptis_raw.label}</text>
                  <text x={300} y={20} fill="#475569" fontSize={11} fontFamily="system-ui">
                    {SCHEMA.maptis_raw.desc}
                  </text>
                  {SCHEMA.maptis_raw.tables.map(t => (
                    <Table key={t.name} table={t} schema="maptis_raw"
                      selected={selected} onSelect={setSelected} ox={0} oy={40} />
                  ))}
                </g>
              )}
              {(activeLayer === "both" || activeLayer === "mira_gold") && (
                <g>
                  {(() => {
                    const oy = activeLayer === "both" ? 1100 : 0;
                    return (
                      <>
                        <rect x={0} y={oy} width={1000} height={30} fill={SCHEMA.mira_gold.bg} />
                        <text x={14} y={oy + 20} fill={SCHEMA.mira_gold.accent} fontSize={13} fontWeight="bold"
                          fontFamily="'JetBrains Mono', monospace">▪ {SCHEMA.mira_gold.label}</text>
                        <text x={380} y={oy + 20} fill="#475569" fontSize={11} fontFamily="system-ui">
                          {SCHEMA.mira_gold.desc}
                        </text>
                        {SCHEMA.mira_gold.tables.map(t => (
                          <Table key={t.name} table={t} schema="mira_gold"
                            selected={selected} onSelect={setSelected} ox={0} oy={oy + 40} />
                        ))}
                      </>
                    );
                  })()}
                </g>
              )}
            </svg>
          </div>
        )}

        {tab === "quality" && <DataQualityPanel />}

        {tab === "sql" && (
          <div style={{
            background: "#060a10", border: "1px solid #1e293b", borderRadius: 8,
            overflow: "auto", maxHeight: "72vh", padding: 18,
          }}>
            <pre style={{
              color: "#cbd5e1", fontSize: 12, fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              lineHeight: 1.6, margin: 0, whiteSpace: "pre-wrap",
            }}>
              {generateRealSQL()}
            </pre>
          </div>
        )}

        <div style={{ marginTop: 12, color: "#334155", fontSize: 11 }}>
          Click tables to highlight • Toggle Raw/Gold tiers • Data Quality tab shows actual MAPTIS field sparsity
        </div>
      </div>
    </div>
  );
}
