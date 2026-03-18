/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 3.8 / 5.3 — GuidanceHeritageBanner
 *
 * Shows auto-extraction provenance. Confirm action when unverified.
 *
 * When heritage is present:
 * - Training/Live: prominent banner showing extraction source and confidence
 * - Expert: subtle indicator, click to expand
 * - If user_confirmed is false: renders "Confirm" action button
 * - Low confidence (< 80%): triggers warning regardless of mode
 */

import React, { useState } from 'react';
import { CheckCircle2, FileSearch, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { GuidanceModeName } from '@/lib/guidance/types';
import type { TelemetryEmitter } from '@/lib/guidance/telemetry';

interface GuidanceHeritageBannerProps {
  source: string;
  confidence: number;
  confirmed: boolean;
  lowConfidence: boolean;
  displayTemplate?: string;
  mode: GuidanceModeName;
  fieldName: string;
  telemetry?: TelemetryEmitter;
  onConfirm?: () => void;
  onReject?: () => void;
  className?: string;
}

export function GuidanceHeritageBanner({
  source,
  confidence,
  confirmed,
  lowConfidence,
  displayTemplate,
  mode,
  fieldName,
  telemetry,
  onConfirm,
  onReject,
  className,
}: GuidanceHeritageBannerProps) {
  const [expanded, setExpanded] = useState(mode !== 'expert');

  // Build display message from template
  const message = displayTemplate
    ? displayTemplate
        .replace('{source}', source)
        .replace('{confidence}', String(Math.round(confidence * 100)))
    : `Extracted from ${source} (confidence: ${Math.round(confidence * 100)}%). Please verify.`;

  // Expert mode: subtle indicator
  if (mode === 'expert' && !lowConfidence && !expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className={cn(
          'flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground',
          className,
        )}
      >
        <FileSearch className="h-3 w-3" />
        <span>Auto-extracted</span>
      </button>
    );
  }

  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-md border px-3 py-2 text-xs',
        lowConfidence
          ? 'border-yellow-300 bg-yellow-50 text-yellow-800 dark:border-yellow-700 dark:bg-yellow-950 dark:text-yellow-200'
          : 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200',
        className,
      )}
      role="status"
    >
      <FileSearch className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <div className="flex-1 space-y-1.5">
        <p className="leading-relaxed">{message}</p>
        {!confirmed && (
          <div className="flex gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded border border-current px-2 py-0.5 text-[11px] font-medium transition-colors hover:bg-blue-100 dark:hover:bg-blue-900"
              onClick={() => {
                telemetry?.heritageConfirmed(fieldName, confidence);
                onConfirm?.();
              }}
            >
              <CheckCircle2 className="h-3 w-3" />
              Confirm
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded border border-current px-2 py-0.5 text-[11px] font-medium transition-colors hover:bg-red-100 dark:hover:bg-red-900"
              onClick={() => {
                telemetry?.heritageRejected(fieldName, confidence);
                onReject?.();
              }}
            >
              <X className="h-3 w-3" />
              Reject
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
