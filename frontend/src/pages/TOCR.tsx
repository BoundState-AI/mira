import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ClipboardCheck, FileSearch, Loader2, Scale, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ModuleChatButton } from "@/components/mira/ModuleChatButton";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  buildChatContextSummary,
  createModuleChatLaunchState,
  registerRouteModuleChatState,
} from "@/lib/mira-chat-context";
import {
  tocrGetGuidance,
  tocrReviewTaskOrders,
  tocrScanTaskOrder,
  type TocrComplianceReport,
  type TocrGuidanceEntry,
  type TocrGuidancePack,
  type TocrReviewResponse,
  type TocrScanResponse,
  type TocrTaskOrder,
} from "@/lib/tocr-api";

type Mode = "scan" | "review";
type ParserHint = "auto" | "atoms" | "docx" | "essca" | "pdf";
type TocrResult = TocrScanResponse | TocrReviewResponse;

const DEFAULT_AGENCY = "NASA";
const DEFAULT_VEHICLE = "ESSCA";
const DEFAULT_PACK = "ESSCA-MSFC";
const DEFAULT_CONTRACT_TYPES = "IDIQ, Task Order";
const DEFAULT_CLAUSES = "FAR 52.232-22";

const SEVERITY_STYLE: Record<string, string> = {
  CRITICAL: "bg-red-50 text-red-700 border-red-200",
  HIGH: "bg-orange-50 text-orange-700 border-orange-200",
  MEDIUM: "bg-amber-50 text-amber-700 border-amber-200",
  LOW: "bg-blue-50 text-blue-700 border-blue-200",
};

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function isScanResult(result: TocrResult): result is TocrScanResponse {
  return result.mode === "scan";
}

function splitCommaSeparated(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function verdictTone(verdict?: string | null): string {
  if (!verdict) return "outline";
  if (verdict === "FATAL") return "destructive";
  if (verdict === "FLAGGED") return "secondary";
  return "default";
}

export default function TOCR() {
  const [mode, setMode] = useState<Mode>("scan");
  const [guidancePack, setGuidancePack] = useState<TocrGuidancePack | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TocrResult | null>(null);

  const [scanFile, setScanFile] = useState<File | null>(null);
  const [priorFile, setPriorFile] = useState<File | null>(null);
  const [proposedFile, setProposedFile] = useState<File | null>(null);
  const [scanParserHint, setScanParserHint] = useState<ParserHint>("auto");
  const [priorParserHint, setPriorParserHint] = useState<ParserHint>("auto");
  const [proposedParserHint, setProposedParserHint] = useState<ParserHint>("auto");

  const [agency, setAgency] = useState(DEFAULT_AGENCY);
  const [center, setCenter] = useState("");
  const [vehicle, setVehicle] = useState(DEFAULT_VEHICLE);
  const [localPolicyPack, setLocalPolicyPack] = useState(DEFAULT_PACK);
  const [contractTypes, setContractTypes] = useState(DEFAULT_CONTRACT_TYPES);
  const [clausesPresent, setClausesPresent] = useState(DEFAULT_CLAUSES);
  const [revisionStatus, setRevisionStatus] = useState("");
  const [useSonnet, setUseSonnet] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const nextGuidance = await tocrGetGuidance();
        if (!cancelled) {
          setGuidancePack(nextGuidance);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load TOCR guidance.");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const report: TocrComplianceReport | null = result?.report ?? null;
  const findings = report?.findings ?? [];
  const remediationSteps = report?.remediation_plan?.steps ?? [];
  const parserSummary = useMemo(() => {
    if (!result) return [];
    if (isScanResult(result)) {
      return [
        `${result.parsed_task_order.task_order_number} (${result.parsed_task_order.revision_number})`,
        `${result.parser_selected} parser`,
      ];
    }
    return [
      `Prior: ${result.prior_task_order.task_order_number} (${result.prior_task_order.revision_number})`,
      `Proposed: ${result.proposed_task_order.task_order_number} (${result.proposed_task_order.revision_number})`,
      `Parsers: ${result.prior_parser_selected} -> ${result.proposed_parser_selected}`,
    ];
  }, [result]);
  const tocrChatLaunchState = useMemo(
    () =>
      createModuleChatLaunchState({
        scopeKey: report?.report_id ? `tocr:${report.report_id}` : "tocr",
        moduleLabel: "TOCR Review",
        moduleContext: {
          module: "tocr",
          mode,
          agency: agency.trim() || undefined,
          center: center.trim() || undefined,
          vehicle: vehicle.trim() || undefined,
          policy_pack: localPolicyPack.trim() || undefined,
          revision_status_override: revisionStatus || undefined,
          use_sonnet: useSonnet,
          parser_summary: parserSummary.join(" | ") || undefined,
          has_result: Boolean(report),
          verdict: report?.score?.verdict,
          raw_score: report?.score?.raw_score,
          findings_count: findings.length,
          remediation_count: remediationSteps.length,
          rules_fired: report?.rules_fired,
          active_rule_ids: findings.map((finding) => finding.rule_id),
        },
        originPath: "/tocr",
        originTitle: "TOCR Review",
        description: "Ground the chat in the active TOCR mode, compliance report, and rule guidance.",
        starterPrompts: [
          "What should I do next in this TOCR review?",
          "What do the current findings actually mean?",
          "Should this be a standalone scan or a revision review?",
        ],
        contextSummary: buildChatContextSummary([
          { label: "Mode", value: mode },
          { label: "Agency", value: agency.trim() || null },
          { label: "Vehicle", value: vehicle.trim() || null },
          { label: "Verdict", value: report?.score?.verdict || null },
          { label: "Findings", value: findings.length || null },
          { label: "Rules", value: report?.rules_fired ?? null },
        ]),
      }),
    [
      agency,
      center,
      findings,
      localPolicyPack,
      mode,
      parserSummary,
      remediationSteps.length,
      report,
      revisionStatus,
      useSonnet,
      vehicle,
    ],
  );

  useEffect(() => {
    registerRouteModuleChatState("/tocr", tocrChatLaunchState);
  }, [tocrChatLaunchState]);

  const runAnalysis = async () => {
    setError(null);
    setResult(null);

    if (mode === "scan" && !scanFile) {
      setError("Select one task order file for standalone scan mode.");
      return;
    }

    if (mode === "review" && (!priorFile || !proposedFile)) {
      setError("Select both prior and proposed task order files for review mode.");
      return;
    }

    setLoading(true);
    try {
      const sharedConfig = {
        agency: agency.trim() || DEFAULT_AGENCY,
        center: center.trim() || undefined,
        vehicle: vehicle.trim() || undefined,
        localPolicyPack: localPolicyPack.trim() || undefined,
        contractTypes: splitCommaSeparated(contractTypes),
        clausesPresent: splitCommaSeparated(clausesPresent),
        revisionStatus: revisionStatus || undefined,
        useSonnet,
      };

      const nextResult =
        mode === "scan"
          ? await tocrScanTaskOrder({
              ...sharedConfig,
              sourceFile: scanFile as File,
              parserHint: scanParserHint,
            })
          : await tocrReviewTaskOrders({
              ...sharedConfig,
              priorFile: priorFile as File,
              proposedFile: proposedFile as File,
              priorParserHint,
              proposedParserHint,
            });

      setResult(nextResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "TOCR analysis failed.");
    } finally {
      setLoading(false);
    }
  };

  const renderTaskOrderCard = (title: string, taskOrder: TocrTaskOrder) => (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">{title}</p>
          <h3 className="mt-2 text-xl font-semibold">{taskOrder.task_order_number}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{taskOrder.revision_number} · {taskOrder.source_format}</p>
        </div>
        <Badge variant="outline">{taskOrder.parser_confidence}</Badge>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">{taskOrder.title || taskOrder.task_order_description || "No title extracted."}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Sub-tasks</p>
          <p className="mt-1 text-2xl font-semibold">{taskOrder.sub_tasks.length}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Funding rows</p>
          <p className="mt-1 text-2xl font-semibold">{taskOrder.funding_table.length}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Summary chars</p>
          <p className="mt-1 text-2xl font-semibold">{taskOrder.summary_of_changes.length}</p>
        </div>
      </div>
    </Card>
  );

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-border bg-card px-6 py-8 shadow-sm">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">
              SENTINEL-TOCR
            </p>
            <h1 className="text-4xl font-serif font-bold tracking-tight">Task Order Compliance Review</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              Review one task order in isolation or compare prior versus proposed revisions. TOCR flags undisclosed
              scope, funding gaps, QMS misses, and other contract-review issues, then produces plain-English
              remediation steps for the task lead and contracting team.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <ModuleChatButton launchState={tocrChatLaunchState} />
            <Badge variant="outline">Protected</Badge>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1.1fr,0.9fr]">
          <Card className="p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">Workflow</p>
            <Tabs value={mode} onValueChange={(value) => setMode(value as Mode)} className="mt-3">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="scan">Standalone Scan</TabsTrigger>
                <TabsTrigger value="review">Revision Review</TabsTrigger>
              </TabsList>
              <TabsContent value="scan" className="mt-4 space-y-4">
                <div>
                  <label className="mb-2 block text-sm font-medium">Task order file</label>
                  <Input type="file" accept=".json,.docx,.docm,.pdf" onChange={(event) => setScanFile(event.target.files?.[0] ?? null)} />
                  <p className="mt-2 text-xs text-muted-foreground">
                    Upload native ATOMS JSON, structured DOCX, ESSCA DOCX, or extracted PDF.
                  </p>
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium">Parser hint</label>
                  <select
                    value={scanParserHint}
                    onChange={(event) => setScanParserHint(event.target.value as ParserHint)}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="auto">Auto-detect</option>
                    <option value="atoms">ATOMS JSON</option>
                    <option value="docx">Generic DOCX</option>
                    <option value="essca">ESSCA DOCX</option>
                    <option value="pdf">PDF</option>
                  </select>
                </div>
              </TabsContent>
              <TabsContent value="review" className="mt-4 space-y-4">
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium">Prior revision</label>
                    <Input type="file" accept=".json,.docx,.docm,.pdf" onChange={(event) => setPriorFile(event.target.files?.[0] ?? null)} />
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium">Proposed revision</label>
                    <Input type="file" accept=".json,.docx,.docm,.pdf" onChange={(event) => setProposedFile(event.target.files?.[0] ?? null)} />
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium">Prior parser hint</label>
                    <select
                      value={priorParserHint}
                      onChange={(event) => setPriorParserHint(event.target.value as ParserHint)}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      <option value="auto">Auto-detect</option>
                      <option value="atoms">ATOMS JSON</option>
                      <option value="docx">Generic DOCX</option>
                      <option value="essca">ESSCA DOCX</option>
                      <option value="pdf">PDF</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium">Proposed parser hint</label>
                    <select
                      value={proposedParserHint}
                      onChange={(event) => setProposedParserHint(event.target.value as ParserHint)}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      <option value="auto">Auto-detect</option>
                      <option value="atoms">ATOMS JSON</option>
                      <option value="docx">Generic DOCX</option>
                      <option value="essca">ESSCA DOCX</option>
                      <option value="pdf">PDF</option>
                    </select>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </Card>

          <Card className="p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">Contract Context</p>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium">Agency</label>
                <Input value={agency} onChange={(event) => setAgency(event.target.value)} />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium">Center</label>
                <Input value={center} onChange={(event) => setCenter(event.target.value)} placeholder="Optional" />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium">Vehicle</label>
                <Input value={vehicle} onChange={(event) => setVehicle(event.target.value)} />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium">Local Policy Pack</label>
                <Input value={localPolicyPack} onChange={(event) => setLocalPolicyPack(event.target.value)} />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium">Revision Status Override</label>
                <select
                  value={revisionStatus}
                  onChange={(event) => setRevisionStatus(event.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <option value="">Use parsed document status</option>
                  <option value="draft">Draft</option>
                  <option value="released">Released</option>
                </select>
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    checked={useSonnet}
                    onChange={(event) => setUseSonnet(event.target.checked)}
                    className="h-4 w-4"
                  />
                  Enable Sonnet remediation wording
                </label>
              </div>
            </div>
            <div className="mt-4">
              <label className="mb-2 block text-sm font-medium">Contract Types</label>
              <Input value={contractTypes} onChange={(event) => setContractTypes(event.target.value)} placeholder="IDIQ, Task Order" />
            </div>
            <div className="mt-4">
              <label className="mb-2 block text-sm font-medium">Clauses Present</label>
              <Textarea value={clausesPresent} onChange={(event) => setClausesPresent(event.target.value)} className="min-h-24" />
            </div>
          </Card>
        </div>

        <div className="mt-4 rounded-2xl border border-dashed border-border bg-background/70 p-4">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 text-muted-foreground" />
            <div className="text-sm text-muted-foreground">
              <p className="font-medium text-foreground">Operating model</p>
              <p className="mt-1">
                Standalone scan evaluates one task order in isolation. Revision review compares prior versus proposed
                revisions and checks whether material changes were disclosed in the Summary of Changes.
              </p>
              {guidancePack && (
                <p className="mt-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  {guidancePack.pack_id} · {guidancePack.spec}
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={runAnalysis} disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Running Review
              </>
            ) : (
              <>
                <ClipboardCheck className="mr-2 h-4 w-4" />
                Run TOCR
              </>
            )}
          </Button>
          {parserSummary.map((item) => (
            <Badge key={item} variant="outline">{item}</Badge>
          ))}
        </div>

        {error && (
          <Card className="mt-4 border-destructive/40 p-4">
            <p className="text-sm text-destructive">{error}</p>
          </Card>
        )}
      </section>

      {report && (
        <>
          <section className="grid gap-4 md:grid-cols-4">
            <Card className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Scale className="h-4 w-4" />
                <span className="text-sm">Verdict</span>
              </div>
              <div className="mt-3">
                <Badge variant={verdictTone(report.score?.verdict)}>{report.score?.verdict ?? "UNSCORED"}</Badge>
              </div>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <AlertTriangle className="h-4 w-4" />
                <span className="text-sm">Score</span>
              </div>
              <p className="mt-3 text-3xl font-semibold">{report.score?.raw_score ?? "n/a"}</p>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <FileSearch className="h-4 w-4" />
                <span className="text-sm">Findings</span>
              </div>
              <p className="mt-3 text-3xl font-semibold">{findings.length}</p>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <ShieldAlert className="h-4 w-4" />
                <span className="text-sm">Rules Fired</span>
              </div>
              <p className="mt-3 text-3xl font-semibold">{report.rules_fired}</p>
            </Card>
          </section>

          {result && (
            <section className="grid gap-4 lg:grid-cols-2">
              {isScanResult(result)
                ? renderTaskOrderCard("Parsed Task Order", result.parsed_task_order)
                : (
                  <>
                    {renderTaskOrderCard("Prior Revision", result.prior_task_order)}
                    {renderTaskOrderCard("Proposed Revision", result.proposed_task_order)}
                  </>
                )}
            </section>
          )}

          <Tabs defaultValue="findings">
            <TabsList className="flex w-full flex-wrap justify-start gap-2">
              <TabsTrigger value="findings">Findings</TabsTrigger>
              <TabsTrigger value="remediation">Remediation</TabsTrigger>
              <TabsTrigger value="raw">Raw JSON</TabsTrigger>
            </TabsList>

            <TabsContent value="findings" className="space-y-4">
              {findings.length === 0 ? (
                <Card className="p-4">
                  <p className="text-sm text-muted-foreground">No findings. The current report scored clean.</p>
                </Card>
              ) : (
                findings.map((finding) => {
                  const guidance = result?.guidance[finding.rule_id] || guidancePack?.entries[finding.rule_id];
                  return (
                    <Card key={finding.finding_id} className="p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                            {finding.rule_id}
                          </p>
                          <h3 className="mt-1 text-lg font-semibold">{finding.rule_title}</h3>
                        </div>
                        <Badge variant="outline" className={SEVERITY_STYLE[finding.severity] || ""}>
                          {finding.severity}
                        </Badge>
                      </div>
                      <p className="mt-3 text-sm text-foreground">{finding.finding}</p>
                      {guidance && (
                        <div className="mt-4 grid gap-3 md:grid-cols-2">
                          <div className="rounded-xl border border-border/70 bg-background/80 p-3">
                            <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">What It Means</p>
                            <p className="mt-2 text-sm text-muted-foreground">{guidance.what_it_means}</p>
                          </div>
                          <div className="rounded-xl border border-border/70 bg-background/80 p-3">
                            <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">What To Do</p>
                            <p className="mt-2 text-sm text-muted-foreground">{guidance.what_to_do}</p>
                          </div>
                        </div>
                      )}
                    </Card>
                  );
                })
              )}
            </TabsContent>

            <TabsContent value="remediation" className="space-y-4">
              {remediationSteps.length === 0 ? (
                <Card className="p-4">
                  <p className="text-sm text-muted-foreground">No remediation steps were generated.</p>
                </Card>
              ) : (
                remediationSteps.map((step) => {
                  const guidance = result?.guidance[step.rule_id] || guidancePack?.entries[step.rule_id] || null;
                  return (
                    <Card key={`${step.finding_id}-${step.rule_id}`} className="p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                            {step.rule_id}
                          </p>
                          <h3 className="mt-1 text-lg font-semibold">{step.title}</h3>
                        </div>
                        <Badge variant="outline">{step.review_priority}</Badge>
                      </div>
                      <p className="mt-3 text-sm text-muted-foreground">{step.how_to_fix}</p>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        <div className="rounded-xl border border-border/70 bg-background/80 p-3">
                          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Why It Matters</p>
                          <p className="mt-2 text-sm text-muted-foreground">{step.why_it_matters || guidance?.why_it_matters || "Not provided."}</p>
                        </div>
                        <div className="rounded-xl border border-border/70 bg-background/80 p-3">
                          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Who Needs To Act</p>
                          <p className="mt-2 text-sm text-muted-foreground">{step.who_needs_to_act || guidance?.who_needs_to_act || "Not provided."}</p>
                        </div>
                      </div>
                    </Card>
                  );
                })
              )}
            </TabsContent>

            <TabsContent value="raw">
              <Card className="p-4">
                <Textarea readOnly className="min-h-[32rem] font-mono text-xs" value={prettyJson(result)} />
              </Card>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
