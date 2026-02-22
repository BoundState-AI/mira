import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Search,
  Sparkles,
  ChevronDown,
  ChevronUp,
  FileText,
  Eye,
  List,
  Table as TableIcon,
  FlaskConical,
  Shield,
  ShieldCheck,
  Award,
  CalendarDays,
  MessageSquare,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { PageHelp } from "@/components/PageHelp";
import helpContent from "@/config/helpContent";

import { ConfidenceBadge } from "@/components/v4/ConfidenceBadge";
import { DirtyDataBanner } from "@/components/v4/DirtyDataBanner";
import { HeritageVetoModal } from "@/components/v4/HeritageVetoModal";
import { IntentDisagreementIndicator } from "@/components/v4/IntentDisagreementIndicator";
import { DecisionLineageDrawer } from "@/components/v4/DecisionLineageDrawer";
import {
  v4Query,
  type V4QueryRequest,
  type V4QueryResponse,
  type V4HeritageOverrideResponse,
} from "@/lib/api";

const exampleQueries = [
  "Is Inconel 718 compatible with LOX at 500 psi?",
  "Show me stainless steels rated for oxygen service",
  "Compare 316L vs Monel 400 in hydrogen at -200C",
  "PTFE compatibility in 3000 psi GOX cryogenic service",
];

export default function MiraV4Query() {
  const { t } = useTranslation("query");
  const localizedExampleQueries = t("exampleQueries", {
    returnObjects: true,
    defaultValue: exampleQueries,
  }) as string[];
  // Search state
  const [query, setQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [result, setResult] = useState<V4QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // UI state
  const [activeTab, setActiveTab] = useState("cards");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showLineageDrawer, setShowLineageDrawer] = useState(false);
  const [showVetoModal, setShowVetoModal] = useState(false);
  const [overrideComplete, setOverrideComplete] = useState(false);
  const [showFullMaterialPool, setShowFullMaterialPool] = useState(false);

  // Advanced environment fields
  const [temperatureC, setTemperatureC] = useState("");
  const [pressureKpa, setPressureKpa] = useState("");
  const [o2Pct, setO2Pct] = useState("");
  const [fluidMedium, setFluidMedium] = useState("");
  const [durationHr, setDurationHr] = useState("");
  const [cycles, setCycles] = useState("");

  const handleSearch = async () => {
    if (!query.trim()) return;

    setIsSearching(true);
    setError(null);
    setResult(null);
    setOverrideComplete(false);

    try {
      const req: V4QueryRequest = { query: query.trim() };

      // Add advanced environment fields if provided
      if (temperatureC) req.temperature_c = parseFloat(temperatureC);
      if (pressureKpa) req.pressure_kpa = parseFloat(pressureKpa);
      if (o2Pct) req.o2_pct = parseFloat(o2Pct);
      if (fluidMedium.trim()) req.fluid_medium = fluidMedium.trim();
      if (durationHr) req.duration_hr = parseFloat(durationHr);
      if (cycles) req.cycles = parseInt(cycles);

      const data = await v4Query(req);
      setResult(data);
      setShowFullMaterialPool(false);

      // Check if heritage veto requires acknowledgment
      if (
        data.heritage_veto?.requires_acknowledgment &&
        data.heritage_veto?.vetoed &&
        !overrideComplete
      ) {
        setShowVetoModal(true);
      }
    } catch (err) {
      console.error("V4 query error:", err);
      setError(
        err instanceof Error
          ? err.message
          : "Query failed. Make sure the backend is running."
      );
    } finally {
      setIsSearching(false);
    }
  };

  const handleOverrideComplete = (_override: V4HeritageOverrideResponse) => {
    setShowVetoModal(false);
    setOverrideComplete(true);
  };

  const handleVetoCancel = () => {
    setShowVetoModal(false);
    setResult(null);
  };

  // Should we show results? Not if veto is blocking
  const showResults =
    result &&
    (!result.heritage_veto?.requires_acknowledgment ||
      overrideComplete ||
      !result.heritage_veto?.vetoed);

  // Should we block due to dirty data REFUSE tier?
  const dirtyRefuse = result?.dirty_data?.tier === "refuse";
  const focusedMaterials = result?.materials ?? [];
  const fullMaterials =
    result?.all_materials && result.all_materials.length > 0
      ? result.all_materials
      : focusedMaterials;
  const hasAdditionalPool =
    (result?.materials_focus_applied ?? false) &&
    fullMaterials.length > focusedMaterials.length;
  const displayedMaterials = showFullMaterialPool
    ? fullMaterials
    : focusedMaterials;
  const displayedMaterialCount = displayedMaterials.length;

  return (
    <div className="min-h-full bg-background">
      {/* Hero search area */}
      <div className="bg-card border-b border-border">
        <div className="max-w-4xl mx-auto px-6 py-12">
          <div className="mb-8">
            <h1 className="text-4xl font-serif font-bold mb-1 text-balance flex items-center gap-3">
              {t("pageTitle", { defaultValue: "MIRA Query" })}
              {helpContent.query && <PageHelp content={helpContent.query} />}
            </h1>
            <p className="text-lg text-muted-foreground mb-1">
              {t("pageSubtitle", { defaultValue: "Decision Lineage Pipeline" })}
            </p>
            <p className="text-sm text-muted-foreground">
              {t("pageDescription", {
                defaultValue:
                  "Evidence-first queries with transparent confidence scoring and NASA-compliant audit trails",
              })}
            </p>
          </div>

          {/* Query input */}
          <div className="flex gap-2 mb-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder={t("placeholder", {
                  defaultValue: "Ask about material compatibility, properties, or safety...",
                })}
                className="pl-10 h-12 text-base"
              />
            </div>
            <Button
              onClick={handleSearch}
              disabled={isSearching || !query.trim()}
              className="h-12 px-6"
            >
              {isSearching
                ? t("searching", { defaultValue: "Analyzing..." })
                : t("search", { defaultValue: "Search" })}
            </Button>
          </div>

          {/* Advanced environment fields */}
          <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="mb-3 text-xs gap-1">
                <Sparkles className="h-3.5 w-3.5" />
                {t("advancedEnvironment", { defaultValue: "Advanced Environment" })}
                {showAdvanced ? (
                  <ChevronUp className="h-3 w-3" />
                ) : (
                  <ChevronDown className="h-3 w-3" />
                )}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <Card className="p-4 mb-3">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <Label className="text-xs">
                      {t("environment.temperature", { defaultValue: "Temperature (C)" })}
                    </Label>
                    <Input
                      type="number"
                      value={temperatureC}
                      onChange={(e) => setTemperatureC(e.target.value)}
                      placeholder="-196"
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">
                      {t("environment.pressure", { defaultValue: "Pressure (kPa)" })}
                    </Label>
                    <Input
                      type="number"
                      value={pressureKpa}
                      onChange={(e) => setPressureKpa(e.target.value)}
                      placeholder="20684"
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">
                      {t("environment.o2", { defaultValue: "O2 %" })}
                    </Label>
                    <Input
                      type="number"
                      value={o2Pct}
                      onChange={(e) => setO2Pct(e.target.value)}
                      placeholder="99.5"
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">
                      {t("environment.fluid", { defaultValue: "Fluid Medium" })}
                    </Label>
                    <Input
                      value={fluidMedium}
                      onChange={(e) => setFluidMedium(e.target.value)}
                      placeholder="LOX, GOX, LH2..."
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">
                      {t("environment.duration", { defaultValue: "Duration (hrs)" })}
                    </Label>
                    <Input
                      type="number"
                      value={durationHr}
                      onChange={(e) => setDurationHr(e.target.value)}
                      placeholder="1000"
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">
                      {t("environment.cycles", { defaultValue: "Cycles" })}
                    </Label>
                    <Input
                      type="number"
                      value={cycles}
                      onChange={(e) => setCycles(e.target.value)}
                      placeholder="100"
                      className="mt-1"
                    />
                  </div>
                </div>
              </Card>
            </CollapsibleContent>
          </Collapsible>

          {/* Example queries */}
          <div className="flex flex-wrap gap-2">
            {localizedExampleQueries.map((example, i) => (
              <Button
                key={i}
                variant="ghost"
                size="sm"
                onClick={() => setQuery(example)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                {example}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {/* Results area */}
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Error */}
        {error && (
          <Card className="p-6 border-red-200 bg-red-50 mb-4">
            <p className="text-red-700 text-sm">{error}</p>
          </Card>
        )}

        {/* Loading */}
        {isSearching && (
          <div className="space-y-4">
            {[1, 2].map((i) => (
              <Card key={i} className="p-6 animate-pulse">
                <div className="h-6 bg-muted rounded w-1/3 mb-4" />
                <div className="h-4 bg-muted rounded w-2/3 mb-3" />
                <div className="flex gap-2">
                  <div className="h-6 bg-muted rounded w-20" />
                  <div className="h-6 bg-muted rounded w-20" />
                </div>
              </Card>
            ))}
          </div>
        )}

        {/* No results yet */}
        {!result && !isSearching && !error && (
          <div className="text-center py-16">
            <Search className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-medium mb-2">
              {t("noSearch.title", { defaultValue: "No search yet" })}
            </h3>
            <p className="text-muted-foreground text-sm">
              {t("noSearch.hint", {
                defaultValue: "Try one of the example queries above to get started",
              })}
            </p>
          </div>
        )}

        {/* Result header bar */}
        {result && (
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <ConfidenceBadge
              score={result.confidence.score}
              gate_action={result.confidence.gate_action}
              safety_critical={result.confidence.safety_critical}
              penalty_details={result.confidence.penalty_details}
            />

            {result.intent_disagreement && (
              <IntentDisagreementIndicator
                disagreement={result.intent_disagreement}
              />
            )}

            {result.confidence.safety_critical && (
              <Badge
                variant="outline"
                className="text-xs border-red-300 bg-red-50 text-red-700"
              >
                Safety-Critical
              </Badge>
            )}

            <div className="flex-1" />

            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowLineageDrawer(true)}
              className="gap-1.5"
            >
              <FileText className="h-4 w-4" />
              View Lineage
            </Button>

            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>
                {displayedMaterialCount} materials
                {result.search_source && (
                  <span className="ml-1 opacity-60">
                    via {result.search_source}
                  </span>
                )}
              </span>
              {result.total_test_records > 0 && (
                <span className="flex items-center gap-1">
                  <FlaskConical className="h-3 w-3" />
                  {result.total_test_records} tests
                </span>
              )}
              {result.materials_with_mua > 0 && (
                <span className="flex items-center gap-1">
                  <Award className="h-3 w-3" />
                  {result.materials_with_mua} MUA
                </span>
              )}
              {hasAdditionalPool && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-[11px]"
                  onClick={() => setShowFullMaterialPool((prev) => !prev)}
                >
                  {showFullMaterialPool
                    ? t("buttons.showAnswerEvidence", {
                        count: focusedMaterials.length,
                        defaultValue: `Show answer evidence (${focusedMaterials.length})`,
                      })
                    : t("buttons.showFullPool", {
                        count: fullMaterials.length,
                        defaultValue: `Show full pool (${fullMaterials.length})`,
                      })}
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Material families banner - shows what Sonnet suggested */}
        {result &&
          result.material_families &&
          result.material_families.length > 0 && (
            <div className="flex items-center gap-2 mb-3 text-sm text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5 shrink-0" />
              <span>{t("searchedFor", { defaultValue: "Searched for:" })}</span>
              {result.material_families.map((family, i) => (
                <Badge
                  key={i}
                  variant="secondary"
                  className="text-xs font-normal"
                >
                  {family}
                </Badge>
              ))}
            </div>
          )}

        {/* MIRA Answer — Sonnet's natural language response */}
        {result?.answer && (
          <Card className="p-5 mb-4 border-primary/20 bg-primary/5">
            <div className="flex items-start gap-3">
              <MessageSquare className="h-5 w-5 text-primary shrink-0 mt-0.5" />
              <div className="flex-1 prose prose-sm dark:prose-invert max-w-none">
                {result.answer.split("\n").map((line, i) => {
                  if (!line.trim()) return <br key={i} />;
                  // Bold markers (**text**)
                  const parts = line.split(/(\*\*[^*]+\*\*)/g);
                  return (
                    <p key={i} className="mb-1.5 last:mb-0 text-sm leading-relaxed">
                      {parts.map((part, j) =>
                        part.startsWith("**") && part.endsWith("**") ? (
                          <strong key={j} className="font-semibold text-foreground">
                            {part.slice(2, -2)}
                          </strong>
                        ) : (
                          <span key={j}>{part}</span>
                        )
                      )}
                    </p>
                  );
                })}
              </div>
            </div>
          </Card>
        )}

        {/* Dirty data banner */}
        {result?.dirty_data && result.dirty_data.tier !== "clean" && (
          <DirtyDataBanner
            tier={result.dirty_data.tier}
            dirtyFraction={result.dirty_data.dirty_fraction}
            userMessage={result.dirty_data.user_message}
            totalRecords={result.dirty_data.total_records}
            dirtyRecords={result.dirty_data.dirty_records}
          />
        )}

        {/* Materials list (only if not blocked by veto or dirty data REFUSE) */}
        {showResults && !dirtyRefuse && displayedMaterials.length > 0 && (
          <div className="animate-subtle-fade-in">
            <Tabs
              value={activeTab}
              onValueChange={setActiveTab}
              className="w-full"
            >
              <TabsList className="mb-4">
                <TabsTrigger value="cards" className="gap-2">
                  <List className="h-4 w-4" />
                  {t("results.cards", { defaultValue: "Cards" })}
                </TabsTrigger>
                <TabsTrigger value="table" className="gap-2">
                  <TableIcon className="h-4 w-4" />
                  {t("results.table", { defaultValue: "Table" })}
                </TabsTrigger>
              </TabsList>

              <TabsContent value="cards" className="space-y-4 mt-0">
                {displayedMaterials.map((mat, idx) => {
                  const totalTests = (mat.total_tests as number) || 0;
                  const testCounts = (mat.test_counts as Record<string, number>) || {};
                  const hasMua = mat.has_mua_precedent as boolean;
                  const o2Compat = mat.oxygen_compatible as boolean;
                  const latestYear = mat.latest_test_year as number | null;
                  const nonZeroTests = Object.entries(testCounts).filter(([, v]) => v > 0);

                  return (
                    <Card
                      key={
                        (mat.material_key as string) ||
                        (mat.row_uid as string) ||
                        `mat-${idx}`
                      }
                      className="p-6 hover:border-primary transition-colors"
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <h3 className="text-lg font-serif font-semibold mb-1">
                            {(mat.designation as string) ||
                              (mat.material_designation as string) ||
                              (mat.canonical_name as string) ||
                              `Material ${idx + 1}`}
                          </h3>
                          <p className="text-sm text-muted-foreground font-mono">
                            {(mat.material_code as string) ||
                              (mat.material_key as string) ||
                              "N/A"}
                            {mat.material_type_name && (
                              <span className="ml-2 font-sans text-xs">
                                ({mat.material_type_name as string})
                              </span>
                            )}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {o2Compat && (
                            <Badge className="bg-emerald-100 text-emerald-800 border-emerald-200 text-xs gap-1">
                              <ShieldCheck className="h-3 w-3" />
                              {t("table.o2Compatible", { defaultValue: "O₂ Compatible" })}
                            </Badge>
                          )}
                          {hasMua && (
                            <Badge className="bg-blue-100 text-blue-800 border-blue-200 text-xs gap-1">
                              <Award className="h-3 w-3" />
                              {t("table.mua", { defaultValue: "MUA" })}
                            </Badge>
                          )}
                          {totalTests > 0 && (
                            <Badge variant="outline" className="text-xs gap-1">
                              <FlaskConical className="h-3 w-3" />
                              {totalTests} tests
                            </Badge>
                          )}
                        </div>
                      </div>

                      {/* Test breakdown pills */}
                      {nonZeroTests.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mb-3">
                          {nonZeroTests.map(([type, count]) => (
                            <span
                              key={type}
                              className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-muted text-muted-foreground"
                            >
                              {type}: {count}
                            </span>
                          ))}
                          {latestYear && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-muted text-muted-foreground">
                              <CalendarDays className="h-2.5 w-2.5" />
                              {latestYear}
                            </span>
                          )}
                        </div>
                      )}

                      {/* Temperature range - show both F and C */}
                      {(mat.use_temp_min_f != null || mat.use_temp_max_f != null) && (
                        <p className="text-sm text-muted-foreground mb-3">
                          {t("results.temp", { defaultValue: "Temp" })}: {mat.use_temp_min_c ?? "—"}°C to {mat.use_temp_max_c ?? "—"}°C
                          <span className="ml-2 text-xs opacity-60">
                            ({mat.use_temp_min_f ?? "—"}°F to {mat.use_temp_max_f ?? "—"}°F)
                          </span>
                        </p>
                      )}

                      {totalTests === 0 && (
                        <p className="text-xs text-amber-600 mb-3 flex items-center gap-1">
                          <Shield className="h-3 w-3" />
                          {t("messages.noDirectTestData", {
                            defaultValue: "No direct test data in MAPTIS",
                          })}
                        </p>
                      )}

                      <div className="flex items-center gap-4 text-sm">
                        <Button variant="link" className="h-auto p-0 gap-1">
                          <Eye className="h-3.5 w-3.5" />
                          {t("results.viewDetails", { defaultValue: "View details" })}
                        </Button>
                      </div>
                    </Card>
                  );
                })}
              </TabsContent>

              <TabsContent value="table" className="mt-0">
                <Card className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/50">
                        <th className="text-left px-4 py-2 font-medium">
                          {t("table.materialName", { defaultValue: "Material" })}
                        </th>
                        <th className="text-left px-4 py-2 font-medium">
                          {t("results.code", { defaultValue: "Code" })}
                        </th>
                        <th className="text-left px-4 py-2 font-medium">
                          {t("table.type", { defaultValue: "Type" })}
                        </th>
                        <th className="text-right px-4 py-2 font-medium">
                          {t("table.tests", { defaultValue: "Tests" })}
                        </th>
                        <th className="text-center px-4 py-2 font-medium">
                          O₂
                        </th>
                        <th className="text-center px-4 py-2 font-medium">
                          {t("table.mua", { defaultValue: "MUA" })}
                        </th>
                        <th className="text-right px-4 py-2 font-medium">
                          {t("table.latest", { defaultValue: "Latest" })}
                        </th>
                        <th className="text-right px-4 py-2 font-medium">
                          Temp (°C)
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayedMaterials.map((mat, idx) => {
                        const totalTests = (mat.total_tests as number) || 0;
                        return (
                          <tr
                            key={
                              (mat.material_key as string) || `mat-${idx}`
                            }
                            className="border-b hover:bg-muted/50"
                          >
                            <td className="px-4 py-2 max-w-[300px] truncate">
                              {(mat.designation as string) ||
                                (mat.material_designation as string) ||
                                (mat.canonical_name as string) ||
                                `Material ${idx + 1}`}
                            </td>
                            <td className="px-4 py-2 font-mono text-xs">
                              {(mat.material_code as string) || "N/A"}
                            </td>
                            <td className="px-4 py-2 text-xs">
                              {(mat.material_type_name as string) || "-"}
                            </td>
                            <td className="px-4 py-2 text-right font-mono text-xs">
                              {totalTests > 0 ? (
                                <span className="font-semibold">{totalTests}</span>
                              ) : (
                                <span className="text-muted-foreground">0</span>
                              )}
                            </td>
                            <td className="px-4 py-2 text-center">
                              {mat.oxygen_compatible ? (
                                <ShieldCheck className="h-4 w-4 text-emerald-600 mx-auto" />
                              ) : (
                                <span className="text-muted-foreground">-</span>
                              )}
                            </td>
                            <td className="px-4 py-2 text-center">
                              {mat.has_mua_precedent ? (
                                <Award className="h-4 w-4 text-blue-600 mx-auto" />
                              ) : (
                                <span className="text-muted-foreground">-</span>
                              )}
                            </td>
                            <td className="px-4 py-2 text-right font-mono text-xs">
                              {mat.latest_test_year || "-"}
                            </td>
                            <td className="px-4 py-2 text-right font-mono text-xs">
                              {mat.use_temp_min_c != null || mat.use_temp_max_c != null
                                ? `${mat.use_temp_min_c ?? "—"} to ${mat.use_temp_max_c ?? "—"}`
                                : "-"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </Card>
              </TabsContent>
            </Tabs>
          </div>
        )}

        {/* Empty results */}
        {showResults && !dirtyRefuse && displayedMaterials.length === 0 && (
          <div className="text-center py-12">
            <p className="text-muted-foreground text-sm">
              {t("results.noResults", {
                defaultValue: "No materials found for this query.",
              })}
            </p>
          </div>
        )}
      </div>

      {/* Heritage Veto Modal (BLOCKING) */}
      {result?.heritage_veto && result.heritage_veto.requires_acknowledgment && (
        <HeritageVetoModal
          open={showVetoModal}
          vetoResult={result.heritage_veto}
          materialKey={
            (result.parsed_query?.material_key as string) || "unknown"
          }
          lineageHash={result.query_hash}
          failureEnvironment={
            (result.parsed_query?.environment as Record<string, unknown>) || {}
          }
          queryEnvironment={
            (result.parsed_query?.environment as Record<string, unknown>) || {}
          }
          onOverrideComplete={handleOverrideComplete}
          onCancel={handleVetoCancel}
        />
      )}

      {/* Decision Lineage Drawer */}
      {result && (
        <DecisionLineageDrawer
          open={showLineageDrawer}
          onOpenChange={setShowLineageDrawer}
          lineage={result}
        />
      )}
    </div>
  );
}
