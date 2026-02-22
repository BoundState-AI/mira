import { useState, useCallback, useEffect, Fragment } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import {
  ChevronLeft,
  FileText,
  Search,
  Eye,
  FileEdit,
  ShieldCheck,
  Check,
  Loader2,
  History,
  RotateCcw,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import {
  type StepName,
  type SessionDetail,
  type SessionSummary,
  type InvestigationResult,
  type MaterialIdentity,
  type ReviewDecisions,
  type MUADraft,
  type FinalizedMUA,
  type EnvironmentSpec,
  type ProcessParams,
  getSession,
  listSessions,
  deleteSession,
} from "@/lib/mua-v7-api";
import MUADefineStep from "@/components/mua-v7/MUADefineStep";
import MUAInvestigateStep from "@/components/mua-v7/MUAInvestigateStep";
import MUAReviewStep from "@/components/mua-v7/MUAReviewStep";
import MUADraftStep from "@/components/mua-v7/MUADraftStep";
import MUAFinalizeStep from "@/components/mua-v7/MUAFinalizeStep";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS: readonly StepName[] = ['define', 'investigate', 'review', 'draft', 'finalize'];

const STEP_META: Record<StepName, { label: string; description: string; icon: LucideIcon }> = {
  define:      { label: 'Define',       description: 'Material & environment', icon: FileText },
  investigate: { label: 'Investigate',  description: 'Evidence search',        icon: Search },
  review:      { label: 'Review',       description: 'Engineer decisions',     icon: Eye },
  draft:       { label: 'Draft',        description: 'MUA document',           icon: FileEdit },
  finalize:    { label: 'Finalize',     description: 'Audit & export',         icon: ShieldCheck },
};

// ---------------------------------------------------------------------------
// Wizard state carried across steps (lightweight -- heavy data lives on server)
// ---------------------------------------------------------------------------

export interface WizardClientState {
  sessionId: string | null;
  material: string | null;
  materialIdentity: MaterialIdentity | null;
  environment: EnvironmentSpec | null;
  processParams: ProcessParams | null;
  applicationDescription: string | null;
  program: string | null;
  hardware: string | null;
  miulRef: string | null;
  approvedCat3Codes: string[] | null;
  investigation: InvestigationResult | null;
  reviewDecisions: ReviewDecisions | null;
  draft: MUADraft | null;
  finalized: FinalizedMUA | null;
  exportText: string | null;
}

const EMPTY_STATE: WizardClientState = {
  sessionId: null,
  material: null,
  materialIdentity: null,
  environment: null,
  processParams: null,
  applicationDescription: null,
  program: null,
  hardware: null,
  miulRef: null,
  approvedCat3Codes: null,
  investigation: null,
  reviewDecisions: null,
  draft: null,
  finalized: null,
  exportText: null,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type StageStatus = 'pending' | 'active' | 'complete';

function getStageStatuses(
  current: StepName,
  allComplete: boolean,
): Record<StepName, StageStatus> {
  if (allComplete) {
    return Object.fromEntries(STEPS.map((s) => [s, 'complete'])) as Record<StepName, StageStatus>;
  }
  const idx = STEPS.indexOf(current);
  return Object.fromEntries(
    STEPS.map((s, i) => [s, i < idx ? 'complete' : i === idx ? 'active' : 'pending']),
  ) as Record<StepName, StageStatus>;
}

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

const STEP_STATUS_LABEL: Record<string, { label: string; color: string }> = {
  define:      { label: 'Defining',     color: 'text-blue-600 bg-blue-50' },
  investigate: { label: 'Investigating', color: 'text-purple-600 bg-purple-50' },
  review:      { label: 'In Review',    color: 'text-amber-600 bg-amber-50' },
  draft:       { label: 'Drafting',     color: 'text-teal-600 bg-teal-50' },
  finalize:    { label: 'Finalizing',   color: 'text-emerald-600 bg-emerald-50' },
};

// ---------------------------------------------------------------------------
// PipelineTracker — ported from MIULBuilderV4
// ---------------------------------------------------------------------------

function PipelineTracker({
  currentStep,
  allComplete,
  isInvestigating,
}: {
  currentStep: StepName;
  allComplete: boolean;
  isInvestigating: boolean;
}) {
  const { t } = useTranslation("muaWizardV7");
  const statuses = getStageStatuses(currentStep, allComplete);
  const stepIndex = STEPS.indexOf(currentStep);
  const progressPct = allComplete ? 100 : ((stepIndex + 0.5) / STEPS.length) * 100;

  return (
    <div className="bg-gradient-to-br from-slate-50 via-white to-slate-50 border rounded-2xl p-6 shadow-sm">
      {/* Stage nodes with connecting lines */}
      <div className="flex items-center justify-between px-2">
        {STEPS.map((step, idx) => {
          const status = statuses[step];
          const meta = STEP_META[step];
          const Icon = meta.icon;
          const nextStatus = idx < STEPS.length - 1 ? statuses[STEPS[idx + 1]] : null;
          const showSpinner = status === 'active' && (step === 'investigate' && isInvestigating);

          return (
            <Fragment key={step}>
              {/* Stage node */}
              <div className="flex flex-col items-center relative z-10">
                <div
                  className={cn(
                    'w-11 h-11 rounded-full flex items-center justify-center transition-all duration-500',
                    status === 'complete' &&
                      'bg-emerald-500 text-white shadow-lg shadow-emerald-200/50',
                    status === 'active' &&
                      'bg-blue-600 text-white shadow-lg shadow-blue-300/60 ring-[3px] ring-blue-200/70',
                    status === 'pending' &&
                      'bg-slate-100 text-slate-400 border-2 border-slate-200',
                  )}
                >
                  {status === 'complete' ? (
                    <Check className="h-5 w-5" />
                  ) : showSpinner ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <Icon className="h-5 w-5" />
                  )}
                </div>
                <span
                  className={cn(
                    'text-xs mt-2 font-semibold tracking-wide transition-colors duration-300',
                    status === 'complete' && 'text-emerald-700',
                    status === 'active' && 'text-blue-700',
                    status === 'pending' && 'text-slate-400',
                  )}
                >
                  {t(`steps.${step}.label`, { defaultValue: meta.label })}
                </span>
              </div>

              {/* Connecting line */}
              {idx < STEPS.length - 1 && (
                <div
                  className={cn(
                    'flex-1 h-[3px] rounded-full mx-2 transition-all duration-700',
                    nextStatus === 'complete' || nextStatus === 'active'
                      ? 'bg-emerald-400'
                      : status === 'active'
                        ? 'bg-gradient-to-r from-blue-400 to-slate-200'
                        : 'bg-slate-200',
                  )}
                />
              )}
            </Fragment>
          );
        })}
      </div>

      {/* Overall progress bar */}
      <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden mt-5">
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500 via-blue-400 to-emerald-500 transition-all duration-1000 ease-out"
          style={{ width: `${Math.min(progressPct, 100)}%` }}
        />
      </div>

      {/* Detail text */}
      <div className="text-center mt-3">
        <span
          className={cn(
            'text-sm',
            allComplete
              ? 'text-emerald-700 font-medium'
              : 'text-slate-600',
          )}
        >
          {allComplete
            ? t("status.finalized", { defaultValue: "MUA finalized" })
            : t("status.stepOf", {
                step: stepIndex + 1,
                total: STEPS.length,
                description: t(`steps.${currentStep}.description`, {
                  defaultValue: STEP_META[currentStep].description,
                }),
                defaultValue: `Step ${stepIndex + 1} of ${STEPS.length}: ${STEP_META[currentStep].description}`,
              })}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SessionResumeBar — ported from MIULBuilderV4
// ---------------------------------------------------------------------------

function SessionResumeBar({
  onResume,
}: {
  onResume: (session: SessionSummary) => void;
}) {
  const { t } = useTranslation("muaWizardV7");
  const { toast } = useToast();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    setIsLoading(true);
    listSessions()
      .then((data) => {
        setSessions(data.sessions.filter(
          (s) => s.status !== 'abandoned',
        ).slice(0, 5));
      })
      .catch(() => { /* non-critical */ })
      .finally(() => setIsLoading(false));
  }, []);

  const handleDelete = useCallback(
    async (sessionId: string) => {
      try {
        await deleteSession(sessionId);
        setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
        toast({
          title: t("toasts.sessionDeleted", { defaultValue: "Session deleted" }),
          description: t("toasts.sessionDataRemoved", { defaultValue: "Session data removed." }),
        });
      } catch {
        toast({
          title: t("toasts.error", { defaultValue: "Error" }),
          description: t("toasts.failedDelete", { defaultValue: "Failed to delete session." }),
          variant: 'destructive',
        });
      }
    },
    [toast, t],
  );

  if (isLoading || sessions.length === 0) return null;

  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <History className="h-4 w-4" />
          {t("recentSessions.title", { defaultValue: "Recent Sessions" })}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="space-y-1">
          {sessions.map((session) => {
            const stepCfg = STEP_STATUS_LABEL[session.current_step] ?? {
              label: session.current_step,
              color: 'text-slate-500 bg-slate-50',
            };
            const timeAgo = session.updated_at
              ? formatTimeAgo(new Date(session.updated_at))
              : '';

            return (
              <div
                key={session.session_id}
                className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-50 group transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Badge
                    variant="outline"
                    className={cn('text-[10px] px-1.5 py-0.5', stepCfg.color)}
                  >
                    {stepCfg.label}
                  </Badge>
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">
                      {session.material_input || session.session_id.slice(0, 8) + '...'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {session.center && `${session.center}`}
                      {session.center && timeAgo && ' -- '}
                      {timeAgo}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => onResume(session)}
                  >
                    <RotateCcw className="h-3 w-3 mr-1" />
                    {t("buttons.resume", { defaultValue: "Resume" })}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs text-red-500 hover:text-red-700 hover:bg-red-50"
                    onClick={() => handleDelete(session.session_id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function MUAWizardV7() {
  const { t } = useTranslation("muaWizardV7");
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  const currentStep = (searchParams.get('step') as StepName) || 'define';
  const urlSessionId = searchParams.get('session');

  const [wizard, setWizard] = useState<WizardClientState>({
    ...EMPTY_STATE,
    sessionId: urlSessionId,
  });
  const [loading, setLoading] = useState(false);

  // Restore session from URL on mount
  useEffect(() => {
    if (urlSessionId && !wizard.investigation) {
      setLoading(true);
      getSession(urlSessionId)
        .then((s: SessionDetail) => {
          setWizard((prev) => {
            const sameSession = prev.sessionId === s.session_id;
            // Guard against stale restore responses clobbering fresh poll results.
            const effectiveInvestigation =
              s.investigation ?? (sameSession ? prev.investigation : null);

            return {
              ...prev,
              sessionId: s.session_id,
              material: s.material_input,
              materialIdentity:
                effectiveInvestigation?.material_identity
                ?? s.material_identity
                ?? (sameSession ? prev.materialIdentity : null),
              environment: effectiveInvestigation?.environment ?? null,
              processParams: effectiveInvestigation?.process_params ?? null,
              applicationDescription: effectiveInvestigation?.environment?.application ?? null,
              approvedCat3Codes: s.approved_cat3_codes ?? null,
              investigation: effectiveInvestigation,
              reviewDecisions: s.review_decisions ?? (sameSession ? prev.reviewDecisions : null),
              draft: s.draft ?? (sameSession ? prev.draft : null),
              finalized: s.finalized_mua ?? (sameSession ? prev.finalized : null),
            };
          });
        })
        .catch(() => {
          /* session not found -- clear stale ID and start fresh */
          setWizard((prev) => ({ ...prev, sessionId: null }));
          setSearchParams({}, { replace: true });
        })
        .finally(() => setLoading(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSessionId]);

  // ---- Navigation helpers -------------------------------------------------

  const stepIndex = STEPS.indexOf(currentStep);

  const goToStep = useCallback(
    (step: StepName, sessionId?: string) => {
      const params: Record<string, string> = { step };
      const sid = sessionId ?? wizard.sessionId;
      if (sid) params.session = sid;
      setSearchParams(params, { replace: false });
    },
    [wizard.sessionId, setSearchParams],
  );

  const goBack = useCallback(() => {
    if (stepIndex > 0) goToStep(STEPS[stepIndex - 1]);
  }, [stepIndex, goToStep]);

  // ---- Session resume handler ----------------------------------------------

  const handleResumeSession = useCallback(
    async (session: SessionSummary) => {
      setLoading(true);
      try {
        const s = await getSession(session.session_id);
        setWizard({
          ...EMPTY_STATE,
          sessionId: s.session_id,
          material: s.material_input,
          materialIdentity: s.investigation?.material_identity ?? s.material_identity ?? null,
          environment: s.investigation?.environment ?? null,
          processParams: s.investigation?.process_params ?? null,
          applicationDescription: s.investigation?.environment?.application ?? null,
          approvedCat3Codes: s.approved_cat3_codes ?? null,
          investigation: s.investigation,
          reviewDecisions: s.review_decisions,
          draft: s.draft,
          finalized: s.finalized_mua,
        });
        goToStep(s.current_step, s.session_id);
        toast({
          title: t("toasts.sessionResumed", { defaultValue: "Session resumed" }),
          description: t("toasts.loadedSession", {
            session: `${s.session_id.slice(0, 8)}...`,
            defaultValue: `Loaded session ${s.session_id.slice(0, 8)}...`,
          }),
        });
      } catch {
        toast({
          title: t("toasts.error", { defaultValue: "Error" }),
          description: t("toasts.failedResume", { defaultValue: "Failed to resume session." }),
          variant: 'destructive',
        });
      } finally {
        setLoading(false);
      }
    },
    [goToStep, toast, t],
  );

  // ---- Patch wizard state helper ------------------------------------------

  const patchWizard = useCallback(
    (patch: Partial<WizardClientState>) => setWizard((prev) => ({ ...prev, ...patch })),
    [],
  );

  // ---- Derived state -------------------------------------------------------

  const isInvestigating = currentStep === 'investigate' && wizard.sessionId !== null && wizard.investigation === null;
  const allComplete = wizard.finalized !== null;

  // ---- Render -------------------------------------------------------------

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FileText className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {t("title", { defaultValue: "MUA Wizard v7" })}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t("description", { defaultValue: "Materials Usage Agreement Generator" })}
            </p>
          </div>
        </div>
        {wizard.sessionId && (
          <Badge variant="outline" className="font-mono text-xs">
            {t("session", { defaultValue: "Session" })}: {wizard.sessionId.slice(0, 8)}
          </Badge>
        )}
      </div>

      {/* Pipeline Tracker (replaces old Progress bar) */}
      <PipelineTracker
        currentStep={currentStep}
        allComplete={allComplete}
        isInvestigating={isInvestigating}
      />

      {/* Back button for steps > 1 */}
      {stepIndex > 0 && (
        <Button variant="ghost" size="sm" onClick={goBack} className="gap-1">
          <ChevronLeft className="h-4 w-4" />
          {t("buttons.backTo", {
            step: t(`steps.${STEPS[stepIndex - 1]}.label`, {
              defaultValue: STEP_META[STEPS[stepIndex - 1]].label,
            }),
            defaultValue: `Back to ${STEP_META[STEPS[stepIndex - 1]].label}`,
          })}
        </Button>
      )}

      <Separator />

      {/* Session resume bar (shown on Define step when no session is active) */}
      {currentStep === 'define' && !wizard.sessionId && (
        <SessionResumeBar onResume={handleResumeSession} />
      )}

      {/* Step content */}
      {loading ? (
        <Card>
          <CardContent className="py-16 text-center text-muted-foreground">
            {t("loadingSession", { defaultValue: "Loading session..." })}
          </CardContent>
        </Card>
      ) : (
        <>
          {currentStep === 'define' && (
            <MUADefineStep wizard={wizard} patchWizard={patchWizard} onNext={(sid) => goToStep('investigate', sid)} />
          )}
          {currentStep === 'investigate' && (
            <MUAInvestigateStep wizard={wizard} patchWizard={patchWizard} onNext={() => goToStep('review')} />
          )}
          {currentStep === 'review' && (
            <MUAReviewStep wizard={wizard} patchWizard={patchWizard} onNext={() => goToStep('draft')} />
          )}
          {currentStep === 'draft' && (
            <MUADraftStep wizard={wizard} patchWizard={patchWizard} onNext={() => goToStep('finalize')} />
          )}
          {currentStep === 'finalize' && (
            <MUAFinalizeStep wizard={wizard} patchWizard={patchWizard} />
          )}
        </>
      )}
    </div>
  );
}
