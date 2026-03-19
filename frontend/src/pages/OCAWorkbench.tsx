import { useEffect, useState, type FormEvent } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  FileStack,
  Flame,
  Loader2,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
} from 'lucide-react';

import {
  GuidanceContextIndicator,
  GuidanceField,
  GuidanceModeSelector,
  GuidanceProvider,
} from '@/components/guidance';
import { MaterialCombobox } from '@/components/oca/MaterialCombobox';
import { OCAInlineHelp } from '@/components/oca/OCAInlineHelp';
import { PageHeader } from '@/components/PageHeader';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { authorityRegistry, createOcaContext, ocaGuidancePack } from '@/lib/guidance/oca-pack';
import type { GuidanceModeName } from '@/lib/guidance/types';
import {
  ocaAssessMechanisms,
  ocaCreateCase,
  ocaExport,
  ocaGetAuthority,
  ocaGetEvidence,
  ocaGetLineage,
  ocaGetRequirements,
  ocaPrecheck,
  ocaRunDecision,
  type OCAApplicabilityClass,
  type OCAAuthorityManifest,
  type OCACreateCaseRequest,
  type OCACreateCaseResponse,
  type OCADecisionPacket,
  type OCAEvidenceResponse,
  type OCAExportArtifact,
  type OCALineageResponse,
  type OCAMechanismAssessment,
  type OCAMissionPhase,
  type OCAOxidizerType,
  type OCAPhase,
  type OCAFlowRegime,
  type OCARequirementsResponse,
} from '@/lib/api';
import {
  getDispositionGuidance,
  getInputGuidance,
  getMechanismGuidance,
  getMprGuidance,
} from '@/lib/oca-guidance';


const OXIDIZER_OPTIONS: Array<{ value: OCAOxidizerType; label: string }> = [
  { value: 'gox', label: 'GOX' },
  { value: 'lox', label: 'LOX' },
  { value: 'enriched_air', label: 'Enriched Air' },
  { value: 'compressed_air', label: 'Compressed Air' },
];

const PHASE_OPTIONS: Array<{ value: OCAPhase; label: string }> = [
  { value: 'gas', label: 'Gas' },
  { value: 'liquid', label: 'Liquid' },
];

const FLOW_OPTIONS: Array<{ value: OCAFlowRegime; label: string }> = [
  { value: 'static', label: 'Static' },
  { value: 'laminar', label: 'Laminar' },
  { value: 'turbulent', label: 'Turbulent' },
];

const MISSION_OPTIONS: Array<{ value: OCAMissionPhase; label: string }> = [
  { value: 'ground_test', label: 'Ground Test' },
  { value: 'ascent', label: 'Ascent' },
  { value: 'on_orbit', label: 'On-Orbit' },
  { value: 'servicing', label: 'Servicing' },
];

const COMPONENT_OPTIONS = [
  'valve',
  'regulator',
  'line',
  'vessel',
  'seal',
  'filter',
  'sensor',
  'fitting',
  'flex_hose',
  'other',
] as const;

const GEOMETRY_OPTIONS = [
  'bulk',
  'thin_wall',
  'mesh',
  'porous',
  'sintered',
  'seal',
  'other',
] as const;

const EVIDENCE_ORDER: OCAApplicabilityClass[] = ['DIRECT', 'PARTIAL', 'WEAK_ANALOG', 'NOT_APPLICABLE'];

const DISPOSITION_META: Record<string, { label: string; className: string }> = {
  compatible_as_configured: { label: 'Compatible As Configured', className: 'bg-emerald-600 text-white' },
  compatible_with_controls: { label: 'Compatible With Controls', className: 'bg-amber-500 text-slate-950' },
  requires_mua: { label: 'Requires MUA', className: 'bg-orange-600 text-white' },
  requires_acceptance_test: { label: 'Requires Acceptance Test', className: 'bg-orange-700 text-white' },
  requires_supplemental_testing: { label: 'Requires Supplemental Testing', className: 'bg-rose-700 text-white' },
  insufficient_evidence: { label: 'Insufficient Evidence', className: 'bg-slate-700 text-white' },
  prohibited: { label: 'Prohibited', className: 'bg-rose-800 text-white' },
};

function tierClass(tier: string): string {
  if (tier === 'tier_a') return 'bg-rose-700 text-white';
  if (tier === 'tier_b') return 'bg-sky-700 text-white';
  if (tier === 'tier_c') return 'bg-emerald-700 text-white';
  return 'bg-amber-600 text-slate-950';
}

function statusClass(status: string): string {
  if (status === 'prohibited') return 'bg-rose-700 text-white';
  if (status === 'action_required') return 'bg-amber-500 text-slate-950';
  if (status === 'satisfied') return 'bg-emerald-600 text-white';
  return 'bg-slate-200 text-slate-700';
}

function applicabilityClassName(applicability: OCAApplicabilityClass): string {
  if (applicability === 'DIRECT') return 'bg-emerald-50 border-emerald-200';
  if (applicability === 'PARTIAL') return 'bg-sky-50 border-sky-200';
  if (applicability === 'WEAK_ANALOG') return 'bg-amber-50 border-amber-200';
  return 'bg-slate-50 border-slate-200';
}

function mechanismIcon(status: string) {
  if (status === 'CREDIBLE') return <ShieldAlert className="h-4 w-4 text-amber-600" />;
  if (status === 'INDETERMINATE') return <AlertTriangle className="h-4 w-4 text-rose-600" />;
  return <ShieldCheck className="h-4 w-4 text-emerald-600" />;
}

function calculateAdiabaticTf(tiK: number, piPsia: number, pfPsia: number, gamma: number = 1.4) {
  if (!piPsia || !pfPsia || piPsia <= 0 || pfPsia <= 0) return null;
  const tfK = tiK * Math.pow(pfPsia / piPsia, (gamma - 1) / gamma);
  const tfC = tfK - 273.15;
  const tfF = tfC * (9 / 5) + 32;
  return { tfK, tfC, tfF };
}

function downloadArtifact(artifact: OCAExportArtifact) {
  const blob = new Blob([artifact.generated_text], { type: artifact.content_type || 'text/plain' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = artifact.filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function workbenchHelp(fieldId: string) {
  return getInputGuidance(`workbench.${fieldId}`);
}

type GuidanceValidationState = 'valid' | 'invalid' | 'warning' | 'pending';

function requiredTextState(value: string): GuidanceValidationState | undefined {
  return value.trim() ? undefined : 'invalid';
}

function numericInputState(value: string): GuidanceValidationState | undefined {
  if (!value.trim()) return 'invalid';
  return Number.isFinite(Number(value)) ? undefined : 'invalid';
}

function dispositionPlainEnglish(disposition: string, decision: OCADecisionPacket): string {
  const materialNames = decision.mua_seed?.materials?.join(', ') || 'this material';
  switch (disposition) {
    case 'compatible_as_configured':
      return `Good news — ${materialNames} passes the oxygen compatibility screening for your service conditions. No additional testing or documentation is required. Your M&P engineer can sign off on this configuration.`;
    case 'compatible_with_controls':
      return `${materialNames} can be used, but some ignition mechanisms need engineering controls before sign-off. Review the "Next Actions" below — these are specific steps your M&P engineer needs to address, such as particle cleanliness or flow velocity limits.`;
    case 'requires_mua':
      return `${materialNames} needs a formal Material Usage Agreement (MUA) before your project can proceed. This means your M&P engineer needs to write a short document explaining why this material is acceptable for your specific application. The export pack below gives them a head start.`;
    case 'requires_acceptance_test':
      return 'Your hardware exceeds the 265 psia threshold for high-pressure GOX/enriched air. Before acceptance, the actual hardware must pass a pressurization acceptance test (10 cycles, ambient to max design pressure within 100 ms). Talk to your test lab.';
    case 'requires_supplemental_testing':
      return `There is not enough published test data for ${materialNames} in your exact service conditions. Additional testing (promoted ignition, mechanical impact, or other) is needed before the material can be approved. Your M&P engineer can specify which tests.`;
    case 'insufficient_evidence':
      return 'The assessment cannot be completed because some required information is missing. Check the warnings above — fill in the missing fields (material identity, pressure, temperature) and re-run the assessment.';
    case 'prohibited':
      return `${materialNames} cannot be used in this oxygen service environment. This is a hard stop from the governing standard (NASA-STD-6016C). The material must be replaced — there is no waiver path for this prohibition. See "Next Actions" for alternatives.`;
    default:
      return decision.summary_rationale;
  }
}

export default function OCAWorkbench() {
  const [authority, setAuthority] = useState<OCAAuthorityManifest | null>(null);
  const [loading, setLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guidanceMode, setGuidanceMode] = useState<GuidanceModeName>('live');

  const [materialName, setMaterialName] = useState('316L');
  const [spec, setSpec] = useState('');
  const [grade, setGrade] = useState('');
  const [temper, setTemper] = useState('');
  const [productForm, setProductForm] = useState('bar');
  const [coating, setCoating] = useState('');
  const [surfaceCondition, setSurfaceCondition] = useState('');
  const [roleInComponent, setRoleInComponent] = useState('body');
  const [componentClass, setComponentClass] = useState<(typeof COMPONENT_OPTIONS)[number]>('valve');
  const [geometryClass, setGeometryClass] = useState<(typeof GEOMETRY_OPTIONS)[number]>('bulk');
  const [designFunction, setDesignFunction] = useState('pressure control');
  const [sealType, setSealType] = useState<'metal' | 'polymer' | 'composite'>('polymer');
  const [pressureBoundaryMaterial, setPressureBoundaryMaterial] = useState('316L');
  const [oxidizerType, setOxidizerType] = useState<OCAOxidizerType>('gox');
  const [phase, setPhase] = useState<OCAPhase>('gas');
  const [o2Fraction, setO2Fraction] = useState('1.0');
  const [pressureMin, setPressureMin] = useState('14.7');
  const [pressureMax, setPressureMax] = useState('500');
  const [tempMin, setTempMin] = useState('20');
  const [tempMax, setTempMax] = useState('25');
  const [velocity, setVelocity] = useState('12');
  const [flowRegime, setFlowRegime] = useState<OCAFlowRegime>('laminar');
  const [missionPhase, setMissionPhase] = useState<OCAMissionPhase>('ground_test');
  const [cleanlinessVerified, setCleanlinessVerified] = useState(true);
  const [contaminationNotes, setContaminationNotes] = useState('');
  const [dynamicContact, setDynamicContact] = useState(false);
  const [rigidTubing, setRigidTubing] = useState(false);
  const [metallicFlexHose, setMetallicFlexHose] = useState(false);
  const [allMetalSeal, setAllMetalSeal] = useState(false);
  const [metallicPressureVessel, setMetallicPressureVessel] = useState(false);
  const [entrainableParticles, setEntrainableParticles] = useState(false);
  const [deadEndConfiguration, setDeadEndConfiguration] = useState(false);
  const [nonmetalInFlow, setNonmetalInFlow] = useState(true);
  const [rapidPressurizationMs, setRapidPressurizationMs] = useState('250');
  const [vibrationPresent, setVibrationPresent] = useState(false);
  const [acousticCavity, setAcousticCavity] = useState(false);
  const [mechanicalImpactRisk, setMechanicalImpactRisk] = useState(false);
  const [isolatedSurface, setIsolatedSurface] = useState(false);
  const [dryGas, setDryGas] = useState(true);
  const [electricalPower, setElectricalPower] = useState(false);
  const [reactiveChemicalPair, setReactiveChemicalPair] = useState(false);
  const [porousMedia, setPorousMedia] = useState(false);
  const [openFlame, setOpenFlame] = useState(false);

  const [createdCase, setCreatedCase] = useState<OCACreateCaseResponse | null>(null);
  const [precheck, setPrecheck] = useState<Awaited<ReturnType<typeof ocaPrecheck>> | null>(null);
  const [evidence, setEvidence] = useState<OCAEvidenceResponse | null>(null);
  const [mechanisms, setMechanisms] = useState<Awaited<ReturnType<typeof ocaAssessMechanisms>> | null>(null);
  const [requirements, setRequirements] = useState<OCARequirementsResponse | null>(null);
  const [decision, setDecision] = useState<OCADecisionPacket | null>(null);
  const [lineage, setLineage] = useState<OCALineageResponse | null>(null);
  const [exports, setExports] = useState<OCAExportArtifact[]>([]);

  const guidanceContext = createOcaContext({
    user_mode: guidanceMode,
    program: authority?.spec_id,
    service_environment: 'oxygen',
    pressure_regime: Number(pressureMax) >= 265 ? 'high' : Number(pressureMax) >= 50 ? 'medium' : 'low',
  });

  useEffect(() => {
    let cancelled = false;

    async function loadAuthority() {
      try {
        const response = await ocaGetAuthority();
        if (!cancelled) setAuthority(response);
      } catch {
        if (!cancelled) setAuthority(null);
      }
    }

    void loadAuthority();

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setExports([]);

    try {
      const request: OCACreateCaseRequest = {
        case_name: `${materialName} ${componentClass}`.trim(),
        service_context: {
          oxidizer_type: oxidizerType,
          o2_fraction: Number(o2Fraction),
          total_pressure_min_psia: Number(pressureMin),
          total_pressure_max_psia: Number(pressureMax),
          phase,
          temp_min_c: tempMin ? Number(tempMin) : null,
          temp_max_c: tempMax ? Number(tempMax) : null,
          flow_regime: flowRegime,
          velocity_m_s: velocity ? Number(velocity) : null,
          cleanliness_verified: cleanlinessVerified,
          contamination_notes: contaminationNotes || null,
          mission_phase: missionPhase,
          application: designFunction,
        },
        materials: [
          {
            material_name: materialName.trim(),
            spec: spec || null,
            grade: grade || null,
            temper: temper || null,
            product_form: productForm || null,
            coating: coating || null,
            surface_condition: surfaceCondition || null,
            role_in_component: roleInComponent || null,
          },
        ],
        components: [
          {
            component_id: 'cmp-1',
            component_class: componentClass,
            geometry_class: geometryClass,
            design_function: designFunction,
            dynamic_contact_flag: dynamicContact,
            is_rigid_metallic_tubing: rigidTubing,
            is_metallic_flex_hose: metallicFlexHose,
            is_all_metal_seal: allMetalSeal,
            is_metallic_pressure_vessel: metallicPressureVessel,
            seal_type: sealType,
            pressure_boundary_material: pressureBoundaryMaterial || null,
          },
        ],
        ignition_context: {
          entrainable_particles_present: entrainableParticles,
          rapid_pressurization_time_ms: rapidPressurizationMs ? Number(rapidPressurizationMs) : null,
          dead_end_configuration: deadEndConfiguration,
          nonmetal_exposed_to_flow: nonmetalInFlow,
          vibration_or_erosion_present: vibrationPresent,
          acoustic_cavity_present: acousticCavity,
          mechanical_impact_risk: mechanicalImpactRisk,
          isolated_surface_present: isolatedSurface,
          dry_gas_environment: dryGas,
          electrical_power_present: electricalPower,
          reactive_chemical_pair_present: reactiveChemicalPair,
          porous_media_present: porousMedia,
          open_flame_or_hot_work_present: openFlame,
        },
      };

      const created = await ocaCreateCase(request);
      setCreatedCase(created);

      const caseId = created.case_id;
      const [precheckResponse, evidenceResponse, mechanismResponse, decisionResponse, requirementsResponse, lineageResponse] =
        await Promise.all([
          ocaPrecheck(caseId),
          ocaGetEvidence(caseId),
          ocaAssessMechanisms(caseId),
          ocaRunDecision(caseId),
          ocaGetRequirements(caseId),
          ocaGetLineage(caseId),
        ]);

      setPrecheck(precheckResponse);
      setEvidence(evidenceResponse);
      setMechanisms(mechanismResponse);
      setDecision(decisionResponse.decision);
      setRequirements(requirementsResponse);
      setLineage(lineageResponse);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'OCA assessment failed.');
    } finally {
      setLoading(false);
    }
  }

  async function handleExport() {
    if (!createdCase?.case_id) return;
    setExportLoading(true);
    try {
      const response = await ocaExport(createdCase.case_id);
      setExports(response.artifacts);
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : 'Export failed.');
    } finally {
      setExportLoading(false);
    }
  }

  const adiabatic = calculateAdiabaticTf(293.15, Number(pressureMin) || 14.7, Number(pressureMax) || 14.7);
  const evidenceBuckets = EVIDENCE_ORDER.map((bucket) => ({
    bucket,
    items: evidence?.evidence.filter((item) => item.applicability.applicability_class === bucket) ?? [],
  })).filter((entry) => entry.items.length > 0);
  const displayedRequirements = requirements?.requirements ?? precheck?.triggered_requirements ?? [];
  const displayedMechanisms = mechanisms?.mechanisms ?? [];

  return (
    <GuidanceProvider
      schema={ocaGuidancePack}
      context={guidanceContext}
      mode={guidanceMode}
      telemetryEnabled
      onModeChange={(newMode) => setGuidanceMode(newMode)}
      authorityRegistry={authorityRegistry}
    >
      <div className="space-y-6">
        <div className="space-y-3">
          <PageHeader
            title="OCA Workbench"
            description="Deterministic oxygen compatibility screening and case routing per BS-SPEC-OCA-001-REV1."
          />
          <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
            <GuidanceContextIndicator context={guidanceContext} />
            <GuidanceModeSelector
              currentMode={guidanceMode}
              context={guidanceContext}
              modeRules={ocaGuidancePack.mode_rules}
              moduleOverride={ocaGuidancePack.module_mode_overrides?.[ocaGuidancePack.module]}
              onModeChange={(newMode) => setGuidanceMode(newMode)}
            />
          </div>
        </div>

        <section className="rounded-3xl border border-slate-900/15 bg-[linear-gradient(135deg,_rgba(88,58,22,0.97)_0%,_rgba(47,55,69,0.97)_38%,_rgba(8,27,42,1)_100%)] px-6 py-6 text-slate-50 shadow-[0_18px_50px_rgba(15,23,42,0.18)]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl space-y-2">
            <p className="text-xs uppercase tracking-[0.22em] text-amber-100/90">Oxygen Compatibility Assessment</p>
            <h2 className="text-2xl font-semibold tracking-tight text-white">Evidence-first, tier-separated, case-oriented.</h2>
            <p className="text-sm text-slate-100/90">
              Tier A requirements, Tier B TM mechanism logic, Tier C evidence scoring, and a locked lineage trail in one workbench.
            </p>
          </div>
          <div className="rounded-2xl border border-white/15 bg-slate-950/20 px-4 py-3 text-sm backdrop-blur-sm">
            <div className="text-xs uppercase tracking-[0.2em] text-amber-100/85">Screening Notice</div>
            <div className="mt-1 max-w-xs text-slate-100/90">
              Screening aid only. Formal OCA still requires M&P concurrence and reviewer signoff before release.
            </div>
          </div>
        </div>
        </section>

        <form onSubmit={handleSubmit} className="space-y-6">
        <Card className="overflow-hidden border-slate-200">
          <CardHeader className="border-b border-slate-200 bg-slate-50/70">
            <CardTitle>Assessment Input</CardTitle>
            <CardDescription>Capture the worst-case service envelope, component configuration, and mechanism context.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-6 p-6 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="space-y-6">
              <div>
                <div className="mb-3 flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">1</span>
                  <span className="text-sm font-semibold text-slate-800">What material?</span>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <GuidanceField
                    name="workbench.material_name"
                    htmlFor="material-name"
                    className="md:col-span-2"
                    validationState={requiredTextState(materialName)}
                    validationMessage="Material name is required."
                  >
                    <MaterialCombobox id="material-name" value={materialName} onChange={setMaterialName} />
                    <p className="text-[11px] text-slate-400">
                      Start typing to see known materials with their flammability class. Unknown materials are still accepted.
                    </p>
                  </GuidanceField>
                  <GuidanceField
                    name="workbench.product_form"
                    htmlFor="product-form"
                    validationState={requiredTextState(productForm)}
                    validationMessage="Product form is required."
                  >
                    <Input id="product-form" value={productForm} onChange={(e) => setProductForm(e.target.value)} placeholder="bar / tube / mesh" />
                  </GuidanceField>
                  <GuidanceField
                    name="workbench.role_in_component"
                    htmlFor="role"
                    validationState={requiredTextState(roleInComponent)}
                    validationMessage="Role in component is required."
                  >
                    <Input id="role" value={roleInComponent} onChange={(e) => setRoleInComponent(e.target.value)} placeholder="body / seat / seal" />
                  </GuidanceField>
                </div>
                <details className="mt-3">
                  <summary className="cursor-pointer text-xs font-medium text-slate-500 hover:text-slate-700">
                    More material details (spec, grade, temper, coating)
                  </summary>
                  <div className="mt-3 grid gap-4 md:grid-cols-2">
                    <GuidanceField name="workbench.spec" htmlFor="spec">
                      <Input id="spec" value={spec} onChange={(e) => setSpec(e.target.value)} placeholder="AMS 5666" />
                    </GuidanceField>
                    <GuidanceField name="workbench.grade" htmlFor="grade">
                      <Input id="grade" value={grade} onChange={(e) => setGrade(e.target.value)} placeholder="718" />
                    </GuidanceField>
                    <GuidanceField name="workbench.temper" htmlFor="temper">
                      <Input id="temper" value={temper} onChange={(e) => setTemper(e.target.value)} placeholder="T6 / annealed" />
                    </GuidanceField>
                    <GuidanceField name="workbench.coating" htmlFor="coating">
                      <Input id="coating" value={coating} onChange={(e) => setCoating(e.target.value)} placeholder="passivated / none" />
                    </GuidanceField>
                    <GuidanceField name="workbench.surface_condition" htmlFor="surface-condition">
                      <Input id="surface-condition" value={surfaceCondition} onChange={(e) => setSurfaceCondition(e.target.value)} placeholder="cleaned / machined" />
                    </GuidanceField>
                  </div>
                </details>
              </div>

              <div>
                <div className="mb-3 flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">2</span>
                  <span className="text-sm font-semibold text-slate-800">What hardware?</span>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <GuidanceField name="workbench.component_class">
                  <Select value={componentClass} onValueChange={(value) => setComponentClass(value as (typeof COMPONENT_OPTIONS)[number])}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {COMPONENT_OPTIONS.map((option) => (
                        <SelectItem key={option} value={option}>{option.replace('_', ' ')}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </GuidanceField>
                <GuidanceField name="workbench.geometry_class">
                  <Select value={geometryClass} onValueChange={(value) => setGeometryClass(value as (typeof GEOMETRY_OPTIONS)[number])}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {GEOMETRY_OPTIONS.map((option) => (
                        <SelectItem key={option} value={option}>{option.replace('_', ' ')}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </GuidanceField>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <GuidanceField
                  name="workbench.design_function"
                  htmlFor="design-function"
                  validationState={requiredTextState(designFunction)}
                  validationMessage="Design function is required."
                >
                  <Input id="design-function" value={designFunction} onChange={(e) => setDesignFunction(e.target.value)} />
                </GuidanceField>
                <GuidanceField
                  name="workbench.pressure_boundary_material"
                  htmlFor="boundary-material"
                  validationState={requiredTextState(pressureBoundaryMaterial)}
                  validationMessage="Pressure boundary material is required."
                >
                  <Input id="boundary-material" value={pressureBoundaryMaterial} onChange={(e) => setPressureBoundaryMaterial(e.target.value)} />
                </GuidanceField>
              </div>

              <details className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                <summary className="cursor-pointer text-sm font-medium">
                  Ignition Context <span className="ml-1 text-xs font-normal text-slate-400">(optional — defaults are conservative)</span>
                </summary>
                <div className="grid gap-3 sm:grid-cols-2">
                  {[
                    { fieldId: 'dynamic_contact_flag', label: 'Dynamic Contact', value: dynamicContact, setter: setDynamicContact },
                    { fieldId: 'entrainable_particles_present', label: 'Entrainable Particles', value: entrainableParticles, setter: setEntrainableParticles },
                    { fieldId: 'dead_end_configuration', label: 'Dead-End Configuration', value: deadEndConfiguration, setter: setDeadEndConfiguration },
                    { fieldId: 'nonmetal_exposed_to_flow', label: 'Nonmetal in Flow', value: nonmetalInFlow, setter: setNonmetalInFlow },
                    { fieldId: 'vibration_or_erosion_present', label: 'Vibration / Erosion', value: vibrationPresent, setter: setVibrationPresent },
                    { fieldId: 'acoustic_cavity_present', label: 'Acoustic Cavity', value: acousticCavity, setter: setAcousticCavity },
                    { fieldId: 'mechanical_impact_risk', label: 'Mechanical Impact Risk', value: mechanicalImpactRisk, setter: setMechanicalImpactRisk },
                    { fieldId: 'isolated_surface_present', label: 'Isolated Surface', value: isolatedSurface, setter: setIsolatedSurface },
                    { fieldId: 'dry_gas_environment', label: 'Dry Gas', value: dryGas, setter: setDryGas },
                    { fieldId: 'electrical_power_present', label: 'Electrical Power', value: electricalPower, setter: setElectricalPower },
                    { fieldId: 'reactive_chemical_pair_present', label: 'Reactive Chemical Pair', value: reactiveChemicalPair, setter: setReactiveChemicalPair },
                    { fieldId: 'porous_media_present', label: 'Porous Media', value: porousMedia, setter: setPorousMedia },
                    { fieldId: 'open_flame_or_hot_work_present', label: 'Open Flame / Hot Work', value: openFlame, setter: setOpenFlame },
                  ].map(({ fieldId, label, value, setter }) => (
                    <label key={fieldId} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                      <span className="flex items-center gap-1.5">
                        <span>{label}</span>
                        <OCAInlineHelp entry={workbenchHelp(fieldId)} />
                      </span>
                      <Switch checked={Boolean(value)} onCheckedChange={setter as (value: boolean) => void} />
                    </label>
                  ))}
                </div>
                <div className="mt-4 space-y-2">
                  <GuidanceField
                    name="workbench.rapid_pressurization_time_ms"
                    htmlFor="rapid-press"
                    validationState={numericInputState(rapidPressurizationMs)}
                    validationMessage="Rapid pressurization time must be numeric."
                  >
                  <Input id="rapid-press" type="number" value={rapidPressurizationMs} onChange={(e) => setRapidPressurizationMs(e.target.value)} />
                  </GuidanceField>
                </div>
              </details>
            </div>

            <div className="space-y-6">
              <div className="mb-3 flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">3</span>
                <span className="text-sm font-semibold text-slate-800">Service conditions</span>
              </div>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
                <GuidanceField name="workbench.oxidizer_type">
                  <Select value={oxidizerType} onValueChange={(value) => setOxidizerType(value as OCAOxidizerType)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {OXIDIZER_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </GuidanceField>
                <GuidanceField name="workbench.phase">
                  <Select value={phase} onValueChange={(value) => setPhase(value as OCAPhase)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PHASE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </GuidanceField>
                <GuidanceField
                  name="workbench.o2_fraction"
                  htmlFor="o2-fraction"
                  validationState={numericInputState(o2Fraction)}
                  validationMessage="O2 fraction must be numeric."
                >
                  <Input id="o2-fraction" type="number" step="0.01" value={o2Fraction} onChange={(e) => setO2Fraction(e.target.value)} />
                </GuidanceField>
                <GuidanceField
                  name="workbench.velocity_m_s"
                  htmlFor="velocity"
                  validationState={numericInputState(velocity)}
                  validationMessage="Velocity must be numeric."
                >
                  <Input id="velocity" type="number" step="0.1" value={velocity} onChange={(e) => setVelocity(e.target.value)} />
                </GuidanceField>
                <GuidanceField
                  name="workbench.total_pressure_min_psia"
                  htmlFor="pressure-min"
                  validationState={numericInputState(pressureMin)}
                  validationMessage="Minimum pressure must be numeric."
                >
                  <Input id="pressure-min" type="number" step="0.1" value={pressureMin} onChange={(e) => setPressureMin(e.target.value)} />
                </GuidanceField>
                <GuidanceField
                  name="workbench.total_pressure_max_psia"
                  htmlFor="pressure-max"
                  validationState={numericInputState(pressureMax)}
                  validationMessage="Maximum pressure must be numeric."
                >
                  <Input id="pressure-max" type="number" step="0.1" value={pressureMax} onChange={(e) => setPressureMax(e.target.value)} />
                </GuidanceField>
                <GuidanceField
                  name="workbench.temp_min_c"
                  htmlFor="temp-min"
                  validationState={numericInputState(tempMin)}
                  validationMessage="Minimum temperature must be numeric."
                >
                  <Input id="temp-min" type="number" step="0.1" value={tempMin} onChange={(e) => setTempMin(e.target.value)} />
                </GuidanceField>
                <GuidanceField
                  name="workbench.temp_max_c"
                  htmlFor="temp-max"
                  validationState={numericInputState(tempMax)}
                  validationMessage="Maximum temperature must be numeric."
                >
                  <Input id="temp-max" type="number" step="0.1" value={tempMax} onChange={(e) => setTempMax(e.target.value)} />
                </GuidanceField>
                <GuidanceField name="workbench.flow_regime">
                  <Select value={flowRegime} onValueChange={(value) => setFlowRegime(value as OCAFlowRegime)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {FLOW_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </GuidanceField>
                <GuidanceField name="workbench.mission_phase">
                  <Select value={missionPhase} onValueChange={(value) => setMissionPhase(value as OCAMissionPhase)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {MISSION_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </GuidanceField>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 space-y-4">
                <div className="text-sm font-medium">MPR 53 Exemption Flags</div>
                {[
                  { fieldId: 'is_rigid_metallic_tubing', label: 'Rigid Metallic Tubing', value: rigidTubing, setter: setRigidTubing },
                  { fieldId: 'is_metallic_flex_hose', label: 'Metallic Flex Hose', value: metallicFlexHose, setter: setMetallicFlexHose },
                  { fieldId: 'is_all_metal_seal', label: 'All-Metal Seal', value: allMetalSeal, setter: setAllMetalSeal },
                  { fieldId: 'is_metallic_pressure_vessel', label: 'Metallic Pressure Vessel', value: metallicPressureVessel, setter: setMetallicPressureVessel },
                ].map(({ fieldId, label, value, setter }) => (
                  <label key={fieldId} className="flex items-center justify-between gap-3 text-sm">
                    <span className="flex items-center gap-1.5">
                      <span>{label}</span>
                      <OCAInlineHelp entry={workbenchHelp(fieldId)} />
                    </span>
                    <Switch checked={Boolean(value)} onCheckedChange={setter as (value: boolean) => void} />
                  </label>
                ))}
                <label className="flex items-center justify-between gap-3 text-sm">
                  <span className="flex items-center gap-1.5">
                    <span>Cleanliness Verified</span>
                    <OCAInlineHelp entry={workbenchHelp('cleanliness_verified')} />
                  </span>
                  <Switch checked={cleanlinessVerified} onCheckedChange={setCleanlinessVerified} />
                </label>
                <GuidanceField name="workbench.contamination_notes" htmlFor="contamination-notes">
                  <Textarea
                    id="contamination-notes"
                    value={contaminationNotes}
                    onChange={(e) => setContaminationNotes(e.target.value)}
                    placeholder="Known debris sources, cleaning assumptions, or unresolved contamination concerns."
                  />
                </GuidanceField>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">Adiabatic Compression Check</div>
                    <div className="text-xs text-muted-foreground">Local calculator for rapid-pressurization what-if review.</div>
                  </div>
                  <Flame className="h-4 w-4 text-orange-500" />
                </div>
                {adiabatic ? (
                  <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
                    <div className="rounded-xl bg-slate-50 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Tf (K)</div>
                      <div className="mt-1 font-semibold">{adiabatic.tfK.toFixed(1)}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Tf (°C)</div>
                      <div className="mt-1 font-semibold">{adiabatic.tfC.toFixed(1)}</div>
                    </div>
                    <div className="rounded-xl bg-slate-50 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Tf (°F)</div>
                      <div className="mt-1 font-semibold">{adiabatic.tfF.toFixed(1)}</div>
                    </div>
                  </div>
                ) : (
                  <div className="mt-3 text-sm text-muted-foreground">Enter valid pressures to compute the compression endpoint temperature.</div>
                )}
              </div>

              <Button type="submit" disabled={loading} className="w-full gap-2">
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScrollText className="h-4 w-4" />}
                Run OCA Case
              </Button>
            </div>
          </CardContent>
        </Card>
      </form>

      {error && (
        <Card className="border-rose-200 bg-rose-50">
          <CardContent className="flex items-start gap-3 p-4 text-rose-900">
            <ShieldX className="mt-0.5 h-4 w-4" />
            <div className="text-sm">{error}</div>
          </CardContent>
        </Card>
      )}

      {precheck?.blocked_states.length ? (
        <Card className="border-amber-300 bg-amber-50">
          <CardHeader>
            <CardTitle className="text-base">Blocked States</CardTitle>
            <CardDescription>Assessment remains partial until the following blockers are resolved.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {precheck.blocked_states.map((state) => (
              <div key={state.code} className="rounded-2xl border border-amber-200 bg-white p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-amber-900">
                  <AlertTriangle className="h-4 w-4" />
                  {state.code.replaceAll('_', ' ')}
                </div>
                <p className="mt-2 text-sm text-slate-700">{state.detail}</p>
                <p className="mt-1 text-xs text-slate-500">{state.resolution_hint}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {createdCase && decision && (
        <>
          <Card className="overflow-hidden border-slate-200">
            <CardHeader className="border-b border-slate-200 bg-slate-50/70">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle>Case Summary</CardTitle>
                  <CardDescription>{createdCase.case_id} · revision {createdCase.revision}</CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Badge className={DISPOSITION_META[decision.final_disposition]?.className || 'bg-slate-700 text-white'}>
                    {DISPOSITION_META[decision.final_disposition]?.label || decision.final_disposition}
                  </Badge>
                  <OCAInlineHelp entry={getDispositionGuidance(decision.final_disposition)} />
                </div>
              </div>
            </CardHeader>
            <CardContent className="grid gap-6 p-6 lg:grid-cols-[1.2fr_0.8fr]">
              <div className="space-y-4">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">What this means</div>
                  <p className="mt-1.5 text-sm leading-relaxed text-slate-700">
                    {dispositionPlainEnglish(decision.final_disposition, decision)}
                  </p>
                </div>
                {decision.governing_prohibition ? (
                  <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
                    Governing prohibition: {decision.governing_prohibition}
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  {displayedRequirements.filter((item) => item.triggered).map((item) => (
                    <span key={item.requirement_id} className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${statusClass(item.status)}`}>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] ${tierClass(item.tier)}`}>{item.tier.replace('tier_', 'T').toUpperCase()}</span>
                      {item.requirement_id}
                    </span>
                  ))}
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Overall Confidence</div>
                    <div className="mt-1 text-lg font-semibold capitalize">{decision.overall_confidence}</div>
                  </div>
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Authority Tier</div>
                    <div className="mt-1 text-lg font-semibold">{decision.authority_level.replace('tier_', 'Tier ').toUpperCase()}</div>
                  </div>
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Open Gaps</div>
                    <div className="mt-1 text-lg font-semibold">{decision.unresolved_gaps.length}</div>
                  </div>
                </div>
              </div>

              <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="text-sm font-medium">Next Actions</div>
                <div className="mt-4 space-y-3">
                  {decision.actions.length ? decision.actions.map((action) => (
                    <div key={action.action_id} className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                      <div className="text-sm font-medium text-slate-900">{action.label}</div>
                      <div className="mt-1 text-xs text-slate-600">{action.rationale}</div>
                    </div>
                  )) : (
                    <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
                      No additional routing actions were required for the current screening pass.
                    </div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>Requirement Backbone</CardTitle>
              <CardDescription>Tier A requirement state with rationale and downstream actions.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-2">
              {displayedRequirements.map((item) => (
                <div key={item.requirement_id} className="rounded-2xl border border-slate-200 bg-white p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${tierClass(item.tier)}`}>
                        {item.tier.replace('tier_', 'T').toUpperCase()}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="text-sm font-medium">{item.requirement_id}</span>
                        <OCAInlineHelp entry={getMprGuidance(item.requirement_id)} />
                      </span>
                    </div>
                    <Badge className={statusClass(item.status)}>{item.status.replaceAll('_', ' ')}</Badge>
                  </div>
                  <p className="mt-3 text-sm text-slate-800">{item.title}</p>
                  <p className="mt-1 text-xs text-slate-500">{item.citation}</p>
                  <p className="mt-3 text-sm text-slate-600">{item.reasoning}</p>
                  {item.downstream_actions.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {item.downstream_actions.map((action) => (
                        <Badge key={action} variant="outline" className="text-[11px]">{action}</Badge>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>Evidence Applicability</CardTitle>
              <CardDescription>Evidence is grouped by directness before it influences the case disposition.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {evidenceBuckets.map(({ bucket, items }) => (
                <div key={bucket} className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">{bucket.replace('_', ' ')}</div>
                    <Badge variant="outline">{items.length}</Badge>
                  </div>
                  <div className="grid gap-3 lg:grid-cols-2">
                    {items.map((item) => (
                      <div key={item.evidence_id} className={`rounded-2xl border p-4 ${applicabilityClassName(item.applicability.applicability_class)}`}>
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-medium text-slate-900">{item.title}</div>
                            <div className="mt-1 text-xs text-slate-500">{item.citation}</div>
                          </div>
                          <Badge variant="outline">{item.applicability.aggregate_score.toFixed(2)}</Badge>
                        </div>
                        <p className="mt-3 text-sm text-slate-700">{item.summary}</p>
                        <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
                          <div>Material: {item.material_name}</div>
                          <div>Method: {item.test_method || 'n/a'}</div>
                          <div>Result: {item.result || 'n/a'}</div>
                          <div>Applicability: {item.applicability.applicability_class}</div>
                        </div>
                        {item.gaps.length ? (
                          <div className="mt-3 space-y-1 text-xs text-amber-800">
                            {item.gaps.map((gap) => (
                              <div key={gap}>• {gap}</div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader>
              <CardTitle>Ignition Mechanisms</CardTitle>
              <CardDescription>
                {(() => {
                  const credible = displayedMechanisms.filter((item: OCAMechanismAssessment) => item.credible_status === 'CREDIBLE');
                  const indeterminate = displayedMechanisms.filter((item: OCAMechanismAssessment) => item.credible_status === 'INDETERMINATE');
                  const notCredible = displayedMechanisms.filter((item: OCAMechanismAssessment) => item.credible_status === 'NOT_CREDIBLE');
                  return `${displayedMechanisms.length} mechanisms evaluated: ${credible.length} credible, ${indeterminate.length} need review, ${notCredible.length} not credible.`;
                })()}
              </CardDescription>
            </CardHeader>
            {(() => {
              const credible = displayedMechanisms.filter((item: OCAMechanismAssessment) => item.credible_status === 'CREDIBLE');
              const indeterminate = displayedMechanisms.filter((item: OCAMechanismAssessment) => item.credible_status === 'INDETERMINATE');
              if (credible.length === 0 && indeterminate.length === 0) {
                return (
                  <div className="mx-6 mb-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
                    <CheckCircle2 className="mb-1 inline h-4 w-4" /> No ignition mechanisms are credible for this configuration. All required elements were absent or the material is nonflammable in this envelope.
                  </div>
                );
              }
              return (
                <div className="mx-6 mb-4 space-y-2">
                  {credible.length ? (
                    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wider text-amber-700">Credible Mechanisms ({credible.length})</div>
                      <div className="mt-2 space-y-1">
                        {credible
                          .sort((left: OCAMechanismAssessment, right: OCAMechanismAssessment) => right.rating - left.rating)
                          .map((item: OCAMechanismAssessment) => (
                            <div key={item.mechanism_name} className="flex items-center justify-between text-sm">
                              <span className="text-slate-800">{item.mechanism_name.replace(/_/g, ' ')}</span>
                              <span className="font-semibold text-amber-800">Rating {item.rating}/4</span>
                            </div>
                          ))}
                      </div>
                    </div>
                  ) : null}
                  {indeterminate.length ? (
                    <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
                      <div className="text-xs font-semibold uppercase tracking-wider text-rose-700">Need More Information ({indeterminate.length})</div>
                      <div className="mt-2 space-y-1">
                        {indeterminate.map((item: OCAMechanismAssessment) => (
                          <div key={item.mechanism_name} className="text-sm text-slate-700">
                            {item.mechanism_name.replace(/_/g, ' ')} — {item.missing_elements.length ? `missing: ${item.missing_elements.join(', ')}` : 'additional context needed'}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })()}
            <CardContent>
              <div className="overflow-x-auto pb-2">
                <div className="flex gap-4 min-w-max">
                  {displayedMechanisms.map((mechanism: OCAMechanismAssessment) => (
                    <div key={mechanism.mechanism_name} className="w-[320px] rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-1.5">
                            <div className="text-sm font-medium">{mechanism.mechanism_name}</div>
                            <OCAInlineHelp entry={getMechanismGuidance(mechanism.mechanism_name)} />
                          </div>
                          <div className="mt-1 text-xs text-slate-500">{mechanism.source_ref}</div>
                        </div>
                        {mechanismIcon(mechanism.credible_status)}
                      </div>
                      <div className="mt-4 flex items-center justify-between">
                        <Badge className={statusClass(mechanism.credible_status === 'NOT_CREDIBLE' ? 'satisfied' : mechanism.credible_status === 'CREDIBLE' ? 'action_required' : 'prohibited')}>
                          {mechanism.credible_status.replace('_', ' ')}
                        </Badge>
                        <div className="text-sm font-semibold">Rating {mechanism.rating}/4</div>
                      </div>
                      <div className="mt-4 space-y-3 text-sm">
                        <div>
                          <div className="text-xs uppercase tracking-wide text-muted-foreground">Observed</div>
                          <div className="mt-1 text-slate-700">{mechanism.observed_elements.join(', ') || 'None captured'}</div>
                        </div>
                        <div>
                          <div className="text-xs uppercase tracking-wide text-muted-foreground">Missing</div>
                          <div className="mt-1 text-slate-700">{mechanism.missing_elements.join(', ') || 'No missing elements'}</div>
                        </div>
                        {mechanism.gaps_identified.length ? (
                          <div className="rounded-2xl bg-amber-50 p-3 text-xs text-amber-900">
                            {mechanism.gaps_identified.join(' ')}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
            <Card className="border-slate-200">
              <CardHeader>
                <CardTitle>Decision Lineage</CardTitle>
                <CardDescription>Every rule execution is recorded with tier, stage, and outcome.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {lineage?.decision_lineage.slice(0, 12).map((entry) => (
                  <div key={`${entry.stage}-${entry.rule_id}-${entry.recorded_at}`} className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Badge className={tierClass(entry.tier)}>{entry.tier.replace('tier_', 'T').toUpperCase()}</Badge>
                        <span className="text-sm font-medium">{entry.rule_id}</span>
                      </div>
                      <span className="text-xs text-slate-500">{entry.stage}</span>
                    </div>
                    <div className="mt-2 text-xs text-slate-600">{entry.detail}</div>
                  </div>
                )) || <div className="text-sm text-muted-foreground">No lineage available yet.</div>}
              </CardContent>
            </Card>

            <Card className="border-slate-200">
              <CardHeader>
                <CardTitle>Export & Authority</CardTitle>
                <CardDescription>Review the locked source manifest and generate case artifacts.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-sm font-medium">Authority Pack</div>
                  <div className="mt-3 space-y-2 text-sm text-slate-700">
                    {authority?.sources.slice(0, 4).map((source) => (
                      <div key={source.source_id} className="flex items-center justify-between gap-3">
                        <span>{source.title}</span>
                        <span className="text-xs text-slate-500">{source.edition}{source.change_number ? ` / ${source.change_number}` : ''}</span>
                      </div>
                    )) || <div className="text-muted-foreground">Authority manifest unavailable.</div>}
                  </div>
                </div>

                <Button onClick={handleExport} disabled={exportLoading || !createdCase?.case_id} className="w-full gap-2">
                  {exportLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileStack className="h-4 w-4" />}
                  Generate Export Pack
                </Button>

                {exports.length ? (
                  <div className="space-y-3">
                    {exports.map((artifact) => (
                      <div key={artifact.filename} className="rounded-2xl border border-slate-200 bg-white p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="text-sm font-medium">{artifact.artifact_type.replace('_', ' ')}</div>
                            <div className="mt-1 text-xs text-slate-500">{artifact.filename}</div>
                          </div>
                          <Button variant="outline" size="sm" onClick={() => downloadArtifact(artifact)}>
                            Download
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </div>
        </>
      )}

        {loading ? (
          <Card className="border-slate-200">
            <CardContent className="flex items-center justify-center gap-3 py-10 text-sm text-slate-600">
              <Loader2 className="h-4 w-4 animate-spin" />
              Building deterministic OCA case, evidence map, mechanism traces, and decision lineage.
            </CardContent>
          </Card>
        ) : null}
      </div>
    </GuidanceProvider>
  );
}
