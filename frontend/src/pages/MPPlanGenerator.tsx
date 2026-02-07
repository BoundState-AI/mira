import { useState, useEffect, useCallback, useRef } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { StatusBadge } from '@/components/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
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
} from 'lucide-react';
import {
  createMPPlanSession,
  listMPPlanVehiclePresets,
  addMPPlanMaterials,
  getMPPlanQuestions,
  submitMPPlanAnswer,
  runMPPlanCompute,
  generateMPPlanArtifacts,
  getMPPlanArtifactDownloadUrl,
  getMPPlanReviewPacket,
  searchMaptisCode,
  type MPPlanSessionSummary,
  type MPPlanVehiclePreset,
  type MPPlanBlockingQuestion,
  type AddMPMaterialRequest,
  type GeneratedMPArtifact,
  type MaptisSearchResult,
} from '@/lib/api';

type Step = 'setup' | 'materials' | 'questions' | 'generate';

interface MaterialRow {
  id: string;
  name: string;
  application: string;
  quantity: number;
  maptis_code: string;
}

export default function MPPlanGenerator() {
  // State
  const [step, setStep] = useState<Step>('setup');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Session state
  const [programName, setProgramName] = useState('');
  const [vehiclePreset, setVehiclePreset] = useState('');
  const [presets, setPresets] = useState<MPPlanVehiclePreset[]>([]);
  const [session, setSession] = useState<MPPlanSessionSummary | null>(null);

  // Materials state
  const [materials, setMaterials] = useState<MaterialRow[]>([
    { id: '1', name: '', application: '', quantity: 1, maptis_code: '' },
  ]);
  const [maptisSearchResults, setMaptisSearchResults] = useState<Record<string, MaptisSearchResult[]>>({});
  const [searchingMaptis, setSearchingMaptis] = useState<Record<string, boolean>>({});
  const searchTimeouts = useRef<Record<string, NodeJS.Timeout>>({});

  // Questions state
  const [questions, setQuestions] = useState<MPPlanBlockingQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  // Generate state
  const [artifacts, setArtifacts] = useState<GeneratedMPArtifact[]>([]);
  const [reviewPacket, setReviewPacket] = useState<Record<string, unknown> | null>(null);

  // Load vehicle presets on mount
  useEffect(() => {
    loadPresets();
  }, []);

  const loadPresets = async () => {
    try {
      const response = await listMPPlanVehiclePresets();
      setPresets(response.presets);
    } catch (err) {
      console.error('Failed to load presets:', err);
    }
  };

  const handleCreateSession = async () => {
    if (!programName) return;

    setLoading(true);
    setError(null);

    try {
      const response = await createMPPlanSession({
        program_name: programName,
        vehicle_preset: vehiclePreset || undefined,
      });
      setSession(response);
      setStep('materials');
    } catch (err) {
      console.error('Failed to create session:', err);
      setError(err instanceof Error ? err.message : 'Failed to create session');
    } finally {
      setLoading(false);
    }
  };

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

    // Trigger MAPTIS search when material name changes
    if (field === 'name' && typeof value === 'string' && value.length >= 2) {
      // Clear previous timeout for this material
      if (searchTimeouts.current[id]) {
        clearTimeout(searchTimeouts.current[id]);
      }
      // Debounce the search
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
    // Clear suggestions after selection
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

      // Run compute and get questions
      const computeResult = await runMPPlanCompute(session.session_id);
      setQuestions(computeResult.blocking_questions);

      // Update session state
      setSession({
        ...session,
        material_count: session.material_count + validMaterials.length,
        can_generate: computeResult.can_generate,
        blockers: computeResult.blockers,
        blocking_question_count: computeResult.blocking_questions.length,
        nonconformance_count: computeResult.nonconformances,
      });

      if (computeResult.blocking_questions.length > 0) {
        setStep('questions');
      } else if (computeResult.can_generate) {
        setStep('generate');
      }
    } catch (err) {
      console.error('Failed to add materials:', err);
      setError(err instanceof Error ? err.message : 'Failed to add materials');
    } finally {
      setLoading(false);
    }
  };

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

  const handleGenerate = async () => {
    if (!session) return;

    setLoading(true);
    setError(null);

    try {
      const result = await generateMPPlanArtifacts(session.session_id, {
        artifacts: ['mp_plan_docx', 'miul_xlsx', 'review_packet'],
      });
      setArtifacts(result.artifacts);

      // Also load review packet
      const packet = await getMPPlanReviewPacket(session.session_id);
      setReviewPacket(packet);
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
          <StepIndicator step="materials" currentStep={step} label="2. Materials" />
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
          <StepIndicator step="questions" currentStep={step} label="3. Questions" />
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
          <StepIndicator step="generate" currentStep={step} label="4. Generate" />
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          {error}
        </div>
      )}

      {/* Step 1: Setup */}
      {step === 'setup' && (
        <Card>
          <CardHeader>
            <CardTitle>Create New M&P Plan Session</CardTitle>
            <CardDescription>
              Enter program details and select a vehicle preset to get started
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
                <Label htmlFor="vehiclePreset">Vehicle Preset</Label>
                <Select value={vehiclePreset} onValueChange={setVehiclePreset}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a vehicle..." />
                  </SelectTrigger>
                  <SelectContent>
                    {presets.map((preset) => (
                      <SelectItem key={preset.preset_id} value={preset.preset_id}>
                        {preset.name} ({preset.o2_pct}% O₂, {preset.pressure_psia} psia)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Presets auto-configure environment parameters
                </p>
              </div>
            </div>

            <Button onClick={handleCreateSession} disabled={loading || !programName}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create Session
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Step 2: Materials */}
      {step === 'materials' && session && (
        <Card>
          <CardHeader>
            <CardTitle>Add Materials</CardTitle>
            <CardDescription>
              Enter material names - MAPTIS codes will be automatically looked up.
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
                      <div className="flex gap-1">
                        <Input
                          placeholder="Auto-lookup"
                          value={material.maptis_code}
                          onChange={(e) => updateMaterial(material.id, 'maptis_code', e.target.value)}
                          className={material.maptis_code ? 'bg-green-50 border-green-300' : ''}
                        />
                      </div>
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
                    <div className="ml-0 sm:ml-0 p-2 bg-blue-50 border border-blue-200 rounded-md">
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
                Continue to Analysis
              </Button>
              <Button variant="ghost" onClick={() => setStep('setup')}>
                Back
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3: Questions */}
      {step === 'questions' && session && (
        <Card>
          <CardHeader>
            <CardTitle>Answer Blocking Questions</CardTitle>
            <CardDescription>
              The following questions must be answered before generation
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {questions.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <CheckCircle className="h-12 w-12 mx-auto mb-3 text-green-500" />
                <p>All questions answered!</p>
                <Button onClick={() => setStep('generate')} className="mt-4">
                  Continue to Generate
                </Button>
              </div>
            ) : (
              questions.map((question) => (
                <Card key={question.question_id} className="border-l-4 border-l-yellow-400">
                  <CardContent className="pt-4">
                    <div className="space-y-3">
                      <div>
                        <Badge variant="outline" className="mb-2">
                          {question.question_type}
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
                          placeholder="Enter your answer (e.g., MAPTIS code)..."
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
              ))
            )}

            <div className="flex gap-3 pt-4 border-t">
              <Button variant="ghost" onClick={() => setStep('materials')}>
                Back to Materials
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Generate */}
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
                  <div className="text-2xl font-bold">{session.environment_count}</div>
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
                    Generate your M&P Plan, MIUL, and Review Packet
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
              </CardContent>
            </Card>
          )}

          {/* Review Packet Preview */}
          {reviewPacket && (
            <Card>
              <CardHeader>
                <CardTitle>Review Packet Preview</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {reviewPacket.key_findings && (
                    <div>
                      <h4 className="font-medium mb-2">Key Findings</h4>
                      <ul className="text-sm space-y-1">
                        {(reviewPacket.key_findings as string[]).map((finding, i) => (
                          <li key={i} className="flex items-start gap-2">
                            <span className="text-muted-foreground">•</span>
                            {finding}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {reviewPacket.predicted_questions && (
                    <div>
                      <h4 className="font-medium mb-2">Predicted Review Questions</h4>
                      <ul className="text-sm space-y-2">
                        {(reviewPacket.predicted_questions as Array<{question: string; answer: string; confidence: string}>).map((q, i) => (
                          <li key={i} className="border-l-2 border-blue-200 pl-3">
                            <p className="font-medium">{q.question}</p>
                            <p className="text-muted-foreground text-xs mt-1">{q.answer}</p>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Start Over */}
          <div className="flex gap-3">
            <Button
              variant="outline"
              onClick={() => {
                setStep('setup');
                setSession(null);
                setMaterials([{ id: '1', name: '', application: '', quantity: 1, maptis_code: '' }]);
                setQuestions([]);
                setAnswers({});
                setArtifacts([]);
                setReviewPacket(null);
                setError(null);
              }}
            >
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
  const steps: Step[] = ['setup', 'materials', 'questions', 'generate'];
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
