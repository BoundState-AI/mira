import { useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  ArrowRight,
  FileText,
  Edit3,
  Check,
  X,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Info,
} from "lucide-react";
import type { FactCheckStatus, DraftSection, FactCheckResult } from "@/lib/mua-v7-api";
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

const FACT_CHECK_CONFIG: Record<
  FactCheckStatus,
  { icon: typeof CheckCircle2; color: string; label: string }
> = {
  verified:   { icon: CheckCircle2,  color: 'text-green-600',  label: 'Verified' },
  judgment:   { icon: AlertTriangle, color: 'text-yellow-600', label: 'Judgment' },
  unverified: { icon: XCircle,       color: 'text-red-500',    label: 'Unverified' },
};

function FactCheckIndicator({ status, claim }: { status: FactCheckStatus; claim: string }) {
  const cfg = FACT_CHECK_CONFIG[status];
  const Icon = cfg.icon;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={`inline-flex items-center gap-0.5 ${cfg.color} cursor-help`}>
            <Icon className="h-3.5 w-3.5" />
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          <p className="text-xs font-medium">{cfg.label}</p>
          <p className="text-xs text-muted-foreground">{claim}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Section component with inline editing
// ---------------------------------------------------------------------------

function SectionBlock({
  section,
  factChecks,
  onEdit,
}: {
  section: DraftSection;
  factChecks: FactCheckResult[];
  onEdit: (content: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(section.content);

  const handleSave = useCallback(() => {
    onEdit(editValue);
    setEditing(false);
  }, [editValue, onEdit]);

  const handleCancel = useCallback(() => {
    setEditValue(section.content);
    setEditing(false);
  }, [section.content]);

  // Group fact checks by paragraph
  const sectionChecks = factChecks.filter((fc) => fc.section_number === section.number);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="font-semibold text-sm">
          {section.number}. {section.title}
        </h4>
        <div className="flex items-center gap-2">
          {/* Fact check summary for this section */}
          {sectionChecks.length > 0 && (
            <div className="flex items-center gap-1">
              {sectionChecks.map((fc, i) => (
                <FactCheckIndicator key={i} status={fc.status} claim={fc.claim} />
              ))}
            </div>
          )}
          {section.editable && !editing && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEditing(true)}
              className="h-7 px-2 text-xs"
            >
              <Edit3 className="h-3 w-3 mr-1" />
              Edit
            </Button>
          )}
        </div>
      </div>

      {editing ? (
        <div className="space-y-2">
          <Textarea
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            rows={Math.max(4, editValue.split('\n').length + 1)}
            className="font-mono text-sm"
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={handleSave}>
              <Check className="h-3.5 w-3.5" />
              Save
            </Button>
            <Button size="sm" variant="outline" onClick={handleCancel}>
              <X className="h-3.5 w-3.5" />
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground">
          {section.content.split('\n\n').map((para, pi) => {
            const paraChecks = sectionChecks.filter((fc) => fc.paragraph_index === pi);
            return (
              <p
                key={pi}
                className={`mb-2 ${
                  section.editable ? 'cursor-pointer hover:bg-accent/50 rounded px-1 -mx-1 transition-colors' : ''
                }`}
                onClick={() => {
                  if (section.editable) setEditing(true);
                }}
              >
                {para}
                {paraChecks.length > 0 && (
                  <span className="inline-flex items-center gap-0.5 ml-1">
                    {paraChecks.map((fc, i) => (
                      <FactCheckIndicator key={i} status={fc.status} claim={fc.claim} />
                    ))}
                  </span>
                )}
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function MUADraftStep({ wizard, patchWizard, onNext }: Props) {
  const draft = wizard.draft;

  const [sectionEdits, setSectionEdits] = useState<Record<number, string>>({});

  if (!draft) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-muted-foreground">
          No draft available. Please complete the Review step first.
        </CardContent>
      </Card>
    );
  }

  const handleSectionEdit = (sectionNumber: number, content: string) => {
    setSectionEdits((prev) => ({ ...prev, [sectionNumber]: content }));
    // Update the draft in wizard state so it persists
    patchWizard({
      draft: {
        ...draft,
        sections: draft.sections.map((s) =>
          s.number === sectionNumber ? { ...s, content } : s,
        ),
      },
    });
  };

  // Count fact checks by type
  const verified = draft.fact_checks.filter((fc) => fc.status === 'verified').length;
  const judgment = draft.fact_checks.filter((fc) => fc.status === 'judgment').length;
  const unverified = draft.fact_checks.filter((fc) => fc.status === 'unverified').length;
  const editCount = Object.keys(sectionEdits).length;

  return (
    <div className="space-y-6">
      {/* Header info */}
      <Card>
        <CardContent className="pt-5 pb-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-primary" />
              <span className="font-medium">MUA Draft</span>
              <Badge variant="outline" className="font-mono">
                Category {draft.category}
              </Badge>
            </div>
            <Separator orientation="vertical" className="h-4" />
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1 text-green-700">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {verified} verified
              </span>
              <span className="flex items-center gap-1 text-yellow-700">
                <AlertTriangle className="h-3.5 w-3.5" />
                {judgment} judgment
              </span>
              <span className="flex items-center gap-1 text-red-600">
                <XCircle className="h-3.5 w-3.5" />
                {unverified} unverified
              </span>
            </div>
            {editCount > 0 && (
              <>
                <Separator orientation="vertical" className="h-4" />
                <span className="text-muted-foreground">
                  {editCount} section{editCount > 1 ? 's' : ''} edited
                </span>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Process constraints */}
      {draft.process_constraints && draft.process_constraints.length > 0 && (
        <Alert className="border-blue-300 bg-blue-50">
          <Info className="h-4 w-4 text-blue-600" />
          <AlertTitle className="text-blue-800">Process Constraints</AlertTitle>
          <AlertDescription className="text-blue-700">
            <ul className="list-disc ml-4 text-sm space-y-0.5 mt-1">
              {draft.process_constraints.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {/* Document sections */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <FileText className="h-5 w-5" />
            MUA Document
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {draft.sections.map((section, idx) => (
            <div key={section.number}>
              <SectionBlock
                section={section}
                factChecks={draft.fact_checks}
                onEdit={(content) => handleSectionEdit(section.number, content)}
              />
              {idx < draft.sections.length - 1 && <Separator className="mt-4" />}
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Fact check legend */}
      <Card>
        <CardContent className="pt-4 pb-3">
          <p className="text-xs font-medium text-muted-foreground mb-2">Fact Check Legend</p>
          <div className="flex flex-wrap gap-4 text-xs">
            <span className="flex items-center gap-1 text-green-700">
              <CheckCircle2 className="h-3.5 w-3.5" /> Verified against source data
            </span>
            <span className="flex items-center gap-1 text-yellow-700">
              <AlertTriangle className="h-3.5 w-3.5" /> Engineering judgment
            </span>
            <span className="flex items-center gap-1 text-red-600">
              <XCircle className="h-3.5 w-3.5" /> Not yet verified
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Next */}
      <div className="flex justify-end">
        <Button size="lg" onClick={onNext}>
          Finalize
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
