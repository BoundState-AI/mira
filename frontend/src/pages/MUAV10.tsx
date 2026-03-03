import { useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Download,
  Loader2,
  RotateCcw,
} from 'lucide-react';

import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  classifyMuaV10Row,
  downloadBlob,
  finalizeMua,
  processSingleMaterial,
  processMuaV10MiulWorkbook,
  generateMuaDocx,
  type GenerateDocxRequest,
  type MaterialClass,
  type MuaV10PipelineResult,
  type ProcessMiulResponse,
} from '@/lib/mua-v10-api';

const ISSUE_COLUMNS = ['FLAM', 'FS', 'TOX', 'TVS', 'SCC', 'CORR'] as const;

type IssueColumn = (typeof ISSUE_COLUMNS)[number];
type RatingsState = Record<IssueColumn, string>;
type WizardStep = 1 | 2 | 3 | 4 | 5;
type ReviewAction = 'approve' | 'edit' | 'reject';

const DEFAULT_RATINGS: RatingsState = {
  FLAM: '',
  FS: '',
  TOX: '',
  TVS: '',
  SCC: '',
  CORR: '',
};

const RATING_HINTS: Record<string, Record<string, string>> = {
  FLAM: {
    A: 'Pass - >=5 samples, burn <=6.0 inches',
    C: 'FAIL - burn >6.0 inches in promoted combustion (O2 environment)',
    I: 'Incomplete pass - <5 samples, all passing. Administrative gap, not failure.',
    S: 'Special test - needs manual review of actual test report',
    U: 'No usable test data exists',
    N: 'Not applicable / not tested - context dependent',
  },
  FS: {
    A: 'Pass - 48hr immersion screening in hydrazine/MMH/N2O4',
    C: 'Fail/unsupported in this model - treated as manual review.',
    U: 'Untested - no Test 15 data. Test 15 covers hydrazine/N2O4 ONLY, not H2.',
  },
  TOX: {
    A: 'Pass - TML <=1.0%, CVCM <=0.1%',
    U: 'Untested for offgassing (Test 7)',
    K: 'UNKNOWN - undocumented rating. Probable MIUL builder error.',
  },
  TVS: {
    A: 'Pass - meets ASTM E595 outgassing criteria',
    C: 'FAIL - exceeds ASTM E595 outgassing criteria',
    U: 'Untested for thermal vacuum stability',
  },
  SCC: {
    A: 'Resistant to stress corrosion cracking',
    B: 'Conditional - batch/lot verification required. NOT an automatic pass.',
    C: 'Susceptible under certain conditions',
    N: 'Not applicable',
    U: 'Untested for SCC',
  },
  CORR: {
    A: 'Resistant to corrosion',
    B: 'Conditional - batch/lot verification required',
    U: 'Untested for corrosion',
  },
};

function toApiRatings(ratings: RatingsState): Record<string, string> {
  // ONLY send columns the user actually entered a value for.
  // "Not provided" ≠ "missing in MAPTIS." Sending nulls for empty
  // columns causes the classifier to flag them as MISSING_DATA.
  const result: Record<string, string> = {};
  for (const column of ISSUE_COLUMNS) {
    const value = ratings[column].trim().toUpperCase();
    if (value) {
      result[column] = value;
    }
  }
  return result;
}

function parsePartNumbers(raw: string): string[] {
  return raw
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}

function normalizeRating(value: string): string {
  return value.slice(0, 1).toUpperCase();
}

export default function MUAV10() {
  // Step 1
  const [maptisCode, setMaptisCode] = useState('');
  const [materialDesignation, setMaterialDesignation] = useState('');
  const [materialClass, setMaterialClass] = useState<MaterialClass>('metal');
  const [media, setMedia] = useState('');
  const [environment, setEnvironment] = useState<'habitable' | 'non-habitable'>('non-habitable');
  const [o2Percent, setO2Percent] = useState('');
  const [batchVerified, setBatchVerified] = useState(false);
  const [project, setProject] = useState('');
  const [system, setSystem] = useState('');
  const [pressure, setPressure] = useState('');
  const [temperature, setTemperature] = useState('');
  const [partNumbers, setPartNumbers] = useState('');
  const [miulFile, setMiulFile] = useState<File | null>(null);
  const [miulImporting, setMiulImporting] = useState(false);
  const [miulImport, setMiulImport] = useState<ProcessMiulResponse | null>(null);
  const [miulSelectedIndex, setMiulSelectedIndex] = useState(0);

  // Step 2
  const [ratings, setRatings] = useState<RatingsState>({ ...DEFAULT_RATINGS });

  // Wizard state
  const [step, setStep] = useState<WizardStep>(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Steps 3-5
  const [pipelineResult, setPipelineResult] = useState<MuaV10PipelineResult | null>(null);
  const [editedRationales, setEditedRationales] = useState<Record<string, string>>({});
  const [editedDispositions, setEditedDispositions] = useState<Record<string, string>>({});
  const [downloading, setDownloading] = useState<Record<string, boolean>>({});
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [formActions, setFormActions] = useState<Record<string, ReviewAction>>({});
  const [resolutionCandidates, setResolutionCandidates] = useState<Array<Record<string, unknown>>>([]);
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null);
  const [precedentExpanded, setPrecedentExpanded] = useState<Record<string, boolean>>({});

  const clearDownstreamState = () => {
    setPipelineResult(null);
    setEditedRationales({});
    setEditedDispositions({});
    setDownloading({});
    setSessionId(null);
    setFinalizing(false);
    setFormActions({});
    setResolutionCandidates([]);
    setDraftSavedAt(null);
    setPrecedentExpanded({});
  };

  const resetWizard = () => {
    setStep(1);
    setMaptisCode('');
    setMaterialDesignation('');
    setMaterialClass('metal');
    setMedia('');
    setEnvironment('non-habitable');
    setO2Percent('');
    setBatchVerified(false);
    setProject('');
    setSystem('');
    setPressure('');
    setTemperature('');
    setPartNumbers('');
    setMiulFile(null);
    setMiulImporting(false);
    setMiulImport(null);
    setMiulSelectedIndex(0);
    setRatings({ ...DEFAULT_RATINGS });
    setLoading(false);
    setError(null);
    clearDownstreamState();
  };

  const handleStep1Next = () => {
    if (!media.trim() || (!maptisCode.trim() && !materialDesignation.trim())) {
      setError('Enter media and either MAPTIS code or material designation.');
      return;
    }
    setError(null);
    setStep(2);
  };

  const handleEditStep1 = () => {
    clearDownstreamState();
    setError(null);
    setStep(1);
  };

  const handleEditStep2 = () => {
    clearDownstreamState();
    setError(null);
    setStep(2);
  };

  const applyImportedMiulRow = (row: ProcessMiulResponse['results'][number]) => {
    const importedRatings: RatingsState = { ...DEFAULT_RATINGS };
    for (const column of ISSUE_COLUMNS) {
      importedRatings[column] = row.ratings[column] || '';
    }

    const normalizedEnvironment = row.environment.toLowerCase().includes('habitable')
      && !row.environment.toLowerCase().includes('non')
      ? 'habitable'
      : 'non-habitable';

    setMaptisCode(row.maptis_code);
    setMaterialDesignation(row.material_designation || row.pipeline_result.material_designation || '');
    setMaterialClass(row.pipeline_result.material_class);
    setMedia(row.media || media);
    setEnvironment(normalizedEnvironment);
    setPartNumbers(row.part_number || '');
    setRatings(importedRatings);

    clearDownstreamState();
    setPipelineResult(row.pipeline_result);
    setResolutionCandidates([]);
    setDraftSavedAt(null);

    const initRationales: Record<string, string> = {};
    const initDispositions: Record<string, string> = {};
    const nextActions: Record<string, ReviewAction> = {};
    for (const form of row.pipeline_result.forms) {
      initRationales[form.issue] = form.rationale;
      initDispositions[form.issue] = form.disposition;
      nextActions[form.issue] = 'approve';
    }
    setEditedRationales(initRationales);
    setEditedDispositions(initDispositions);
    setFormActions(nextActions);

    setError(null);
    setStep(3);
  };

  const handleImportMiul = async () => {
    if (!miulFile) {
      setError('Choose a completed MIUL workbook (.xlsx/.xlsm) first.');
      return;
    }

    setMiulImporting(true);
    setError(null);
    clearDownstreamState();

    try {
      const response = await processMuaV10MiulWorkbook(miulFile, {
        media_override: media.trim() || undefined,
        environment_override: environment,
        project: project.trim() || undefined,
        system: system.trim() || undefined,
        max_rows: 200,
      });

      setMiulImport(response);
      setMiulSelectedIndex(0);

      if (!response.results.length) {
        throw new Error('MIUL import succeeded but no non-A trigger rows were found.');
      }

      applyImportedMiulRow(response.results[0]);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to process MIUL workbook';
      setError(message);
    } finally {
      setMiulImporting(false);
    }
  };

  const handleClassify = async () => {
    setLoading(true);
    setError(null);

    try {
      const parsedO2 = o2Percent.trim() ? Number(o2Percent) : undefined;
      const partNumbersList = parsePartNumbers(partNumbers);
      const payload = {
        maptis_code: maptisCode.trim() || undefined,
        material_designation: materialDesignation,
        material_class: materialClass,
        media,
        environment,
        o2_percent: Number.isFinite(parsedO2) ? parsedO2 : undefined,
        batch_verified: batchVerified,
        ratings: toApiRatings(ratings),
        part_numbers: partNumbersList,
        part_count: partNumbersList.length > 0 ? partNumbersList.length : 1,
        project,
        system,
        pressure,
        temperature,
      };

      let pipeline: MuaV10PipelineResult | null = null;
      let resolvedSessionId: string | null = null;

      try {
        const response = await processSingleMaterial({
          material_text: materialDesignation,
          ...payload,
        });

        if (response.status !== 'ok' || !response.pipeline_result) {
          setResolutionCandidates(response.candidates || []);
          const message =
            response.material_resolution?.message ||
            'Material resolution requires manual MAPTIS code selection.';
          throw new Error(message);
        }

        pipeline = response.pipeline_result;
        resolvedSessionId = response.session_id ?? null;
        setResolutionCandidates([]);
      } catch (runtimeErr) {
        const message = runtimeErr instanceof Error ? runtimeErr.message : String(runtimeErr);
        const isRouteMiss = message.includes('404') || message.toLowerCase().includes('not found');
        if (!isRouteMiss) {
          throw runtimeErr;
        }

        // Compatibility fallback for stale backend instances that do not yet
        // expose /process-single.
        pipeline = await classifyMuaV10Row(payload);
        resolvedSessionId = null;
        setResolutionCandidates([]);
      }

      if (!pipeline) {
        throw new Error('Failed to classify MUA row');
      }

      setPipelineResult(pipeline);
      setMaptisCode(pipeline.maptis_code);
      setSessionId(resolvedSessionId);
      setDraftSavedAt(resolvedSessionId ? new Date().toISOString() : null);

      const initRationales: Record<string, string> = {};
      const initDispositions: Record<string, string> = {};
      const nextActions: Record<string, ReviewAction> = {};
      for (const form of pipeline.forms) {
        initRationales[form.issue] = form.rationale;
        initDispositions[form.issue] = form.disposition;
        nextActions[form.issue] = 'approve';
      }
      setEditedRationales(initRationales);
      setEditedDispositions(initDispositions);
      setFormActions(nextActions);

      setStep(3);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to classify MUA row';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const handleStep3Next = () => {
    setError(null);
    setStep(4);
  };

  const handleStep4Next = async () => {
    if (!pipelineResult) {
      setStep(5);
      return;
    }

    setFinalizing(true);
    setError(null);

    try {
      const parsedO2 = o2Percent.trim() ? Number(o2Percent) : undefined;
      const partNumbersList = parsePartNumbers(partNumbers);

      const actions = pipelineResult.forms.map((form) => {
        const editedRationale = editedRationales[form.issue];
        const editedDisposition = editedDispositions[form.issue];
        const changed =
          (editedRationale ?? form.rationale) !== form.rationale ||
          (editedDisposition ?? form.disposition) !== form.disposition;
        const selectedAction = formActions[form.issue];
        const action: ReviewAction = selectedAction || (changed ? 'edit' : 'approve');

        return {
          issue: form.issue,
          action,
          rationale: editedRationale ?? form.rationale,
          disposition: editedDisposition ?? form.disposition,
          comment: '',
        };
      });

      const response = await finalizeMua({
        session_id: sessionId ?? undefined,
        maptis_code: pipelineResult.maptis_code || maptisCode || undefined,
        material_designation: materialDesignation,
        material_class: materialClass,
        media,
        environment,
        o2_percent: Number.isFinite(parsedO2) ? parsedO2 : undefined,
        batch_verified: batchVerified,
        ratings: toApiRatings(ratings),
        part_numbers: partNumbersList,
        part_count: partNumbersList.length > 0 ? partNumbersList.length : 1,
        project,
        system,
        pressure,
        temperature,
        actions,
      });

      const formsByIssue = new Map(response.forms.map((form) => [form.issue, form]));
      const mergedForms = pipelineResult.forms.map((form) => formsByIssue.get(form.issue) ?? form);
      setPipelineResult({
        ...pipelineResult,
        forms: mergedForms,
      });

      const nextRationales: Record<string, string> = {};
      const nextDispositions: Record<string, string> = {};
      for (const form of mergedForms) {
        nextRationales[form.issue] = form.rationale;
        nextDispositions[form.issue] = form.disposition;
      }
      setEditedRationales(nextRationales);
      setEditedDispositions(nextDispositions);
      setDraftSavedAt(response.session_id ? new Date().toISOString() : draftSavedAt);
      setSessionId(response.session_id ?? sessionId);

      setStep(5);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to finalize MUA edits';
      setError(message);
    } finally {
      setFinalizing(false);
    }
  };

  const handleDownload = async (form: MuaV10PipelineResult['forms'][number]) => {
    const key = form.issue;
    setDownloading((prev) => ({ ...prev, [key]: true }));
    setError(null);

    try {
      const parsedO2 = o2Percent.trim() ? Number(o2Percent) : undefined;
      const partNumbersList = parsePartNumbers(partNumbers);

      const request: GenerateDocxRequest = {
        maptis_code: pipelineResult?.maptis_code || maptisCode || undefined,
        material_designation: materialDesignation,
        material_class: materialClass,
        media,
        environment,
        o2_percent: Number.isFinite(parsedO2) ? parsedO2 : undefined,
        batch_verified: batchVerified,
        ratings: { [form.issue]: form.rating },
        project,
        system,
        pressure,
        temperature,
        part_numbers: partNumbersList,
        part_count: partNumbersList.length > 0 ? partNumbersList.length : 1,
        rationale_override: editedRationales[form.issue] || undefined,
        disposition_override: editedDispositions[form.issue] || undefined,
        session_id: sessionId || undefined,
        issue: sessionId ? form.issue : undefined,
      };

      const blob = await generateMuaDocx(request);
      const filename = `MUA_${form.issue}_${pipelineResult?.maptis_code || maptisCode || 'resolved'}.docx`;
      downloadBlob(blob, filename);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to generate DOCX';
      setError(message);
    } finally {
      setDownloading((prev) => ({ ...prev, [key]: false }));
    }
  };

  const setRating = (column: IssueColumn, value: string) => {
    setRatings((prev) => ({
      ...prev,
      [column]: normalizeRating(value),
    }));
  };

  const nonEmptyRatings = ISSUE_COLUMNS
    .map((column) => `${column}=${ratings[column]}`)
    .filter((entry) => !entry.endsWith('='));

  const partNumbersList = parsePartNumbers(partNumbers);
  const automatableCount = pipelineResult?.automatable_count ?? 0;
  const humanRequiredCount = pipelineResult?.human_required_count ?? 0;
  const hasMaterialIdentifier = Boolean(maptisCode.trim() || materialDesignation.trim());
  const saveDraftLabel = draftSavedAt ? `Draft saved ${new Date(draftSavedAt).toLocaleString()}` : 'Save Draft';

  const getConfidencePct = (value: number): number => {
    if (!Number.isFinite(value)) return 0;
    return Math.max(0, Math.min(100, Math.round(value * 100)));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <PageHeader
          title="MUA Writer"
          description="Flag-first classifier - walk through each classification step"
        />
        <div className="flex items-center gap-2">
          {sessionId ? (
            <Button type="button" variant="outline" size="sm" onClick={() => setDraftSavedAt(new Date().toISOString())}>
              {saveDraftLabel}
            </Button>
          ) : null}
          {step > 1 ? (
            <Button variant="outline" size="sm" onClick={resetWizard}>
              <RotateCcw className="mr-2 h-4 w-4" />
              Start Over
            </Button>
          ) : null}
        </div>
      </div>

      <Card className={step === 1 ? '' : 'opacity-75'}>
        {step === 1 ? (
          <>
            <CardHeader>
              <CardTitle>Step 1: Who / What / Where</CardTitle>
              <CardDescription>Identify the material, MAPTIS code, and service environment.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="rounded-md border p-3 space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="miul-upload">Optional: Import completed MIUL workbook</Label>
                  <Input
                    id="miul-upload"
                    type="file"
                    accept=".xlsx,.xlsm"
                    onChange={(event) => setMiulFile(event.target.files?.[0] ?? null)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Uses MAPTIS codes + non-A ratings from your MIUL and runs the v10 pipeline.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" variant="outline" onClick={handleImportMiul} disabled={miulImporting || !miulFile}>
                    {miulImporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    Import MIUL
                  </Button>
                  {miulImport ? (
                    <span className="text-xs text-muted-foreground">
                      {miulImport.processed_rows} processed / {miulImport.total_rows} total
                    </span>
                  ) : null}
                </div>
                {miulImport && miulImport.results.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={String(miulSelectedIndex)}
                      onChange={(event) => setMiulSelectedIndex(Number(event.target.value))}
                      className="h-9 min-w-[280px] rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      {miulImport.results.map((row, idx) => (
                        <option key={`${row.row_index}-${row.maptis_code}-${idx}`} value={idx}>
                          Row {row.row_index} | {row.maptis_code} | {row.part_number || 'part N/A'} | {Object.entries(row.ratings).map(([k, v]) => `${k}=${v}`).join(', ')}
                        </option>
                      ))}
                    </select>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => applyImportedMiulRow(miulImport.results[miulSelectedIndex])}
                    >
                      Load Selected Row
                    </Button>
                  </div>
                ) : null}
              </div>

              {resolutionCandidates.length > 0 ? (
                <div className="rounded-md border border-amber-300 bg-amber-50 p-3">
                  <p className="text-sm font-medium text-amber-900">Material resolution candidates</p>
                  <p className="mt-1 text-xs text-amber-800">
                    Select a MAPTIS code below and re-run Classify.
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {resolutionCandidates.slice(0, 8).map((candidate, idx) => {
                      const code = String(
                        candidate.material_code ?? candidate.materialCode ?? candidate.code ?? '',
                      ).trim();
                      const name = String(
                        candidate.canonical_name ?? candidate.canonicalName ?? candidate.designation ?? '',
                      ).trim();
                      const label = code ? `${code}${name ? ` - ${name}` : ''}` : name || `candidate-${idx + 1}`;
                      return (
                        <Button
                          key={`${label}-${idx}`}
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            if (code) setMaptisCode(code);
                            if (name) setMaterialDesignation(name);
                            setResolutionCandidates([]);
                            setError(null);
                          }}
                        >
                          {label}
                        </Button>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="maptis-code">MAPTIS Code (optional)</Label>
                  <Input
                    id="maptis-code"
                    value={maptisCode}
                    onChange={(event) => setMaptisCode(event.target.value)}
                    placeholder="e.g., 10392"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="material-designation">Material Designation</Label>
                  <Input
                    id="material-designation"
                    value={materialDesignation}
                    onChange={(event) => setMaterialDesignation(event.target.value)}
                    placeholder="e.g., A286 CRES"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="material-class">Material Class</Label>
                  <select
                    id="material-class"
                    value={materialClass}
                    onChange={(event) => setMaterialClass(event.target.value as MaterialClass)}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="metal">metal</option>
                    <option value="nonmetallic">nonmetallic</option>
                  </select>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="media">Media</Label>
                  <Input
                    id="media"
                    value={media}
                    onChange={(event) => setMedia(event.target.value)}
                    placeholder="e.g., GH2"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="environment">Environment</Label>
                  <select
                    id="environment"
                    value={environment}
                    onChange={(event) => setEnvironment(event.target.value as 'habitable' | 'non-habitable')}
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="non-habitable">non-habitable</option>
                    <option value="habitable">habitable</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="o2-percent">O2 Percent</Label>
                  <Input
                    id="o2-percent"
                    type="number"
                    value={o2Percent}
                    onChange={(event) => setO2Percent(event.target.value)}
                    placeholder="optional"
                  />
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="project">Project</Label>
                  <Input id="project" value={project} onChange={(event) => setProject(event.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="system">System</Label>
                  <Input id="system" value={system} onChange={(event) => setSystem(event.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="pressure">Pressure</Label>
                  <Input id="pressure" value={pressure} onChange={(event) => setPressure(event.target.value)} />
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="temperature">Temperature</Label>
                  <Input
                    id="temperature"
                    value={temperature}
                    onChange={(event) => setTemperature(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="part-numbers">Part Numbers (comma-separated)</Label>
                  <Input
                    id="part-numbers"
                    value={partNumbers}
                    onChange={(event) => setPartNumbers(event.target.value)}
                    placeholder="MER07581-001, MER07581-002"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input
                  id="batch-verified"
                  type="checkbox"
                  checked={batchVerified}
                  onChange={(event) => setBatchVerified(event.target.checked)}
                  className="h-4 w-4 rounded border"
                />
                <Label htmlFor="batch-verified">Batch verified</Label>
              </div>

              <Button onClick={handleStep1Next} disabled={!hasMaterialIdentifier || !media.trim()}>
                Next: Enter Ratings
                <ChevronRight className="ml-2 h-4 w-4" />
              </Button>
            </CardContent>
          </>
        ) : (
          <CardContent className="flex items-center justify-between pt-6">
            <p className="text-sm">
              {materialDesignation || '[TBD]'} (MAPTIS {maptisCode || '[TBD]'}) in {media || '[TBD]'} - {environment}
            </p>
            <Button variant="outline" size="sm" onClick={handleEditStep1}>
              Edit
            </Button>
          </CardContent>
        )}
      </Card>

      {step >= 2 ? (
        <Card className={step === 2 ? '' : 'opacity-75'}>
          {step === 2 ? (
            <>
              <CardHeader>
                <CardTitle>Step 2: Why is MAPTIS flagging?</CardTitle>
                <CardDescription>Enter the MAPTIS ratings. Each rating is decoded as you type.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
                  {ISSUE_COLUMNS.map((column) => {
                    const value = ratings[column].trim().toUpperCase();
                    const hint = RATING_HINTS[column][value];
                    return (
                      <div key={column} className="space-y-2">
                        <Label htmlFor={`rating-${column}`}>{column}</Label>
                        <Input
                          id={`rating-${column}`}
                          value={ratings[column]}
                          onChange={(event) => setRating(column, event.target.value)}
                          placeholder="A/U/C..."
                          maxLength={1}
                        />
                        {value ? (
                          hint ? (
                            <p className="text-xs text-muted-foreground">{hint}</p>
                          ) : (
                            <p className="text-xs text-red-600">Unknown rating '{value}' for {column}</p>
                          )
                        ) : null}
                      </div>
                    );
                  })}
                </div>

                <Button onClick={handleClassify} disabled={loading}>
                  {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Classify
                  <ChevronRight className="ml-2 h-4 w-4" />
                </Button>
              </CardContent>
            </>
          ) : (
            <CardContent className="flex items-center justify-between gap-3 pt-6">
              <div className="flex flex-wrap gap-2">
                {nonEmptyRatings.length > 0
                  ? nonEmptyRatings.map((entry) => (
                      <Badge key={entry} variant="outline">
                        {entry}
                      </Badge>
                    ))
                  : (
                    <span className="text-sm text-muted-foreground">No ratings entered.</span>
                  )}
              </div>
              <Button variant="outline" size="sm" onClick={handleEditStep2}>
                Edit
              </Button>
            </CardContent>
          )}
        </Card>
      ) : null}

      {step >= 3 && pipelineResult ? (
        <Card className={step === 3 ? '' : 'opacity-75'}>
          {step === 3 ? (
            <>
              <CardHeader>
                <CardTitle>Step 3: Is the flag even correct?</CardTitle>
                <CardDescription>Material-class gate and hazard check for each flag.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">Flags: {pipelineResult.total_flags}</Badge>
                  <Badge variant="outline">Automatable: {pipelineResult.automatable_count}</Badge>
                  <Badge variant="outline">Human Required: {pipelineResult.human_required_count}</Badge>
                  <Badge variant="outline">No MUA Needed: {pipelineResult.no_mua_needed_count}</Badge>
                </div>

                {pipelineResult.classifications.map((classification, index) => {
                  const borderClass = classification.mua_type === 'STANDARD'
                    ? 'border-l-green-500'
                    : classification.automatable
                      ? 'border-l-amber-500'
                      : 'border-l-red-500';

                  return (
                    <div key={`${classification.issue_key}-${classification.rating}-${index}`} className={`rounded-md border border-l-4 p-3 ${borderClass}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge>{classification.issue_key}</Badge>
                        <Badge variant="outline">{classification.rating || 'blank'}</Badge>
                        <Badge variant="outline">{classification.mua_type}</Badge>
                        {classification.mua_type === 'STANDARD' ? (
                          <Badge className="bg-green-700">
                            <CheckCircle2 className="mr-1 h-3 w-3" />
                            No MUA
                          </Badge>
                        ) : null}
                      </div>

                      <p className="mt-2 text-sm text-muted-foreground">{classification.classification_reason}</p>

                      <div className="mt-3 space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-muted-foreground">Confidence</span>
                          <span>{getConfidencePct(classification.confidence)}%</span>
                        </div>
                        <div className="h-2 w-full rounded bg-muted">
                          <div
                            className="h-2 rounded bg-slate-700"
                            style={{ width: `${getConfidencePct(classification.confidence)}%` }}
                          />
                        </div>
                      </div>

                      {classification.precedent ? (
                        <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-2">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <Badge variant="outline">
                              {classification.precedent.approved_count}/{classification.precedent.total_count} approved precedent
                            </Badge>
                            {classification.evidence_bundle?.exemplars && classification.evidence_bundle.exemplars.length > 0 ? (
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                onClick={() =>
                                  setPrecedentExpanded((prev) => ({
                                    ...prev,
                                    [classification.issue_key]: !prev[classification.issue_key],
                                  }))
                                }
                              >
                                {precedentExpanded[classification.issue_key] ? 'Hide citations' : 'Show top citations'}
                              </Button>
                            ) : null}
                          </div>
                          {precedentExpanded[classification.issue_key] ? (
                            <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                              {(classification.evidence_bundle?.exemplars || []).slice(0, 3).map((exemplar) => (
                                <div key={`${classification.issue_key}-${exemplar.mua_number}`} className="rounded border bg-white px-2 py-1">
                                  {exemplar.mua_number} - {exemplar.material_name || 'material N/A'} ({exemplar.media_category || 'media N/A'})
                                </div>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      ) : null}

                      {!classification.screening_applicable ? (
                        <p className="mt-1 text-xs text-green-700">{classification.screening_reason}</p>
                      ) : null}

                      {classification.hazard_applies !== null ? (
                        <p className="mt-1 text-xs">Hazard present in {media}: {classification.hazard_applies ? 'Yes' : 'No'}</p>
                      ) : null}

                      {classification.synthesis?.suggested_elements && classification.synthesis.suggested_elements.length > 0 ? (
                        <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-2">
                          <p className="text-xs font-medium text-amber-900">Suggested rationale elements (engineer review)</p>
                          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-amber-900">
                            {classification.synthesis.suggested_elements.slice(0, 5).map((item, idx) => (
                              <li key={`${classification.issue_key}-suggestion-${idx}`}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </div>
                  );
                })}

                {automatableCount > 0 ? (
                  <Button onClick={handleStep3Next}>
                    Next: Review Rationale
                    <ChevronRight className="ml-2 h-4 w-4" />
                  </Button>
                ) : humanRequiredCount > 0 ? (
                  <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
                    <AlertTriangle className="mr-2 inline h-4 w-4" />
                    All flags require engineering judgment. No automatable MUAs.
                  </div>
                ) : null}
              </CardContent>
            </>
          ) : (
            <CardContent className="flex items-center justify-between pt-6">
              <p className="text-sm">
                {pipelineResult.automatable_count} automatable, {pipelineResult.human_required_count} need engineer
              </p>
              <Badge variant="outline">Step 3 complete</Badge>
            </CardContent>
          )}
        </Card>
      ) : null}

      {step >= 4 && pipelineResult ? (
        <Card className={step === 4 ? '' : 'opacity-75'}>
          {step === 4 ? (
            <>
              <CardHeader>
                <CardTitle>Step 4: Why should there be no flag?</CardTitle>
                <CardDescription>Review and edit generated rationale before producing the MUA document.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {pipelineResult.forms.map((form, index) => (
                  <div key={`${form.issue}-${index}`} className="rounded-md border p-3">
                    {(() => {
                      const classification = pipelineResult.classifications.find((item) => item.issue_key === form.issue);
                      const selectedAction = formActions[form.issue] || 'approve';
                      const claims = classification?.synthesis?.claims || [];
                      const evidenceHash = classification?.evidence_bundle?.evidence_hash || '';
                      return (
                        <>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{form.issue}</Badge>
                      <Badge variant="outline">{form.rating}</Badge>
                      <Badge variant="outline">Category {form.category || 'N/A'}</Badge>
                      <Badge variant="outline">{classification?.mua_type || 'N/A'}</Badge>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant={selectedAction === 'approve' ? 'default' : 'outline'}
                        onClick={() => setFormActions((prev) => ({ ...prev, [form.issue]: 'approve' }))}
                      >
                        Approve
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant={selectedAction === 'edit' ? 'default' : 'outline'}
                        onClick={() => setFormActions((prev) => ({ ...prev, [form.issue]: 'edit' }))}
                      >
                        Edit
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant={selectedAction === 'reject' ? 'destructive' : 'outline'}
                        onClick={() => setFormActions((prev) => ({ ...prev, [form.issue]: 'reject' }))}
                      >
                        Reject
                      </Button>
                    </div>

                    <div className="mt-3 space-y-2">
                      <Label>Rationale</Label>
                      <textarea
                        value={editedRationales[form.issue] ?? ''}
                        rows={6}
                        className="w-full rounded-md border p-2 text-sm font-mono"
                        onChange={(event) =>
                          {
                            setEditedRationales((prev) => ({
                              ...prev,
                              [form.issue]: event.target.value,
                            }));
                            setFormActions((prev) => ({ ...prev, [form.issue]: 'edit' }));
                          }
                        }
                      />
                    </div>

                    {claims.length > 0 ? (
                      <div className="mt-3 space-y-2">
                        <Label>Claim Sources</Label>
                        <div className="space-y-2">
                          {claims.map((claim, claimIdx) => {
                            const sourceType = (claim.source_type || '').toLowerCase();
                            const sourceClass = sourceType === 'precedent'
                              ? 'border-blue-300 bg-blue-50'
                              : sourceType === 'template'
                                ? 'border-slate-300 bg-slate-50'
                                : 'border-purple-300 bg-purple-50';
                            return (
                              <div key={`${form.issue}-claim-${claimIdx}`} className={`rounded-md border p-2 text-xs ${sourceClass}`}>
                                <div className="font-medium">
                                  {claim.source_type} - {claim.source_mua}
                                </div>
                                <div className="mt-1">{claim.text}</div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : null}

                    {evidenceHash ? (
                      <p className="mt-2 text-[11px] text-muted-foreground">Evidence hash: {evidenceHash}</p>
                    ) : null}

                    <div className="mt-3 space-y-2">
                      <Label>Disposition</Label>
                      <textarea
                        value={editedDispositions[form.issue] ?? ''}
                        rows={3}
                        className="w-full rounded-md border p-2 text-sm"
                        onChange={(event) =>
                          {
                            setEditedDispositions((prev) => ({
                              ...prev,
                              [form.issue]: event.target.value,
                            }));
                            setFormActions((prev) => ({ ...prev, [form.issue]: 'edit' }));
                          }
                        }
                      />
                    </div>
                        </>
                      );
                    })()}
                  </div>
                ))}

                {pipelineResult.classifications
                  .filter((classification) => !classification.automatable && classification.mua_type !== 'STANDARD')
                  .map((classification, index) => (
                    <div key={`${classification.issue_key}-${index}`} className="rounded-md border border-l-4 border-l-red-500 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge>{classification.issue_key}</Badge>
                        <Badge variant="destructive">Needs Engineer</Badge>
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">{classification.classification_reason}</p>
                      {classification.synthesis?.suggested_elements && classification.synthesis.suggested_elements.length > 0 ? (
                        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-red-900">
                          {classification.synthesis.suggested_elements.slice(0, 5).map((item, idx) => (
                            <li key={`${classification.issue_key}-step4-suggested-${idx}`}>{item}</li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ))}

                <Button onClick={handleStep4Next} disabled={pipelineResult.forms.length === 0 || finalizing}>
                  {finalizing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Generate MUA Documents
                  <ChevronRight className="ml-2 h-4 w-4" />
                </Button>
                {sessionId ? (
                  <p className="text-xs text-muted-foreground">
                    Session: {sessionId}
                    {draftSavedAt ? ` | Draft saved: ${new Date(draftSavedAt).toLocaleString()}` : ''}
                  </p>
                ) : null}
              </CardContent>
            </>
          ) : (
            <CardContent className="flex items-center justify-between pt-6">
              <p className="text-sm">{pipelineResult.forms.length} rationale draft(s) reviewed.</p>
              <Badge variant="outline">Step 4 complete</Badge>
            </CardContent>
          )}
        </Card>
      ) : null}

      {step === 5 && pipelineResult ? (
        <Card>
          <CardHeader>
            <CardTitle>Step 5: Download MUA</CardTitle>
            <CardDescription>Generate and download Form 551 .docx for each automatable flag.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {pipelineResult.forms.map((form, index) => {
              const classification = pipelineResult.classifications.find((item) => item.issue_key === form.issue);
              const rationalePreview = (editedRationales[form.issue] || form.rationale || '').slice(0, 100);
              const key = form.issue;
              return (
                <div key={`${form.issue}-${index}`} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{form.issue}={form.rating}</Badge>
                    <Badge variant="outline">Category {form.category || 'N/A'}</Badge>
                    <Badge variant="outline">{classification?.mua_type || 'N/A'}</Badge>
                  </div>

                  <p className="mt-2 text-sm text-muted-foreground">
                    {rationalePreview}{rationalePreview.length === 100 ? '...' : ''}
                  </p>

                  <Button className="mt-3" onClick={() => handleDownload(form)} disabled={downloading[key]}>
                    {downloading[key] ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
                    Download MUA_{form.issue}_{pipelineResult.maptis_code || maptisCode || 'resolved'}.docx
                  </Button>
                </div>
              );
            })}

            {pipelineResult.classifications
              .filter((classification) => !classification.automatable && classification.mua_type !== 'STANDARD')
              .map((classification, index) => (
                <div key={`${classification.issue_key}-human-${index}`} className="rounded-md border border-l-4 border-l-red-500 p-3">
                  <div className="flex items-center gap-2">
                    <Badge>{classification.issue_key}</Badge>
                    <Badge variant="destructive">Needs Engineer</Badge>
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">{classification.classification_reason}</p>
                </div>
              ))}

            {pipelineResult.forms.length === 0 ? (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
                <AlertTriangle className="mr-2 inline h-4 w-4" />
                No automatable MUAs are available for download.
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {error ? (
        <Card className="border-red-300">
          <CardContent className="pt-6 text-sm text-red-700">{error}</CardContent>
        </Card>
      ) : null}

      {step >= 3 && partNumbersList.length > 0 ? (
        <Card className="opacity-75">
          <CardHeader>
            <CardTitle className="text-sm">Part Numbers</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2 pt-0">
            {partNumbersList.map((part) => (
              <Badge key={part} variant="outline">{part}</Badge>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
