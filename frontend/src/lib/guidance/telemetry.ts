/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.5 — Telemetry Event Model
 *
 * Value-redacted event emitter with kill switch support.
 * Per Section 5.5.2: NEVER include actual user-entered values.
 */

import type {
  GuidanceTelemetryEvent,
  GuidanceTelemetryEventType,
  GuidanceTelemetryHandler,
  GuidanceModeName,
  ValidationSeverity,
  WarningSeverity,
} from './types';

function makeEvent(
  type: GuidanceTelemetryEventType,
  payload: Omit<GuidanceTelemetryEvent, 'type' | 'timestamp'>,
): GuidanceTelemetryEvent {
  return { type, timestamp: new Date().toISOString(), ...payload };
}

/**
 * Create a scoped telemetry emitter. When `enabled` is false, all calls are
 * no-ops — the kill switch severs the event pipeline entirely (Section 5.1).
 */
export function createTelemetryEmitter(
  handler: GuidanceTelemetryHandler | undefined,
  enabled: boolean,
) {
  function emit(event: GuidanceTelemetryEvent) {
    if (!enabled || !handler) return;
    handler(event);
  }

  return {
    /** Section 5.5.1 — guidance.viewed */
    viewed(field: string, tab: 'what' | 'why' | 'how' | 'do') {
      emit(makeEvent('guidance.viewed', { field, tab }));
    },

    /** Section 5.5.1 — guidance.authority.expanded */
    authorityExpanded(field: string, authorityRef: string) {
      emit(makeEvent('guidance.authority.expanded', { field, authority_ref: authorityRef }));
    },

    /** Section 5.5.1 — guidance.warning.dismissed */
    warningDismissed(field: string, conditionRef: string) {
      emit(makeEvent('guidance.warning.dismissed', { field, condition_ref: conditionRef }));
    },

    /** Section 5.5.1 — guidance.action.clicked */
    actionClicked(field: string, actionType: string, target: string) {
      emit(makeEvent('guidance.action.clicked', { field, action_type: actionType, target }));
    },

    /** Section 5.5.1 — guidance.lookup.opened */
    lookupOpened(field: string, source: string) {
      emit(makeEvent('guidance.lookup.opened', { field, source }));
    },

    /** Section 5.5.1 — guidance.heritage.confirmed */
    heritageConfirmed(field: string, confidence: number) {
      emit(makeEvent('guidance.heritage.confirmed', { field, extraction_confidence: confidence }));
    },

    /** Section 5.5.1 — guidance.heritage.rejected */
    heritageRejected(field: string, confidence: number) {
      emit(makeEvent('guidance.heritage.rejected', { field, extraction_confidence: confidence }));
    },

    /**
     * Section 5.5.1 — guidance.validation.failed
     * Per Section 5.5.2: logs field, rule, severity ONLY — NEVER the entered value.
     */
    validationFailed(field: string, rule: string, severity: ValidationSeverity) {
      emit(makeEvent('guidance.validation.failed', { field, rule, severity }));
    },

    /** Section 5.5.1 — guidance.walkthrough.completed */
    walkthroughCompleted(module: string, durationMs: number) {
      emit(makeEvent('guidance.walkthrough.completed', { module, duration: durationMs }));
    },

    /** Section 5.5.1 — guidance.walkthrough.abandoned */
    walkthroughAbandoned(module: string, stepReached: string) {
      emit(makeEvent('guidance.walkthrough.abandoned', { module, step_reached: stepReached }));
    },

    /** Section 5.5.1 — guidance.mode.changed */
    modeChanged(oldMode: GuidanceModeName, newMode: GuidanceModeName, trigger: string) {
      emit(makeEvent('guidance.mode.changed', { old_mode: oldMode, new_mode: newMode, trigger }));
    },

    /** Section 5.5.1 — guidance.schema.verified */
    schemaVerified(packId: string, version: string) {
      emit(makeEvent('guidance.schema.verified', { pack_id: packId, version }));
    },

    /** Section 5.5.1 — guidance.schema.stale */
    schemaStale(packId: string, loadedVersion: string, latestVersion: string) {
      emit(makeEvent('guidance.schema.stale', {
        pack_id: packId,
        loaded_version: loadedVersion,
        latest_version: latestVersion,
      }));
    },
  };
}

export type TelemetryEmitter = ReturnType<typeof createTelemetryEmitter>;
