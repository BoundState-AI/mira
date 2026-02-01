import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  FileText,
  Download,
  Upload,
  CheckCircle,
  AlertCircle,
  FileSpreadsheet,
  FileCode,
  Globe,
  Search,
  Sparkles,
  Brain,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Loader2,
  Copy,
  ClipboardCheck,
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { PageHelp } from "@/components/PageHelp";
import helpContent from "@/config/helpContent";
import {
  muaV6SearchPrecedents,
  muaV6Generate,
  muaCorpusSearch,
  muaCorpusDraft,
  type MuaV6PrecedentSearchResponse,
  type MuaV6GenerateResponse,
  type MuaV6PrecedentSummary,
  type GenerationDecision,
  type OverlapStatus,
  type CorpusSearchResponse,
  type CorpusDraftResponse,
  type CorpusPrecedent,
} from "@/lib/api";

interface MUAResult {
  material_code: string;
  designation: string;
  mua: {
    required: boolean;
    id: string;
    category: string;
    gap_profile: Record<string, string>;
    confidence: {
      global: number;
      ci_68: [number, number];
      ci_95: [number, number];
    };
    draft_text: string;
  };
}

interface MUABatchResponse {
  success: boolean;
  materials_processed: number;
  muas_generated: number;
  muas: MUAResult[];
}

// Interactive workflow types
interface MUAPrecedent {
  mua_number: string;
  material: string;
  environment: string;
  determination: string;
  rationale_summary: string;
  rationale_full: string | null;
  score: number;
  source_file: string;
  category: string | null;
  issue: string | null;
  material_family: string | null;
  test_reports: string[];
}

interface MUADraft {
  material: string;
  material_code: string | null;
  category: string;
  gaps: Record<string, string>;
  rationale: string;
  provenance_summary: string;
  confidence: number;
  environment: string | null;
  precedents: MUAPrecedent[];
}

// V3 Synthesis types
interface ApplicabilityFactor {
  match: string;
  reason: string;
}

interface ApplicabilityAnalysis {
  precedent_id: string;
  applicability: "YES" | "PARTIAL" | "NO";
  relevance_score: number;
  factors: Record<string, ApplicabilityFactor>;
  summary: string;
}

interface SynthesizedPrecedent {
  mua_number: string;
  material: string;
  environment: string;
  determination: string;
  rationale_summary: string;
  category: string | null;
  issue: string | null;
  application: string | null;
  score: number;
}

interface SynthesisResult {
  success: boolean;
  material: string;
  issue: string;
  category: string;
  rationale: string;
  confidence: number;
  precedents: SynthesizedPrecedent[];
  applicability_analyses: ApplicabilityAnalysis[];
  warnings: string[];
  error: string | null;
}

// V4 Precedent Engine types
interface PrecedentMatch {
  contract_id: string;
  material_name: string;
  material_key: string | null;
  tier: number;
  similarity_score: number;
  material_equivalent: boolean;
  environment_equivalent: boolean;
  deviation_equivalent: boolean;
  media: string | null;
  o2_pct: number;
  temp_max_f: number | null;
  pressure_max_psia: number | null;
  is_rejected: boolean;
  rationale_text: string | null;
  category: string | null;
  source_program: string | null;
  environment_delta_summary: string;
}

interface PrecedentEvalResult {
  success: boolean;
  query_material: string;
  query_environment_summary: string;
  n_total_candidates: number;
  n_tier1: number;
  n_tier2: number;
  n_tier3: number;
  adequacy: string;
  adequacy_reasoning: string;
  tier1_matches: PrecedentMatch[];
  tier2_matches: PrecedentMatch[];
  tier3_matches: PrecedentMatch[];
  recommended_base: PrecedentMatch | null;
  base_selection_reasoning: string;
  statistics: {
    n_total_with_material: number;
    n_similar_environment: number;
    n_approved: number;
    n_rejected: number;
    approval_rate: number;
  };
}

export default function MUAGenerator() {
  const { t } = useTranslation('muaGenerator');
  // Main mode tab
  const [mainMode, setMainMode] = useState<"synthesis" | "interactive" | "batch" | "precedent" | "v6" | "corpus">("corpus");

  // Batch mode state
  const [enrichedFile, setEnrichedFile] = useState<File | null>(null);
  const [programName, setProgramName] = useState<string>("ORION");
  const [hardwareName, setHardwareName] = useState<string>("Dual Motion Valve");
  const [isGenerating, setIsGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [muaResults, setMuaResults] = useState<MUABatchResponse | null>(null);

  // Interactive mode state
  const [searchMaterial, setSearchMaterial] = useState<string>("");
  const [searchIssues, setSearchIssues] = useState<string[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [precedents, setPrecedents] = useState<MUAPrecedent[]>([]);
  const [selectedPrecedents, setSelectedPrecedents] = useState<Set<string>>(new Set());
  const [interactiveStep, setInteractiveStep] = useState<1 | 2 | 3>(1);
  const [interactiveEnvironment, setInteractiveEnvironment] = useState<string>("");
  const [interactiveApplication, setInteractiveApplication] = useState<string>("");
  const [generatedDraft, setGeneratedDraft] = useState<MUADraft | null>(null);
  const [isGeneratingFromSelection, setIsGeneratingFromSelection] = useState(false);

  // V3 Synthesis mode state
  const [synthMaterial, setSynthMaterial] = useState<string>("");
  const [synthIssue, setSynthIssue] = useState<string>("FLAM");
  const [synthApplication, setSynthApplication] = useState<string>("");
  const [synthEnvironment, setSynthEnvironment] = useState<string>("");
  const [synthLocation, setSynthLocation] = useState<string>("Non-habitable");
  const [synthMass, setSynthMass] = useState<string>("");
  const [synthProgram, setSynthProgram] = useState<string>("");
  const [isSynthesizing, setIsSynthesizing] = useState(false);
  const [synthesisResult, setSynthesisResult] = useState<SynthesisResult | null>(null);
  const [expandedAnalyses, setExpandedAnalyses] = useState<Set<string>>(new Set());
  const [copiedRationale, setCopiedRationale] = useState(false);

  // V4 Precedent Engine state
  const [precMaterial, setPrecMaterial] = useState<string>("");
  const [precMedia, setPrecMedia] = useState<string>("");
  const [precO2Pct, setPrecO2Pct] = useState<string>("21");
  const [precTempMax, setPrecTempMax] = useState<string>("");
  const [precPressureMax, setPrecPressureMax] = useState<string>("");
  const [precDeviations, setPrecDeviations] = useState<string[]>([]);
  const [precLocation, setPrecLocation] = useState<string>("non_habitable");
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<PrecedentEvalResult | null>(null);
  const [expandedTiers, setExpandedTiers] = useState<Set<number>>(new Set([1]));

  // V6 Pipeline state
  const [v6Material, setV6Material] = useState<string>("");
  const [v6EnvDescription, setV6EnvDescription] = useState<string>("");
  const [v6O2Percent, setV6O2Percent] = useState<string>("");
  const [v6PressurePsia, setV6PressurePsia] = useState<string>("");
  const [v6TempF, setV6TempF] = useState<string>("");
  const [v6IsHabitable, setV6IsHabitable] = useState(false);
  const [v6K, setV6K] = useState<string>("10");
  const [v6Mode, setV6Mode] = useState<"evaluate_only" | "auto">("evaluate_only");
  const [isV6Searching, setIsV6Searching] = useState(false);
  const [isV6Generating, setIsV6Generating] = useState(false);
  const [v6SearchResult, setV6SearchResult] = useState<MuaV6PrecedentSearchResponse | null>(null);
  const [v6GenerateResult, setV6GenerateResult] = useState<MuaV6GenerateResponse | null>(null);
  const [copiedV6Draft, setCopiedV6Draft] = useState(false);

  // Corpus Draft state (5,650+ parsed MUAs)
  const [corpusMaterial, setCorpusMaterial] = useState<string>("");
  const [corpusEnvironment, setCorpusEnvironment] = useState<string>("");
  const [corpusApplication, setCorpusApplication] = useState<string>("");
  const [corpusO2Percent, setCorpusO2Percent] = useState<string>("");
  const [corpusPressurePsia, setCorpusPressurePsia] = useState<string>("");
  const [corpusTempF, setCorpusTempF] = useState<string>("");
  const [corpusIsHabitable, setCorpusIsHabitable] = useState(false);
  const [corpusIssues, setCorpusIssues] = useState<string[]>([]);
  const [isCorpusSearching, setIsCorpusSearching] = useState(false);
  const [isCorpusGenerating, setIsCorpusGenerating] = useState(false);
  const [corpusSearchResult, setCorpusSearchResult] = useState<CorpusSearchResponse | null>(null);
  const [corpusDraftResult, setCorpusDraftResult] = useState<CorpusDraftResponse | null>(null);
  const [copiedCorpusDraft, setCopiedCorpusDraft] = useState(false);

  const { toast } = useToast();

  // Issue type options
  const issueTypes = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"];
  const locationOptions = ["Habitable", "Non-habitable"];

  // Toggle issue selection (for interactive mode)
  const toggleIssue = (issue: string) => {
    setSearchIssues(prev =>
      prev.includes(issue)
        ? prev.filter(i => i !== issue)
        : [...prev, issue]
    );
  };

  // Toggle precedent selection (for interactive mode)
  const togglePrecedentSelection = (muaNumber: string) => {
    setSelectedPrecedents(prev => {
      const newSet = new Set(prev);
      if (newSet.has(muaNumber)) {
        newSet.delete(muaNumber);
      } else {
        newSet.add(muaNumber);
      }
      return newSet;
    });
  };

  // Toggle analysis expansion
  const toggleAnalysisExpansion = (precedentId: string) => {
    setExpandedAnalyses(prev => {
      const newSet = new Set(prev);
      if (newSet.has(precedentId)) {
        newSet.delete(precedentId);
      } else {
        newSet.add(precedentId);
      }
      return newSet;
    });
  };

  // V3 Synthesis handler
  const handleSynthesize = async () => {
    if (!synthMaterial.trim()) {
      toast({
        title: "Missing Material",
        description: "Please enter a material designation",
        variant: "destructive",
      });
      return;
    }

    if (!synthApplication.trim()) {
      toast({
        title: "Missing Application",
        description: "Please describe the application/use case",
        variant: "destructive",
      });
      return;
    }

    setIsSynthesizing(true);
    setSynthesisResult(null);

    try {
      const response = await fetch(`/api/mua/bok/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          material: synthMaterial,
          issue: synthIssue,
          application: synthApplication,
          environment: synthEnvironment,
          location: synthLocation,
          mass_quantity: synthMass || null,
          program: synthProgram || null,
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Synthesis failed');
      }

      const data: SynthesisResult = await response.json();
      setSynthesisResult(data);

      if (data.success) {
        toast({
          title: "MUA Synthesized",
          description: `Generated rationale from ${data.precedents.length} applicable precedents`,
        });
      } else {
        toast({
          title: "Synthesis Issue",
          description: data.error || "Could not generate MUA",
          variant: "destructive",
        });
      }
    } catch (error) {
      console.error('Synthesis error:', error);
      toast({
        title: "Synthesis Failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsSynthesizing(false);
    }
  };

  // Copy rationale to clipboard
  const handleCopyRationale = async () => {
    if (!synthesisResult?.rationale) return;

    try {
      await navigator.clipboard.writeText(synthesisResult.rationale);
      setCopiedRationale(true);
      toast({
        title: "Copied",
        description: "Rationale copied to clipboard",
      });
      setTimeout(() => setCopiedRationale(false), 2000);
    } catch (error) {
      toast({
        title: "Copy Failed",
        description: "Could not copy to clipboard",
        variant: "destructive",
      });
    }
  };

  // Reset synthesis workflow
  const resetSynthesis = () => {
    setSynthMaterial("");
    setSynthIssue("FLAM");
    setSynthApplication("");
    setSynthEnvironment("");
    setSynthLocation("Non-habitable");
    setSynthMass("");
    setSynthProgram("");
    setSynthesisResult(null);
    setExpandedAnalyses(new Set());
  };

  // V4 Precedent Engine - Toggle deviation selection
  const togglePrecDeviation = (dev: string) => {
    setPrecDeviations(prev =>
      prev.includes(dev) ? prev.filter(d => d !== dev) : [...prev, dev]
    );
  };

  // V4 Precedent Engine - Toggle tier expansion
  const toggleTierExpansion = (tier: number) => {
    setExpandedTiers(prev => {
      const newSet = new Set(prev);
      if (newSet.has(tier)) {
        newSet.delete(tier);
      } else {
        newSet.add(tier);
      }
      return newSet;
    });
  };

  // V4 Precedent Engine - Evaluate precedents
  const handleEvaluatePrecedents = async () => {
    if (!precMaterial.trim()) {
      toast({
        title: "Missing Material",
        description: "Please enter a material designation",
        variant: "destructive",
      });
      return;
    }

    setIsEvaluating(true);
    setEvalResult(null);

    try {
      const response = await fetch(`/api/mua/bok/precedent/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          material_name: precMaterial,
          media: precMedia || null,
          o2_pct: parseFloat(precO2Pct) || 21.0,
          temp_max_f: precTempMax ? parseFloat(precTempMax) : null,
          pressure_max_psia: precPressureMax ? parseFloat(precPressureMax) : null,
          deviation_types: precDeviations,
          location_class: precLocation,
          k: 30,
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Evaluation failed');
      }

      const data: PrecedentEvalResult = await response.json();
      setEvalResult(data);

      toast({
        title: "Evaluation Complete",
        description: `Found ${data.n_total_candidates} precedents - Adequacy: ${data.adequacy}`,
      });
    } catch (error) {
      console.error('Evaluation error:', error);
      toast({
        title: "Evaluation Failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsEvaluating(false);
    }
  };

  // V4 Precedent Engine - Reset
  const resetPrecedentEval = () => {
    setPrecMaterial("");
    setPrecMedia("");
    setPrecO2Pct("21");
    setPrecTempMax("");
    setPrecPressureMax("");
    setPrecDeviations([]);
    setPrecLocation("non_habitable");
    setEvalResult(null);
    setExpandedTiers(new Set([1]));
  };

  // V6 Pipeline - Search precedents
  const handleV6Search = async () => {
    if (!v6Material.trim()) {
      toast({
        title: "Missing Material",
        description: "Please enter a material designation",
        variant: "destructive",
      });
      return;
    }

    setIsV6Searching(true);
    setV6SearchResult(null);

    try {
      const result = await muaV6SearchPrecedents({
        material: v6Material,
        environment: v6EnvDescription ? {
          description: v6EnvDescription,
          o2_percent: v6O2Percent ? parseFloat(v6O2Percent) : undefined,
          pressure_psia: v6PressurePsia ? parseFloat(v6PressurePsia) : undefined,
          temperature_f: v6TempF ? parseFloat(v6TempF) : undefined,
          is_habitable: v6IsHabitable,
        } : undefined,
        k: parseInt(v6K) || 10,
      });

      setV6SearchResult(result);
      toast({
        title: "Precedent Search Complete",
        description: `Found ${result.supporting_count} supporting, ${result.conflicting_count} conflicting precedents`,
      });
    } catch (error) {
      console.error('V6 search error:', error);
      toast({
        title: "Search Failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsV6Searching(false);
    }
  };

  // V6 Pipeline - Generate/Evaluate MUA
  const handleV6Generate = async () => {
    if (!v6Material.trim() || !v6EnvDescription.trim()) {
      toast({
        title: "Missing Fields",
        description: "Material and environment description are required",
        variant: "destructive",
      });
      return;
    }

    setIsV6Generating(true);
    setV6GenerateResult(null);

    try {
      const result = await muaV6Generate({
        material: v6Material,
        environment: {
          description: v6EnvDescription,
          o2_percent: v6O2Percent ? parseFloat(v6O2Percent) : undefined,
          pressure_psia: v6PressurePsia ? parseFloat(v6PressurePsia) : undefined,
          temperature_f: v6TempF ? parseFloat(v6TempF) : undefined,
          is_habitable: v6IsHabitable,
        },
        k: parseInt(v6K) || 10,
        mode: v6Mode,
      });

      setV6GenerateResult(result);
      toast({
        title: "Evaluation Complete",
        description: `Decision: ${result.decision.toUpperCase()} (${(result.confidence_score * 100).toFixed(0)}% confidence)`,
      });
    } catch (error) {
      console.error('V6 generate error:', error);
      toast({
        title: "Generation Failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsV6Generating(false);
    }
  };

  // V6 Pipeline - Copy draft to clipboard
  const handleCopyV6Draft = async () => {
    if (!v6GenerateResult?.draft_text) return;

    try {
      await navigator.clipboard.writeText(v6GenerateResult.draft_text);
      setCopiedV6Draft(true);
      toast({
        title: "Copied",
        description: "MUA draft copied to clipboard",
      });
      setTimeout(() => setCopiedV6Draft(false), 2000);
    } catch (error) {
      toast({
        title: "Copy Failed",
        description: "Could not copy to clipboard",
        variant: "destructive",
      });
    }
  };

  // V6 Pipeline - Reset
  const resetV6Pipeline = () => {
    setV6Material("");
    setV6EnvDescription("");
    setV6O2Percent("");
    setV6PressurePsia("");
    setV6TempF("");
    setV6IsHabitable(false);
    setV6K("10");
    setV6Mode("evaluate_only");
    setV6SearchResult(null);
    setV6GenerateResult(null);
  };

  // Corpus Draft - Search for precedents
  const handleCorpusSearch = async () => {
    if (!corpusMaterial.trim()) {
      toast({
        title: "Missing Material",
        description: "Please enter a material designation",
        variant: "destructive",
      });
      return;
    }

    setIsCorpusSearching(true);
    setCorpusSearchResult(null);

    try {
      const result = await muaCorpusSearch({
        material: corpusMaterial,
        environment: corpusEnvironment || undefined,
        application: corpusApplication || undefined,
        k: 15,
      });

      setCorpusSearchResult(result);
      toast({
        title: "Corpus Search Complete",
        description: `Found ${result.total_found} precedents in parsed MUA corpus`,
      });
    } catch (error) {
      console.error('Corpus search error:', error);
      toast({
        title: "Search Failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsCorpusSearching(false);
    }
  };

  // Corpus Draft - Generate MUA draft
  const handleCorpusDraft = async () => {
    if (!corpusMaterial.trim() || !corpusEnvironment.trim()) {
      toast({
        title: "Missing Required Fields",
        description: "Please enter material and environment",
        variant: "destructive",
      });
      return;
    }

    setIsCorpusGenerating(true);
    setCorpusDraftResult(null);

    try {
      const result = await muaCorpusDraft({
        material: corpusMaterial,
        environment: corpusEnvironment,
        application: corpusApplication || undefined,
        o2_percent: corpusO2Percent ? parseFloat(corpusO2Percent) : undefined,
        pressure_psia: corpusPressurePsia ? parseFloat(corpusPressurePsia) : undefined,
        temperature_f: corpusTempF ? parseFloat(corpusTempF) : undefined,
        is_habitable: corpusIsHabitable,
        issues: corpusIssues.length > 0 ? corpusIssues : undefined,
        k: 15,
      });

      setCorpusDraftResult(result);
      toast({
        title: "Draft Generated",
        description: `${result.recommended_determination} - ${(result.confidence * 100).toFixed(0)}% confidence`,
      });
    } catch (error) {
      console.error('Corpus draft error:', error);
      toast({
        title: "Draft Generation Failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsCorpusGenerating(false);
    }
  };

  // Corpus Draft - Copy rationale
  const handleCopyCorpusDraft = async () => {
    if (!corpusDraftResult?.rationale) return;

    try {
      await navigator.clipboard.writeText(corpusDraftResult.rationale);
      setCopiedCorpusDraft(true);
      toast({
        title: "Copied",
        description: "Rationale copied to clipboard",
      });
      setTimeout(() => setCopiedCorpusDraft(false), 2000);
    } catch (error) {
      toast({
        title: "Copy Failed",
        description: "Could not copy to clipboard",
        variant: "destructive",
      });
    }
  };

  // Corpus Draft - Reset
  const resetCorpusDraft = () => {
    setCorpusMaterial("");
    setCorpusEnvironment("");
    setCorpusApplication("");
    setCorpusO2Percent("");
    setCorpusPressurePsia("");
    setCorpusTempF("");
    setCorpusIsHabitable(false);
    setCorpusIssues([]);
    setCorpusSearchResult(null);
    setCorpusDraftResult(null);
  };

  // Corpus Draft - Toggle issue
  const toggleCorpusIssue = (issue: string) => {
    setCorpusIssues(prev =>
      prev.includes(issue) ? prev.filter(i => i !== issue) : [...prev, issue]
    );
  };

  // Corpus Draft - Get determination badge
  const getCorpusDeterminationBadge = (determination: string) => {
    switch (determination) {
      case 'APPROVED':
        return <Badge className="bg-green-600">APPROVED</Badge>;
      case 'CONDITIONAL':
        return <Badge className="bg-yellow-600">CONDITIONAL</Badge>;
      case 'REQUIRES_REVIEW':
        return <Badge className="bg-orange-600">REQUIRES REVIEW</Badge>;
      default:
        return <Badge variant="outline">{determination}</Badge>;
    }
  };

  // V6 Pipeline - Get decision badge color
  const getDecisionBadge = (decision: GenerationDecision) => {
    switch (decision) {
      case 'proceed':
        return <Badge className="bg-green-600">PROCEED</Badge>;
      case 'warn':
        return <Badge className="bg-yellow-600">WARN</Badge>;
      case 'review':
        return <Badge className="bg-orange-600">REVIEW</Badge>;
      case 'blocked':
        return <Badge className="bg-red-600">BLOCKED</Badge>;
      default:
        return <Badge variant="outline">{decision}</Badge>;
    }
  };

  // V6 Pipeline - Get envelope status badge
  const getEnvelopeBadge = (status: OverlapStatus | null) => {
    if (!status) return null;
    switch (status) {
      case 'within':
        return <Badge variant="outline" className="text-green-600 border-green-600">Within Envelope</Badge>;
      case 'partial_overlap':
        return <Badge variant="outline" className="text-yellow-600 border-yellow-600">Partial Overlap</Badge>;
      case 'extrapolation':
        return <Badge variant="outline" className="text-red-600 border-red-600">Extrapolation</Badge>;
      case 'insufficient_data':
        return <Badge variant="outline" className="text-muted-foreground">Insufficient Data</Badge>;
      default:
        return null;
    }
  };

  // Search for precedents (Step 1 - Interactive mode)
  const handleSearchPrecedents = async () => {
    if (!searchMaterial.trim()) {
      toast({
        title: "Missing Material",
        description: "Please enter a material to search for",
        variant: "destructive",
      });
      return;
    }

    setIsSearching(true);
    setPrecedents([]);
    setSelectedPrecedents(new Set());

    try {
      const response = await fetch(`/api/mua/bok/find`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          material: searchMaterial,
          issues: searchIssues,
          k: 20
        })
      });

      if (!response.ok) {
        throw new Error('Search failed');
      }

      const data = await response.json();
      setPrecedents(data.precedents || []);
      setInteractiveStep(2);

      toast({
        title: "Search Complete",
        description: data.message || `Found ${data.count} precedents`,
      });
    } catch (error) {
      console.error('Search error:', error);
      toast({
        title: "Search Failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsSearching(false);
    }
  };

  // Generate MUA from selected precedents (Step 3 - Interactive mode)
  const handleGenerateFromSelection = async () => {
    if (selectedPrecedents.size === 0) {
      toast({
        title: "No Precedents Selected",
        description: "Please select at least one precedent to use",
        variant: "destructive",
      });
      return;
    }

    // Build issues object
    const issuesObj: Record<string, string> = {};
    searchIssues.forEach(issue => {
      issuesObj[issue] = "B"; // Default to B rating
    });

    setIsGeneratingFromSelection(true);

    try {
      const response = await fetch(`/api/mua/bok/generate-from-selection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          material: searchMaterial,
          material_code: null,
          environment: interactiveEnvironment,
          issues: issuesObj,
          selected_precedent_ids: Array.from(selectedPrecedents),
          application: interactiveApplication,
        })
      });

      if (!response.ok) {
        throw new Error('Generation failed');
      }

      const data = await response.json();
      setGeneratedDraft(data.draft);
      setInteractiveStep(3);

      toast({
        title: "MUA Draft Generated",
        description: data.message || "Draft created with precedent citations",
      });
    } catch (error) {
      console.error('Generation error:', error);
      toast({
        title: "Generation Failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsGeneratingFromSelection(false);
    }
  };

  // Reset interactive workflow
  const resetInteractiveWorkflow = () => {
    setSearchMaterial("");
    setSearchIssues([]);
    setPrecedents([]);
    setSelectedPrecedents(new Set());
    setInteractiveStep(1);
    setInteractiveEnvironment("");
    setInteractiveApplication("");
    setGeneratedDraft(null);
  };

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.xls')) {
        toast({
          title: "Invalid File",
          description: "Please upload an Excel file (.xlsx or .xls)",
          variant: "destructive",
        });
        return;
      }
      setEnrichedFile(file);
      setMuaResults(null);
      toast({
        title: "File Loaded",
        description: `${file.name} ready for MUA generation`,
      });
    }
  };

  const handleGenerateMUAs = async () => {
    if (!enrichedFile) {
      toast({
        title: "No File",
        description: "Please upload an enriched MIUL file first",
        variant: "destructive",
      });
      return;
    }

    setIsGenerating(true);
    setProgress(10);

    try {
      const formData = new FormData();
      formData.append('file', enrichedFile);

      setProgress(30);

      const response = await fetch(
        `/api/mua/generate-batch?program=${encodeURIComponent(programName)}&hardware=${encodeURIComponent(hardwareName)}`,
        {
          method: 'POST',
          body: formData,
        }
      );

      setProgress(70);

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'MUA generation failed');
      }

      const data: MUABatchResponse = await response.json();
      setMuaResults(data);
      setProgress(100);

      toast({
        title: "MUAs Generated",
        description: `Successfully generated ${data.muas_generated} MUA documents`,
      });
    } catch (error) {
      console.error('MUA generation error:', error);
      toast({
        title: "Generation Failed",
        description: error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      });
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownloadExcel = async () => {
    if (!enrichedFile) return;

    try {
      const formData = new FormData();
      formData.append('file', enrichedFile);

      const response = await fetch(
        `/api/mua/generate-batch-excel?program=${encodeURIComponent(programName)}&hardware=${encodeURIComponent(hardwareName)}`,
        {
          method: 'POST',
          body: formData,
        }
      );

      if (!response.ok) throw new Error('Excel generation failed');

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `MIUL_with_MUAs_${Date.now()}.xlsx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      toast({ title: "Download Complete", description: "Excel file with MUAs has been downloaded" });
    } catch (error) {
      toast({ title: "Download Failed", description: "Failed to download Excel file", variant: "destructive" });
    }
  };

  const getCategoryColor = (category: string): "default" | "destructive" | "secondary" | "outline" => {
    switch (category) {
      case 'I': return 'destructive';
      case 'II': return 'default';
      case 'III': return 'secondary';
      default: return 'outline';
    }
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.75) return 'text-green-600';
    if (confidence >= 0.50) return 'text-yellow-600';
    return 'text-red-600';
  };

  const getApplicabilityIcon = (applicability: string) => {
    switch (applicability) {
      case 'YES': return <CheckCircle2 className="h-4 w-4 text-green-600" />;
      case 'PARTIAL': return <AlertTriangle className="h-4 w-4 text-yellow-600" />;
      case 'NO': return <XCircle className="h-4 w-4 text-red-600" />;
      default: return null;
    }
  };

  const getApplicabilityBadge = (applicability: string) => {
    switch (applicability) {
      case 'YES': return <Badge className="bg-green-100 text-green-800 hover:bg-green-100">Applicable</Badge>;
      case 'PARTIAL': return <Badge className="bg-yellow-100 text-yellow-800 hover:bg-yellow-100">Partial</Badge>;
      case 'NO': return <Badge className="bg-red-100 text-red-800 hover:bg-red-100">Not Applicable</Badge>;
      default: return <Badge variant="outline">Unknown</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <FileText className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold flex items-center gap-3">
              MUA Generator
              <PageHelp content={helpContent.muaGenerator} />
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Generate NASA-STD-6016 compliant Material Usage Agreements with LLM-powered synthesis
          </p>
        </div>
        <Badge variant="default" className="flex items-center gap-1">
          <Brain className="h-3 w-3" />
          MUA BOK V3
        </Badge>
      </div>

      {/* Mode Selection Tabs */}
      <Tabs value={mainMode} onValueChange={(v) => setMainMode(v as "synthesis" | "interactive" | "batch" | "precedent" | "v6" | "corpus")} className="w-full">
        <TabsList className="grid w-full grid-cols-6 mb-4">
          <TabsTrigger value="corpus" className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Corpus Draft
          </TabsTrigger>
          <TabsTrigger value="v6" className="flex items-center gap-2">
            <Globe className="h-4 w-4" />
            V6 Pipeline
          </TabsTrigger>
          <TabsTrigger value="synthesis" className="flex items-center gap-2">
            <Brain className="h-4 w-4" />
            AI Synthesis
          </TabsTrigger>
          <TabsTrigger value="precedent" className="flex items-center gap-2">
            <Sparkles className="h-4 w-4" />
            Precedent Engine
          </TabsTrigger>
          <TabsTrigger value="interactive" className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            Interactive
          </TabsTrigger>
          <TabsTrigger value="batch" className="flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4" />
            Batch
          </TabsTrigger>
        </TabsList>

        {/* Corpus Draft Mode Content */}
        <TabsContent value="corpus" className="space-y-6">
          {/* Info Card */}
          <Card className="border-emerald-200 bg-emerald-50/50">
            <CardContent className="pt-4">
              <div className="flex items-start gap-3">
                <FileText className="h-5 w-5 text-emerald-600 mt-0.5" />
                <div>
                  <h3 className="font-medium text-emerald-900">Corpus-Based MUA Draft Generator</h3>
                  <p className="text-sm text-emerald-700 mt-1">
                    Generate MUA drafts from <strong>5,650+ parsed historic MUAs</strong>. The system finds
                    relevant precedents using semantic search, analyzes coverage, and synthesizes rationale
                    with full provenance tracking.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Input Form */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Material & Environment</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Material */}
                <div>
                  <label className="text-sm font-medium">Material Designation *</label>
                  <Input
                    placeholder="e.g., 6061-T6 Aluminum, Inconel 718, Viton"
                    value={corpusMaterial}
                    onChange={(e) => setCorpusMaterial(e.target.value)}
                    className="mt-1"
                  />
                </div>

                {/* Environment */}
                <div>
                  <label className="text-sm font-medium">Environment Description *</label>
                  <Input
                    placeholder="e.g., Enriched oxygen, cabin air, vacuum"
                    value={corpusEnvironment}
                    onChange={(e) => setCorpusEnvironment(e.target.value)}
                    className="mt-1"
                  />
                </div>

                {/* Application */}
                <div>
                  <label className="text-sm font-medium">Application Context</label>
                  <Textarea
                    placeholder="Describe the intended use..."
                    value={corpusApplication}
                    onChange={(e) => setCorpusApplication(e.target.value)}
                    className="mt-1 h-20"
                  />
                </div>

                {/* Environment Parameters */}
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="text-xs font-medium">O2 %</label>
                    <Input
                      type="number"
                      placeholder="21"
                      value={corpusO2Percent}
                      onChange={(e) => setCorpusO2Percent(e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium">Pressure (PSIA)</label>
                    <Input
                      type="number"
                      placeholder="14.7"
                      value={corpusPressurePsia}
                      onChange={(e) => setCorpusPressurePsia(e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium">Temp (°F)</label>
                    <Input
                      type="number"
                      placeholder="85"
                      value={corpusTempF}
                      onChange={(e) => setCorpusTempF(e.target.value)}
                      className="mt-1"
                    />
                  </div>
                </div>

                {/* Habitable checkbox */}
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="corpus-habitable"
                    checked={corpusIsHabitable}
                    onCheckedChange={(checked) => setCorpusIsHabitable(checked === true)}
                  />
                  <label htmlFor="corpus-habitable" className="text-sm">Habitable Location</label>
                </div>

                {/* Issue selection */}
                <div>
                  <label className="text-sm font-medium">Issues to Address</label>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {["flammability", "corrosion", "scc", "toxicity", "offgassing", "o2_compat"].map(issue => (
                      <Badge
                        key={issue}
                        variant={corpusIssues.includes(issue) ? "default" : "outline"}
                        className="cursor-pointer"
                        onClick={() => toggleCorpusIssue(issue)}
                      >
                        {issue}
                      </Badge>
                    ))}
                  </div>
                </div>

                {/* Action buttons */}
                <div className="flex gap-2 pt-2">
                  <Button
                    onClick={handleCorpusSearch}
                    disabled={isCorpusSearching || !corpusMaterial.trim()}
                    variant="outline"
                    className="flex-1"
                  >
                    {isCorpusSearching ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Searching...
                      </>
                    ) : (
                      <>
                        <Search className="h-4 w-4 mr-2" />
                        Search Precedents
                      </>
                    )}
                  </Button>
                  <Button
                    onClick={handleCorpusDraft}
                    disabled={isCorpusGenerating || !corpusMaterial.trim() || !corpusEnvironment.trim()}
                    className="flex-1"
                  >
                    {isCorpusGenerating ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Generating...
                      </>
                    ) : (
                      <>
                        <FileText className="h-4 w-4 mr-2" />
                        Generate Draft
                      </>
                    )}
                  </Button>
                </div>
                <Button variant="ghost" size="sm" onClick={resetCorpusDraft} className="w-full">
                  Reset
                </Button>
              </CardContent>
            </Card>

            {/* Results */}
            <div className="space-y-4">
              {/* Search Results */}
              {corpusSearchResult && (
                <Card>
                  <CardHeader className="pb-2">
                    <div className="flex justify-between items-center">
                      <CardTitle className="text-base">Precedent Search Results</CardTitle>
                      <Badge variant="outline">{corpusSearchResult.total_found} found</Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {corpusSearchResult.precedents.slice(0, 8).map((p, i) => (
                        <div key={i} className="p-2 border rounded text-sm">
                          <div className="flex justify-between items-start">
                            <span className="font-medium">{p.mua_number}</span>
                            <Badge variant={p.determination === "APPROVED" ? "default" : "secondary"} className="text-xs">
                              {p.determination}
                            </Badge>
                          </div>
                          <div className="text-muted-foreground text-xs mt-1">{p.material_designation}</div>
                          <div className="text-muted-foreground text-xs">{p.environment}</div>
                          {p.issues.length > 0 && (
                            <div className="flex gap-1 mt-1 flex-wrap">
                              {p.issues.map((issue, j) => (
                                <Badge key={j} variant="outline" className="text-xs py-0">{issue}</Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Draft Result */}
              {corpusDraftResult && (
                <Card className={
                  corpusDraftResult.recommended_determination === 'APPROVED' ? 'border-green-300' :
                  corpusDraftResult.recommended_determination === 'CONDITIONAL' ? 'border-yellow-300' :
                  'border-orange-300'
                }>
                  <CardHeader className="pb-2">
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-2">
                        <CardTitle className="text-base">Generated Draft</CardTitle>
                        {getCorpusDeterminationBadge(corpusDraftResult.recommended_determination)}
                        <Badge variant="outline">
                          {(corpusDraftResult.confidence * 100).toFixed(0)}% confidence
                        </Badge>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {/* Coverage Assessment */}
                    <div className="p-2 bg-muted rounded text-sm">
                      <strong>Coverage:</strong> {corpusDraftResult.coverage_assessment}
                    </div>

                    {/* Issues Addressed */}
                    {corpusDraftResult.issues_addressed.length > 0 && (
                      <div>
                        <h4 className="text-sm font-medium mb-1">Issues Addressed</h4>
                        <div className="flex gap-1 flex-wrap">
                          {corpusDraftResult.issues_addressed.map((issue, i) => (
                            <Badge key={i} variant="outline" className="text-xs">{issue}</Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Gaps */}
                    {corpusDraftResult.gaps_identified.length > 0 && (
                      <div className="p-2 bg-yellow-50 border border-yellow-200 rounded">
                        <h4 className="text-sm font-medium text-yellow-800 mb-1">Gaps Identified</h4>
                        <ul className="text-xs text-yellow-700 space-y-1">
                          {corpusDraftResult.gaps_identified.map((gap, i) => (
                            <li key={i}>• {gap}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Warnings */}
                    {corpusDraftResult.warnings.length > 0 && (
                      <div className="p-2 bg-red-50 border border-red-200 rounded">
                        <h4 className="text-sm font-medium text-red-800 mb-1">Warnings</h4>
                        <ul className="text-xs text-red-700 space-y-1">
                          {corpusDraftResult.warnings.map((w, i) => (
                            <li key={i}>• {w}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Precedents Cited */}
                    <div>
                      <h4 className="text-sm font-medium mb-1">Precedents Cited ({corpusDraftResult.precedents_cited.length})</h4>
                      <div className="space-y-1 max-h-32 overflow-y-auto">
                        {corpusDraftResult.precedents_cited.map((cit, i) => (
                          <div key={i} className="text-xs p-1 border rounded flex justify-between">
                            <span><strong>{cit.mua_number}</strong> - {cit.material}</span>
                            <Badge variant="outline" className="text-xs py-0">{cit.determination}</Badge>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Rationale */}
                    <div>
                      <div className="flex justify-between items-center mb-1">
                        <h4 className="text-sm font-medium">Synthesized Rationale</h4>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={handleCopyCorpusDraft}
                        >
                          {copiedCorpusDraft ? (
                            <ClipboardCheck className="h-4 w-4 text-green-600" />
                          ) : (
                            <Copy className="h-4 w-4" />
                          )}
                        </Button>
                      </div>
                      <pre className="text-xs bg-muted p-3 rounded overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto">
                        {corpusDraftResult.rationale}
                      </pre>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Empty state */}
              {!corpusSearchResult && !corpusDraftResult && (
                <Card className="border-dashed">
                  <CardContent className="py-8 text-center text-muted-foreground">
                    <FileText className="h-12 w-12 mx-auto mb-3 opacity-50" />
                    <p>Enter material and environment details, then click "Generate Draft" to create an MUA based on historic precedents.</p>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>

        {/* V6 Pipeline Mode Content */}
        <TabsContent value="v6" className="space-y-6">
          {/* Info Card */}
          <Card className="border-blue-200 bg-blue-50/50">
            <CardContent className="pt-4">
              <div className="flex items-start gap-3">
                <Globe className="h-5 w-5 text-blue-600 mt-0.5" />
                <div>
                  <h3 className="font-medium text-blue-900">MUA V6 Evidence Pipeline</h3>
                  <p className="text-sm text-blue-700 mt-1">
                    Six-stage evidence-first pipeline: Material Resolution → Precedent Search →
                    MAPTIS Test Data → Envelope Matching → Decision Engine → Logic Validation.
                    Returns structured decisions with confidence scores and citations.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Input Form */}
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <FileCode className="h-5 w-5" />
                    Query Parameters
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Material */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Material Designation *</label>
                    <Input
                      placeholder="e.g., INCONEL 625, 304 SS, Nylon 6/6"
                      value={v6Material}
                      onChange={(e) => setV6Material(e.target.value)}
                    />
                  </div>

                  {/* Environment Description */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Environment Description *</label>
                    <Textarea
                      placeholder="e.g., Gaseous oxygen service at elevated pressure"
                      value={v6EnvDescription}
                      onChange={(e) => setV6EnvDescription(e.target.value)}
                      rows={2}
                    />
                  </div>

                  {/* Environment Parameters */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">O2 %</label>
                      <Input
                        type="number"
                        placeholder="0-100"
                        value={v6O2Percent}
                        onChange={(e) => setV6O2Percent(e.target.value)}
                        min="0"
                        max="100"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Pressure (PSIA)</label>
                      <Input
                        type="number"
                        placeholder="e.g., 3000"
                        value={v6PressurePsia}
                        onChange={(e) => setV6PressurePsia(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Temp (°F)</label>
                      <Input
                        type="number"
                        placeholder="e.g., 200"
                        value={v6TempF}
                        onChange={(e) => setV6TempF(e.target.value)}
                      />
                    </div>
                  </div>

                  {/* Location & K */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="v6-habitable"
                        checked={v6IsHabitable}
                        onCheckedChange={(checked) => setV6IsHabitable(checked === true)}
                      />
                      <label htmlFor="v6-habitable" className="text-sm">Habitable Location</label>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Results (k)</label>
                      <Input
                        type="number"
                        placeholder="10"
                        value={v6K}
                        onChange={(e) => setV6K(e.target.value)}
                        min="1"
                        max="50"
                      />
                    </div>
                  </div>

                  {/* Mode Selection */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Generation Mode</label>
                    <Select value={v6Mode} onValueChange={(v) => setV6Mode(v as "evaluate_only" | "auto")}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="evaluate_only">Evaluate Only (returns decision)</SelectItem>
                        <SelectItem value="auto">Auto (generate draft if PROCEED)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex gap-2 pt-2">
                    <Button
                      onClick={handleV6Search}
                      disabled={isV6Searching || !v6Material.trim()}
                      variant="outline"
                      className="flex-1"
                    >
                      {isV6Searching ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Searching...
                        </>
                      ) : (
                        <>
                          <Search className="h-4 w-4 mr-2" />
                          Search Precedents
                        </>
                      )}
                    </Button>
                    <Button
                      onClick={handleV6Generate}
                      disabled={isV6Generating || !v6Material.trim() || !v6EnvDescription.trim()}
                      className="flex-1"
                    >
                      {isV6Generating ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Evaluating...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-4 w-4 mr-2" />
                          Evaluate/Generate
                        </>
                      )}
                    </Button>
                  </div>
                  <Button variant="ghost" size="sm" onClick={resetV6Pipeline} className="w-full">
                    Reset
                  </Button>
                </CardContent>
              </Card>

              {/* Precedent Search Results */}
              {v6SearchResult && (
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base">Precedent Search Results</CardTitle>
                      <Badge variant="outline">ID: {v6SearchResult.request_id}</Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Material Resolution Status */}
                    <div className="flex items-center gap-2 p-2 bg-muted rounded">
                      {v6SearchResult.material_resolved ? (
                        <>
                          <CheckCircle className="h-4 w-4 text-green-600" />
                          <span className="text-sm">Material resolved: <code className="bg-background px-1 rounded">{v6SearchResult.material_code}</code></span>
                        </>
                      ) : (
                        <>
                          <AlertCircle className="h-4 w-4 text-yellow-600" />
                          <span className="text-sm">Material not resolved to canonical code</span>
                        </>
                      )}
                    </div>

                    {/* Counts */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="p-3 bg-green-50 rounded-lg text-center">
                        <div className="text-2xl font-bold text-green-700">{v6SearchResult.supporting_count}</div>
                        <div className="text-xs text-green-600">Supporting</div>
                      </div>
                      <div className="p-3 bg-red-50 rounded-lg text-center">
                        <div className="text-2xl font-bold text-red-700">{v6SearchResult.conflicting_count}</div>
                        <div className="text-xs text-red-600">Conflicting</div>
                      </div>
                    </div>

                    {/* Supporting Precedents */}
                    {v6SearchResult.supporting_precedents.length > 0 && (
                      <div>
                        <h4 className="text-sm font-medium mb-2 text-green-700">Supporting Precedents</h4>
                        <div className="space-y-2 max-h-48 overflow-auto">
                          {v6SearchResult.supporting_precedents.slice(0, 5).map((p, i) => (
                            <div key={i} className="p-2 border border-green-200 rounded-lg text-xs bg-green-50/50">
                              <div className="flex items-center justify-between mb-1">
                                <span className="font-mono font-medium">{p.mua_number || 'N/A'}</span>
                                <Badge variant="outline" className="text-xs">{(p.similarity_score * 100).toFixed(0)}%</Badge>
                              </div>
                              <p className="font-medium">{p.material_designation}</p>
                              <p className="text-muted-foreground">{p.rationale_preview}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Conflicting Precedents */}
                    {v6SearchResult.conflicting_precedents.length > 0 && (
                      <div>
                        <h4 className="text-sm font-medium mb-2 text-red-700">Conflicting Precedents</h4>
                        <div className="space-y-2 max-h-48 overflow-auto">
                          {v6SearchResult.conflicting_precedents.slice(0, 5).map((p, i) => (
                            <div key={i} className="p-2 border border-red-200 rounded-lg text-xs bg-red-50/50">
                              <div className="flex items-center justify-between mb-1">
                                <span className="font-mono font-medium">{p.mua_number || 'N/A'}</span>
                                <Badge variant="destructive" className="text-xs">{p.determination}</Badge>
                              </div>
                              <p className="font-medium">{p.material_designation}</p>
                              <p className="text-muted-foreground">{p.rationale_preview}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>

            {/* Right: Results */}
            <div className="space-y-4">
              {v6GenerateResult ? (
                <>
                  {/* Decision Summary Card */}
                  <Card className={
                    v6GenerateResult.decision === 'proceed' ? 'border-green-300' :
                    v6GenerateResult.decision === 'warn' ? 'border-yellow-300' :
                    v6GenerateResult.decision === 'review' ? 'border-orange-300' :
                    'border-red-300'
                  }>
                    <CardContent className="pt-6">
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="font-medium">Decision Result</h3>
                        <div className="flex items-center gap-2">
                          {getDecisionBadge(v6GenerateResult.decision)}
                          <Badge variant="outline">
                            {(v6GenerateResult.confidence_score * 100).toFixed(0)}% confidence
                          </Badge>
                        </div>
                      </div>

                      {/* Request ID and Envelope Status */}
                      <div className="flex items-center gap-3 mb-4 flex-wrap">
                        <Badge variant="secondary">ID: {v6GenerateResult.request_id}</Badge>
                        {getEnvelopeBadge(v6GenerateResult.envelope_status)}
                        {v6GenerateResult.test_data_currency && (
                          <Badge variant="outline">Test Data: {v6GenerateResult.test_data_currency}</Badge>
                        )}
                      </div>

                      {/* Warnings */}
                      {v6GenerateResult.warnings.length > 0 && (
                        <div className="p-3 bg-yellow-50 rounded-lg mb-4">
                          <div className="flex items-center gap-2 text-yellow-800 text-sm font-medium mb-1">
                            <AlertTriangle className="h-4 w-4" />
                            Warnings
                          </div>
                          <ul className="text-xs text-yellow-700 list-disc list-inside">
                            {v6GenerateResult.warnings.map((w, i) => (
                              <li key={i}>{w}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Review Factors */}
                      {v6GenerateResult.review_factors.length > 0 && (
                        <div className="p-3 bg-orange-50 rounded-lg mb-4">
                          <div className="flex items-center gap-2 text-orange-800 text-sm font-medium mb-1">
                            <AlertCircle className="h-4 w-4" />
                            Review Factors
                          </div>
                          <ul className="text-xs text-orange-700 list-disc list-inside">
                            {v6GenerateResult.review_factors.map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Blocking Factors */}
                      {v6GenerateResult.blocking_factors.length > 0 && (
                        <div className="p-3 bg-red-50 rounded-lg mb-4">
                          <div className="flex items-center gap-2 text-red-800 text-sm font-medium mb-1">
                            <XCircle className="h-4 w-4" />
                            Blocking Factors
                          </div>
                          <ul className="text-xs text-red-700 list-disc list-inside">
                            {v6GenerateResult.blocking_factors.map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Precedents Used */}
                      {v6GenerateResult.precedents_used.length > 0 && (
                        <div className="p-3 bg-muted rounded-lg">
                          <h4 className="text-sm font-medium mb-2">Precedents Cited</h4>
                          <div className="flex flex-wrap gap-1">
                            {v6GenerateResult.precedents_used.map((p, i) => (
                              <Badge key={i} variant="outline" className="text-xs">{p}</Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  {/* Generated Draft */}
                  {v6GenerateResult.draft_text && (
                    <Card>
                      <CardHeader className="pb-3">
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-base">Generated MUA Draft</CardTitle>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleCopyV6Draft}
                          >
                            {copiedV6Draft ? (
                              <>
                                <ClipboardCheck className="h-4 w-4 mr-1" />
                                Copied
                              </>
                            ) : (
                              <>
                                <Copy className="h-4 w-4 mr-1" />
                                Copy
                              </>
                            )}
                          </Button>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <div className="border rounded-lg p-4 bg-muted/30 max-h-96 overflow-auto">
                          <pre className="text-sm whitespace-pre-wrap font-mono">
                            {v6GenerateResult.draft_text}
                          </pre>
                        </div>
                      </CardContent>
                    </Card>
                  )}
                </>
              ) : (
                <Card className="p-12">
                  <div className="text-center space-y-3">
                    <Globe className="h-12 w-12 text-muted-foreground mx-auto" />
                    <p className="font-medium">No Evaluation Results Yet</p>
                    <p className="text-sm text-muted-foreground">
                      Enter material and environment parameters, then click "Evaluate/Generate"
                      to run the V6 evidence pipeline.
                    </p>
                  </div>
                </Card>
              )}

              {/* Pipeline Info Card */}
              <Card className="bg-muted/50">
                <CardContent className="pt-4">
                  <h4 className="font-medium text-sm mb-3">V6 Pipeline Stages</h4>
                  <div className="space-y-2 text-xs">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="w-6 h-6 p-0 flex items-center justify-center">1</Badge>
                      <span><strong>Material Resolution</strong> - Canonical code lookup</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="w-6 h-6 p-0 flex items-center justify-center">2</Badge>
                      <span><strong>Precedent Search</strong> - FAISS semantic + string matching</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="w-6 h-6 p-0 flex items-center justify-center">3</Badge>
                      <span><strong>MAPTIS Query</strong> - Test data currency check</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="w-6 h-6 p-0 flex items-center justify-center">4</Badge>
                      <span><strong>Envelope Matching</strong> - Query vs. precedent bounds</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="w-6 h-6 p-0 flex items-center justify-center">5</Badge>
                      <span><strong>Decision Engine</strong> - PROCEED/WARN/REVIEW/BLOCKED</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="w-6 h-6 p-0 flex items-center justify-center">6</Badge>
                      <span><strong>Logic Validation</strong> - LLM rationale synthesis</span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        {/* V3 AI Synthesis Mode Content */}
        <TabsContent value="synthesis" className="space-y-6">
          {/* Info Card */}
          <Card className="bg-gradient-to-r from-primary/5 to-primary/10 border-primary/20">
            <CardContent className="pt-4">
              <div className="flex items-start gap-3">
                <Sparkles className="h-5 w-5 text-primary mt-0.5" />
                <div>
                  <h4 className="font-medium text-sm mb-1">Intelligent MUA Synthesis</h4>
                  <p className="text-xs text-muted-foreground">
                    AI analyzes your use case against historic MUA precedents, determines applicability,
                    and synthesizes an <strong>original rationale</strong> citing relevant precedents.
                    No copy/paste - every rationale is tailored to your specific application.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Input Form */}
            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileCode className="h-4 w-4" />
                    Material & Use Case
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">Material *</label>
                      <Input
                        value={synthMaterial}
                        onChange={(e) => setSynthMaterial(e.target.value)}
                        placeholder="e.g., Nylon 6/6"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-2 block">Issue Type *</label>
                      <Select value={synthIssue} onValueChange={setSynthIssue}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {issueTypes.map(issue => (
                            <SelectItem key={issue} value={issue}>{issue}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div>
                    <label className="text-sm font-medium mb-2 block">Application *</label>
                    <Textarea
                      value={synthApplication}
                      onChange={(e) => setSynthApplication(e.target.value)}
                      placeholder="e.g., Cable tie wraps for wire management in avionics bay"
                      rows={2}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">Environment</label>
                      <Input
                        value={synthEnvironment}
                        onChange={(e) => setSynthEnvironment(e.target.value)}
                        placeholder="e.g., Ambient, <150F"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-2 block">Location</label>
                      <Select value={synthLocation} onValueChange={setSynthLocation}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {locationOptions.map(loc => (
                            <SelectItem key={loc} value={loc}>{loc}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">Mass/Quantity</label>
                      <Input
                        value={synthMass}
                        onChange={(e) => setSynthMass(e.target.value)}
                        placeholder="e.g., 100g total"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-2 block">Program</label>
                      <Input
                        value={synthProgram}
                        onChange={(e) => setSynthProgram(e.target.value)}
                        placeholder="e.g., Orion"
                      />
                    </div>
                  </div>

                  <Button
                    onClick={handleSynthesize}
                    disabled={isSynthesizing || !synthMaterial.trim() || !synthApplication.trim()}
                    className="w-full"
                    size="lg"
                  >
                    {isSynthesizing ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        Analyzing & Synthesizing...
                      </>
                    ) : (
                      <>
                        <Brain className="h-4 w-4 mr-2" />
                        Synthesize MUA
                      </>
                    )}
                  </Button>
                </CardContent>
              </Card>

              {/* Issue Type Info */}
              <Card className="bg-muted/50">
                <CardContent className="pt-4">
                  <h4 className="font-medium text-sm mb-2">Issue Types (Non-A Ratings)</h4>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div><Badge variant="outline" className="mr-1">FLAM</Badge>Flammability</div>
                    <div><Badge variant="outline" className="mr-1">SCC</Badge>Stress Corrosion</div>
                    <div><Badge variant="outline" className="mr-1">CORR</Badge>Corrosion</div>
                    <div><Badge variant="outline" className="mr-1">TVS</Badge>Outgassing</div>
                    <div><Badge variant="outline" className="mr-1">TOX</Badge>Toxicity</div>
                    <div><Badge variant="outline" className="mr-1">FS</Badge>Fluid Service</div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Right: Results */}
            <div className="space-y-4">
              {synthesisResult ? (
                <>
                  {/* Result Summary Card */}
                  <Card className={synthesisResult.success ? "border-green-200" : "border-red-200"}>
                    <CardContent className="pt-6">
                      <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-2">
                          {synthesisResult.success ? (
                            <CheckCircle className="h-5 w-5 text-green-600" />
                          ) : (
                            <AlertCircle className="h-5 w-5 text-red-600" />
                          )}
                          <h3 className="font-medium">
                            {synthesisResult.success ? "MUA Draft Generated" : "Synthesis Issue"}
                          </h3>
                        </div>
                        {synthesisResult.success && (
                          <div className="flex items-center gap-2">
                            <Badge variant={getCategoryColor(synthesisResult.category)}>
                              Category {synthesisResult.category}
                            </Badge>
                            <Badge variant="outline" className={getConfidenceColor(synthesisResult.confidence)}>
                              {(synthesisResult.confidence * 100).toFixed(0)}% confidence
                            </Badge>
                          </div>
                        )}
                      </div>

                      {synthesisResult.error && (
                        <div className="p-3 bg-red-50 rounded-lg text-red-800 text-sm mb-4">
                          {synthesisResult.error}
                        </div>
                      )}

                      {synthesisResult.warnings.length > 0 && (
                        <div className="p-3 bg-yellow-50 rounded-lg mb-4">
                          <div className="flex items-center gap-2 text-yellow-800 text-sm font-medium mb-1">
                            <AlertTriangle className="h-4 w-4" />
                            Warnings
                          </div>
                          <ul className="text-xs text-yellow-700 list-disc list-inside">
                            {synthesisResult.warnings.map((w, i) => (
                              <li key={i}>{w}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      <div className="p-3 bg-muted rounded-lg mb-4">
                        <div className="flex items-center justify-between">
                          <div>
                            <p className="text-sm font-medium">{synthesisResult.material}</p>
                            <p className="text-xs text-muted-foreground">
                              Issue: {synthesisResult.issue} | {synthesisResult.precedents.length} precedent(s) cited
                            </p>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Applicability Analysis Card */}
                  {synthesisResult.applicability_analyses.length > 0 && (
                    <Card>
                      <CardHeader className="pb-3">
                        <CardTitle className="text-base">Precedent Analysis</CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2">
                        {synthesisResult.applicability_analyses.map((analysis) => (
                          <Collapsible
                            key={analysis.precedent_id}
                            open={expandedAnalyses.has(analysis.precedent_id)}
                            onOpenChange={() => toggleAnalysisExpansion(analysis.precedent_id)}
                          >
                            <CollapsibleTrigger className="w-full">
                              <div className={`p-3 border rounded-lg hover:bg-muted/50 transition-colors ${
                                analysis.applicability === 'YES' ? 'border-green-200 bg-green-50/50' :
                                analysis.applicability === 'PARTIAL' ? 'border-yellow-200 bg-yellow-50/50' :
                                'border-red-200 bg-red-50/50'
                              }`}>
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2">
                                    {getApplicabilityIcon(analysis.applicability)}
                                    <span className="font-medium text-sm">{analysis.precedent_id}</span>
                                    {getApplicabilityBadge(analysis.applicability)}
                                    <span className="text-xs text-muted-foreground">
                                      ({(analysis.relevance_score * 100).toFixed(0)}%)
                                    </span>
                                  </div>
                                  {expandedAnalyses.has(analysis.precedent_id) ? (
                                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                                  ) : (
                                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                                  )}
                                </div>
                                <p className="text-xs text-muted-foreground mt-1 text-left">
                                  {analysis.summary}
                                </p>
                              </div>
                            </CollapsibleTrigger>
                            <CollapsibleContent>
                              <div className="p-3 bg-muted/30 rounded-b-lg border-x border-b space-y-2">
                                <h5 className="text-xs font-medium">Comparison Factors:</h5>
                                <div className="grid grid-cols-2 gap-2">
                                  {Object.entries(analysis.factors).map(([key, value]) => (
                                    <div key={key} className="text-xs">
                                      <span className="font-medium capitalize">{key.replace('_', ' ')}:</span>
                                      <Badge variant="outline" className="ml-1 text-xs">{value.match}</Badge>
                                      <p className="text-muted-foreground mt-0.5">{value.reason}</p>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </CollapsibleContent>
                          </Collapsible>
                        ))}
                      </CardContent>
                    </Card>
                  )}

                  {/* Synthesized Rationale Card */}
                  {synthesisResult.rationale && (
                    <Card>
                      <CardHeader className="pb-3">
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-base">Synthesized Rationale</CardTitle>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleCopyRationale}
                          >
                            {copiedRationale ? (
                              <>
                                <ClipboardCheck className="h-4 w-4 mr-1" />
                                Copied
                              </>
                            ) : (
                              <>
                                <Copy className="h-4 w-4 mr-1" />
                                Copy
                              </>
                            )}
                          </Button>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <div className="border rounded-lg p-4 bg-muted/30 max-h-96 overflow-auto">
                          <pre className="text-sm whitespace-pre-wrap font-sans">
                            {synthesisResult.rationale}
                          </pre>
                        </div>
                        <Button
                          variant="outline"
                          onClick={resetSynthesis}
                          className="w-full mt-4"
                        >
                          Start New Synthesis
                        </Button>
                      </CardContent>
                    </Card>
                  )}
                </>
              ) : (
                <Card className="p-12">
                  <div className="text-center space-y-3">
                    <Brain className="h-12 w-12 text-muted-foreground mx-auto" />
                    <p className="font-medium">Ready for Synthesis</p>
                    <p className="text-sm text-muted-foreground">
                      Enter your material and use case details, then click "Synthesize MUA" to generate
                      an original rationale based on historic precedents.
                    </p>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>

        {/* Interactive Mode Content */}
        <TabsContent value="interactive" className="space-y-6">
          {/* Interactive Workflow Steps */}
          <Card>
            <CardContent className="pt-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className={`flex items-start gap-3 ${interactiveStep >= 1 ? 'opacity-100' : 'opacity-50'}`}>
                  <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${interactiveStep === 1 ? 'bg-primary text-primary-foreground' : 'bg-primary/10'}`}>
                    <span className="text-sm font-medium">1</span>
                  </div>
                  <div>
                    <h3 className="font-medium text-sm">Search Precedents</h3>
                    <p className="text-xs text-muted-foreground mt-1">
                      Enter material + issues to find MUAs
                    </p>
                  </div>
                </div>
                <div className={`flex items-start gap-3 ${interactiveStep >= 2 ? 'opacity-100' : 'opacity-50'}`}>
                  <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${interactiveStep === 2 ? 'bg-primary text-primary-foreground' : 'bg-primary/10'}`}>
                    <span className="text-sm font-medium">2</span>
                  </div>
                  <div>
                    <h3 className="font-medium text-sm">Select Applicable</h3>
                    <p className="text-xs text-muted-foreground mt-1">
                      Review rationales and select ones that apply
                    </p>
                  </div>
                </div>
                <div className={`flex items-start gap-3 ${interactiveStep >= 3 ? 'opacity-100' : 'opacity-50'}`}>
                  <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${interactiveStep === 3 ? 'bg-primary text-primary-foreground' : 'bg-primary/10'}`}>
                    <span className="text-sm font-medium">3</span>
                  </div>
                  <div>
                    <h3 className="font-medium text-sm">Generate MUA</h3>
                    <p className="text-xs text-muted-foreground mt-1">
                      Create MUA with precedent citations
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Search & Precedents */}
            <div className="space-y-4">
              {/* Step 1: Search */}
              <Card>
                <CardContent className="pt-6">
                  <h3 className="font-medium mb-4 flex items-center gap-2">
                    <Search className="h-4 w-4" />
                    Step 1: Search for Precedents
                  </h3>
                  <div className="space-y-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">Material</label>
                      <Input
                        type="text"
                        value={searchMaterial}
                        onChange={(e) => setSearchMaterial(e.target.value)}
                        placeholder="e.g., 6061, 316 SS, Inconel 625"
                        className="w-full"
                      />
                      <p className="text-xs text-muted-foreground mt-1">
                        Enter material designation or alloy number
                      </p>
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-2 block">Issues (Optional)</label>
                      <div className="flex flex-wrap gap-2">
                        {issueTypes.map(issue => (
                          <Badge
                            key={issue}
                            variant={searchIssues.includes(issue) ? "default" : "outline"}
                            className="cursor-pointer"
                            onClick={() => toggleIssue(issue)}
                          >
                            {issue}
                          </Badge>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground mt-2">
                        Filter by issue type (leave empty for all)
                      </p>
                    </div>
                    <Button
                      onClick={handleSearchPrecedents}
                      disabled={isSearching || !searchMaterial.trim()}
                      className="w-full"
                    >
                      <Search className="h-4 w-4 mr-2" />
                      {isSearching ? 'Searching...' : 'Search MUA BOK'}
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Step 2: Precedent Results */}
              {precedents.length > 0 && (
                <Card>
                  <CardContent className="pt-6">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="font-medium">Step 2: Select Precedents</h3>
                      <Badge variant="secondary">{precedents.length} found</Badge>
                    </div>
                    <div className="space-y-3 max-h-96 overflow-auto">
                      {precedents.map((p) => (
                        <div
                          key={p.mua_number}
                          className={`p-3 border rounded-lg cursor-pointer transition-colors ${
                            selectedPrecedents.has(p.mua_number)
                              ? 'border-primary bg-primary/5'
                              : 'border-muted hover:border-primary/50'
                          }`}
                          onClick={() => togglePrecedentSelection(p.mua_number)}
                        >
                          <div className="flex items-start gap-3">
                            <Checkbox
                              checked={selectedPrecedents.has(p.mua_number)}
                              onCheckedChange={() => togglePrecedentSelection(p.mua_number)}
                            />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between mb-1">
                                <span className="font-medium text-sm">{p.mua_number}</span>
                                <Badge variant={p.determination === "APPROVED" ? "default" : "secondary"} className="text-xs">
                                  {p.determination}
                                </Badge>
                              </div>
                              <p className="text-xs text-muted-foreground">{p.material}</p>
                              {p.issue && (
                                <p className="text-xs text-muted-foreground mt-1">Issue: {p.issue}</p>
                              )}
                              <p className="text-xs mt-2 text-foreground/80">{p.rationale_summary}</p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-4 pt-4 border-t">
                      <p className="text-sm text-muted-foreground mb-2">
                        Selected: {selectedPrecedents.size} precedent(s)
                      </p>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>

            {/* Right: Generate & Result */}
            <div className="space-y-4">
              {/* Environment & Application */}
              {interactiveStep >= 2 && (
                <Card>
                  <CardContent className="pt-6">
                    <h3 className="font-medium mb-4">Additional Context (Optional)</h3>
                    <div className="space-y-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">Environment</label>
                        <Input
                          type="text"
                          value={interactiveEnvironment}
                          onChange={(e) => setInteractiveEnvironment(e.target.value)}
                          placeholder="e.g., GOX 3000 psi, Cryogenic LH2"
                          className="w-full"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">Application</label>
                        <Textarea
                          value={interactiveApplication}
                          onChange={(e) => setInteractiveApplication(e.target.value)}
                          placeholder="e.g., Valve body, Structural bracket"
                          className="w-full"
                          rows={2}
                        />
                      </div>
                      <Button
                        onClick={handleGenerateFromSelection}
                        disabled={isGeneratingFromSelection || selectedPrecedents.size === 0}
                        className="w-full"
                      >
                        <Sparkles className="h-4 w-4 mr-2" />
                        {isGeneratingFromSelection ? 'Generating...' : `Generate MUA from ${selectedPrecedents.size} Precedent(s)`}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Generated Draft */}
              {generatedDraft && (
                <Card>
                  <CardContent className="pt-6">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="font-medium">Generated MUA Draft</h3>
                      <div className="flex items-center gap-2">
                        <Badge variant={getCategoryColor(generatedDraft.category)}>
                          Category {generatedDraft.category}
                        </Badge>
                        <Badge variant="outline" className={getConfidenceColor(generatedDraft.confidence)}>
                          {(generatedDraft.confidence * 100).toFixed(0)}%
                        </Badge>
                      </div>
                    </div>
                    <div className="space-y-4">
                      <div className="p-3 bg-muted rounded-lg">
                        <p className="text-sm font-medium">{generatedDraft.material}</p>
                        <p className="text-xs text-muted-foreground">
                          Gaps: {Object.entries(generatedDraft.gaps).map(([k, v]) => `${k}(${v})`).join(', ')}
                        </p>
                      </div>
                      <div>
                        <h4 className="text-sm font-medium mb-2">Provenance</h4>
                        <p className="text-xs text-muted-foreground whitespace-pre-wrap">
                          {generatedDraft.provenance_summary}
                        </p>
                      </div>
                      <div>
                        <h4 className="text-sm font-medium mb-2">Rationale</h4>
                        <div className="border rounded-lg p-3 bg-muted/50 max-h-64 overflow-auto">
                          <pre className="text-xs whitespace-pre-wrap font-mono">
                            {generatedDraft.rationale}
                          </pre>
                        </div>
                      </div>
                      <Button variant="outline" onClick={resetInteractiveWorkflow} className="w-full">
                        Start New Search
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Info Card */}
              {interactiveStep === 1 && (
                <Card className="bg-primary/5 border-primary/20">
                  <CardContent className="pt-4">
                    <h4 className="font-medium text-sm mb-2">How Interactive Mode Works</h4>
                    <div className="space-y-2 text-xs text-muted-foreground">
                      <p><strong>1.</strong> Enter a material (e.g., "6061") and optionally select issue types</p>
                      <p><strong>2.</strong> Review MUAs found for that material and select ones with relevant rationales</p>
                      <p><strong>3.</strong> Generate a new MUA draft that cites the selected precedents</p>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>

        {/* Batch Mode Content */}
        <TabsContent value="batch" className="space-y-6">
          {/* Batch Workflow Steps */}
          <Card>
            <CardContent className="pt-6">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                {['Upload MIUL', 'Generate MUAs', 'Review Results', 'Download'].map((step, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                      <span className="text-sm font-medium">{i + 1}</span>
                    </div>
                    <div>
                      <h3 className="font-medium text-sm">{step}</h3>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Program Configuration */}
          <Card className="bg-primary/5 border-primary/20">
            <CardContent className="pt-6">
              <h3 className="font-semibold text-lg mb-4">Program Configuration</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium mb-2 block">Program Name</label>
                  <Input value={programName} onChange={(e) => setProgramName(e.target.value)} placeholder="e.g., ORION" />
                </div>
                <div>
                  <label className="text-sm font-medium mb-2 block">Hardware/System Name</label>
                  <Input value={hardwareName} onChange={(e) => setHardwareName(e.target.value)} placeholder="e.g., Dual Motion Valve" />
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Upload & Generate */}
            <div className="space-y-4">
              <Card>
                <CardContent className="pt-6">
                  <h3 className="font-medium mb-4">Step 1: Upload Source File</h3>
                  <div className="border-2 border-dashed border-muted rounded-lg p-6 text-center">
                    {enrichedFile ? (
                      <div className="space-y-3">
                        <CheckCircle className="h-12 w-12 text-green-500 mx-auto" />
                        <p className="font-medium">{enrichedFile.name}</p>
                        <Button variant="outline" size="sm" onClick={() => { setEnrichedFile(null); setMuaResults(null); }}>Remove</Button>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        <Upload className="h-12 w-12 text-muted-foreground mx-auto" />
                        <p className="text-sm font-medium">Upload Enriched MIUL</p>
                        <Button variant="outline" size="sm" asChild>
                          <label>
                            <input type="file" accept=".xlsx,.xls" onChange={handleFileUpload} className="hidden" />
                            Select File
                          </label>
                        </Button>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="pt-6">
                  <h3 className="font-medium mb-4">Step 2: Generate MUAs</h3>
                  {isGenerating && <Progress value={progress} className="h-2 mb-4" />}
                  <Button onClick={handleGenerateMUAs} disabled={!enrichedFile || isGenerating} className="w-full" size="lg">
                    <FileText className="h-4 w-4 mr-2" />
                    {isGenerating ? 'Generating...' : 'Generate MUAs'}
                  </Button>
                </CardContent>
              </Card>

              {/* NASA Categories Info */}
              <Card className="bg-primary/5 border-primary/20">
                <CardContent className="pt-4">
                  <h4 className="font-medium text-sm mb-2">NASA-STD-6016 Categories</h4>
                  <div className="space-y-2 text-xs">
                    <div className="flex items-start gap-2">
                      <Badge variant="destructive" className="text-xs">I</Badge>
                      <p className="text-muted-foreground">Mission/crew safety - NASA M&P + Program approval</p>
                    </div>
                    <div className="flex items-start gap-2">
                      <Badge variant="default" className="text-xs">II</Badge>
                      <p className="text-muted-foreground">Fails screening - NASA M&P approval</p>
                    </div>
                    <div className="flex items-start gap-2">
                      <Badge variant="secondary" className="text-xs">III</Badge>
                      <p className="text-muted-foreground">Appendix B acceptable - No formal approval</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Right: Results */}
            <div className="space-y-4">
              {muaResults ? (
                <>
                  <Card>
                    <CardContent className="pt-6">
                      <h3 className="font-medium mb-4">Generation Results</h3>
                      <div className="grid grid-cols-2 gap-4 mb-4">
                        <div className="text-center p-3 bg-muted rounded-lg">
                          <div className="text-2xl font-bold">{muaResults.materials_processed}</div>
                          <div className="text-xs text-muted-foreground">Materials Processed</div>
                        </div>
                        <div className="text-center p-3 bg-primary/10 rounded-lg">
                          <div className="text-2xl font-bold text-primary">{muaResults.muas_generated}</div>
                          <div className="text-xs text-muted-foreground">MUAs Generated</div>
                        </div>
                      </div>
                      <Button onClick={handleDownloadExcel} variant="default" size="sm" className="w-full">
                        <FileSpreadsheet className="h-4 w-4 mr-2" />Download Excel
                      </Button>
                    </CardContent>
                  </Card>

                  {muaResults.muas.length > 0 && (
                    <Card>
                      <CardContent className="pt-6">
                        <h3 className="font-medium mb-4">MUA Preview</h3>
                        <Tabs defaultValue="0">
                          <TabsList className="w-full">
                            {muaResults.muas.slice(0, 3).map((_, i) => (
                              <TabsTrigger key={i} value={i.toString()} className="flex-1">MUA {i + 1}</TabsTrigger>
                            ))}
                          </TabsList>
                          {muaResults.muas.slice(0, 3).map((mua, i) => (
                            <TabsContent key={i} value={i.toString()} className="space-y-4">
                              <div className="flex items-center justify-between">
                                <h4 className="font-medium text-sm">{mua.material_code}</h4>
                                <Badge variant={getCategoryColor(mua.mua.category)}>Cat {mua.mua.category}</Badge>
                              </div>
                              <p className="text-xs text-muted-foreground">{mua.designation}</p>
                              <div className="text-xs">
                                <span className="text-muted-foreground">Confidence: </span>
                                <span className={getConfidenceColor(mua.mua.confidence.global)}>
                                  {(mua.mua.confidence.global * 100).toFixed(0)}%
                                </span>
                              </div>
                              <pre className="text-xs border rounded p-3 bg-muted/50 max-h-48 overflow-auto whitespace-pre-wrap">
                                {mua.mua.draft_text}
                              </pre>
                            </TabsContent>
                          ))}
                        </Tabs>
                      </CardContent>
                    </Card>
                  )}
                </>
              ) : (
                <Card className="p-12">
                  <div className="text-center space-y-3">
                    <AlertCircle className="h-12 w-12 text-muted-foreground mx-auto" />
                    <p className="font-medium">No MUAs Generated Yet</p>
                    <p className="text-sm text-muted-foreground">Upload an enriched MIUL and click "Generate MUAs"</p>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>

        {/* V4 Precedent Engine Mode Content */}
        <TabsContent value="precedent" className="space-y-6">
          {/* Info Card */}
          <Card className="border-purple-200 bg-purple-50/50">
            <CardContent className="pt-4">
              <div className="flex items-start gap-3">
                <Sparkles className="h-5 w-5 text-purple-600 mt-0.5" />
                <div>
                  <h3 className="font-medium text-purple-900">V4 Precedent Engine</h3>
                  <p className="text-sm text-purple-700 mt-1">
                    Tiered precedent retrieval with statistical adequacy assessment. Evaluates material/environment
                    equivalence across Tier 1 (exact match), Tier 2 (relaxed tolerance), and Tier 3 (analogs).
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Input Form */}
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Query Parameters</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Material */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Material Designation *</label>
                    <Input
                      placeholder="e.g., Inconel 625, 316 SS, Nylon 6/6"
                      value={precMaterial}
                      onChange={(e) => setPrecMaterial(e.target.value)}
                    />
                  </div>

                  {/* Environment */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Media</label>
                      <Select value={precMedia} onValueChange={setPrecMedia}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select media" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="GOX">GOX (Gaseous Oxygen)</SelectItem>
                          <SelectItem value="LOX">LOX (Liquid Oxygen)</SelectItem>
                          <SelectItem value="GH2">GH2 (Gaseous Hydrogen)</SelectItem>
                          <SelectItem value="LH2">LH2 (Liquid Hydrogen)</SelectItem>
                          <SelectItem value="AIR">Air</SelectItem>
                          <SelectItem value="VACUUM">Vacuum</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">O2 %</label>
                      <Input
                        type="number"
                        placeholder="21"
                        value={precO2Pct}
                        onChange={(e) => setPrecO2Pct(e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Max Temp (°F)</label>
                      <Input
                        type="number"
                        placeholder="e.g., 500"
                        value={precTempMax}
                        onChange={(e) => setPrecTempMax(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Max Pressure (psia)</label>
                      <Input
                        type="number"
                        placeholder="e.g., 3000"
                        value={precPressureMax}
                        onChange={(e) => setPrecPressureMax(e.target.value)}
                      />
                    </div>
                  </div>

                  {/* Location */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Location Class</label>
                    <Select value={precLocation} onValueChange={setPrecLocation}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="habitable">Habitable</SelectItem>
                        <SelectItem value="non_habitable">Non-habitable</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Deviation Types */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Deviation Types</label>
                    <div className="flex flex-wrap gap-2">
                      {issueTypes.map(issue => (
                        <Badge
                          key={issue}
                          variant={precDeviations.includes(issue) ? "default" : "outline"}
                          className="cursor-pointer"
                          onClick={() => togglePrecDeviation(issue)}
                        >
                          {issue}
                        </Badge>
                      ))}
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex gap-2 pt-2">
                    <Button
                      onClick={handleEvaluatePrecedents}
                      disabled={isEvaluating || !precMaterial.trim()}
                      className="flex-1"
                    >
                      {isEvaluating ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Evaluating...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-4 w-4 mr-2" />
                          Evaluate Precedents
                        </>
                      )}
                    </Button>
                    <Button variant="outline" onClick={resetPrecedentEval}>
                      Reset
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Tier Legend */}
              <Card className="bg-muted/50">
                <CardContent className="pt-4">
                  <h4 className="font-medium text-sm mb-3">Tier Definitions</h4>
                  <div className="space-y-2 text-xs">
                    <div className="flex items-center gap-2">
                      <Badge className="bg-green-600">T1</Badge>
                      <span>Exact material + environment + deviation match</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge className="bg-yellow-600">T2</Badge>
                      <span>Same material, relaxed environment tolerance</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge className="bg-orange-600">T3</Badge>
                      <span>Analog material with same deviation alignment</span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Right: Results */}
            <div className="space-y-4">
              {evalResult ? (
                <>
                  {/* Adequacy Summary */}
                  <Card className={
                    evalResult.adequacy === 'STRONG' ? 'border-green-300 bg-green-50' :
                    evalResult.adequacy === 'MODERATE' ? 'border-yellow-300 bg-yellow-50' :
                    'border-red-300 bg-red-50'
                  }>
                    <CardContent className="pt-4">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="font-medium">Precedent Adequacy</h3>
                        <Badge className={
                          evalResult.adequacy === 'STRONG' ? 'bg-green-600' :
                          evalResult.adequacy === 'MODERATE' ? 'bg-yellow-600' :
                          'bg-red-600'
                        }>
                          {evalResult.adequacy}
                        </Badge>
                      </div>
                      <p className="text-sm text-muted-foreground mb-3">{evalResult.adequacy_reasoning}</p>
                      <div className="grid grid-cols-4 gap-2 text-center text-xs">
                        <div className="p-2 bg-white rounded">
                          <div className="font-bold text-lg">{evalResult.n_total_candidates}</div>
                          <div className="text-muted-foreground">Total</div>
                        </div>
                        <div className="p-2 bg-green-100 rounded">
                          <div className="font-bold text-lg text-green-700">{evalResult.n_tier1}</div>
                          <div className="text-green-600">Tier 1</div>
                        </div>
                        <div className="p-2 bg-yellow-100 rounded">
                          <div className="font-bold text-lg text-yellow-700">{evalResult.n_tier2}</div>
                          <div className="text-yellow-600">Tier 2</div>
                        </div>
                        <div className="p-2 bg-orange-100 rounded">
                          <div className="font-bold text-lg text-orange-700">{evalResult.n_tier3}</div>
                          <div className="text-orange-600">Tier 3</div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Recommended Base */}
                  {evalResult.recommended_base && (
                    <Card className="border-purple-200">
                      <CardContent className="pt-4">
                        <h4 className="font-medium text-sm mb-2 flex items-center gap-2">
                          <CheckCircle2 className="h-4 w-4 text-purple-600" />
                          Recommended Base Precedent
                        </h4>
                        <div className="p-3 bg-purple-50 rounded-lg text-sm">
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-mono font-medium">{evalResult.recommended_base.contract_id}</span>
                            <Badge className="bg-green-600">T{evalResult.recommended_base.tier}</Badge>
                          </div>
                          <p className="text-xs text-muted-foreground mb-2">{evalResult.recommended_base.material_name}</p>
                          <p className="text-xs">{evalResult.base_selection_reasoning}</p>
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {/* Statistics */}
                  <Card>
                    <CardContent className="pt-4">
                      <h4 className="font-medium text-sm mb-3">Statistics</h4>
                      <div className="grid grid-cols-2 gap-3 text-sm">
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Approved:</span>
                          <span className="font-medium text-green-600">{evalResult.statistics.n_approved}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Rejected:</span>
                          <span className="font-medium text-red-600">{evalResult.statistics.n_rejected}</span>
                        </div>
                        <div className="flex justify-between col-span-2">
                          <span className="text-muted-foreground">Approval Rate:</span>
                          <span className="font-medium">{(evalResult.statistics.approval_rate * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Tiered Results */}
                  {[1, 2, 3].map(tier => {
                    const matches = tier === 1 ? evalResult.tier1_matches :
                                   tier === 2 ? evalResult.tier2_matches :
                                   evalResult.tier3_matches;
                    if (matches.length === 0) return null;

                    return (
                      <Collapsible
                        key={tier}
                        open={expandedTiers.has(tier)}
                        onOpenChange={() => toggleTierExpansion(tier)}
                      >
                        <Card>
                          <CollapsibleTrigger className="w-full">
                            <CardHeader className="py-3">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                  <Badge className={
                                    tier === 1 ? 'bg-green-600' :
                                    tier === 2 ? 'bg-yellow-600' :
                                    'bg-orange-600'
                                  }>T{tier}</Badge>
                                  <span className="font-medium">Tier {tier} Matches ({matches.length})</span>
                                </div>
                                {expandedTiers.has(tier) ? (
                                  <ChevronDown className="h-4 w-4" />
                                ) : (
                                  <ChevronRight className="h-4 w-4" />
                                )}
                              </div>
                            </CardHeader>
                          </CollapsibleTrigger>
                          <CollapsibleContent>
                            <CardContent className="pt-0 space-y-2">
                              {matches.slice(0, 5).map((m, i) => (
                                <div key={i} className="p-3 border rounded-lg text-sm">
                                  <div className="flex items-center justify-between mb-1">
                                    <span className="font-mono text-xs">{m.contract_id}</span>
                                    <div className="flex gap-1">
                                      {m.material_equivalent && <Badge variant="outline" className="text-xs">Mat</Badge>}
                                      {m.environment_equivalent && <Badge variant="outline" className="text-xs">Env</Badge>}
                                      {m.deviation_equivalent && <Badge variant="outline" className="text-xs">Dev</Badge>}
                                    </div>
                                  </div>
                                  <p className="font-medium text-xs">{m.material_name}</p>
                                  <p className="text-xs text-muted-foreground">{m.environment_delta_summary}</p>
                                  {m.rationale_text && (
                                    <p className="text-xs mt-2 p-2 bg-muted rounded">{m.rationale_text.slice(0, 200)}...</p>
                                  )}
                                </div>
                              ))}
                              {matches.length > 5 && (
                                <p className="text-xs text-center text-muted-foreground">
                                  + {matches.length - 5} more matches
                                </p>
                              )}
                            </CardContent>
                          </CollapsibleContent>
                        </Card>
                      </Collapsible>
                    );
                  })}
                </>
              ) : (
                <Card className="p-12">
                  <div className="text-center space-y-3">
                    <Sparkles className="h-12 w-12 text-muted-foreground mx-auto" />
                    <p className="font-medium">No Evaluation Results Yet</p>
                    <p className="text-sm text-muted-foreground">
                      Enter material and environment parameters, then click "Evaluate Precedents"
                    </p>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
