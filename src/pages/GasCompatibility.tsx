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
  o2Evaluate,
  o2SearchBOK,
  o2GetFamilies,
  type CompatibilityResponse,
  type O2EvaluateResponse,
  type O2BOKSearchResponse,
  type O2FamiliesResponse,
} from '@/lib/api';
import helpContent from '@/config/helpContent';

type GasType = 'O2' | 'H2';

export default function GasCompatibility() {
  const [gasType, setGasType] = useState<GasType>('O2');
  const [materialKey, setMaterialKey] = useState('');
  const [pressure, setPressure] = useState('');
  const [temperature, setTemperature] = useState('');
  const [phase, setPhase] = useState<'gox' | 'lox'>('gox');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CompatibilityResponse | null>(null);
  const [o2Result, setO2Result] = useState<O2EvaluateResponse | null>(null);

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!materialKey || !pressure || !temperature) return;

    setLoading(true);
    setResult(null);
    setO2Result(null);

    try {
      const request = {
        material_key: materialKey,
        pressure: parseFloat(pressure),
        temperature: parseFloat(temperature),
      };

      if (gasType === 'O2') {
        // Use both endpoints for richer data
        const [legacyResponse, newResponse] = await Promise.allSettled([
          checkO2Compatibility(request),
          o2Evaluate({
            material_key: materialKey,
            pressure_psia: parseFloat(pressure),
            temperature_f: parseFloat(temperature),
            phase,
          }),
        ]);

        if (legacyResponse.status === 'fulfilled') {
          setResult(legacyResponse.value);
        }
        if (newResponse.status === 'fulfilled') {
          setO2Result(newResponse.value);
        }
      } else {
        const response = await checkH2Compatibility(request);
        setResult(response);
      }
    } catch (error) {
      console.error('Compatibility check failed:', error);
    } finally {
      setLoading(false);
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
                O₂ Oxygen
              </Button>
              <Button
                type="button"
                variant={gasType === 'H2' ? 'default' : 'outline'}
                onClick={() => setGasType('H2')}
                className="flex-1"
              >
                H₂ Hydrogen
              </Button>
            </div>

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
                          {gasType === 'O2' ? `Oxygen Service (${phase.toUpperCase()})` : 'Hydrogen Service'}
                        </span>
                        {o2Result && (
                          <Badge variant="outline" className="text-xs">
                            {o2Result.pressure_psia} PSIA @ {o2Result.temperature_f}°F
                          </Badge>
                        )}
                      </div>
                      <p className="text-foreground leading-relaxed">
                        {o2Result?.rationale || result?.rationale}
                      </p>
                      {o2Result?.notes && (
                        <p className="text-sm text-muted-foreground mt-2">{o2Result.notes}</p>
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
                {bokResults.results.map((result, idx) => (
                  <Card key={result.doc_id || idx}>
                    <CardContent className="pt-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-2 flex-1">
                          <div className="flex items-center gap-2">
                            <Badge variant="secondary">{result.source}</Badge>
                            {result.section && (
                              <span className="text-xs text-muted-foreground">{result.section}</span>
                            )}
                            <span className="text-xs text-muted-foreground ml-auto">
                              Score: {(result.relevance_score * 100).toFixed(1)}%
                            </span>
                          </div>
                          <p className="text-sm text-foreground leading-relaxed">
                            {result.text.length > 500 ? `${result.text.slice(0, 500)}...` : result.text}
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
                    Approved ({families.approved_families?.length ?? 0})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {(families.approved_families ?? []).map((family, idx) => (
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
                    Restricted ({families.restricted_families?.length ?? 0})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {!families.restricted_families?.length ? (
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
                    Prohibited ({families.prohibited_families?.length ?? 0})
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {!families.prohibited_families?.length ? (
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
