/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 3.8 / 5.3 — GuidanceHeritageBanner
 *
 * Shows auto-extraction provenance. Confirm action when unverified.
 *
 * When heritage is present:
 * - Training: full explanation banner with source, confidence, and message
 * - Live/Expert: compact badge (source + confidence), click to expand
 * - If user_confirmed is false: renders "Confirm"/"Reject" action buttons
 * - Low confidence (< 80%): triggers full warning banner regardless of mode
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
  // Training starts expanded (full banner), Live/Expert start compact
  const [expanded, setExpanded] = useState(mode === 'training');

  // Build display message from template
  const message = displayTemplate
    ? displayTemplate
        .replace('{source}', source)
        .replace('{confidence}', String(Math.round(confidence * 100)))
    : `Extracted from ${source} (confidence: ${Math.round(confidence * 100)}%). Please verify.`;

  // Expert/Live collapsed: subtle indicator (click to expand)
  // Expert: always compact badge unless low confidence
  // Live: compact badge unless low confidence
  const isCompactMode = mode === 'expert' || mode === 'live';

  if (isCompactMode && !lowConfidence && !expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors',
          className,
        )}
      >
        <FileSearch className="h-3 w-3 shrink-0" />
        <span className="font-medium">{source}</span>
        <span className="text-muted-foreground/70">
          {Math.round(confidence * 100)}%
        </span>
        {!confirmed && (
          <>
            <span className="mx-0.5 text-muted-foreground/40">|</span>
            <span
              className="font-medium text-primary hover:underline"
              onClick={(e) => {
                e.stopPropagation();
                telemetry?.heritageConfirmed(fieldName, confidence);
                onConfirm?.();
              }}
            >
              Confirm
            </span>
            <span
              className="font-medium text-destructive hover:underline"
              onClick={(e) => {
                e.stopPropagation();
                telemetry?.heritageRejected(fieldName, confidence);
                onReject?.();
              }}
            >
              Reject
            </span>
          </>
        )}
      </button>
    );
  }

  // Training: full explanation banner
  // Also shown when low confidence (any mode) or when compact mode is expanded
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
