import { useDeferredValue, useEffect, useState, type FormEvent } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, ShieldAlert, ShieldCheck, ShieldX } from 'lucide-react';

import { PageHeader } from '@/components/PageHeader';
import { ModuleChatButton } from '@/components/mira/ModuleChatButton';
import { StatusBadge } from '@/components/StatusBadge';
import {
  GuidanceContextIndicator,
  GuidanceField,
  GuidanceInlineHelp,
  GuidanceModeSelector,
  GuidanceProvider,
} from '@/components/guidance';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  fractureClassify,
  fractureGetAuthority,
  fractureSearchMaterials,
  type FractureAssessmentResponse,
  type FractureAuthorityManifest,
  type FractureMaterialSearchResult,
} from '@/lib/api';
import {
  authorityRegistry,
  createFractureContext,
  fractureGuidancePack,
} from '@/lib/guidance/fracture-pack';
import type { GuidanceModeName } from '@/lib/guidance/types';
import {
  buildWorkflowContext,
  buildChatContextSummary,
  createModuleChatLaunchState,
  registerRouteModuleChatState,
  resolveGuidanceFieldFromTarget,
} from '@/lib/mira-chat-context';

const MISSION_OPTIONS = [
  { value: 'HUMAN_RATED', label: 'Human-Rated' },
  { value: 'CARGO', label: 'Cargo' },
  { value: 'EXPERIMENTAL', label: 'Experimental' },
  { value: 'GSE', label: 'Ground Support Equipment' },
  { value: 'GROUND_SUPPORT', label: 'Ground Support' },
] as const;

const HAZARD_OPTIONS = [
  { value: 'CATASTROPHIC', label: 'Catastrophic' },
  { value: 'CRITICAL', label: 'Critical' },
  { value: 'MARGINAL', label: 'Marginal' },
  { value: 'NEGLIGIBLE', label: 'Negligible' },
  { value: 'UNKNOWN', label: 'Unknown' },
] as const;

const LOAD_PATH_OPTIONS = [
  { value: 'SINGLE', label: 'Single Load Path' },
  { value: 'REDUNDANT', label: 'Redundant Load Path' },
  { value: 'UNKNOWN', label: 'Unknown' },
] as const;

const LIFECYCLE_OPTIONS = [
  { value: 'NEW_BUILD', label: 'New Build' },
  { value: 'REFLIGHT', label: 'Reflight' },
] as const;

const STRUCTURAL_ROLE_OPTIONS = [
  { value: 'PRIMARY', label: 'Primary' },
  { value: 'SECONDARY', label: 'Secondary' },
  { value: 'NON_STRUCTURAL', label: 'Non-Structural' },
] as const;

const MATERIAL_SYSTEM_OPTIONS = [
  { value: 'METALLIC', label: 'Metallic' },
  { value: 'COMPOSITE', label: 'Composite' },
  { value: 'BONDED', label: 'Bonded' },
  { value: 'CERAMIC', label: 'Ceramic' },
  { value: 'OTHER', label: 'Other' },
] as const;

const HARDWARE_TYPE_OPTIONS = [
  { value: 'GENERAL', label: 'General' },
  { value: 'FASTENER', label: 'Fastener' },
  { value: 'SHATTERABLE', label: 'Shatterable' },
  { value: 'ROTATING_HARDWARE', label: 'Rotating Hardware' },
  { value: 'SEALED_CONTAINER', label: 'Sealed Container' },
  { value: 'TOOLS_TETHERS', label: 'Tools / Tethers' },
  { value: 'BATTERY', label: 'Battery' },
  { value: 'PRESSURE_VESSEL', label: 'Pressure Vessel' },
  { value: 'COPV', label: 'COPV' },
  { value: 'PRESSURIZED_COMPONENT', label: 'Pressurized Component' },
  { value: 'HABITABLE_STRUCTURE', label: 'Habitable Structure' },
  { value: 'PRESSURIZED_STRUCTURE', label: 'Pressurized Structure' },
] as const;

const QUALIFICATION_OPTIONS = [
  { value: 'unknown', label: 'Unknown' },
  { value: 'qualified', label: 'Qualified to NASA-STD-6016' },
  { value: 'not-qualified', label: 'Not qualified to NASA-STD-6016' },
] as const;

function MaterialSuggestions({
  results,
  onPick,
}: {
  results: FractureMaterialSearchResult[];
  onPick: (value: string) => void;
}) {
  if (!results.length) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {results.slice(0, 6).map((item) => (
        <button
          key={item.canonical_name}
          type="button"
          onClick={() => onPick(item.canonical_name)}
          className="rounded-full border border-border bg-muted/50 px-3 py-1 text-xs text-foreground transition-colors hover:bg-muted"
        >
          {item.canonical_name}
        </button>
      ))}
    </div>
  );
}

function classificationBadge(classification: string): string {
  switch (classification) {
    case 'EXEMPT':
      return 'OK';
    case 'FC':
      return 'CAUTION';
    case 'INDETERMINATE':
      return 'CLARIFY';
    default:
      return 'UNKNOWN';
  }
}

function classificationIcon(classification: string) {
  if (classification === 'EXEMPT') return <ShieldCheck className="h-5 w-5 text-emerald-600" />;
  if (classification === 'FC') return <ShieldAlert className="h-5 w-5 text-amber-600" />;
  if (classification === 'INDETERMINATE') return <AlertTriangle className="h-5 w-5 text-rose-600" />;
  return <CheckCircle2 className="h-5 w-5 text-sky-600" />;
}

export default function FractureControl() {
  const [guidanceMode, setGuidanceMode] = useState<GuidanceModeName>('live');
  const [activeChatField, setActiveChatField] = useState<{ fieldKey: string; label: string } | null>(null);
  const [partName, setPartName] = useState('Primary Bracket');
  const [materialName, setMaterialName] = useState('Al 6061-T6');
  const [missionClass, setMissionClass] = useState('HUMAN_RATED');
  const [hazardConsequence, setHazardConsequence] = useState('CATASTROPHIC');
  const [loadPathType, setLoadPathType] = useState('SINGLE');
  const [lifecyclePhase, setLifecyclePhase] = useState('NEW_BUILD');
  const [structuralRole, setStructuralRole] = useState('PRIMARY');
  const [materialSystem, setMaterialSystem] = useState('METALLIC');
  const [specificHardwareType, setSpecificHardwareType] = useState('GENERAL');
  const [pressureBoundary, setPressureBoundary] = useState(false);
  const [optionalApproachRequested, setOptionalApproachRequested] = useState(false);
  const [proofTestUsed, setProofTestUsed] = useState(false);
  const [processControlsUsed, setProcessControlsUsed] = useState(false);
  const [detectedFlawAcceptedForFlight, setDetectedFlawAcceptedForFlight] = useState(false);
  const [corrosionIccpRecommended, setCorrosionIccpRecommended] = useState(false);
  const [lowRiskCandidate, setLowRiskCandidate] = useState(false);
  const [additiveManufactured, setAdditiveManufactured] = useState(false);
  const [chlorideExposure, setChlorideExposure] = useState(false);
  const [sustainedLoadExpected, setSustainedLoadExpected] = useState(false);
  const [approvedSourceDataAttached, setApprovedSourceDataAttached] = useState(false);
  const [muaPresent, setMuaPresent] = useState(false);
  const [qualificationState, setQualificationState] = useState('unknown');
  const [kicFtyRatio, setKicFtyRatio] = useState('');
  const [ftuKsi, setFtuKsi] = useState('');
  const [shortTransverseDimension, setShortTransverseDimension] = useState('');
  const [authority, setAuthority] = useState<FractureAuthorityManifest | null>(null);
  const [searchResults, setSearchResults] = useState<FractureMaterialSearchResult[]>([]);
  const [result, setResult] = useState<FractureAssessmentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const guidanceContext = createFractureContext({
    user_mode: guidanceMode,
    service_environment: lifecyclePhase,
    material_class: materialSystem === 'METALLIC' ? 'metallic' : materialSystem === 'COMPOSITE' ? 'composite' : undefined,
  });

  const deferredMaterialName = useDeferredValue(materialName);

  useEffect(() => {
    let cancelled = false;

    async function loadAuthority() {
      setBootLoading(true);
      try {
        const manifest = await fractureGetAuthority();
        if (!cancelled) setAuthority(manifest);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load fracture authority pack.');
        }
      } finally {
        if (!cancelled) setBootLoading(false);
      }
    }

    void loadAuthority();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function search() {
      const query = deferredMaterialName.trim();
      if (query.length < 2) {
        setSearchResults([]);
        return;
      }
      try {
        const matches = await fractureSearchMaterials(query);
        if (!cancelled) setSearchResults(matches);
      } catch {
        if (!cancelled) setSearchResults([]);
      }
    }

    void search();

    return () => {
      cancelled = true;
    };
  }, [deferredMaterialName]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const response = await fractureClassify({
        part_name: partName,
        mission_class: missionClass as 'HUMAN_RATED' | 'CARGO' | 'EXPERIMENTAL' | 'GSE' | 'GROUND_SUPPORT',
        hazard_consequence: hazardConsequence as 'CATASTROPHIC' | 'CRITICAL' | 'MARGINAL' | 'NEGLIGIBLE' | 'UNKNOWN',
        load_path_type: loadPathType as 'SINGLE' | 'REDUNDANT' | 'UNKNOWN',
        pressure_boundary: pressureBoundary,
        lifecycle_phase: lifecyclePhase as 'NEW_BUILD' | 'REFLIGHT',
        structural_role: structuralRole as 'PRIMARY' | 'SECONDARY' | 'NON_STRUCTURAL',
        material_system: materialSystem as 'METALLIC' | 'COMPOSITE' | 'BONDED' | 'CERAMIC' | 'OTHER',
        specific_hardware_type: specificHardwareType as
          | 'GENERAL'
          | 'FASTENER'
          | 'SHATTERABLE'
          | 'ROTATING_HARDWARE'
          | 'SEALED_CONTAINER'
          | 'TOOLS_TETHERS'
          | 'BATTERY'
          | 'PRESSURE_VESSEL'
          | 'COPV'
          | 'PRESSURIZED_COMPONENT'
          | 'HABITABLE_STRUCTURE'
          | 'PRESSURIZED_STRUCTURE',
        material_name: materialName.trim() || null,
        optional_approach_requested: optionalApproachRequested,
        proof_test_used: proofTestUsed,
        process_controls_used: processControlsUsed,
        detected_flaw_accepted_for_flight: detectedFlawAcceptedForFlight,
        corrosion_iccp_recommended: corrosionIccpRecommended,
        material_context: {
          low_risk_candidate: lowRiskCandidate,
          additive_manufactured: additiveManufactured,
          chloride_exposure: chlorideExposure,
          sustained_load_expected: sustainedLoadExpected,
          approved_source_data_attached: approvedSourceDataAttached,
          mua_present: muaPresent,
          nasa_std_6016_qualified:
            qualificationState === 'unknown'
              ? null
              : qualificationState === 'qualified',
          kic_fty_ratio: kicFtyRatio.trim() ? Number(kicFtyRatio) : null,
          ftu_ksi: ftuKsi.trim() ? Number(ftuKsi) : null,
          short_transverse_dimension_in: shortTransverseDimension.trim()
            ? Number(shortTransverseDimension)
            : null,
        },
      });
      setResult(response);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Fracture assessment failed.');
    } finally {
      setLoading(false);
    }
  }

  const checkboxes = [
    { checked: pressureBoundary, setChecked: setPressureBoundary, label: 'Pressure boundary', fieldId: 'pressure_boundary' },
    { checked: optionalApproachRequested, setChecked: setOptionalApproachRequested, label: 'Optional approach requested', fieldId: 'optional_approach_requested' },
    { checked: proofTestUsed, setChecked: setProofTestUsed, label: 'Proof test used', fieldId: 'proof_test_used' },
    { checked: processControlsUsed, setChecked: setProcessControlsUsed, label: 'Process controls used', fieldId: 'process_controls_used' },
    { checked: detectedFlawAcceptedForFlight, setChecked: setDetectedFlawAcceptedForFlight, label: 'Detected flaw accepted for flight', fieldId: 'detected_flaw_accepted_for_flight' },
    { checked: corrosionIccpRecommended, setChecked: setCorrosionIccpRecommended, label: 'Corrosion module recommends ICCP' },
    { checked: lowRiskCandidate, setChecked: setLowRiskCandidate, label: 'Evaluate metallic low-risk path', fieldId: 'low_risk_candidate' },
    { checked: additiveManufactured, setChecked: setAdditiveManufactured, label: 'Additively manufactured metallic part', fieldId: 'additive_manufactured' },
    { checked: chlorideExposure, setChecked: setChlorideExposure, label: 'Wet chloride / salt exposure expected', fieldId: 'chloride_exposure' },
    { checked: sustainedLoadExpected, setChecked: setSustainedLoadExpected, label: 'Sustained load expected', fieldId: 'sustained_load_expected' },
    { checked: approvedSourceDataAttached, setChecked: setApprovedSourceDataAttached, label: 'Approved source data attached', fieldId: 'approved_source_data_attached' },
    { checked: muaPresent, setChecked: setMuaPresent, label: 'MUA already present' },
  ];
  const fractureFieldStates = [
    { fieldKey: 'inputs.part_name', label: 'Part Name', status: partName.trim() ? 'complete' : 'incomplete', required: true },
    { fieldKey: 'inputs.material_name', label: 'Material', status: materialName.trim() ? 'complete' : 'incomplete', required: true },
    { fieldKey: 'inputs.mission_class', label: 'Mission Class', status: missionClass ? 'complete' : 'incomplete', required: true },
    { fieldKey: 'inputs.hazard_consequence', label: 'Hazard Consequence', status: hazardConsequence ? 'complete' : 'incomplete', required: true },
    { fieldKey: 'inputs.load_path_type', label: 'Load Path', status: loadPathType ? 'complete' : 'incomplete', required: true },
    { fieldKey: 'inputs.material_system', label: 'Material System', status: materialSystem ? 'complete' : 'incomplete', required: true },
    { fieldKey: 'inputs.specific_hardware_type', label: 'Specific Hardware Type', status: specificHardwareType ? 'complete' : 'incomplete', required: true },
  ] as const;
  const fractureBlockers = fractureFieldStates
    .filter((field) => field.status !== 'complete')
    .map((field) => field.label);
  const fractureWorkflowContext = buildWorkflowContext({
    currentStep: result ? 'review_classification' : fractureBlockers.length ? 'define_part_context' : 'ready_to_classify',
    activeField: activeChatField,
    fieldStates: fractureFieldStates.map((field) => ({ ...field })),
    nextSteps: fractureBlockers.length
      ? [`Complete ${fractureBlockers[0]}.`]
      : result
        ? ['Review the applicable requirements and material findings for the current classification.']
        : ['Run the classifier for the current part context.'],
    blockers: fractureBlockers,
  });
  const fractureChatLaunchState = createModuleChatLaunchState({
    scopeKey: 'fracture-control',
    moduleLabel: 'Fracture Control',
    moduleContext: {
      module: 'fracture',
      material: materialName.trim(),
      part_name: partName.trim(),
      mission_class: missionClass,
      chat_workflow: fractureWorkflowContext,
    },
    originPath: '/fracture-control',
    originTitle: 'Fracture Control',
    description: 'Ground the chat in the current part, mission class, and fracture-screen inputs.',
    contextSummary: buildChatContextSummary([
      { label: 'Part', value: partName.trim() },
      { label: 'Material', value: materialName.trim() },
      { label: 'Mission', value: missionClass.replaceAll('_', ' ') },
      { label: 'Lifecycle', value: lifecyclePhase.replaceAll('_', ' ') },
      { label: 'Hardware', value: specificHardwareType.replaceAll('_', ' ') },
    ]),
  });

  useEffect(() => {
    registerRouteModuleChatState('/fracture-control', fractureChatLaunchState);
  }, [activeChatField, lifecyclePhase, materialName, missionClass, partName, specificHardwareType]);

  return (
    <GuidanceProvider
      schema={fractureGuidancePack}
      context={guidanceContext}
      mode={guidanceMode}
      telemetryEnabled
      onModeChange={(newMode) => setGuidanceMode(newMode)}
      authorityRegistry={authorityRegistry}
    >
      <div
        className="space-y-8"
        onFocusCapture={(event) => {
          const field = resolveGuidanceFieldFromTarget(event.target);
          if (field) setActiveChatField(field);
        }}
      >
        <PageHeader
          title="Fracture Control"
          description="Deterministic NASA-STD-5019A classifier for fracture-control routing. Define the part context, review applicable FCRs, and surface Phase 1 material findings with citations."
          actions={<ModuleChatButton launchState={fractureChatLaunchState} />}
        />
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
          <GuidanceContextIndicator context={guidanceContext} />
          <GuidanceModeSelector
            currentMode={guidanceMode}
            context={guidanceContext}
            onModeChange={(newMode) => setGuidanceMode(newMode)}
          />
        </div>

      <Card className="border-border/70">
        <CardHeader>
          <CardTitle className="text-xl">Assessment Inputs</CardTitle>
          <CardDescription>
            This module classifies the part, maps applicable FCRs from verified authority JSON, and surfaces Phase 1 material findings without pretending to run a crack-growth solver.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-6" onSubmit={handleSubmit}>
            <div className="grid gap-4 md:grid-cols-2">
              <GuidanceField name="inputs.part_name" htmlFor="part-name" label="Part Name">
                <Input id="part-name" value={partName} onChange={(event) => setPartName(event.target.value)} className="mt-2" />
              </GuidanceField>
              <GuidanceField name="inputs.material_name" htmlFor="material-name" label="Material">
                <Input
                  id="material-name"
                  value={materialName}
                  onChange={(event) => setMaterialName(event.target.value)}
                  placeholder="Example: Ti-6Al-4V"
                  className="mt-2"
                />
                <MaterialSuggestions results={searchResults} onPick={setMaterialName} />
              </GuidanceField>
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <GuidanceField name="inputs.mission_class" label="Mission Class">
                <Select value={missionClass} onValueChange={setMissionClass}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{MISSION_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                </Select>
              </GuidanceField>
              <GuidanceField name="inputs.hazard_consequence" label="Hazard Consequence">
                <Select value={hazardConsequence} onValueChange={setHazardConsequence}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{HAZARD_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                </Select>
              </GuidanceField>
              <GuidanceField name="inputs.load_path_type" label="Load Path">
                <Select value={loadPathType} onValueChange={setLoadPathType}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{LOAD_PATH_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                </Select>
              </GuidanceField>
              <GuidanceField name="inputs.lifecycle_phase" label="Lifecycle Phase">
                <Select value={lifecyclePhase} onValueChange={setLifecyclePhase}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{LIFECYCLE_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                </Select>
              </GuidanceField>
              <GuidanceField name="inputs.structural_role" label="Structural Role">
                <Select value={structuralRole} onValueChange={setStructuralRole}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{STRUCTURAL_ROLE_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                </Select>
              </GuidanceField>
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <GuidanceField name="inputs.material_system" label="Material System">
                <Select value={materialSystem} onValueChange={setMaterialSystem}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{MATERIAL_SYSTEM_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                </Select>
              </GuidanceField>
              <GuidanceField name="inputs.specific_hardware_type" label="Specific Hardware Type">
                <Select value={specificHardwareType} onValueChange={setSpecificHardwareType}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{HARDWARE_TYPE_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                </Select>
              </GuidanceField>
              <GuidanceField name="inputs.nasa_std_6016_qualified" label="NASA-STD-6016 Qualification">
                <Select value={qualificationState} onValueChange={setQualificationState}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{QUALIFICATION_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                </Select>
              </GuidanceField>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <GuidanceField name="inputs.kic_fty_ratio" htmlFor="kic-fty" label="KIc/Fty ratio">
                <Input id="kic-fty" value={kicFtyRatio} onChange={(event) => setKicFtyRatio(event.target.value)} placeholder="Example: 0.41" className="mt-2" />
              </GuidanceField>
              <GuidanceField name="inputs.ftu_ksi" htmlFor="ftu-ksi" label="FTU (ksi)">
                <Input id="ftu-ksi" value={ftuKsi} onChange={(event) => setFtuKsi(event.target.value)} placeholder="Example: 190" className="mt-2" />
              </GuidanceField>
              <GuidanceField
                name="inputs.short_transverse_dimension_in"
                htmlFor="short-transverse"
                label="Short-Transverse Dimension (in)"
              >
                <Input id="short-transverse" value={shortTransverseDimension} onChange={(event) => setShortTransverseDimension(event.target.value)} placeholder="Example: 3.5" className="mt-2" />
              </GuidanceField>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {checkboxes.map((item) => (
                item.fieldId ? (
                  <GuidanceField
                    key={item.label}
                    name={`inputs.${item.fieldId}`}
                    label={item.label}
                    className="rounded-lg border border-dashed border-border px-4 py-3"
                  >
                    <div className="flex justify-end">
                      <Checkbox checked={item.checked} onCheckedChange={(checked) => item.setChecked(Boolean(checked))} />
                    </div>
                  </GuidanceField>
                ) : (
                  <label key={item.label} className="flex items-center gap-3 rounded-lg border border-dashed border-border px-4 py-3">
                    <Checkbox checked={item.checked} onCheckedChange={(checked) => item.setChecked(Boolean(checked))} />
                    <div className="text-sm font-medium">{item.label}</div>
                  </label>
                )
              ))}
            </div>

            <div className="flex items-center gap-3">
              <Button type="submit" disabled={loading || bootLoading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Run Fracture Screen
              </Button>
              {authority && (
                <p className="text-sm text-muted-foreground">
                  Verified authority pack: <span className="font-medium text-foreground">{authority.version}</span>
                </p>
              )}
            </div>
          </form>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-rose-200 bg-rose-50/60">
          <CardContent className="flex items-start gap-3 p-4 text-sm text-rose-900">
            <ShieldX className="mt-0.5 h-4 w-4" />
            <div>{error}</div>
          </CardContent>
        </Card>
      )}

      {result && (
        <div className="space-y-6">
          <Card className="overflow-hidden border-border/70">
            <div className="border-b bg-gradient-to-r from-slate-900 via-slate-800 to-slate-900 px-6 py-5 text-slate-50">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-xs uppercase tracking-[0.2em] text-slate-300">Assessment Result</div>
                  <div className="mt-2 flex items-center gap-3">
                    {classificationIcon(result.classification)}
                    <div className="text-2xl font-semibold">{result.classification}</div>
                  </div>
                  <div className="mt-2 text-sm text-slate-300">
                    Baseline path: <span className="font-medium text-slate-50">{result.baseline_key}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={classificationBadge(result.classification)} />
                  <GuidanceInlineHelp name={`classifications.${result.classification}`} />
                </div>
              </div>
            </div>
            <CardContent className="pt-6">
              <div className="grid gap-4 md:grid-cols-3">
                <div className="rounded-lg border p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Confidence</div>
                  <div className="mt-2 text-xl font-semibold">{result.confidence_state}</div>
                </div>
                <div className="rounded-lg border p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Applicable FCRs</div>
                  <div className="mt-2 text-xl font-semibold">{result.applicable_fcrs.join(', ') || 'None'}</div>
                </div>
                <div className="rounded-lg border p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Resolved Material</div>
                  <div className="mt-2 text-base font-semibold">{result.resolved_material?.canonical_name ?? 'No material resolved'}</div>
                </div>
              </div>
              <p className="mt-4 text-sm text-muted-foreground">{result.screening_basis}</p>
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="text-xl">Required Actions</CardTitle>
              <CardDescription>Deterministic action list from the applicable FCR path.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 lg:grid-cols-2">
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Actions</div>
                <ul className="mt-3 space-y-2 text-sm">
                  {result.required_actions.map((item) => <li key={item} className="rounded-lg border p-3">{item}</li>)}
                </ul>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Documents</div>
                <ul className="mt-3 space-y-2 text-sm">
                  {result.required_documents.map((item) => <li key={item} className="rounded-lg border p-3">{item}</li>)}
                </ul>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="text-xl">Applicable FCRs</CardTitle>
              <CardDescription>Source-backed requirements with section and page citations.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {result.requirements.map((requirement) => (
                <div key={requirement.fcr} className="rounded-xl border p-4">
                  <div className="flex items-center justify-between gap-3">
                    <Badge variant="secondary">FCR {requirement.fcr}</Badge>
                    <Badge variant="outline">{requirement.category}</Badge>
                  </div>
                  <div className="mt-3 text-lg font-semibold">{requirement.title}</div>
                  <div className="mt-1 text-sm text-muted-foreground">Section {requirement.section}</div>
                  <p className="mt-3 text-sm text-muted-foreground">{requirement.description}</p>
                  {requirement.notes && (
                    <p className="mt-3 text-sm">
                      <span className="font-medium">Implementation note:</span> {requirement.notes}
                    </p>
                  )}
                  <div className="mt-4 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
                    {requirement.citation.source_document} · pp. {requirement.citation.source_pages.join(', ')}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="text-xl">Material Findings</CardTitle>
              <CardDescription>Phase 1 findings stay explicit about what is source-backed and what data is still missing.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 lg:grid-cols-2">
              {result.material_findings.length ? result.material_findings.map((finding) => (
                <div key={finding.finding_id} className="rounded-xl border p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-lg font-semibold">{finding.title}</div>
                    <StatusBadge status={finding.status} />
                  </div>
                  <p className="mt-3 text-sm text-muted-foreground">{finding.detail}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {finding.governing_fcrs.map((fcr) => <Badge key={`${finding.finding_id}-${fcr}`} variant="secondary">FCR {fcr}</Badge>)}
                    {finding.source_clauses.map((clause) => <Badge key={`${finding.finding_id}-${clause}`} variant="outline">{clause}</Badge>)}
                  </div>
                  {finding.data_provided.length > 0 && (
                    <div className="mt-4 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
                      Data provided: {finding.data_provided.join(', ')}
                    </div>
                  )}
                </div>
              )) : (
                <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  No material findings were generated for the selected path.
                </div>
              )}
            </CardContent>
          </Card>

          {(result.warnings.length > 0 || result.unresolved_inputs.length > 0 || result.conservative_fallback) && (
            <Card className="border-border/70">
              <CardHeader>
                <CardTitle className="text-xl">Warnings and Unresolved Inputs</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {result.warnings.length > 0 && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Warnings</div>
                    <ul className="mt-3 space-y-2 text-sm">
                      {result.warnings.map((warning) => <li key={warning} className="rounded-lg border p-3">{warning}</li>)}
                    </ul>
                  </div>
                )}
                {result.unresolved_inputs.length > 0 && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Unresolved inputs</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {result.unresolved_inputs.map((item) => <Badge key={item} variant="outline">{item}</Badge>)}
                    </div>
                  </div>
                )}
                {result.conservative_fallback && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-4 text-sm text-amber-950">
                    Conservative fallback: {result.conservative_fallback}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="text-xl">Authority Pack</CardTitle>
              <CardDescription>Runtime authority files loaded by this module.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 lg:grid-cols-[280px_1fr]">
              <div className="rounded-lg border p-4">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Version</div>
                <div className="mt-2 text-3xl font-semibold">{authority?.version ?? result.source_manifest_version}</div>
                {authority && (
                  <div className="mt-4 space-y-2 text-sm text-muted-foreground">
                    <div>Total FCRs: <span className="font-medium text-foreground">{authority.total_fcrs}</span></div>
                    <div>Baselines: <span className="font-medium text-foreground">{authority.baseline_count}</span></div>
                    <div>Conditionals: <span className="font-medium text-foreground">{authority.conditional_extension_count}</span></div>
                    <div>Special rules: <span className="font-medium text-foreground">{authority.special_rule_count}</span></div>
                  </div>
                )}
              </div>
              <div className="space-y-3">
                {authority?.sources.map((source) => (
                  <div key={source.path} className="rounded-lg border p-4">
                    <div className="font-medium">{source.document}</div>
                    <div className="mt-1 text-xs text-muted-foreground break-all">{source.path}</div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
      </div>
    </GuidanceProvider>
  );
}
