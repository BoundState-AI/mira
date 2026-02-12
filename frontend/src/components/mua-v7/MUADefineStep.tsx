import { useState, useEffect, useRef, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Search,
  Thermometer,
  Gauge,
  Wind,
  ArrowRight,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Flame,
  Snowflake,
  Atom,
} from "lucide-react";
import {
  type MaterialIntelCandidate,
  type MaterialResolution,
  type MaterialIntelResponse,
  type MIULImportResponse,
  type MIULImportBucket,
  type EnvironmentSpec,
  type ProcessParams,
  type InvestigateRequest,
  type IssueCode,
  type IssueCodeInfo,
  importMIULWorkbook,
  getMaterialIntel,
  resolveMaterial,
  investigate,
  previewIssues,
} from "@/lib/mua-v7-api";
import type { WizardClientState } from "@/pages/MUAWizardV7";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  wizard: WizardClientState;
  patchWizard: (patch: Partial<WizardClientState>) => void;
  onNext: (sessionId: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MEDIUM_OPTIONS = ['Air', 'GOX', 'LOX', 'GN2', 'LN2', 'Helium', 'Hydrogen', 'NTO', 'MMH', 'Other'] as const;
const LOCATION_OPTIONS = [
  { value: 'habitable', label: 'Habitable' },
  { value: 'non-habitable', label: 'Non-Habitable' },
  { value: 'external', label: 'External / EVA' },
] as const;

const HABITABLE_DEFAULTS: Partial<EnvironmentSpec> = {
  o2_percent: 21,
  pressure_psia: 14.7,
  temp_min_f: 60,
  temp_max_f: 85,
  medium: 'Air',
  application: '',
};

// S-5 / D-3 fix: Check MaterialClass via backend resolution,
// not substring matching on free text.
function isProcessSensitive(res: MaterialResolution | null): boolean {
  if (!res) return false;
  return res.is_process_sensitive;
}

interface MaterialCandidate {
  name: string;
  spec: string;
  score: number;
  material_code: string | null;
  material_key: number | null;
}

function normalizeCandidate(raw: unknown): MaterialCandidate | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;

  const name =
    (typeof row.name === "string" && row.name.trim()) ||
    (typeof row.canonical_name === "string" && row.canonical_name.trim()) ||
    "";

  const materialCode =
    (typeof row.material_code === "string" && row.material_code.trim()) ||
    (typeof row.spec === "string" && row.spec.trim()) ||
    "";

  if (!name && !materialCode) return null;

  const scoreRaw = row.score ?? row.similarity;
  const score = typeof scoreRaw === "number" ? scoreRaw : 0;
  const materialKey =
    typeof row.material_key === "number"
      ? row.material_key
      : typeof row.material_key === "string" && row.material_key.trim()
        ? Number(row.material_key)
        : null;

  return {
    name: name || materialCode,
    spec: materialCode || name,
    score,
    material_code: materialCode || null,
    material_key: Number.isFinite(materialKey ?? NaN) ? materialKey : null,
  };
}

function calloutMatchLabel(score: number): string {
  if (score >= 0.98) return "callout match: very strong";
  if (score >= 0.9) return "callout match: strong";
  if (score >= 0.8) return "callout match: moderate";
  return "callout match: weak";
}

function parseApprovedCat3Codes(input: string): string[] {
  const matches = input.match(/\b10[3-8]\b/g) ?? [];
  return Array.from(new Set(matches));
}

function isO2ServiceMedium(medium: string): boolean {
  const normalized = medium.trim().toUpperCase().replace(/\s+/g, "_");
  return [
    "GOX",
    "LOX",
    "OXYGEN",
    "O2",
    "ENRICHED_AIR",
    "ENRICHED_O2",
  ].includes(normalized);
}

function buildCandidateWhy(
  candidate: MaterialIntelCandidate,
  baseline: MaterialIntelCandidate | null,
  mixedInput: boolean,
): {
  summary: string;
  chooseReasons: string[];
  verifyChecks: string[];
  diffs: string[];
  pickIf: string[];
  avoidIf: string[];
} {
  const chooseReasons: string[] = [];
  const verifyChecks: string[] = [];
  const diffs: string[] = [];
  const pickIf: string[] = [];
  const avoidIf: string[] = [];

  const formConditionParts = [
    candidate.form ? `form: ${candidate.form}` : null,
    candidate.condition ? `condition: ${candidate.condition}` : null,
  ].filter((p): p is string => Boolean(p));

  if (candidate.score >= 0.98) {
    chooseReasons.push("The callout match is very strong for this designation.");
  } else if (candidate.score >= 0.9) {
    chooseReasons.push("The callout match is strong for this designation.");
  } else {
    verifyChecks.push("The callout match is only moderate. Double-check the drawing/spec before selecting.");
  }

  if (candidate.coverage.total_muas > 0) {
    chooseReasons.push(
      `There are ${candidate.coverage.total_muas} related MUAs (${candidate.coverage.approved} approved), so this choice has historical evidence behind it.`,
    );
  } else {
    verifyChecks.push("No related MUAs were found. Choose this only if it exactly matches your source callout.");
  }

  if (candidate.coverage.rejected > 0) {
    verifyChecks.push(
      `${candidate.coverage.rejected} related precedent(s) ended in rejection. Review those reasons before selecting.`,
    );
  }

  if (candidate.coverage.deferred > 0) {
    verifyChecks.push(
      `${candidate.coverage.deferred} related precedent(s) required added testing or deferral. Expect possible test burden.`,
    );
  }

  if (mixedInput && candidate.is_mixed_record) {
    verifyChecks.push("This appears to be a mixed-material record. Confirm this is the exact material you are approving.");
  }

  if (candidate.coverage.top_issues.length > 0) {
    const topIssue = candidate.coverage.top_issues[0];
    chooseReasons.push(
      `Most historical usage for this code is in ${topIssue.label} context (${topIssue.count} records).`,
    );
  }

  if (formConditionParts.length > 0) {
    chooseReasons.push(
      `This candidate includes ${formConditionParts.join(" and ")}. Matching these to your part callout helps avoid choosing the wrong variant.`,
    );
  }

  pickIf.push(
    `Pick this if your drawing/spec callout matches ${candidate.designation} (${candidate.material_code}).`,
  );
  if (formConditionParts.length > 0) {
    pickIf.push(`Pick this if the part ${formConditionParts.join(" and ")} match your application.`);
  }

  avoidIf.push("Do not pick this if the drawing/spec points to a different temper, form, or MAPTIS code.");
  if (candidate.coverage.total_muas === 0) {
    avoidIf.push("Avoid this as a first choice when there is another candidate with relevant MUA history.");
  }

  if (baseline) {
    if (candidate.material_code !== baseline.material_code) {
      diffs.push(`Uses MAPTIS code ${candidate.material_code} instead of ${baseline.material_code}.`);
    }
    if (candidate.family !== baseline.family) {
      diffs.push(`Material family differs (${candidate.family ?? "unknown"} vs ${baseline.family ?? "unknown"}).`);
    }
    if (candidate.form !== baseline.form) {
      diffs.push(`Material form differs (${candidate.form ?? "unspecified"} vs ${baseline.form ?? "unspecified"}).`);
    }
    if (candidate.condition !== baseline.condition) {
      diffs.push(
        `Material condition differs (${candidate.condition ?? "unspecified"} vs ${baseline.condition ?? "unspecified"}).`,
      );
    }

    const coverageDelta = candidate.coverage.total_muas - baseline.coverage.total_muas;
    if (coverageDelta > 0) {
      diffs.push(`Has ${coverageDelta} more related MUAs than the comparison option.`);
    } else if (coverageDelta < 0) {
      diffs.push(`Has ${Math.abs(coverageDelta)} fewer related MUAs than the comparison option.`);
    }
  }

  let summary = "This is a reasonable option if the callout details match.";
  if (candidate.coverage.total_muas > 0) {
    summary = `This option is backed by ${candidate.coverage.total_muas} related MUAs, but you should still verify callout details before selecting.`;
  }
  if (candidate.coverage.total_muas === 0) {
    summary = "This option has little precedent support, so only choose it with an exact callout match.";
  }

  return { summary, chooseReasons, verifyChecks, diffs, pickIf, avoidIf };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MUADefineStep({ wizard, patchWizard, onNext }: Props) {
  // Material resolution
  const [materialInput, setMaterialInput] = useState(wizard.material ?? '');
  const [resolution, setResolution] = useState<MaterialResolution | null>(null);
  const [selectedMaterialCode, setSelectedMaterialCode] = useState<string | null>(null);
  const [selectedMaterialKey, setSelectedMaterialKey] = useState<number | null>(null);
  const [selectedMaterialName, setSelectedMaterialName] = useState<string | null>(null);
  const [hasUserSelectedMaterial, setHasUserSelectedMaterial] = useState(false);
  const [resolving, setResolving] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const resolveRequestIdRef = useRef(0);
  const [materialIntel, setMaterialIntel] = useState<MaterialIntelResponse | null>(null);
  const [intelLoading, setIntelLoading] = useState(false);
  const intelDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intelRequestIdRef = useRef(0);
  const [materialFilters, setMaterialFilters] = useState<Record<string, string>>({});
  const [whyCandidateCode, setWhyCandidateCode] = useState<string | null>(null);

  // Environment
  const [env, setEnv] = useState<EnvironmentSpec>(
    wizard.environment ?? {
      o2_percent: 21,
      pressure_psia: 14.7,
      temp_min_f: 60,
      temp_max_f: 85,
      medium: 'Air',
      location: 'habitable',
      application: '',
    },
  );

  // Process params
  const [process, setProcess] = useState<ProcessParams>(
    wizard.processParams ?? {
      cure_temp_f: null,
      cure_time_min: null,
      cure_pressure_psi: null,
      mix_ratio: null,
      layup_orientation: null,
    },
  );

  // Issue codes (MAPTIS triggers)
  const [autoIssues, setAutoIssues] = useState<IssueCodeInfo[]>([]);
  const [selectedIssues, setSelectedIssues] = useState<Set<IssueCode>>(new Set());
  const [issueOverridden, setIssueOverridden] = useState(false);
  const issueDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Optional metadata
  const [appDesc, setAppDesc] = useState(wizard.applicationDescription ?? '');
  const [program, setProgram] = useState(wizard.program ?? '');
  const [hardware, setHardware] = useState(wizard.hardware ?? '');
  const [miulRef, setMiulRef] = useState(wizard.miulRef ?? '');
  const [approvedCat3CodesText, setApprovedCat3CodesText] = useState(
    (wizard.approvedCat3Codes ?? []).join(', ')
  );
  const [missionCritical, setMissionCritical] = useState<'unknown' | 'yes' | 'no'>('unknown');
  const [cat3PathKnown, setCat3PathKnown] = useState<'unknown' | 'yes' | 'no'>('unknown');
  const [miulImport, setMiulImport] = useState<MIULImportResponse | null>(null);
  const [miulLoading, setMiulLoading] = useState(false);
  const [miulError, setMiulError] = useState<string | null>(null);
  const [selectedMIULBucketId, setSelectedMIULBucketId] = useState<string | null>(null);

  // Submission
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounced material resolution
  const doResolve = useCallback(async (query: string) => {
    if (query.trim().length < 2) {
      setResolution(null);
      return;
    }
    const reqId = ++resolveRequestIdRef.current;
    setResolving(true);
    try {
      const { resolution: r } = await resolveMaterial(query.trim());
      if (reqId === resolveRequestIdRef.current) {
        setResolution(r);
      }
    } catch {
      if (reqId === resolveRequestIdRef.current) {
        setResolution(null);
      }
    } finally {
      if (reqId === resolveRequestIdRef.current) {
        setResolving(false);
      }
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doResolve(materialInput), 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [materialInput, doResolve]);

  useEffect(() => {
    if (intelDebounceRef.current) clearTimeout(intelDebounceRef.current);
    const query = materialInput.trim();
    if (query.length < 2) {
      setMaterialIntel(null);
      setIntelLoading(false);
      return;
    }

    intelDebounceRef.current = setTimeout(async () => {
      const reqId = ++intelRequestIdRef.current;
      setIntelLoading(true);
      try {
        const intel = await getMaterialIntel(query, selectedMaterialCode ?? null, 20, materialFilters);
        if (reqId === intelRequestIdRef.current) {
          setMaterialIntel(intel);
        }
      } catch {
        if (reqId === intelRequestIdRef.current) {
          setMaterialIntel(null);
        }
      } finally {
        if (reqId === intelRequestIdRef.current) {
          setIntelLoading(false);
        }
      }
    }, 700);

    return () => {
      if (intelDebounceRef.current) clearTimeout(intelDebounceRef.current);
    };
  }, [materialInput, selectedMaterialCode, materialFilters]);

  const materialCandidates: MaterialCandidate[] = (resolution?.suggestions ?? [])
    .map((raw) => normalizeCandidate(raw))
    .filter((c): c is MaterialCandidate => c !== null);

  const intelCandidates = materialIntel?.candidates ?? [];
  const effectiveMaterialCode = selectedMaterialCode ?? resolution?.material_code ?? null;
  const effectiveMaterialKey = selectedMaterialKey ?? resolution?.material_key ?? null;
  const effectiveMaterialName = selectedMaterialName ?? resolution?.resolved_name ?? null;
  const selectedIntelCandidate =
    intelCandidates.find((c) => c.material_code === effectiveMaterialCode) ?? null;
  const whyCandidate =
    intelCandidates.find((c) => c.material_code === whyCandidateCode) ?? null;
  const baselineIntelCandidate = (() => {
    if (!whyCandidate) {
      return selectedIntelCandidate ?? intelCandidates[0] ?? null;
    }
    if (
      selectedIntelCandidate &&
      selectedIntelCandidate.material_code !== whyCandidate.material_code
    ) {
      return selectedIntelCandidate;
    }
    return intelCandidates.find((c) => c.material_code !== whyCandidate.material_code) ?? null;
  })();
  const baselineLabel =
    selectedIntelCandidate &&
    whyCandidate &&
    selectedIntelCandidate.material_code !== whyCandidate.material_code
      ? "your current selection"
      : "next best alternative";
  const whyPayload =
    whyCandidate ? buildCandidateWhy(whyCandidate, baselineIntelCandidate, Boolean(materialIntel?.mixed_input)) : null;
  const intelOutcomeMessages: string[] = (() => {
    if (!materialIntel) return [];
    const msgs: string[] = [];

    if (effectiveMaterialCode) {
      msgs.push(
        `Result: Investigate will use MAPTIS ${effectiveMaterialCode} as the material code for precedent search and draft generation.`,
      );
    } else {
      msgs.push(
        "Result: pick one candidate so Investigate uses the correct MAPTIS code and evidence set.",
      );
    }

    if (baselineIntelCandidate) {
      msgs.push(
        `Current best match has ${baselineIntelCandidate.coverage.total_muas} related MUAs (${baselineIntelCandidate.coverage.approved} approved).`,
      );
    }

    if (materialIntel.mixed_input) {
      msgs.push(
        "This callout appears mixed-material. Choose the exact subject material before continuing.",
      );
    } else {
      msgs.push("Candidates are ordered from best to weaker match for this callout.");
    }

    const activeFilterCount = Object.keys(materialFilters).length;
    if (activeFilterCount > 0) {
      msgs.push(`Filters applied: ${activeFilterCount}.`);
    }

    return msgs;
  })();

  const selectMaterialCandidate = useCallback(
    (candidate: MaterialCandidate, updateInput = true, userSelected = true) => {
    setSelectedMaterialCode(candidate.material_code ?? candidate.spec ?? null);
    setSelectedMaterialKey(candidate.material_key ?? null);
    setSelectedMaterialName(candidate.name || null);
    if (userSelected) {
      setHasUserSelectedMaterial(true);
    }
    if (updateInput) {
      setMaterialInput(candidate.name);
    }
    },
    [],
  );

  const updateMaterialFilter = useCallback((key: string, value: string) => {
    setMaterialFilters((prev) => {
      const next = { ...prev };
      if (!value || value === "__any") {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
    setWhyCandidateCode(null);
  }, []);

  const clearMaterialFilters = useCallback(() => {
    setMaterialFilters({});
  }, []);

  useEffect(() => {
    if (!resolution) {
      // Preserve explicit MIUL/HITL selection until resolver catches up.
      if (!hasUserSelectedMaterial || !selectedMaterialCode) {
        setSelectedMaterialCode(null);
        setSelectedMaterialKey(null);
        setSelectedMaterialName(null);
        setHasUserSelectedMaterial(false);
      }
      return;
    }

    const candidateCodes = (resolution.suggestions ?? [])
      .map((raw) => normalizeCandidate(raw)?.material_code)
      .filter((code): code is string => Boolean(code));

    const resolvedCode = resolution.material_code ?? null;
    const resolvedKey = resolution.material_key ?? null;
    const resolvedName = resolution.resolved_name ?? null;

    if (
      resolution.status === "fuzzy" &&
      hasUserSelectedMaterial &&
      selectedMaterialCode &&
      candidateCodes.includes(selectedMaterialCode)
    ) {
      return;
    }

    if (resolution.status === "resolved") {
      if (hasUserSelectedMaterial && selectedMaterialCode) {
        return;
      }
      setSelectedMaterialCode(resolvedCode);
      setSelectedMaterialKey(resolvedKey);
      setSelectedMaterialName(resolvedName);
      setHasUserSelectedMaterial(false);
    } else if (resolution.status === "fuzzy") {
      setSelectedMaterialCode(null);
      setSelectedMaterialKey(null);
      setSelectedMaterialName(null);
      setHasUserSelectedMaterial(false);
    } else {
      if (!hasUserSelectedMaterial || !selectedMaterialCode) {
        setSelectedMaterialCode(null);
        setSelectedMaterialKey(null);
        setSelectedMaterialName(null);
        setHasUserSelectedMaterial(false);
      }
    }
  }, [resolution, hasUserSelectedMaterial, selectedMaterialCode]);

  useEffect(() => {
    if (!whyCandidateCode) return;
    const stillExists = intelCandidates.some((c) => c.material_code === whyCandidateCode);
    if (!stillExists) {
      setWhyCandidateCode(null);
    }
  }, [whyCandidateCode, intelCandidates]);

  useEffect(() => {
    // Keep resolver-selected code stable for resolved material.
    // Only clear a user-picked fuzzy candidate when it falls out of scope.
    if (resolution?.status !== "fuzzy") return;
    if (!hasUserSelectedMaterial || !selectedMaterialCode || !materialIntel) return;
    const stillValid = materialIntel.candidates.some(
      (c) => c.material_code === selectedMaterialCode
    );
    if (!stillValid) {
      setSelectedMaterialCode(null);
      setSelectedMaterialKey(null);
      setSelectedMaterialName(null);
      setHasUserSelectedMaterial(false);
    }
  }, [resolution?.status, hasUserSelectedMaterial, selectedMaterialCode, materialIntel]);

  // Auto-detect issue codes when environment changes
  useEffect(() => {
    if (issueDebounceRef.current) clearTimeout(issueDebounceRef.current);
    issueDebounceRef.current = setTimeout(async () => {
      try {
        const { issues } = await previewIssues(env);
        setAutoIssues(issues);
        // If the engineer hasn't manually toggled anything, sync selections
        if (!issueOverridden) {
          setSelectedIssues(new Set(issues.map((i) => i.code)));
        }
      } catch {
        // Silently fail -- issue preview is non-critical
      }
    }, 600);
    return () => {
      if (issueDebounceRef.current) clearTimeout(issueDebounceRef.current);
    };
  }, [env.o2_percent, env.pressure_psia, env.temp_min_f, env.temp_max_f, env.medium, env.location, issueOverridden]);

  const toggleIssue = (code: IssueCode) => {
    setIssueOverridden(true);
    setSelectedIssues((prev) => {
      const next = new Set(prev);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  };

  const resetIssuesToAuto = () => {
    setIssueOverridden(false);
    setSelectedIssues(new Set(autoIssues.map((i) => i.code)));
  };

  const handleImportMIUL = useCallback(async (file: File | null) => {
    if (!file) return;
    setMiulError(null);
    setMiulLoading(true);
    try {
      const payload = await importMIULWorkbook(file);
      setMiulImport(payload);
      setSelectedMIULBucketId(null);
    } catch (err) {
      setMiulImport(null);
      setMiulError(err instanceof Error ? err.message : "Failed to import MIUL workbook");
    } finally {
      setMiulLoading(false);
    }
  }, []);

  const applyMIULBucket = useCallback((bucket: MIULImportBucket) => {
    setSelectedMIULBucketId(bucket.bucket_id);
    const materialText = (bucket.suggested_material || bucket.material_code || "").trim();
    if (materialText) {
      setMaterialInput(materialText);
    }
    if (bucket.material_code) {
      setSelectedMaterialCode(bucket.material_code);
      setSelectedMaterialName(bucket.suggested_material || bucket.material_code);
      setHasUserSelectedMaterial(true);
    }

    if (bucket.suggested_environment) {
      setEnv(bucket.suggested_environment);
    }
    if (bucket.issue_codes?.length) {
      setSelectedIssues(new Set(bucket.issue_codes));
      setIssueOverridden(true);
    }
    if (!appDesc && bucket.sample_part_descriptions?.length) {
      setAppDesc(bucket.sample_part_descriptions[0]);
    }

    if (bucket.likely_category === "I_or_II" || bucket.likely_category === "I") {
      setMissionCritical("yes");
    } else {
      setMissionCritical("unknown");
    }
    if (bucket.likely_category.includes("III")) {
      setCat3PathKnown("yes");
    } else {
      setCat3PathKnown("unknown");
    }
  }, [appDesc]);

  // Location shortcut
  const handleLocationChange = (loc: string) => {
    const location = loc as EnvironmentSpec['location'];
    if (location === 'habitable') {
      setEnv((e) => ({ ...e, ...HABITABLE_DEFAULTS, location }));
    } else {
      setEnv((e) => ({ ...e, location }));
    }
  };

  // Env field helpers
  const patchEnv = (patch: Partial<EnvironmentSpec>) => setEnv((e) => ({ ...e, ...patch }));
  const patchProc = (patch: Partial<ProcessParams>) => setProcess((p) => ({ ...p, ...patch }));

  // Warnings
  const enrichedO2 = env.o2_percent >= 23.5;
  const cryogenic = env.temp_min_f <= -150;
  const hydrogenService = env.medium === 'Hydrogen';
  const o2Service = isO2ServiceMedium(env.medium);
  const showProcess = isProcessSensitive(resolution);
  const approvedCat3Codes = parseApprovedCat3Codes(approvedCat3CodesText);
  const catIReasons: string[] = [];
  if (o2Service) {
    catIReasons.push(`Medium '${env.medium}' is oxygen service.`);
  }
  if (enrichedO2) {
    catIReasons.push(`O2 ${env.o2_percent}% is enriched (>= 23.5%).`);
  }
  if (hydrogenService) {
    catIReasons.push("Hydrogen service is selected.");
  }
  if (cryogenic) {
    catIReasons.push(`Temperature minimum ${env.temp_min_f}F is cryogenic.`);
  }
  const cat3PlanSignal = cat3PathKnown === 'yes' || approvedCat3Codes.length > 0;

  const categoryHint = (() => {
    if (catIReasons.length > 0) {
      return {
        title: "Likely Category I",
        tone: "critical",
        summary:
          "This appears safety/mission critical. Plan for a full Category I MUA package and approvals.",
        reasons: catIReasons,
      } as const;
    }
    if (missionCritical === 'yes' && !cat3PlanSignal) {
      return {
        title: "Likely Category I",
        tone: "critical",
        summary:
          "You marked this usage as mission/crew/vehicle safety critical, and no Category III path is identified yet.",
        reasons: [
          "Safety/mission critical usage generally routes to Category I unless your approved plan explicitly supports a Category III path.",
        ],
      } as const;
    }
    if (cat3PlanSignal) {
      return {
        title: "Likely Category III Candidate",
        tone: "info",
        summary:
          "A Category III path is indicated by your plan input. If Appendix B applicability and evidence checks pass, this should route as Category III.",
        reasons: [
          cat3PathKnown === 'yes'
            ? "You indicated your plan has an approved Category III rationale path for this usage."
            : `Approved Category III code(s) entered: ${approvedCat3Codes.join(", ")}.`,
          "Final routing still validates Appendix B fit, ratings, and open gaps.",
        ],
      } as const;
    }
    if (cat3PathKnown === 'unknown') {
      return {
        title: "Likely Category III Or II",
        tone: "warning",
        summary:
          "Most similar cases are Category III when an approved rationale path exists. If none exists in your plan, use Category II.",
        reasons: [
          "Check your approved M&P plan first for a relevant Category III rationale path.",
          "If available and applicable, proceed as Category III; otherwise proceed as Category II.",
        ],
      } as const;
    }
    return {
      title: "Likely Category II",
      tone: "warning",
      summary:
        "You indicated no approved Category III path for this usage, and no Category I trigger is present.",
      reasons: [
        "Category II is typically used for nonconforming but non-safety-critical material usage.",
      ],
    } as const;
  })();
  // UI tuning: adjust this one class to change the gap between Location radios and the env field grid.
  const envFieldsFromLocationGapClass = "mt-8";
  // UI tuning: adjust this one class to change label-to-input spacing for O2/Pressure/Temp fields.
  const envFieldLabelGapClass = "space-y-2";

  // Validation
  const requiresCandidateSelection =
    resolution?.status === 'fuzzy' && materialCandidates.length > 0;
  const hasExplicitMaterialSelection =
    hasUserSelectedMaterial && Boolean(selectedMaterialCode) && materialInput.trim().length > 0;
  const materialResolvedByResolver =
    (resolution?.status === 'resolved' || resolution?.status === 'fuzzy') &&
    (!requiresCandidateSelection || (hasUserSelectedMaterial && Boolean(selectedMaterialCode)));
  const materialOk = hasExplicitMaterialSelection || materialResolvedByResolver;
  const envOk = env.o2_percent > 0 && env.pressure_psia > 0 && env.temp_max_f > env.temp_min_f;
  const canSubmit = materialOk && envOk && !submitting;

  // Submit
  const handleInvestigate = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const effectiveMaterialName = materialInput.trim();
      const explicitOverride = hasUserSelectedMaterial && Boolean(selectedMaterialCode);

      const buildReq = (sid: string | null): InvestigateRequest => ({
        session_id: sid,
        material: effectiveMaterialName,
        material_code: explicitOverride ? selectedMaterialCode : null,
        material_key: explicitOverride ? selectedMaterialKey : null,
        resolved_name: explicitOverride ? (selectedMaterialName ?? effectiveMaterialName) : null,
        environment: { ...env, application: appDesc || env.application },
        process_params: showProcess ? process : undefined,
        issue_codes: selectedIssues.size > 0 ? Array.from(selectedIssues) : undefined,
        approved_cat3_codes: approvedCat3Codes.length > 0 ? approvedCat3Codes : undefined,
        program: program || undefined,
        hardware: hardware || undefined,
        miul_ref: miulRef || undefined,
      });

      let result: { session_id: string; status: string };
      try {
        result = await investigate(buildReq(wizard.sessionId));
      } catch (firstErr: unknown) {
        // If the session is stale (already past investigate step), retry with a fresh session
        const isStaleSession =
          wizard.sessionId &&
          firstErr instanceof Error &&
          'status' in firstErr &&
          (firstErr as { status: number }).status === 400;
        if (isStaleSession) {
          console.warn('[MUA] Stale session, retrying with fresh session');
          result = await investigate(buildReq(null));
        } else {
          throw firstErr;
        }
      }
      patchWizard({
        sessionId: result.session_id,
        material: effectiveMaterialName,
        environment: env,
        processParams: showProcess ? process : null,
        applicationDescription: appDesc || null,
        program: program || null,
        hardware: hardware || null,
        miulRef: miulRef || null,
        approvedCat3Codes: approvedCat3Codes.length > 0 ? approvedCat3Codes : null,
        investigation: null,  // async -- populated when polling completes
      });
      onNext(result.session_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Investigation failed');
    } finally {
      setSubmitting(false);
    }
  };

  // ---- Render -------------------------------------------------------------

  const resolutionIcon =
    resolution?.status === 'resolved' ? (
      <CheckCircle2 className="h-4 w-4 text-green-600" />
    ) : resolution?.status === 'fuzzy' ? (
      <AlertTriangle className="h-4 w-4 text-yellow-600" />
    ) : resolution?.status === 'unresolved' ? (
      <XCircle className="h-4 w-4 text-red-500" />
    ) : null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Step 0: Import MIUL (optional)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Input
              type="file"
              accept=".xlsx"
              disabled={miulLoading}
              className="max-w-md"
              onChange={(e) => {
                const file = e.target.files?.[0] ?? null;
                void handleImportMIUL(file);
              }}
            />
            {miulLoading && (
              <span className="text-sm text-muted-foreground inline-flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Importing MIUL...
              </span>
            )}
          </div>

          {miulError && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>MIUL Import Error</AlertTitle>
              <AlertDescription>{miulError}</AlertDescription>
            </Alert>
          )}

          {miulImport && (
            <div className="space-y-3">
              <div className="rounded-md border bg-muted/20 p-3 text-sm">
                Imported <strong>{miulImport.filename}</strong>: {miulImport.non_a_parts} non-A trigger parts across{" "}
                {miulImport.bucket_count} buckets.
              </div>
              <div className="space-y-2 max-h-72 overflow-auto pr-1">
                {miulImport.buckets.slice(0, 30).map((bucket) => (
                  <div
                    key={bucket.bucket_id}
                    className={`rounded border p-3 space-y-2 ${
                      selectedMIULBucketId === bucket.bucket_id ? "border-primary bg-primary/5" : ""
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-medium">
                        {bucket.suggested_material} ({bucket.material_code})
                      </div>
                      <Badge variant="outline">
                        {bucket.part_count} part{bucket.part_count === 1 ? "" : "s"}
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Trigger: {bucket.trigger_signature} | Env: {bucket.environment_raw || bucket.suggested_environment.medium} | Fluid: {(bucket.fluid_types && bucket.fluid_types.length > 0) ? bucket.fluid_types.join(", ") : "unknown"} | Hint: {bucket.likely_category}
                    </div>
                    {bucket.category_reasons.length > 0 && (
                      <div className="text-xs text-muted-foreground">
                        {bucket.category_reasons[0]}
                      </div>
                    )}
                    <div className="flex justify-end">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => applyMIULBucket(bucket)}
                      >
                        Use This Bucket
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Start Here: What Type Of MUA Do You Need?</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Has this use already been classified as mission/crew/vehicle safety critical?</Label>
            <RadioGroup
              value={missionCritical}
              onValueChange={(v) => setMissionCritical(v as 'unknown' | 'yes' | 'no')}
              className="flex flex-wrap gap-6"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="yes" id="mc-yes" />
                <Label htmlFor="mc-yes" className="font-normal cursor-pointer">Yes</Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="no" id="mc-no" />
                <Label htmlFor="mc-no" className="font-normal cursor-pointer">No</Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="unknown" id="mc-unknown" />
                <Label htmlFor="mc-unknown" className="font-normal cursor-pointer">Not sure yet</Label>
              </div>
            </RadioGroup>
          </div>

          <div className="space-y-2">
            <Label>Does your approved M&P plan define a Category III rationale path for this specific use?</Label>
            <RadioGroup
              value={cat3PathKnown}
              onValueChange={(v) => setCat3PathKnown(v as 'unknown' | 'yes' | 'no')}
              className="flex flex-wrap gap-6"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="yes" id="cat3-yes" />
                <Label htmlFor="cat3-yes" className="font-normal cursor-pointer">Yes</Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="no" id="cat3-no" />
                <Label htmlFor="cat3-no" className="font-normal cursor-pointer">No</Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="unknown" id="cat3-unknown" />
                <Label htmlFor="cat3-unknown" className="font-normal cursor-pointer">Not sure yet</Label>
              </div>
            </RadioGroup>
          </div>

          <Alert
            className={
              categoryHint.tone === "critical"
                ? "border-red-300 bg-red-50"
                : categoryHint.tone === "warning"
                  ? "border-amber-300 bg-amber-50"
                  : "border-blue-300 bg-blue-50"
            }
          >
            <AlertTriangle
              className={
                categoryHint.tone === "critical"
                  ? "h-4 w-4 text-red-600"
                  : categoryHint.tone === "warning"
                    ? "h-4 w-4 text-amber-600"
                    : "h-4 w-4 text-blue-600"
              }
            />
            <AlertTitle>{categoryHint.title}</AlertTitle>
            <AlertDescription className="space-y-2">
              <p>{categoryHint.summary}</p>
              <div className="space-y-1 text-xs">
                {categoryHint.reasons.map((reason) => (
                  <p key={reason}>- {reason}</p>
                ))}
              </div>
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      {/* Material input */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Search className="h-5 w-5" />
            Material Identification
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="material">Material Name or Specification</Label>
            <div className="relative">
              <Input
                id="material"
                placeholder="e.g. Teflon TFE, AMS 3281, Kapton HN..."
                value={materialInput}
                onChange={(e) => {
                  setHasUserSelectedMaterial(false);
                  setSelectedMaterialCode(null);
                  setSelectedMaterialKey(null);
                  setSelectedMaterialName(null);
                  setMaterialInput(e.target.value);
                  setMaterialFilters({});
                }}
              />
              <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5">
                {resolving && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
                {!resolving && resolutionIcon}
              </div>
            </div>
            {resolution && (
              <div className="text-sm">
                {resolution.status === 'resolved' && (
                  <div className="space-y-1">
                    <span className="text-green-700">
                      Resolved: {effectiveMaterialName ?? resolution.resolved_name}
                      {effectiveMaterialCode &&
                        ` (${effectiveMaterialCode})`}
                    </span>
                    {(effectiveMaterialCode || effectiveMaterialKey) && (
                      <p className="text-xs text-muted-foreground">
                        Using MAPTIS record
                        {effectiveMaterialCode ? ` ${effectiveMaterialCode}` : ''}
                        {effectiveMaterialKey ? ` (key ${effectiveMaterialKey})` : ''}.
                      </p>
                    )}
                  </div>
                )}
                {resolution.status === 'fuzzy' && (
                  <div className="space-y-1">
                    <span className="text-yellow-700">
                      {resolution.selection_method === "multi_material_detected"
                        ? "Multiple materials detected in one callout. Pick the exact subject material for this MUA."
                        : "Review required: select the best MAPTIS record for this callout."}
                    </span>
                    {materialCandidates.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {materialCandidates.slice(0, 8).map((c) => (
                          <Badge
                            key={`${c.spec}-${c.name}`}
                            variant={selectedMaterialCode === c.material_code ? "default" : "outline"}
                            className="cursor-pointer hover:bg-accent"
                            onClick={() => selectMaterialCandidate(c, true, true)}
                          >
                            {c.name} ({c.spec})
                          </Badge>
                        ))}
                      </div>
                    )}
                    {hasUserSelectedMaterial && (selectedMaterialName || selectedMaterialCode) && (
                      <p className="text-xs text-muted-foreground mt-1">
                        Selected: {selectedMaterialName ?? resolution.resolved_name}
                        {selectedMaterialCode ? ` (${selectedMaterialCode})` : ''}
                      </p>
                    )}
                  </div>
                )}
                {resolution.status === 'unresolved' && (
                  <span className="text-red-600">
                    Material not confidently resolved. Enter a tighter designation or pick from suggestions if available.
                  </span>
                )}
              </div>
            )}

            {(intelLoading || materialIntel) && (
              <div className="mt-3 rounded-md border bg-muted/20 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    Material Intel
                  </p>
                  {intelLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
                </div>

                {materialIntel ? (
                  <div className="space-y-1">
                    {intelOutcomeMessages.map((msg, idx) => (
                      <p key={`intel-outcome-${idx}`} className="text-xs text-muted-foreground">
                        {msg}
                      </p>
                    ))}
                    <p className="text-xs text-muted-foreground">
                      Showing {materialIntel.candidate_count} of {materialIntel.initial_candidate_count || materialIntel.candidate_count} candidate(s).
                    </p>
                  </div>
                ) : null}

                {materialIntel?.disambiguation_questions?.length ? (
                  <div className="space-y-2 rounded border bg-background/60 p-2">
                    <div className="flex items-center justify-between">
                      <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                        Narrow Material
                      </p>
                      {Object.keys(materialFilters).length > 0 && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[11px]"
                          onClick={clearMaterialFilters}
                        >
                          Clear filters
                        </Button>
                      )}
                    </div>
                    {materialIntel.disambiguation_questions.map((q) => (
                      <div key={q.key} className="grid grid-cols-1 md:grid-cols-[1fr_220px] gap-2 items-center">
                        <p className="text-[11px] text-muted-foreground">{q.prompt}</p>
                        <Select
                          value={materialFilters[q.key] ?? "__any"}
                          onValueChange={(v) => updateMaterialFilter(q.key, v)}
                        >
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__any">Any</SelectItem>
                            {q.options.map((opt) => (
                              <SelectItem key={`${q.key}-${opt.value}`} value={opt.value}>
                                {opt.label} ({opt.candidate_count})
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    ))}
                  </div>
                ) : null}

                {materialIntel?.candidates?.length ? (
                  <div className="space-y-2">
                    <p className="text-[11px] text-muted-foreground">
                      Click a candidate designation to set the MAPTIS code used for investigation.
                    </p>
                    {materialIntel.candidates.slice(0, 4).map((c) => {
                      const isSelected = selectedMaterialCode === c.material_code;
                      return (
                        <div
                          key={`${c.material_code}-${c.designation}`}
                          className={`rounded border p-2 space-y-1 ${
                            isSelected ? "border-primary bg-primary/5" : "border-border"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                selectMaterialCandidate(
                                  {
                                    name: c.designation,
                                    spec: c.material_code,
                                    score: c.score,
                                    material_code: c.material_code,
                                    material_key: c.material_key,
                                  },
                                  true,
                                  true,
                                )
                              }
                              className="text-left text-xs font-medium hover:underline"
                            >
                              {c.designation} ({c.material_code})
                            </button>
                            <div className="flex items-center gap-2">
                              <span className="text-[11px] text-muted-foreground">
                                {calloutMatchLabel(c.score)}
                              </span>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-6 px-2 text-[11px]"
                                onClick={() => setWhyCandidateCode(c.material_code)}
                              >
                                Why this candidate?
                              </Button>
                            </div>
                          </div>
                          <p className="text-[11px] text-muted-foreground">
                            If selected: uses code {c.material_code} with {c.coverage.total_muas} related MUAs ({c.coverage.approved} approved, {c.coverage.conditional} conditional, {c.coverage.rejected} rejected)
                          </p>
                          {(c.family || c.form || c.condition) && (
                            <div className="flex flex-wrap gap-1">
                              {c.family && (
                                <Badge variant="secondary" className="text-[10px]">
                                  family: {c.family}
                                </Badge>
                              )}
                              {c.form && (
                                <Badge variant="secondary" className="text-[10px]">
                                  form: {c.form}
                                </Badge>
                              )}
                              {c.condition && (
                                <Badge variant="secondary" className="text-[10px]">
                                  cond: {c.condition}
                                </Badge>
                              )}
                            </div>
                          )}
                          {c.coverage.top_issues.length > 0 && (
                            <p className="text-[11px] text-muted-foreground">
                              top issues:{" "}
                              {c.coverage.top_issues
                                .slice(0, 3)
                                .map((i) => `${i.label} (${i.count})`)
                                .join(", ")}
                            </p>
                          )}
                          {c.differences.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {c.differences.slice(0, 2).map((d) => (
                                <Badge key={`${c.material_code}-${d}`} variant="outline" className="text-[10px]">
                                  {d}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : materialIntel ? (
                  <div className="rounded border border-amber-300 bg-amber-50 p-2">
                    <p className="text-xs text-amber-900">
                      No candidates match the current filters. Clear one filter to continue.
                    </p>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Sheet
        open={Boolean(whyCandidate)}
        onOpenChange={(open) => {
          if (!open) setWhyCandidateCode(null);
        }}
      >
        <SheetContent className="sm:max-w-xl overflow-y-auto">
          <SheetHeader className="mb-4">
            <SheetTitle>Why this candidate?</SheetTitle>
          </SheetHeader>

          {whyCandidate && whyPayload && (
            <div className="space-y-4">
              <div className="rounded-md border p-3 space-y-1">
                <p className="text-sm font-medium">
                  {whyCandidate.designation} ({whyCandidate.material_code})
                </p>
                {baselineIntelCandidate ? (
                  <p className="text-xs text-muted-foreground">
                    Compared against {baselineLabel}:{" "}
                    {baselineIntelCandidate.designation} ({baselineIntelCandidate.material_code})
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    No alternate candidate available for side-by-side comparison.
                  </p>
                )}
                <p className="text-xs text-muted-foreground">
                  {whyPayload.summary}
                </p>
              </div>

              {baselineIntelCandidate && (
                <div className="rounded-md border p-3 space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Candidate vs Comparison
                  </p>
                  <div className="grid grid-cols-[100px_1fr_1fr] gap-2 text-xs">
                    <p className="font-medium text-muted-foreground">Field</p>
                    <p className="font-medium text-muted-foreground">Candidate</p>
                    <p className="font-medium text-muted-foreground">Comparison</p>

                    <p className="text-muted-foreground">Code</p>
                    <p>{whyCandidate.material_code}</p>
                    <p>{baselineIntelCandidate.material_code}</p>

                    <p className="text-muted-foreground">Family</p>
                    <p>{whyCandidate.family ?? "unspecified"}</p>
                    <p>{baselineIntelCandidate.family ?? "unspecified"}</p>

                    <p className="text-muted-foreground">Form</p>
                    <p>{whyCandidate.form ?? "unspecified"}</p>
                    <p>{baselineIntelCandidate.form ?? "unspecified"}</p>

                    <p className="text-muted-foreground">Condition</p>
                    <p>{whyCandidate.condition ?? "unspecified"}</p>
                    <p>{baselineIntelCandidate.condition ?? "unspecified"}</p>

                    <p className="text-muted-foreground">Coverage</p>
                    <p>{whyCandidate.coverage.total_muas} MUAs</p>
                    <p>{baselineIntelCandidate.coverage.total_muas} MUAs</p>
                  </div>
                </div>
              )}

              <div className="rounded-md border p-3 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Why You Might Choose This
                </p>
                {whyPayload.chooseReasons.length > 0 ? (
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    {whyPayload.chooseReasons.map((item, idx) => (
                      <li key={`why-strength-${idx}`}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground">No strong positive signals identified yet.</p>
                )}
              </div>

              {whyPayload.pickIf.length > 0 && (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-emerald-800">
                    Pick This If
                  </p>
                  <ul className="list-disc pl-5 space-y-1 text-xs text-emerald-900">
                    {whyPayload.pickIf.map((item, idx) => (
                      <li key={`why-pick-${idx}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {(whyPayload.diffs.length > 0 || whyCandidate.differences.length > 0) && (
                <div className="rounded-md border p-3 space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Key Differences
                  </p>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    {[...whyPayload.diffs, ...whyCandidate.differences].slice(0, 8).map((item, idx) => (
                      <li key={`why-diff-${idx}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {(whyPayload.verifyChecks.length > 0 || whyPayload.avoidIf.length > 0) && (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-3 space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">
                    Verify Before You Select
                  </p>
                  <ul className="list-disc pl-5 space-y-1 text-xs text-amber-900">
                    {whyPayload.verifyChecks.map((item, idx) => (
                      <li key={`why-caution-${idx}`}>{item}</li>
                    ))}
                    {whyPayload.avoidIf.map((item, idx) => (
                      <li key={`why-avoid-${idx}`}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex justify-end">
                <Button
                  type="button"
                  onClick={() => {
                    selectMaterialCandidate(
                      {
                        name: whyCandidate.designation,
                        spec: whyCandidate.material_code,
                        score: whyCandidate.score,
                        material_code: whyCandidate.material_code,
                        material_key: whyCandidate.material_key,
                      },
                      true,
                      true,
                    );
                    setWhyCandidateCode(null);
                  }}
                >
                  Use This Candidate
                </Button>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>

      {/* Environment */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Wind className="h-5 w-5" />
            Use Environment
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div>
            {/* Location radio */}
            <div className="space-y-2">
              <Label>Location</Label>
              <RadioGroup
                value={env.location}
                onValueChange={handleLocationChange}
                className="flex gap-6"
              >
                {LOCATION_OPTIONS.map((opt) => (
                  <div key={opt.value} className="flex items-center gap-2">
                    <RadioGroupItem value={opt.value} id={`loc-${opt.value}`} />
                    <Label htmlFor={`loc-${opt.value}`} className="font-normal cursor-pointer">
                      {opt.label}
                    </Label>
                  </div>
                ))}
              </RadioGroup>
            </div>

            {/* Grid of env fields */}
            <div className={`${envFieldsFromLocationGapClass} grid grid-cols-2 md:grid-cols-4 gap-4`}>
              <div className={envFieldLabelGapClass}>
                <Label htmlFor="o2" className="flex items-center gap-1.5">
                  <Gauge className="h-3.5 w-3.5 shrink-0" /> O2 %
                </Label>
                <Input
                  id="o2"
                  type="number"
                  step="0.1"
                  value={env.o2_percent}
                  onChange={(e) => patchEnv({ o2_percent: parseFloat(e.target.value) || 0 })}
                />
              </div>
              <div className={envFieldLabelGapClass}>
                <Label htmlFor="press" className="flex items-center gap-1.5">
                  <Gauge className="h-3.5 w-3.5 shrink-0" /> Pressure (PSIA)
                </Label>
                <Input
                  id="press"
                  type="number"
                  step="0.1"
                  value={env.pressure_psia}
                  onChange={(e) => patchEnv({ pressure_psia: parseFloat(e.target.value) || 0 })}
                />
              </div>
              <div className={envFieldLabelGapClass}>
                <Label htmlFor="tmin" className="flex items-center gap-1.5">
                  <Thermometer className="h-3.5 w-3.5 shrink-0" /> Temp Min (F)
                </Label>
                <Input
                  id="tmin"
                  type="number"
                  value={env.temp_min_f}
                  onChange={(e) => patchEnv({ temp_min_f: parseFloat(e.target.value) || 0 })}
                />
              </div>
              <div className={envFieldLabelGapClass}>
                <Label htmlFor="tmax" className="flex items-center gap-1.5">
                  <Thermometer className="h-3.5 w-3.5 shrink-0" /> Temp Max (F)
                </Label>
                <Input
                  id="tmax"
                  type="number"
                  value={env.temp_max_f}
                  onChange={(e) => patchEnv({ temp_max_f: parseFloat(e.target.value) || 0 })}
                />
              </div>
            </div>

            {/* Medium select */}
            <div className="mt-3 space-y-1.5 max-w-xs">
              <Label>Medium</Label>
              <Select value={env.medium} onValueChange={(v) => patchEnv({ medium: v })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MEDIUM_OPTIONS.map((m) => (
                    <SelectItem key={m} value={m}>
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Warning banners */}
          {enrichedO2 && (
            <Alert className="border-orange-300 bg-orange-50">
              <Flame className="h-4 w-4 text-orange-600" />
              <AlertTitle className="text-orange-800">Enriched Oxygen Environment</AlertTitle>
              <AlertDescription className="text-orange-700">
                O2 concentration &gt;= 23.5%. Additional flammability testing per NASA-STD-6001B Test 1
                may be required.
              </AlertDescription>
            </Alert>
          )}
          {cryogenic && (
            <Alert className="border-blue-300 bg-blue-50">
              <Snowflake className="h-4 w-4 text-blue-600" />
              <AlertTitle className="text-blue-800">Cryogenic Service</AlertTitle>
              <AlertDescription className="text-blue-700">
                Temperature below -150 F. Cryogenic compatibility data will be prioritized.
              </AlertDescription>
            </Alert>
          )}
          {hydrogenService && (
            <Alert className="border-purple-300 bg-purple-50">
              <Atom className="h-4 w-4 text-purple-600" />
              <AlertTitle className="text-purple-800">Hydrogen Service</AlertTitle>
              <AlertDescription className="text-purple-700">
                Hydrogen embrittlement and permeation data will be evaluated.
              </AlertDescription>
            </Alert>
          )}

          {/* Issue code chips -- auto-detected, engineer-overridable */}
          {autoIssues.length > 0 && (
            <div className="space-y-2 pt-2 border-t">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">
                  MAPTIS Issue Triggers
                </Label>
                {issueOverridden && (
                  <button
                    type="button"
                    className="text-xs text-muted-foreground hover:text-foreground underline"
                    onClick={resetIssuesToAuto}
                  >
                    Reset to auto-detected
                  </button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Auto-detected from your environment. Click to add or remove issue types.
              </p>
              <div className="flex flex-wrap gap-2">
                {/* All possible issue codes, with auto-detected ones shown first */}
                {(["FLAM", "TVS", "FS", "TOX", "OFFGAS", "O2_COMPAT", "HEE", "SCC", "CORR", "FRACTURE"] as IssueCode[]).map(
                  (code) => {
                    const info = autoIssues.find((i) => i.code === code);
                    const isSelected = selectedIssues.has(code);
                    const isAuto = !!info;
                    const label = info?.label ?? {
                      FLAM: "Flammability",
                      TVS: "Thermal Vacuum Stability",
                      FS: "Fluid Susceptibility",
                      TOX: "Toxicity",
                      OFFGAS: "Offgassing",
                      O2_COMPAT: "O2 Compatibility",
                      HEE: "H2 Embrittlement",
                      SCC: "Stress Corrosion",
                      CORR: "Corrosion",
                      FRACTURE: "Cryogenic Fracture",
                    }[code];
                    return (
                      <Badge
                        key={code}
                        variant={isSelected ? "default" : "outline"}
                        className={`cursor-pointer select-none transition-colors ${
                          isSelected
                            ? isAuto
                              ? "bg-primary hover:bg-primary/80"
                              : "bg-blue-600 hover:bg-blue-500"
                            : "opacity-50 hover:opacity-80"
                        }`}
                        onClick={() => toggleIssue(code)}
                      >
                        {label}
                        {isSelected && isAuto && !issueOverridden && (
                          <span className="ml-1 text-[10px] opacity-70">auto</span>
                        )}
                      </Badge>
                    );
                  },
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Process parameters (conditional) */}
      {showProcess && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Process Parameters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div className="space-y-1.5">
                <Label>Cure Temp (F)</Label>
                <Input
                  type="number"
                  value={process.cure_temp_f ?? ''}
                  onChange={(e) =>
                    patchProc({ cure_temp_f: e.target.value ? parseFloat(e.target.value) : null })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Cure Time (min)</Label>
                <Input
                  type="number"
                  step="1"
                  value={process.cure_time_min ?? ''}
                  onChange={(e) =>
                    patchProc({ cure_time_min: e.target.value ? parseFloat(e.target.value) : null })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Cure Pressure (psi)</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={process.cure_pressure_psi ?? ''}
                  onChange={(e) =>
                    patchProc({
                      cure_pressure_psi: e.target.value ? parseFloat(e.target.value) : null,
                    })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Mix Ratio</Label>
                <Input
                  value={process.mix_ratio ?? ''}
                  onChange={(e) =>
                    patchProc({ mix_ratio: e.target.value || null })
                  }
                  placeholder="e.g. 100:42"
                />
              </div>
              <div className="space-y-1.5 col-span-2">
                <Label>Layup Orientation</Label>
                <Input
                  value={process.layup_orientation ?? ''}
                  onChange={(e) =>
                    patchProc({ layup_orientation: e.target.value || null })
                  }
                  placeholder="e.g. 0/90/±45"
                />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Application & metadata */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Application Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="appDesc">Application Description</Label>
            <Textarea
              id="appDesc"
              rows={3}
              placeholder="Describe how and where this material will be used..."
              value={appDesc}
              onChange={(e) => setAppDesc(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="program">Program (optional)</Label>
              <Input
                id="program"
                value={program}
                onChange={(e) => setProgram(e.target.value)}
                placeholder="e.g. ISS, Orion"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="hardware">Hardware (optional)</Label>
              <Input
                id="hardware"
                value={hardware}
                onChange={(e) => setHardware(e.target.value)}
                placeholder="e.g. ECLSS rack"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="miulRef">MIUL Reference (optional)</Label>
              <Input
                id="miulRef"
                value={miulRef}
                onChange={(e) => setMiulRef(e.target.value)}
                placeholder="e.g. MIUL-2024-0142"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="approvedCat3Codes">Approved Cat III Codes (advanced, optional)</Label>
              <Input
                id="approvedCat3Codes"
                value={approvedCat3CodesText}
                onChange={(e) => setApprovedCat3CodesText(e.target.value)}
                placeholder="e.g. 103,104,105"
              />
              <p className="text-[11px] text-muted-foreground">
                Enter codes only if they are already approved for this hardware in your M&P plan.
              </p>
            </div>
          </div>
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
      <div className="flex justify-end">
        <Button size="lg" disabled={!canSubmit} onClick={handleInvestigate}>
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Investigating...
            </>
          ) : (
            <>
              Investigate
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
