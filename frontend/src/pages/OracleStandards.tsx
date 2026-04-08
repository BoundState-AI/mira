import { useEffect, useMemo, useState } from "react";
import { BookOpenText, FileText, Library, Loader2, RefreshCw, Scale, Sparkles, Upload } from "lucide-react";

import { ModuleChatButton } from "@/components/mira/ModuleChatButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/PageHeader";
import {
  fetchOraclePackCatalog,
  importOraclePack,
  ingestOraclePdf,
  refreshOraclePackCatalog,
  type OraclePackCatalogResponse,
  type OraclePackSummary,
} from "@/lib/chat-api";
import {
  buildChatContextSummary,
  createModuleChatLaunchState,
  registerRouteModuleChatState,
} from "@/lib/mira-chat-context";

type OracleStandardCard = {
  code: string;
  title: string;
  detail: string;
  prompts: string[];
  tags: string[];
};

const FALLBACK_STANDARD_CARDS: OracleStandardCard[] = [
  {
    code: "NASA-STD-5009C",
    title: "Fracture Control Requirements",
    detail: "Use this pack for clause lookup and applicability questions around fracture-control requirements and tin-whisker style restrictions surfaced in the extracted rules.",
    prompts: [
      "What does NASA-STD-5009C say about tin whiskers?",
      "Show me the governing clause in NASA-STD-5009C for pure tin finishes.",
    ],
    tags: ["NASA", "fracture control", "spaceflight hardware"],
  },
  {
    code: "MSFC-STD-3012A",
    title: "EEE Parts Management Requirements",
    detail: "Best for Grade-driven parts questions, repeated table-note restrictions, and clause-level checks against the dense EEE parts management standard.",
    prompts: [
      "Show me MSFC-STD-3012A Table V Note 6.",
      "What does MSFC-STD-3012A say about connector plating restrictions?",
    ],
    tags: ["MSFC", "EEE parts", "table notes"],
  },
  {
    code: "FAR Part 31",
    title: "Federal Acquisition Regulation Cost Principles",
    detail: "Use this pack for cost-principle clause lookup and compare-mode questions against related acquisition authorities.",
    prompts: [
      "What does FAR Part 31 say about allowability on this cost?",
      "Compare FAR Part 31 and NFS 1831 on this topic.",
    ],
    tags: ["acquisition", "cost allowability", "FAR"],
  },
  {
    code: "NFS Part 1831",
    title: "NASA FAR Supplement Cost Principles",
    detail: "Use this when NASA-specific acquisition supplements matter more than the base FAR text.",
    prompts: [
      "What NASA supplement clause governs this cost principle?",
      "Compare NFS Part 1831 and FAR Part 31 for this issue.",
    ],
    tags: ["NASA supplement", "procurement", "NFS"],
  },
];

function inferTags(pack: OraclePackSummary): string[] {
  const label = `${pack.standard_id} ${pack.standard_title}`.toLowerCase();
  const tags = new Set<string>();

  if (label.includes("nasa")) tags.add("NASA");
  if (label.includes("msfc")) tags.add("MSFC");
  if (label.includes("far")) tags.add("FAR");
  if (label.includes("nfs")) tags.add("NFS");
  if (label.includes("fracture")) tags.add("fracture control");
  if (label.includes("eee")) tags.add("EEE parts");
  if (label.includes("procurement") || label.includes("cost")) tags.add("acquisition");
  if (label.includes("table")) tags.add("table notes");
  for (const obligationType of pack.obligation_types) {
    tags.add(obligationType);
  }

  return Array.from(tags).slice(0, 4);
}

function buildPrompts(pack: OraclePackSummary): string[] {
  const code = pack.standard_id;
  const lower = `${pack.standard_id} ${pack.standard_title}`.toLowerCase();

  if (lower.includes("5009")) {
    return [
      `What does ${code} say about tin whiskers?`,
      `Show me the governing clause in ${code} for pure tin finishes.`,
    ];
  }
  if (lower.includes("3012")) {
    return [
      `Show me ${code} Table V Note 6.`,
      `What does ${code} say about connector plating restrictions?`,
    ];
  }
  if (lower.includes("far")) {
    return [
      `What does ${code} say about allowability on this cost?`,
      `Compare ${code} against another loaded standard on this topic.`,
    ];
  }

  return [
    `What does ${code} say about this topic?`,
    `Show me the governing clause in ${code}.`,
  ];
}

function toStandardCard(pack: OraclePackSummary): OracleStandardCard {
  return {
    code: pack.standard_id,
    title: pack.standard_title,
    detail: `${pack.rule_count.toLocaleString()} extracted rules loaded for clause lookup, applicability checks, and compare-mode questions.`,
    prompts: buildPrompts(pack),
    tags: inferTags(pack),
  };
}

function comparePrompts(primary: string, others: string[]): string[] {
  const compareLabel = [primary, ...others].join(" and ");
  return [
    `Compare ${compareLabel} on this topic.`,
    `Which clause is stricter between ${primary} and ${others[0]}?`,
    `What evidence would I need to resolve a conflict between ${compareLabel}?`,
  ];
}

export default function OracleStandards() {
  const [catalogCards, setCatalogCards] = useState<OracleStandardCard[]>([]);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [manageMessage, setManageMessage] = useState<string | null>(null);
  const [ingestName, setIngestName] = useState("");
  const [selectedStandardCode, setSelectedStandardCode] = useState<string>(FALLBACK_STANDARD_CARDS[0].code);
  const [compareSelection, setCompareSelection] = useState<string[]>([]);
  const standardCards = catalogCards.length ? catalogCards : FALLBACK_STANDARD_CARDS;

  const applyCatalog = (payload: OraclePackCatalogResponse, error: string | null = null) => {
    const cards = Array.isArray(payload.packs)
      ? payload.packs.map(toStandardCard)
      : [];
    setCatalogCards(cards);
    setCatalogError(error ?? (payload.status === "ok" ? null : "Oracle pack catalog unavailable."));
  };

  useEffect(() => {
    let cancelled = false;

    void fetchOraclePackCatalog()
      .then((payload) => {
        if (cancelled) return;
        applyCatalog(payload);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setCatalogCards([]);
        setCatalogError(error instanceof Error ? error.message : "Oracle pack catalog unavailable.");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (standardCards.some((card) => card.code === selectedStandardCode)) {
      return;
    }
    setSelectedStandardCode(standardCards[0]?.code ?? FALLBACK_STANDARD_CARDS[0].code);
  }, [selectedStandardCode, standardCards]);

  useEffect(() => {
    setCompareSelection((current) => current.filter((code) => code !== selectedStandardCode && standardCards.some((card) => card.code === code)));
  }, [selectedStandardCode, standardCards]);

  const selectedStandard = useMemo(
    () => standardCards.find((card) => card.code === selectedStandardCode) ?? standardCards[0],
    [selectedStandardCode, standardCards],
  );
  const compareTargets = useMemo(
    () => standardCards.filter((card) => card.code !== selectedStandard.code).slice(0, 3),
    [selectedStandard.code, standardCards],
  );
  const compareCards = useMemo(
    () => standardCards.filter((card) => compareSelection.includes(card.code)),
    [compareSelection, standardCards],
  );

  const oracleChatLaunchState = useMemo(() => createModuleChatLaunchState({
    scopeKey: `oracle-${selectedStandard.code.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    moduleLabel: "Oracle Standards",
    moduleContext: {
      module: "oracle",
      standard_ref: selectedStandard.code,
    },
    originPath: "/oracle",
    originTitle: "Oracle Standards",
    description: "Stay grounded in the selected Oracle rule pack for clause lookup, applicability checks, and standards comparison.",
    starterPrompts: selectedStandard.prompts,
    contextSummary: buildChatContextSummary([
      { label: "Standard", value: selectedStandard.code },
      { label: "Title", value: selectedStandard.title },
      { label: "Mode", value: "Clause-grounded advisory chat" },
    ]),
  }), [selectedStandard]);
  const compareChatLaunchState = useMemo(() => {
    if (!compareCards.length) {
      return null;
    }
    const compareRefs = [selectedStandard.code, ...compareCards.map((card) => card.code)];
    return createModuleChatLaunchState({
      scopeKey: `oracle-compare-${compareRefs.join("-").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      moduleLabel: "Oracle Compare",
      moduleContext: {
        module: "oracle",
        standard_ref: selectedStandard.code,
        compare_standard_refs: compareRefs,
        compare_only: true,
      },
      originPath: "/oracle",
      originTitle: "Oracle Standards",
      description: `Compare the selected standards inside Oracle without expanding to the full library.`,
      starterPrompts: comparePrompts(selectedStandard.code, compareCards.map((card) => card.code)),
      contextSummary: buildChatContextSummary([
        { label: "Primary", value: selectedStandard.code },
        { label: "Compare", value: compareCards.map((card) => card.code).join(", ") },
        { label: "Mode", value: "Compare-only advisory chat" },
      ]),
    });
  }, [compareCards, selectedStandard.code]);
  const activeLaunchState = compareChatLaunchState ?? oracleChatLaunchState;

  useEffect(() => {
    registerRouteModuleChatState("/oracle", activeLaunchState);
  }, [activeLaunchState]);

  const toggleCompareSelection = (code: string) => {
    setCompareSelection((current) => (
      current.includes(code)
        ? current.filter((item) => item !== code)
        : [...current, code].slice(0, 2)
    ));
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setManageMessage(null);
    try {
      const payload = await refreshOraclePackCatalog();
      applyCatalog(payload);
      setManageMessage("Oracle library refreshed without restart.");
    } catch (error: unknown) {
      setManageMessage(error instanceof Error ? error.message : "Oracle refresh failed.");
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleImportJson = async (file: File | null) => {
    if (!file) return;
    setIsImporting(true);
    setManageMessage(null);
    try {
      const payload = await importOraclePack(file);
      applyCatalog(payload);
      setManageMessage(`Imported ${file.name} into the Oracle library.`);
    } catch (error: unknown) {
      setManageMessage(error instanceof Error ? error.message : "Oracle JSON import failed.");
    } finally {
      setIsImporting(false);
    }
  };

  const handleIngestPdf = async (file: File | null) => {
    if (!file) return;
    setIsIngesting(true);
    setManageMessage(null);
    try {
      const payload = await ingestOraclePdf({
        file,
        standardName: ingestName,
        useVision: false,
      });
      applyCatalog(payload);
      setManageMessage(`Ingested ${file.name} into the Oracle library.`);
      setIngestName("");
    } catch (error: unknown) {
      setManageMessage(error instanceof Error ? error.message : "Oracle PDF ingest failed.");
    } finally {
      setIsIngesting(false);
    }
  };

  return (
    <div className="space-y-8">
      <PageHeader
        title="Oracle Standards"
        description="Clause-grounded chat for extracted standards rule packs. Ask what the standard says, whether a clause applies, or compare authorities without dropping provenance."
        actions={(
          <ModuleChatButton
            launchState={activeLaunchState}
            label={compareChatLaunchState ? "Open Compare Chat" : "Open Oracle Chat"}
          />
        )}
      />

      <Card className="overflow-hidden border-border/70">
        <div className="bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.16),_transparent_38%),linear-gradient(135deg,_rgba(15,23,42,0.98),_rgba(30,41,59,0.98))] px-6 py-6 text-slate-50">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-200">
                <Library className="h-3.5 w-3.5" />
                Shared Chat Shape
              </div>
              <h1 className="text-3xl font-semibold tracking-tight">Standards chat with Oracle grounding</h1>
              <p className="text-sm text-slate-200/85">
                The Oracle engine now sits inside the same shared MIRA chat surface as the rest of the workspace,
                but keeps standards-specific cues: cited clauses, rule-pack scope, and advisory-only guardrails.
              </p>
            </div>

            <div className="grid gap-3 text-sm text-slate-100 sm:grid-cols-3">
              <div className="rounded-xl border border-white/10 bg-white/8 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-300">Primary use</div>
                <div className="mt-1 font-medium">Clause lookup</div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/8 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-300">Guardrail</div>
                <div className="mt-1 font-medium">Advisory only</div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/8 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-300">Shared UX</div>
                <div className="mt-1 font-medium">Drawer + full chat page</div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/8 px-4 py-3 sm:col-span-3">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-300">Loaded packs</div>
                <div className="mt-1 font-medium">
                  {catalogCards.length
                    ? `${catalogCards.length} live Oracle rule packs`
                    : "Fallback catalog"}
                </div>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-6">
          <Card className="border-border/70 p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Manage library</h2>
                <p className="text-sm text-muted-foreground">
                  Add a generated JSON pack, ingest a new PDF into the Oracle library, or refresh the live catalog without restarting the app.
                </p>
              </div>
              <Button type="button" variant="outline" onClick={() => void handleRefresh()} disabled={isRefreshing}>
                {isRefreshing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                Refresh library
              </Button>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-2xl border border-border/70 bg-muted/20 p-4">
                <div className="mb-2 text-sm font-semibold text-foreground">Import pack JSON</div>
                <p className="mb-4 text-sm text-muted-foreground">
                  Use this when Oracle already produced a rule-pack JSON and you just need it in the shared library.
                </p>
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-muted/40">
                  <Upload className="h-4 w-4" />
                  {isImporting ? "Importing..." : "Choose JSON pack"}
                  <input
                    type="file"
                    accept=".json,application/json"
                    className="hidden"
                    disabled={isImporting}
                    onChange={(event) => {
                      void handleImportJson(event.target.files?.[0] ?? null);
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>

              <div className="rounded-2xl border border-border/70 bg-muted/20 p-4">
                <div className="mb-2 text-sm font-semibold text-foreground">Ingest new standards PDF</div>
                <p className="mb-4 text-sm text-muted-foreground">
                  Upload a new standards PDF and let Oracle parse it into a registered library pack.
                </p>
                <div className="mb-3">
                  <Input
                    value={ingestName}
                    onChange={(event) => setIngestName(event.target.value)}
                    placeholder="Optional standard name override"
                  />
                </div>
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-muted/40">
                  <Upload className="h-4 w-4" />
                  {isIngesting ? "Ingesting..." : "Choose PDF"}
                  <input
                    type="file"
                    accept=".pdf,application/pdf"
                    className="hidden"
                    disabled={isIngesting}
                    onChange={(event) => {
                      void handleIngestPdf(event.target.files?.[0] ?? null);
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>
            </div>

            {manageMessage ? (
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                {manageMessage}
              </div>
            ) : null}
          </Card>

          <Card className="border-border/70 p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Select a governing standard</h2>
                <p className="text-sm text-muted-foreground">
                  Choosing a standard here pre-scopes the shared chat drawer and the full Oracle chat page.
                </p>
              </div>
              <Badge variant="outline" className="px-3 py-1 text-xs uppercase tracking-[0.18em]">
                {selectedStandard.code}
              </Badge>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              {standardCards.map((card) => {
                const isSelected = card.code === selectedStandard.code;
                return (
                  <div
                    key={card.code}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedStandardCode(card.code)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedStandardCode(card.code);
                      }
                    }}
                    className={[
                      "rounded-2xl border p-4 text-left transition",
                      isSelected
                        ? "border-sky-500 bg-sky-50 shadow-sm"
                        : "border-border/70 bg-background hover:border-sky-300 hover:bg-slate-50",
                    ].join(" ")}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-2">
                        <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{card.code}</div>
                        <div className="text-base font-semibold text-foreground">{card.title}</div>
                      </div>
                      {isSelected ? <Sparkles className="h-4 w-4 text-sky-600" /> : null}
                    </div>
                    <p className="mt-3 text-sm text-muted-foreground">{card.detail}</p>
                    <div className="mt-4 flex flex-wrap gap-1.5">
                      {card.tags.map((tag) => (
                        <span
                          key={`${card.code}-${tag}`}
                          className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                    {!isSelected ? (
                      <div className="mt-4">
                        <Button
                          type="button"
                          size="sm"
                          variant={compareSelection.includes(card.code) ? "default" : "outline"}
                          onClick={(event) => {
                            event.stopPropagation();
                            toggleCompareSelection(card.code);
                          }}
                        >
                          {compareSelection.includes(card.code) ? "Selected for compare" : "Add to compare"}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
            {catalogError ? (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                Oracle pack catalog fell back to curated defaults: {catalogError}
              </div>
            ) : null}
          </Card>

          <Card className="border-border/70 p-5">
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="space-y-3">
                <div className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
                  <BookOpenText className="h-4 w-4 text-sky-700" />
                  Oracle starter prompts
                </div>
                <div className="space-y-2">
                  {selectedStandard.prompts.map((prompt) => (
                    <div
                      key={prompt}
                      className="rounded-xl border border-border/70 bg-muted/20 px-3 py-2 text-sm text-foreground"
                    >
                      {prompt}
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                <div className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Scale className="h-4 w-4 text-amber-700" />
                  Compare shortcuts
                </div>
                {compareTargets.length ? (
                  <div className="space-y-2 text-sm text-muted-foreground">
                    {compareTargets.map((target) => (
                      <button
                        key={`${selectedStandard.code}-${target.code}`}
                        type="button"
                        onClick={() => toggleCompareSelection(target.code)}
                        className="w-full rounded-xl border border-border/70 bg-muted/20 px-3 py-2 text-left text-foreground transition hover:border-sky-300 hover:bg-sky-50"
                      >
                        Compare {selectedStandard.code} and {target.code}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-border/70 bg-muted/20 px-3 py-2 text-sm text-muted-foreground">
                    Add another Oracle pack to unlock compare-mode shortcuts here.
                  </div>
                )}
              </div>
            </div>
          </Card>
        </div>

        <Card className="border-border/70 p-5">
          <div className="space-y-4">
            <h2 className="text-base font-semibold">Current grounding</h2>
            <div className="space-y-3">
              {oracleChatLaunchState.contextSummary.map((item) => (
                <div
                  key={`${item.label}-${item.value}`}
                  className="rounded-xl border border-border/70 bg-muted/20 px-3 py-2"
                >
                  <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                    {item.label}
                  </div>
                  <div className="mt-1 text-sm font-medium text-foreground">{item.value}</div>
                </div>
              ))}
            </div>

            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <div className="mb-1 inline-flex items-center gap-2 font-medium">
                <FileText className="h-4 w-4" />
                Advisory boundary
              </div>
              Oracle can surface the governing requirement, compare clauses, and identify missing evidence. It does not
              issue program approval, certification, waiver, or final disposition.
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              Oracle answers in the shared chat now expose clause citations inline and keep follow-ups scoped to the
              selected standard by default.
            </div>

            {compareCards.length ? (
              <div className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
                <div className="mb-2 font-medium">Compare-only selection</div>
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {[selectedStandard, ...compareCards].map((card) => (
                    <span
                      key={`compare-${card.code}`}
                      className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-[11px]"
                    >
                      {card.code}
                    </span>
                  ))}
                </div>
                <p>
                  Compare chat stays limited to these packs instead of blending the entire Oracle library.
                </p>
              </div>
            ) : null}

            <ModuleChatButton
              launchState={activeLaunchState}
              label={compareChatLaunchState ? "Open Compare Chat" : "Ask Oracle About This Standard"}
              className="w-full"
              variant="default"
            />
          </div>
        </Card>
      </div>
    </div>
  );
}
