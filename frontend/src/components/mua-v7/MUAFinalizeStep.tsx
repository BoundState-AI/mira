import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Copy,
  Download,
  FileUp,
  Save,
  Loader2,
  ShieldCheck,
  ClipboardCheck,
  FileText,
  Award,
} from "lucide-react";
import {
  type FinalizeRequest,
  type FinalizedMUA,
  type EvidenceStrengthBand,
  finalize,
} from "@/lib/mua-v7-api";
import type { WizardClientState } from "@/pages/MUAWizardV7";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  wizard: WizardClientState;
  patchWizard: (patch: Partial<WizardClientState>) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BAND_COLORS: Record<EvidenceStrengthBand, string> = {
  strong: 'text-green-700 bg-green-50 border-green-300',
  moderate: 'text-yellow-700 bg-yellow-50 border-yellow-300',
  weak: 'text-orange-700 bg-orange-50 border-orange-300',
  insufficient: 'text-red-700 bg-red-50 border-red-300',
};

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MUAFinalizeStep({ wizard, patchWizard }: Props) {
  const [reviewerName, setReviewerName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const finalized = wizard.finalized;
  const inv = wizard.investigation;

  // ---- Pre-finalize view --------------------------------------------------

  const handleFinalize = async (exportFormat?: 'text' | 'nasa') => {
    if (!wizard.sessionId) return;
    setSubmitting(true);
    setError(null);

    try {
      const req: FinalizeRequest = {
        session_id: wizard.sessionId,
        reviewer: reviewerName.trim(),
        export_format: exportFormat ?? 'text',
      };
      const result = await finalize(req);
      patchWizard({
        finalized: result.mua,
        exportText: result.export_text ?? null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Finalization failed');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopy = async () => {
    const text = wizard.exportText ?? buildPlainText(finalized);
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard API may be blocked */
    }
  };

  // ---------------------------------------------------------------------------
  // Post-finalized view
  // ---------------------------------------------------------------------------

  if (finalized) {
    const audit = finalized.audit_trail as Record<string, any>;
    const reviewSummary = (audit?.review_summary ?? {}) as Record<string, any>;
    const draftSummary = (audit?.draft_summary ?? {}) as Record<string, any>;
    const bandCls = BAND_COLORS[finalized.evidence_strength.band];

    return (
      <div className="space-y-6">
        {/* Success banner */}
        <Alert className="border-green-300 bg-green-50">
          <CheckCircle2 className="h-5 w-5 text-green-600" />
          <AlertTitle className="text-green-800 text-base">MUA Finalized</AlertTitle>
          <AlertDescription className="text-green-700">
            {finalized.mua_id} has been finalized and is ready for export.
          </AlertDescription>
        </Alert>

        {/* Summary card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Award className="h-5 w-5 text-primary" />
              Summary
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">Category</span>
                <div className="font-semibold text-lg font-mono">{finalized.category.category}</div>
              </div>
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">Evidence Strength</span>
                <div>
                  <Badge className={`${bandCls} border`}>
                    {finalized.evidence_strength.band.toUpperCase()}
                  </Badge>
                </div>
              </div>
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">Material</span>
                <div className="font-medium text-sm">{finalized.material.input_text}</div>
              </div>
              <div className="space-y-1">
                <span className="text-xs text-muted-foreground">Standard</span>
                <div className="text-sm text-muted-foreground">{finalized.applied_standard_version}</div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Audit trail */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <ShieldCheck className="h-5 w-5" />
              Audit Trail
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <AuditItem label="Items Reviewed" value={reviewSummary.all_items_reviewed ? 1 : 0} />
              <AuditItem label="Gap Decisions" value={reviewSummary.gap_decisions ?? 0} />
              <AuditItem label="Conflict Decisions" value={reviewSummary.conflict_decisions ?? 0} />
              <AuditItem label="Precedent Decisions" value={reviewSummary.precedent_decisions ?? 0} />
              <AuditItem
                label="Facts Verified"
                value={draftSummary.fact_checks_verified ?? 0}
                icon={<CheckCircle2 className="h-3.5 w-3.5 text-green-600" />}
              />
              <AuditItem
                label="Engineering Judgment"
                value={draftSummary.fact_checks_judgment ?? 0}
                icon={<AlertTriangle className="h-3.5 w-3.5 text-yellow-600" />}
              />
              <AuditItem
                label="Unverified"
                value={draftSummary.fact_checks_unverified ?? 0}
                icon={<XCircle className="h-3.5 w-3.5 text-red-500" />}
              />
              <AuditItem
                label="Divergences"
                value={reviewSummary.divergence_detected ? 1 : 0}
                highlight={!!reviewSummary.divergence_detected}
              />
            </div>
          </CardContent>
        </Card>

        {/* Reviewer certification */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Reviewer Certification</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Reviewer</span>
                <p className="font-medium">{finalized.reviewer}</p>
              </div>
              <div>
                <span className="text-muted-foreground">Date</span>
                <p className="font-medium">{finalized.finalized_at}</p>
              </div>
            </div>
            <Separator />
            <p className="text-sm text-muted-foreground italic">
              I certify that I have reviewed the evidence, precedents, gaps, and conflicts
              presented by MIRA for this Materials Usage Agreement. All engineering judgments
              and rationale documented herein represent my professional assessment. I accept
              responsibility for the accuracy and completeness of this MUA.
            </p>
          </CardContent>
        </Card>

        {/* Export actions */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Export</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3">
              <Button onClick={handleCopy} variant="outline">
                {copied ? (
                  <>
                    <ClipboardCheck className="h-4 w-4" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4" />
                    Copy to Clipboard
                  </>
                )}
              </Button>
              <Button
                onClick={() => handleFinalize('nasa')}
                variant="outline"
                disabled={submitting}
              >
                <Download className="h-4 w-4" />
                Export NASA Format
              </Button>
              <Button
                onClick={() => handleFinalize('text')}
                variant="outline"
                disabled={submitting}
              >
                <FileUp className="h-4 w-4" />
                Export to MIUL
              </Button>
              <Button variant="secondary" disabled={submitting}>
                <Save className="h-4 w-4" />
                Save Draft
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Pre-finalize view: certification form
  // ---------------------------------------------------------------------------

  const precedentCount = [...(inv?.supporting_precedents ?? []), ...(inv?.conflicting_precedents ?? [])].length;
  const gapCount = inv?.gaps.length ?? 0;
  const conflictCount = inv?.conflicts.length ?? 0;
  const canFinalize = reviewerName.trim().length > 0 && !submitting;

  return (
    <div className="space-y-6">
      {/* Pre-finalize summary */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            Ready to Finalize
          </CardTitle>
          <CardDescription>
            Review the summary below and certify the MUA for finalization.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div className="space-y-1">
              <span className="text-muted-foreground">Category</span>
              <div className="font-semibold text-lg font-mono">
                {wizard.draft?.category ?? inv?.preliminary_category ?? '--'}
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-muted-foreground">Evidence</span>
              <div>
                {inv?.evidence_strength && (
                  <Badge
                    className={`${BAND_COLORS[inv.evidence_strength.band]} border`}
                  >
                    {inv.evidence_strength.band.toUpperCase()}
                  </Badge>
                )}
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-muted-foreground">Precedents</span>
              <div className="font-medium">{precedentCount}</div>
            </div>
            <div className="space-y-1">
              <span className="text-muted-foreground">Gaps / Conflicts</span>
              <div className="font-medium">
                {gapCount} / {conflictCount}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Applied standard */}
      <Card>
        <CardContent className="pt-5 pb-4">
          <div className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <span className="text-muted-foreground">Applied standard:</span>
            <span className="font-medium">NASA-STD-6016B (current)</span>
          </div>
        </CardContent>
      </Card>

      {/* Certification form */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Reviewer Certification</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="reviewer">Reviewer Name</Label>
              <Input
                id="reviewer"
                placeholder="Full name"
                value={reviewerName}
                onChange={(e) => setReviewerName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Date</Label>
              <Input value={today()} disabled />
            </div>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            I certify that I have reviewed the evidence, precedents, gaps, and conflicts
            presented by MIRA for this Materials Usage Agreement. All engineering judgments
            and rationale documented herein represent my professional assessment. I accept
            responsibility for the accuracy and completeness of this MUA.
          </p>
        </CardContent>
      </Card>

      {/* Error */}
      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Submit */}
      <div className="flex justify-end gap-3">
        <Button
          variant="secondary"
          disabled={!canFinalize}
          onClick={() => handleFinalize()}
        >
          <Save className="h-4 w-4" />
          Save as Draft
        </Button>
        <Button size="lg" disabled={!canFinalize} onClick={() => handleFinalize()}>
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Finalizing...
            </>
          ) : (
            <>
              <CheckCircle2 className="h-4 w-4" />
              Finalize MUA
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small sub-components
// ---------------------------------------------------------------------------

function AuditItem({
  label,
  value,
  icon,
  highlight,
}: {
  label: string;
  value: number;
  icon?: React.ReactNode;
  highlight?: boolean;
}) {
  return (
    <div className="space-y-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className={`font-semibold flex items-center gap-1 ${highlight ? 'text-amber-600' : ''}`}>
        {icon}
        {value}
      </div>
    </div>
  );
}

function buildPlainText(mua: FinalizedMUA | null): string {
  if (!mua) return '';
  const lines: string[] = [];
  lines.push(`MUA: ${mua.mua_id}`);
  lines.push(`Category: ${mua.category.category}`);
  lines.push(`Material: ${mua.material.input_text}`);
  lines.push(`Evidence Strength: ${mua.evidence_strength.band.toUpperCase()} (${mua.evidence_strength.score.toFixed(2)})`);
  lines.push(`Standard: ${mua.applied_standard_version}`);
  lines.push('');
  for (const s of mua.draft.sections) {
    lines.push(`--- ${s.section_number}. ${s.title} ---`);
    lines.push(s.content);
    lines.push('');
  }
  lines.push(`Reviewer: ${mua.reviewer}`);
  lines.push(`Date: ${mua.finalized_at}`);
  lines.push('');
  lines.push(
    'I certify that I have reviewed the evidence, precedents, gaps, and conflicts ' +
    'presented by MIRA for this Materials Usage Agreement. All engineering judgments ' +
    'and rationale documented herein represent my professional assessment. I accept ' +
    'responsibility for the accuracy and completeness of this MUA.'
  );
  return lines.join('\n');
}
