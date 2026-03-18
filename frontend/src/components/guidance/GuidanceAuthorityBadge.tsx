/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.3 — GuidanceAuthorityBadge
 *
 * Governing standard badge. Hover shows full citation + last_verified date.
 * Click opens reference. Always visible, size varies by mode.
 * Local overlays visually grouped and indented (Section 3.5.5 Rule 7).
 *
 * Non-negotiable rules (Section 3.5.5):
 * - Rule 4: Authority badges MUST remain visible in Expert mode
 * - Rule 5: last_verified date on hover
 */

import React from 'react';

import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type {
  AuthorityRef,
  AuthorityRegistryEntry,
  GuidanceModeName,
} from '@/lib/guidance/types';
import type { TelemetryEmitter } from '@/lib/guidance/telemetry';

interface GuidanceAuthorityBadgeProps {
  authRef: AuthorityRef;
  authorityRegistry: Map<string, AuthorityRegistryEntry>;
  mode: GuidanceModeName;
  fieldName: string;
  telemetry?: TelemetryEmitter;
  compact?: boolean;
  className?: string;
}

const typeStyles: Record<string, string> = {
  requirement: 'font-bold',
  guidance: 'font-normal',
  best_practice: 'italic',
  local_policy: 'font-normal border-dashed',
};

export function GuidanceAuthorityBadge({
  authRef,
  authorityRegistry,
  mode,
  fieldName,
  telemetry,
  compact = false,
  className,
}: GuidanceAuthorityBadgeProps) {
  const entry = authorityRegistry.get(authRef.authority_ref);
  const label = entry
    ? compact
      ? entry.document_id
      : `${entry.document_id} ${entry.section}`
    : authRef.authority_ref;

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="outline"
            className={cn(
              'cursor-pointer select-none whitespace-nowrap',
              compact ? 'px-1 py-0 text-[9px]' : 'px-1.5 py-0.5 text-[10px]',
              typeStyles[authRef.type],
              authRef.relationship === 'overlay' && 'border-dashed',
              className,
            )}
            onClick={() => {
              telemetry?.authorityExpanded(fieldName, authRef.authority_ref);
            }}
          >
            {label}
          </Badge>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-72 space-y-1 text-xs">
          {entry ? (
            <>
              <div className="font-semibold">
                {entry.document_id} {entry.revision} — {entry.section}
              </div>
              {entry.requirement_id && (
                <div className="text-muted-foreground">{entry.requirement_id}</div>
              )}
              <div>{entry.boundstate_summary}</div>
              {/* Section 3.5.5 Rule 5: last_verified on hover */}
              <div className="text-[10px] text-muted-foreground">
                Last verified: {entry.last_verified}
              </div>
              {authRef.overlay_note && (
                <div className="text-[10px] italic text-muted-foreground">
                  {authRef.overlay_note}
                </div>
              )}
            </>
          ) : (
            <div>{authRef.authority_ref}</div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
