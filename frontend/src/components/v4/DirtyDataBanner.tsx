import { AlertTriangle, XOctagon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { V4DirtyDataTier } from "@/lib/api";

interface DirtyDataBannerProps {
  tier: V4DirtyDataTier;
  dirtyFraction: number;
  userMessage: string | null;
  totalRecords: number;
  dirtyRecords: number;
}

export function DirtyDataBanner({
  tier,
  dirtyFraction,
  userMessage,
  totalRecords,
  dirtyRecords,
}: DirtyDataBannerProps) {
  if (tier === "clean") return null;

  const pct = Math.round(dirtyFraction * 100);

  if (tier === "refuse") {
    return (
      <Alert variant="destructive" className="mb-4">
        <XOctagon className="h-4 w-4" />
        <AlertTitle>Data Quality: REFUSE ({pct}% non-typed)</AlertTitle>
        <AlertDescription>
          <p className="mb-2">
            {userMessage ||
              `${dirtyRecords} of ${totalRecords} records contain non-typed data (>${30}% threshold). Property display is blocked for this query.`}
          </p>
          <p className="text-xs opacity-80">
            Per BuildSpec Section 3.2, queries with &gt;30% dirty records are
            refused for the affected property. Refine your query or request
            typed data from the source.
          </p>
        </AlertDescription>
      </Alert>
    );
  }

  // DEGRADED tier
  return (
    <Alert className="mb-4 border-yellow-300 bg-yellow-50 text-yellow-900 [&>svg]:text-yellow-600">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>Data Quality: DEGRADED ({pct}% non-typed)</AlertTitle>
      <AlertDescription>
        {userMessage ||
          `${dirtyRecords} of ${totalRecords} records contain non-typed data. Results are shown but confidence has been reduced.`}
      </AlertDescription>
    </Alert>
  );
}
