/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.3 — GuidanceValidationIndicator
 *
 * Visual state: green/yellow/red/gray. Inline message. Severity-aware.
 *
 * Accessibility (Section 5.4):
 * - High-contrast mode support
 * - Screen reader announces state changes via aria-live
 */

import React from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, Info, Loader2 } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { ValidationSeverity } from '@/lib/guidance/types';

interface GuidanceValidationIndicatorProps {
  state: 'valid' | 'invalid' | 'warning' | 'pending';
  message?: string;
  severity?: ValidationSeverity;
  className?: string;
}

const stateConfig = {
  valid: {
    icon: CheckCircle2,
    color: 'text-green-600 dark:text-green-400',
    bg: '',
    label: 'Valid',
  },
  invalid: {
    icon: AlertCircle,
    color: 'text-destructive',
    bg: 'bg-destructive/5',
    label: 'Error',
  },
  warning: {
    icon: AlertTriangle,
    color: 'text-yellow-600 dark:text-yellow-400',
    bg: 'bg-yellow-50 dark:bg-yellow-950/30',
    label: 'Warning',
  },
  pending: {
    icon: Loader2,
    color: 'text-muted-foreground',
    bg: '',
    label: 'Validating',
  },
} as const;

export function GuidanceValidationIndicator({
  state,
  message,
  severity,
  className,
}: GuidanceValidationIndicatorProps) {
  const config = stateConfig[state];
  const Icon = config.icon;

  if (state === 'valid' && !message) return null;

  return (
    <div
      className={cn(
        'flex items-start gap-1.5 rounded px-2 py-1 text-[11px] leading-relaxed',
        config.bg,
        className,
      )}
      role="status"
      aria-live="polite"
      aria-label={`${config.label}${message ? `: ${message}` : ''}`}
    >
      <Icon
        className={cn('mt-0.5 h-3 w-3 shrink-0', config.color, state === 'pending' && 'animate-spin')}
        aria-hidden
      />
      {message && <span className={config.color}>{message}</span>}
    </div>
  );
}
