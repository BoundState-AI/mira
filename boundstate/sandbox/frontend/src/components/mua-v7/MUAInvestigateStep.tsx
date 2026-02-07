import { useState } from "react";
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
  Clock,
} from "lucide-react";
import type {
  InvestigationResult,
  PrecedentMatch,
  EvidenceStrengthBand,
  EvidenceStrengthResult,
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
                            {strength.score}/{strength.max_score}
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
                  <Badge variant="outline" className="text-xs">
                    Cat {p.category}
                  </Badge>
                  {p.expired && (
                    <Badge variant="outline" className="text-xs text-orange-600 border-orange-300">
                      <Clock className="h-3 w-3 mr-1" />
                      Expired
                    </Badge>
                  )}
                  {p.is_conflicting && (
                    <Badge variant="destructive" className="text-xs">
                      <AlertTriangle className="h-3 w-3 mr-1" />
                      Conflict ({p.conflict_severity})
                    </Badge>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">
                  {p.material} -- {p.environment_summary}
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
              {/* Relationship explanation -- the core innovation */}
              <div className="rounded-md bg-muted/50 p-3">
                <div className="flex items-start gap-2">
                  <Lightbulb className="h-4 w-4 text-primary mt-0.5 shrink-0" />
                  <div className="text-sm">
                    <span className="font-medium">Why this matters: </span>
                    {p.relationship_explanation}
                  </div>
                </div>
              </div>

              {/* Conflict explanation */}
              {p.is_conflicting && p.conflict_explanation && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Conflict Detail</AlertTitle>
                  <AlertDescription>{p.conflict_explanation}</AlertDescription>
                </Alert>
              )}

              {/* Relevance tags */}
              <div className="flex items-center gap-2">
                {p.physics_relevant && (
                  <Badge variant="outline" className="text-xs">
                    <Beaker className="h-3 w-3 mr-1" />
                    Physics Relevant
                  </Badge>
                )}
                {p.regulatory_relevant && (
                  <Badge variant="outline" className="text-xs">
                    <FileSearch className="h-3 w-3 mr-1" />
                    Regulatory Relevant
                  </Badge>
                )}
                {p.date_issued && (
                  <span className="text-xs text-muted-foreground">
                    Issued: {p.date_issued}
                  </span>
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

export default function MUAInvestigateStep({ wizard, onNext }: Props) {
  const inv = wizard.investigation;

  if (!inv) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-muted-foreground">
          No investigation data. Please complete the Define step first.
        </CardContent>
      </Card>
    );
  }

  const supportingCount = inv.precedents.filter((p) => p.is_supporting).length;
  const conflictingCount = inv.precedents.filter((p) => p.is_conflicting).length;
  const currentTests = inv.test_data.filter((t) => !t.expired).length;
  const expiredTests = inv.test_data.filter((t) => t.expired).length;

  return (
    <div className="space-y-6">
      {/* Summary banner */}
      <Card>
        <CardContent className="pt-5 pb-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <div className="flex items-center gap-1.5">
              <FileSearch className="h-4 w-4 text-primary" />
              <span className="font-medium">{inv.precedents.length} precedents found</span>
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
                {inv.suggested_category}
              </Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Novel material banner */}
      {inv.novel_material && (
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
            {inv.precedents.length}
          </Badge>
        </h3>
        {inv.precedents.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              No precedents found for this material/environment combination.
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {inv.precedents.map((p) => (
              <PrecedentCard key={p.id} p={p} />
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
            <Alert key={c.id} variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>{c.severity === 'hard' ? 'Hard Conflict' : 'Soft Conflict'}</AlertTitle>
              <AlertDescription className="space-y-1">
                <p>{c.description}</p>
                <p className="text-xs opacity-80">
                  Suggested resolution: {c.suggested_resolution}
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
            <Card key={g.id} className="border-orange-200">
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
                      <span className="text-xs text-muted-foreground">{g.category}</span>
                    </div>
                    <p className="text-sm">{g.description}</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Suggested: {g.suggested_action}
                    </p>
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
                {inv.test_data.slice(0, 8).map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center justify-between text-sm py-1 border-b last:border-0"
                  >
                    <div className="flex items-center gap-2">
                      {t.pass ? (
                        <CheckCircle2 className="h-4 w-4 text-green-600" />
                      ) : (
                        <XCircle className="h-4 w-4 text-red-500" />
                      )}
                      <span className="font-medium">{t.test_type}</span>
                      <span className="text-muted-foreground">-- {t.environment}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {t.expired && (
                        <Badge variant="outline" className="text-xs text-orange-600 border-orange-300">
                          Expired
                        </Badge>
                      )}
                      <span className="text-xs text-muted-foreground">{t.date}</span>
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
