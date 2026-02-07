import { useState, useCallback, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ChevronLeft, FileText } from "lucide-react";
import {
  type StepName,
  type SessionState,
  type InvestigationResult,
  type ReviewDecisions,
  type MUADraft,
  type FinalizedMUA,
  type EnvironmentSpec,
  type ProcessParams,
  getSession,
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

const STEP_META: Record<StepName, { label: string; description: string }> = {
  define:      { label: 'Define',       description: 'Material & environment' },
  investigate: { label: 'Investigate',  description: 'Evidence search' },
  review:      { label: 'Review',       description: 'Engineer decisions' },
  draft:       { label: 'Draft',        description: 'MUA document' },
  finalize:    { label: 'Finalize',     description: 'Audit & export' },
};

// ---------------------------------------------------------------------------
// Wizard state carried across steps (lightweight -- heavy data lives on server)
// ---------------------------------------------------------------------------

export interface WizardClientState {
  sessionId: string | null;
  material: string | null;
  environment: EnvironmentSpec | null;
  processParams: ProcessParams | null;
  applicationDescription: string | null;
  program: string | null;
  hardware: string | null;
  miulRef: string | null;
  investigation: InvestigationResult | null;
  reviewDecisions: ReviewDecisions | null;
  draft: MUADraft | null;
  finalized: FinalizedMUA | null;
  exportText: string | null;
}

const EMPTY_STATE: WizardClientState = {
  sessionId: null,
  material: null,
  environment: null,
  processParams: null,
  applicationDescription: null,
  program: null,
  hardware: null,
  miulRef: null,
  investigation: null,
  reviewDecisions: null,
  draft: null,
  finalized: null,
  exportText: null,
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MUAWizardV7() {
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
        .then((s: SessionState) => {
          setWizard((prev) => ({
            ...prev,
            sessionId: s.session_id,
            material: s.material,
            environment: s.environment,
            processParams: s.process_params,
            applicationDescription: s.application_description,
            program: s.program,
            hardware: s.hardware,
            miulRef: s.miul_ref,
            investigation: s.investigation,
            reviewDecisions: s.review_decisions,
            draft: s.draft,
            finalized: s.finalized,
          }));
        })
        .catch(() => {
          /* session not found -- start fresh */
        })
        .finally(() => setLoading(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSessionId]);

  // ---- Navigation helpers -------------------------------------------------

  const stepIndex = STEPS.indexOf(currentStep);
  const progressPct = ((stepIndex + 1) / STEPS.length) * 100;

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

  // ---- Patch wizard state helper ------------------------------------------

  const patchWizard = useCallback(
    (patch: Partial<WizardClientState>) => setWizard((prev) => ({ ...prev, ...patch })),
    [],
  );

  // ---- Render -------------------------------------------------------------

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FileText className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold tracking-tight">MUA Wizard v7</h1>
            <p className="text-sm text-muted-foreground">
              Materials Usage Agreement Generator
            </p>
          </div>
        </div>
        {wizard.sessionId && (
          <Badge variant="outline" className="font-mono text-xs">
            Session: {wizard.sessionId.slice(0, 8)}
          </Badge>
        )}
      </div>

      {/* Step progress */}
      <Card>
        <CardContent className="pt-6 pb-4 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">
              Step {stepIndex + 1} of {STEPS.length}:{' '}
              {STEP_META[currentStep].label}
            </span>
            <span className="text-muted-foreground">
              {STEP_META[currentStep].description}
            </span>
          </div>
          <Progress value={progressPct} className="h-2" />
          <div className="flex justify-between">
            {STEPS.map((s, i) => {
              const isActive = s === currentStep;
              const isDone = i < stepIndex;
              return (
                <button
                  key={s}
                  disabled={i > stepIndex}
                  onClick={() => i <= stepIndex && goToStep(s)}
                  className={`text-xs font-medium transition-colors ${
                    isActive
                      ? 'text-primary'
                      : isDone
                        ? 'text-muted-foreground hover:text-primary cursor-pointer'
                        : 'text-muted-foreground/40 cursor-not-allowed'
                  }`}
                >
                  {STEP_META[s].label}
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Back button for steps > 1 */}
      {stepIndex > 0 && (
        <Button variant="ghost" size="sm" onClick={goBack} className="gap-1">
          <ChevronLeft className="h-4 w-4" />
          Back to {STEP_META[STEPS[stepIndex - 1]].label}
        </Button>
      )}

      <Separator />

      {/* Step content */}
      {loading ? (
        <Card>
          <CardContent className="py-16 text-center text-muted-foreground">
            Loading session...
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
