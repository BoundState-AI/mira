/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.3 — GuidanceContextIndicator
 *
 * Shows active context: what program, what environment, what upstream
 * verdicts inform this view.
 */

import React from 'react';
import { Info, Shield, Zap } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type { GuidanceContext, UpstreamVerdict } from '@/lib/guidance/types';

interface GuidanceContextIndicatorProps {
  context: GuidanceContext;
  className?: string;
}

const verdictColors: Record<string, string> = {
  PASS: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  CONDITIONAL_PASS: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  FAIL: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  PROHIBITED: 'bg-red-200 text-red-900 dark:bg-red-950 dark:text-red-100',
};

export function GuidanceContextIndicator({
  context,
  className,
}: GuidanceContextIndicatorProps) {
  const upstreamEntries = context.upstream_verdicts
    ? Object.entries(context.upstream_verdicts).filter(
        (entry): entry is [string, UpstreamVerdict] => entry[1] !== null,
      )
    : [];

  return (
    <div className={cn('flex flex-wrap items-center gap-1.5 text-[11px]', className)}>
      {/* Program / Center */}
      {context.program && (
        <Badge variant="outline" className="px-1.5 py-0 text-[10px] font-normal">
          {context.program}
          {context.center ? ` / ${context.center}` : ''}
        </Badge>
      )}

      {/* Hardware class */}
      {context.hardware_class === 'human_rated' && (
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge variant="outline" className="gap-0.5 px-1.5 py-0 text-[10px] font-medium text-orange-700 dark:text-orange-300">
                <Shield className="h-2.5 w-2.5" />
                Human Rated
              </Badge>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              Enhanced guidance active for human-rated hardware
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}

      {/* Service environment */}
      {context.service_environment && (
        <Badge variant="outline" className="gap-0.5 px-1.5 py-0 text-[10px] font-normal">
          <Zap className="h-2.5 w-2.5" />
          {context.service_environment}
          {context.pressure_regime ? ` (${context.pressure_regime})` : ''}
        </Badge>
      )}

      {/* Upstream verdicts */}
      {upstreamEntries.map(([engine, verdict]) => (
        <TooltipProvider key={engine} delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge
                variant="outline"
                className={cn(
                  'px-1.5 py-0 text-[10px] font-medium',
                  verdictColors[verdict.verdict] ?? '',
                )}
              >
                {engine.toUpperCase()}: {verdict.verdict.replace(/_/g, ' ')}
              </Badge>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-64 space-y-1 text-xs">
              <div className="font-semibold">{engine.toUpperCase()} verdict</div>
              {verdict.material && <div>Material: {verdict.material}</div>}
              {verdict.environment && <div>Environment: {verdict.environment}</div>}
              {verdict.mitigations != null && (
                <div>Mitigations: {verdict.mitigations}</div>
              )}
              {verdict.gaps && verdict.gaps.length > 0 && (
                <div>Gaps: {verdict.gaps.join(', ')}</div>
              )}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ))}

      {/* Mode indicator */}
      <Badge
        variant="secondary"
        className="px-1.5 py-0 text-[10px] font-normal capitalize"
      >
        {context.user_mode}
      </Badge>
    </div>
  );
}
