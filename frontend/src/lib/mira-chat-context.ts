export interface MiraChatContextSummaryItem {
  label: string;
  value: string;
}

export interface MiraChatActiveField {
  fieldKey: string;
  label: string;
}

export interface MiraChatWorkflowFieldState {
  fieldKey: string;
  label: string;
  status: "complete" | "incomplete" | "warning" | "blocked";
  required?: boolean;
}

export interface MiraModuleChatLaunchState {
  kind: "module";
  scopeKey: string;
  moduleLabel: string;
  moduleContext: Record<string, unknown>;
  originPath: string;
  originTitle: string;
  description?: string;
  starterPrompts: string[];
  contextSummary: MiraChatContextSummaryItem[];
}

export interface MiraChatStoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  engineUsed?: string | null;
  verdict?: string | null;
  auditId?: string | null;
  followUps?: string[];
  citations?: string[];
  advisoryOnly?: boolean;
  entities: Record<string, unknown>;
}

export interface MiraChatStoredConversation {
  sessionId: string | null;
  messages: MiraChatStoredMessage[];
}

export const MIRA_CHAT_GLOBAL_SCOPE_KEY = "global";
export const MIRA_CHAT_LEGACY_STORAGE_KEY = "mira-chat-session-v1";
export const MIRA_CHAT_STORAGE_KEY_PREFIX = "mira-chat-session-v2";

const LAUNCH_STATE_STORAGE_PREFIX = "mira-chat-launch-state-v1";
const ACTIVE_ROUTE_SCOPE_STORAGE_PREFIX = "mira-chat-route-scope-v1";
export const MIRA_CHAT_ROUTE_STATE_EVENT = "mira-chat-route-state-updated";

const MODULE_PROMPTS: Record<string, string[]> = {
  oca: [
    "What mechanism is driving the oxygen risk here?",
    "What missing input is blocking a clean OCA decision?",
    "What controls would move this toward a pass?",
  ],
  h2: [
    "Walk me through this hydrogen screen and tell me which input matters most.",
    "What hydrogen condition or embrittlement concern should I check next?",
    "If I change the pressure or condition, what do you want me to re-check first?",
  ],
  galvanic: [
    "Walk me through this couple and tell me which member is driving the galvanic risk.",
    "What mitigation would you change first on this joint?",
    "Which input on this page most changes the galvanic verdict?",
  ],
  fracture: [
    "Walk me through this fracture screen step by step.",
    "What input would most likely change this fracture path?",
    "What evidence or inspection burden would I need to defend a different classification?",
  ],
  maptis_search: [
    "Walk me through the strongest evidence in this MAPTIS record.",
    "How strong is the current test evidence for this material?",
    "What property or test gap should I go find next?",
  ],
  gpcm: [
    "Which NASA-STD-6016C requirement is actually governing this case?",
    "Walk me through what is still missing for a clean compliance closure.",
    "What is the most conservative reading of this requirement?",
  ],
  oracle: [
    "What does NASA-STD-5009C say about tin whiskers?",
    "Show me the governing clause for pure tin finishes in MSFC-STD-3012A.",
    "Compare NASA-STD-5009C and MSFC-STD-3012A on this topic.",
  ],
  bsmh: [
    "Help me sort this into the right engineering workflow.",
    "What inputs do you need before this should go to a specialist?",
    "If this belongs in OCA, hydrogen, galvanic, or fracture, which one and why?",
  ],
};

function cleanModuleContext(moduleContext: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(moduleContext).filter(([, value]) => {
      if (value === null || value === undefined) return false;
      if (typeof value === "string") return value.trim().length > 0;
      return true;
    }),
  );
}

export function buildChatContextSummary(
  entries: Array<{ label: string; value: string | number | boolean | null | undefined }>,
): MiraChatContextSummaryItem[] {
  return entries.flatMap((entry) => {
    if (entry.value === null || entry.value === undefined) return [];
    if (typeof entry.value === "string" && entry.value.trim().length === 0) return [];
    return [{ label: entry.label, value: String(entry.value) }];
  });
}

export function resolveGuidanceFieldFromTarget(target: EventTarget | null): MiraChatActiveField | null {
  if (!(target instanceof Element)) return null;
  const container = target.closest("[data-guidance-field]");
  if (!(container instanceof HTMLElement)) return null;

  const fieldKey = container.dataset.guidanceField?.trim();
  const label = container.dataset.guidanceLabel?.trim();
  if (!fieldKey || !label) return null;

  return { fieldKey, label };
}

export function buildWorkflowContext(args: {
  currentStep: string;
  activeField?: MiraChatActiveField | null;
  fieldStates?: MiraChatWorkflowFieldState[];
  nextSteps?: string[];
  blockers?: string[];
}): Record<string, unknown> {
  const fieldStates = args.fieldStates ?? [];
  const completedFields = fieldStates
    .filter((field) => field.status === "complete")
    .map((field) => field.label);
  const incompleteFields = fieldStates
    .filter((field) => field.status !== "complete")
    .map((field) => field.label);

  return {
    current_step: args.currentStep,
    active_field: args.activeField?.fieldKey,
    active_field_label: args.activeField?.label,
    field_states: fieldStates,
    completed_fields: completedFields,
    incomplete_fields: incompleteFields,
    next_steps: args.nextSteps ?? [],
    blockers: args.blockers ?? [],
  };
}

export function createModuleChatLaunchState(args: {
  scopeKey: string;
  moduleLabel: string;
  moduleContext: Record<string, unknown>;
  originPath: string;
  originTitle: string;
  description?: string;
  starterPrompts?: string[];
  contextSummary?: MiraChatContextSummaryItem[];
}): MiraModuleChatLaunchState {
  const cleanedContext = cleanModuleContext(args.moduleContext);
  const moduleName = String(cleanedContext.module ?? "").toLowerCase();

  return {
    kind: "module",
    scopeKey: args.scopeKey,
    moduleLabel: args.moduleLabel,
    moduleContext: cleanedContext,
    originPath: args.originPath,
    originTitle: args.originTitle,
    description: args.description,
    starterPrompts:
      args.starterPrompts && args.starterPrompts.length > 0
        ? args.starterPrompts
        : MODULE_PROMPTS[moduleName] ?? [],
    contextSummary: args.contextSummary ?? [],
  };
}

export function isMiraModuleChatLaunchState(value: unknown): value is MiraModuleChatLaunchState {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<MiraModuleChatLaunchState>;
  return (
    candidate.kind === "module"
    && typeof candidate.scopeKey === "string"
    && typeof candidate.moduleLabel === "string"
    && typeof candidate.originPath === "string"
    && typeof candidate.originTitle === "string"
    && !!candidate.moduleContext
    && typeof candidate.moduleContext === "object"
    && Array.isArray(candidate.starterPrompts)
    && Array.isArray(candidate.contextSummary)
  );
}

export function persistModuleChatLaunchState(state: MiraModuleChatLaunchState): void {
  if (typeof window === "undefined") return;

  try {
    window.sessionStorage.setItem(
      `${LAUNCH_STATE_STORAGE_PREFIX}:${state.scopeKey}`,
      JSON.stringify(state),
    );
  } catch {
    // Ignore storage failures. Chat still works without persistence.
  }
}

export function loadPersistedModuleChatLaunchState(scopeKey: string): MiraModuleChatLaunchState | null {
  if (typeof window === "undefined" || !scopeKey.trim()) return null;

  try {
    const raw = window.sessionStorage.getItem(
      `${LAUNCH_STATE_STORAGE_PREFIX}:${scopeKey}`,
    );
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isMiraModuleChatLaunchState(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function registerRouteModuleChatState(
  pathname: string,
  state: MiraModuleChatLaunchState,
): void {
  if (typeof window === "undefined" || !pathname.trim()) return;

  persistModuleChatLaunchState(state);

  try {
    window.sessionStorage.setItem(
      `${ACTIVE_ROUTE_SCOPE_STORAGE_PREFIX}:${pathname}`,
      state.scopeKey,
    );
  } catch {
    // Ignore storage failures. Chat can still fall back to global scope.
  }

  window.dispatchEvent(
    new CustomEvent(MIRA_CHAT_ROUTE_STATE_EVENT, {
      detail: { pathname, scopeKey: state.scopeKey },
    }),
  );
}

export function loadRouteModuleChatState(pathname: string): MiraModuleChatLaunchState | null {
  if (typeof window === "undefined" || !pathname.trim()) return null;

  try {
    const scopeKey = window.sessionStorage.getItem(
      `${ACTIVE_ROUTE_SCOPE_STORAGE_PREFIX}:${pathname}`,
    );
    if (!scopeKey) return null;
    return loadPersistedModuleChatLaunchState(scopeKey);
  } catch {
    return null;
  }
}

export function buildChatScopeSearch(scopeKey: string): string {
  const params = new URLSearchParams();
  params.set("scope", scopeKey);
  return `?${params.toString()}`;
}

export function conversationStorageKey(scopeKey: string): string {
  return `${MIRA_CHAT_STORAGE_KEY_PREFIX}:${scopeKey}`;
}

export function loadStoredConversation(
  storageKey: string,
  fallbackKeys: string[] = [],
): MiraChatStoredConversation {
  if (typeof window === "undefined") {
    return { sessionId: null, messages: [] };
  }

  try {
    const candidateKeys = [storageKey, ...fallbackKeys];
    for (const candidateKey of candidateKeys) {
      const raw = window.localStorage.getItem(candidateKey);
      if (!raw) {
        continue;
      }
      const parsed = JSON.parse(raw) as MiraChatStoredConversation;
      return {
        sessionId: parsed.sessionId ?? null,
        messages: Array.isArray(parsed.messages) ? parsed.messages : [],
      };
    }
    return { sessionId: null, messages: [] };
  } catch {
    return { sessionId: null, messages: [] };
  }
}

export function saveStoredConversation(
  storageKey: string,
  conversation: MiraChatStoredConversation,
  mirrorLegacyGlobal = false,
): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const payload = JSON.stringify(conversation);
    window.localStorage.setItem(storageKey, payload);
    if (mirrorLegacyGlobal) {
      window.localStorage.setItem(MIRA_CHAT_LEGACY_STORAGE_KEY, payload);
    }
  } catch {
    // Ignore storage failures; chat still works without persistence.
  }
}
