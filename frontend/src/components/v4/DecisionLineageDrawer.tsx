import { useState } from "react";
import { Copy, Check, ChevronDown, ChevronRight, Hash, Shield, FileText } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { IntentDisagreementIndicator } from "./IntentDisagreementIndicator";
import type { V4QueryResponse } from "@/lib/api";

interface DecisionLineageDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lineage: V4QueryResponse;
}

function CopyableHash({ label, hash }: { label: string; hash: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(hash);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground w-20 shrink-0">{label}</span>
      <code className="text-xs font-mono bg-muted px-2 py-1 rounded truncate flex-1">
        {hash.slice(0, 16)}...{hash.slice(-8)}
      </code>
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0"
        onClick={handleCopy}
      >
        {copied ? (
          <Check className="h-3 w-3 text-green-600" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
      </Button>
    </div>
  );
}

function GateStatusCard({
  title,
  status,
  details,
}: {
  title: string;
  status: string;
  details: string;
}) {
  const isPass = status === "PROCEED" || status === "PASS";
  const isRefuse = status === "REFUSE";

  return (
    <Card className="p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium">{title}</span>
        <Badge
          variant="outline"
          className={
            isPass
              ? "bg-green-50 text-green-700 border-green-200"
              : isRefuse
              ? "bg-red-50 text-red-700 border-red-200"
              : "bg-yellow-50 text-yellow-700 border-yellow-200"
          }
        >
          {status}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground">{details}</p>
    </Card>
  );
}

export function DecisionLineageDrawer({
  open,
  onOpenChange,
  lineage,
}: DecisionLineageDrawerProps) {
  const [queryExpanded, setQueryExpanded] = useState(false);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-lg overflow-y-auto">
        <SheetHeader className="mb-4">
          <SheetTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Decision Lineage
          </SheetTitle>
          <p className="text-xs text-muted-foreground font-mono">
            {lineage.lineage_id}
          </p>
        </SheetHeader>

        <div className="space-y-6">
          {/* Section 1: Provenance Hashes */}
          <section>
            <h3 className="text-sm font-semibold flex items-center gap-1.5 mb-2">
              <Hash className="h-4 w-4" />
              Provenance
            </h3>
            <div className="space-y-2">
              <CopyableHash label="Query Hash" hash={lineage.query_hash || ""} />
              <CopyableHash label="Snapshot" hash={lineage.snapshot_hash || ""} />
            </div>
          </section>

          {/* Section 2: Confidence */}
          <section>
            <h3 className="text-sm font-semibold flex items-center gap-1.5 mb-2">
              <Shield className="h-4 w-4" />
              Confidence
            </h3>
            <div className="mb-2">
              <ConfidenceBadge
                score={lineage.confidence.score}
                gate_action={lineage.confidence.gate_action}
                safety_critical={lineage.confidence.safety_critical}
                penalty_details={lineage.confidence.penalty_details}
              />
            </div>
            {/* Full penalty table */}
            {lineage.confidence.penalty_details.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs h-7">Penalty Type</TableHead>
                    <TableHead className="text-xs h-7 w-16 text-right">Value</TableHead>
                    <TableHead className="text-xs h-7">Explanation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lineage.confidence.penalty_details.map((p, i) => (
                    <TableRow key={i}>
                      <TableCell className="text-xs py-1 font-mono">
                        {p.penalty_type}
                      </TableCell>
                      <TableCell className="text-xs py-1 text-right font-mono text-red-600">
                        -{p.penalty_value.toFixed(3)}
                      </TableCell>
                      <TableCell className="text-xs py-1 text-muted-foreground">
                        {p.explanation}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
              {lineage.confidence.explanation}
            </p>
          </section>

          {/* Section 3: Gate Decisions */}
          <section>
            <h3 className="text-sm font-semibold mb-2">Gate Decisions</h3>
            <div className="space-y-2">
              {lineage.batch_gate && (
                <GateStatusCard
                  title="Batch Safety Gate"
                  status={lineage.batch_gate.action}
                  details={lineage.batch_gate.reason}
                />
              )}
              {lineage.heritage_veto && (
                <GateStatusCard
                  title="Heritage Veto"
                  status={lineage.heritage_veto.vetoed ? "VETOED" : "CLEAR"}
                  details={
                    lineage.heritage_veto.vetoed
                      ? `${lineage.heritage_veto.heritage_failure_ids.length} matching failure(s). ${
                          lineage.heritage_veto.requires_acknowledgment
                            ? "Requires acknowledgment."
                            : `Rank penalty: -${lineage.heritage_veto.rank_penalty}`
                        }`
                      : "No heritage failures match the query envelope."
                  }
                />
              )}
              {lineage.dirty_data && (
                <GateStatusCard
                  title="Data Quality"
                  status={lineage.dirty_data.tier.toUpperCase()}
                  details={
                    lineage.dirty_data.user_message ||
                    `${lineage.dirty_data.dirty_records}/${lineage.dirty_data.total_records} non-typed records (${Math.round(lineage.dirty_data.dirty_fraction * 100)}%)`
                  }
                />
              )}
            </div>
          </section>

          {/* Section 4: Intent */}
          {lineage.intent_disagreement && (
            <section>
              <h3 className="text-sm font-semibold mb-2">Intent Classification</h3>
              <IntentDisagreementIndicator
                disagreement={lineage.intent_disagreement}
              />
            </section>
          )}

          {/* Section 5: Parsed Query */}
          <section>
            <Collapsible open={queryExpanded} onOpenChange={setQueryExpanded}>
              <CollapsibleTrigger className="flex items-center gap-1.5 text-sm font-semibold hover:text-primary transition-colors">
                {queryExpanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                Parsed Query
              </CollapsibleTrigger>
              <CollapsibleContent>
                <pre className="mt-2 p-3 bg-muted rounded-md text-xs font-mono overflow-x-auto max-h-64 overflow-y-auto">
                  {JSON.stringify(lineage.parsed_query, null, 2)}
                </pre>
              </CollapsibleContent>
            </Collapsible>
          </section>

          {/* Footer */}
          <div className="border-t pt-3 text-xs text-muted-foreground space-y-1">
            <div className="flex justify-between">
              <span>Schema Version</span>
              <span className="font-mono">{lineage.schema_version}</span>
            </div>
            <div className="flex justify-between">
              <span>Timestamp</span>
              <span className="font-mono">
                {lineage.timestamp
                  ? new Date(lineage.timestamp).toLocaleString()
                  : "N/A"}
              </span>
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
