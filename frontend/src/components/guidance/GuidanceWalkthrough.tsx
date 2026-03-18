/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.3 — GuidanceWalkthrough
 *
 * Sequential field tour in training mode. Highlights current, dims others,
 * floating panel. Active only when mode === 'training'.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { GuidanceModeName } from '@/lib/guidance/types';
import type { TelemetryEmitter } from '@/lib/guidance/telemetry';

interface WalkthroughStep {
  fieldName: string;
  label: string;
  guidance: string;
}

interface GuidanceWalkthroughProps {
  steps: WalkthroughStep[];
  module: string;
  mode: GuidanceModeName;
  telemetry?: TelemetryEmitter;
  onComplete?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export function GuidanceWalkthrough({
  steps,
  module,
  mode,
  telemetry,
  onComplete,
  onDismiss,
  className,
}: GuidanceWalkthroughProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const startTimeRef = useRef(Date.now());

  // Only active in training mode
  if (mode !== 'training' || dismissed || steps.length === 0) return null;

  const step = steps[currentStep];
  const isLast = currentStep === steps.length - 1;
  const isFirst = currentStep === 0;

  function handleNext() {
    if (isLast) {
      const duration = Date.now() - startTimeRef.current;
      telemetry?.walkthroughCompleted(module, duration);
      onComplete?.();
      setDismissed(true);
    } else {
      setCurrentStep((s) => s + 1);
    }
  }

  function handlePrev() {
    if (!isFirst) setCurrentStep((s) => s - 1);
  }

  function handleDismiss() {
    telemetry?.walkthroughAbandoned(module, step.fieldName);
    onDismiss?.();
    setDismissed(true);
  }

  return (
    <div
      className={cn(
        'fixed bottom-6 left-1/2 z-50 w-96 -translate-x-1/2 rounded-lg border border-border bg-background p-4 shadow-lg',
        className,
      )}
      role="dialog"
      aria-label={`Walkthrough step ${currentStep + 1} of ${steps.length}`}
    >
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">
          Step {currentStep + 1} of {steps.length}
        </span>
        <button
          type="button"
          onClick={handleDismiss}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
          aria-label="Dismiss walkthrough"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Content */}
      <div className="mb-3 space-y-1">
        <div className="text-sm font-semibold text-foreground">{step.label}</div>
        <p className="text-xs leading-relaxed text-muted-foreground">{step.guidance}</p>
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={handlePrev}
          disabled={isFirst}
          className={cn(
            'inline-flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors',
            isFirst
              ? 'text-muted-foreground/40'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <ArrowLeft className="h-3 w-3" />
          Back
        </button>

        {/* Progress dots */}
        <div className="flex gap-1">
          {steps.map((_, i) => (
            <div
              key={i}
              className={cn(
                'h-1.5 w-1.5 rounded-full transition-colors',
                i === currentStep ? 'bg-primary' : 'bg-muted-foreground/30',
              )}
            />
          ))}
        </div>

        <button
          type="button"
          onClick={handleNext}
          className="inline-flex items-center gap-1 rounded bg-primary px-2 py-1 text-xs text-primary-foreground transition-colors hover:bg-primary/90"
        >
          {isLast ? 'Finish' : 'Next'}
          {!isLast && <ArrowRight className="h-3 w-3" />}
        </button>
      </div>
    </div>
  );
}
