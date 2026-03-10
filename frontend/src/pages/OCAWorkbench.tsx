import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Slider } from '@/components/ui/slider';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import {
  Loader2, AlertTriangle, CheckCircle, XCircle, Shield, Flame,
  FileText, Download, ChevronRight, Info, Zap,
} from 'lucide-react';
import {
  ocaCreateCase, ocaRunDecision, ocaAdiabaticCalc,
  type OCACreateCaseRequest, type OCADecisionResponse, type OCADecisionPacket,
  type OCAMechanismTrace, type OCATriggeredRequirement, type OCABlockedState,
  type OCAHazardControl, type OCAAdiabaticResult,
  type OCAOxidizerType, type OCAPhase, type OCAFlowRegime, type OCAMissionPhase,
  type OCAComponentClass, type OCAGeometryClass, type OCAFlammabilityRating,
  type OCACredibleStatus, type OCAReactionEffect, type OCADisposition, type OCARuleTier,
} from '@/lib/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TIER_COLORS: Record<OCARuleTier, string> = {
  A: 'bg-red-700 text-white',
  B: 'bg-blue-700 text-white',
  C: 'bg-emerald-700 text-white',
  D: 'bg-amber-600 text-white',
};

const DISPOSITION_LABELS: Record<OCADisposition, { label: string; color: string }> = {
  compatible_as_configured: { label: 'Compatible As Configured', color: 'bg-emerald-600 text-white' },
  compatible_with_controls: { label: 'Compatible With Controls', color: 'bg-amber-500 text-black' },
  requires_mua: { label: 'Requires MUA', color: 'bg-orange-600 text-white' },
  requires_acceptance_test: { label: 'Requires Acceptance Test', color: 'bg-orange-600 text-white' },
  requires_supplemental_testing: { label: 'Requires Supplemental Testing', color: 'bg-red-600 text-white' },
  insufficient_evidence: { label: 'Insufficient Evidence', color: 'bg-red-800 text-white' },
};

const REACTION_COLORS: Record<OCAReactionEffect, string> = {
  A: 'bg-emerald-600 text-white',
  B: 'bg-amber-500 text-black',
  C: 'bg-orange-600 text-white',
  D: 'bg-red-700 text-white',
};

const REACTION_LABELS: Record<OCAReactionEffect, string> = {
  A: 'A — Negligible',
  B: 'B — Marginal',
  C: 'C — Critical',
  D: 'D — Catastrophic',
};

function credibleBadge(status: OCACredibleStatus) {
  if (status === 'credible') return <Badge className="bg-red-600 text-white text-[10px]">CREDIBLE</Badge>;
  if (status === 'indeterminate') return <Badge className="bg-amber-500 text-black text-[10px]">INDETERMINATE</Badge>;
  return <Badge variant="outline" className="text-[10px]">NOT CREDIBLE</Badge>;
}

function ratingBar(rating: number) {
  const segments = Array.from({ length: 5 }, (_, i) => (
    <div
      key={i}
      className={`h-2 w-5 rounded-sm ${
        i < rating
          ? rating >= 4 ? 'bg-red-600' : rating >= 3 ? 'bg-orange-500' : 'bg-amber-400'
          : 'bg-gray-700'
      }`}
    />
  ));
  return <div className="flex gap-0.5 items-center">{segments}<span className="ml-1 text-xs text-muted-foreground">{rating}/4</span></div>;
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function OCAWorkbench() {
  // --- Form state ---
  const [materialName, setMaterialName] = useState('');
  const [materialSpec, setMaterialSpec] = useState('');
  const [flammabilityRating, setFlammabilityRating] = useState<OCAFlammabilityRating>('unknown');
  const [isTitanium, setIsTitanium] = useState(false);
  const [isNonmetal, setIsNonmetal] = useState(false);
  const [oxidizerType, setOxidizerType] = useState<OCAOxidizerType>('gox');
  const [o2Fraction, setO2Fraction] = useState(1.0);
  const [pressureMin, setPressureMin] = useState(14.7);
  const [pressureMax, setPressureMax] = useState(3000);
  const [phase, setPhase] = useState<OCAPhase>('gas');
  const [flowRegime, setFlowRegime] = useState<OCAFlowRegime>('static');
  const [velocity, setVelocity] = useState<number | null>(null);
  const [missionPhase, setMissionPhase] = useState<OCAMissionPhase>('ground_test');
  const [cleanlinessVerified, setCleanlinessVerified] = useState(false);
  const [componentClass, setComponentClass] = useState<OCAComponentClass>('other');
  const [geometryClass, setGeometryClass] = useState<OCAGeometryClass>('bulk');
  const [dynamicContact, setDynamicContact] = useState(false);
  const [isRigidTubing, setIsRigidTubing] = useState(false);
  const [isFlexHose, setIsFlexHose] = useState(false);
  const [isAllMetalSeal, setIsAllMetalSeal] = useState(false);
  const [isPressureVessel, setIsPressureVessel] = useState(false);

  // --- Assessment state ---
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<OCADecisionPacket | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);

  // --- Adiabatic calc state ---
  const [adiabaticResult, setAdiabaticResult] = useState<OCAAdiabaticResult | null>(null);
  const [adiabaticLoading, setAdiabaticLoading] = useState(false);

  // ---------------------------------------------------------------------------
  // Run Assessment
  // ---------------------------------------------------------------------------

  const runAssessment = useCallback(async () => {
    if (!materialName.trim()) {
      setError('Material name is required.');
      return;
    }

    setLoading(true);
    setError(null);
    setDecision(null);

    try {
      const req: OCACreateCaseRequest = {
        service_context: {
          oxidizer_type: oxidizerType,
          o2_fraction: o2Fraction,
          total_pressure_min_psia: pressureMin,
          total_pressure_max_psia: pressureMax,
          phase,
          flow_regime: flowRegime,
          velocity_m_s: velocity,
          cleanliness_verified: cleanlinessVerified,
          mission_phase: missionPhase,
        },
        component: {
          component_class: componentClass,
          geometry_class: geometryClass,
          dynamic_contact_flag: dynamicContact,
          is_rigid_metallic_tubing: isRigidTubing,
          is_metallic_flex_hose: isFlexHose,
          is_all_metal_seal: isAllMetalSeal,
          is_metallic_pressure_vessel: isPressureVessel,
        },
        materials: [
          {
            material_name: materialName,
            spec: materialSpec || null,
            identity_confidence: 0.9,
            flammability_rating: flammabilityRating,
            is_titanium: isTitanium,
            is_nonmetal: isNonmetal,
          },
        ],
      };

      // Step 1: Create case
      const caseResp = await ocaCreateCase(req);
      setCaseId(caseResp.case_id);

      // Step 2: Run full decision
      const decisionResp = await ocaRunDecision(caseResp.case_id);
      setDecision(decisionResp.decision);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Assessment failed');
    } finally {
      setLoading(false);
    }
  }, [
    materialName, materialSpec, flammabilityRating, isTitanium, isNonmetal,
    oxidizerType, o2Fraction, pressureMin, pressureMax, phase,
    flowRegime, velocity, missionPhase, cleanlinessVerified,
    componentClass, geometryClass, dynamicContact,
    isRigidTubing, isFlexHose, isAllMetalSeal, isPressureVessel,
  ]);

  // ---------------------------------------------------------------------------
  // Adiabatic Calc
  // ---------------------------------------------------------------------------

  const runAdiabaticCalc = useCallback(async () => {
    setAdiabaticLoading(true);
    try {
      const result = await ocaAdiabaticCalc(293.15, 14.7, pressureMax);
      setAdiabaticResult(result);
    } catch {
      // ignore
    } finally {
      setAdiabaticLoading(false);
    }
  }, [pressureMax]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="max-w-5xl mx-auto space-y-4 p-4">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">OCA Workbench</h1>
          <p className="text-sm text-muted-foreground">
            Oxygen Compatibility Assessment per NASA/TM-2007-213740
          </p>
        </div>
        <Badge variant="outline" className="text-xs">BS-SPEC-OCA-001-REV1</Badge>
      </div>

      {/* Disclaimer */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription className="text-xs">
          Screening aid only. Formal OCA requires M&P organization concurrence per FOCR 37.
          This tool does not constitute an approved OCA.
        </AlertDescription>
      </Alert>

      {/* ================================================================= */}
      {/* TILE 1: Assessment Input */}
      {/* ================================================================= */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Assessment Input</CardTitle>
          <CardDescription>Define service context, component, and materials (Step 1: Worst-Case Conditions)</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="material" className="w-full">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="material">Material</TabsTrigger>
              <TabsTrigger value="environment">Environment</TabsTrigger>
              <TabsTrigger value="component">Component</TabsTrigger>
            </TabsList>

            {/* --- Material Tab --- */}
            <TabsContent value="material" className="space-y-3 mt-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Material Name</Label>
                  <Input
                    placeholder="e.g., INCONEL 718, PTFE, Ti-6Al-4V"
                    value={materialName}
                    onChange={e => setMaterialName(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Specification</Label>
                  <Input
                    placeholder="e.g., AMS 5666"
                    value={materialSpec}
                    onChange={e => setMaterialSpec(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Flammability Rating</Label>
                  <Select value={flammabilityRating} onValueChange={v => setFlammabilityRating(v as OCAFlammabilityRating)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="A">A — Nonflammable</SelectItem>
                      <SelectItem value="B">B — Self-extinguishing</SelectItem>
                      <SelectItem value="C">C — Flammable (slow)</SelectItem>
                      <SelectItem value="D">D — Flammable (rapid)</SelectItem>
                      <SelectItem value="X">X — Not tested</SelectItem>
                      <SelectItem value="unknown">Unknown</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end gap-4 col-span-2">
                  <div className="flex items-center gap-2">
                    <Switch checked={isTitanium} onCheckedChange={setIsTitanium} id="titanium" />
                    <Label htmlFor="titanium" className="text-xs">Titanium Alloy</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch checked={isNonmetal} onCheckedChange={setIsNonmetal} id="nonmetal" />
                    <Label htmlFor="nonmetal" className="text-xs">Nonmetal</Label>
                  </div>
                </div>
              </div>
              {isTitanium && (
                <Alert variant="destructive">
                  <XCircle className="h-4 w-4" />
                  <AlertTitle className="text-sm font-semibold">MPR 67 — Titanium Prohibition (Tier A)</AlertTitle>
                  <AlertDescription className="text-xs">
                    Titanium alloys SHALL NOT be used with LOX or GOX at any pressure, or with air
                    above 5 psia O2 partial pressure. Per NASA-STD-6016C §4.2.1.3c.
                  </AlertDescription>
                </Alert>
              )}
            </TabsContent>

            {/* --- Environment Tab --- */}
            <TabsContent value="environment" className="space-y-3 mt-3">
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Oxidizer Type</Label>
                  <Select value={oxidizerType} onValueChange={v => setOxidizerType(v as OCAOxidizerType)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="gox">GOX (Gaseous O2)</SelectItem>
                      <SelectItem value="lox">LOX (Liquid O2)</SelectItem>
                      <SelectItem value="enriched_air">Enriched Air</SelectItem>
                      <SelectItem value="compressed_air">Compressed Air</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Phase</Label>
                  <Select value={phase} onValueChange={v => setPhase(v as OCAPhase)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="gas">Gas</SelectItem>
                      <SelectItem value="liquid">Liquid</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Mission Phase</Label>
                  <Select value={missionPhase} onValueChange={v => setMissionPhase(v as OCAMissionPhase)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ground_test">Ground Test</SelectItem>
                      <SelectItem value="ascent">Ascent</SelectItem>
                      <SelectItem value="on_orbit">On-Orbit</SelectItem>
                      <SelectItem value="servicing">Servicing</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">O2 Fraction ({(o2Fraction * 100).toFixed(0)}%)</Label>
                  <Slider
                    min={21} max={100} step={1}
                    value={[o2Fraction * 100]}
                    onValueChange={([v]) => setO2Fraction(v / 100)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Max Pressure (psia)</Label>
                  <Input
                    type="number" min={0}
                    value={pressureMax}
                    onChange={e => setPressureMax(Number(e.target.value))}
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Flow Regime</Label>
                  <Select value={flowRegime} onValueChange={v => setFlowRegime(v as OCAFlowRegime)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="static">Static</SelectItem>
                      <SelectItem value="laminar">Laminar</SelectItem>
                      <SelectItem value="turbulent">Turbulent</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Flow Velocity (m/s)</Label>
                  <Input
                    type="number" min={0}
                    placeholder="Optional"
                    value={velocity ?? ''}
                    onChange={e => setVelocity(e.target.value ? Number(e.target.value) : null)}
                  />
                </div>
                <div className="flex items-end">
                  <div className="flex items-center gap-2">
                    <Switch checked={cleanlinessVerified} onCheckedChange={setCleanlinessVerified} id="clean" />
                    <Label htmlFor="clean" className="text-xs">Cleanliness Verified</Label>
                  </div>
                </div>
              </div>
              {pressureMax > 265 && (oxidizerType === 'gox' || oxidizerType === 'enriched_air') && (
                <Alert>
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription className="text-xs">
                    <strong>MPR 53:</strong> GOX/enriched-air above 265 psia triggers acceptance testing
                    requirement (10 cycles, ambient to MDP within 100 ms) unless component is exempt.
                  </AlertDescription>
                </Alert>
              )}
            </TabsContent>

            {/* --- Component Tab --- */}
            <TabsContent value="component" className="space-y-3 mt-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Component Class</Label>
                  <Select value={componentClass} onValueChange={v => setComponentClass(v as OCAComponentClass)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="valve">Valve</SelectItem>
                      <SelectItem value="regulator">Regulator</SelectItem>
                      <SelectItem value="line">Line/Tube</SelectItem>
                      <SelectItem value="vessel">Vessel</SelectItem>
                      <SelectItem value="seal">Seal</SelectItem>
                      <SelectItem value="filter">Filter</SelectItem>
                      <SelectItem value="sensor">Sensor</SelectItem>
                      <SelectItem value="fitting">Fitting</SelectItem>
                      <SelectItem value="flex_hose">Flex Hose</SelectItem>
                      <SelectItem value="other">Other</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Geometry Class</Label>
                  <Select value={geometryClass} onValueChange={v => setGeometryClass(v as OCAGeometryClass)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="bulk">Bulk</SelectItem>
                      <SelectItem value="thin_wall">Thin Wall</SelectItem>
                      <SelectItem value="mesh">Mesh</SelectItem>
                      <SelectItem value="porous">Porous</SelectItem>
                      <SelectItem value="sintered">Sintered</SelectItem>
                      <SelectItem value="seal">Seal</SelectItem>
                      <SelectItem value="other">Other</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex flex-wrap gap-4">
                <div className="flex items-center gap-2">
                  <Switch checked={dynamicContact} onCheckedChange={setDynamicContact} id="dynamic" />
                  <Label htmlFor="dynamic" className="text-xs">Moving Parts</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={isRigidTubing} onCheckedChange={setIsRigidTubing} id="rigid" />
                  <Label htmlFor="rigid" className="text-xs">Rigid Metallic Tubing</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={isFlexHose} onCheckedChange={setIsFlexHose} id="flex" />
                  <Label htmlFor="flex" className="text-xs">Metallic Flex Hose</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={isAllMetalSeal} onCheckedChange={setIsAllMetalSeal} id="metalseal" />
                  <Label htmlFor="metalseal" className="text-xs">All-Metal Seal</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={isPressureVessel} onCheckedChange={setIsPressureVessel} id="vessel" />
                  <Label htmlFor="vessel" className="text-xs">Metallic Pressure Vessel</Label>
                </div>
              </div>
            </TabsContent>
          </Tabs>

          {/* Run Button */}
          <div className="mt-4 flex items-center gap-3">
            <Button onClick={runAssessment} disabled={loading} className="gap-2">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              Run OCA Assessment
            </Button>
            <Button variant="outline" size="sm" onClick={runAdiabaticCalc} disabled={adiabaticLoading}>
              {adiabaticLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Flame className="h-3 w-3" />}
              <span className="ml-1 text-xs">Adiabatic Calc</span>
            </Button>
          </div>

          {adiabaticResult && (
            <div className="mt-2 p-2 rounded bg-muted text-xs font-mono">
              Tf = {adiabaticResult.tf_k.toFixed(1)} K ({adiabaticResult.tf_c.toFixed(1)}°C / {adiabaticResult.tf_f.toFixed(1)}°F)
              &nbsp;| Pi={adiabaticResult.pi_psia} → Pf={adiabaticResult.pf_psia} psia
            </div>
          )}
        </CardContent>
      </Card>

      {/* Error */}
      {error && (
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Loading */}
      {loading && (
        <Card>
          <CardContent className="flex items-center gap-3 py-8 justify-center">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm text-muted-foreground">Running 7-step OCA pipeline...</span>
          </CardContent>
        </Card>
      )}

      {/* ================================================================= */}
      {/* RESULTS TILES (only shown after assessment) */}
      {/* ================================================================= */}
      {decision && (
        <>
          {/* TILE 2: Blocked States */}
          {decision.blocked_states.length > 0 && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Blocked States</AlertTitle>
              <AlertDescription>
                {decision.blocked_states.map((b, i) => (
                  <div key={i} className="mt-1">
                    <strong className="uppercase text-xs">{b.state_type.replace(/_/g, ' ')}</strong>
                    <p className="text-xs">{b.description}</p>
                    <p className="text-xs text-muted-foreground">{b.resolution_hint}</p>
                  </div>
                ))}
              </AlertDescription>
            </Alert>
          )}

          {/* TILE 3: Assessment Result */}
          <Card>
            <CardHeader className="pb-2 bg-card border-b">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base flex items-center gap-2">
                  <Shield className="h-4 w-4" />
                  Assessment Result
                </CardTitle>
                <Badge className={DISPOSITION_LABELS[decision.final_disposition]?.color || 'bg-gray-600 text-white'}>
                  {DISPOSITION_LABELS[decision.final_disposition]?.label || decision.final_disposition}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="pt-3 space-y-3">
              <p className="text-sm">{decision.summary_rationale}</p>

              {/* Triggered Requirements */}
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Triggered Requirements</p>
                <div className="flex flex-wrap gap-1.5">
                  {decision.triggered_requirements.map((r, i) => (
                    <Badge
                      key={i}
                      variant={r.is_prohibition ? 'destructive' : r.satisfied ? 'default' : 'secondary'}
                      className="text-[10px] gap-1"
                    >
                      <span className={`inline-block w-4 text-center rounded text-[8px] font-bold ${TIER_COLORS[r.tier]}`}>
                        {r.tier}
                      </span>
                      {r.requirement_id}
                      {r.is_prohibition && ' — PROHIBITION'}
                      {r.satisfied && <CheckCircle className="h-3 w-3" />}
                    </Badge>
                  ))}
                  {decision.triggered_requirements.length === 0 && (
                    <span className="text-xs text-muted-foreground">None</span>
                  )}
                </div>
              </div>

              {/* Reaction Effect + Stats */}
              <div className="grid grid-cols-4 gap-2">
                <div className="p-2 rounded bg-muted text-center">
                  <p className="text-[10px] text-muted-foreground uppercase">Reaction Effect</p>
                  <Badge className={`mt-1 ${REACTION_COLORS[decision.reaction_effect]}`}>
                    {REACTION_LABELS[decision.reaction_effect]}
                  </Badge>
                </div>
                <div className="p-2 rounded bg-muted text-center">
                  <p className="text-[10px] text-muted-foreground uppercase">Kindling Chain</p>
                  <p className="text-sm font-semibold mt-1">{decision.kindling_chain_present ? 'Present' : 'No'}</p>
                </div>
                <div className="p-2 rounded bg-muted text-center">
                  <p className="text-[10px] text-muted-foreground uppercase">Accept. Test</p>
                  <p className="text-sm font-semibold mt-1">{decision.acceptance_test_required ? 'Required' : 'No'}</p>
                </div>
                <div className="p-2 rounded bg-muted text-center">
                  <p className="text-[10px] text-muted-foreground uppercase">Gaps</p>
                  <p className="text-sm font-semibold mt-1">{decision.unresolved_gaps.length}</p>
                </div>
              </div>

              {/* Prohibition details */}
              {decision.triggered_requirements.filter(r => r.is_prohibition).map((r, i) => (
                <Alert key={i} variant="destructive">
                  <XCircle className="h-4 w-4" />
                  <AlertTitle className="text-sm">{r.requirement_id}: {r.title}</AlertTitle>
                  <AlertDescription className="text-xs">{r.prohibition_detail}</AlertDescription>
                </Alert>
              ))}
            </CardContent>
          </Card>

          {/* TILE 4: Ignition Mechanisms */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Flame className="h-4 w-4" />
                Ignition Mechanisms (12 per TM-2007-213740)
              </CardTitle>
              <CardDescription>
                {decision.mechanism_assessments.filter(m => m.credible_status === 'credible').length} credible,{' '}
                {decision.mechanism_assessments.filter(m => m.credible_status === 'indeterminate').length} indeterminate,{' '}
                {decision.mechanism_assessments.filter(m => m.credible_status === 'not_credible').length} not credible
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Accordion type="multiple" className="w-full">
                {decision.mechanism_assessments.map((m, i) => (
                  <AccordionItem key={i} value={m.mechanism_name}>
                    <AccordionTrigger className="py-2 hover:no-underline">
                      <div className="flex items-center gap-3 w-full pr-4">
                        <span className="text-sm font-medium capitalize w-44 text-left">
                          {m.mechanism_name.replace(/_/g, ' ')}
                        </span>
                        {credibleBadge(m.credible_status)}
                        {ratingBar(m.rating)}
                        <span className="text-[10px] text-muted-foreground ml-auto">{m.source_ref}</span>
                      </div>
                    </AccordionTrigger>
                    <AccordionContent className="pb-3">
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div>
                          <p className="font-medium text-muted-foreground mb-1">Required Elements</p>
                          <ul className="space-y-0.5">
                            {m.required_elements.map((el, j) => (
                              <li key={j} className="flex items-center gap-1">
                                {m.observed_elements.includes(el)
                                  ? <CheckCircle className="h-3 w-3 text-emerald-500" />
                                  : <XCircle className="h-3 w-3 text-muted-foreground" />
                                }
                                <span className={m.observed_elements.includes(el) ? '' : 'text-muted-foreground'}>
                                  {el.replace(/_/g, ' ')}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <p className="font-medium text-muted-foreground mb-1">Missing Elements</p>
                          {m.missing_elements.length > 0 ? (
                            <ul className="space-y-0.5">
                              {m.missing_elements.map((el, j) => (
                                <li key={j} className="text-amber-500">{el.replace(/_/g, ' ')}</li>
                              ))}
                            </ul>
                          ) : (
                            <p className="text-muted-foreground">All elements observed</p>
                          )}
                        </div>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </CardContent>
          </Card>

          {/* TILE 5: Kindling Chain & Reaction Effect */}
          {decision.kindling_chain && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Kindling Chain & Reaction Effect</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center gap-2">
                  <Badge className={decision.kindling_chain.kindling_chain_present ? 'bg-red-600 text-white' : 'bg-emerald-600 text-white'}>
                    {decision.kindling_chain.kindling_chain_present ? 'Kindling Chain Present' : 'No Kindling Chain'}
                  </Badge>
                  <Badge className={REACTION_COLORS[decision.kindling_chain.reaction_effect]}>
                    {REACTION_LABELS[decision.kindling_chain.reaction_effect]}
                  </Badge>
                </div>
                <p className="text-sm">{decision.kindling_chain.rationale}</p>
                {decision.kindling_chain.propagation_path.length > 0 && (
                  <div className="flex items-center gap-1 flex-wrap">
                    {decision.kindling_chain.propagation_path.map((p, i) => (
                      <span key={i} className="flex items-center gap-1">
                        {i > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground" />}
                        <Badge variant="outline" className="text-[10px]">{p}</Badge>
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* TILE 6: Hazard Controls */}
          {decision.hazard_controls.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Hazard Control Table (TM Table 4)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="text-left py-1 pr-2">Hazard</th>
                        <th className="text-left py-1 pr-2">Rating</th>
                        <th className="text-left py-1 pr-2">Recommendation</th>
                        <th className="text-left py-1 pr-2">Class</th>
                        <th className="text-left py-1">Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {decision.hazard_controls.map((hc, i) => (
                        <tr key={i} className="border-b border-border/50">
                          <td className="py-1.5 pr-2 capitalize">{hc.ignition_hazard.replace(/_/g, ' ')}</td>
                          <td className="py-1.5 pr-2">{ratingBar(hc.probability_rating)}</td>
                          <td className="py-1.5 pr-2">{hc.recommendation}</td>
                          <td className="py-1.5 pr-2">
                            <Badge variant="outline" className="text-[9px]">{hc.recommendation_class.replace(/_/g, ' ')}</Badge>
                          </td>
                          <td className="py-1.5">{hc.confidence}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* TILE 7: Evidence Gaps */}
          {decision.unresolved_gaps.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500" />
                  Evidence Gaps
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1">
                  {decision.unresolved_gaps.map((g, i) => (
                    <li key={i} className="text-sm text-amber-200 flex items-start gap-2">
                      <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
                      {g}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {/* TILE 8: MUA Seed */}
          {decision.mua_seed && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  MUA Seed (Pre-Population Packet)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <p className="text-xs text-muted-foreground">Material Identity</p>
                    <p>{decision.mua_seed.material_identity}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Service Conditions</p>
                    <p>{decision.mua_seed.service_conditions}</p>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Trigger Reason</p>
                  <p>{decision.mua_seed.trigger_reason}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Rationale Draft</p>
                  <p className="text-xs">{decision.mua_seed.rationale_draft}</p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* TILE 9: Export */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Disposition & Export</CardTitle>
            </CardHeader>
            <CardContent className="flex items-center gap-3">
              <Badge className={DISPOSITION_LABELS[decision.final_disposition]?.color || ''}>
                {DISPOSITION_LABELS[decision.final_disposition]?.label}
              </Badge>
              <span className="text-xs text-muted-foreground">Case: {decision.case_id.slice(0, 8)}...</span>
              <div className="ml-auto flex gap-2">
                <Button variant="outline" size="sm" className="gap-1 text-xs" onClick={() => {
                  const blob = new Blob([JSON.stringify(decision, null, 2)], { type: 'application/json' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `oca-${decision.case_id.slice(0, 8)}.json`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}>
                  <Download className="h-3 w-3" />
                  Export JSON
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
