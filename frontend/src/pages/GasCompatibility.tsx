import { useState, useEffect } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { StatusBadge } from '@/components/StatusBadge';
import { EvidenceTable } from '@/components/EvidenceTable';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Loader2, Search, BookOpen, Layers, AlertTriangle, CheckCircle, XCircle } from 'lucide-react';
import {
  checkO2Compatibility,
  checkH2Compatibility,
  getH2Conditions,
  getH2ConditionAliases,
  verifyH2ConditionAlias,
  o2Evaluate,
  o2SearchBOK,
  o2GetFamilies,
  type CompatibilityResponse,
  type H2ConditionAliasRecord,
  type H2ConditionOption,
  type H2ConditionLookupResponse,
  type O2EvaluateResponse,
  type O2BOKSearchResponse,
  type O2FamiliesResponse,
} from '@/lib/api';
import helpContent from '@/config/helpContent';

type GasType = 'O2' | 'H2';
type H2DecisionBand = 'prohibited' | 'judgement' | 'mixed' | 'none';

function extractEngineeringReviewBullets(rationale?: string | null): {
  rationaleWithoutReview: string;
  bullets: string[];
} {
  const text = (rationale || '').trim();
  if (!text) return { rationaleWithoutReview: '', bullets: [] };

  const headingRegex = /the following engineering review is suggested:?/i;
  const match = headingRegex.exec(text);
  if (!match || match.index < 0) return { rationaleWithoutReview: text, bullets: [] };

  const before = text.slice(0, match.index).trim();
  const after = text.slice(match.index + match[0].length).trim();
  const bullets: string[] = [];

  const lines = after.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  for (const line of lines) {
    if (/^[-*•]\s+/.test(line)) {
      bullets.push(line.replace(/^[-*•]\s+/, '').trim());
    }
  }
  if (!bullets.length && after.includes('•')) {
    for (const part of after.split('•')) {
      const item = part.trim();
      if (item) bullets.push(item);
    }
  }

  return { rationaleWithoutReview: before || text, bullets };
}

function parseH2DecisionBand(result: CompatibilityResponse | null): {
  band: H2DecisionBand;
  detail?: string;
} {
  if (!result) return { band: 'none' };
  const text = `${result.notes || ''} ${result.rationale || ''}`.toLowerCase();
  const detailMatch = /h2\/he ratio screen:[^.]+/i.exec(`${result.notes || ''} ${result.rationale || ''}`);
  const detail = detailMatch?.[0]?.trim();

  if (text.includes('<=0.75 threshold')) return { band: 'prohibited', detail };
  if (text.includes('>=0.76; engineering judgement required')) return { band: 'judgement', detail };
  if (text.includes('crosses 0.75/0.76 threshold')) return { band: 'mixed', detail };
  return { band: 'none', detail };
}

export default function GasCompatibility() {
  const [gasType, setGasType] = useState<GasType>('O2');
  const [h2Condition, setH2Condition] = useState('');
  const [lastEvaluatedH2Condition, setLastEvaluatedH2Condition] = useState('');
  const [materialKey, setMaterialKey] = useState('');
  const [pressure, setPressure] = useState('');
  const [temperature, setTemperature] = useState('');
  const [phase, setPhase] = useState<'gox' | 'lox'>('gox');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CompatibilityResponse | null>(null);
  const [o2Result, setO2Result] = useState<O2EvaluateResponse | null>(null);
  const [conditionLookupLoading, setConditionLookupLoading] = useState(false);
  const [conditionLookup, setConditionLookup] = useState<H2ConditionLookupResponse | null>(null);
  const [aliasReviewLoading, setAliasReviewLoading] = useState(false);
  const [aliasReviewRows, setAliasReviewRows] = useState<H2ConditionAliasRecord[]>([]);
  const [aliasReviewDrafts, setAliasReviewDrafts] = useState<Record<string, { display: string; canonical: string }>>({});
  const [aliasSaveLoadingKey, setAliasSaveLoadingKey] = useState<string | null>(null);

  // O2 BOK Search state
  const [bokQuery, setBokQuery] = useState('');
  const [bokLoading, setBokLoading] = useState(false);
  const [bokResults, setBokResults] = useState<O2BOKSearchResponse | null>(null);

  // O2 Families state
  const [familiesLoading, setFamiliesLoading] = useState(false);
  const [families, setFamilies] = useState<O2FamiliesResponse | null>(null);

  // Load families on mount
  useEffect(() => {
    loadFamilies();
  }, []);

  // H2 condition lookup when material changes
  useEffect(() => {
    setH2Condition('');
    if (gasType !== 'H2') {
      setConditionLookup(null);
      setConditionLookupLoading(false);
      return;
    }

    const material = materialKey.trim();
    if (material.length < 2) {
      setConditionLookup(null);
      setConditionLookupLoading(false);
      return;
    }

    let cancelled = false;
    setConditionLookupLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const data = await getH2Conditions(material);
        if (!cancelled) {
          setConditionLookup(data);
          // Auto-select when there's only one condition
          const opts = (data.available_conditions || [])
            .map((c) => c.condition_name?.trim())
            .filter(Boolean);
          if (opts.length === 1) setH2Condition(opts[0]);
        }
      } catch {
        if (!cancelled) setConditionLookup(null);
      } finally {
        if (!cancelled) setConditionLookupLoading(false);
      }
    }, 350);

    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [gasType, materialKey]);

  // Alias review — loads when unresolved conditions are detected
  const syncAliasDrafts = (rows: H2ConditionAliasRecord[]) => {
    setAliasReviewDrafts((prev) => {
      const next: Record<string, { display: string; canonical: string }> = {};
      for (const row of rows) {
        const existing = prev[row.raw_key];
        next[row.raw_key] = {
          display: existing?.display ?? row.display_label,
          canonical: existing?.canonical ?? (row.canonical_condition || row.display_label),
        };
      }
      return next;
    });
  };

  const loadAliasReview = async (material: string) => {
    if (!material.trim()) {
      setAliasReviewRows([]);
      setAliasReviewDrafts({});
      return;
    }
    setAliasReviewLoading(true);
    try {
      const data = await getH2ConditionAliases(material, true, 50);
      const rows = data.aliases || [];
      setAliasReviewRows(rows);
      syncAliasDrafts(rows);
    } catch {
      setAliasReviewRows([]);
      setAliasReviewDrafts({});
    } finally {
      setAliasReviewLoading(false);
    }
  };

  useEffect(() => {
    if (gasType !== 'H2') {
      setAliasReviewRows([]);
      setAliasReviewDrafts({});
      setAliasReviewLoading(false);
      return;
    }

    const material = materialKey.trim();
    const unresolved = conditionLookup?.unresolved_condition_count || 0;
    if (!material || unresolved <= 0) {
      setAliasReviewRows([]);
      setAliasReviewDrafts({});
      setAliasReviewLoading(false);
      return;
    }

    let cancelled = false;
    setAliasReviewLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const data = await getH2ConditionAliases(material, true, 50);
        if (cancelled) return;
        const rows = data.aliases || [];
        setAliasReviewRows(rows);
        syncAliasDrafts(rows);
      } catch {
        if (cancelled) return;
        setAliasReviewRows([]);
        setAliasReviewDrafts({});
      } finally {
        if (!cancelled) setAliasReviewLoading(false);
      }
    }, 250);

    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [gasType, materialKey, conditionLookup?.unresolved_condition_count]);

  const loadFamilies = async () => {
    setFamiliesLoading(true);
    try {
      const data = await o2GetFamilies();
      setFamilies(data);
    } catch (error) {
      console.error('Failed to load O2 families:', error);
    } finally {
      setFamiliesLoading(false);
    }
  };

  const runCompatibilityCheck = async (conditionOverride?: string) => {
    if (!materialKey || !pressure || !temperature) return;

    setLoading(true);
    setResult(null);
    setO2Result(null);

    try {
      const effectiveCondition = conditionOverride ?? h2Condition;
      const normalizedCondition = (effectiveCondition || '').trim();
      const request = {
        material_key: materialKey,
        pressure: parseFloat(pressure),
        temperature: parseFloat(temperature),
        condition: gasType === 'H2' ? (normalizedCondition || undefined) : undefined,
      };

      if (gasType === 'O2') {
        setLastEvaluatedH2Condition('');
        const [legacyResponse, newResponse] = await Promise.allSettled([
          checkO2Compatibility(request),
          o2Evaluate({
            material_key: materialKey,
            pressure_psia: parseFloat(pressure),
            temperature_f: parseFloat(temperature),
            phase,
          }),
        ]);

        if (legacyResponse.status === 'fulfilled') setResult(legacyResponse.value);
        if (newResponse.status === 'fulfilled') setO2Result(newResponse.value);
      } else {
        setLastEvaluatedH2Condition(normalizedCondition);
        const response = await checkH2Compatibility(request);
        setResult(response);
      }
    } catch (error) {
      console.error('Compatibility check failed:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await runCompatibilityCheck();
  };

  const handleApplyCondition = async (conditionName: string) => {
    setH2Condition(conditionName);
    await runCompatibilityCheck(conditionName);
  };

  const handleAliasDraftChange = (
    rawKey: string,
    field: 'display' | 'canonical',
    value: string,
  ) => {
    setAliasReviewDrafts((prev) => ({
      ...prev,
      [rawKey]: { ...prev[rawKey], [field]: value },
    }));
  };

  const handleVerifyAlias = async (row: H2ConditionAliasRecord) => {
    const draft = aliasReviewDrafts[row.raw_key] || {
      display: row.display_label,
      canonical: row.canonical_condition || row.display_label,
    };
    const display = (draft.display || '').trim();
    const canonical = (draft.canonical || '').trim() || display;
    if (!display) return;

    setAliasSaveLoadingKey(row.raw_key);
    try {
      await verifyH2ConditionAlias({
        raw_key: row.raw_key,
        raw_text: row.raw_text,
        display_label: display,
        canonical_condition: canonical,
        is_condition: true,
        source_document: row.source_document || undefined,
        material_name: row.material_name || materialKey || undefined,
      });

      const material = materialKey.trim();
      if (material) {
        try {
          const lookup = await getH2Conditions(material);
          setConditionLookup(lookup);
        } catch { /* refresh failed, non-critical */ }
        await loadAliasReview(material);
      }
    } catch (error) {
      console.error('H2 alias verification failed:', error);
    } finally {
      setAliasSaveLoadingKey(null);
    }
  };

  const handleBOKSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bokQuery.trim()) return;

    setBokLoading(true);
    setBokResults(null);

    try {
      const response = await o2SearchBOK({
        query: bokQuery,
        k: 10,
        use_hybrid: true,
      });
      setBokResults(response);
    } catch (error) {
      console.error('BOK search failed:', error);
    } finally {
      setBokLoading(false);
    }
  };

  // Derived state for H2 result display
  const h2Classification = (result?.classification || '').toLowerCase();
  const displayedRationale = o2Result?.rationale || result?.rationale || '';
  const { rationaleWithoutReview, bullets: extractedReviewBullets } =
    extractEngineeringReviewBullets(displayedRationale);
  const showEngineeringReview =
    gasType === 'H2' && ['caution', 'unknown', 'prohibited'].includes(h2Classification);
  const engineeringReviewBullets =
    extractedReviewBullets.length > 0
      ? extractedReviewBullets
      : [
          'Verify pressure, temperature, and stress envelope match.',
          'Confirm material condition, product form, and heat-treatment applicability.',
          'Assess fracture-criticality and failure consequences for the application.',
          'Review hydrogen embrittlement and degradation evidence for the selected material.',
          'Complete qualification testing if available evidence is insufficient.',
          'Obtain Materials/Fracture authority disposition before final use.',
        ];
  const showClarification =
    gasType === 'H2' &&
    Boolean(result?.needs_clarification) &&
    (Boolean(result?.clarification_prompt) || Boolean(result?.available_conditions?.length));

  // Merge condition options from lookup + result
  const conditionOptionMap = new Map<string, H2ConditionOption>();
  for (const opt of conditionLookup?.available_conditions || []) {
    const key = (opt.condition_name || '').trim();
    if (key && !conditionOptionMap.has(key)) conditionOptionMap.set(key, opt);
  }
  for (const opt of result?.available_conditions || []) {
    const key = (opt.condition_name || '').trim();
    if (key && !conditionOptionMap.has(key)) conditionOptionMap.set(key, opt);
  }
  const conditionOptionRecords = Array.from(conditionOptionMap.values());
  const conditionOptions = conditionOptionRecords.map((opt) => opt.condition_name);

  const h2DecisionBand = gasType === 'H2' ? parseH2DecisionBand(result) : { band: 'none' as const };
  const showDecisionBand = gasType === 'H2' && h2DecisionBand.band !== 'none';

  return (
    <div>
      <PageHeader
        title="Gas Compatibility"
        description="Check material compatibility for oxygen or hydrogen service"
        helpContent={helpContent.gasCompatibility}
      />

      <Tabs defaultValue="compatibility" className="space-y-6">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="compatibility" className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            Compatibility Check
          </TabsTrigger>
          <TabsTrigger value="bok" className="flex items-center gap-2">
            <BookOpen className="h-4 w-4" />
            O2 Standards Search
          </TabsTrigger>
          <TabsTrigger value="families" className="flex items-center gap-2">
            <Layers className="h-4 w-4" />
            Material Families
          </TabsTrigger>
        </TabsList>

        {/* Compatibility Check Tab */}
        <TabsContent value="compatibility" className="space-y-6">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Gas Type Toggle */}
            <div className="flex gap-2">
              <Button
                type="button"
                variant={gasType === 'O2' ? 'default' : 'outline'}
                onClick={() => setGasType('O2')}
                className="flex-1"
              >
                O&#x2082; Oxygen
              </Button>
              <Button
                type="button"
                variant={gasType === 'H2' ? 'default' : 'outline'}
                onClick={() => setGasType('H2')}
                className="flex-1"
              >
                H&#x2082; Hydrogen
              </Button>
            </div>

            {/* H2-specific controls */}
            {gasType === 'H2' && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 pt-1">
                  <Label htmlFor="h2-condition" className="text-xs text-muted-foreground">Condition</Label>
                  <Input
                    id="h2-condition"
                    placeholder="optional, e.g. ST 1900F"
                    value={h2Condition}
                    onChange={(e) => setH2Condition(e.target.value)}
                    className="h-8 max-w-xs"
                  />
                  {h2Condition && (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-8 px-2"
                      onClick={() => setH2Condition('')}
                    >
                      Clear
                    </Button>
                  )}
                </div>
                {conditionLookupLoading && (
                  <p className="text-xs text-muted-foreground">Looking up known conditions...</p>
                )}
                {!conditionLookupLoading && conditionLookup?.canonical_material && (
                  <p className="text-xs text-muted-foreground">
                    Evidence match: {conditionLookup.canonical_material}
                  </p>
                )}
                {!conditionLookupLoading &&
                  (conditionLookup?.unresolved_condition_count || 0) > 0 && (
                    <p className="text-xs text-amber-700">
                      Condition mapping review flag: {conditionLookup?.unresolved_condition_count} unresolved label(s).
                    </p>
                  )}

                {/* Condition Alias Review Panel */}
                {!conditionLookupLoading &&
                  (conditionLookup?.unresolved_condition_count || 0) > 0 && (
                    <div className="rounded-md border border-amber-300 bg-amber-50/60 p-3 space-y-2">
                      <p className="text-xs font-medium uppercase tracking-wide text-amber-900">
                        Condition Alias Review
                      </p>
                      {aliasReviewLoading && (
                        <p className="text-xs text-amber-800">Loading unresolved aliases...</p>
                      )}
                      {!aliasReviewLoading && aliasReviewRows.length === 0 && (
                        <p className="text-xs text-amber-800">No unresolved alias rows found for this material.</p>
                      )}
                      {!aliasReviewLoading &&
                        aliasReviewRows.map((row) => {
                          const draft = aliasReviewDrafts[row.raw_key] || {
                            display: row.display_label,
                            canonical: row.canonical_condition || row.display_label,
                          };
                          return (
                            <div key={row.raw_key} className="rounded border bg-white p-2 space-y-2">
                              <div className="text-xs">
                                <span className="font-medium">Raw:</span> {row.raw_text}
                              </div>
                              <div className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center">
                                <div className="md:col-span-4">
                                  <Label className="text-[11px] text-muted-foreground">Display Label</Label>
                                  <Input
                                    value={draft.display}
                                    onChange={(e) =>
                                      handleAliasDraftChange(row.raw_key, 'display', e.target.value)
                                    }
                                    className="h-8 text-xs"
                                  />
                                </div>
                                <div className="md:col-span-4">
                                  <Label className="text-[11px] text-muted-foreground">Canonical</Label>
                                  <Input
                                    value={draft.canonical}
                                    onChange={(e) =>
                                      handleAliasDraftChange(row.raw_key, 'canonical', e.target.value)
                                    }
                                    className="h-8 text-xs"
                                  />
                                </div>
                                <div className="md:col-span-4">
                                  <Label className="text-[11px] text-muted-foreground">Action</Label>
                                  <Button
                                    type="button"
                                    size="sm"
                                    className="h-8 w-full"
                                    disabled={aliasSaveLoadingKey === row.raw_key}
                                    onClick={() => handleVerifyAlias(row)}
                                  >
                                    {aliasSaveLoadingKey === row.raw_key && (
                                      <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                                    )}
                                    Verify Alias
                                  </Button>
                                </div>
                              </div>
                              {(row.material_name || row.source_document) && (
                                <p className="text-[11px] text-muted-foreground">
                                  {row.material_name ? `Material: ${row.material_name}` : ''}
                                  {row.material_name && row.source_document ? ' | ' : ''}
                                  {row.source_document ? `Source: ${row.source_document}` : ''}
                                </p>
                              )}
                            </div>
                          );
                        })}
                    </div>
                  )}

                {/* Known Conditions Dropdown */}
                {conditionOptions.length > 0 && (
                  <div className="flex items-center gap-2 pt-1">
                    <Label htmlFor="h2-condition-select" className="text-xs text-muted-foreground">
                      Known Conditions
                    </Label>
                    <select
                      id="h2-condition-select"
                      value={conditionOptions.includes(h2Condition) ? h2Condition : ''}
                      onChange={(e) => setH2Condition(e.target.value)}
                      className="h-8 max-w-xs rounded-md border border-input bg-background px-2 text-sm"
                    >
                      <option value="">Select from evidence...</option>
                      {conditionOptions.map((opt) => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-8 px-2"
                      disabled={loading || !h2Condition.trim()}
                      onClick={() => runCompatibilityCheck()}
                    >
                      Apply
                    </Button>
                  </div>
                )}

                {/* Condition Compare Table */}
                {conditionOptionRecords.length > 0 && (
                  <div className="rounded-md border p-3 space-y-2">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Condition Compare
                    </p>
                    <div className="grid grid-cols-12 gap-2 text-xs text-muted-foreground font-medium">
                      <div className="col-span-5">Condition</div>
                      <div className="col-span-2">HEE</div>
                      <div className="col-span-2">Verdict</div>
                      <div className="col-span-1">n</div>
                      <div className="col-span-2">Action</div>
                    </div>
                    {conditionOptionRecords.map((opt) => (
                      <div key={`${opt.condition_name}-${opt.hee_band}`} className="grid grid-cols-12 gap-2 text-xs items-center">
                        <div className="col-span-5 truncate" title={opt.condition_name}>{opt.condition_name}</div>
                        <div className="col-span-2">{opt.hee_band}</div>
                        <div className="col-span-2">{opt.verdict_if_selected}</div>
                        <div className="col-span-1">{opt.evidence_count}</div>
                        <div className="col-span-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2"
                            disabled={loading}
                            onClick={() => {
                              setH2Condition(opt.condition_name);
                              runCompatibilityCheck(opt.condition_name);
                            }}
                          >
                            Use
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-2">
                <Label htmlFor="material">Material</Label>
                <Input
                  id="material"
                  placeholder="e.g., SS316, INCONEL 718"
                  value={materialKey}
                  onChange={(e) => setMaterialKey(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="pressure">Pressure (PSIA)</Label>
                <Input
                  id="pressure"
                  type="number"
                  placeholder="e.g., 3000"
                  value={pressure}
                  onChange={(e) => setPressure(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="temperature">Temperature (°F)</Label>
                <Input
                  id="temperature"
                  type="number"
                  placeholder="e.g., 70"
                  value={temperature}
                  onChange={(e) => setTemperature(e.target.value)}
                />
              </div>
              {gasType === 'O2' && (
                <div className="space-y-2">
                  <Label htmlFor="phase">Phase</Label>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={phase === 'gox' ? 'default' : 'outline'}
                      onClick={() => setPhase('gox')}
                      className="flex-1"
                    >
                      GOX (Gas)
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={phase === 'lox' ? 'default' : 'outline'}
                      onClick={() => setPhase('lox')}
                      className="flex-1"
                    >
                      LOX (Liquid)
                    </Button>
                  </div>
                </div>
              )}
            </div>

            <Button type="submit" disabled={loading || !materialKey || !pressure || !temperature}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Check Compatibility
            </Button>
          </form>

          {/* Results */}
          {(result || o2Result) && (
            <div className="mt-8 space-y-6 animate-fade-in">
              <Card>
                <CardContent className="pt-6">
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-2">
                      <div className="flex items-center gap-3">
                        <StatusBadge status={o2Result?.classification?.toLowerCase() || result?.classification || 'unknown'} />
                        <span className="text-sm text-muted-foreground">
                          {gasType === 'O2'
                            ? `Oxygen Service (${phase.toUpperCase()})`
                            : 'Hydrogen Service'}
                        </span>
                        {gasType === 'H2' && lastEvaluatedH2Condition && (
                          <Badge variant="outline" className="text-xs">
                            Condition: {lastEvaluatedH2Condition}
                          </Badge>
                        )}
                        {o2Result && (
                          <Badge variant="outline" className="text-xs">
                            {o2Result.pressure_psia} PSIA @ {o2Result.temperature_f}°F
                          </Badge>
                        )}
                      </div>
                      <p className="text-foreground leading-relaxed whitespace-pre-line">
                        {rationaleWithoutReview}
                      </p>
                      {(o2Result?.notes || result?.notes) && (
                        <p className="text-sm text-muted-foreground mt-2">
                          {o2Result?.notes || result?.notes}
                        </p>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>

              {(o2Result?.evidence?.length || result?.evidence?.length) ? (
                <div className="space-y-3">
                  <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                    Supporting Evidence
                  </h3>
                  <EvidenceTable evidence={o2Result?.evidence || result?.evidence || []} />
                </div>
              ) : null}

              {/* Condition Clarification Card */}
              {showClarification && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Condition Clarification Required</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {result?.clarification_prompt && (
                      <p className="text-sm text-muted-foreground">{result.clarification_prompt}</p>
                    )}
                    {result?.available_conditions?.length ? (
                      <div className="space-y-2">
                        {result.available_conditions.map((opt) => (
                          <div
                            key={`${opt.condition_name}-${opt.hee_band}-${opt.source}`}
                            className="rounded-md border p-3"
                          >
                            <div className="flex flex-wrap items-center gap-2 text-sm">
                              <Badge variant="outline">{opt.condition_name}</Badge>
                              <Badge variant="secondary">HEE: {opt.hee_band}</Badge>
                              <Badge variant="secondary">Verdict: {opt.verdict_if_selected}</Badge>
                              <span className="text-muted-foreground">n={opt.evidence_count}</span>
                            </div>
                            <p className="mt-2 text-xs text-muted-foreground">Source: {opt.source}</p>
                            <div className="mt-2">
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={loading}
                                onClick={() => handleApplyCondition(opt.condition_name)}
                              >
                                Use This Condition
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              )}

              {/* H2/He Decision Band Card */}
              {showDecisionBand && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">H2/He Decision Band</CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm text-muted-foreground space-y-2">
                    {h2DecisionBand.band === 'prohibited' && (
                      <p>
                        Deterministic screen indicates <strong className="text-foreground">H2/He &le; 0.75</strong>.
                        Treat as <strong className="text-foreground">not suitable for hydrogen service</strong>.
                      </p>
                    )}
                    {h2DecisionBand.band === 'judgement' && (
                      <p>
                        Deterministic screen indicates <strong className="text-foreground">H2/He &ge; 0.76</strong>.
                        Use is potentially acceptable with condition-specific engineering review.
                      </p>
                    )}
                    {h2DecisionBand.band === 'mixed' && (
                      <p>
                        Evidence spans both sides of the 0.75/0.76 threshold.
                        Treat as condition-dependent and resolve by heat treatment/test condition.
                      </p>
                    )}
                    {h2DecisionBand.detail && (
                      <p className="text-xs">{h2DecisionBand.detail}</p>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Engineering Review Card */}
              {showEngineeringReview && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">The following engineering review is suggested</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="list-disc pl-5 space-y-1 text-sm text-muted-foreground">
                      {engineeringReviewBullets.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </TabsContent>

        {/* O2 BOK Search Tab */}
        <TabsContent value="bok" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BookOpen className="h-5 w-5" />
                O2 Body of Knowledge Search
              </CardTitle>
              <CardDescription>
                Search NASA standards and guidance documents for oxygen compatibility information.
                Includes NASA-STD-6016, NASA-STD-6001B, JSC-27301F, and KSC-KTI-5210C.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleBOKSearch} className="flex gap-4">
                <Input
                  placeholder="Search O2 standards... (e.g., 'ignition temperature aluminum')"
                  value={bokQuery}
                  onChange={(e) => setBokQuery(e.target.value)}
                  className="flex-1"
                />
                <Button type="submit" disabled={bokLoading || !bokQuery.trim()}>
                  {bokLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Search
                </Button>
              </form>
            </CardContent>
          </Card>

          {bokResults && (
            <div className="space-y-4 animate-fade-in">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                  {bokResults.total_results} Results ({bokResults.search_type} search)
                </h3>
              </div>

              <div className="space-y-3">
                {bokResults.results.map((r, idx) => (
                  <Card key={r.doc_id || idx}>
                    <CardContent className="pt-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-2 flex-1">
                          <div className="flex items-center gap-2">
                            <Badge variant="secondary">{r.source}</Badge>
                            {r.section && (
                              <span className="text-xs text-muted-foreground">{r.section}</span>
                            )}
                            <span className="text-xs text-muted-foreground ml-auto">
                              Score: {(r.relevance_score * 100).toFixed(1)}%
                            </span>
                          </div>
                          <p className="text-sm text-foreground leading-relaxed">
                            {r.text.length > 500 ? `${r.text.slice(0, 500)}...` : r.text}
                          </p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </TabsContent>

        {/* Material Families Tab */}
        <TabsContent value="families" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Layers className="h-5 w-5" />
                O2 Material Family Classifications
              </CardTitle>
              <CardDescription>
                Material families and their O2 compatibility status per NASA-STD-6016.
                Classification is based on MAPTIS material family, not string matching.
              </CardDescription>
            </CardHeader>
          </Card>

          {familiesLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : families ? (
            <div className="grid gap-6 md:grid-cols-3">
              {/* Approved Families */}
              <Card className="border-green-200 dark:border-green-900">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-green-700 dark:text-green-400">
                    <CheckCircle className="h-5 w-5" />
                    Approved ({families.approved_families.length})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {families.approved_families.map((family, idx) => (
                    <div key={idx} className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-400">
                          {family.family}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">{family.reason}</p>
                      {family.bok_ref && (
                        <p className="text-xs text-muted-foreground italic">{family.bok_ref}</p>
                      )}
                    </div>
                  ))}
                </CardContent>
              </Card>

              {/* Restricted Families */}
              <Card className="border-yellow-200 dark:border-yellow-900">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-yellow-700 dark:text-yellow-400">
                    <AlertTriangle className="h-5 w-5" />
                    Restricted ({families.restricted_families.length})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {families.restricted_families.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No restricted families defined</p>
                  ) : (
                    families.restricted_families.map((family, idx) => (
                      <div key={idx} className="space-y-1">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="bg-yellow-50 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-400">
                            {family.family}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">{family.reason}</p>
                        {family.bok_ref && (
                          <p className="text-xs text-muted-foreground italic">{family.bok_ref}</p>
                        )}
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>

              {/* Prohibited Families */}
              <Card className="border-red-200 dark:border-red-900">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-red-700 dark:text-red-400">
                    <XCircle className="h-5 w-5" />
                    Prohibited ({families.prohibited_families.length})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {families.prohibited_families.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No prohibited families defined</p>
                  ) : (
                    families.prohibited_families.map((family, idx) => (
                      <div key={idx} className="space-y-1">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400">
                            {family.family}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">{family.reason}</p>
                        {family.bok_ref && (
                          <p className="text-xs text-muted-foreground italic">{family.bok_ref}</p>
                        )}
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>
            </div>
          ) : (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">
                Failed to load material families. The O2 Knowledge Twin may not be available.
              </CardContent>
            </Card>
          )}

          {families?.note && (
            <p className="text-sm text-muted-foreground text-center">{families.note}</p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
