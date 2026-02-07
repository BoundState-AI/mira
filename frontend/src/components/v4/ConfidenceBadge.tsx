import { useState } from "react";
import { ChevronDown, ChevronUp, Shield, ShieldAlert, ShieldX } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { V4GateAction, V4PenaltyDetail } from "@/lib/api";

interface ConfidenceBadgeProps {
  score: number;
  gate_action: V4GateAction;
  safety_critical: boolean;
  penalty_details: V4PenaltyDetail[];
}

function getGateColor(gate_action: V4GateAction): string {
  switch (gate_action) {
    case "PASS":
      return "bg-green-100 text-green-800 border-green-300 hover:bg-green-200";
    case "CLARIFY":
      return "bg-yellow-100 text-yellow-800 border-yellow-300 hover:bg-yellow-200";
    case "REFUSE":
      return "bg-red-100 text-red-800 border-red-300 hover:bg-red-200";
    default:
      return "";
  }
}

function getGateIcon(gate_action: V4GateAction) {
  switch (gate_action) {
    case "PASS":
      return <Shield className="h-3.5 w-3.5" />;
    case "CLARIFY":
      return <ShieldAlert className="h-3.5 w-3.5" />;
    case "REFUSE":
      return <ShieldX className="h-3.5 w-3.5" />;
    default:
      return null;
  }
}

export function ConfidenceBadge({
  score,
  gate_action,
  safety_critical,
  penalty_details,
}: ConfidenceBadgeProps) {
  const [open, setOpen] = useState(false);
  const threshold = safety_critical ? 0.85 : 0.70;
  const pct = Math.round(score * 100);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Badge
          variant="outline"
          className={`cursor-pointer gap-1.5 px-3 py-1 text-sm font-medium transition-colors ${getGateColor(gate_action)}`}
        >
          {getGateIcon(gate_action)}
          <span>{pct}%</span>
          <span className="text-xs opacity-70">{gate_action}</span>
          {open ? (
            <ChevronUp className="h-3 w-3 ml-0.5" />
          ) : (
            <ChevronDown className="h-3 w-3 ml-0.5" />
          )}
        </Badge>
      </PopoverTrigger>
      <PopoverContent className="w-96" align="start">
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-sm">Confidence Breakdown</h4>
            <span className="text-xs text-muted-foreground">
              Threshold: {Math.round(threshold * 100)}%
              {safety_critical ? " (safety-critical)" : " (general)"}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex-1 h-2.5 bg-muted rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  gate_action === "PASS"
                    ? "bg-green-500"
                    : gate_action === "CLARIFY"
                    ? "bg-yellow-500"
                    : "bg-red-500"
                }`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-sm font-mono font-bold w-12 text-right">
              {score.toFixed(2)}
            </span>
          </div>

          {penalty_details.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs h-8">Penalty</TableHead>
                  <TableHead className="text-xs h-8 w-16 text-right">Value</TableHead>
                  <TableHead className="text-xs h-8">Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {penalty_details.map((p, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs py-1.5 font-mono">
                      {p.penalty_type}
                    </TableCell>
                    <TableCell className="text-xs py-1.5 text-right font-mono text-red-600">
                      -{p.penalty_value.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-xs py-1.5 text-muted-foreground max-w-[180px] truncate">
                      {p.explanation}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {penalty_details.length === 0 && (
            <p className="text-xs text-muted-foreground italic">
              No penalties applied - full confidence.
            </p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
