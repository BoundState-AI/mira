import { useCallback, useEffect, useState } from "react";
import {
  Bot,
  ClipboardList,
  FileText,
  Hash,
  Mic,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  ShieldQuestion,
  Type,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { fetchRecentAudit } from "@/lib/audit/auditApi";
import type { AuditRecord, AuditTurnModality, UserIdentity } from "@/lib/audit/types";
import { cn } from "@/lib/utils";

interface AuditDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessionId?: string | null;
  /** Bumping this triggers a re-fetch — wire to onTurnComplete from chat surfaces. */
  refreshKey?: number;
}

function formatTimestamp(value: string): string {
  if (!value) return "—";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function truncateHash(hash: string): string {
  if (!hash) return "—";
  const match = hash.match(/^(sha256:)?([0-9a-f]+)$/i);
  if (!match) return hash;
  const digest = match[2];
  if (digest.length <= 12) return hash;
  return `${match[1] ?? ""}${digest.slice(0, 8)}…${digest.slice(-4)}`;
}

function verdictTone(verdict: string): "default" | "secondary" | "destructive" | "outline" {
  switch (verdict) {
    case "PASS":
      return "default";
    case "CONDITIONAL_PASS":
      return "secondary";
    case "FAIL":
    case "ERROR":
    case "REFUSE":
      return "destructive";
    default:
      return "outline";
  }
}

function ModalityBadge({ modality }: { modality: AuditTurnModality }) {
  if (modality === "voice") {
    return (
      <Badge variant="outline" className="border-teal-300 bg-teal-50 text-teal-900">
        <Mic className="mr-1 h-3 w-3" />
        voice
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-slate-300 bg-slate-50 text-slate-700">
      <Type className="mr-1 h-3 w-3" />
      text
    </Badge>
  );
}

function IdentityHeader({ identity }: { identity: UserIdentity | null }) {
  if (!identity) {
    return (
      <div className="rounded-lg border border-amber-300/50 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        <ShieldQuestion className="mr-1 inline h-4 w-4" />
        Identity not recorded
      </div>
    );
  }
  const isPiv = identity.auth_method === "cognito+piv" || Boolean(identity.edipi);
  const primary = identity.username || identity.email || identity.sub.slice(0, 12);

  return (
    <div
      className={cn(
        "space-y-1 rounded-lg border px-3 py-2 text-sm",
        isPiv
          ? "border-emerald-300/60 bg-emerald-50 text-emerald-900"
          : "border-slate-300 bg-slate-50 text-slate-700",
      )}
    >
      <div className="flex items-center gap-2 font-medium">
        <ShieldCheck className={cn("h-4 w-4", isPiv ? "text-emerald-700" : "text-slate-500")} />
        <span>{primary}</span>
        <span className="ml-auto text-[10px] uppercase tracking-[0.16em] opacity-70">
          {identity.auth_method}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs opacity-90">
        {identity.email ? <div className="col-span-2">{identity.email}</div> : null}
        {identity.edipi ? <div>EDIPI {identity.edipi}</div> : null}
        {identity.agency ? <div>{identity.agency}</div> : null}
        {identity.role ? <div>Role: {identity.role}</div> : null}
        {identity.itar_access ? <div>ITAR: {identity.itar_access}</div> : null}
      </div>
      {identity.piv_subject ? (
        <div className="break-all rounded bg-white/60 px-2 py-1 font-mono text-[10px] text-emerald-950">
          {identity.piv_subject}
        </div>
      ) : null}
    </div>
  );
}

function AuditEntry({ record }: { record: AuditRecord }) {
  const citations = record.source_citations ?? [];
  const authority = record.authority_basis ?? [];
  return (
    <div className="space-y-2 rounded-lg border border-border bg-background p-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono text-[11px] text-muted-foreground">{record.audit_id}</span>
        <ModalityBadge modality={record.turn_modality} />
        {record.engine_status ? (
          <Badge variant={verdictTone(record.engine_status)}>{record.engine_status}</Badge>
        ) : null}
        {record.fine_routing ? (
          <Badge variant="outline" className="border-slate-300 bg-slate-50">
            <Bot className="mr-1 h-3 w-3" />
            {record.fine_routing}
          </Badge>
        ) : null}
        <span className="ml-auto text-[11px] text-muted-foreground">
          {formatTimestamp(record.timestamp)}
        </span>
      </div>

      {record.user_input ? (
        <div className="rounded bg-slate-50 px-2 py-1.5 text-sm">
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Question</div>
          <div className="mt-0.5 text-slate-900">{record.user_input}</div>
        </div>
      ) : null}

      {citations.length ? (
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            <ScrollText className="mr-1 inline h-3 w-3" />
            Citations ({citations.length})
          </div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-800">
            {citations.map((cite, idx) => (
              <li key={`${record.audit_id}-cite-${idx}`} className="break-words">
                {cite}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {authority.length ? (
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
            <FileText className="mr-1 inline h-3 w-3" />
            Authority basis
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            {authority.map((item, idx) => (
              <Badge key={`${record.audit_id}-auth-${idx}`} variant="secondary" className="text-[10px]">
                {item}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3 border-t border-border/60 pt-2 text-[11px] text-muted-foreground">
        <span title={record.response_hash}>
          <Hash className="mr-1 inline h-3 w-3" />
          {truncateHash(record.response_hash)}
        </span>
        {record.llm_model_used ? <span>model: {record.llm_model_used}</span> : null}
        {record.session_id ? <span>session: {record.session_id}</span> : null}
      </div>
    </div>
  );
}

export function AuditDrawer({ open, onOpenChange, sessionId, refreshKey }: AuditDrawerProps) {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userSub, setUserSub] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchRecentAudit({ limit: 20, sessionId });
      setRecords(data.records);
      setUserSub(data.user_sub);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit history");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, load, refreshKey]);

  const identityFromTopRecord = records[0]?.user_identity ?? null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full max-w-[480px] sm:max-w-[520px]">
        <SheetHeader className="space-y-1">
          <SheetTitle className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5" />
            Audit trail
          </SheetTitle>
          <SheetDescription>
            Every chat turn — text or voice — is bound to the authenticated caller, citation
            chain, and content hash. This drawer shows your recent turns.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4">
          <IdentityHeader identity={identityFromTopRecord} />
        </div>

        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="text-xs text-muted-foreground">
            {userSub ? `Filtered to your identity (sub: ${userSub.slice(0, 12)}…)` : "Showing recent turns"}
            {records.length ? ` · ${records.length} record${records.length === 1 ? "" : "s"}` : ""}
          </div>
          <Button type="button" variant="ghost" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("mr-1 h-3.5 w-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>

        {error ? (
          <div className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <Separator className="my-3" />

        <ScrollArea className="h-[calc(100vh-18rem)] pr-3">
          <div className="space-y-3">
            {records.length === 0 && !loading ? (
              <div className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
                No audit records yet. Ask MIRA a question to populate the trail.
              </div>
            ) : null}
            {records.map((record) => (
              <AuditEntry key={record.audit_id} record={record} />
            ))}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
