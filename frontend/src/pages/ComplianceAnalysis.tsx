import { useState } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { StatusBadge } from '@/components/StatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Loader2, AlertTriangle, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import {
  analyzeCompliance,
  type ComplianceAnalysisRequest,
  type ComplianceAnalysisResponse,
  type MPRDeterminationResponse,
  type GapSignalResponse,
  type OperationalConstraintResponse,
} from '@/lib/api';
import helpContent from '@/config/helpContent';

// Map compliance status to UI status
function mapComplianceStatus(status: string): string {
  switch (status.toLowerCase()) {
    case 'compliant':
      return 'OK';
    case 'compliant_with_constraints':
      return 'CAUTION';
    case 'noncompliant':
      return 'PROHIBITED';
    default:
      return 'UNKNOWN';
  }
}

// Map overall status to icon and color
function getStatusIcon(status: string) {
  switch (status.toLowerCase()) {
    case 'compliant':
      return <CheckCircle className="h-5 w-5 text-green-500" />;
    case 'compliant_with_constraints':
      return <AlertCircle className="h-5 w-5 text-yellow-500" />;
    case 'noncompliant':
      return <XCircle className="h-5 w-5 text-red-500" />;
    default:
      return <AlertTriangle className="h-5 w-5 text-gray-500" />;
  }
}

// Map severity to color
function getSeverityColor(severity: string): string {
  switch (severity.toLowerCase()) {
    case 'critical':
      return 'text-red-600 bg-red-50 border-red-200';
    case 'high':
      return 'text-orange-600 bg-orange-50 border-orange-200';
    case 'medium':
      return 'text-yellow-600 bg-yellow-50 border-yellow-200';
    case 'low':
      return 'text-blue-600 bg-blue-50 border-blue-200';
    default:
      return 'text-gray-600 bg-gray-50 border-gray-200';
  }
}

export default function ComplianceAnalysis() {
  const [materialKey, setMaterialKey] = useState('');
  const [maptisCode, setMaptisCode] = useState('');
  const [pressure, setPressure] = useState('14.7');
  const [temperature, setTemperature] = useState('70');
  const [o2Percent, setO2Percent] = useState('21');
  const [isHydrogenService, setIsHydrogenService] = useState(false);
  const [isHabitable, setIsHabitable] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ComplianceAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!materialKey) return;

    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const request: ComplianceAnalysisRequest = {
        material_key: materialKey,
        maptis_code: maptisCode ? parseInt(maptisCode) : undefined,
        pressure_psia: parseFloat(pressure) || 14.7,
        temperature_f: parseFloat(temperature) || 70,
        o2_percent: parseFloat(o2Percent) || 21,
        is_hydrogen_service: isHydrogenService,
        is_habitable: isHabitable,
        hydrogen_phase: isHydrogenService ? 'gh2' : undefined,
      };

      const response = await analyzeCompliance(request);
      setResult(response);
    } catch (err) {
      console.error('Compliance analysis failed:', err);
      setError(err instanceof Error ? err.message : 'Compliance analysis failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Compliance Analysis"
        description="Analyze material compliance with NASA-STD-6016C requirements"
        helpContent={helpContent.complianceAnalysis}
      />

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Material Inputs */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-2">
            <Label htmlFor="material">Material Key *</Label>
            <Input
              id="material"
              placeholder="e.g., SS316, Ti-6Al-4V"
              value={materialKey}
              onChange={(e) => setMaterialKey(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="maptis">MAPTIS Code (optional)</Label>
            <Input
              id="maptis"
              type="number"
              placeholder="e.g., 12345"
              value={maptisCode}
              onChange={(e) => setMaptisCode(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pressure">Pressure (PSIA)</Label>
            <Input
              id="pressure"
              type="number"
              step="0.1"
              placeholder="14.7"
              value={pressure}
              onChange={(e) => setPressure(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="temperature">Temperature (°F)</Label>
            <Input
              id="temperature"
              type="number"
              step="0.1"
              placeholder="70"
              value={temperature}
              onChange={(e) => setTemperature(e.target.value)}
            />
          </div>
        </div>

        {/* Environment Options */}
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="o2percent">O₂ Concentration (%)</Label>
            <Input
              id="o2percent"
              type="number"
              step="0.1"
              placeholder="21"
              value={o2Percent}
              onChange={(e) => setO2Percent(e.target.value)}
            />
          </div>
          <div className="flex items-center space-x-2 pt-6">
            <Checkbox
              id="hydrogen"
              checked={isHydrogenService}
              onCheckedChange={(checked) => setIsHydrogenService(checked === true)}
            />
            <Label htmlFor="hydrogen" className="font-normal cursor-pointer">
              Hydrogen Service (H₂)
            </Label>
          </div>
          <div className="flex items-center space-x-2 pt-6">
            <Checkbox
              id="habitable"
              checked={isHabitable}
              onCheckedChange={(checked) => setIsHabitable(checked === true)}
            />
            <Label htmlFor="habitable" className="font-normal cursor-pointer">
              Habitable Environment
            </Label>
          </div>
        </div>

        <Button type="submit" disabled={loading || !materialKey}>
          {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Analyze Compliance
        </Button>
      </form>

      {/* Error Display */}
      {error && (
        <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded-md">
          <div className="flex items-center gap-2 text-red-700">
            <AlertTriangle className="h-5 w-5" />
            <span className="font-medium">Error</span>
          </div>
          <p className="mt-1 text-red-600">{error}</p>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="mt-8 space-y-6 animate-fade-in">
          {/* Summary Card */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2">
                {getStatusIcon(result.summary.overall_status)}
                Overall Compliance Status
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <StatusBadge status={mapComplianceStatus(result.summary.overall_status)} />
                  <span className="text-sm text-muted-foreground">
                    {result.environment_description}
                  </span>
                </div>
                <p className="text-foreground leading-relaxed">
                  {result.summary.status_rationale}
                </p>

                {/* Summary Stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t">
                  <div className="text-center">
                    <div className="text-2xl font-bold text-green-600">
                      {result.summary.mprs_compliant}
                    </div>
                    <div className="text-xs text-muted-foreground">MPRs Compliant</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-yellow-600">
                      {result.summary.mprs_compliant_with_constraints}
                    </div>
                    <div className="text-xs text-muted-foreground">With Constraints</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-red-600">
                      {result.summary.mprs_noncompliant}
                    </div>
                    <div className="text-xs text-muted-foreground">Non-Compliant</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-orange-600">
                      {result.summary.total_gaps}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Gaps ({result.summary.critical_gaps} Critical)
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* MPR Determinations */}
          {result.determinations.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                MPR Determinations ({result.determinations.length})
              </h3>
              <div className="grid gap-3">
                {result.determinations.map((det: MPRDeterminationResponse, idx: number) => (
                  <Card key={idx} className="overflow-hidden">
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-1 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">
                              MPR-{det.mpr_number}: {det.mpr_title}
                            </span>
                            <StatusBadge
                              status={mapComplianceStatus(det.compliance_status)}
                              className="text-[10px] px-2 py-0.5"
                            />
                          </div>
                          <p className="text-sm text-muted-foreground">
                            Section {det.mpr_section}
                          </p>
                          <p className="text-sm mt-2">{det.compliance_basis}</p>
                          {det.required_action !== 'none' && (
                            <p className="text-sm text-orange-600 mt-1">
                              Required: {det.required_action.replace(/_/g, ' ')}
                            </p>
                          )}
                        </div>
                        <div className="text-right text-sm text-muted-foreground">
                          {det.gap_count > 0 && (
                            <div className="text-orange-600">{det.gap_count} gaps</div>
                          )}
                          {det.constraint_count > 0 && (
                            <div className="text-blue-600">{det.constraint_count} constraints</div>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {/* Gaps */}
          {result.gaps.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                Gap Signals ({result.gaps.length})
              </h3>
              <div className="grid gap-2">
                {result.gaps.map((gap: GapSignalResponse, idx: number) => (
                  <div
                    key={idx}
                    className={`p-3 rounded-md border ${getSeverityColor(gap.severity)}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm">{gap.gap_type}</span>
                          <span className="text-xs uppercase px-1.5 py-0.5 rounded bg-white/50">
                            {gap.severity}
                          </span>
                        </div>
                        <p className="text-sm">{gap.description}</p>
                        <p className="text-xs opacity-75">Trigger: {gap.trigger}</p>
                      </div>
                      {gap.evidence_count > 0 && (
                        <div className="text-xs">
                          {gap.evidence_count} evidence
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Constraints */}
          {result.constraints.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                Operational Constraints ({result.constraints.length})
              </h3>
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="text-left p-3 font-medium">Parameter</th>
                        <th className="text-left p-3 font-medium">Limit</th>
                        <th className="text-left p-3 font-medium">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.constraints.map((constraint: OperationalConstraintResponse, idx: number) => (
                        <tr key={idx} className="border-t">
                          <td className="p-3 font-medium">{constraint.parameter}</td>
                          <td className="p-3">
                            <span className="text-blue-600">
                              {constraint.limit_type}: {constraint.limit_value}
                            </span>
                          </td>
                          <td className="p-3 text-muted-foreground">{constraint.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Warnings */}
          {result.warnings.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                Warnings
              </h3>
              <div className="space-y-1">
                {result.warnings.map((warning: string, idx: number) => (
                  <div key={idx} className="flex items-center gap-2 text-sm text-yellow-600">
                    <AlertTriangle className="h-4 w-4" />
                    {warning}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Footer Info */}
          <div className="text-xs text-muted-foreground pt-4 border-t">
            <div className="flex justify-between">
              <span>Request ID: {result.request_id}</span>
              <span>Analysis time: {result.run_duration_ms}ms</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
