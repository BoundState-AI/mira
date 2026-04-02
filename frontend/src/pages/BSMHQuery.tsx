import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Shield, Search, Bot, Scale, FileText, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  ModuleAvailabilityGate,
  TemporarilyUnavailableNotice,
} from "@/components/TemporarilyUnavailableModule";
import { isUnavailableModuleId } from "@/lib/moduleAvailability";

import {
  bsmhQuery,
  miraQuery,
  type BSMHQueryRequest,
  type BSMHQueryResponse,
} from "@/lib/api";

const EXAMPLES = [
  "Compare 304L and 316L corrosion test coverage in MAPTIS.",
  "What MAPTIS test evidence exists for Inconel 625 bar versus cast forms?",
  "Does Inconel 718 have different ratings in aged versus as-cast condition?",
  "What fluid compatibility test data exists for CRES 304L in MAPTIS?",
  "Which materials have the strongest combined MUA precedent and test coverage for high-strength hardware?",
];

function verdictVariant(verdict: string): "default" | "secondary" | "destructive" | "outline" {
  if (verdict === "COMPATIBLE") return "default";
  if (verdict === "INCOMPATIBLE") return "destructive";
  if (verdict === "CONDITIONAL") return "secondary";
  return "outline";
}

interface BSMHQueryProps {
  endpoint?: "bsmh" | "query";
  title?: string;
  runLabel?: string;
  subtitle?: string;
  description?: string;
  showPipelineBlurb?: boolean;
}

export default function BSMHQuery({
  endpoint = "bsmh",
  title,
  runLabel,
  subtitle,
  description,
  showPipelineBlurb = true,
}: BSMHQueryProps) {
  const { t } = useTranslation(["common", "query"]);
  const localizedExamples = t("examples", {
    ns: "query",
    returnObjects: true,
    defaultValue: EXAMPLES,
  }) as string[];
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingProgress, setLoadingProgress] = useState(0);
  const [result, setResult] = useState<BSMHQueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const effectiveTitle = title ?? t("pageTitle", { ns: "query", defaultValue: "MIRA Query" });
  const effectiveSubtitle = subtitle ?? t("pageSubtitle", { ns: "query", defaultValue: "Decision Lineage Pipeline" });
  const effectiveDescription = description ?? t("pageDescription", {
    ns: "query",
    defaultValue: "Evidence-first queries with transparent confidence scoring and NASA-compliant audit trails",
  });
  const isTemporarilyUnavailable = endpoint === "query" && isUnavailableModuleId("query");

  useEffect(() => {
    if (!loading) {
      setLoadingProgress(0);
      return;
    }

    setLoadingProgress(8);
    const timer = window.setInterval(() => {
      setLoadingProgress((prev) => {
        const step = prev < 60 ? 4 : prev < 85 ? 2 : 0.5;
        return Math.min(96, prev + step);
      });
    }, 220);

    return () => window.clearInterval(timer);
  }, [loading]);

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const payload: BSMHQueryRequest = {
        query: query.trim(),
        answer_mode: "sonnet",
      };
      const data = endpoint === "query"
        ? await miraQuery(payload)
        : await bsmhQuery(payload);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-full bg-background">
      {isTemporarilyUnavailable ? (
        <div className="mx-auto max-w-5xl px-6 pt-6">
          <TemporarilyUnavailableNotice moduleName="MIRA Query" />
        </div>
      ) : null}
      <ModuleAvailabilityGate unavailable={isTemporarilyUnavailable}>
      <div className="bg-card border-b border-border">
        <div className="max-w-5xl mx-auto px-6 py-10">
          <h1 className="text-4xl font-serif font-bold mb-2 flex items-center gap-3">
            <Shield className="h-8 w-8 text-primary" />
            {effectiveTitle}
          </h1>
          {effectiveSubtitle && <p className="text-lg text-muted-foreground mb-1">{effectiveSubtitle}</p>}
          {effectiveDescription && <p className="text-sm text-muted-foreground mb-1">{effectiveDescription}</p>}
          {showPipelineBlurb && (
            <p className="text-sm text-muted-foreground mb-6">
              {t("pipelineLabel", { ns: "query", defaultValue: "Pipeline:" })}{" "}
              <code>{t("pipelineFlow", {
                ns: "query",
                defaultValue: "Bouncer → Sonnet → MIRA Rules → Sonnet",
              })}</code>
            </p>
          )}

          <div className="flex gap-2 mb-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && run()}
                placeholder={t("placeholder", { ns: "query", defaultValue: "Ask an M&P question..." })}
                className="pl-9 h-11"
              />
            </div>
            <Button onClick={run} disabled={loading || !query.trim()} className="h-11 px-6">
              {loading
                ? t("searching", { ns: "query", defaultValue: "Running..." })
                : (runLabel ?? t("buttons.search", { ns: "common", defaultValue: endpoint === "query" ? "Run Query" : "Run BSMH" }))}
            </Button>
          </div>

          <div className="flex flex-wrap gap-2">
            {localizedExamples.map((example) => (
              <Button
                key={example}
                variant="ghost"
                size="sm"
                className="text-xs"
                onClick={() => setQuery(example)}
              >
                {example}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-4">
        {loading && (
          <Card className="p-4 border-primary/30">
            <div className="flex items-center gap-2 mb-3">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              <p className="text-sm font-medium">
                {t("status.processing", { ns: "common", defaultValue: "MIRA is evaluating evidence..." })}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="h-9 w-1 rounded-full bg-muted overflow-hidden">
                <div
                  className="w-full bg-primary transition-all duration-200"
                  style={{
                    height: `${Math.max(8, loadingProgress)}%`,
                    marginTop: `${100 - Math.max(8, loadingProgress)}%`,
                  }}
                />
              </div>

              <div className="flex-1">
                <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full bg-primary transition-all duration-200"
                    style={{ width: `${loadingProgress}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("pipelineFlow", {
                    ns: "query",
                    defaultValue: "Bouncer → Sonnet → MIRA Rules → Sonnet",
                  })}
                </p>
              </div>
            </div>
          </Card>
        )}

        {error && (
          <Card className="p-4 border-destructive/40">
            <p className="text-sm text-destructive">{error}</p>
          </Card>
        )}

        {result && (
          <>
            <Card className="p-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">
                    {t("labels.pipelineStatus", { ns: "query", defaultValue: "Pipeline status" })}
                  </p>
                  <p className="font-semibold">{result.status.toUpperCase()}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">
                    {t("labels.bouncer", { ns: "query", defaultValue: "Bouncer" })}
                  </p>
                  <Badge variant={result.bouncer.status === "accepted" ? "default" : "destructive"}>
                    {result.bouncer.status.toUpperCase()}
                  </Badge>
                </div>
              </div>
              {result.bouncer.rejection_reason && (
                <p className="mt-3 text-sm text-muted-foreground">{result.bouncer.rejection_reason}</p>
              )}
            </Card>

            <Card className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <FileText className="h-4 w-4" />
                <h2 className="font-semibold">
                  {t("sections.sonnetAnswer", { ns: "query", defaultValue: "Sonnet Answer" })}
                </h2>
              </div>
              <div className="whitespace-pre-wrap text-sm leading-6">
                {result.answer_sonnet ?? result.answer}
              </div>
            </Card>

            {result.rules && (
              <Card className="p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Scale className="h-4 w-4" />
                  <h2 className="font-semibold">
                    {t("sections.deterministicRules", {
                      ns: "query",
                      defaultValue: "Deterministic Rules (M)",
                    })}
                  </h2>
                </div>
                <div className="flex flex-wrap items-center gap-2 mb-3">
                  <Badge variant={verdictVariant(result.rules.verdict)}>
                    {result.rules.verdict}
                  </Badge>
                  <Badge variant="outline">
                    {t("labels.confidence", { ns: "query", defaultValue: "Confidence" })}{" "}
                    {(result.rules.confidence * 100).toFixed(0)}%
                  </Badge>
                  <Badge variant="outline">
                    {t("labels.scope", { ns: "query", defaultValue: "Scope" })}{" "}
                    {result.rules.aggregation_scope}
                  </Badge>
                  <Badge variant="outline">
                    {t("labels.primary", { ns: "query", defaultValue: "Primary" })}{" "}
                    {result.rules.primary_material_count}
                  </Badge>
                  <Badge variant="outline">
                    {t("labels.associated", { ns: "query", defaultValue: "Associated" })}{" "}
                    {result.rules.associated_material_count}
                  </Badge>
                  {result.rules.bok_context_used && (
                    <Badge variant="outline">
                      {t("labels.h2Bok", { ns: "query", defaultValue: "H2 BoK" })}{" "}
                      {result.rules.bok_evidence_count}
                    </Badge>
                  )}
                  {result.rules.standards_category && (
                    <Badge variant="outline">
                      {t("labels.category", { ns: "query", defaultValue: "Category" })}{" "}
                      {result.rules.standards_category}
                    </Badge>
                  )}
                </div>
                <div className="space-y-2">
                  {result.rules.materials.map((material) => (
                    <div key={`${material.material_key}-${material.material_name}`} className="border rounded p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-medium text-sm">{material.material_name}</p>
                        <Badge variant={verdictVariant(material.verdict)}>{material.verdict}</Badge>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        {t("labels.score", { ns: "query", defaultValue: "Score" })}{" "}
                        {(material.score * 100).toFixed(0)}%
                      </p>
                      {material.warnings.length > 0 && (
                        <ul className="mt-2 text-xs text-muted-foreground list-disc pl-4 space-y-1">
                          {material.warnings.slice(0, 2).map((warning) => (
                            <li key={warning}>{warning}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            )}

            <Card className="p-4">
              <div className="flex items-center gap-2 mb-3">
                <Bot className="h-4 w-4" />
                <h2 className="font-semibold">
                  {t("sections.sonnetDbLayer", {
                    ns: "query",
                    defaultValue: "Sonnet + DB Layer (S)",
                  })}
                </h2>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
                <div>
                  <p className="text-muted-foreground">
                    {t("labels.materials", { ns: "query", defaultValue: "Materials" })}
                  </p>
                  <p className="font-semibold">{result.materials.length}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">
                    {t("labels.sonnetCalls", { ns: "query", defaultValue: "Sonnet Calls" })}
                  </p>
                  <p className="font-semibold">
                    {result.sonnet_calls_used ?? Number(result.sonnet_metadata?.sonnet_calls_used ?? 0)}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">
                    {t("labels.searchSource", { ns: "query", defaultValue: "Search Source" })}
                  </p>
                  <p className="font-semibold">{String(result.sonnet_metadata?.search_source ?? "n/a")}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">
                    {t("labels.v4Gate", { ns: "query", defaultValue: "v4 Gate" })}
                  </p>
                  <p className="font-semibold">{result.v4_gate_action ?? "n/a"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">
                    {t("labels.v4Confidence", { ns: "query", defaultValue: "v4 Confidence" })}
                  </p>
                  <p className="font-semibold">
                    {result.v4_confidence_score != null
                      ? `${(result.v4_confidence_score * 100).toFixed(0)}%`
                      : "n/a"}
                  </p>
                </div>
              </div>
            </Card>
          </>
        )}
      </div>
      </ModuleAvailabilityGate>
    </div>
  );
}
