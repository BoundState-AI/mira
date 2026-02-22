import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ArrowRight,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  HelpCircle,
  UserCheck,
  Beaker,
} from "lucide-react";
import {
  type ReviewDecisionType,
  type GapDecisionType,
  type PrecedentDecision,
  type GapDecision,
  type ConflictDecision,
  type ReviewDecisions,
  saveReviewDecisions,
  generateDraft,
} from "@/lib/mua-v7-api";
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
// Types for local state
// ---------------------------------------------------------------------------

interface PrecedentLocal {
  mua_number: string;
  decision: ReviewDecisionType;
  rationale: string;
  autoIncluded: boolean;
  needsExpertise: boolean;
  diverges: boolean;
}

interface GapLocal {
  id: string;
  decision: GapDecisionType | null;
  rationale: string;
}

interface ConflictLocal {
  id: string;
  decision: ReviewDecisionType | null;
  rationale: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MUAReviewStep({ wizard, patchWizard, onNext }: Props) {
  const inv = wizard.investigation;
  const identityCandidates = inv?.material_identity?.all_maptis_codes ?? [];
  const recommendedCode = inv?.code_recommendation?.recommended_code ?? identityCandidates[0]?.material_code ?? null;
  const [confirmedMaptisCode, setConfirmedMaptisCode] = useState<string>(
    wizard.reviewDecisions?.confirmed_maptis_code ?? recommendedCode ?? "",
  );
  const [overrideJustification, setOverrideJustification] = useState<string>(
    wizard.reviewDecisions?.override_justification ?? "",
  );

  // Build initial local review state from investigation data
  const allPrecedents = useMemo(
    () => (inv ? [...inv.supporting_precedents, ...inv.conflicting_precedents] : []),
    [inv],
  );

  const [precedents, setPrecedents] = useState<PrecedentLocal[]>(() => {
    if (!inv) return [];
    return allPrecedents.map((p) => {
      const highRelevance = p.relevance_score >= 0.7 && p.is_supporting;
      return {
        mua_number: p.mua_number,
        decision: highRelevance ? 'include_supporting' : 'include_context',
        rationale: '',
        autoIncluded: highRelevance,
        needsExpertise: p.is_conflicting || p.relevance_score < 0.4,
        diverges: false,
      };
    });
  });

  const [gaps, setGaps] = useState<GapLocal[]>(() => {
    if (!inv) return [];
    return inv.gaps.map((g) => ({ id: g.gap_id, decision: null, rationale: '' }));
  });

  const [conflicts, setConflicts] = useState<ConflictLocal[]>(() => {
    if (!inv) return [];
    return inv.conflicts.map((c) => ({ id: c.conflict_id, decision: null, rationale: '' }));
  });

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const flaggedPrecedents = precedents.filter((p) => p.needsExpertise);

  const totalFlagged = flaggedPrecedents.length + gaps.length + conflicts.length;
  const reviewedFlagged =
    flaggedPrecedents.filter((p) => p.rationale.trim().length > 0 || !p.needsExpertise).length +
    gaps.filter((g) => g.decision !== null).length +
    conflicts.filter((c) => c.decision !== null).length;

  // Require rationale when engineer's decision opposes evidence
  const rationaleRequired = useMemo(() => {
    const issues: string[] = [];
    for (const p of precedents) {
      if (p.diverges && p.rationale.trim().length === 0) {
        const orig = allPrecedents.find((op) => op.mua_number === p.mua_number);
        issues.push(`Rationale required for ${orig?.mua_number ?? p.mua_number} (divergent decision)`);
      }
    }
    return issues;
  }, [precedents, allPrecedents]);

  const allReviewed = reviewedFlagged >= totalFlagged && rationaleRequired.length === 0;
  const requiresCodeConfirmation = identityCandidates.length > 0;
  const hasCodeConfirmation = !requiresCodeConfirmation || Boolean(confirmedMaptisCode);
  const overrideRequired = Boolean(
    requiresCodeConfirmation
      && recommendedCode
      && confirmedMaptisCode
      && confirmedMaptisCode !== recommendedCode
      && !overrideJustification.trim(),
  );
  const canSubmit = allReviewed && hasCodeConfirmation && !overrideRequired && !submitting;

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const updatePrecedent = (mua_number: string, patch: Partial<PrecedentLocal>) => {
    setPrecedents((prev) =>
      prev.map((p) => {
        if (p.mua_number !== mua_number) return p;
        const updated = { ...p, ...patch };
        // Detect divergence: if a conflicting precedent is included as supporting
        const orig = allPrecedents.find((op) => op.mua_number === mua_number);
        if (orig) {
          updated.diverges =
            (orig.is_conflicting && updated.decision === 'include_supporting') ||
            (orig.is_supporting && updated.decision === 'exclude');
        }
        return updated;
      }),
    );
  };

  const updateGap = (id: string, patch: Partial<GapLocal>) => {
    setGaps((prev) => prev.map((g) => (g.id === id ? { ...g, ...patch } : g)));
  };

  const updateConflict = (id: string, patch: Partial<ConflictLocal>) => {
    setConflicts((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  };

  const handleSubmit = async () => {
    if (!wizard.sessionId) return;
    setSubmitting(true);
    setError(null);

    const decisions: ReviewDecisions = {
      all_items_reviewed: false,
      divergence_detected: false,
      precedent_decisions: precedents.map(
        (p): PrecedentDecision => ({
          mua_number: p.mua_number,
          decision: p.decision,
          rationale: p.rationale,
        }),
      ),
      gap_decisions: gaps
        .filter((g) => g.decision !== null)
        .map(
          (g): GapDecision => ({
            gap_id: g.id,
            decision: g.decision!,
            rationale: g.rationale,
          }),
        ),
      conflict_decisions: conflicts
        .filter((c) => c.decision !== null)
        .map(
          (c): ConflictDecision => ({
            conflict_id: c.id,
            decision: c.decision!,
            rationale: c.rationale,
          }),
        ),
      confirmed_maptis_code: requiresCodeConfirmation ? confirmedMaptisCode : null,
      confirmed_maptis_key: null,
      confirmed_maptis_designation: null,
      override_justification:
        requiresCodeConfirmation && confirmedMaptisCode !== recommendedCode
          ? overrideJustification.trim() || null
          : null,
    };

    if (requiresCodeConfirmation) {
      const selected = identityCandidates.find((c) => c.material_code === confirmedMaptisCode) ?? null;
      decisions.confirmed_maptis_key = selected?.material_key ?? null;
      decisions.confirmed_maptis_designation = selected?.designation ?? null;
    }

    try {
      const saveResult = await saveReviewDecisions({ session_id: wizard.sessionId, decisions });
      if (!saveResult.can_generate_draft) {
        setError(
          saveResult.unreviewed_count > 0
            ? `Please review all required items before drafting (${saveResult.unreviewed_count} remaining).`
            : 'Review decisions were saved, but draft generation is not yet allowed.',
        );
        return;
      }
      const draftResult = await generateDraft(wizard.sessionId);
      patchWizard({
        reviewDecisions: decisions,
        draft: draftResult.draft,
      });
      onNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save review');
    } finally {
      setSubmitting(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (!inv) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-muted-foreground">
          No investigation data. Please complete earlier steps first.
        </CardContent>
      </Card>
    );
  }

  const progressPct = totalFlagged > 0 ? (reviewedFlagged / totalFlagged) * 100 : 100;

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card>
        <CardContent className="pt-5 pb-4 space-y-3">
          <div className="flex items-center gap-2">
            <UserCheck className="h-5 w-5 text-primary" />
            <p className="text-sm">
              MIRA gathered <strong>{allPrecedents.length + inv.test_data.length}</strong> evidence
              items.{' '}
              {totalFlagged > 0 ? (
                <>
                  <strong>{totalFlagged}</strong> could use your expertise.
                </>
              ) : (
                'All items auto-categorized. Review and confirm below.'
              )}
            </p>
          </div>
          {totalFlagged > 0 && (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {reviewedFlagged} of {totalFlagged} items reviewed
                </span>
                <span>{Math.round(progressPct)}%</span>
              </div>
              <Progress value={progressPct} className="h-2" />
            </div>
          )}
        </CardContent>
      </Card>

      {requiresCodeConfirmation && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">MAPTIS Code Confirmation</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {recommendedCode && (
              <Alert>
                <AlertTitle>Recommended Code: {recommendedCode}</AlertTitle>
                <AlertDescription>
                  {inv?.code_recommendation?.rationale
                    ?? "Recommendation based on precedent and test coverage."}
                </AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              <Label>Confirm MAPTIS code for draft/final traceability</Label>
              <div className="space-y-2">
                {identityCandidates.slice(0, 20).map((candidate) => {
                  const isSelected = confirmedMaptisCode === candidate.material_code;
                  return (
                    <button
                      key={`${candidate.material_code}-${candidate.rank}`}
                      type="button"
                      onClick={() => setConfirmedMaptisCode(candidate.material_code)}
                      className={`w-full rounded border p-2 text-left ${
                        isSelected ? "border-primary bg-primary/5" : "border-border"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <p className="text-sm font-medium">{candidate.designation}</p>
                          <p className="text-xs text-muted-foreground">
                            code {candidate.material_code}
                            {candidate.relationship ? ` • ${candidate.relationship}` : ""}
                          </p>
                        </div>
                        {recommendedCode === candidate.material_code && (
                          <Badge variant="secondary">Recommended</Badge>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {recommendedCode && confirmedMaptisCode && confirmedMaptisCode !== recommendedCode && (
              <div className="space-y-1.5">
                <Label className="text-xs">Override Justification (required)</Label>
                <Textarea
                  rows={2}
                  placeholder="Explain why you selected a different MAPTIS code than recommended..."
                  value={overrideJustification}
                  onChange={(e) => setOverrideJustification(e.target.value)}
                  className={!overrideJustification.trim() ? "border-amber-400" : ""}
                />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Pre-included precedents */}
      {precedents.filter((p) => p.autoIncluded).length > 0 && (
        <div className="space-y-3">
          <h3 className="text-base font-semibold">Auto-Included Precedents</h3>
          <Card>
            <CardContent className="pt-3 pb-3 space-y-2">
              {precedents
                .filter((p) => p.autoIncluded)
                .map((p) => {
                  const orig = allPrecedents.find((op) => op.mua_number === p.mua_number);
                  return (
                    <div key={p.mua_number} className="flex items-center gap-3 py-1.5 border-b last:border-0">
                      <Checkbox
                        checked={p.decision !== 'exclude'}
                        onCheckedChange={(checked) =>
                          updatePrecedent(p.mua_number, {
                            decision: checked ? 'include_supporting' : 'exclude',
                          })
                        }
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm">{orig?.mua_number}</span>
                          <Badge variant="outline" className="text-xs">
                            {(orig?.relevance_score ?? 0) * 100 | 0}% match
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground truncate">
                          {orig?.material_designation} -- {orig?.environment_description}
                        </p>
                      </div>
                      <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
                    </div>
                  );
                })}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Flagged precedents */}
      {flaggedPrecedents.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-base font-semibold flex items-center gap-2">
            Flagged for Review
            <Badge variant="secondary" className="text-xs">
              <HelpCircle className="h-3 w-3 mr-1" />
              Could use your expertise
            </Badge>
          </h3>
          {flaggedPrecedents.map((p) => {
            const orig = allPrecedents.find((op) => op.mua_number === p.mua_number);
            if (!orig) return null;
            return (
              <Card key={p.mua_number}>
                <CardContent className="pt-4 pb-4 space-y-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold">{orig.mua_number}</span>
                        {orig.is_conflicting && (
                          <Badge variant="destructive" className="text-xs">
                            <AlertTriangle className="h-3 w-3 mr-1" />
                            Conflicting
                          </Badge>
                        )}
                        <Badge variant="outline" className="text-xs">
                          {(orig.relevance_score * 100) | 0}% match
                        </Badge>
                      </div>
                      {orig.supporting_rationale && (
                        <p className="text-sm text-green-700 mt-1">
                          {orig.supporting_rationale}
                        </p>
                      )}
                      {orig.non_applicability_caveat && (
                        <p className="text-sm text-amber-700 mt-1">
                          {orig.non_applicability_caveat}
                        </p>
                      )}
                      {!orig.supporting_rationale && !orig.non_applicability_caveat && orig.relationship_explanation && (
                        <p className="text-sm text-muted-foreground mt-1">
                          {orig.relationship_explanation}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Decision buttons */}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant={p.decision === 'include_supporting' ? 'default' : 'outline'}
                      onClick={() => updatePrecedent(p.mua_number, { decision: 'include_supporting' })}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Include as Supporting
                    </Button>
                    <Button
                      size="sm"
                      variant={p.decision === 'include_context' ? 'default' : 'outline'}
                      onClick={() => updatePrecedent(p.mua_number, { decision: 'include_context' })}
                    >
                      Include as Context
                    </Button>
                    <Button
                      size="sm"
                      variant={p.decision === 'exclude' ? 'destructive' : 'outline'}
                      onClick={() => updatePrecedent(p.mua_number, { decision: 'exclude' })}
                    >
                      <XCircle className="h-3.5 w-3.5" />
                      Exclude
                    </Button>
                  </div>

                  {/* Rationale */}
                  <div className="space-y-1.5">
                    <Label className="text-xs">Rationale</Label>
                    <Textarea
                      rows={2}
                      placeholder="Explain your reasoning..."
                      value={p.rationale}
                      onChange={(e) => updatePrecedent(p.mua_number, { rationale: e.target.value })}
                    />
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Gap decisions */}
      {gaps.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-base font-semibold flex items-center gap-2">
            Evidence Gaps
            <Badge variant="secondary" className="text-xs">
              {gaps.length}
            </Badge>
          </h3>
          {gaps.map((g) => {
            const orig = inv.gaps.find((og) => og.gap_id === g.id);
            if (!orig) return null;
            return (
              <Card key={g.id}>
                <CardContent className="pt-4 pb-4 space-y-3">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <Badge
                        variant={orig.severity === 'critical' ? 'destructive' : 'secondary'}
                        className="text-xs"
                      >
                        {orig.severity}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{orig.dimension}</span>
                    </div>
                    <p className="text-sm">{orig.description}</p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant={g.decision === 'accept_with_rationale' ? 'default' : 'outline'}
                      onClick={() => updateGap(g.id, { decision: 'accept_with_rationale' })}
                    >
                      Accept Gap - Document Rationale
                    </Button>
                    <Button
                      size="sm"
                      variant={g.decision === 'flag_for_testing' ? 'default' : 'outline'}
                      onClick={() => updateGap(g.id, { decision: 'flag_for_testing' })}
                    >
                      Flag for Testing
                    </Button>
                  </div>

                  {g.decision === 'accept_with_rationale' && (
                    <div className="space-y-1.5">
                      <Label className="text-xs">Rationale (required)</Label>
                      <Textarea
                        rows={2}
                        placeholder="Why is this gap acceptable..."
                        value={g.rationale}
                        onChange={(e) => updateGap(g.id, { rationale: e.target.value })}
                        className={!g.rationale.trim() ? 'border-amber-400' : ''}
                      />
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Conflict decisions */}
      {conflicts.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-base font-semibold flex items-center gap-2 text-red-700">
            <AlertTriangle className="h-5 w-5" />
            Conflicts
            <Badge variant="destructive" className="text-xs">
              {conflicts.length}
            </Badge>
          </h3>
          {conflicts.map((c) => {
            const orig = inv.conflicts.find((oc) => oc.conflict_id === c.id);
            if (!orig) return null;
            return (
              <Card key={c.id} className="border-red-200">
                <CardContent className="pt-4 pb-4 space-y-3">
                  <div>
                    <Badge variant="destructive" className="text-xs mb-1">
                      {orig.severity} conflict
                    </Badge>
                    <p className="text-sm">{orig.description}</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Suggested: {orig.recommendation}
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant={c.decision === 'include_supporting' ? 'default' : 'outline'}
                      onClick={() => updateConflict(c.id, { decision: 'include_supporting' })}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Include as Supporting
                    </Button>
                    <Button
                      size="sm"
                      variant={c.decision === 'include_context' ? 'default' : 'outline'}
                      onClick={() => updateConflict(c.id, { decision: 'include_context' })}
                    >
                      Include as Context
                    </Button>
                    <Button
                      size="sm"
                      variant={c.decision === 'exclude' ? 'destructive' : 'outline'}
                      onClick={() => updateConflict(c.id, { decision: 'exclude' })}
                    >
                      <XCircle className="h-3.5 w-3.5" />
                      Exclude
                    </Button>
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-xs">Rationale (required)</Label>
                    <Textarea
                      rows={2}
                      placeholder="How are you addressing this conflict..."
                      value={c.rationale}
                      onChange={(e) => updateConflict(c.id, { rationale: e.target.value })}
                      className={c.decision && !c.rationale.trim() ? 'border-red-400' : ''}
                    />
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Test data table */}
      {inv.test_data.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-base font-semibold flex items-center gap-2">
            <Beaker className="h-5 w-5" />
            MAPTIS Test Data
          </h3>
          <Card>
            <CardContent className="pt-0 pb-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8" />
                    <TableHead>Test</TableHead>
                    <TableHead>Result</TableHead>
                    <TableHead className="w-24">Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {inv.test_data.map((t, i) => {
                    const pass = t.rating && ['A', 'B'].includes(t.rating.toUpperCase());
                    const expired = t.is_current === false;
                    return (
                      <TableRow key={`${t.test_class}-${t.test_number ?? i}`} className={expired ? 'opacity-60' : ''}>
                        <TableCell>
                          {pass ? (
                            <CheckCircle2 className="h-4 w-4 text-green-600" />
                          ) : (
                            <XCircle className="h-4 w-4 text-red-500" />
                          )}
                        </TableCell>
                        <TableCell className="font-medium text-sm">{t.test_class}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {t.rating ?? 'U'}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {t.test_date}
                          {expired && (
                            <Badge variant="outline" className="ml-1 text-[10px] text-orange-600 border-orange-300">
                              Exp
                            </Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Validation errors */}
      {rationaleRequired.length > 0 && (
        <Alert className="border-amber-300 bg-amber-50">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <AlertTitle className="text-amber-800">Rationale Required</AlertTitle>
          <AlertDescription className="text-amber-700">
            <ul className="list-disc ml-4 text-sm space-y-0.5">
              {rationaleRequired.map((msg, i) => (
                <li key={i}>{msg}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {requiresCodeConfirmation && !hasCodeConfirmation && (
        <Alert className="border-amber-300 bg-amber-50">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <AlertTitle className="text-amber-800">MAPTIS Code Required</AlertTitle>
          <AlertDescription className="text-amber-700">
            Confirm the MAPTIS code before generating a draft.
          </AlertDescription>
        </Alert>
      )}

      {overrideRequired && (
        <Alert className="border-amber-300 bg-amber-50">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <AlertTitle className="text-amber-800">Override Justification Required</AlertTitle>
          <AlertDescription className="text-amber-700">
            You selected a different code than the recommendation. Add a brief rationale.
          </AlertDescription>
        </Alert>
      )}

      {/* Error */}
      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Submit */}
      <div className="flex justify-end">
        <Button size="lg" disabled={!canSubmit} onClick={handleSubmit}>
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Generating Draft...
            </>
          ) : (
            <>
              Generate Draft
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
