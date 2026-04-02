import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { MODULE_UNAVAILABLE_NOTICE } from "@/lib/moduleAvailability";
import { cn } from "@/lib/utils";

interface TemporarilyUnavailableNoticeProps {
  moduleName: string;
  className?: string;
}

interface ModuleAvailabilityGateProps {
  unavailable: boolean;
  children: ReactNode;
  className?: string;
}

export function TemporarilyUnavailableNotice({
  moduleName,
  className,
}: TemporarilyUnavailableNoticeProps) {
  return (
    <Alert
      className={cn(
        "border-amber-300 bg-amber-50 text-amber-950 [&>svg]:text-amber-700",
        className,
      )}
    >
      <AlertTriangle className="h-4 w-4" />
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant="outline"
            className="border-amber-300 bg-amber-100 text-amber-900"
          >
            {MODULE_UNAVAILABLE_NOTICE.badge}
          </Badge>
          <span className="text-sm font-medium">{moduleName}</span>
        </div>
        <div>
          <AlertTitle>{MODULE_UNAVAILABLE_NOTICE.title}</AlertTitle>
          <AlertDescription className="text-amber-950/90">
            {MODULE_UNAVAILABLE_NOTICE.description}
          </AlertDescription>
        </div>
      </div>
    </Alert>
  );
}

export function ModuleAvailabilityGate({
  unavailable,
  children,
  className,
}: ModuleAvailabilityGateProps) {
  if (!unavailable) {
    return <div className={className}>{children}</div>;
  }

  return (
    <fieldset disabled className={cn("min-w-0", className)}>
      <div className="pointer-events-none opacity-45 saturate-0">{children}</div>
    </fieldset>
  );
}
