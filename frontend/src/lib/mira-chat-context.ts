export interface MiraChatContextSummaryItem {
  label: string;
  value: string;
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
    "Does this material stay acceptable if I change the pressure?",
    "What hydrogen condition or evidence gap should I check next?",
    "What would make this hydrogen assessment more defensible?",
  ],
  galvanic: [
    "What mitigation gets this pair into a lower-risk band?",
    "How much does the environment change the galvanic screen?",
    "Which material in this couple is driving the corrosion risk?",
  ],
  fracture: [
    "Why did this part classify into that fracture bucket?",
    "What data would I need to justify a different fracture path?",
    "Which assumptions in this fracture screen are most fragile?",
  ],
  maptis_search: [
    "What MAPTIS evidence should I look for next?",
    "How strong is the test evidence for this material?",
    "What is missing from the current MAPTIS record?",
  ],
  gpcm: [
    "Which requirement is governing this compliance result?",
    "What evidence would close the remaining compliance gap?",
    "What is the most conservative interpretation here?",
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
