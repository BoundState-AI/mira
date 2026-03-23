import { useState, useCallback, useEffect, useMemo, Fragment } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { ModuleChatButton } from "@/components/mira/ModuleChatButton";
import { PageHelp } from "@/components/PageHelp";
import {
  GuidanceContextIndicator,
  GuidanceField,
  GuidanceInlineHelp,
  GuidanceModeSelector,
  GuidanceProvider,
} from "@/components/guidance";
import helpContent from "@/config/helpContent";
import {
  authorityRegistry,
  createMiulContext,
  miulGuidancePack,
} from "@/lib/guidance/miul-pack";
import type { GuidanceModeName } from "@/lib/guidance/types";
import {
  buildChatContextSummary,
  createModuleChatLaunchState,
  registerRouteModuleChatState,
} from "@/lib/mira-chat-context";
import { cn } from "@/lib/utils";
import {
  Upload,
  Download,
  CheckCircle2,
  AlertTriangle,
  Eye,
  Edit3,
  Loader2,
  FileJson,
  FileSpreadsheet,
  Check,
  X,
  ChevronDown,
  ChevronRight,
  Sparkles,
  ShieldCheck,
  Clock,
  Trash2,
  RotateCcw,
  Lock,
  History,
  type LucideIcon,
} from "lucide-react";

// ============================================================================
// Types
// ============================================================================

type PipelineStageId = "upload" | "extract" | "review" | "approve" | "export";
type StageStatus = "pending" | "active" | "complete";

interface ReviewField {
  value: string | null;
  confidence: number;
  corrected_by?: string;
}

interface ReviewItem {
  item_id?: string;
  part_number: string;
  part_description: string;
  nha: string | null;
  source_file: string;
  source_page: number;
  fields: Record<string, ReviewField>;
  gaps: string[];
  gap_reasons: string[];
  evidence: Array<{
    source_location: string;
    source_text: string;
    confidence: number;
  }>;
  worst_confidence: number;
  status: "open" | "corrected" | "accepted";
  corrected_at?: string;
  accepted_at?: string;
}

// "Grocery list" -- unique material values across the whole extraction
type MaterialGroceryList = Record<string, string[]>;

interface SessionInfo {
  extraction_id: string;
  status: string;
  summary: ExtractionSummary | Record<string, never>;
  created_at: string | null;
  project: string | null;
}

interface ExtractionSummary {
  total_materials: number;
  total_extractions?: number; // raw count before dedup
  needs_review: number;
  auto_approved: number;
}

interface SourceDrawing {
  drawing_id: string;
  drawing_number: string;
  drawing_type: string;
  title: string;
  source_files: string[];
  materials_count: number;
}

// ============================================================================
// Pipeline Configuration
// ============================================================================

const PIPELINE_STAGES: { id: PipelineStageId; label: string; icon: LucideIcon }[] = [
  { id: "upload", label: "Upload", icon: Upload },
  { id: "extract", label: "Extract", icon: Sparkles },
  { id: "review", label: "Review", icon: Eye },
  { id: "approve", label: "Approve", icon: ShieldCheck },
  { id: "export", label: "Export", icon: Download },
];

const STAGE_ORDER: PipelineStageId[] = ["upload", "extract", "review", "approve", "export"];

/** Format a date as a relative time string (e.g. "2h ago", "3d ago"). */
function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

function extractDrawingNumberFromSourceFile(sourceFile: string): string {
  if (!sourceFile) return "";
  const leaf = sourceFile.split(/[\\/]/).pop() || sourceFile;
  const stem = leaf.replace(/\.pdf$/i, "");
  for (const sep of [".DRW", "_DRW", "_drw", "_Drw"]) {
    if (stem.includes(sep)) return stem.split(sep)[0].toUpperCase();
  }
  return (stem.includes("_") ? stem.split("_")[0] : stem).toUpperCase();
}

function getSummaryCounts(summary: ExtractionSummary | null | undefined): {
  extractedSightings: number;
  uniqueParts: number;
  hasUniqueParts: boolean;
} {
  if (!summary) {
    return { extractedSightings: 0, uniqueParts: 0, hasUniqueParts: false };
  }
  const hasUniqueParts = typeof summary.total_extractions === "number";
  return {
    extractedSightings: hasUniqueParts
      ? (summary.total_extractions || 0)
      : (summary.total_materials || 0),
    uniqueParts: summary.total_materials || 0,
    hasUniqueParts,
  };
}

function parseFilenameFromContentDisposition(headerValue: string | null): string | null {
  if (!headerValue) return null;
  const match = headerValue.match(/filename\*?=(?:UTF-8''|\"?)([^\";]+)/i);
  if (!match || !match[1]) return null;
  const raw = match[1].replace(/\"/g, "").trim();
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function getStageStatuses(
  current: PipelineStageId,
  allComplete: boolean,
): Record<PipelineStageId, StageStatus> {
  if (allComplete) {
    return Object.fromEntries(STAGE_ORDER.map((s) => [s, "complete"])) as Record<
      PipelineStageId,
      StageStatus
    >;
  }
  const idx = STAGE_ORDER.indexOf(current);
  return Object.fromEntries(
    STAGE_ORDER.map((s, i) => [s, i < idx ? "complete" : i === idx ? "active" : "pending"]),
  ) as Record<PipelineStageId, StageStatus>;
}

const EXTRACT_SUBSTAGES = [
  "Running local OCR scan on drawing pages...",
  "Sending OCR + images to Sonnet Vision...",
  "Sonnet cross-referencing OCR against drawings...",
  "Pass 2: targeted gap-filling for low-confidence fields...",
  "Finalizing extraction results...",
];

const BUILD_SUBSTAGES = [
  "Converting extraction to V3 format...",
  "Merging with Drawing Tree hierarchy...",
  "Applying environment parameters...",
  "Generating formatted Excel spreadsheet...",
];

// ============================================================================
// Pipeline Tracker Component
// ============================================================================

function PipelineTracker({
  currentStage,
  allComplete,
  detail,
  overallProgress,
  reviewProgress,
}: {
  currentStage: PipelineStageId;
  allComplete: boolean;
  detail: string;
  overallProgress: number;
  reviewProgress?: { done: number; total: number };
}) {
  const statuses = getStageStatuses(currentStage, allComplete);

  return (
    <div className="bg-gradient-to-br from-slate-50 via-white to-slate-50 border rounded-2xl p-6 shadow-sm">
      {/* Stage nodes with connecting lines */}
      <div className="flex items-center justify-between px-2">
        {PIPELINE_STAGES.map((stage, idx) => {
          const status = statuses[stage.id];
          const Icon = stage.icon;
          const nextStatus = idx < PIPELINE_STAGES.length - 1 ? statuses[PIPELINE_STAGES[idx + 1].id] : null;

          return (
            <Fragment key={stage.id}>
              {/* Stage node */}
              <div className="flex flex-col items-center relative z-10">
                <div
                  className={cn(
                    "w-11 h-11 rounded-full flex items-center justify-center transition-all duration-500",
                    status === "complete" &&
                      "bg-emerald-500 text-white shadow-lg shadow-emerald-200/50",
                    status === "active" &&
                      "bg-blue-600 text-white shadow-lg shadow-blue-300/60 ring-[3px] ring-blue-200/70",
                    status === "pending" && "bg-slate-100 text-slate-400 border-2 border-slate-200",
                  )}
                >
                  {status === "complete" ? (
                    <Check className="h-5 w-5" />
                  ) : status === "active" && (currentStage === "extract" || currentStage === "export") ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <Icon className="h-5 w-5" />
                  )}
                </div>
                <span
                  className={cn(
                    "text-xs mt-2 font-semibold tracking-wide transition-colors duration-300",
                    status === "complete" && "text-emerald-700",
                    status === "active" && "text-blue-700",
                    status === "pending" && "text-slate-400",
                  )}
                >
                  {stage.label}
                </span>
                {/* Review count badge */}
                {stage.id === "review" && reviewProgress && status === "active" && (
                  <span className="text-[10px] font-medium text-blue-500 mt-0.5">
                    {reviewProgress.done}/{reviewProgress.total}
                  </span>
                )}
              </div>

              {/* Connecting line */}
              {idx < PIPELINE_STAGES.length - 1 && (
                <div
                  className={cn(
                    "flex-1 h-[3px] rounded-full mx-2 transition-all duration-700",
                    nextStatus === "complete" || nextStatus === "active"
                      ? "bg-emerald-400"
                      : status === "active"
                        ? "bg-gradient-to-r from-blue-400 to-slate-200"
                        : "bg-slate-200",
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
          style={{ width: `${Math.min(overallProgress, 100)}%` }}
        />
      </div>

      {/* Detail text */}
      {detail && (
        <div className="text-center mt-3">
          <span
            className={cn(
              "text-sm",
              currentStage === "extract" || (currentStage === "export" && !allComplete)
                ? "text-blue-600"
                : allComplete
                  ? "text-emerald-700 font-medium"
                  : "text-slate-600",
            )}
          >
            {(currentStage === "extract" || (currentStage === "export" && !allComplete)) && (
              <Loader2 className="inline h-3.5 w-3.5 mr-1.5 animate-spin align-text-bottom" />
            )}
            {detail}
          </span>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Completed Milestone Banner
// ============================================================================

function CompletedMilestone({ icon: Icon, text }: { icon: LucideIcon; text: string }) {
  return (
    <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-emerald-50/80 border border-emerald-100 text-sm text-emerald-700">
      <Icon className="h-4 w-4 shrink-0 text-emerald-500" />
      <span>{text}</span>
      <Check className="h-3.5 w-3.5 ml-auto text-emerald-400" />
    </div>
  );
}

// ============================================================================
// Confidence Badge
// ============================================================================

function ConfidenceBadge({ confidence }: { confidence: number }) {
  if (confidence >= 0.8) {
    return (
      <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200">
        {(confidence * 100).toFixed(0)}%
      </Badge>
    );
  }
  if (confidence >= 0.5) {
    return (
      <Badge variant="outline" className="bg-yellow-50 text-yellow-700 border-yellow-200">
        {(confidence * 100).toFixed(0)}%
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200">
      {confidence > 0 ? `${(confidence * 100).toFixed(0)}%` : "Missing"}
    </Badge>
  );
}

// ============================================================================
// Review Item Card
// ============================================================================

interface ReviewItemCardProps {
  item: ReviewItem;
  onAccept: (itemKey: string) => void;
  onCorrect: (itemKey: string, corrections: Record<string, string>) => void;
  onRemovePart: (itemKey: string, partNumber: string) => void;
  removingPartKey: string | null;
  isSubmitting: boolean;
  groceryList: MaterialGroceryList;
}

interface DrawingRemovalPanelProps {
  drawings: SourceDrawing[];
  removingDrawingId: string | null;
  disabled: boolean;
  onRemove: (drawingId: string) => void;
  description?: string;
}

const ASSEMBLY_LEVEL_FIELDS = new Set([
  "designation",
  "material_spec",
  "process_spec",
  "material_form",
  "uns_code",
]);

function isAssemblyLevelExpectedMissing(item: ReviewItem): boolean {
  const desc = (item.part_description || "").toUpperCase();
  const reasons = (item.gap_reasons || []).join(" ").toUpperCase();
  const hasAssemblySignal =
    desc.includes("ASSEMBLY") ||
    reasons.includes("MATERIAL NOT SPECIFIED AT ASSEMBLY LEVEL");

  if (!hasAssemblySignal) {
    return false;
  }

  const reqFields = ["designation", "material_spec", "process_spec", "material_form"];
  return reqFields.every((fieldName) => {
    const field = item.fields[fieldName];
    return !field?.value;
  });
}

function ReviewItemCard({
  item,
  onAccept,
  onCorrect,
  onRemovePart,
  removingPartKey,
  isSubmitting,
  groceryList,
}: ReviewItemCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const [corrections, setCorrections] = useState<Record<string, string>>({});

  // Use item_id if available (unique across duplicate part numbers), else part_number
  const itemKey = item.item_id || item.part_number;

  const handleSave = () => {
    const changed: Record<string, string> = {};
    for (const [key, val] of Object.entries(corrections)) {
      if (val && val !== (item.fields[key]?.value || "")) {
        changed[key] = val;
      }
    }
    if (Object.keys(changed).length > 0) {
      onCorrect(itemKey, changed);
    }
    setIsEditing(false);
  };

  const isResolved = item.status === "corrected" || item.status === "accepted";
  const isRemovingThisItem = removingPartKey === itemKey;
  const sourceDrawing = extractDrawingNumberFromSourceFile(item.source_file);
  const assemblyExpectedMissing = isAssemblyLevelExpectedMissing(item);
  const acceptLabel = assemblyExpectedMissing ? "Accept (Expected for Assembly)" : "Accept As-Is";
  const humanGuidance = assemblyExpectedMissing
    ? "Recommended action: Accept As-Is. Assembly/sub-assembly drawings often do not define direct material at this level."
    : "Recommended action: Check evidence. Edit values if the drawing clearly specifies material/process; otherwise Accept As-Is.";

  return (
    <Card
      className={cn(
        "mb-3 transition-all duration-300",
        isResolved
          ? "opacity-60 border-emerald-200 bg-emerald-50/30"
          : "border-amber-200 bg-amber-50/20 shadow-sm",
      )}
    >
      <CardContent className="pt-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {isResolved ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-500" />
            )}
            <span className="font-mono font-semibold text-sm">{item.part_number}</span>
            <span className="text-sm text-muted-foreground truncate max-w-[200px]">
              {item.part_description}
            </span>
            <Badge
              variant="secondary"
              className={cn(
                "text-xs",
                item.status === "open" && "bg-amber-100 text-amber-700",
                item.status === "corrected" && "bg-blue-100 text-blue-700",
                item.status === "accepted" && "bg-emerald-100 text-emerald-700",
              )}
            >
              {item.status}
            </Badge>
          </div>
          <div className="flex items-center gap-1">
            <ConfidenceBadge confidence={item.worst_confidence} />
            <span className="text-xs text-muted-foreground ml-1">
              {item.source_file} p{item.source_page}
            </span>
          </div>
        </div>

        <div className="text-xs text-slate-600 mb-3">
          This item is part <span className="font-mono font-semibold">{item.part_number}</span> from drawing{" "}
          <span className="font-mono font-semibold">{sourceDrawing || "UNKNOWN"}</span> (source page {item.source_page}).
        </div>

        {!isResolved && (
          <div
            className={cn(
              "text-xs rounded-lg p-2.5 mb-3 border",
              assemblyExpectedMissing
                ? "text-emerald-800 bg-emerald-50 border-emerald-200"
                : "text-blue-800 bg-blue-50 border-blue-200",
            )}
          >
            {humanGuidance}
          </div>
        )}

        {/* Fields */}
        {isEditing ? (
          <div className="space-y-2 mb-3">
            {Object.entries(item.fields).map(([fieldName, field]) => {
              const options = groceryList[fieldName] || [];
              const listId = `gl-${itemKey}-${fieldName}`;
              return (
                <div key={fieldName} className="flex items-center gap-2">
                  <div className="flex w-32 items-center justify-end gap-1.5">
                    <Label className="text-xs text-right capitalize">
                      {fieldName.replace(/_/g, " ")}
                    </Label>
                    <GuidanceInlineHelp name={`inputs.${fieldName}`} />
                  </div>
                  <div className="flex-1 relative">
                    <Input
                      className="h-8 text-sm"
                      list={options.length > 0 ? listId : undefined}
                      defaultValue={field.value || ""}
                      placeholder={options.length > 0 ? `${options.length} known values...` : ""}
                      onChange={(e) =>
                        setCorrections((prev) => ({ ...prev, [fieldName]: e.target.value }))
                      }
                    />
                    {options.length > 0 && (
                      <datalist id={listId}>
                        {options.map((opt) => (
                          <option key={opt} value={opt} />
                        ))}
                      </datalist>
                    )}
                  </div>
                  <ConfidenceBadge confidence={field.confidence} />
                </div>
              );
            })}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 mb-3 text-sm">
            {Object.entries(item.fields).map(([fieldName, field]) => {
              const expectedBlank =
                assemblyExpectedMissing &&
                ASSEMBLY_LEVEL_FIELDS.has(fieldName) &&
                !field.value;
              return (
                <div key={fieldName} className="flex items-center gap-2">
                  <span className="text-muted-foreground capitalize text-xs w-28">
                    {fieldName.replace(/_/g, " ")}:
                  </span>
                  <span
                    className={
                      field.value
                        ? ""
                        : expectedBlank
                          ? "text-slate-500 italic"
                          : "text-red-500 italic"
                    }
                  >
                    {field.value || (expectedBlank ? "expected at assembly level" : "missing")}
                  </span>
                  <ConfidenceBadge confidence={field.confidence} />
                </div>
              );
            })}
          </div>
        )}

        {/* Gaps */}
        {item.gaps.length > 0 && (
          <div className="text-xs text-amber-700 bg-amber-50 rounded-lg p-2.5 mb-3 border border-amber-100">
            {item.gap_reasons.map((reason, i) => (
              <div key={i}>- {reason}</div>
            ))}
          </div>
        )}

        {/* Evidence toggle */}
        {item.evidence.length > 0 && (
          <div className="mb-3">
            <button
              className="text-xs text-blue-600 flex items-center gap-1 hover:text-blue-800 transition-colors"
              onClick={() => setShowEvidence(!showEvidence)}
            >
              {showEvidence ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {item.evidence.length} evidence source{item.evidence.length > 1 ? "s" : ""}
            </button>
            {showEvidence && (
              <div className="mt-1 text-xs bg-slate-50 rounded-lg p-2 space-y-1 border border-slate-100">
                {item.evidence.map((e, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <Badge variant="outline" className="text-xs shrink-0">
                      {e.source_location}
                    </Badge>
                    <span className="font-mono text-slate-700">{e.source_text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        {!isResolved && (
          <div className="flex gap-2">
            {isEditing ? (
              <>
                <Button size="sm" onClick={handleSave} disabled={isSubmitting}>
                  <Check className="h-3 w-3 mr-1" />
                  Save Correction
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setIsEditing(false)}>
                  <X className="h-3 w-3 mr-1" />
                  Cancel
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAccept(itemKey)}
                  disabled={isSubmitting || !!removingPartKey}
                >
                  <Check className="h-3 w-3 mr-1" />
                  {acceptLabel}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setIsEditing(true)}
                  disabled={isSubmitting || !!removingPartKey}
                >
                  <Edit3 className="h-3 w-3 mr-1" />
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowEvidence(!showEvidence)}
                  disabled={isSubmitting || !!removingPartKey}
                >
                  <Eye className="h-3 w-3 mr-1" />
                  Evidence
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="border-red-200 text-red-700 hover:bg-red-50"
                  onClick={() => onRemovePart(itemKey, item.part_number)}
                  disabled={isSubmitting || !!removingPartKey}
                >
                  {isRemovingThisItem ? (
                    <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                  ) : (
                    <Trash2 className="h-3 w-3 mr-1" />
                  )}
                  Remove Part
                </Button>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DrawingRemovalPanel({
  drawings,
  removingDrawingId,
  disabled,
  onRemove,
  description,
}: DrawingRemovalPanelProps) {
  return (
    <div className="border rounded-xl p-3 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-900">Drawings in this extraction</p>
        <Badge variant="outline">{drawings.length}</Badge>
      </div>
      {drawings.length > 0 ? (
        <div className="max-h-56 overflow-y-auto space-y-2 pr-1">
          {drawings.map((drawing) => {
            const label = drawing.drawing_number || drawing.drawing_id;
            const sourcePreview = drawing.source_files[0] || "";
            const materialLabel = `${drawing.materials_count} material sighting${
              drawing.materials_count === 1 ? "" : "s"
            }`;
            return (
              <div
                key={drawing.drawing_id}
                className="rounded-md border px-3 py-2 flex items-center justify-between gap-2"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{label}</p>
                  <p className="text-xs text-muted-foreground truncate">
                    {materialLabel}
                    {sourcePreview ? ` - ${sourcePreview}` : ""}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="border-red-200 text-red-700 hover:bg-red-50"
                  disabled={disabled || removingDrawingId === drawing.drawing_id}
                  onClick={() => onRemove(drawing.drawing_id)}
                >
                  {removingDrawingId === drawing.drawing_id ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5 mr-1" />
                  )}
                  Remove
                </Button>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No drawing packages found.</p>
      )}
      <p className="text-xs text-muted-foreground">
        {description || "Removing a drawing updates extraction results and rebuilds the review queue."}
      </p>
    </div>
  );
}

// ============================================================================
// Main Page Component
// ============================================================================

export default function MIULBuilderV4() {
  const { t } = useTranslation("miulBuilder");
  const { toast } = useToast();
  const [guidanceMode, setGuidanceMode] = useState<GuidanceModeName>("live");

  // ---- Upload state ----
  const [dtJsonFile, setDtJsonFile] = useState<File | null>(null);
  const [drawingFiles, setDrawingFiles] = useState<FileList | null>(null);
  const [project, setProject] = useState("");

  // ---- Environment config state ----
  const [maxTemp, setMaxTemp] = useState("120");
  const [minTemp, setMinTemp] = useState("0");
  const [maxPressure, setMaxPressure] = useState("14.7");
  const [minPressure, setMinPressure] = useState("0");
  const [fluidType, setFluidType] = useState("Air");
  const [envMedia, setEnvMedia] = useState("Air, VAC");
  const [o2Percent, setO2Percent] = useState("20.9");

  // ---- Extraction state ----
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractionId, setExtractionId] = useState<string | null>(null);
  const [summary, setSummary] = useState<ExtractionSummary | null>(null);
  const [extractSubStage, setExtractSubStage] = useState(0);

  // ---- Review state ----
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [groceryList, setGroceryList] = useState<MaterialGroceryList>({});
  const [sourceDrawings, setSourceDrawings] = useState<SourceDrawing[]>([]);
  const [removingDrawingId, setRemovingDrawingId] = useState<string | null>(null);
  const [removingPartKey, setRemovingPartKey] = useState<string | null>(null);
  const [isLoadingReview, setIsLoadingReview] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [reviewFilter, setReviewFilter] = useState<"all" | "open" | "resolved">("all");

  // ---- Build state ----
  const [isBuilding, setIsBuilding] = useState(false);
  const [isApproved, setIsApproved] = useState(false);
  const [buildComplete, setBuildComplete] = useState(false);
  const [buildSubStage, setBuildSubStage] = useState(0);
  const [buildBlob, setBuildBlob] = useState<Blob | null>(null);
  const [buildFileName, setBuildFileName] = useState<string | null>(null);
  const [builtRowCount, setBuiltRowCount] = useState<number | null>(null);
  const [isEnriching, setIsEnriching] = useState(false);
  const [enrichComplete, setEnrichComplete] = useState(false);
  const [standaloneEnrichFile, setStandaloneEnrichFile] = useState<File | null>(null);

  // ---- Session resume state ----
  const [recentSessions, setRecentSessions] = useState<SessionInfo[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [sensitiveBuild, setSensitiveBuild] = useState(false);
  const guidanceContext = createMiulContext({
    user_mode: guidanceMode,
    program: project || undefined,
    service_environment: envMedia || fluidType,
    pressure_regime:
      Number(maxPressure) >= 265 ? "high" : Number(maxPressure) >= 50 ? "medium" : "low",
  });

  // ---- Derived state ----
  const openCount = reviewItems.filter((i) => i.status === "open").length;
  const resolvedCount = reviewItems.filter((i) => i.status !== "open").length;
  const summaryCounts = getSummaryCounts(summary);

  const filteredItems =
    reviewFilter === "all"
      ? reviewItems
      : reviewFilter === "open"
        ? reviewItems.filter((i) => i.status === "open")
        : reviewItems.filter((i) => i.status !== "open");

  // ---- Pipeline stage computation ----
  const currentStage = useMemo((): PipelineStageId => {
    if (buildComplete) return "export";
    if (isBuilding) return "export";
    if (isApproved) return "export";
    if (extractionId && summary) {
      if (summary.needs_review === 0) return "approve";
      if (reviewItems.length > 0 && openCount === 0) return "approve";
      return "review";
    }
    if (isExtracting) return "extract";
    return "upload";
  }, [isExtracting, extractionId, summary, isApproved, isBuilding, buildComplete, reviewItems.length, openCount]);

  const stageDetail = useMemo(() => {
    switch (currentStage) {
      case "upload":
        return t("stages.uploadDetail", {
          defaultValue:
            "Upload drawing PDFs to begin. Drawing Tree JSON is optional (recommended for accurate hierarchy).",
        });
      case "extract":
        return EXTRACT_SUBSTAGES[extractSubStage];
      case "review":
        if (reviewItems.length === 0) {
        return t("stages.loadingReviewItems", { defaultValue: "Loading review items..." });
        }
        return t("stages.reviewDetail", {
          open: openCount,
          total: reviewItems.length,
          defaultValue: `${openCount} of ${reviewItems.length} items need your expertise`,
        });
      case "approve":
        if (isApproved && !isBuilding && !buildComplete)
          return t("stages.approvedReady", { defaultValue: "Approved — ready to build MIUL" });
        if (isBuilding)
          return BUILD_SUBSTAGES[buildSubStage];
        if (buildComplete)
          return t("stages.builtSuccess", { defaultValue: "MIUL built and exported successfully" });
        return t("stages.reviewedReady", {
          defaultValue: "All items reviewed — ready for engineer sign-off",
        });
      case "export":
        if (buildComplete) {
          return t("stages.builtSuccess", { defaultValue: "MIUL built and exported successfully" });
        }
        if (isBuilding) return BUILD_SUBSTAGES[buildSubStage];
        return t("stages.exportReady", {
          defaultValue: "Approved — click Build to generate the MIUL Excel",
        });
      default:
        return "";
    }
  }, [currentStage, extractSubStage, openCount, reviewItems.length, isApproved, isBuilding, buildSubStage, buildComplete, t]);
  const miulChatLaunchState = useMemo(
    () =>
      createModuleChatLaunchState({
        scopeKey: extractionId ? `miul:${extractionId}` : "miul",
        moduleLabel: "MIUL Builder",
        moduleContext: {
          module: "miul",
          current_stage: currentStage,
          extraction_id: extractionId,
          project: project || undefined,
          drawing_count: drawingFiles?.length || 0,
          source_drawing_count: sourceDrawings.length,
          review_item_count: reviewItems.length,
          open_review_count: openCount,
          resolved_review_count: resolvedCount,
          auto_approved_count: summary?.auto_approved ?? 0,
          flagged_count: summary?.needs_review ?? 0,
          build_complete: buildComplete,
          dt_json_present: Boolean(dtJsonFile),
          fluid_type: fluidType || undefined,
          environment: envMedia || undefined,
          max_pressure: maxPressure || undefined,
          sensitive_build: sensitiveBuild,
        },
        originPath: "/miul",
        originTitle: "MIUL Builder",
        description: "Ground the chat in the active MIUL workflow stage, review queue, and rating-gap routing logic.",
        starterPrompts: [
          "What should I do next in this MIUL workflow?",
          "What is still unresolved in this MIUL build?",
          "When does a rating gap here require a formal MUA?",
        ],
        contextSummary: buildChatContextSummary([
          { label: "Stage", value: currentStage },
          { label: "Extraction", value: extractionId || null },
          { label: "Project", value: project || null },
          { label: "Drawings", value: drawingFiles?.length || null },
          { label: "Review", value: reviewItems.length || null },
          { label: "Open", value: openCount || null },
          { label: "Auto", value: summary?.auto_approved ?? null },
        ]),
      }),
    [
      buildComplete,
      currentStage,
      drawingFiles,
      dtJsonFile,
      envMedia,
      extractionId,
      fluidType,
      maxPressure,
      openCount,
      project,
      resolvedCount,
      reviewItems.length,
      sensitiveBuild,
      sourceDrawings.length,
      summary?.auto_approved,
      summary?.needs_review,
    ],
  );

  useEffect(() => {
    registerRouteModuleChatState("/miul", miulChatLaunchState);
  }, [miulChatLaunchState]);

  const overallProgress = useMemo(() => {
    switch (currentStage) {
      case "upload":
        return 0;
      case "extract":
        return 5 + (extractSubStage / Math.max(EXTRACT_SUBSTAGES.length - 1, 1)) * 20;
      case "review": {
        const pct = reviewItems.length > 0 ? resolvedCount / reviewItems.length : 0;
        return 25 + pct * 45;
      }
      case "approve":
        return 75;
      case "export":
        if (buildComplete) return 100;
        if (isBuilding) return 80 + (buildSubStage / Math.max(BUILD_SUBSTAGES.length - 1, 1)) * 18;
        return 78;
      default:
        return 0;
    }
  }, [currentStage, extractSubStage, reviewItems.length, resolvedCount, isBuilding, buildSubStage, buildComplete]);

  // ---- Sub-stage timers ----
  useEffect(() => {
    if (!isExtracting) {
      setExtractSubStage(0);
      return;
    }
    const interval = setInterval(() => {
      setExtractSubStage((s) => Math.min(s + 1, EXTRACT_SUBSTAGES.length - 1));
    }, 5000);
    return () => clearInterval(interval);
  }, [isExtracting]);

  useEffect(() => {
    if (!isBuilding) {
      setBuildSubStage(0);
      return;
    }
    const interval = setInterval(() => {
      setBuildSubStage((s) => Math.min(s + 1, BUILD_SUBSTAGES.length - 1));
    }, 3000);
    return () => clearInterval(interval);
  }, [isBuilding]);

  // ---- Load recent sessions on mount (with retry for server restarts) ----
  const loadRecentSessions = useCallback(async (retries = 2) => {
    setIsLoadingSessions(true);
    try {
      const res = await fetch("/api/miul/v4/sessions?limit=10");
      if (res.ok) {
        const data = await res.json();
        setRecentSessions(data.sessions || []);
      } else if (res.status === 502 && retries > 0) {
        // Server may be restarting (hot-reload) -- retry after short delay
        await new Promise((r) => setTimeout(r, 2000));
        return loadRecentSessions(retries - 1);
      }
    } catch {
      if (retries > 0) {
        await new Promise((r) => setTimeout(r, 2000));
        return loadRecentSessions(retries - 1);
      }
    } finally {
      setIsLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    loadRecentSessions();
  }, [loadRecentSessions]);

  // ---- Resume a previous session ----
  const handleResumeSession = useCallback(
    async (session: SessionInfo) => {
      setExtractionId(session.extraction_id);
      if (session.project) setProject(session.project);
      setBuiltRowCount(null);
      setBuildComplete(false);
      setBuildBlob(null);
      setBuildFileName(null);
      setEnrichComplete(false);
      setRemovingDrawingId(null);
      setRemovingPartKey(null);

      // Determine where to resume based on session status
      if (session.status === "approved") {
        setIsApproved(true);
        if (session.summary && "total_materials" in session.summary) {
          setSummary(session.summary as ExtractionSummary);
        }
      } else if (session.status === "in_review" || session.status === "unknown") {
        // Load review items and let the pipeline figure out the stage
        if (session.summary && "total_materials" in session.summary) {
          setSummary(session.summary as ExtractionSummary);
        }
      }

      // Always try to load review items -- the stage computation will handle the rest
      try {
        const [reviewRes, groceryRes, drawingsRes] = await Promise.all([
          fetch(`/api/miul/v4/extract/${session.extraction_id}/review`),
          fetch(`/api/miul/v4/extract/${session.extraction_id}/materials`),
          fetch(`/api/miul/v4/extract/${session.extraction_id}/drawings`),
        ]);
        if (reviewRes.ok) {
          const data = await reviewRes.json();
          setReviewItems(data.items || []);
          setSummary(data.summary);
        }
        if (groceryRes.ok) {
          const gData = await groceryRes.json();
          setGroceryList(gData.materials || {});
        }
        if (drawingsRes.ok) {
          const dData = await drawingsRes.json();
          setSourceDrawings(dData.drawings || []);
        } else {
          setSourceDrawings([]);
        }
      } catch {
        // If loading fails, we still have the extraction_id set
        setSourceDrawings([]);
      }

      toast({
        title: "Session resumed",
        description: `Loaded extraction ${session.extraction_id.slice(0, 8)}...`,
      });
    },
    [toast],
  );

  // ---- Delete a session (sensitive-build purge) ----
  const handleDeleteSession = useCallback(
    async (extractionId: string) => {
      try {
        const res = await fetch(`/api/miul/v4/sessions/${extractionId}`, {
          method: "DELETE",
        });
        if (res.ok) {
          setRecentSessions((prev) => prev.filter((s) => s.extraction_id !== extractionId));
          toast({ title: "Session purged", description: "Session data deleted." });
        }
      } catch {
        toast({ title: "Error", description: "Failed to delete session.", variant: "destructive" });
      }
    },
    [toast],
  );

  // ---- Handlers ----

  const loadReviewItems = useCallback(async (extId: string) => {
    setIsLoadingReview(true);
    try {
      // Fetch review items, grocery list, and source drawings in parallel
      const [reviewRes, groceryRes, drawingsRes] = await Promise.all([
        fetch(`/api/miul/v4/extract/${extId}/review`),
        fetch(`/api/miul/v4/extract/${extId}/materials`),
        fetch(`/api/miul/v4/extract/${extId}/drawings`),
      ]);

      if (!reviewRes.ok) throw new Error("Failed to load review items");

      const data = await reviewRes.json();
      setReviewItems(data.items || []);
      setSummary(data.summary);

      if (groceryRes.ok) {
        const gData = await groceryRes.json();
        setGroceryList(gData.materials || {});
      }
      if (drawingsRes.ok) {
        const dData = await drawingsRes.json();
        setSourceDrawings(dData.drawings || []);
      } else {
        setSourceDrawings([]);
      }
    } catch (e: any) {
      setSourceDrawings([]);
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setIsLoadingReview(false);
    }
  }, [toast]);

  const pollExtractionStatus = useCallback(
    (extId: string) => {
      const poll = setInterval(async () => {
        try {
          const res = await fetch(`/api/miul/v4/extract/${extId}/status`);
          if (!res.ok) return; // retry next tick
          const status = await res.json();

          if (status.status === "complete") {
            clearInterval(poll);
            setSummary(status.summary || null);
            toast({
              title: "Extraction complete",
              description: `${status.summary?.total_materials ?? "?"} extracted sightings found. Building unique-part review queue...`,
            });
            await loadReviewItems(extId);
            setIsExtracting(false);
          } else if (status.status === "failed") {
            clearInterval(poll);
            toast({
              title: "Extraction failed",
              description: status.error || "Unknown error",
              variant: "destructive",
            });
            setIsExtracting(false);
          }
          // else: still extracting -- keep polling
        } catch {
          // Network glitch -- keep polling, don't crash
        }
      }, 3000);

      // Safety: stop polling after 20 minutes no matter what
      setTimeout(() => {
        clearInterval(poll);
      }, 20 * 60 * 1000);

      return poll;
    },
    [toast, loadReviewItems],
  );

  const handleExtract = useCallback(async () => {
    if (!drawingFiles || drawingFiles.length === 0) {
      toast({
        title: "Missing files",
        description: "Upload drawing PDFs.",
        variant: "destructive",
      });
      return;
    }

    setIsExtracting(true);
    setBuiltRowCount(null);
    setBuildFileName(null);
    setExtractSubStage(0);
    setSourceDrawings([]);
    setRemovingDrawingId(null);
    setRemovingPartKey(null);

    try {
      const formData = new FormData();
      if (dtJsonFile) {
        formData.append("drawing_tree_json", dtJsonFile);
      }
      for (let i = 0; i < drawingFiles.length; i++) {
        formData.append("drawings", drawingFiles[i]);
      }
      formData.append("project", project);

      // POST returns immediately with extraction_id (no blocking!)
      const response = await fetch("/api/miul/v4/extract", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Extraction failed" }));
        throw new Error(err.detail || "Extraction failed");
      }

      const data = await response.json();
      setExtractionId(data.extraction_id);

      // Start polling for completion
      pollExtractionStatus(data.extraction_id);
    } catch (e: any) {
      toast({ title: "Extraction failed", description: e.message, variant: "destructive" });
      setIsExtracting(false);
    }
  }, [dtJsonFile, drawingFiles, project, toast, pollExtractionStatus]);

  const handleAccept = async (itemKey: string) => {
    if (!extractionId) return;
    setIsSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("reviewer", "engineer");
      formData.append("reason", "");

      const response = await fetch(
        `/api/miul/v4/extract/${extractionId}/review/${encodeURIComponent(itemKey)}/accept`,
        { method: "POST", body: formData },
      );
      if (!response.ok) throw new Error("Failed to accept item");

      setReviewItems((prev) =>
        prev.map((item) =>
          (item.item_id || item.part_number) === itemKey
            ? { ...item, status: "accepted" as const }
            : item,
        ),
      );
      toast({ title: "Accepted", description: `${itemKey.split("::")[0]} accepted as-is.` });
    } catch (e: any) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCorrect = async (itemKey: string, corrections: Record<string, string>) => {
    if (!extractionId) return;
    setIsSubmitting(true);
    try {
      const response = await fetch(
        `/api/miul/v4/extract/${extractionId}/review/${encodeURIComponent(itemKey)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ corrections, reviewer: "engineer" }),
        },
      );
      if (!response.ok) throw new Error("Failed to submit correction");

      setReviewItems((prev) =>
        prev.map((item) =>
          (item.item_id || item.part_number) === itemKey
            ? { ...item, status: "corrected" as const }
            : item,
        ),
      );
      toast({ title: "Corrected", description: `${itemKey.split("::")[0]} correction saved.` });
    } catch (e: any) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemoveDrawing = useCallback(
    async (drawingId: string) => {
      if (!extractionId || !drawingId) return;

      const confirmed = window.confirm(
        `Remove drawing '${drawingId}' from extraction ${extractionId.slice(0, 8)}...? This regenerates the review queue.`,
      );
      if (!confirmed) return;

      setRemovingDrawingId(drawingId);
      try {
        const response = await fetch(
          `/api/miul/v4/extract/${extractionId}/drawings/${encodeURIComponent(drawingId)}?reviewer=engineer`,
          { method: "DELETE" },
        );

        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: "Failed to remove drawing" }));
          throw new Error(err.detail || "Failed to remove drawing");
        }

        setIsApproved(false);
        setBuildComplete(false);
        setBuildBlob(null);
        setBuildFileName(null);
        setBuiltRowCount(null);
        setEnrichComplete(false);

        await loadReviewItems(extractionId);
        toast({
          title: "Drawing removed",
          description: `${drawingId} removed from this extraction session.`,
        });
      } catch (e: any) {
        toast({ title: "Remove failed", description: e.message, variant: "destructive" });
      } finally {
        setRemovingDrawingId(null);
      }
    },
    [extractionId, loadReviewItems, toast],
  );

  const handleRemovePart = useCallback(
    async (itemKey: string, partNumber: string) => {
      if (!extractionId || !itemKey) return;

      const confirmed = window.confirm(
        `Remove part '${partNumber}' from extraction ${extractionId.slice(0, 8)}...? This regenerates the review queue.`,
      );
      if (!confirmed) return;

      setRemovingPartKey(itemKey);
      try {
        const response = await fetch(
          `/api/miul/v4/extract/${extractionId}/parts/${encodeURIComponent(itemKey)}?reviewer=engineer`,
          { method: "DELETE" },
        );

        if (!response.ok) {
          const err = await response.json().catch(() => ({ detail: "Failed to remove part" }));
          throw new Error(err.detail || "Failed to remove part");
        }

        setIsApproved(false);
        setBuildComplete(false);
        setBuildBlob(null);
        setBuildFileName(null);
        setBuiltRowCount(null);
        setEnrichComplete(false);

        await loadReviewItems(extractionId);
        toast({
          title: "Part removed",
          description: `${partNumber} removed from this extraction session.`,
        });
      } catch (e: any) {
        toast({ title: "Remove failed", description: e.message, variant: "destructive" });
      } finally {
        setRemovingPartKey(null);
      }
    },
    [extractionId, loadReviewItems, toast],
  );

  const handleApprove = async () => {
    if (!extractionId) return;
    setIsSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("reviewer", "engineer");

      const response = await fetch(`/api/miul/v4/extract/${extractionId}/approve`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!data.approved) {
        toast({
          title: "Cannot approve yet",
          description: `${data.unresolved_count} items still need review.`,
          variant: "destructive",
        });
        // Re-sync review items from backend to correct any stale local state
        await loadReviewItems(extractionId);
        return;
      }

      setIsApproved(true);
      toast({ title: "Approved", description: "Extraction approved. Ready to build MIUL." });
    } catch (e: any) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleBuild = async () => {
    if (!extractionId) return;
    setIsBuilding(true);
    setBuiltRowCount(null);
    setBuildSubStage(0);
    try {
      const formData = new FormData();
      formData.append("extraction_id", extractionId);
      formData.append("project", project || "MIUL_V4");
      formData.append("max_temp", maxTemp);
      formData.append("min_temp", minTemp);
      formData.append("max_pressure", maxPressure);
      formData.append("min_pressure", minPressure);
      formData.append("fluid_type", fluidType);
      formData.append("environment", envMedia);
      formData.append("o2_percent", o2Percent);

      const response = await fetch("/api/miul/v4/build", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Build failed" }));
        throw new Error(err.detail || "Build failed");
      }

      const miulCountHeader = response.headers.get("X-MIUL-Count");
      if (miulCountHeader) {
        const parsed = Number.parseInt(miulCountHeader, 10);
        setBuiltRowCount(Number.isFinite(parsed) ? parsed : null);
      }
      const downloadedName =
        parseFilenameFromContentDisposition(response.headers.get("Content-Disposition")) ||
        `MIUL_${project || "V4"}_v4.xlsx`;
      setBuildFileName(downloadedName);

      const blob = await response.blob();
      setBuildBlob(blob);

      // Auto-download base MIUL
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = downloadedName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      setBuildComplete(true);
      toast({
        title: "Base MIUL Built",
        description: `${
          miulCountHeader ? `${miulCountHeader} MIUL rows exported.` : "MIUL workbook exported."
        } Use 'Enrich' to add MAPTIS ratings.`,
      });

      // Sensitive build: auto-purge session data after successful download
      if (sensitiveBuild && extractionId) {
        try {
          await fetch(`/api/miul/v4/sessions/${extractionId}`, { method: "DELETE" });
          toast({
            title: "Session purged",
            description: "Sensitive build -- session data deleted from server.",
          });
        } catch {
          // Non-critical -- file is already downloaded
        }
      }
    } catch (e: any) {
      toast({ title: "Build failed", description: e.message, variant: "destructive" });
    } finally {
      setIsBuilding(false);
    }
  };

  const runEnrich = async (
    sourceBlob: Blob,
    sourceName: string,
    downloadName: string,
    markBuildEnriched: boolean,
  ) => {
    setIsEnriching(true);
    try {
      const formData = new FormData();
      formData.append("file", sourceBlob, sourceName);

      const response = await fetch("/api/miul/enrich", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Enrichment failed" }));
        throw new Error(err.detail || "Enrichment failed");
      }

      const enrichedBlob = await response.blob();
      const url = URL.createObjectURL(enrichedBlob);
      const a = document.createElement("a");
      a.href = url;
      a.download = downloadName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      const codesFound = Number.parseInt(response.headers.get("X-Codes-Found") || "0", 10);
      const ratingsEnriched = Number.parseInt(response.headers.get("X-Ratings-Enriched") || "0", 10);
      const ratingsAdded = Number.parseInt(response.headers.get("X-Ratings-Added") || "0", 10);
      const coveragePct = response.headers.get("X-Rating-Coverage-Pct") || "0.0";

      if (markBuildEnriched) {
        setEnrichComplete(true);
      }
      toast({
        title: "MIUL Enriched",
        description: `Codes found: ${Number.isFinite(codesFound) ? codesFound : 0} · Materials enriched: ${
          Number.isFinite(ratingsEnriched) ? ratingsEnriched : 0
        } · Ratings added: ${Number.isFinite(ratingsAdded) ? ratingsAdded : 0} · Coverage: ${coveragePct}%`,
      });
    } catch (e: any) {
      toast({ title: "Enrichment failed", description: e.message, variant: "destructive" });
    } finally {
      setIsEnriching(false);
    }
  };

  const handleEnrichFromBuild = async () => {
    if (!buildBlob) return;
    const sourceName = buildFileName || `MIUL_${project || "V4"}_v4.xlsx`;
    const baseName = sourceName.replace(/\.(xlsx|xlsm)$/i, "");
    const outExt = ".xlsx";
    await runEnrich(
      buildBlob,
      sourceName,
      `${baseName}_enriched${outExt}`,
      true,
    );
  };

  const handleStandaloneEnrich = async () => {
    if (!standaloneEnrichFile) return;
    const sourceName = standaloneEnrichFile.name;
    const baseName = sourceName.replace(/\.(xlsx|xlsm)$/i, "");
    const outExt = ".xlsx";
    const downloadName = `${baseName}_enriched${outExt}`;
    await runEnrich(standaloneEnrichFile, sourceName, downloadName, false);
  };

  // ---- Render ----
  const stageStatuses = getStageStatuses(currentStage, buildComplete);

  return (
    <GuidanceProvider
      schema={miulGuidancePack}
      context={guidanceContext}
      mode={guidanceMode}
      telemetryEnabled
      onModeChange={(newMode) => setGuidanceMode(newMode)}
      authorityRegistry={authorityRegistry}
    >
      <div className="space-y-4 max-w-5xl mx-auto">
      {/* Header */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">
              {t("title", { defaultValue: "MIUL Builder" })}
            </h1>
            <p className="text-muted-foreground">
              {t("description", {
                defaultValue: "Vision extraction with human-in-the-loop review",
              })}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <ModuleChatButton launchState={miulChatLaunchState} />
            <PageHelp content={helpContent.miulBuilder} />
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
          <GuidanceContextIndicator context={guidanceContext} />
          <GuidanceModeSelector
            currentMode={guidanceMode}
            context={guidanceContext}
            onModeChange={(newMode) => setGuidanceMode(newMode)}
          />
        </div>
      </div>

      {/* Pipeline Tracker */}
      <PipelineTracker
        currentStage={currentStage}
        allComplete={buildComplete}
        detail={stageDetail}
        overallProgress={overallProgress}
        reviewProgress={
          currentStage === "review" && reviewItems.length > 0
            ? { done: resolvedCount, total: reviewItems.length }
          : undefined
        }
      />

      {/* Completed milestone summaries */}
      {stageStatuses.upload === "complete" && (
        <CompletedMilestone
          icon={Upload}
          text={`${drawingFiles?.length || 0} PDF${(drawingFiles?.length || 0) > 1 ? "s" : ""} uploaded${dtJsonFile ? ` \u00b7 DT: ${dtJsonFile.name}` : ""}`}
        />
      )}
      {stageStatuses.extract === "complete" && summary && (
        <CompletedMilestone
          icon={Sparkles}
          text={
            summaryCounts.hasUniqueParts
              ? `${summaryCounts.extractedSightings} sightings extracted \u00b7 ${summaryCounts.uniqueParts} unique parts \u00b7 ${summary.auto_approved} auto-approved \u00b7 ${summary.needs_review} flagged for review`
              : `${summaryCounts.extractedSightings} sightings extracted \u00b7 preparing unique-part review queue`
          }
        />
      )}
      {stageStatuses.review === "complete" && (
        <CompletedMilestone
          icon={Eye}
          text={`${reviewItems.length} review items resolved`}
        />
      )}
      {stageStatuses.approve === "complete" && (
        <CompletedMilestone icon={ShieldCheck} text="Build approved by engineer" />
      )}

      {/* ================================================================ */}
      {/* STAGE: Upload */}
      {/* ================================================================ */}
      {currentStage === "upload" && (
        <Card className="border-blue-200 shadow-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Upload className="h-5 w-5 text-blue-600" />
              {t("upload.drawings", { defaultValue: "Upload Drawings" })}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <GuidanceField
                name="inputs.detail_drawing"
                label={t("upload.drawingTree", { defaultValue: "Drawing Tree JSON (Optional)" })}
                className="space-y-1"
              >
                <p className="text-xs text-muted-foreground mb-1">
                  {t("upload.drawingTreeHint", {
                    defaultValue: "From DT Editor. Include for accurate NHA/Parent hierarchy.",
                  })}
                </p>
                <Input
                  type="file"
                  accept=".json"
                  onChange={(e) => setDtJsonFile(e.target.files?.[0] || null)}
                />
                {dtJsonFile && (
                  <p className="text-xs text-emerald-600 mt-1 flex items-center gap-1">
                    <FileJson className="h-3 w-3" />
                    {dtJsonFile.name}
                  </p>
                )}
                {!dtJsonFile && (
                  <p className="text-xs text-amber-600 mt-1">
                    {t("upload.noDrawingTreeWarning", {
                      defaultValue: "No DT JSON selected: build will run in degraded hierarchy mode.",
                    })}
                  </p>
                )}
              </GuidanceField>
              <div>
                <Label className="text-sm font-medium">
                  {t("program.name", { defaultValue: "Project Name" })}
                </Label>
                <p className="text-xs text-muted-foreground mb-1">
                  {t("program.forExcel", { defaultValue: "For Excel output" })}
                </p>
                <Input
                  placeholder="e.g., DMLLV"
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                />
              </div>
            </div>

            {/* Environment Configuration */}
            <div className="border rounded-lg p-3 space-y-3">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">
                  {t("environment.title", { defaultValue: "Use Environment" })}
                </Label>
                <div className="flex gap-1">
                  <Button variant="outline" size="sm" className="h-6 text-xs"
                    onClick={() => { setMaxTemp("120"); setMinTemp("0"); setMaxPressure("14.7"); setMinPressure("0"); setFluidType("Air"); setEnvMedia("Air, VAC"); setO2Percent("20.9"); }}>
                    {t("environment.useDefaults", { defaultValue: "SLS Default" })}
                  </Button>
                  <Button variant="outline" size="sm" className="h-6 text-xs"
                    onClick={() => { setMaxTemp("200"); setMinTemp("-423"); setMaxPressure("6000"); setMinPressure("0"); setFluidType("H2"); setEnvMedia("GH2, LH2"); setO2Percent("0"); }}>
                    {t("environment.h2Service", { defaultValue: "H2 Service" })}
                  </Button>
                  <Button variant="outline" size="sm" className="h-6 text-xs"
                    onClick={() => { setMaxTemp("120"); setMinTemp("-297"); setMaxPressure("3000"); setMinPressure("0"); setFluidType("O2"); setEnvMedia("GOX, LOX"); setO2Percent("100"); }}>
                    {t("environment.o2Service", { defaultValue: "O2 Service" })}
                  </Button>
                </div>
              </div>
              <div className="grid grid-cols-4 gap-2">
                <GuidanceField
                  name="inputs.max_pressure"
                  label="Pressure Min (psia)"
                  className="space-y-1"
                >
                  <Input value={minPressure} onChange={(e) => setMinPressure(e.target.value)} className="h-8 text-sm" />
                </GuidanceField>
                <GuidanceField name="inputs.max_pressure" label="Pressure Max (psia)" className="space-y-1">
                  <Input value={maxPressure} onChange={(e) => setMaxPressure(e.target.value)} className="h-8 text-sm" />
                </GuidanceField>
                <GuidanceField
                  name="inputs.max_temperature"
                  label="Temp Min (F)"
                  className="space-y-1"
                >
                  <Input value={minTemp} onChange={(e) => setMinTemp(e.target.value)} className="h-8 text-sm" />
                </GuidanceField>
                <GuidanceField name="inputs.max_temperature" label="Temp Max (F)" className="space-y-1">
                  <Input value={maxTemp} onChange={(e) => setMaxTemp(e.target.value)} className="h-8 text-sm" />
                </GuidanceField>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <GuidanceField name="inputs.environment" label="O2 Concentration (%)" className="space-y-1">
                  <Input value={o2Percent} onChange={(e) => setO2Percent(e.target.value)} className="h-8 text-sm" />
                </GuidanceField>
                <GuidanceField name="inputs.environment" label="Service Media" className="space-y-1">
                  <Input value={fluidType} onChange={(e) => setFluidType(e.target.value)} className="h-8 text-sm" />
                </GuidanceField>
                <GuidanceField name="inputs.environment" label="Environment" className="space-y-1">
                  <Input value={envMedia} onChange={(e) => setEnvMedia(e.target.value)} className="h-8 text-sm" />
                </GuidanceField>
              </div>
            </div>

            <div>
              <Label className="text-sm font-medium">
                {t("upload.drawings", { defaultValue: "Drawing PDFs" })}
              </Label>
              <p className="text-xs text-muted-foreground mb-1">
                {t("upload.supportedFormats", {
                  defaultValue: "Engineering drawings containing material data",
                })}
              </p>
              <Input
                type="file"
                accept=".pdf"
                multiple
                onChange={(e) => setDrawingFiles(e.target.files)}
              />
              {drawingFiles && drawingFiles.length > 0 && (
                <p className="text-xs text-emerald-600 mt-1">
                  {drawingFiles.length} PDF{drawingFiles.length > 1 ? "s" : ""} selected
                </p>
              )}
            </div>

            <div className="flex items-center gap-4">
              <Button
                onClick={handleExtract}
                disabled={!drawingFiles || drawingFiles.length === 0}
                className="flex-1 h-11 text-base"
              >
                <Sparkles className="h-4 w-4 mr-2" />
                {t("generate.button", { defaultValue: "Extract Materials" })}
              </Button>

              {/* Sensitive Build toggle */}
              <label
                className="flex items-center gap-2 cursor-pointer select-none"
                title="Sensitive Build: auto-purge session data from server after build completes"
              >
                <Lock className={cn("h-4 w-4", sensitiveBuild ? "text-amber-600" : "text-slate-300")} />
                <span className="text-xs font-medium text-muted-foreground whitespace-nowrap">
                  {t("labels.sensitive", { defaultValue: "Sensitive" })}
                </span>
                <input
                  type="checkbox"
                  className="sr-only peer"
                  checked={sensitiveBuild}
                  onChange={(e) => setSensitiveBuild(e.target.checked)}
                />
                <div className={cn(
                  "relative w-9 h-5 rounded-full transition-colors",
                  sensitiveBuild ? "bg-amber-500" : "bg-slate-200",
                )}>
                  <div className={cn(
                    "absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform shadow-sm",
                    sensitiveBuild && "translate-x-4",
                  )} />
                </div>
              </label>
            </div>

            {sensitiveBuild && (
              <p className="text-xs text-amber-600 flex items-center gap-1">
                <Lock className="h-3 w-3" />
                {t("messages.autoPurge", {
                  defaultValue: "Session data will be auto-purged from server after build completes",
                })}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Standalone MIUL Enrich (below upload) */}
      <Card className="border-slate-200 shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-blue-600" />
            {t("enrich.title", { defaultValue: "Standalone MIUL Enrich" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {t("enrich.description", {
              defaultValue:
                "Upload a non-enriched MIUL Excel file and run MAPTIS enrichment without re-running extraction.",
            })}
          </p>
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <Label className="text-sm font-medium">Base MIUL (.xlsx/.xlsm)</Label>
              <Input
                type="file"
                accept=".xlsx,.xlsm"
                onChange={(e) => setStandaloneEnrichFile(e.target.files?.[0] || null)}
              />
              {standaloneEnrichFile && (
                <p className="text-xs text-emerald-600 mt-1 flex items-center gap-1">
                  <FileSpreadsheet className="h-3 w-3" />
                  {standaloneEnrichFile.name}
                </p>
              )}
            </div>
            <Button
              onClick={handleStandaloneEnrich}
              disabled={!standaloneEnrichFile || isEnriching}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {isEnriching ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4 mr-2" />
              )}
              {isEnriching
                ? t("enrich.enriching", { defaultValue: "Enriching..." })
                : t("enrich.uploaded", { defaultValue: "Enrich Uploaded MIUL" })}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Recent Sessions (shown on upload stage) */}
      {currentStage === "upload" && recentSessions.length > 0 && (
        <Card className="border-slate-200 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <History className="h-4 w-4" />
              {t("session.recentSessions", { defaultValue: "Recent Sessions" })}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="space-y-1">
              {recentSessions.slice(0, 5).map((session) => {
                const s = session.summary as ExtractionSummary | Record<string, never>;
                const uniqueParts = "total_materials" in s ? s.total_materials : 0;
                const hasSightings = "total_extractions" in s && typeof s.total_extractions === "number";
                const extractedSightings = hasSightings ? (s.total_extractions as number) : uniqueParts;
                const statusLabel =
                  session.status === "approved"
                    ? "Approved"
                    : session.status === "in_review"
                      ? "In Review"
                      : "Unknown";
                const statusColor =
                  session.status === "approved"
                    ? "text-emerald-600 bg-emerald-50"
                    : session.status === "in_review"
                      ? "text-amber-600 bg-amber-50"
                      : "text-slate-500 bg-slate-50";

                const timeAgo = session.created_at
                  ? formatTimeAgo(new Date(session.created_at))
                  : "";

                return (
                  <div
                    key={session.extraction_id}
                    className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-50 group transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0.5", statusColor)}>
                        {statusLabel}
                      </Badge>
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">
                          {session.project || session.extraction_id.slice(0, 8) + "..."}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {extractedSightings > 0 &&
                            (hasSightings
                              ? `${extractedSightings} sightings \u00b7 ${uniqueParts} parts`
                              : `${extractedSightings} sightings`)}
                          {extractedSightings > 0 && timeAgo && " -- "}
                          {timeAgo}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs"
                        onClick={() => handleResumeSession(session)}
                      >
                        <RotateCcw className="h-3 w-3 mr-1" />
                        Resume
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs text-red-500 hover:text-red-700 hover:bg-red-50"
                        onClick={() => handleDeleteSession(session.extraction_id)}
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
      )}

      {/* ================================================================ */}
      {/* STAGE: Extracting */}
      {/* ================================================================ */}
      {currentStage === "extract" && (
        <Card className="border-blue-200 shadow-md">
          <CardContent className="py-12 text-center">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-50 mb-4">
              <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
            </div>
            <h2 className="text-lg font-semibold text-blue-900 mb-1">
              Extracting Materials
            </h2>
            <p className="text-sm text-blue-600 mb-4">
              {EXTRACT_SUBSTAGES[extractSubStage]}
            </p>

            {/* Sub-stage indicators */}
            <div className="flex items-center justify-center gap-3 mt-6">
              {EXTRACT_SUBSTAGES.map((label, idx) => (
                <div key={idx} className="flex items-center gap-1.5">
                  <div
                    className={cn(
                      "w-2 h-2 rounded-full transition-all duration-500",
                      idx < extractSubStage
                        ? "bg-emerald-400"
                        : idx === extractSubStage
                          ? "bg-blue-500 animate-pulse"
                          : "bg-slate-200",
                    )}
                  />
                  <span
                    className={cn(
                      "text-xs hidden sm:inline transition-colors duration-300",
                      idx === extractSubStage ? "text-blue-700 font-medium" : "text-slate-400",
                    )}
                  >
                    {label.replace("...", "").split(" ").slice(0, 2).join(" ")}
                  </span>
                </div>
              ))}
            </div>

            <p className="text-xs text-slate-400 mt-6">
              This may take a few minutes for large drawing sets
            </p>
          </CardContent>
        </Card>
      )}

      {/* ================================================================ */}
      {/* STAGE: Review */}
      {/* ================================================================ */}
      {currentStage === "review" && summary && (
        <Card className="border-blue-200 shadow-md">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-lg">
              <Eye className="h-5 w-5 text-blue-600" />
              Human Review
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Summary banner */}
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
              <p className="text-sm font-medium text-blue-900">
                {summaryCounts.hasUniqueParts ? (
                  <>
                    MIRA extracted <strong>{summaryCounts.extractedSightings}</strong> sightings and grouped
                    them into <strong>{summaryCounts.uniqueParts}</strong> unique parts.{" "}
                  </>
                ) : (
                  <>
                    MIRA extracted <strong>{summaryCounts.extractedSightings}</strong> sightings.{" "}
                  </>
                )}
                <span className="text-emerald-700">
                  {summary.auto_approved} auto-approved.
                </span>{" "}
                {summary.needs_review > 0 && (
                  <span className="text-amber-700">
                    {summary.needs_review} queued for your review.
                  </span>
                )}
              </p>
            </div>
            {/* Review progress bar */}
            {reviewItems.length > 0 && (
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Review progress</span>
                  <span className="font-medium">
                    {resolvedCount}/{reviewItems.length} reviewed
                  </span>
                </div>
                <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all duration-500"
                    style={{
                      width: `${(resolvedCount / reviewItems.length) * 100}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {/* Filter tabs */}
            <div className="flex gap-2">
              {(["all", "open", "resolved"] as const).map((filter) => (
                <Button
                  key={filter}
                  variant={reviewFilter === filter ? "default" : "outline"}
                  size="sm"
                  onClick={() => setReviewFilter(filter)}
                  className="rounded-full"
                >
                  {filter === "all" && `All (${reviewItems.length})`}
                  {filter === "open" && `Needs Review (${openCount})`}
                  {filter === "resolved" && `Resolved (${resolvedCount})`}
                </Button>
              ))}
            </div>

            <DrawingRemovalPanel
              drawings={sourceDrawings}
              removingDrawingId={removingDrawingId}
              disabled={isSubmitting || !!removingPartKey}
              onRemove={(drawingId) => {
                void handleRemoveDrawing(drawingId);
              }}
            />

            {/* Review items list */}
            {isLoadingReview ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : filteredItems.length > 0 ? (
              <div className="max-h-[600px] overflow-y-auto pr-1">
                {filteredItems.map((item, idx) => (
                  <ReviewItemCard
                    key={`${item.part_number}-${item.source_file}-${item.source_page}-${idx}`}
                    item={item}
                    onAccept={handleAccept}
                    onCorrect={handleCorrect}
                    onRemovePart={handleRemovePart}
                    removingPartKey={removingPartKey}
                    isSubmitting={isSubmitting}
                    groceryList={groceryList}
                  />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">
                {reviewFilter === "open"
                  ? "All items reviewed!"
                  : "No items to show."}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* ================================================================ */}
      {/* STAGE: Approve */}
      {/* ================================================================ */}
      {currentStage === "approve" && !isApproved && (
        <Card className="border-blue-200 shadow-md">
          <CardContent className="py-10 text-center">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-emerald-50 mb-4">
              <ShieldCheck className="h-7 w-7 text-emerald-600" />
            </div>
            <h2 className="text-lg font-semibold mb-1">Ready for Approval</h2>
            <p className="text-sm text-muted-foreground mb-6">
              All {reviewItems.length} review items have been resolved.
              Approve to proceed with MIUL build.
            </p>
            <Button
              onClick={handleApprove}
              disabled={isSubmitting}
              className="h-11 px-8 text-base"
            >
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4 mr-2" />
              )}
              Approve Build
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ================================================================ */}
      {/* STAGE: Export (Build + Download) */}
      {/* ================================================================ */}
      {currentStage === "export" && !buildComplete && !isBuilding && (
        <Card className="border-blue-200 shadow-md">
          <CardContent className="py-10 text-center">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-blue-50 mb-4">
              <FileSpreadsheet className="h-7 w-7 text-blue-600" />
            </div>
            <h2 className="text-lg font-semibold mb-1">Build MIUL</h2>
            <p className="text-sm text-muted-foreground mb-6">
              Extraction approved. Build the base MIUL with tree structure and environment parameters.
              Enrich with MAPTIS ratings separately.
            </p>
            <Button onClick={handleBuild} className="h-11 px-8 text-base">
              <Download className="h-4 w-4 mr-2" />
              Build & Download MIUL
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Building animation */}
      {isBuilding && (
        <Card className="border-blue-200 shadow-md">
          <CardContent className="py-12 text-center">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-50 mb-4">
              <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
            </div>
            <h2 className="text-lg font-semibold text-blue-900 mb-1">Building MIUL</h2>
            <p className="text-sm text-blue-600 mb-4">
              {BUILD_SUBSTAGES[buildSubStage]}
            </p>

            {/* Build sub-stage dots */}
            <div className="flex items-center justify-center gap-4 mt-4">
              {BUILD_SUBSTAGES.map((label, idx) => (
                <div key={idx} className="flex items-center gap-1.5">
                  <div
                    className={cn(
                      "w-2.5 h-2.5 rounded-full transition-all duration-500",
                      idx < buildSubStage
                        ? "bg-emerald-400"
                        : idx === buildSubStage
                          ? "bg-blue-500 animate-pulse"
                          : "bg-slate-200",
                    )}
                  />
                  <span
                    className={cn(
                      "text-xs transition-colors",
                      idx === buildSubStage ? "text-blue-700 font-medium" : "text-slate-400",
                    )}
                  >
                    {label.replace("...", "")}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Build complete */}
      {buildComplete && (
        <Card className="border-emerald-200 shadow-md bg-gradient-to-br from-emerald-50/50 to-white">
          <CardContent className="py-12 text-center">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-emerald-100 mb-4">
              <CheckCircle2 className="h-8 w-8 text-emerald-600" />
            </div>
            <h2 className="text-xl font-bold text-emerald-900 mb-1">
              {enrichComplete ? "MIUL Enriched" : "Base MIUL Built"}
            </h2>
            <p className="text-sm text-slate-600 mt-1 mb-6">
              {enrichComplete
                ? `${builtRowCount ?? "All"} MIUL rows with MAPTIS ratings exported`
                : `${builtRowCount ?? "All"} MIUL rows exported. Enrich to add material codes and ratings.`
              }
            </p>
            <div className="flex items-center justify-center gap-3">
              {!enrichComplete && buildBlob && (
                <Button onClick={handleEnrichFromBuild} disabled={isEnriching} className="bg-blue-600 hover:bg-blue-700">
                  {isEnriching ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4 mr-2" />
                  )}
                  {isEnriching
                    ? t("enrich.enriching", { defaultValue: "Enriching..." })
                    : t("enrich.button", { defaultValue: "Enrich with MAPTIS Ratings" })}
                </Button>
              )}
              <Button variant="outline" onClick={handleBuild}>
                <Download className="h-4 w-4 mr-2" />
                Download Base MIUL
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setExtractionId(null);
                  setSummary(null);
                  setReviewItems([]);
                  setSourceDrawings([]);
                  setRemovingDrawingId(null);
                  setIsApproved(false);
                  setBuildComplete(false);
                  setBuildBlob(null);
                  setBuildFileName(null);
                  setBuiltRowCount(null);
                  setEnrichComplete(false);
                  setStandaloneEnrichFile(null);
                  setDtJsonFile(null);
                  setDrawingFiles(null);
                  setProject("");
                  setMaxTemp("120"); setMinTemp("0");
                  setMaxPressure("14.7"); setMinPressure("0");
                  setFluidType("Air"); setEnvMedia("Air, VAC");
                  setO2Percent("20.9");
                }}
              >
                Start New Extraction
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      </div>
    </GuidanceProvider>
  );
}

