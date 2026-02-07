import { useState, useCallback, useEffect, useMemo, Fragment } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { PageHelp } from "@/components/PageHelp";
import helpContent from "@/config/helpContent";
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
  "Looking up material codes...",
  "Fetching MAPTIS compatibility ratings...",
  "Constructing MIUL tree structure...",
  "Generating Excel spreadsheet...",
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
  isSubmitting: boolean;
  groceryList: MaterialGroceryList;
}

function ReviewItemCard({ item, onAccept, onCorrect, isSubmitting, groceryList }: ReviewItemCardProps) {
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

        {/* Fields */}
        {isEditing ? (
          <div className="space-y-2 mb-3">
            {Object.entries(item.fields).map(([fieldName, field]) => {
              const options = groceryList[fieldName] || [];
              const listId = `gl-${itemKey}-${fieldName}`;
              return (
                <div key={fieldName} className="flex items-center gap-2">
                  <Label className="w-32 text-xs text-right capitalize">
                    {fieldName.replace(/_/g, " ")}
                  </Label>
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
            {Object.entries(item.fields).map(([fieldName, field]) => (
              <div key={fieldName} className="flex items-center gap-2">
                <span className="text-muted-foreground capitalize text-xs w-28">
                  {fieldName.replace(/_/g, " ")}:
                </span>
                <span className={field.value ? "" : "text-red-500 italic"}>
                  {field.value || "missing"}
                </span>
                <ConfidenceBadge confidence={field.confidence} />
              </div>
            ))}
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
                  disabled={isSubmitting}
                >
                  <Check className="h-3 w-3 mr-1" />
                  Accept As-Is
                </Button>
                <Button size="sm" variant="outline" onClick={() => setIsEditing(true)}>
                  <Edit3 className="h-3 w-3 mr-1" />
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowEvidence(!showEvidence)}
                >
                  <Eye className="h-3 w-3 mr-1" />
                  Evidence
                </Button>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// Main Page Component
// ============================================================================

export default function MIULBuilderV4() {
  const { toast } = useToast();

  // ---- Upload state ----
  const [dtJsonFile, setDtJsonFile] = useState<File | null>(null);
  const [drawingFiles, setDrawingFiles] = useState<FileList | null>(null);
  const [project, setProject] = useState("");

  // ---- Extraction state ----
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractionId, setExtractionId] = useState<string | null>(null);
  const [summary, setSummary] = useState<ExtractionSummary | null>(null);
  const [extractSubStage, setExtractSubStage] = useState(0);

  // ---- Review state ----
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [groceryList, setGroceryList] = useState<MaterialGroceryList>({});
  const [isLoadingReview, setIsLoadingReview] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [reviewFilter, setReviewFilter] = useState<"all" | "open" | "resolved">("all");

  // ---- Build state ----
  const [isBuilding, setIsBuilding] = useState(false);
  const [isApproved, setIsApproved] = useState(false);
  const [buildComplete, setBuildComplete] = useState(false);
  const [buildSubStage, setBuildSubStage] = useState(0);

  // ---- Session resume state ----
  const [recentSessions, setRecentSessions] = useState<SessionInfo[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [sensitiveBuild, setSensitiveBuild] = useState(false);

  // ---- Derived state ----
  const openCount = reviewItems.filter((i) => i.status === "open").length;
  const resolvedCount = reviewItems.filter((i) => i.status !== "open").length;

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
        return "Upload drawing PDFs and Drawing Tree JSON to begin";
      case "extract":
        return EXTRACT_SUBSTAGES[extractSubStage];
      case "review":
        if (reviewItems.length === 0) return "Loading review items...";
        return `${openCount} of ${reviewItems.length} items need your expertise`;
      case "approve":
        if (isApproved && !isBuilding && !buildComplete)
          return "Approved — ready to build MIUL";
        if (isBuilding)
          return BUILD_SUBSTAGES[buildSubStage];
        if (buildComplete)
          return "MIUL built and exported successfully";
        return "All items reviewed — ready for engineer sign-off";
      case "export":
        if (buildComplete) return "MIUL built and exported successfully";
        if (isBuilding) return BUILD_SUBSTAGES[buildSubStage];
        return "Approved — click Build to generate the MIUL Excel";
      default:
        return "";
    }
  }, [currentStage, extractSubStage, openCount, reviewItems.length, isApproved, isBuilding, buildSubStage, buildComplete]);

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

  // ---- Load recent sessions on mount ----
  const loadRecentSessions = useCallback(async () => {
    setIsLoadingSessions(true);
    try {
      const res = await fetch("/api/miul/v4/sessions?limit=10");
      if (res.ok) {
        const data = await res.json();
        setRecentSessions(data.sessions || []);
      }
    } catch {
      // Non-critical -- just don't show sessions
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
        const [reviewRes, groceryRes] = await Promise.all([
          fetch(`/api/miul/v4/extract/${session.extraction_id}/review`),
          fetch(`/api/miul/v4/extract/${session.extraction_id}/materials`),
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
      } catch {
        // If loading fails, we still have the extraction_id set
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
      // Fetch review items and grocery list in parallel
      const [reviewRes, groceryRes] = await Promise.all([
        fetch(`/api/miul/v4/extract/${extId}/review`),
        fetch(`/api/miul/v4/extract/${extId}/materials`),
      ]);

      if (!reviewRes.ok) throw new Error("Failed to load review items");

      const data = await reviewRes.json();
      setReviewItems(data.items || []);
      setSummary(data.summary);

      if (groceryRes.ok) {
        const gData = await groceryRes.json();
        setGroceryList(gData.materials || {});
      }
    } catch (e: any) {
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
              description: `${status.summary?.total_materials ?? "?"} materials found. ${status.summary?.needs_review ?? "?"} need review.`,
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
    if (!dtJsonFile || !drawingFiles || drawingFiles.length === 0) {
      toast({
        title: "Missing files",
        description: "Upload DT JSON and drawing PDFs.",
        variant: "destructive",
      });
      return;
    }

    setIsExtracting(true);
    setExtractSubStage(0);

    try {
      const formData = new FormData();
      formData.append("drawing_tree_json", dtJsonFile);
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
    setBuildSubStage(0);
    try {
      const formData = new FormData();
      formData.append("extraction_id", extractionId);
      formData.append("project", project || "MIUL_V4");

      const response = await fetch("/api/miul/v4/build", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Build failed" }));
        throw new Error(err.detail || "Build failed");
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `MIUL_${project || "V4"}_v4.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      setBuildComplete(true);
      toast({ title: "MIUL Built", description: "Excel file downloaded successfully." });

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

  // ---- Render ----
  const stageStatuses = getStageStatuses(currentStage, buildComplete);

  return (
    <div className="space-y-4 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">MIUL Builder V4</h1>
          <p className="text-muted-foreground">
            Vision extraction with human-in-the-loop review
          </p>
        </div>
        <PageHelp content={helpContent.miulBuilder} />
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
          text={`${summary.total_materials} materials extracted \u00b7 ${summary.auto_approved} auto-approved \u00b7 ${summary.needs_review} flagged for review`}
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
              Upload Drawings
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label className="text-sm font-medium">Drawing Tree JSON</Label>
                <p className="text-xs text-muted-foreground mb-1">From DT Editor</p>
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
              </div>
              <div>
                <Label className="text-sm font-medium">Project Name</Label>
                <p className="text-xs text-muted-foreground mb-1">For Excel output</p>
                <Input
                  placeholder="e.g., DMLLV"
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                />
              </div>
            </div>

            <div>
              <Label className="text-sm font-medium">Drawing PDFs</Label>
              <p className="text-xs text-muted-foreground mb-1">
                Engineering drawings containing material data
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
                disabled={!dtJsonFile || !drawingFiles}
                className="flex-1 h-11 text-base"
              >
                <Sparkles className="h-4 w-4 mr-2" />
                Extract Materials
              </Button>

              {/* Sensitive Build toggle */}
              <label
                className="flex items-center gap-2 cursor-pointer select-none"
                title="Sensitive Build: auto-purge session data from server after build completes"
              >
                <Lock className={cn("h-4 w-4", sensitiveBuild ? "text-amber-600" : "text-slate-300")} />
                <span className="text-xs font-medium text-muted-foreground whitespace-nowrap">
                  Sensitive
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
                Session data will be auto-purged from server after build completes
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Recent Sessions (shown on upload stage) */}
      {currentStage === "upload" && recentSessions.length > 0 && (
        <Card className="border-slate-200 shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <History className="h-4 w-4" />
              Recent Sessions
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="space-y-1">
              {recentSessions.slice(0, 5).map((session) => {
                const s = session.summary as ExtractionSummary | Record<string, never>;
                const totalMaterials = "total_materials" in s ? s.total_materials : 0;
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
                          {totalMaterials > 0 && `${totalMaterials} materials`}
                          {totalMaterials > 0 && timeAgo && " -- "}
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
                MIRA extracted <strong>{summary.total_materials}</strong> materials.{" "}
                <span className="text-emerald-700">
                  {summary.auto_approved} look good.
                </span>{" "}
                {summary.needs_review > 0 && (
                  <span className="text-amber-700">
                    {summary.needs_review} could use your expertise.
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
              Extraction approved. Build the final MIUL with MAPTIS enrichment and export to Excel.
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
            <h2 className="text-xl font-bold text-emerald-900 mb-1">MIUL Complete</h2>
            <p className="text-sm text-slate-600 mt-1 mb-6">
              {summary?.total_materials} materials processed and exported to Excel
            </p>
            <div className="flex items-center justify-center gap-3">
              <Button variant="outline" onClick={handleBuild}>
                <Download className="h-4 w-4 mr-2" />
                Download Again
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setExtractionId(null);
                  setSummary(null);
                  setReviewItems([]);
                  setIsApproved(false);
                  setBuildComplete(false);
                  setDtJsonFile(null);
                  setDrawingFiles(null);
                  setProject("");
                }}
              >
                Start New Extraction
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
