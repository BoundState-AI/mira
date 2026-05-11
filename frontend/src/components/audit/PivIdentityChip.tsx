import { useEffect, useState } from "react";
import { ShieldCheck, ShieldQuestion, User2 } from "lucide-react";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { fetchWhoami } from "@/lib/audit/auditApi";
import type { UserIdentity } from "@/lib/audit/types";
import { cn } from "@/lib/utils";

interface PivIdentityChipProps {
  className?: string;
  compact?: boolean;
}

export function PivIdentityChip({ className, compact = false }: PivIdentityChipProps) {
  const [identity, setIdentity] = useState<UserIdentity | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchWhoami()
      .then((data) => {
        if (!cancelled) setIdentity(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "identity unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className={cn("inline-flex items-center gap-1.5 rounded-full border border-amber-300/50 bg-amber-50 px-2.5 py-1 text-[11px] text-amber-900", className)}>
        <ShieldQuestion className="h-3.5 w-3.5" />
        identity unavailable
      </div>
    );
  }

  if (!identity) {
    return null;
  }

  const isPiv = identity.auth_method === "cognito+piv" || Boolean(identity.edipi);
  const isAnonymous = identity.auth_method === "anonymous";

  if (isAnonymous) {
    return (
      <div className={cn("inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-600", className)}>
        <User2 className="h-3.5 w-3.5" />
        anonymous
      </div>
    );
  }

  const primaryName = identity.username || identity.email || identity.sub.slice(0, 8);
  const subtitleParts: string[] = [];
  if (identity.edipi) subtitleParts.push(`EDIPI ${identity.edipi}`);
  if (identity.agency) subtitleParts.push(identity.agency);
  const subtitle = subtitleParts.join(" · ");

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
              isPiv
                ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                : "border-slate-300 bg-slate-50 text-slate-700",
              className,
            )}
          >
            <ShieldCheck className={cn("h-3.5 w-3.5", isPiv ? "text-emerald-700" : "text-slate-500")} />
            <span className="truncate max-w-[14ch]">{primaryName}</span>
            {!compact && subtitle ? (
              <span className="opacity-80 hidden sm:inline">· {subtitle}</span>
            ) : null}
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-xs space-y-1 text-xs">
          <div className="font-semibold">{primaryName}</div>
          {identity.email ? <div>{identity.email}</div> : null}
          {identity.edipi ? <div>EDIPI: {identity.edipi}</div> : null}
          {identity.piv_subject ? (
            <div className="break-all opacity-80">{identity.piv_subject}</div>
          ) : null}
          {identity.agency ? <div>Agency: {identity.agency}</div> : null}
          {identity.role ? <div>Role: {identity.role}</div> : null}
          <div className="pt-1 opacity-80">auth: {identity.auth_method}</div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
