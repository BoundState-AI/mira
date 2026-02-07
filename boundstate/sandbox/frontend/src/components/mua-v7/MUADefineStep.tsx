import { useState, useEffect, useRef, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
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
  type MaterialResolution,
  type EnvironmentSpec,
  type ProcessParams,
  type InvestigateRequest,
  resolveMaterial,
  investigate,
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
  oxygen_pct: 21,
  pressure_psia: 14.7,
  temp_min_f: 60,
  temp_max_f: 85,
  medium: 'Air',
};

function isProcessSensitive(material: string | null): boolean {
  if (!material) return false;
  const lower = material.toLowerCase();
  return (
    lower.includes('adhesive') ||
    lower.includes('epoxy') ||
    lower.includes('composite') ||
    lower.includes('bond') ||
    lower.includes('potting') ||
    lower.includes('rtvs') ||
    lower.includes('silicone')
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MUADefineStep({ wizard, patchWizard, onNext }: Props) {
  // Material resolution
  const [materialInput, setMaterialInput] = useState(wizard.material ?? '');
  const [resolution, setResolution] = useState<MaterialResolution | null>(null);
  const [resolving, setResolving] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Environment
  const [env, setEnv] = useState<EnvironmentSpec>(
    wizard.environment ?? {
      oxygen_pct: 21,
      pressure_psia: 14.7,
      temp_min_f: 60,
      temp_max_f: 85,
      medium: 'Air',
      location: 'habitable',
    },
  );

  // Process params
  const [process, setProcess] = useState<ProcessParams>(
    wizard.processParams ?? {
      cure_temp_f: null,
      cure_time_hrs: null,
      post_cure_temp_f: null,
      bond_area_sqin: null,
      substrate_material: null,
    },
  );

  // Optional metadata
  const [appDesc, setAppDesc] = useState(wizard.applicationDescription ?? '');
  const [program, setProgram] = useState(wizard.program ?? '');
  const [hardware, setHardware] = useState(wizard.hardware ?? '');
  const [miulRef, setMiulRef] = useState(wizard.miulRef ?? '');

  // Submission
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounced material resolution
  const doResolve = useCallback(async (query: string) => {
    if (query.trim().length < 2) {
      setResolution(null);
      return;
    }
    setResolving(true);
    try {
      const { resolution: r } = await resolveMaterial(query.trim());
      setResolution(r);
    } catch {
      setResolution(null);
    } finally {
      setResolving(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doResolve(materialInput), 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [materialInput, doResolve]);

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
  const enrichedO2 = env.oxygen_pct >= 23.5;
  const cryogenic = env.temp_min_f <= -150;
  const hydrogenService = env.medium === 'Hydrogen';
  const showProcess = isProcessSensitive(materialInput);

  // Validation
  const materialOk = resolution?.status === 'resolved' || resolution?.status === 'fuzzy';
  const envOk = env.oxygen_pct > 0 && env.pressure_psia > 0 && env.temp_max_f > env.temp_min_f;
  const canSubmit = materialOk && envOk && !submitting;

  // Submit
  const handleInvestigate = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const req: InvestigateRequest = {
        session_id: wizard.sessionId,
        material: resolution?.resolved_name ?? materialInput.trim(),
        environment: env,
        process_params: showProcess ? process : undefined,
        application_description: appDesc || undefined,
        program: program || undefined,
        hardware: hardware || undefined,
        miul_ref: miulRef || undefined,
      };
      const result = await investigate(req);
      patchWizard({
        sessionId: result.session_id,
        material: req.material,
        environment: env,
        processParams: showProcess ? process : null,
        applicationDescription: appDesc || null,
        program: program || null,
        hardware: hardware || null,
        miulRef: miulRef || null,
        investigation: result.investigation,
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
                onChange={(e) => setMaterialInput(e.target.value)}
              />
              <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5">
                {resolving && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
                {!resolving && resolutionIcon}
              </div>
            </div>
            {resolution && (
              <div className="text-sm">
                {resolution.status === 'resolved' && (
                  <span className="text-green-700">
                    Resolved: {resolution.resolved_name}
                    {resolution.resolved_spec && ` (${resolution.resolved_spec})`}
                  </span>
                )}
                {resolution.status === 'fuzzy' && (
                  <div className="space-y-1">
                    <span className="text-yellow-700">
                      Possible match: {resolution.resolved_name ?? 'Multiple candidates'}
                    </span>
                    {resolution.candidates.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {resolution.candidates.slice(0, 5).map((c) => (
                          <Badge
                            key={c.spec}
                            variant="outline"
                            className="cursor-pointer hover:bg-accent"
                            onClick={() => {
                              setMaterialInput(c.name);
                            }}
                          >
                            {c.name} ({c.spec})
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {resolution.status === 'unresolved' && (
                  <span className="text-red-600">
                    Material not found in database.
                    {resolution.warnings.length > 0 && ` ${resolution.warnings[0]}`}
                  </span>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Environment */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Wind className="h-5 w-5" />
            Use Environment
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="o2" className="flex items-center gap-1">
                <Gauge className="h-3.5 w-3.5" /> O2 %
              </Label>
              <Input
                id="o2"
                type="number"
                step="0.1"
                value={env.oxygen_pct}
                onChange={(e) => patchEnv({ oxygen_pct: parseFloat(e.target.value) || 0 })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="press">Pressure (PSIA)</Label>
              <Input
                id="press"
                type="number"
                step="0.1"
                value={env.pressure_psia}
                onChange={(e) => patchEnv({ pressure_psia: parseFloat(e.target.value) || 0 })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tmin" className="flex items-center gap-1">
                <Thermometer className="h-3.5 w-3.5" /> Temp Min (F)
              </Label>
              <Input
                id="tmin"
                type="number"
                value={env.temp_min_f}
                onChange={(e) => patchEnv({ temp_min_f: parseFloat(e.target.value) || 0 })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tmax">Temp Max (F)</Label>
              <Input
                id="tmax"
                type="number"
                value={env.temp_max_f}
                onChange={(e) => patchEnv({ temp_max_f: parseFloat(e.target.value) || 0 })}
              />
            </div>
          </div>

          {/* Medium select */}
          <div className="space-y-1.5 max-w-xs">
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

          {/* Warning banners */}
          {enrichedO2 && (
            <Alert className="border-orange-300 bg-orange-50">
              <Flame className="h-4 w-4 text-orange-600" />
              <AlertTitle className="text-orange-800">Enriched Oxygen Environment</AlertTitle>
              <AlertDescription className="text-orange-700">
                O2 concentration >= 23.5%. Additional flammability testing per NASA-STD-6001B Test 1
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
                <Label>Cure Time (hrs)</Label>
                <Input
                  type="number"
                  step="0.5"
                  value={process.cure_time_hrs ?? ''}
                  onChange={(e) =>
                    patchProc({ cure_time_hrs: e.target.value ? parseFloat(e.target.value) : null })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Post-Cure Temp (F)</Label>
                <Input
                  type="number"
                  value={process.post_cure_temp_f ?? ''}
                  onChange={(e) =>
                    patchProc({
                      post_cure_temp_f: e.target.value ? parseFloat(e.target.value) : null,
                    })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Bond Area (sq in)</Label>
                <Input
                  type="number"
                  step="0.1"
                  value={process.bond_area_sqin ?? ''}
                  onChange={(e) =>
                    patchProc({
                      bond_area_sqin: e.target.value ? parseFloat(e.target.value) : null,
                    })
                  }
                />
              </div>
              <div className="space-y-1.5 col-span-2">
                <Label>Substrate Material</Label>
                <Input
                  value={process.substrate_material ?? ''}
                  onChange={(e) =>
                    patchProc({ substrate_material: e.target.value || null })
                  }
                  placeholder="e.g. Aluminum 6061-T6"
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
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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
