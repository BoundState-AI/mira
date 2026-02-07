import { useState } from "react";
import { ShieldAlert, Loader2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  v4HeritageOverride,
  type V4HeritageVetoResponse,
  type V4HeritageOverrideResponse,
} from "@/lib/api";

interface HeritageVetoModalProps {
  open: boolean;
  vetoResult: V4HeritageVetoResponse;
  materialKey: string;
  lineageHash: string;
  failureEnvironment: Record<string, unknown>;
  queryEnvironment: Record<string, unknown>;
  onOverrideComplete: (override: V4HeritageOverrideResponse) => void;
  onCancel: () => void;
}

function EnvComparisonRow({ label, failureVal, queryVal }: {
  label: string;
  failureVal: unknown;
  queryVal: unknown;
}) {
  const fStr = failureVal != null ? String(failureVal) : "N/A";
  const qStr = queryVal != null ? String(queryVal) : "N/A";
  return (
    <TableRow>
      <TableCell className="text-xs font-medium py-1.5">{label}</TableCell>
      <TableCell className="text-xs font-mono py-1.5">{fStr}</TableCell>
      <TableCell className="text-xs font-mono py-1.5">{qStr}</TableCell>
    </TableRow>
  );
}

export function HeritageVetoModal({
  open,
  vetoResult,
  materialKey,
  lineageHash,
  failureEnvironment,
  queryEnvironment,
  onOverrideComplete,
  onCancel,
}: HeritageVetoModalProps) {
  const [engineerName, setEngineerName] = useState("");
  const [rationale, setRationale] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isValid = engineerName.trim().length > 0 && rationale.trim().length >= 10;
  const firstFailureId = vetoResult.heritage_failure_ids[0] || "";

  const handleSubmit = async () => {
    if (!isValid || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);

    try {
      const override = await v4HeritageOverride({
        material_key: materialKey,
        heritage_failure_id: firstFailureId,
        failure_environment: failureEnvironment,
        query_environment: queryEnvironment,
        engineer_name: engineerName.trim(),
        engineer_rationale: rationale.trim(),
        lineage_hash: lineageHash,
      });
      onOverrideComplete(override);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Override failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Extract envelope match details for display
  const envDetails = vetoResult.envelope_match_details || {};
  const firstDetail = Object.values(envDetails)[0] as Record<string, unknown> | undefined;

  return (
    <AlertDialog open={open}>
      <AlertDialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2 text-red-700">
            <ShieldAlert className="h-5 w-5" />
            Safety-Critical Heritage Veto
          </AlertDialogTitle>
          <AlertDialogDescription className="text-sm">
            Material <span className="font-mono font-bold">{materialKey}</span>{" "}
            has {vetoResult.heritage_failure_ids.length} known heritage
            failure(s) in a matching environment. You must acknowledge this
            before proceeding.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-4 py-2">
          {/* Heritage failure IDs */}
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">
              Heritage Failure Records
            </Label>
            <div className="flex flex-wrap gap-1.5">
              {vetoResult.heritage_failure_ids.map((id) => (
                <Badge key={id} variant="destructive" className="font-mono text-xs">
                  {id}
                </Badge>
              ))}
            </div>
          </div>

          {/* Environment comparison */}
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">
              Environment Comparison
            </Label>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs h-8 w-32">Parameter</TableHead>
                  <TableHead className="text-xs h-8">Failure Env</TableHead>
                  <TableHead className="text-xs h-8">Query Env</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <EnvComparisonRow
                  label="Temperature (C)"
                  failureVal={failureEnvironment.temperature_c}
                  queryVal={queryEnvironment.temperature_c}
                />
                <EnvComparisonRow
                  label="Pressure (kPa)"
                  failureVal={failureEnvironment.pressure_kpa}
                  queryVal={queryEnvironment.pressure_kpa}
                />
                <EnvComparisonRow
                  label="Fluid Medium"
                  failureVal={failureEnvironment.fluid_medium}
                  queryVal={queryEnvironment.fluid_medium}
                />
                <EnvComparisonRow
                  label="O2 %"
                  failureVal={failureEnvironment.o2_pct}
                  queryVal={queryEnvironment.o2_pct}
                />
              </TableBody>
            </Table>
          </div>

          {/* Envelope match details */}
          {firstDetail && (
            <div>
              <Label className="text-xs text-muted-foreground mb-1 block">
                Envelope Overlap Details
              </Label>
              <div className="grid grid-cols-3 gap-2 text-xs">
                {["temperature", "pressure", "media"].map((dim) => {
                  const d = firstDetail[dim] as Record<string, unknown> | undefined;
                  if (!d) return null;
                  const match = d.match as boolean;
                  return (
                    <div
                      key={dim}
                      className={`rounded p-2 border ${
                        match
                          ? "border-red-200 bg-red-50"
                          : "border-green-200 bg-green-50"
                      }`}
                    >
                      <span className="font-medium capitalize">{dim}</span>
                      <br />
                      <span className={match ? "text-red-700" : "text-green-700"}>
                        {match ? "OVERLAP" : "No overlap"}
                      </span>
                      {d.reason && (
                        <p className="text-muted-foreground mt-0.5 text-[10px]">
                          {String(d.reason)}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Engineer acknowledgment form */}
          <div className="border-t pt-4 space-y-3">
            <h4 className="text-sm font-semibold">Engineer Acknowledgment</h4>

            <div>
              <Label htmlFor="engineer-name" className="text-xs">
                Engineer Name <span className="text-red-500">*</span>
              </Label>
              <Input
                id="engineer-name"
                value={engineerName}
                onChange={(e) => setEngineerName(e.target.value)}
                placeholder="Full name"
                className="mt-1"
              />
            </div>

            <div>
              <Label htmlFor="engineer-rationale" className="text-xs">
                Rationale (min 10 characters) <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="engineer-rationale"
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                placeholder="Explain why this heritage failure does not apply to the current use case..."
                className="mt-1 min-h-[80px]"
              />
              <p className="text-xs text-muted-foreground mt-1">
                {rationale.length}/10 characters minimum
              </p>
            </div>

            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}
          </div>
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>
            Return to Query
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleSubmit}
            disabled={!isValid || isSubmitting}
            className="bg-red-600 hover:bg-red-700"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Submitting...
              </>
            ) : (
              "Acknowledge and Proceed"
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
