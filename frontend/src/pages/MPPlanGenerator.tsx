import { useState, useEffect, useCallback, useRef } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Loader2,
  Plus,
  Trash2,
  CheckCircle,
  AlertCircle,
  FileText,
  Download,
  RefreshCw,
  ChevronRight,
  Search,
  Thermometer,
  Shield,
} from 'lucide-react';
import {
  createMPPlanSession,
  addMPPlanEnvironment,
  addMPPlanMaterials,
  getMPPlanQuestions,
  submitMPPlanAnswer,
  runMPPlanCompute,
  generateMPPlanArtifacts,
  getMPPlanArtifactDownloadUrl,
  exportMPPlanJson,
  searchMaptisCode,
  type MPPlanSessionSummary,
  type MPPlanBlockingQuestion,
  type AddMPMaterialRequest,
  type AddMPEnvironmentRequest,
  type MPPlanEnvironment,
  type GeneratedMPArtifact,
  type MaptisSearchResult,
  type MPPlanComputeResult,
} from '@/lib/api';

type Step = 'setup' | 'environment' | 'materials' | 'analysis' | 'generate';

interface MaterialRow {
  id: string;
  name: string;
  application: string;
  quantity: number;
  maptis_code: string;
}

interface EnvironmentPreset {
  label: string;
  name: string;
  o2_pct: number;
  pressure_psia: number;
  temp_min_c: number;
  temp_max_c: number;
  habitable: boolean;
  vacuum_exposure: boolean;
  lunar_dust: boolean;
}

const ENV_PRESETS: EnvironmentPreset[] = [
  { label: 'ISS Habitable', name: 'ISS Habitable Volume', o2_pct: 23.5, pressure_psia: 14.7, temp_min_c: 18, temp_max_c: 27, habitable: true, vacuum_exposure: false, lunar_dust: false },
  { label: 'SLS Launch', name: 'SLS Launch Environment', o2_pct: 21.0, pressure_psia: 14.7, temp_min_c: -20, temp_max_c: 60, habitable: false, vacuum_exposure: false, lunar_dust: false },
  { label: 'Lunar Surface', name: 'Lunar Surface EVA', o2_pct: 100, pressure_psia: 4.3, temp_min_c: -170, temp_max_c: 120, habitable: false, vacuum_exposure: true, lunar_dust: true },
  { label: 'O₂ Service', name: 'Oxygen Service', o2_pct: 100, pressure_psia: 14.7, temp_min_c: -183, temp_max_c: 60, habitable: false, vacuum_exposure: false, lunar_dust: false },
];

const PROGRAM_PHASES = ['PDR', 'CDR', 'Flight', 'Ground Ops', 'Prototype', 'Qual Test'];

const QUESTION_TYPE_LABELS: Record<string, { label: string; color: string }> = {
  material_ambiguous: { label: 'Material', color: 'bg-blue-100 text-blue-700' },
  environment_missing: { label: 'Environment', color: 'bg-purple-100 text-purple-700' },
  tailoring_approval: { label: 'Tailoring', color: 'bg-amber-100 text-amber-700' },
  closure_selection: { label: 'Closure', color: 'bg-red-100 text-red-700' },
  grouping_confirmation: { label: 'Grouping', color: 'bg-slate-100 text-slate-700' },
  quantity_missing: { label: 'Quantity', color: 'bg-teal-100 text-teal-700' },
  cots_criticality: { label: 'COTS', color: 'bg-orange-100 text-orange-700' },
  precedent_validation: { label: 'Precedent', color: 'bg-indigo-100 text-indigo-700' },
};

export default function MPPlanGenerator() {
  // Step state
  const [step, setStep] = useState<Step>('setup');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Session state
  const [programName, setProgramName] = useState('');
  const [programPhase, setProgramPhase] = useState('');
  const [session, setSession] = useState<MPPlanSessionSummary | null>(null);

  // Environment state
  const [envName, setEnvName] = useState('');
  const [envO2, setEnvO2] = useState('21.0');
  const [envPressure, setEnvPressure] = useState('14.7');
  const [envTempMin, setEnvTempMin] = useState('-20');
  const [envTempMax, setEnvTempMax] = useState('60');
  const [envHabitable, setEnvHabitable] = useState(false);
  const [envVacuum, setEnvVacuum] = useState(false);
  const [envLunarDust, setEnvLunarDust] = useState(false);
  const [addedEnvironments, setAddedEnvironments] = useState<MPPlanEnvironment[]>([]);

  // Materials state
  const [materials, setMaterials] = useState<MaterialRow[]>([
    { id: '1', name: '', application: '', quantity: 1, maptis_code: '' },
  ]);
  const [maptisSearchResults, setMaptisSearchResults] = useState<Record<string, MaptisSearchResult[]>>({});
  const [searchingMaptis, setSearchingMaptis] = useState<Record<string, boolean>>({});
  const searchTimeouts = useRef<Record<string, NodeJS.Timeout>>({});

  // Analysis state
  const [computeResult, setComputeResult] = useState<MPPlanComputeResult | null>(null);
  const [questions, setQuestions] = useState<MPPlanBlockingQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  // Generate state
  const [artifacts, setArtifacts] = useState<GeneratedMPArtifact[]>([]);

  // --------------------------------------------------------------------------
  // Setup handlers
  // --------------------------------------------------------------------------
  const handleCreateSession = async () => {
    if (!programName) return;
    setLoading(true);
    setError(null);

    try {
      const response = await createMPPlanSession({
        program_name: programName,
        program_phase: programPhase || undefined,
      });
      setSession(response);
      setStep('environment');
    } catch (err) {
      console.error('Failed to create session:', err);
      setError(err instanceof Error ? err.message : 'Failed to create session');
    } finally {
      setLoading(false);
    }
  };

  // --------------------------------------------------------------------------
  // Environment handlers
  // --------------------------------------------------------------------------
  const applyEnvPreset = (preset: EnvironmentPreset) => {
    setEnvName(preset.name);
    setEnvO2(String(preset.o2_pct));
    setEnvPressure(String(preset.pressure_psia));
    setEnvTempMin(String(preset.temp_min_c));
    setEnvTempMax(String(preset.temp_max_c));
    setEnvHabitable(preset.habitable);
    setEnvVacuum(preset.vacuum_exposure);
    setEnvLunarDust(preset.lunar_dust);
  };

  const handleAddEnvironment = async () => {
    if (!session || !envName) return;
    setLoading(true);
    setError(null);

    try {
      const env: AddMPEnvironmentRequest = {
        name: envName,
        o2_pct: parseFloat(envO2) || 21.0,
        pressure_psia: parseFloat(envPressure) || 14.7,
        temp_min_c: parseFloat(envTempMin) || -20,
        temp_max_c: parseFloat(envTempMax) || 60,
        habitable: envHabitable,
        vacuum_exposure: envVacuum,
        lunar_dust: envLunarDust,
      };
      const result = await addMPPlanEnvironment(session.session_id, env);
      setAddedEnvironments((prev) => [...prev, result]);
      // Clear form for next
      setEnvName('');
      setEnvO2('21.0');
      setEnvPressure('14.7');
      setEnvTempMin('-20');
      setEnvTempMax('60');
      setEnvHabitable(false);
      setEnvVacuum(false);
      setEnvLunarDust(false);
    } catch (err) {
      console.error('Failed to add environment:', err);
      setError(err instanceof Error ? err.message : 'Failed to add environment');
    } finally {
      setLoading(false);
    }
  };

  // --------------------------------------------------------------------------
  // Material handlers
  // --------------------------------------------------------------------------
  const addMaterialRow = () => {
    setMaterials([
      ...materials,
      { id: String(Date.now()), name: '', application: '', quantity: 1, maptis_code: '' },
    ]);
  };

  const removeMaterialRow = (id: string) => {
    if (materials.length > 1) {
      setMaterials(materials.filter((m) => m.id !== id));
    }
  };

  const updateMaterial = (id: string, field: keyof MaterialRow, value: string | number) => {
    setMaterials(
      materials.map((m) => (m.id === id ? { ...m, [field]: value } : m))
    );

    if (field === 'name' && typeof value === 'string' && value.length >= 2) {
      if (searchTimeouts.current[id]) {
        clearTimeout(searchTimeouts.current[id]);
      }
      searchTimeouts.current[id] = setTimeout(() => {
        searchMaptisForMaterial(id, value);
      }, 500);
    }
  };

  const searchMaptisForMaterial = async (materialId: string, materialName: string) => {
    if (materialName.length < 2) return;
    setSearchingMaptis((prev) => ({ ...prev, [materialId]: true }));

    try {
      const response = await searchMaptisCode(materialName);
      setMaptisSearchResults((prev) => ({ ...prev, [materialId]: response.results }));
    } catch (err) {
      console.error('MAPTIS search error:', err);
      setMaptisSearchResults((prev) => ({ ...prev, [materialId]: [] }));
    } finally {
      setSearchingMaptis((prev) => ({ ...prev, [materialId]: false }));
    }
  };

  const selectMaptisCode = (materialId: string, code: string) => {
    setMaterials(
      materials.map((m) => (m.id === materialId ? { ...m, maptis_code: code } : m))
    );
    setMaptisSearchResults((prev) => ({ ...prev, [materialId]: [] }));
  };

  const handleAddMaterials = async () => {
    if (!session) return;

    const validMaterials = materials.filter((m) => m.name.trim());
    if (validMaterials.length === 0) {
      setError('Please add at least one material');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const materialsToAdd: AddMPMaterialRequest[] = validMaterials.map((m) => ({
        name: m.name,
        application: m.application || 'General',
        quantity: m.quantity || 1,
        maptis_code: m.maptis_code || undefined,
      }));

      await addMPPlanMaterials(session.session_id, materialsToAdd);

      // Run compute
      const result = await runMPPlanCompute(session.session_id);
      setComputeResult(result);
      setQuestions(result.blocking_questions);

      // Update session
      setSession({
        ...session,
        material_count: session.material_count + validMaterials.length,
        can_generate: result.can_generate,
        blockers: result.blockers,
        blocking_question_count: result.blocking_questions.length,
        nonconformance_count: result.nonconformances,
      });

      if (result.blocking_questions.length > 0 || !result.can_generate) {
        setStep('analysis');
      } else {
        setStep('generate');
      }
    } catch (err) {
      console.error('Failed to add materials:', err);
      setError(err instanceof Error ? err.message : 'Failed to add materials');
    } finally {
      setLoading(false);
    }
  };

  // --------------------------------------------------------------------------
  // Analysis handlers
  // --------------------------------------------------------------------------
  const handleSubmitAnswer = async (questionId: string) => {
    if (!session || !answers[questionId]) return;
    setLoading(true);
    setError(null);

    try {
      const result = await submitMPPlanAnswer(session.session_id, {
        question_id: questionId,
        answer: answers[questionId],
        rationale: '',
      });

      // Refresh questions
      const questionsResult = await getMPPlanQuestions(session.session_id);
      setQuestions(questionsResult.questions);

      // Update session
      setSession({
        ...session,
        can_generate: result.can_generate,
        blockers: result.blockers,
        blocking_question_count: questionsResult.count,
      });

      if (questionsResult.count === 0 && result.can_generate) {
        setStep('generate');
      }
    } catch (err) {
      console.error('Failed to submit answer:', err);
      setError(err instanceof Error ? err.message : 'Failed to submit answer');
    } finally {
      setLoading(false);
    }
  };

  // --------------------------------------------------------------------------
  // Generate handlers
  // --------------------------------------------------------------------------
  const handleGenerate = async () => {
    if (!session) return;
    setLoading(true);
    setError(null);

    try {
      const result = await generateMPPlanArtifacts(session.session_id, {
        artifacts: ['mp_plan_docx', 'mp_plan_json'],
      });
      setArtifacts(result.artifacts);
    } catch (err) {
      console.error('Failed to generate:', err);
      setError(err instanceof Error ? err.message : 'Failed to generate artifacts');
    } finally {
      setLoading(false);
    }
  };

  const downloadArtifact = (artifact: GeneratedMPArtifact) => {
    if (!session || !artifact.artifact_id) return;
    window.open(getMPPlanArtifactDownloadUrl(session.session_id, artifact.artifact_id), '_blank');
  };

  const handleExportJson = async () => {
    if (!session) return;
    try {
      const data = await exportMPPlanJson(session.session_id);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mp_plan_${session.session_id.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export JSON:', err);
      setError(err instanceof Error ? err.message : 'Failed to export JSON');
    }
  };

  const resetSession = () => {
    setStep('setup');
    setSession(null);
    setProgramName('');
    setProgramPhase('');
    setAddedEnvironments([]);
    setMaterials([{ id: '1', name: '', application: '', quantity: 1, maptis_code: '' }]);
    setMaptisSearchResults({});
    setComputeResult(null);
    setQuestions([]);
    setAnswers({});
    setArtifacts([]);
    setError(null);
  };

  // --------------------------------------------------------------------------
  // Render
  // --------------------------------------------------------------------------
  return (
    <div>
      <PageHeader
        title="M&P Plan Generator"
        description="Generate Materials & Processes Plans with automated NASA-STD-6016C compliance analysis"
      />

      {/* Progress Steps */}
      <div className="mb-8">
        <div className="flex items-center gap-2 text-sm">
          <StepIndicator step="setup" currentStep={step} label="1. Setup" />
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
          <StepIndicator step="environment" currentStep={step} label="2. Environment" />
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
          <StepIndicator step="materials" currentStep={step} label="3. Materials" />
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
          <StepIndicator step="analysis" currentStep={step} label="4. Analysis" />
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
          <StepIndicator step="generate" currentStep={step} label="5. Generate" />
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          {error}
        </div>
      )}

      {/* ================================================================ */}
      {/* Step 1: Setup */}
      {/* ================================================================ */}
      {step === 'setup' && (
        <Card>
          <CardHeader>
            <CardTitle>Create New M&P Plan Session</CardTitle>
            <CardDescription>
              Enter program details to start a NASA-STD-6016C compliance session
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="programName">Program Name *</Label>
                <Input
                  id="programName"
                  placeholder="e.g., Artemis II, ISS Resupply"
                  value={programName}
                  onChange={(e) => setProgramName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="programPhase">Program Phase</Label>
                <Select value={programPhase} onValueChange={setProgramPhase}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select phase..." />
                  </SelectTrigger>
                  <SelectContent>
                    {PROGRAM_PHASES.map((phase) => (
                      <SelectItem key={phase} value={phase}>
                        {phase}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <Button onClick={handleCreateSession} disabled={loading || !programName}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create Session
            </Button>
          </CardContent>
        </Card>
      )}

      {/* ================================================================ */}
      {/* Step 2: Environment */}
      {/* ================================================================ */}
      {step === 'environment' && session && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Thermometer className="h-5 w-5" />
              Define Service Environment
            </CardTitle>
            <CardDescription>
              Define one or more environments where materials will be used
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Quick-fill presets */}
            <div>
              <Label className="text-sm font-medium mb-2 block">Quick Fill</Label>
              <div className="flex flex-wrap gap-2">
                {ENV_PRESETS.map((preset) => (
                  <Button
                    key={preset.label}
                    variant="outline"
                    size="sm"
                    onClick={() => applyEnvPreset(preset)}
                    className="text-xs"
                  >
                    {preset.label}
                  </Button>
                ))}
              </div>
            </div>

            {/* Environment form */}
            <div className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label className="text-xs">Environment Name *</Label>
                  <Input
                    placeholder="e.g., ISS Habitable Volume"
                    value={envName}
                    onChange={(e) => setEnvName(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">O₂ Concentration (%)</Label>
                  <Input
                    type="number"
                    step="0.1"
                    value={envO2}
                    onChange={(e) => setEnvO2(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                  <Label className="text-xs">Pressure (psia)</Label>
                  <Input
                    type="number"
                    step="0.1"
                    value={envPressure}
                    onChange={(e) => setEnvPressure(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Temp Min (°C)</Label>
                  <Input
                    type="number"
                    value={envTempMin}
                    onChange={(e) => setEnvTempMin(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Temp Max (°C)</Label>
                  <Input
                    type="number"
                    value={envTempMax}
                    onChange={(e) => setEnvTempMax(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex gap-6">
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    checked={envHabitable}
                    onChange={(e) => setEnvHabitable(e.target.checked)}
                    className="rounded"
                  />
                  Habitable
                </label>
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    checked={envVacuum}
                    onChange={(e) => setEnvVacuum(e.target.checked)}
                    className="rounded"
                  />
                  Vacuum Exposure
                </label>
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    checked={envLunarDust}
                    onChange={(e) => setEnvLunarDust(e.target.checked)}
                    className="rounded"
                  />
                  Lunar Dust
                </label>
              </div>
            </div>

            <Button onClick={handleAddEnvironment} disabled={loading || !envName} variant="outline">
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <Plus className="mr-2 h-4 w-4" />
              Add Environment
            </Button>

            {/* Added environments */}
            {addedEnvironments.length > 0 && (
              <div className="space-y-2">
                <Label className="text-sm font-medium">Added Environments</Label>
                <div className="flex flex-wrap gap-2">
                  {addedEnvironments.map((env) => (
                    <Badge key={env.environment_id} variant="secondary" className="py-1 px-3 text-xs">
                      {env.name} — {env.o2_pct}% O₂, {env.pressure_psia} psia
                      {env.habitable && ', Habitable'}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-3 pt-4 border-t">
              <Button
                onClick={() => setStep('materials')}
                disabled={addedEnvironments.length === 0}
              >
                Continue to Materials
              </Button>
              <Button variant="ghost" onClick={() => setStep('setup')}>
                Back
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ================================================================ */}
      {/* Step 3: Materials */}
      {/* ================================================================ */}
      {step === 'materials' && session && (
        <Card>
          <CardHeader>
            <CardTitle>Add Materials</CardTitle>
            <CardDescription>
              Enter material names — MAPTIS codes will be automatically looked up
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-4">
              {materials.map((material, index) => (
                <div key={material.id} className="space-y-2">
                  <div className="grid gap-3 sm:grid-cols-5 items-end">
                    <div className="space-y-1 relative">
                      {index === 0 && <Label className="text-xs">Material Name *</Label>}
                      <div className="relative">
                        <Input
                          placeholder="e.g., Kapton, Viton A, 316L"
                          value={material.name}
                          onChange={(e) => updateMaterial(material.id, 'name', e.target.value)}
                        />
                        {searchingMaptis[material.id] && (
                          <Loader2 className="absolute right-2 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />
                        )}
                      </div>
                    </div>
                    <div className="space-y-1">
                      {index === 0 && <Label className="text-xs">Application</Label>}
                      <Input
                        placeholder="e.g., Insulation, O-Ring"
                        value={material.application}
                        onChange={(e) => updateMaterial(material.id, 'application', e.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      {index === 0 && <Label className="text-xs">Quantity</Label>}
                      <Input
                        type="number"
                        min="1"
                        value={material.quantity}
                        onChange={(e) =>
                          updateMaterial(material.id, 'quantity', parseInt(e.target.value) || 1)
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      {index === 0 && <Label className="text-xs">MAPTIS Code</Label>}
                      <Input
                        placeholder="Auto-lookup"
                        value={material.maptis_code}
                        onChange={(e) => updateMaterial(material.id, 'maptis_code', e.target.value)}
                        className={material.maptis_code ? 'bg-green-50 border-green-300' : ''}
                      />
                    </div>
                    <div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => removeMaterialRow(material.id)}
                        disabled={materials.length === 1}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  {/* MAPTIS Suggestions */}
                  {maptisSearchResults[material.id]?.length > 0 && !material.maptis_code && (
                    <div className="ml-0 p-2 bg-blue-50 border border-blue-200 rounded-md">
                      <p className="text-xs text-blue-700 mb-1 flex items-center gap-1">
                        <Search className="h-3 w-3" />
                        Found {maptisSearchResults[material.id].length} MAPTIS match(es):
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {maptisSearchResults[material.id].map((result, i) => (
                          <Button
                            key={i}
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs bg-white hover:bg-blue-100"
                            onClick={() => selectMaptisCode(material.id, result.material_code)}
                          >
                            <span className="font-mono">{result.material_code}</span>
                            <span className="text-muted-foreground ml-1">
                              ({result.designation.slice(0, 20)}{result.designation.length > 20 ? '...' : ''})
                            </span>
                          </Button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            <Button variant="outline" onClick={addMaterialRow}>
              <Plus className="mr-2 h-4 w-4" />
              Add Material
            </Button>

            <div className="flex gap-3 pt-4 border-t">
              <Button onClick={handleAddMaterials} disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Compute Compliance
              </Button>
              <Button variant="ghost" onClick={() => setStep('environment')}>
                Back
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ================================================================ */}
      {/* Step 4: Analysis */}
      {/* ================================================================ */}
      {step === 'analysis' && session && (
        <div className="space-y-6">
          {/* Compute Summary */}
          {computeResult && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Shield className="h-5 w-5" />
                  Compliance Analysis
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 sm:grid-cols-5">
                  <div className="text-center p-3 bg-muted rounded-lg">
                    <div className="text-xl font-bold">{computeResult.materials}</div>
                    <div className="text-xs text-muted-foreground">Materials</div>
                  </div>
                  <div className="text-center p-3 bg-muted rounded-lg">
                    <div className="text-xl font-bold">{computeResult.environments}</div>
                    <div className="text-xs text-muted-foreground">Environments</div>
                  </div>
                  <div className="text-center p-3 bg-muted rounded-lg">
                    <div className="text-xl font-bold">{computeResult.determinations}</div>
                    <div className="text-xs text-muted-foreground">Determinations</div>
                  </div>
                  <div className="text-center p-3 bg-muted rounded-lg">
                    <div className="text-xl font-bold text-red-600">{computeResult.nonconformances}</div>
                    <div className="text-xs text-muted-foreground">Nonconformances</div>
                  </div>
                  <div className="text-center p-3 bg-muted rounded-lg">
                    <div className="text-xl font-bold text-amber-600">{computeResult.hitl_required}</div>
                    <div className="text-xs text-muted-foreground">HITL Required</div>
                  </div>
                </div>

                {session.blockers.length > 0 && (
                  <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                    <p className="text-sm font-medium text-yellow-800">Blockers:</p>
                    <ul className="text-sm text-yellow-700 list-disc list-inside">
                      {session.blockers.map((blocker, i) => (
                        <li key={i}>{blocker}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Blocking Questions */}
          <Card>
            <CardHeader>
              <CardTitle>Blocking Questions</CardTitle>
              <CardDescription>
                Answer these questions to resolve compliance gaps and proceed to generation
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {questions.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <CheckCircle className="h-12 w-12 mx-auto mb-3 text-green-500" />
                  <p className="font-medium">All questions resolved!</p>
                  {session.can_generate ? (
                    <Button onClick={() => setStep('generate')} className="mt-4">
                      Proceed to Generate
                    </Button>
                  ) : (
                    <p className="text-sm mt-2">
                      Generation is still blocked. Check blockers above.
                    </p>
                  )}
                </div>
              ) : (
                questions.map((question) => {
                  const typeInfo = QUESTION_TYPE_LABELS[question.question_type] || {
                    label: question.question_type,
                    color: 'bg-slate-100 text-slate-700',
                  };
                  return (
                    <Card key={question.question_id} className="border-l-4 border-l-yellow-400">
                      <CardContent className="pt-4">
                        <div className="space-y-3">
                          <div>
                            <Badge className={`mb-2 ${typeInfo.color} border-0`}>
                              {typeInfo.label}
                            </Badge>
                            <p className="font-medium">{question.question_text}</p>
                            {question.context && (
                              <p className="text-sm text-muted-foreground mt-1">{question.context}</p>
                            )}
                          </div>

                          {question.options && question.options.length > 0 ? (
                            <Select
                              value={answers[question.question_id] || ''}
                              onValueChange={(value) =>
                                setAnswers({ ...answers, [question.question_id]: value })
                              }
                            >
                              <SelectTrigger>
                                <SelectValue placeholder="Select an option..." />
                              </SelectTrigger>
                              <SelectContent>
                                {question.options.map((option) => (
                                  <SelectItem key={option} value={option}>
                                    {option}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          ) : (
                            <Input
                              placeholder="Enter your answer..."
                              value={answers[question.question_id] || ''}
                              onChange={(e) =>
                                setAnswers({ ...answers, [question.question_id]: e.target.value })
                              }
                            />
                          )}

                          <Button
                            onClick={() => handleSubmitAnswer(question.question_id)}
                            disabled={loading || !answers[question.question_id]}
                            size="sm"
                          >
                            {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                            Submit Answer
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </CardContent>
          </Card>

          <div className="flex gap-3">
            <Button variant="ghost" onClick={() => setStep('materials')}>
              Back to Materials
            </Button>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Step 5: Generate */}
      {/* ================================================================ */}
      {step === 'generate' && session && (
        <div className="space-y-6">
          {/* Session Summary */}
          <Card>
            <CardHeader>
              <CardTitle>Session Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-4">
                <div className="text-center p-4 bg-muted rounded-lg">
                  <div className="text-2xl font-bold">{session.material_count}</div>
                  <div className="text-sm text-muted-foreground">Materials</div>
                </div>
                <div className="text-center p-4 bg-muted rounded-lg">
                  <div className="text-2xl font-bold">{session.environment_count || addedEnvironments.length}</div>
                  <div className="text-sm text-muted-foreground">Environments</div>
                </div>
                <div className="text-center p-4 bg-muted rounded-lg">
                  <div className="text-2xl font-bold">{session.nonconformance_count}</div>
                  <div className="text-sm text-muted-foreground">Gaps Found</div>
                </div>
                <div className="text-center p-4 bg-muted rounded-lg">
                  <div className="flex items-center justify-center gap-2">
                    {session.can_generate ? (
                      <CheckCircle className="h-5 w-5 text-green-500" />
                    ) : (
                      <AlertCircle className="h-5 w-5 text-yellow-500" />
                    )}
                    <span className="text-sm">
                      {session.can_generate ? 'Ready' : 'Blocked'}
                    </span>
                  </div>
                  <div className="text-sm text-muted-foreground">Status</div>
                </div>
              </div>

              {session.blockers.length > 0 && (
                <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <p className="text-sm font-medium text-yellow-800">Blockers:</p>
                  <ul className="text-sm text-yellow-700 list-disc list-inside">
                    {session.blockers.map((blocker, i) => (
                      <li key={i}>{blocker}</li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Generate Button */}
          {session.can_generate && artifacts.length === 0 && (
            <Card>
              <CardContent className="pt-6">
                <div className="text-center">
                  <FileText className="h-12 w-12 mx-auto mb-3 text-muted-foreground" />
                  <h3 className="font-medium mb-2">Ready to Generate</h3>
                  <p className="text-sm text-muted-foreground mb-4">
                    Generate your M&P Plan (DOCX) and structured JSON export
                  </p>
                  <Button onClick={handleGenerate} disabled={loading}>
                    {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Generate Documents
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Generated Artifacts */}
          {artifacts.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Generated Artifacts</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {artifacts.map((artifact, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between p-3 bg-muted rounded-lg"
                    >
                      <div className="flex items-center gap-3">
                        <FileText className="h-5 w-5 text-muted-foreground" />
                        <div>
                          <div className="font-medium">{artifact.name}</div>
                          {artifact.size_bytes && (
                            <div className="text-xs text-muted-foreground">
                              {(artifact.size_bytes / 1024).toFixed(1)} KB
                            </div>
                          )}
                        </div>
                      </div>
                      {artifact.artifact_id ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => downloadArtifact(artifact)}
                        >
                          <Download className="mr-2 h-4 w-4" />
                          Download
                        </Button>
                      ) : artifact.error ? (
                        <Badge variant="destructive">{artifact.error}</Badge>
                      ) : null}
                    </div>
                  ))}
                </div>

                <div className="mt-4">
                  <Button variant="outline" size="sm" onClick={handleExportJson}>
                    <Download className="mr-2 h-4 w-4" />
                    Export Full JSON
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Start Over */}
          <div className="flex gap-3">
            <Button variant="outline" onClick={resetSession}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Start New Session
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// Step indicator component
function StepIndicator({
  step,
  currentStep,
  label,
}: {
  step: Step;
  currentStep: Step;
  label: string;
}) {
  const steps: Step[] = ['setup', 'environment', 'materials', 'analysis', 'generate'];
  const currentIndex = steps.indexOf(currentStep);
  const stepIndex = steps.indexOf(step);

  const isActive = step === currentStep;
  const isComplete = stepIndex < currentIndex;

  return (
    <span
      className={`px-3 py-1 rounded-full text-xs font-medium ${
        isActive
          ? 'bg-primary text-primary-foreground'
          : isComplete
          ? 'bg-green-100 text-green-700'
          : 'bg-muted text-muted-foreground'
      }`}
    >
      {isComplete && <CheckCircle className="inline h-3 w-3 mr-1" />}
      {label}
    </span>
  );
}
