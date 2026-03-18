/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.1/5.2 — GuidanceProvider
 *
 * Context provider. Loads schema, manages mode, locale, context, event
 * dispatch, and schema version verification.
 *
 * The GuidanceProvider is stateless regarding workflow data (Section 7).
 * The parent engine is responsible for persisting workflow state.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import type {
  AuthorityRegistryEntry,
  GuidanceContext,
  GuidanceFieldDefinition,
  GuidanceModeName,
  GuidancePack,
  GuidanceProviderProps,
  GuidanceTelemetryHandler,
  ModuleModeOverride,
} from '@/lib/guidance/types';
import { createTelemetryEmitter, type TelemetryEmitter } from '@/lib/guidance/telemetry';
import {
  evaluateCondition,
  getActiveActions,
  getActiveAuthorities,
  getActiveWarnings,
  getMinimumWarningSeverity,
  isFieldEnhanced,
  isFieldRequired,
  isFieldVisible,
} from '@/lib/guidance/context';

// ---------------------------------------------------------------------------
// Context value
// ---------------------------------------------------------------------------

export interface GuidanceContextValue {
  /** The loaded guidance pack */
  schema: GuidancePack;
  /** Current application context */
  context: GuidanceContext;
  /** Active guidance mode */
  mode: GuidanceModeName;
  /** Active locale with fallback */
  locale: string;
  /** Whether schema is stale (backend unreachable) */
  schemaStale: boolean;
  /** Telemetry emitter (no-op when disabled) */
  telemetry: TelemetryEmitter;
  /** Authority registry for resolving authority_ref → full entry */
  authorityRegistry: Map<string, AuthorityRegistryEntry>;

  // Field evaluation helpers
  getField: (fieldName: string) => GuidanceFieldDefinition | undefined;
  isVisible: (fieldName: string) => boolean;
  isRequired: (fieldName: string) => boolean;
  isEnhanced: (fieldName: string) => boolean;
  getAuthorities: (fieldName: string) => ReturnType<typeof getActiveAuthorities>;
  getWarnings: (fieldName: string) => ReturnType<typeof getActiveWarnings>;
  getActions: (fieldName: string) => ReturnType<typeof getActiveActions>;
  getModuleOverride: () => ModuleModeOverride | undefined;
  getMinSeverity: () => ReturnType<typeof getMinimumWarningSeverity>;

  // Mode management
  requestModeChange: (newMode: GuidanceModeName, trigger: string) => void;
}

const GuidanceCtx = createContext<GuidanceContextValue | null>(null);

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useGuidance(): GuidanceContextValue {
  const ctx = useContext(GuidanceCtx);
  if (!ctx) {
    throw new Error('useGuidance must be used within a <GuidanceProvider>');
  }
  return ctx;
}

/**
 * Convenience hook to get guidance for a single field.
 * Returns null if the field doesn't exist in the schema.
 */
export function useFieldGuidance(fieldName: string) {
  const g = useGuidance();
  const field = g.getField(fieldName);
  if (!field) return null;

  return {
    field,
    visible: g.isVisible(fieldName),
    required: g.isRequired(fieldName),
    enhanced: g.isEnhanced(fieldName),
    authorities: g.getAuthorities(fieldName),
    warnings: g.getWarnings(fieldName),
    actions: g.getActions(fieldName),
    mode: g.mode,
    locale: g.locale,
    telemetry: g.telemetry,
    authorityRegistry: g.authorityRegistry,
    moduleOverride: g.getModuleOverride(),
    minSeverity: g.getMinSeverity(),
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GuidanceProvider({
  schema: initialSchema,
  context,
  mode: initialMode,
  locale = 'en',
  telemetryEnabled = true,
  onEvent,
  onModeChange,
  authorityRegistry = new Map(),
  children,
}: GuidanceProviderProps) {
  const [schema, setSchema] = useState(initialSchema);
  const [mode, setMode] = useState(initialMode);
  const [schemaStale, setSchemaStale] = useState(false);
  const legalDisclaimerShownRef = useRef(new Set<string>());

  // Update schema when prop changes (parent may fetch new pack)
  useEffect(() => {
    setSchema(initialSchema);
  }, [initialSchema]);

  // Update mode when prop changes
  useEffect(() => {
    setMode(initialMode);
  }, [initialMode]);

  // Telemetry emitter — kill switch via telemetryEnabled (Section 5.1)
  const telemetry = useMemo(
    () => createTelemetryEmitter(onEvent, telemetryEnabled),
    [onEvent, telemetryEnabled],
  );

  // Schema version handshake (Section 5.2)
  // On mount, verify schema currency against backend.
  // If backend unreachable, proceed with cached schema + stale flag.
  useEffect(() => {
    let cancelled = false;

    async function verifySchema() {
      try {
        // Attempt to check latest version from backend
        const res = await fetch(
          `/api/guidance/packs/${schema.guidance_pack_id}/version`,
          { signal: AbortSignal.timeout(5000) },
        );

        if (cancelled) return;

        if (res.ok) {
          const data = (await res.json()) as { version: string; pack?: GuidancePack };
          if (data.version !== schema.schema_version) {
            // Newer version available
            if (data.pack) {
              setSchema(data.pack);
            }
            telemetry.schemaStale(
              schema.guidance_pack_id,
              schema.schema_version,
              data.version,
            );
            setSchemaStale(true);
          } else {
            telemetry.schemaVerified(schema.guidance_pack_id, schema.schema_version);
            setSchemaStale(false);
          }
        } else {
          // Backend returned error — treat as unreachable
          setSchemaStale(false); // don't show stale warning if backend is down
        }
      } catch {
        // Backend unreachable — proceed with cached schema (Section 3.2)
        // Air-gapped deployments: suppress stale notification
        if (!cancelled) setSchemaStale(false);
      }
    }

    verifySchema();
    return () => { cancelled = true; };
  }, [schema.guidance_pack_id, schema.schema_version, telemetry]);

  // Field helpers
  const getField = useCallback(
    (fieldName: string) => schema.fields[fieldName],
    [schema],
  );

  const isVisible = useCallback(
    (fieldName: string) => {
      const field = schema.fields[fieldName];
      return field ? isFieldVisible(field, context) : false;
    },
    [schema, context],
  );

  const isRequired = useCallback(
    (fieldName: string) => {
      const field = schema.fields[fieldName];
      return field ? isFieldRequired(field, context) : false;
    },
    [schema, context],
  );

  const isEnhanced = useCallback(
    (fieldName: string) => {
      const field = schema.fields[fieldName];
      return field ? isFieldEnhanced(field, context) : false;
    },
    [schema, context],
  );

  const getAuthorities = useCallback(
    (fieldName: string) => {
      const field = schema.fields[fieldName];
      return field ? getActiveAuthorities(field, context) : [];
    },
    [schema, context],
  );

  const getWarnings = useCallback(
    (fieldName: string) => {
      const field = schema.fields[fieldName];
      return field ? getActiveWarnings(field, context) : [];
    },
    [schema, context],
  );

  const getActions = useCallback(
    (fieldName: string) => {
      const field = schema.fields[fieldName];
      return field ? getActiveActions(field, context) : [];
    },
    [schema, context],
  );

  const getModuleOverride = useCallback(
    () => schema.module_mode_overrides?.[schema.module],
    [schema],
  );

  const getMinSeverity = useCallback(
    () => getMinimumWarningSeverity(mode, getModuleOverride()),
    [mode, getModuleOverride],
  );

  const requestModeChange = useCallback(
    (newMode: GuidanceModeName, trigger: string) => {
      const oldMode = mode;
      setMode(newMode);
      telemetry.modeChanged(oldMode, newMode, trigger);
      onModeChange?.(newMode, trigger);
    },
    [mode, telemetry, onModeChange],
  );

  const value = useMemo<GuidanceContextValue>(
    () => ({
      schema,
      context,
      mode,
      locale,
      schemaStale,
      telemetry,
      authorityRegistry,
      getField,
      isVisible,
      isRequired,
      isEnhanced,
      getAuthorities,
      getWarnings,
      getActions,
      getModuleOverride,
      getMinSeverity,
      requestModeChange,
    }),
    [
      schema, context, mode, locale, schemaStale, telemetry, authorityRegistry,
      getField, isVisible, isRequired, isEnhanced, getAuthorities, getWarnings,
      getActions, getModuleOverride, getMinSeverity, requestModeChange,
    ],
  );

  return <GuidanceCtx.Provider value={value}>{children}</GuidanceCtx.Provider>;
}
