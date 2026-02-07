import { AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { V4IntentDisagreementResponse } from "@/lib/api";

interface IntentDisagreementIndicatorProps {
  disagreement: V4IntentDisagreementResponse;
}

export function IntentDisagreementIndicator({
  disagreement,
}: IntentDisagreementIndicatorProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant="outline"
          className="cursor-help gap-1 px-2 py-0.5 text-xs border-orange-300 bg-orange-50 text-orange-700"
        >
          <AlertCircle className="h-3 w-3" />
          Intent Override
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-sm">
        <div className="space-y-1.5 text-xs">
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Sonnet classified:</span>
            <span className="font-mono">{disagreement.sonnet_intent}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Heuristic classified:</span>
            <span className="font-mono">{disagreement.heuristic_intent}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Used (conservative):</span>
            <span className="font-mono font-bold">{disagreement.chosen_intent}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">Penalty:</span>
            <span className="font-mono text-red-600">
              -{disagreement.penalty_applied.toFixed(2)}
            </span>
          </div>
          <p className="pt-1 border-t text-muted-foreground leading-relaxed">
            {disagreement.explanation}
          </p>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
