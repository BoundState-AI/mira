import { useDeferredValue, useEffect, useState, type FormEvent } from 'react';
import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
} from 'lucide-react';

import { PageHeader } from '@/components/PageHeader';
import { StatusBadge } from '@/components/StatusBadge';
import { MiraHelpLabel, MiraInlineHelp } from '@/components/mira/MiraInlineHelp';
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
  galvanicEvaluate,
  galvanicGetSeries,
  galvanicListEnvironments,
  galvanicSearchMaterials,
  type GalvanicAssessmentResponse,
  type GalvanicEnvironmentDescriptor,
  type GalvanicMaterialSearchResult,
  type GalvanicMitigationRecommendation,
  type GalvanicSeriesPayload,
} from '@/lib/api';
import { getMiraGuidanceEntry, getMiraInputGuidance } from '@/lib/mira-guidance';
import { useAuth } from '@/auth/AuthContext';

const APPLICATION_OPTIONS = [
  { value: 'FLIGHT_HARDWARE', label: 'Flight Hardware' },
  { value: 'SPACECRAFT_STRUCTURE', label: 'Spacecraft Structure' },
  { value: 'GROUND_SUPPORT_EQUIPMENT', label: 'Ground Support Equipment' },
  { value: 'LAUNCH_STRUCTURE', label: 'Launch Structure' },
  { value: 'FIXED_INSTALLATION', label: 'Fixed Installation' },
] as const;

const JOINT_OPTIONS = [
  { value: 'GENERAL', label: 'General Contact' },
  { value: 'FASTENER', label: 'Fastener Joint' },
  { value: 'FAYING_SURFACE', label: 'Faying Surface' },
  { value: 'LAP_JOINT', label: 'Lap Joint' },
  { value: 'CREVICE_PRONE', label: 'Crevice-Prone' },
  { value: 'IMMERSED', label: 'Immersed Joint' },
] as const;

const ELECTRICAL_CONTACT_OPTIONS = [
  { value: 'YES', label: 'Yes' },
  { value: 'NO', label: 'No' },
  { value: 'UNKNOWN', label: 'Unknown' },
] as const;

const SURFACE_OPTIONS = [
  { value: 'bare', label: 'Bare / untreated' },
  { value: 'anodized', label: 'Anodized' },
  { value: 'conversion-coated', label: 'Conversion coated' },
  { value: 'passivated', label: 'Passivated' },
  { value: 'primed', label: 'Primed' },
  { value: 'painted', label: 'Painted' },
  { value: 'fully_coated', label: 'Fully coated barrier' },
  { value: 'isolated', label: 'Electrical isolation' },
] as const;

const DECISION_BASIS_LABELS: Record<string, string> = {
  NASA_STD_6012A_CPR39: 'NASA-STD-6012A CPR 39',
  BOUNDSTATE_SYNTHESIZED: 'BoundState screening band',
  NO_ELECTRICAL_CONTACT: 'No electrical contact',
  NO_ELECTROLYTE: 'No electrolyte / open circuit',
};

const TARGET_DELTA_DEFAULT_MAX = 1200;

const MITIGATION_UI_EFFECTS: Record<
  string,
  { mode: 'multiplier' | 'floor'; value: number; label: string }
> = {
  anodize_aluminum: { mode: 'multiplier', value: 0.8, label: 'Anodize reduces the effective driving difference.' },
  cathodic_barrier_coating: { mode: 'multiplier', value: 0.75, label: 'Barrier coating suppresses galvanic current.' },
  seal_faying_surfaces: { mode: 'multiplier', value: 0.82, label: 'Sealing reduces electrolyte access at the interface.' },
  wet_install_fasteners: { mode: 'multiplier', value: 0.9, label: 'Wet-installed fasteners reduce trapped-electrolyte exposure.' },
  titanium_fasteners_for_cfrp: { mode: 'multiplier', value: 0.9, label: 'Titanium hardware moderates CFRP fastener couples.' },
  passivate_stainless_fasteners: { mode: 'multiplier', value: 0.92, label: 'Passivation improves stainless surface behavior.' },
  zinc_nickel_plating_for_steel: { mode: 'multiplier', value: 0.68, label: 'Plating substitutes the exposed steel surface state.' },
  cadmium_plating_restricted: { mode: 'multiplier', value: 0.62, label: 'Cadmium plating can materially reduce the effective gap.' },
  sacrificial_anode_gacp: { mode: 'multiplier', value: 0.55, label: 'Sacrificial protection shifts the system toward the anode.' },
  iccp_structures_only: { mode: 'multiplier', value: 0.45, label: 'ICCP is treated as a strong system-level reduction.' },
  physical_isolation: { mode: 'floor', value: 0, label: 'Electrical isolation breaks the galvanic circuit.' },
};

type PlannedMitigationStep = {
  mitigation: GalvanicMitigationRecommendation;
  estimated_delta_mv: number;
  planning_note: string;
};

function formatMillivolts(value: number): string {
  return `${Math.round(value)} mV`;
}

function classifyDelta(deltaMv: number): 'COMPATIBLE' | 'CAUTION' | 'INCOMPATIBLE' {
  if (deltaMv < 250) return 'COMPATIBLE';
  if (deltaMv <= 500) return 'CAUTION';
  return 'INCOMPATIBLE';
}

function severityIcon(severity: string) {
  if (severity === 'COMPATIBLE') return <ShieldCheck className="h-5 w-5 text-emerald-600" />;
  if (severity === 'CAUTION') return <ShieldAlert className="h-5 w-5 text-amber-600" />;
  return <ShieldX className="h-5 w-5 text-rose-600" />;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function deltaMarkerPosition(deltaMv: number, scaleMax: number): number {
  return (clamp(deltaMv, 0, scaleMax) / scaleMax) * 100;
}

function buildMitigationPlan(
  result: GalvanicAssessmentResponse,
  targetDeltaMv: number,
): {
  steps: PlannedMitigationStep[];
  remaining_delta_mv: number;
  can_reach_target: boolean;
  used_circuit_break: boolean;
} {
  let remaining = result.effective_delta_mv;
  const steps: PlannedMitigationStep[] = [];
  const deferredCircuitBreakers: GalvanicMitigationRecommendation[] = [];

  if (remaining <= targetDeltaMv) {
    return { steps, remaining_delta_mv: remaining, can_reach_target: true, used_circuit_break: false };
  }

  for (const mitigation of result.mitigations) {
    const effect = MITIGATION_UI_EFFECTS[mitigation.mitigation_id];
    if (!effect) continue;
    if (effect.mode === 'floor') {
      deferredCircuitBreakers.push(mitigation);
      continue;
    }

    const nextDelta = remaining * effect.value;
    if (nextDelta >= remaining) continue;

    remaining = nextDelta;
    steps.push({
      mitigation,
      estimated_delta_mv: nextDelta,
      planning_note: effect.label,
    });

    if (remaining <= targetDeltaMv) {
      return { steps, remaining_delta_mv: remaining, can_reach_target: true, used_circuit_break: false };
    }
  }

  for (const mitigation of deferredCircuitBreakers) {
    const effect = MITIGATION_UI_EFFECTS[mitigation.mitigation_id];
    if (!effect) continue;

    const nextDelta = Math.min(remaining, effect.value);
    if (nextDelta >= remaining) continue;

    remaining = nextDelta;
    steps.push({
      mitigation,
      estimated_delta_mv: nextDelta,
      planning_note: effect.label,
    });

    return {
      steps,
      remaining_delta_mv: remaining,
      can_reach_target: true,
      used_circuit_break: true,
    };
  }

  return {
    steps,
    remaining_delta_mv: remaining,
    can_reach_target: remaining <= targetDeltaMv,
    used_circuit_break: false,
  };
}

function MaterialSuggestions({
  results,
  onPick,
}: {
  results: GalvanicMaterialSearchResult[];
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

export default function GalvanicCompatibility() {
  const { authHeaders, loading: authLoading } = useAuth();
  const galvanicHelp = (fieldId: string) => getMiraInputGuidance('galvanic', fieldId);
  const [materialA, setMaterialA] = useState('Al 6061-T6');
  const [materialB, setMaterialB] = useState('316SS');
  const [environment, setEnvironment] = useState('seawater_proxy');
  const [applicationType, setApplicationType] = useState('FLIGHT_HARDWARE');
  const [jointType, setJointType] = useState('GENERAL');
  const [electricalContact, setElectricalContact] = useState('YES');
  const [surfaceConditionA, setSurfaceConditionA] = useState('bare');
  const [surfaceConditionB, setSurfaceConditionB] = useState('bare');
  const [electrolytePooling, setElectrolytePooling] = useState(false);
  const [areaRatio, setAreaRatio] = useState('');
  const [environments, setEnvironments] = useState<GalvanicEnvironmentDescriptor[]>([]);
  const [seriesPayload, setSeriesPayload] = useState<GalvanicSeriesPayload | null>(null);
  const [searchA, setSearchA] = useState<GalvanicMaterialSearchResult[]>([]);
  const [searchB, setSearchB] = useState<GalvanicMaterialSearchResult[]>([]);
  const [result, setResult] = useState<GalvanicAssessmentResponse | null>(null);
  const [targetDeltaMv, setTargetDeltaMv] = useState(0);
  const [loading, setLoading] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const deferredMaterialA = useDeferredValue(materialA);
  const deferredMaterialB = useDeferredValue(materialB);

  useEffect(() => {
    if (authLoading) return;

    let cancelled = false;

    async function loadReferenceData() {
      setBootLoading(true);
      try {
        const [environmentList, series] = await Promise.all([
          galvanicListEnvironments(authHeaders),
          galvanicGetSeries(authHeaders),
        ]);
        if (cancelled) return;
        setEnvironments(environmentList);
        setSeriesPayload(series);
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : 'Failed to load corrosion reference data.');
      } finally {
        if (!cancelled) {
          setBootLoading(false);
        }
      }
    }

    void loadReferenceData();

    return () => {
      cancelled = true;
    };
  }, [authLoading]);

  useEffect(() => {
    if (authLoading) return;

    let cancelled = false;

    async function search() {
      const query = deferredMaterialA.trim();
      if (query.length < 2) {
        setSearchA([]);
        return;
      }
      try {
        const matches = await galvanicSearchMaterials(query, authHeaders);
        if (!cancelled) setSearchA(matches);
      } catch {
        if (!cancelled) setSearchA([]);
      }
    }

    void search();

    return () => {
      cancelled = true;
    };
  }, [authHeaders, authLoading, deferredMaterialA]);

  useEffect(() => {
    if (authLoading) return;

    let cancelled = false;

    async function search() {
      const query = deferredMaterialB.trim();
      if (query.length < 2) {
        setSearchB([]);
        return;
      }
      try {
        const matches = await galvanicSearchMaterials(query, authHeaders);
        if (!cancelled) setSearchB(matches);
      } catch {
        if (!cancelled) setSearchB([]);
      }
    }

    void search();

    return () => {
      cancelled = true;
    };
  }, [authHeaders, authLoading, deferredMaterialB]);

  async function runAssessment(showError = true) {
    if (!materialA.trim() || !materialB.trim()) {
      setResult(null);
      return;
    }

    setLoading(true);
    if (showError) setError(null);

    try {
      const assessment = await galvanicEvaluate({
        material_a: materialA.trim(),
        material_b: materialB.trim(),
        environment: environment as never,
        application_type: applicationType as never,
        surface_condition_a: surfaceConditionA === 'bare' ? null : surfaceConditionA,
        surface_condition_b: surfaceConditionB === 'bare' ? null : surfaceConditionB,
        couple_context: {
          electrical_contact: electricalContact as never,
          electrolyte_pooling: electrolytePooling,
          joint_type: jointType as never,
          cathode_to_anode_area_ratio: areaRatio ? Number(areaRatio) : null,
        },
      }, authHeaders);
      setResult(assessment);
    } catch (assessmentError) {
      if (showError) {
        setError(assessmentError instanceof Error ? assessmentError.message : 'Corrosion assessment failed.');
      }
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (authLoading || bootLoading) return;
    if (!materialA.trim() || !materialB.trim()) {
      setResult(null);
      return;
    }

    const timer = window.setTimeout(() => {
      void runAssessment(false);
    }, 300);

    return () => {
      window.clearTimeout(timer);
    };
  }, [
    authLoading,
    bootLoading,
    deferredMaterialA,
    deferredMaterialB,
    environment,
    applicationType,
    jointType,
    electricalContact,
    surfaceConditionA,
    surfaceConditionB,
    electrolytePooling,
    areaRatio,
  ]);

  useEffect(() => {
    if (result) {
      setTargetDeltaMv(Math.round(result.effective_delta_mv));
    }
  }, [result]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runAssessment(true);
  }

  const selectedEnvironment = environments.find((item) => item.key === environment);
  const targetScaleMax = Math.max(
    TARGET_DELTA_DEFAULT_MAX,
    Math.ceil((result?.raw_delta_mv ?? 0) / 100) * 100,
  );
  const currentMarkerPosition = result ? deltaMarkerPosition(result.effective_delta_mv, targetScaleMax) : 0;
  const targetMarkerPosition = deltaMarkerPosition(targetDeltaMv, targetScaleMax);
  const targetSeverity = classifyDelta(targetDeltaMv);
  const targetPlan = result ? buildMitigationPlan(result, targetDeltaMv) : null;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Galvanic Compatibility"
        description="Corrosion prevention screen for dissimilar material couples. The intrinsic EMF positions update as you type, and the right-side target box can be dragged toward green to see what protection scheme gets you there."
      />

      <div className="space-y-6">
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="text-xl">Assessment Inputs</CardTitle>
            <CardDescription>
              This page auto-screens the pair as you enter materials. The button remains available when you want a manual rerun.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-6" onSubmit={handleSubmit}>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <MiraHelpLabel htmlFor="material-a" entry={galvanicHelp('material_a')}>
                    Material A
                  </MiraHelpLabel>
                  <Input
                    id="material-a"
                    value={materialA}
                    onChange={(event) => setMaterialA(event.target.value)}
                    placeholder="Example: Al 6061-T6"
                    className="mt-2"
                  />
                  <MaterialSuggestions results={searchA} onPick={setMaterialA} />
                </div>
                <div>
                  <MiraHelpLabel htmlFor="material-b" entry={galvanicHelp('material_b')}>
                    Material B
                  </MiraHelpLabel>
                  <Input
                    id="material-b"
                    value={materialB}
                    onChange={(event) => setMaterialB(event.target.value)}
                    placeholder="Example: Graphite"
                    className="mt-2"
                  />
                  <MaterialSuggestions results={searchB} onPick={setMaterialB} />
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div>
                  <MiraHelpLabel entry={galvanicHelp('environment')}>Environment</MiraHelpLabel>
                  <Select value={environment} onValueChange={setEnvironment}>
                    <SelectTrigger className="mt-2">
                      <SelectValue placeholder="Select environment" />
                    </SelectTrigger>
                    <SelectContent>
                      {environments.map((item) => (
                        <SelectItem key={item.key} value={item.key}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <MiraHelpLabel entry={galvanicHelp('application_type')}>Application</MiraHelpLabel>
                  <Select value={applicationType} onValueChange={setApplicationType}>
                    <SelectTrigger className="mt-2">
                      <SelectValue placeholder="Select application" />
                    </SelectTrigger>
                    <SelectContent>
                      {APPLICATION_OPTIONS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <MiraHelpLabel entry={galvanicHelp('joint_type')}>Joint Type</MiraHelpLabel>
                  <Select value={jointType} onValueChange={setJointType}>
                    <SelectTrigger className="mt-2">
                      <SelectValue placeholder="Select joint type" />
                    </SelectTrigger>
                    <SelectContent>
                      {JOINT_OPTIONS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <MiraHelpLabel entry={galvanicHelp('electrical_contact')}>Electrical Contact</MiraHelpLabel>
                  <Select value={electricalContact} onValueChange={setElectricalContact}>
                    <SelectTrigger className="mt-2">
                      <SelectValue placeholder="Select contact state" />
                    </SelectTrigger>
                    <SelectContent>
                      {ELECTRICAL_CONTACT_OPTIONS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                <div>
                  <MiraHelpLabel entry={galvanicHelp('surface_condition_a')}>Surface Condition A</MiraHelpLabel>
                  <Select value={surfaceConditionA} onValueChange={setSurfaceConditionA}>
                    <SelectTrigger className="mt-2">
                      <SelectValue placeholder="Select surface condition" />
                    </SelectTrigger>
                    <SelectContent>
                      {SURFACE_OPTIONS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <MiraHelpLabel entry={galvanicHelp('surface_condition_b')}>Surface Condition B</MiraHelpLabel>
                  <Select value={surfaceConditionB} onValueChange={setSurfaceConditionB}>
                    <SelectTrigger className="mt-2">
                      <SelectValue placeholder="Select surface condition" />
                    </SelectTrigger>
                    <SelectContent>
                      {SURFACE_OPTIONS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <MiraHelpLabel htmlFor="area-ratio" entry={galvanicHelp('cathode_to_anode_area_ratio')}>
                    Cathode:Anode Area Ratio
                  </MiraHelpLabel>
                  <Input
                    id="area-ratio"
                    type="number"
                    min="0"
                    step="0.1"
                    value={areaRatio}
                    onChange={(event) => setAreaRatio(event.target.value)}
                    placeholder="Example: 12"
                    className="mt-2"
                  />
                </div>
              </div>

              <label className="flex items-center gap-3 rounded-lg border border-dashed border-border px-4 py-3">
                <Checkbox
                  checked={electrolytePooling}
                  onCheckedChange={(checked) => setElectrolytePooling(Boolean(checked))}
                />
                <div>
                  <div className="flex items-center gap-1.5">
                    <div className="text-sm font-medium">Persistent electrolyte pooling expected</div>
                    <MiraInlineHelp
                      entry={galvanicHelp('electrolyte_pooling')}
                      title="Persistent electrolyte pooling expected"
                    />
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Use this when the joint retains condensed moisture, trapped wash water, or standing fluid.
                  </div>
                </div>
              </label>

              <div className="flex items-center gap-3">
                <Button type="submit" disabled={loading || bootLoading}>
                  {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Run Corrosion Screen
                </Button>
                {selectedEnvironment && (
                  <p className="text-sm text-muted-foreground">
                    Environment factor: <span className="font-medium text-foreground">{selectedEnvironment.modifier.toFixed(2)}x</span>
                  </p>
                )}
              </div>
            </form>
          </CardContent>
        </Card>
      </div>

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
                    {severityIcon(result.severity)}
                    <div className="text-2xl font-semibold">
                      {result.material_a.canonical_name} vs {result.material_b.canonical_name}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={result.severity} />
                  <MiraInlineHelp entry={getMiraGuidanceEntry('galvanic', 'verdicts', result.severity)} />
                </div>
              </div>
            </div>

            <CardContent className="pt-6">
              <div className="grid gap-4 md:grid-cols-3">
                <div className="rounded-lg border p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Raw delta</div>
                  <div className="mt-2 text-3xl font-semibold">{formatMillivolts(result.raw_delta_mv)}</div>
                </div>
                <div className="rounded-lg border p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Effective delta</div>
                  <div className="mt-2 text-3xl font-semibold">{formatMillivolts(result.effective_delta_mv)}</div>
                </div>
                <div className="rounded-lg border p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">Anode to Cathode</div>
                  <div className="mt-2 text-base font-semibold">{result.anode} {'->'} {result.cathode}</div>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="text-xl">Slider</CardTitle>
              <CardDescription>
                Drag the target horizontally toward green. The mitigation tiles update to show what gets the couple there.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="rounded-2xl border bg-slate-950 p-5 text-slate-50">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.18em] text-slate-400">
                  <span>Potential-difference screen</span>
                  <span>{DECISION_BASIS_LABELS[result.decision_basis]}</span>
                </div>
                <div className="mt-6 h-4 rounded-full bg-gradient-to-r from-emerald-500 via-amber-400 to-rose-500" />
                <div className="relative mt-2 h-8">
                  <div
                    className="absolute top-0 -translate-x-1/2"
                    style={{ left: `${currentMarkerPosition}%` }}
                  >
                    <div className="h-8 w-0.5 bg-white/90" />
                    <div className="mt-1 whitespace-nowrap text-xs font-medium">
                      {formatMillivolts(result.effective_delta_mv)}
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex justify-between text-xs text-slate-400">
                  <span>&lt;250 mV compatible</span>
                  <span>250-500 mV caution</span>
                  <span>&gt;500 mV incompatible</span>
                </div>

                <div className="mt-6 rounded-xl border border-slate-700 bg-slate-900/70 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Drag target effective delta</div>
                      <div className="mt-1 text-sm text-slate-300">
                        Pull the target box toward green and the rest of the page updates underneath.
                      </div>
                    </div>
                    <StatusBadge status={targetSeverity} className="border-transparent" />
                  </div>

                  <div className="relative mt-6 h-24">
                    <div className="absolute inset-x-0 top-9 h-4 rounded-full bg-gradient-to-r from-emerald-500 via-amber-400 to-rose-500" />
                    <div
                      className="pointer-events-none absolute top-1 -translate-x-1/2"
                      style={{ left: `${currentMarkerPosition}%` }}
                    >
                      <div className="rounded-lg border border-white/15 bg-slate-800 px-3 py-2 text-center shadow-lg">
                        <div className="text-[11px] uppercase tracking-wide text-slate-400">Current</div>
                        <div className="text-sm font-semibold text-white">{formatMillivolts(result.effective_delta_mv)}</div>
                      </div>
                    </div>

                    <input
                      type="range"
                      min={0}
                      max={targetScaleMax}
                      value={targetDeltaMv}
                      onChange={(event) => setTargetDeltaMv(Number(event.target.value))}
                      className="absolute inset-x-0 top-5 hidden h-14 cursor-ew-resize opacity-0 md:block"
                    />

                    <div
                      className="pointer-events-none absolute top-11 h-0.5 bg-white/40"
                      style={{
                        left: `${Math.min(currentMarkerPosition, targetMarkerPosition)}%`,
                        width: `${Math.abs(currentMarkerPosition - targetMarkerPosition)}%`,
                      }}
                    />

                    <div
                      className="pointer-events-none absolute top-10 -translate-x-1/2"
                      style={{ left: `${targetMarkerPosition}%` }}
                    >
                      <div className={`rounded-xl border px-3 py-2 text-center shadow-lg ${
                        targetSeverity === 'COMPATIBLE'
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-950'
                          : targetSeverity === 'CAUTION'
                            ? 'border-amber-200 bg-amber-50 text-amber-950'
                            : 'border-rose-200 bg-rose-50 text-rose-950'
                      }`}>
                        <div className="text-[11px] uppercase tracking-wide opacity-70">Target box</div>
                        <div className="text-sm font-semibold">{formatMillivolts(targetDeltaMv)}</div>
                      </div>
                    </div>
                  </div>

                  <div className="mt-2 flex justify-between text-xs text-slate-400">
                    <span>Green &lt;250 mV</span>
                    <span>Yellow 250-500 mV</span>
                    <span>Red &gt;500 mV</span>
                  </div>

                  <div className="mt-4 md:hidden">
                    <Label htmlFor="mobile-target-delta" className="text-xs uppercase tracking-[0.18em] text-slate-400">
                      Mobile target control
                    </Label>
                    <input
                      id="mobile-target-delta"
                      type="range"
                      min={0}
                      max={targetScaleMax}
                      value={targetDeltaMv}
                      onChange={(event) => setTargetDeltaMv(Number(event.target.value))}
                      className="mt-3 h-10 w-full accent-white"
                    />
                  </div>
                </div>

                <p className="mt-4 text-sm text-slate-300">{result.screening_disclaimer}</p>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="text-xl">Mitigation Path To Target</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {targetPlan && targetPlan.steps.length > 0 ? (
                <>
                  <div className="rounded-lg border bg-muted/30 p-4 text-sm">
                    Starting at <span className="font-semibold">{formatMillivolts(result.effective_delta_mv)}</span>, this path estimates a landing point of{' '}
                    <span className="font-semibold">{formatMillivolts(targetPlan.remaining_delta_mv)}</span>.
                    {targetPlan.used_circuit_break && (
                      <span className="block mt-2 text-muted-foreground">
                        The final move uses a circuit-breaking mitigation. That is why extreme couples can still be pulled into green.
                      </span>
                    )}
                  </div>

                  <div className="flex gap-4 overflow-x-auto pb-2">
                    {targetPlan.steps.map((step, index) => (
                      <div key={step.mitigation.mitigation_id} className="min-w-[360px] flex-none rounded-xl border p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="flex items-center gap-2">
                              <Badge variant="secondary">Priority {index + 1}</Badge>
                              <Badge variant="outline">{step.mitigation.mitigation_class}</Badge>
                            </div>
                            <div className="mt-2 text-lg font-semibold">{step.mitigation.name}</div>
                          </div>
                          <Badge variant="outline">Estimated {formatMillivolts(step.estimated_delta_mv)}</Badge>
                        </div>

                        <p className="mt-3 text-sm text-muted-foreground">{step.mitigation.description}</p>
                        <p className="mt-3 text-sm">
                          <span className="font-medium">Planning note:</span> {step.planning_note}
                        </p>
                        <p className="mt-2 text-sm">
                          <span className="font-medium">Why it ranked:</span> {step.mitigation.trigger_reason}
                        </p>

                        {step.mitigation.coat_cathode_warning && (
                          <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                            <div className="flex items-start gap-2">
                              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                              <div>
                                <span className="font-semibold">Coat the cathodic member.</span>{' '}
                                Coating the anodic member without controlling the cathode can intensify galvanic attack if the coating is damaged.
                              </div>
                            </div>
                          </div>
                        )}

                        <div className="mt-4 flex flex-wrap gap-2">
                          {step.mitigation.standards.map((standard) => (
                            <Badge key={standard} variant="outline">{standard}</Badge>
                          ))}
                        </div>

                        <div className="mt-4 grid gap-4 md:grid-cols-2">
                          <div>
                            <div className="text-xs uppercase tracking-wide text-muted-foreground">Source clauses</div>
                            <ul className="mt-2 space-y-1 text-sm">
                              {step.mitigation.source_clauses.map((clause) => (
                                <li key={clause}>{clause}</li>
                              ))}
                            </ul>
                          </div>
                          <div>
                            <div className="text-xs uppercase tracking-wide text-muted-foreground">Restrictions / notes</div>
                            <ul className="mt-2 space-y-1 text-sm">
                              {[...step.mitigation.restrictions, ...step.mitigation.notes].map((note) => (
                                <li key={note}>{note}</li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-lg border border-dashed p-4 text-xs text-muted-foreground">
                    Drag interaction is a planning UI. Intrinsic material potentials remain fixed; the target path estimates what protection stack gets the effective delta to the selected value.
                  </div>
                </>
              ) : targetPlan?.can_reach_target ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50/70 p-4 text-sm text-emerald-950">
                  The current configuration is already at or below the selected target. No additional mitigation stack is required.
                </div>
              ) : (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50/70 p-4 text-sm text-emerald-950">
                  No mitigation path is required or available for the selected target.
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="text-xl">Resolved Materials</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {[result.material_a, result.material_b].map((item) => (
                <div key={`${item.canonical_name}-${item.query}`} className="rounded-lg border p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold">{item.canonical_name}</div>
                      <div className="text-xs text-muted-foreground">Input: {item.query}</div>
                    </div>
                    <Badge variant="outline">{item.family}</Badge>
                  </div>
                  <div className="mt-4 grid gap-2 text-sm md:grid-cols-2">
                    <div>
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Chosen state</div>
                      <div className="mt-1 font-medium">{item.chosen_state}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">Representative potential</div>
                      <div className="mt-1 font-medium">{formatMillivolts(item.representative_potential_mv_sce)}</div>
                    </div>
                  </div>
                  <div className="mt-4">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Possible states</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {item.possible_states.map((state) => (
                        <Badge key={`${item.canonical_name}-${state.state}`} variant="secondary">
                          {state.state}: {formatMillivolts(state.representative_potential_mv_sce)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="text-xl">Warnings</CardTitle>
              <CardDescription>Condition-specific cautions generated by the corrosion screen.</CardDescription>
            </CardHeader>
            <CardContent>
              {result.warnings.length ? (
                <div className="space-y-3">
                  {result.warnings.map((warning) => (
                    <div key={warning} className="rounded-lg border border-amber-200 bg-amber-50/70 p-3 text-sm text-amber-950">
                      {warning}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50/70 p-3 text-sm text-emerald-900">
                  No additional warnings were generated for this screening case.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <div className="space-y-6">
        <Card className="border-border/70 bg-muted/20">
          <CardHeader>
            <CardTitle className="text-xl">Phase 1 Dataset</CardTitle>
            <CardDescription>
              Source-backed corrosion seed data loaded into the standalone galvanic module.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {bootLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading reference pack...
              </div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border bg-background p-3">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Series records</div>
                    <div className="mt-1 text-2xl font-semibold">{seriesPayload?.records.length ?? 0}</div>
                  </div>
                  <div className="rounded-lg border bg-background p-3">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Manifest version</div>
                    <div className="mt-1 text-2xl font-semibold">{seriesPayload?.version ?? 'n/a'}</div>
                  </div>
                </div>

                <div className="rounded-lg border bg-background p-4">
                  <div className="text-sm font-medium">Reference environment</div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {seriesPayload?.reference_environment.label} using {seriesPayload?.reference_environment.reference_electrode}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {seriesPayload?.reference_environment.conditions}
                  </p>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="text-xl">Screen Logic</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" />
              <p>The intrinsic material boxes sit on the actual galvanic line using the selected representative potentials.</p>
            </div>
            <div className="flex items-start gap-3">
              <ArrowRightLeft className="mt-0.5 h-4 w-4 text-sky-600" />
              <p>The draggable target box is a mitigation-planning metaphor. It does not claim every protection scheme literally changes intrinsic EMF.</p>
            </div>
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-600" />
              <p>The red/yellow/green bands follow the Phase 1 screening model: green &lt;250 mV, yellow 250-500 mV, red &gt;500 mV.</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
