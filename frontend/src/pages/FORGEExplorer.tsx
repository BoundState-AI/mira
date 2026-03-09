import { useState, useEffect } from "react";
import {
  Database, Search, Shield, Scale, FileText, Bot, Loader2,
  ChevronDown, ChevronRight, Network, ScrollText, Zap, Filter,
  BarChart3, GitFork, Clock, Eye, CheckCircle2, Activity,
  ArrowRight, Sparkles, Table2,
} from "lucide-react";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  forgeCompile,
  forgeBSMSQuery,
  type ForgeCompileJobResponse,
  type ForgeCompileRequest,
  type ForgeCompileResponse,
  type ForgeBSMSQueryResponse,
} from "@/lib/api";

/* ── Question type config ──────────────────────────────────────────── */

const QT: Record<string, { icon: typeof Search; label: string; cls: string }> = {
  text_search: { icon: Search, label: "Search", cls: "text-blue-600 dark:text-blue-400" },
  detail_view: { icon: Eye, label: "Detail", cls: "text-green-600 dark:text-green-400" },
  categorical_filter: { icon: Filter, label: "Filter", cls: "text-sky-600 dark:text-sky-400" },
  filter: { icon: Filter, label: "Filter", cls: "text-sky-600 dark:text-sky-400" },
  aggregation: { icon: BarChart3, label: "Stats", cls: "text-amber-600 dark:text-amber-400" },
  relationship: { icon: GitFork, label: "Join", cls: "text-violet-600 dark:text-violet-400" },
  time_series: { icon: Clock, label: "Timeline", cls: "text-pink-600 dark:text-pink-400" },
  comparison: { icon: Scale, label: "Compare", cls: "text-orange-600 dark:text-orange-400" },
};

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    PASS: "bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
    ACTIVE: "bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800",
    PENDING: "bg-muted text-muted-foreground border-border",
    ACCEPTED: "bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
    REJECTED: "bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800",
  };
  return (
    <span className={`inline-flex items-center rounded-sm px-3 py-1 text-xs font-medium tracking-wide uppercase border ${styles[status] || styles.PENDING}`}>
      {status}
    </span>
  );
}

/* ── Pipeline stage animation ──────────────────────────────────────── */

function PipelineStage({ icon: Icon, label, model, active, passed }: {
  icon: typeof Shield;
  label: string;
  model: string;
  active: boolean;
  passed: boolean;
}) {
  return (
    <Card className={`p-3 transition-all duration-300 ${
      active ? "border-primary/30 bg-primary/5" : passed ? "border-green-500/20 bg-green-500/5" : "opacity-50"
    }`}>
      <div className="flex items-center gap-2 mb-1">
        {active ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> :
         passed ? <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" /> :
         <Icon className="h-4 w-4 text-muted-foreground" />}
        <span className="text-sm font-medium">{label}</span>
        <StatusBadge status={passed ? "PASS" : active ? "ACTIVE" : "PENDING"} />
      </div>
      <p className="text-xs text-muted-foreground">{model}</p>
    </Card>
  );
}

/* ── Types for parsed compile data ─────────────────────────────────── */

interface TableProfile {
  name: string;
  rows: number;
  cols: number;
}

interface ParsedQuestion {
  id: string;
  q: string;
  type: string;
  table: string;
  u: number;
  category: string;
}

interface ParsedRelationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  type: string;
}

interface ParsedCapabilityCoverage {
  capability_id: string;
  label: string;
  support_level: string;
  rationale: string;
}

interface ParsedCandidateArchetype {
  motif_type: string;
  proposed_intent: string;
  confidence: number;
  tables_involved: string[];
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return "";
}

function finiteNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const numeric = typeof value === "number" ? value : Number(value);
    if (Number.isFinite(numeric)) {
      return numeric;
    }
  }
  return null;
}

function extractTables(response: ForgeCompileResponse): TableProfile[] {
  const manifest = response.schema_manifest as Record<string, unknown>;
  const tables = (manifest.tables || []) as Array<Record<string, unknown>>;
  return tables.map((t) => ({
    name: String(t.name || ""),
    rows: Number(t.row_count || 0),
    cols: Array.isArray(t.columns) ? t.columns.length : 0,
  }));
}

function extractQuestions(response: ForgeCompileResponse): ParsedQuestion[] {
  const qmap = response.question_map as Record<string, unknown>;
  const categories = (qmap.question_categories || []) as Array<Record<string, unknown>>;
  const questions: ParsedQuestion[] = [];
  for (const cat of categories) {
    const qs = (cat.questions || []) as Array<Record<string, unknown>>;
    for (const q of qs) {
      const confidence = q.confidence as Record<string, unknown> | undefined;
      const utility = finiteNumber(
        q.utility,
        q.reliability_score,
        confidence?.score,
      );
      questions.push({
        id: firstString(q.id, String(questions.length)),
        q: firstString(q.natural_language, q.text, q.question),
        type: firstString(q.template_type, q.type, cat.category, "text_search"),
        table: firstString(
          q.target_table,
          q.table,
          Array.isArray(q.join_tables) ? q.join_tables[0] : undefined,
        ),
        u: utility ?? 0.8,
        category: firstString(cat.category, "Questions"),
      });
    }
  }
  return questions;
}

function groupQuestions(questions: ParsedQuestion[]): Array<[string, ParsedQuestion[]]> {
  const grouped = new Map<string, ParsedQuestion[]>();
  for (const question of questions) {
    const key = question.category || "Questions";
    const existing = grouped.get(key) || [];
    existing.push(question);
    grouped.set(key, existing);
  }
  return Array.from(grouped.entries());
}

function extractRelationships(response: ForgeCompileResponse): ParsedRelationship[] {
  const graph = response.relationship_graph as Record<string, unknown>;
  const rels = (graph.relationships || graph.edges || []) as Array<Record<string, unknown>>;
  return rels.map((r) => ({
    from_table: firstString(r.source_table, r.from_table),
    from_column: firstString(r.source_column, r.from_column),
    to_table: firstString(r.target_table, r.to_table),
    to_column: firstString(r.target_column, r.to_column),
    type: firstString(r.type, r.discovery_method, "fk"),
  }));
}

function extractCapabilityCoverage(response: ForgeCompileResponse): ParsedCapabilityCoverage[] {
  const qmap = response.question_map as Record<string, unknown>;
  const coverage = (qmap.capability_coverage || []) as Array<Record<string, unknown>>;
  return coverage.map((entry) => ({
    capability_id: firstString(entry.capability_id),
    label: firstString(entry.label, entry.capability_id),
    support_level: firstString(entry.support_level, "unsupported"),
    rationale: firstString(entry.rationale),
  }));
}

function extractCandidateArchetypes(response: ForgeCompileResponse): ParsedCandidateArchetype[] {
  const qmap = response.question_map as Record<string, unknown>;
  const candidates = (qmap.candidate_archetypes || []) as Array<Record<string, unknown>>;
  return candidates.map((entry) => ({
    motif_type: firstString(entry.motif_type),
    proposed_intent: firstString(entry.proposed_intent),
    confidence: finiteNumber(entry.confidence) ?? 0,
    tables_involved: Array.isArray(entry.tables_involved)
      ? entry.tables_involved.map((value) => String(value))
      : [],
  }));
}

/* ════════════════════════════════════════════════════════════════════ */

const EXAMPLE_SQLITE_URL = "sqlite:////tmp/forge_demo.sqlite";

const COMPILE_MODES = {
  curated: {
    label: "Curated",
    description: "10 best decision-support questions",
    maxQuestions: 10,
  },
  comprehensive: {
    label: "Comprehensive",
    description: "broader answer surface",
    maxQuestions: 240,
  },
} as const;

type CompileMode = keyof typeof COMPILE_MODES;

type CompilePhaseId =
  | "introspection"
  | "motif_detection"
  | "archetype_matching"
  | "semantic_dedup"
  | "scoring_diversity"
  | "llm_polish"
  | "bundle_artifacts";

interface CompilePhaseDefinition {
  id: CompilePhaseId;
  label: string;
  description: string;
  icon: typeof Database;
}

const CURATED_COMPILE_PHASES: CompilePhaseDefinition[] = [
  {
    id: "introspection",
    label: "Introspection",
    description: "Schema, profiling, relationships, and data quality",
    icon: Database,
  },
  {
    id: "motif_detection",
    label: "Motif detection",
    description: "Recurring structural patterns in the discovered graph",
    icon: Network,
  },
  {
    id: "archetype_matching",
    label: "Archetype matching",
    description: "Binding the schema to intent-driven question families",
    icon: Sparkles,
  },
  {
    id: "semantic_dedup",
    label: "Semantic dedup",
    description: "Collapsing equivalent engineering questions",
    icon: GitFork,
  },
  {
    id: "scoring_diversity",
    label: "Scoring + diversity",
    description: "Ranking and selecting the final question surface",
    icon: Activity,
  },
  {
    id: "llm_polish",
    label: "LLM polish",
    description: "Sonnet rewrite-only refinement",
    icon: Bot,
  },
  {
    id: "bundle_artifacts",
    label: "Bundle/artifacts",
    description: "Capabilities, authority pack, lineage, and bundle output",
    icon: FileText,
  },
];

const COMPREHENSIVE_COMPILE_PHASES: CompilePhaseDefinition[] = [
  CURATED_COMPILE_PHASES[0],
  {
    id: "archetype_matching",
    label: "Question generation",
    description: "Generating broader answerable question families",
    icon: Sparkles,
  },
  CURATED_COMPILE_PHASES[5],
  CURATED_COMPILE_PHASES[6],
];

type CompilePhaseStatus = "pending" | "active" | "completed" | "failed";

function getCompilePhases(mode: CompileMode): CompilePhaseDefinition[] {
  return mode === "curated" ? CURATED_COMPILE_PHASES : COMPREHENSIVE_COMPILE_PHASES;
}

function inferCompilePhaseId(
  job: ForgeCompileJobResponse,
  mode: CompileMode,
): CompilePhaseId {
  const stage = job.stage.toLowerCase();
  const message = job.message.toLowerCase();

  if (job.status === "completed") {
    return "bundle_artifacts";
  }
  if (stage === "introspection") {
    return "introspection";
  }
  if (stage === "llm_refinement") {
    return "llm_polish";
  }
  if (stage === "runtime_planning" || stage === "artifact_generation") {
    return "bundle_artifacts";
  }
  if (stage === "question_generation") {
    if (mode === "comprehensive") {
      return "archetype_matching";
    }
    if (message.includes("motif")) {
      return "motif_detection";
    }
    if (message.includes("archetype")) {
      return "archetype_matching";
    }
    if (message.includes("semantic")) {
      return "semantic_dedup";
    }
    if (
      message.includes("scoring")
      || message.includes("diverse")
      || message.includes("selected")
      || message.includes("coverage")
      || message.includes("candidate")
      || message.includes("finalizing")
    ) {
      return "scoring_diversity";
    }
    return "motif_detection";
  }

  return mode === "curated" ? "introspection" : "introspection";
}

function getCompilePhaseStates(
  job: ForgeCompileJobResponse,
  mode: CompileMode,
): Array<CompilePhaseDefinition & { status: CompilePhaseStatus }> {
  const phases = getCompilePhases(mode);
  const activeId = inferCompilePhaseId(job, mode);
  const activeIndex = phases.findIndex((phase) => phase.id === activeId);

  return phases.map((phase, index) => {
    let status: CompilePhaseStatus = "pending";
    if (job.status === "completed") {
      status = "completed";
    } else if (index < activeIndex) {
      status = "completed";
    } else if (index === activeIndex) {
      status = job.status === "failed" ? "failed" : "active";
    }

    return { ...phase, status };
  });
}

function CompilePhaseCard({
  label,
  description,
  icon: Icon,
  status,
}: CompilePhaseDefinition & { status: CompilePhaseStatus }) {
  const isActive = status === "active";
  const isCompleted = status === "completed";
  const isFailed = status === "failed";

  return (
    <Card
      className={`p-3 transition-all ${
        isActive
          ? "border-primary/30 bg-primary/5"
          : isCompleted
            ? "border-green-500/20 bg-green-500/5"
            : isFailed
              ? "border-destructive/30 bg-destructive/5"
              : "opacity-70"
      }`}
    >
      <div className="flex items-center gap-2">
        {isActive ? (
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
        ) : isCompleted ? (
          <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
        ) : (
          <Icon className={`h-4 w-4 ${isFailed ? "text-destructive" : "text-muted-foreground"}`} />
        )}
        <div className="min-w-0">
          <div className="text-sm font-medium">{label}</div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </div>
      </div>
    </Card>
  );
}

function QuestionCatalog({
  groupedQuestions,
  questionCount,
  activeCompileMode,
  onQuestionSelect,
  compact = false,
}: {
  groupedQuestions: Array<[string, ParsedQuestion[]]>;
  questionCount: number;
  activeCompileMode: CompileMode;
  onQuestionSelect: (question: string) => void;
  compact?: boolean;
}) {
  return (
    <Card className="p-6">
      <div className="flex items-center gap-2 mb-1">
        <Sparkles className="h-5 w-5 text-amber-500" />
        <h2 className="text-xl font-serif font-bold">
          {compact ? "Question catalog" : "What this database can answer"}
        </h2>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        FORGE compiled {questionCount} {activeCompileMode === "curated" ? "curated" : "candidate"} questions
        from the schema, joins, and semantic analysis. Click a question to test whether
        the database can answer it through the BSMS pipeline.
      </p>
      <div className={`space-y-5 pr-1 ${compact ? "max-h-[960px] overflow-y-auto" : "max-h-[760px] overflow-y-auto"}`}>
        {groupedQuestions.map(([category, items]) => (
          <div key={category}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                {category}
              </h3>
              <Badge variant="outline">{items.length}</Badge>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {items.map((q) => {
                const T = QT[q.type] || QT.text_search;
                return (
                  <button
                    key={q.id}
                    onClick={() => onQuestionSelect(q.q)}
                    className="rounded-xl border border-border bg-background/60 p-4 text-left transition-all hover:border-primary/40 hover:bg-accent/40"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <T.icon className={`h-4 w-4 flex-shrink-0 ${T.cls}`} />
                        <Badge variant="secondary">{T.label}</Badge>
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          q.u > 0.9
                            ? "border-green-500/40 text-green-700 dark:text-green-400"
                            : q.u > 0.85
                              ? "border-amber-500/40 text-amber-700 dark:text-amber-400"
                              : "text-muted-foreground"
                        }
                      >
                        {(q.u * 100).toFixed(0)}%
                      </Badge>
                    </div>
                    <p className="mt-3 text-sm font-medium leading-6">{q.q}</p>
                    <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                      <code className="truncate">{q.table}</code>
                      <span className="inline-flex items-center gap-1">
                        Ask via BSMS
                        <ChevronRight className="h-3.5 w-3.5" />
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function FORGEExplorer() {
  // Compile form state
  const [databaseUrl, setDatabaseUrl] = useState(EXAMPLE_SQLITE_URL);
  const [compileMode, setCompileMode] = useState<CompileMode>("curated");
  const [activeCompileMode, setActiveCompileMode] = useState<CompileMode>("curated");
  const [compileLoading, setCompileLoading] = useState(false);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [compileJob, setCompileJob] = useState<ForgeCompileJobResponse | null>(null);
  const [compileResult, setCompileResult] = useState<ForgeCompileResponse | null>(null);

  // Explorer state
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [ps, setPs] = useState(-1);
  const [result, setResult] = useState<ForgeBSMSQueryResponse | null>(null);
  const [lineageOpen, setLineageOpen] = useState(false);
  const [tab, setTab] = useState("profile");

  // Derived data from compile result
  const tables = compileResult ? extractTables(compileResult) : [];
  const questions = compileResult ? extractQuestions(compileResult) : [];
  const groupedQuestions = groupQuestions(questions);
  const relationships = compileResult ? extractRelationships(compileResult) : [];
  const capabilityCoverage = compileResult ? extractCapabilityCoverage(compileResult) : [];
  const candidateArchetypes = compileResult ? extractCandidateArchetypes(compileResult) : [];
  const compilePhases = compileJob ? getCompilePhaseStates(compileJob, activeCompileMode) : [];

  // Progress bar animation
  useEffect(() => {
    if (!loading) { setProgress(0); return; }
    setProgress(8);
    const t = setInterval(() => setProgress(p => Math.min(96, p + (p < 60 ? 4 : p < 85 ? 2 : 0.5))), 220);
    return () => clearInterval(t);
  }, [loading]);

  async function runCompile() {
    if (!databaseUrl.trim()) {
      setCompileError("Database URL is required.");
      return;
    }
    setCompileLoading(true);
    setCompileError(null);
    setCompileJob(null);
    setCompileResult(null);
    setActiveCompileMode(compileMode);
    try {
      const payload: ForgeCompileRequest = {
        database_url: databaseUrl.trim(),
        sample_rows_per_table: 50,
        generate_bundle: true,
        require_llm_refinement: true,
        max_generated_questions: COMPILE_MODES[compileMode].maxQuestions,
      };
      const response = await forgeCompile(payload, {
        onProgress: setCompileJob,
      });
      setCompileResult(response);
      setTab("profile");
    } catch (err) {
      setCompileError(err instanceof Error ? err.message : "FORGE compile failed.");
    } finally {
      setCompileLoading(false);
    }
  }

  async function runQuery(q?: string) {
    const text = q || query;
    if (!text.trim() || !compileResult) return;
    setQuery(text);
    setTab("results");
    setLoading(true);
    setResult(null);
    setPs(0);
    setLineageOpen(false);

    // Animate pipeline stages while the API call runs
    const t1 = setTimeout(() => setPs(1), 400);
    const t2 = setTimeout(() => setPs(2), 800);
    const t3 = setTimeout(() => setPs(3), 1200);

    try {
      const response = await forgeBSMSQuery({
        query: text,
        question_map: compileResult.question_map,
        database_url: databaseUrl.trim(),
        bsms_pipeline: compileResult.bsms_pipeline,
        authority_pack: compileResult.authority_pack,
        limit: 25,
        require_llm: true,
        persist_lineage: true,
      });
      setPs(4);
      setResult(response);
    } catch (err) {
      setPs(4);
      setResult({
        status: "error",
        pipeline: "B-S-M-S",
        bouncer: { status: "error" },
        answer: err instanceof Error ? err.message : "BSMS query failed.",
        lineage: {},
      });
    } finally {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">

      {/* ── HERO + COMPILE FORM ── */}
      <section className="rounded-3xl border border-border bg-card px-6 py-8 shadow-sm">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">
              BoundState FORGE
            </p>
            <h1 className="text-4xl font-serif font-bold tracking-tight">
              Explore What A Database Can Answer
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              Compile a database, inspect the answer surface FORGE discovered, and run grounded
              BSMS queries against that compiled understanding. This is the primary exploration
              workflow for engineers and analysts.
            </p>
          </div>
          {compileResult && (
            <Badge variant="outline">{compileResult.summary.database_url_redacted}</Badge>
          )}
        </div>

        {/* Compile controls */}
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="mb-2 block text-sm font-medium">Database URL</label>
            <Input
              value={databaseUrl}
              onChange={(e) => setDatabaseUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runCompile()}
              placeholder="sqlite:////path/to/db.sqlite or postgresql://..."
            />
          </div>
          <div className="min-w-[290px]">
            <label className="mb-2 block text-sm font-medium">Compile Mode</label>
            <div className="grid grid-cols-2 gap-2">
              {(Object.entries(COMPILE_MODES) as Array<[CompileMode, typeof COMPILE_MODES[CompileMode]]>).map(([mode, config]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setCompileMode(mode)}
                  className={`rounded-md border px-3 py-2 text-left transition-colors ${
                    compileMode === mode
                      ? "border-primary bg-primary/5 text-foreground"
                      : "border-border bg-background text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <div className="text-sm font-medium">{config.label}</div>
                  <div className="text-xs">{config.description}</div>
                </button>
              ))}
            </div>
          </div>
          <Button onClick={runCompile} disabled={compileLoading} className="min-w-40 h-10">
            {compileLoading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Compiling
              </>
            ) : (
              <>
                <Database className="mr-2 h-4 w-4" />
                Compile
              </>
            )}
          </Button>
        </div>

        {compileJob && (
          <Card className="mt-4 p-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                  Compile Status
                </p>
                <p className="mt-1 text-sm font-medium">{compileJob.message}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Stage: <code>{compileJob.stage}</code>
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Mode: <code>{COMPILE_MODES[activeCompileMode].label}</code> · Question budget:{" "}
                  <code>{COMPILE_MODES[activeCompileMode].maxQuestions}</code>
                </p>
              </div>
              <Badge variant="outline">{Math.round(compileJob.progress)}%</Badge>
            </div>
            <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all duration-300"
                style={{ width: `${Math.max(0, Math.min(100, compileJob.progress))}%` }}
              />
            </div>
            <div className="mt-4">
              <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Phase Progress
              </p>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {compilePhases.map((phase) => (
                  <CompilePhaseCard key={phase.id} {...phase} />
                ))}
              </div>
            </div>
          </Card>
        )}

        {compileError && (
          <Card className="mt-4 border-destructive/40 p-4">
            <p className="text-sm text-destructive">{compileError}</p>
          </Card>
        )}
      </section>

      {/* ── COMPILED DATA VIEW ── */}
      {compileResult && (
        <div className="space-y-6">
          {/* STAT CARDS */}
          <section className="grid gap-4 md:grid-cols-5">
            {[
              { icon: Database, label: "Tables", value: String(compileResult.summary.table_count) },
              { icon: ScrollText, label: "Columns", value: String(compileResult.summary.column_count) },
              { icon: Network, label: "Relationships", value: String(compileResult.summary.relationship_count) },
              { icon: Zap, label: "Questions", value: String(compileResult.summary.generated_question_count) },
              { icon: GitFork, label: "Latent Joins", value: String(compileResult.summary.latent_relationship_count) },
            ].map(({ icon: I, label, value }) => (
              <Card key={label} className="p-4">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <I className="h-4 w-4" />
                  <span className="text-sm">{label}</span>
                </div>
                <p className="mt-3 text-3xl font-semibold">{value}</p>
              </Card>
            ))}
          </section>

          {/* SEARCH BAR */}
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runQuery()}
                placeholder="Ask anything about this database..."
                className="w-full pl-9 pr-4 h-11 rounded-md border border-input bg-background text-sm outline-none focus:ring-2 focus:ring-ring focus:border-transparent transition-all"
              />
            </div>
            <Button
              onClick={() => runQuery()}
              disabled={loading || !query.trim()}
              className="h-11 px-6"
            >
              {loading ? "Running..." : "Run BSMS"}
            </Button>
          </div>

          {/* TAB STRIP */}
          <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
            {([["profile", "Database Profile"], ["results", "Query Results"]] as const).map(([k, label]) => (
              <button key={k} onClick={() => setTab(k)}
                className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                  tab === k ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                }`}>
                {label}
              </button>
            ))}
          </div>

          {/* ════════ PROFILE TAB ════════ */}
          {tab === "profile" && (
            <div className="space-y-6">

              {/* Tables */}
              <Card className="p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Database className="h-5 w-5 text-primary" />
                  <h2 className="text-xl font-serif font-bold">What's in this database</h2>
                </div>
                <div className="space-y-2">
                  {tables.map((t) => (
                    <div key={t.name} className="flex items-center gap-4 rounded-md border border-border bg-background/50 p-3">
                      <Table2 className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <code className="text-sm font-semibold">{t.name}</code>
                          <Badge variant="outline">{t.rows.toLocaleString()} rows</Badge>
                          <Badge variant="outline">{t.cols} cols</Badge>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>

              <QuestionCatalog
                groupedQuestions={groupedQuestions}
                questionCount={questions.length}
                activeCompileMode={activeCompileMode}
                onQuestionSelect={(question) => {
                  setQuery(question);
                  runQuery(question);
                }}
              />

              {capabilityCoverage.length > 0 && (
                <Card className="p-6">
                  <div className="flex items-center gap-2 mb-1">
                    <Activity className="h-5 w-5 text-emerald-500" />
                    <h2 className="text-xl font-serif font-bold">Capability coverage</h2>
                  </div>
                  <p className="text-sm text-muted-foreground mb-4">
                    FORGE inferred what kind of answer surface this database supports and graded each
                    capability family before selecting the curated questions.
                  </p>
                  <div className="grid gap-3 md:grid-cols-2">
                    {capabilityCoverage.map((entry) => (
                      <Card key={entry.capability_id} className="p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-semibold">{entry.label}</div>
                          <Badge
                            variant="outline"
                            className={
                              entry.support_level === "strong"
                                ? "border-green-500/40 text-green-700 dark:text-green-400"
                                : entry.support_level === "partial"
                                  ? "border-amber-500/40 text-amber-700 dark:text-amber-400"
                                  : "text-muted-foreground"
                            }
                          >
                            {entry.support_level}
                          </Badge>
                        </div>
                        <p className="mt-2 text-xs text-muted-foreground">{entry.rationale}</p>
                      </Card>
                    ))}
                  </div>
                </Card>
              )}

              {/* Relationships */}
              {relationships.length > 0 && (
                <Card className="p-6">
                  <div className="flex items-center gap-2 mb-4">
                    <GitFork className="h-5 w-5 text-violet-500" />
                    <h2 className="text-xl font-serif font-bold">Discovered relationships</h2>
                  </div>
                  <div className="space-y-2 max-h-[400px] overflow-y-auto">
                    {relationships.map((r, i) => (
                      <div key={i} className="flex items-center gap-2 rounded-md bg-background/50 border border-border px-4 py-3 font-mono text-sm">
                        <code className="text-primary">{r.from_table}</code>
                        <span className="text-muted-foreground">.</span>
                        <code className="text-sky-500">{r.from_column}</code>
                        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                        <code className="text-primary">{r.to_table}</code>
                        <span className="text-muted-foreground">.</span>
                        <code className="text-sky-500">{r.to_column}</code>
                        <Badge variant="outline" className="ml-auto">{r.type}</Badge>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {candidateArchetypes.length > 0 && (
                <Card className="p-6">
                  <div className="flex items-center gap-2 mb-1">
                    <Sparkles className="h-5 w-5 text-indigo-500" />
                    <h2 className="text-xl font-serif font-bold">Discovery suggested next</h2>
                  </div>
                  <p className="text-sm text-muted-foreground mb-4">
                    These motif-driven question families were discovered but not promoted into the
                    current curated surface automatically.
                  </p>
                  <div className="space-y-2">
                    {candidateArchetypes.map((entry, index) => (
                      <div key={`${entry.motif_type}-${index}`} className="rounded-md border border-border bg-background/50 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-medium">{entry.proposed_intent}</div>
                          <Badge variant="outline">{Math.round(entry.confidence * 100)}%</Badge>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Motif: <code>{entry.motif_type}</code>
                          {entry.tables_involved.length > 0 ? ` · Tables: ${entry.tables_involved.join(", ")}` : ""}
                        </p>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </div>
          )}

          {/* ════════ RESULTS TAB ════════ */}
          {tab === "results" && (
            <div className="space-y-6">
              <QuestionCatalog
                groupedQuestions={groupedQuestions}
                questionCount={questions.length}
                activeCompileMode={activeCompileMode}
                onQuestionSelect={(question) => {
                  setQuery(question);
                  runQuery(question);
                }}
              />

              {(loading || result) && (
                <Card className={`p-4 ${loading ? "border-primary/30" : ""}`}>
                  {loading && (
                    <div className="mb-3 flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin text-primary" />
                      <p className="text-sm font-medium">BSMS is evaluating evidence...</p>
                    </div>
                  )}
                  {loading && (
                    <div className="mb-4 h-2 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary transition-all duration-200"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  )}
                  <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
                    <PipelineStage icon={Shield} label="B — Bouncer" model="Haiku" active={ps === 0} passed={ps > 0} />
                    <PipelineStage icon={Bot} label="S — Parser" model="Sonnet" active={ps === 1} passed={ps > 1} />
                    <PipelineStage icon={Scale} label="M — Rules" model="Deterministic" active={ps === 2} passed={ps > 2} />
                    <PipelineStage icon={FileText} label="S — Formatter" model="Sonnet" active={ps === 3} passed={ps > 3} />
                  </div>
                </Card>
              )}

              {result && (
                <>
                  <Card className="p-4">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <p className="text-sm text-muted-foreground">Pipeline status</p>
                        <p className="font-semibold">{result.status.toUpperCase()}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm text-muted-foreground">Bouncer</p>
                        <StatusBadge status={String(result.bouncer?.status || "").toUpperCase()} />
                      </div>
                    </div>
                  </Card>

                  {result.parsed_intent && (
                    <Card className="p-4">
                      <div className="mb-3 flex items-center gap-2">
                        <Bot className="h-4 w-4" />
                        <h2 className="font-semibold">Parser (S)</h2>
                      </div>
                      <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                        <div>
                          <p className="text-muted-foreground">Matched Question</p>
                          <p className="text-xs font-semibold">
                            {String(result.parsed_intent.question_text || result.parsed_intent.question_id || "")}
                          </p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Type</p>
                          <p className="font-semibold">{String(result.parsed_intent.question_type || "")}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Table</p>
                          <p className="font-semibold">{String(result.parsed_intent.table || "")}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Confidence</p>
                          <p className="font-semibold">
                            {((Number(result.parsed_intent.confidence) || 0) * 100).toFixed(0)}%
                          </p>
                        </div>
                      </div>
                    </Card>
                  )}

                  {result.rules && (
                    <Card className="p-4">
                      <div className="mb-3 flex items-center gap-2">
                        <Scale className="h-4 w-4" />
                        <h2 className="font-semibold">Deterministic Rules (M)</h2>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={String(result.rules.verdict || "").replace("_", " ")} />
                        {Array.isArray(result.rules.rules_applied) && result.rules.rules_applied.map((r: unknown) => (
                          <Badge key={String(r)} variant="outline">{String(r)}</Badge>
                        ))}
                      </div>
                    </Card>
                  )}

                  <Card className="p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      <h2 className="font-semibold">BSMS Answer</h2>
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                      {result.answer}
                    </p>
                  </Card>

                  <Card className="p-4">
                    <button onClick={() => setLineageOpen(!lineageOpen)} className="flex w-full items-center gap-2 text-left">
                      <Activity className="h-4 w-4 text-amber-500" />
                      <h2 className="font-semibold">Decision Lineage</h2>
                      <Badge variant="secondary">Audit Trail</Badge>
                      {lineageOpen ? (
                        <ChevronDown className="ml-auto h-4 w-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="ml-auto h-4 w-4 text-muted-foreground" />
                      )}
                    </button>
                    {lineageOpen && (
                      <div className="mt-4 space-y-2">
                        {Object.entries(result.lineage || {}).map(([k, v]) => (
                          <div key={k} className="flex gap-3 text-sm">
                            <span className="min-w-[140px] shrink-0 text-xs font-medium text-muted-foreground">{k}</span>
                            <code className="break-all rounded bg-muted px-2 py-1 text-xs font-mono">
                              {String(v)}
                            </code>
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>
                </>
              )}

              {!loading && !result && (
                <Card className="p-12 text-center">
                  <Database className="mx-auto mb-4 h-12 w-12 text-muted-foreground/30" />
                  <h3 className="mb-2 text-lg font-bold">Point. Ask. Get evidence.</h3>
                  <p className="mx-auto max-w-md text-sm leading-relaxed text-muted-foreground">
                    Select a question from the Database Profile or type your own.
                    Every answer includes the executed query, rules applied, and full decision lineage.
                  </p>
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      {/* Empty state before compile */}
      {!compileResult && !compileLoading && (
        <Card className="p-12 text-center">
          <Database className="h-16 w-16 mx-auto text-muted-foreground/20 mb-6" />
          <h3 className="text-xl font-serif font-bold mb-3">Compile a database, then explore it</h3>
          <p className="text-sm text-muted-foreground max-w-lg mx-auto leading-relaxed">
            Enter a SQLAlchemy database URL above and click Compile. FORGE will build a question map,
            discover relationships, and then let you inspect and interrogate that compiled answer surface
            through the BSMS pipeline.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">Schema Introspection</Badge>
            <Badge variant="outline">Semantic Inference</Badge>
            <Badge variant="outline">Relationship Discovery</Badge>
            <Badge variant="outline">Question Generation</Badge>
            <Badge variant="outline">Authority Pack</Badge>
            <Badge variant="outline">BSMS Pipeline</Badge>
          </div>
        </Card>
      )}
    </div>
  );
}
