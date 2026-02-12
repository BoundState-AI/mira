import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Beaker,
  FileSearch,
  Lightbulb,
  Info,
  Loader2,
} from "lucide-react";
import type {
  InvestigationResult,
  PrecedentMatch,
  EvidenceStrengthBand,
  EvidenceStrengthResult,
} from "@/lib/mua-v7-api";
import { getInvestigationStatus, getSession } from "@/lib/mua-v7-api";
import type { WizardClientState } from "@/pages/MUAWizardV7";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  wizard: WizardClientState;
  patchWizard: (patch: Partial<WizardClientState>) => void;
  onNext: () => void;
}

// ---------------------------------------------------------------------------
// Investigation sub-stage labels (timer-driven animation)
// ---------------------------------------------------------------------------

const INVESTIGATE_SUBSTAGES = [
  "Finding precedents...",
  "Checking test data...",
  "Assessing fit...",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BAND_CONFIG: Record<
  EvidenceStrengthBand,
  { color: string; bg: string; border: string; icon: typeof ShieldCheck; label: string }
> = {
  strong:       { color: 'text-green-700',  bg: 'bg-green-50',  border: 'border-green-300', icon: ShieldCheck, label: 'Strong' },
  moderate:     { color: 'text-yellow-700', bg: 'bg-yellow-50', border: 'border-yellow-300', icon: Shield,      label: 'Moderate' },
  weak:         { color: 'text-orange-700', bg: 'bg-orange-50', border: 'border-orange-300', icon: ShieldAlert, label: 'Weak' },
  insufficient: { color: 'text-red-700',    bg: 'bg-red-50',    border: 'border-red-300',    icon: ShieldX,     label: 'Insufficient' },
};

function bandBadgeVariant(band: EvidenceStrengthBand) {
  if (band === 'strong') return 'default' as const;
  if (band === 'insufficient') return 'destructive' as const;
  return 'secondary' as const;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function EvidenceStrengthCard({ strength }: { strength: EvidenceStrengthResult }) {
  const [open, setOpen] = useState(false);
  const cfg = BAND_CONFIG[strength.band];
  const Icon = cfg.icon;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className={`${cfg.border} ${cfg.bg}`}>
        <CardContent className="pt-4 pb-3">
          <CollapsibleTrigger className="w-full">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Icon className={`h-6 w-6 ${cfg.color}`} />
                <div className="text-left">
                  <div className="flex items-center gap-2">
                    <span className={`text-lg font-semibold ${cfg.color}`}>
                      Evidence: {cfg.label}
                    </span>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Badge variant={bandBadgeVariant(strength.band)} className="text-xs">
                            {strength.score.toFixed(2)}
                          </Badge>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Composite evidence score</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    {strength.explanation}
                  </p>
                </div>
              </div>
              {open ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-4">
            <Separator className="mb-3" />
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
              {Object.entries(strength.components).map(([key, val]) => (
                <div key={key} className="space-y-1">
                  <span className="text-muted-foreground capitalize">
                    {key.replace(/_/g, ' ')}
                  </span>
                  <div className="font-medium">
                    {typeof val === 'number' ? val.toFixed(1) : String(val)}
                  </div>
                </div>
              ))}
            </div>
          </CollapsibleContent>
        </CardContent>
      </Card>
    </Collapsible>
  );
}

function PrecedentCard({ p }: { p: PrecedentMatch }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Collapsible open={expanded} onOpenChange={setExpanded}>
      <Card className={p.is_conflicting ? 'border-red-300 bg-red-50/30' : ''}>
        <CardContent className="pt-4 pb-3">
          <CollapsibleTrigger className="w-full text-left">
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold">{p.mua_number}</span>
                  <Badge
                    variant={p.is_supporting ? 'default' : p.is_conflicting ? 'destructive' : 'secondary'}
                    className="text-xs"
                  >
                    {p.determination}
                  </Badge>
                  {p.is_conflicting && (
                    <Badge variant="destructive" className="text-xs">
                      <AlertTriangle className="h-3 w-3 mr-1" />
                      Conflict
                    </Badge>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">
                  {p.material_designation} -- {p.environment_description}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge variant="outline" className="text-xs tabular-nums">
                  {(p.relevance_score * 100).toFixed(0)}% match
                </Badge>
                {expanded ? (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                )}
              </div>
            </div>
          </CollapsibleTrigger>

          <CollapsibleContent className="mt-3">
            <Separator className="mb-3" />
            <div className="space-y-3">
              {/* Supporting rationale */}
              {p.supporting_rationale && (
                <div className="rounded-md bg-green-50 border border-green-200 p-3">
                  <div className="flex items-start gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5 shrink-0" />
                    <div className="text-sm">
                      <span className="font-medium text-green-800">Supporting: </span>
                      {p.supporting_rationale}
                    </div>
                  </div>
                </div>
              )}

              {/* Non-applicability caveat */}
              {p.non_applicability_caveat && (
                <div className="rounded-md bg-amber-50 border border-amber-200 p-3">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
                    <div className="text-sm">
                      <span className="font-medium text-amber-800">Limitations: </span>
                      {p.non_applicability_caveat}
                    </div>
                  </div>
                </div>
              )}

              {/* Fallback to combined explanation when split fields are empty */}
              {!p.supporting_rationale && !p.non_applicability_caveat && p.relationship_explanation && (
                <div className="rounded-md bg-muted/50 p-3">
                  <div className="flex items-start gap-2">
                    <Lightbulb className="h-4 w-4 text-primary mt-0.5 shrink-0" />
                    <div className="text-sm">
                      <span className="font-medium">Why this matters: </span>
                      {p.relationship_explanation}
                    </div>
                  </div>
                </div>
              )}

              {/* Relevance tags */}
              <div className="flex items-center gap-2">
                {p.physics_relevance > 0.3 && (
                  <Badge variant="outline" className="text-xs">
                    <Beaker className="h-3 w-3 mr-1" />
                    Physics Relevant
                  </Badge>
                )}
                {p.regulatory_relevance > 0.3 && (
                  <Badge variant="outline" className="text-xs">
                    <FileSearch className="h-3 w-3 mr-1" />
                    Regulatory Relevant
                  </Badge>
                )}
              </div>
            </div>
          </CollapsibleContent>
        </CardContent>
      </Card>
    </Collapsible>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function MUAInvestigateStep({ wizard, patchWizard, onNext }: Props) {
  const inv = wizard.investigation;
  const sessionId = wizard.sessionId;

  const [isPolling, setIsPolling] = useState(false);
  const [hasStartedPolling, setHasStartedPolling] = useState(false);
  const [subStageIndex, setSubStageIndex] = useState(0);
  const [pollError, setPollError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const statusFailCountRef = useRef(0);
  const sessionFetchFailCountRef = useRef(0);
  const pollInFlightRef = useRef(false);
  const pollTickRef = useRef(0);
  const idleStatusCountRef = useRef(0);
  const unknownStatusCountRef = useRef(0);
  const wasPollingRef = useRef(false);

  // Start polling when we have a session but no investigation results yet
  useEffect(() => {
    if (!sessionId || inv) {
      // Investigation already populated (e.g. via session restore) -- stop polling
      setIsPolling(false);
      setHasStartedPolling(false);
      if (inv) setPollError(null);
      return;
    }

    setIsPolling(true);
    setHasStartedPolling(true);
    setSubStageIndex(0);
    setPollError(null);

    statusFailCountRef.current = 0;
    sessionFetchFailCountRef.current = 0;
    pollInFlightRef.current = false;
    pollTickRef.current = 0;
    idleStatusCountRef.current = 0;
    unknownStatusCountRef.current = 0;

    pollRef.current = setInterval(async () => {
      if (pollInFlightRef.current) return;
      pollInFlightRef.current = true;

      try {
        const status = await getInvestigationStatus(sessionId, 10000);
        pollTickRef.current += 1;
        // Status poll succeeded -- reset only status-failure counter.
        statusFailCountRef.current = 0;
        const rawStatus =
          typeof status.status === 'string' ? status.status : '';
        const normalizedStatus = rawStatus.trim().toLowerCase();
        const isComplete = normalizedStatus === 'complete' || status.progress >= 100;

        if (isComplete) {
          idleStatusCountRef.current = 0;
          unknownStatusCountRef.current = 0;
          // Fetch full session to populate wizard state
          try {
            const session = await getSession(sessionId, 12000);
            if (session.investigation) {
              patchWizard({ investigation: session.investigation });
              sessionFetchFailCountRef.current = 0;
              setIsPolling(false);
            } else {
              sessionFetchFailCountRef.current += 1;
              console.warn(
                `[MUA] session returned without investigation after status=complete (attempt ${sessionFetchFailCountRef.current})`,
                { sessionId, currentStep: session.current_step, status: session.status },
              );
              if (sessionFetchFailCountRef.current >= 3) {
                setPollError(
                  'Investigation completed but results were empty. Try refreshing the page.',
                );
                setIsPolling(false);
              }
            }
          } catch (fetchErr) {
            // getSession failed AFTER investigation completed
            sessionFetchFailCountRef.current += 1;
            console.warn(
              `[MUA] getSession failed after investigation complete (attempt ${sessionFetchFailCountRef.current}):`,
              fetchErr,
            );
            if (sessionFetchFailCountRef.current >= 3) {
              setPollError(
                'Investigation completed but failed to load results. Try refreshing the page.',
              );
              setIsPolling(false);
            }
          }
        } else if (normalizedStatus === 'investigating') {
          idleStatusCountRef.current = 0;
          unknownStatusCountRef.current = 0;
          if (pollTickRef.current % 4 === 0) {
            // Fallback in case status lags behind persisted session data.
            try {
              const session = await getSession(sessionId, 8000);
              if (session.investigation) {
                patchWizard({ investigation: session.investigation });
                setIsPolling(false);
              }
            } catch (sessionProbeErr) {
              console.warn('[MUA] getSession probe during investigating failed:', sessionProbeErr);
            }
          }
        } else if (normalizedStatus === 'idle') {
          idleStatusCountRef.current += 1;
          unknownStatusCountRef.current = 0;
          // Probe the session aggressively when the status endpoint is unexpectedly idle.
          if (pollTickRef.current % 2 === 0 || idleStatusCountRef.current >= 6) {
            try {
              const session = await getSession(sessionId, 8000);
              if (session.investigation) {
                patchWizard({ investigation: session.investigation });
                setIsPolling(false);
              } else if (idleStatusCountRef.current >= 8) {
                setPollError(
                  'Investigation is stuck in idle state with no results. Please go back and run Investigate again.',
                );
                setIsPolling(false);
              }
            } catch (sessionProbeErr) {
              console.warn('[MUA] getSession probe during idle status failed:', sessionProbeErr);
              if (idleStatusCountRef.current >= 8) {
                setPollError(
                  'Investigation status is idle and results could not be loaded. Please go back and re-submit.',
                );
                setIsPolling(false);
              }
            }
          }
        } else if (normalizedStatus === 'failed') {
          setPollError(status.error || 'Investigation failed');
          setIsPolling(false);
        } else {
          unknownStatusCountRef.current += 1;
          console.warn(
            `[MUA] unexpected investigation status '${rawStatus}' (attempt ${unknownStatusCountRef.current})`,
            status,
          );
          try {
            const session = await getSession(sessionId, 8000);
            if (session.investigation) {
              patchWizard({ investigation: session.investigation });
              setIsPolling(false);
            }
          } catch (sessionProbeErr) {
            console.warn('[MUA] getSession probe during unknown status failed:', sessionProbeErr);
          }
          if (unknownStatusCountRef.current >= 3) {
            setPollError(
              `Received unexpected investigation status '${rawStatus || 'unknown'}'. Please go back and re-submit.`,
            );
            setIsPolling(false);
          }
        }
        // else: still investigating -- keep polling
      } catch (pollErr) {
        // Status poll itself failed (404 = stale session, 502 = backend down, etc.)
        statusFailCountRef.current += 1;
        console.warn(
          `[MUA] status poll failed (attempt ${statusFailCountRef.current}):`,
          pollErr,
        );
        if (statusFailCountRef.current >= 5) {
          setPollError(
            'Lost connection to investigation session. The server may have restarted. Please go back and re-submit.',
          );
          setIsPolling(false);
        }
      } finally {
        pollInFlightRef.current = false;
      }
    }, 3000);

    // Safety timeout: 5 minutes
    timeoutRef.current = setTimeout(() => {
      if (pollRef.current) clearInterval(pollRef.current);
      setIsPolling(false);
      setPollError('Investigation timed out after 5 minutes.');
    }, 5 * 60 * 1000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      pollInFlightRef.current = false;
    };
  }, [sessionId, inv, patchWizard]);

  // Cleanup polling intervals when polling stops
  useEffect(() => {
    // Avoid clearing a freshly created interval on the initial render
    // (isPolling=false before the startup effect flips it to true).
    if (isPolling) {
      wasPollingRef.current = true;
      return;
    }
    if (!wasPollingRef.current) return;

    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; }
    pollInFlightRef.current = false;
    wasPollingRef.current = false;
  }, [isPolling]);

  // Sub-stage animation timer (cycle through labels every 10 seconds)
  useEffect(() => {
    if (!isPolling) return;
    const timer = setInterval(() => {
      setSubStageIndex((i) => Math.min(i + 1, INVESTIGATE_SUBSTAGES.length - 1));
    }, 10000);
    return () => clearInterval(timer);
  }, [isPolling]);

  // ---- Polling UI ----
  if (isPolling || (!hasStartedPolling && !inv && sessionId && !pollError)) {
    const progress = ((subStageIndex + 1) / INVESTIGATE_SUBSTAGES.length) * 100;
    return (
      <div className="space-y-6">
        <Card className="border-blue-200 bg-gradient-to-br from-blue-50/50 via-white to-blue-50/30">
          <CardContent className="py-16 text-center space-y-6">
            <Loader2 className="h-10 w-10 animate-spin mx-auto text-blue-600" />
            <div className="space-y-2">
              <p className="text-lg font-semibold text-blue-900">
                Investigating evidence...
              </p>
              <p className="text-sm text-blue-600 transition-all duration-500">
                {INVESTIGATE_SUBSTAGES[subStageIndex]}
              </p>
            </div>
            <div className="max-w-md mx-auto">
              <div className="w-full h-1.5 bg-blue-100 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-blue-500 to-blue-400 transition-all duration-1000 ease-out"
                  style={{ width: `${Math.min(progress, 95)}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                This may take up to a minute
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---- Error UI ----
  if (pollError) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Investigation Failed</AlertTitle>
        <AlertDescription>{pollError}</AlertDescription>
      </Alert>
    );
  }

  // ---- No data and no session ----
  if (!inv) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-muted-foreground">
          No investigation data. Please complete the Define step first.
        </CardContent>
      </Card>
    );
  }

  // ---- Results display ----
  const allPrecedents = [...inv.supporting_precedents, ...inv.conflicting_precedents];
  const supportingCount = inv.supporting_precedents.length;
  const conflictingCount = inv.conflicting_precedents.length;
  const currentTests = inv.test_data.filter((t) => t.is_current !== false).length;
  const expiredTests = inv.test_data.filter((t) => t.is_current === false).length;

  return (
    <div className="space-y-6">
      {/* Summary banner */}
      <Card>
        <CardContent className="pt-5 pb-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <div className="flex items-center gap-1.5">
              <FileSearch className="h-4 w-4 text-primary" />
              <span className="font-medium">{allPrecedents.length} precedents found</span>
              <span className="text-muted-foreground">
                ({supportingCount} supporting{conflictingCount > 0 && `, ${conflictingCount} conflicting`})
              </span>
            </div>
            <Separator orientation="vertical" className="h-4" />
            <div className="flex items-center gap-1.5">
              <Beaker className="h-4 w-4 text-primary" />
              <span>
                MAPTIS test data: {currentTests} current
                {expiredTests > 0 && `, ${expiredTests} expired`}
              </span>
            </div>
            <Separator orientation="vertical" className="h-4" />
            <div className="flex items-center gap-1.5">
              <span>Suggested category:</span>
              <Badge variant="outline" className="font-mono">
                {inv.preliminary_category}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Novel material banner */}
      {inv.is_novel_material && (
        <Alert className="border-blue-300 bg-blue-50">
          <Info className="h-4 w-4 text-blue-600" />
          <AlertTitle className="text-blue-800">Novel Material Detected</AlertTitle>
          <AlertDescription className="text-blue-700">
            Limited prior usage data exists for this material. A Qualification Plan may be
            required. MIRA can generate one after this MUA is finalized.
          </AlertDescription>
        </Alert>
      )}

      {/* Evidence strength */}
      <EvidenceStrengthCard strength={inv.evidence_strength} />

      {/* Precedents */}
      <div className="space-y-3">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <FileSearch className="h-5 w-5" />
          Precedent Matches
          <Badge variant="outline" className="text-xs font-normal">
            {allPrecedents.length}
          </Badge>
        </h3>
        {allPrecedents.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              No precedents found for this material/environment combination.
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {allPrecedents.map((p) => (
              <PrecedentCard key={p.mua_number} p={p} />
            ))}
          </div>
        )}
      </div>

      {/* Conflicts callout */}
      {inv.conflicts.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2 text-red-700">
            <AlertTriangle className="h-5 w-5" />
            Conflicts Detected
            <Badge variant="destructive" className="text-xs font-normal">
              {inv.conflicts.length}
            </Badge>
          </h3>
          {inv.conflicts.map((c) => (
            <Alert key={c.conflict_id} variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>{c.severity === 'hard' ? 'Hard Conflict' : 'Soft Conflict'}</AlertTitle>
              <AlertDescription className="space-y-1">
                <p>{c.description}</p>
                <p className="text-xs opacity-80">
                  Suggested resolution: {c.recommendation}
                </p>
              </AlertDescription>
            </Alert>
          ))}
        </div>
      )}

      {/* Gaps */}
      {inv.gaps.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-orange-600" />
            Evidence Gaps
            <Badge variant="secondary" className="text-xs font-normal">
              {inv.gaps.length}
            </Badge>
          </h3>
          {inv.gaps.map((g) => (
            <Card key={g.gap_id} className="border-orange-200">
              <CardContent className="pt-3 pb-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <Badge
                        variant={g.severity === 'critical' ? 'destructive' : 'secondary'}
                        className="text-xs"
                      >
                        {g.severity}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{g.dimension}</span>
                    </div>
                    <p className="text-sm">{g.description}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Test data summary */}
      {inv.test_data.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Beaker className="h-5 w-5" />
            Test Data
            <Badge variant="outline" className="text-xs font-normal">
              {inv.test_data.length} records
            </Badge>
          </h3>
          <Card>
            <CardContent className="pt-3 pb-3">
              <div className="space-y-2">
                {inv.test_data.slice(0, 8).map((t, i) => (
                  <div
                    key={`${t.test_class}-${t.test_number ?? i}`}
                    className="flex items-center justify-between text-sm py-1 border-b last:border-0"
                  >
                    <div className="flex items-center gap-2">
                      {t.rating && ['A', 'B'].includes(t.rating.toUpperCase()) ? (
                        <CheckCircle2 className="h-4 w-4 text-green-600" />
                      ) : (
                        <XCircle className="h-4 w-4 text-red-500" />
                      )}
                      <span className="font-medium">{t.test_class}</span>
                      <span className="text-muted-foreground">({t.rating ?? 'U'})</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {t.is_current === false && (
                        <Badge variant="outline" className="text-xs text-orange-600 border-orange-300">
                          Expired
                        </Badge>
                      )}
                      <span className="text-xs text-muted-foreground">{t.test_date}</span>
                    </div>
                  </div>
                ))}
                {inv.test_data.length > 8 && (
                  <p className="text-xs text-muted-foreground text-center pt-1">
                    + {inv.test_data.length - 8} more records
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Next */}
      <div className="flex justify-end">
        <Button size="lg" onClick={onNext}>
          Review Evidence
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

