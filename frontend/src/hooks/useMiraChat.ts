import { useEffect, useMemo, useRef, useState } from "react";
import type { MiraChatMessage } from "@/lib/chat-api";
import {
  conversationStorageKey,
  loadStoredConversation,
  MIRA_CHAT_GLOBAL_SCOPE_KEY,
  MIRA_CHAT_LEGACY_STORAGE_KEY,
  saveStoredConversation,
  type MiraChatStoredConversation,
  type MiraChatStoredMessage,
  type MiraModuleChatLaunchState,
} from "@/lib/mira-chat-context";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_HISTORY_MESSAGES = 10;
const MAX_STORED_MESSAGES = 24;
const CHAT_STREAM_URL = "/api/chat/stream";

// ---------------------------------------------------------------------------
// Exported types
// ---------------------------------------------------------------------------

export type Verdict =
  | "PASS"
  | "CONDITIONAL_PASS"
  | "FAIL"
  | "REFUSE"
  | "INSUFFICIENT_DATA"
  | "ERROR"
  | null;

export type ChatUiMessage = MiraChatStoredMessage & { verdict?: Verdict };

export interface StreamingMessage {
  content: string;
  thinking: boolean;
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for component use)
// ---------------------------------------------------------------------------

export function verdictVariant(
  verdict: Verdict,
): "default" | "secondary" | "destructive" | "outline" {
  if (verdict === "PASS") return "default";
  if (verdict === "FAIL" || verdict === "ERROR" || verdict === "REFUSE") return "destructive";
  if (verdict === "CONDITIONAL_PASS") return "secondary";
  return "outline";
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function messageId(prefix: "user" | "assistant"): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function toHistoryMessages(messages: ChatUiMessage[]): MiraChatMessage[] {
  return messages.slice(-MAX_HISTORY_MESSAGES).map((msg) => ({
    role: msg.role,
    content: msg.content,
    engine_used: msg.engineUsed ?? undefined,
    entities: msg.entities,
  }));
}

// ---------------------------------------------------------------------------
// SSE parsing
// ---------------------------------------------------------------------------

interface SseEvent {
  type: string;
  content?: string;
  engine_id?: string | null;
  verdict?: string | null;
  mode?: string | null;
  audit_id?: string | null;
  session_id?: string;
  entities?: Record<string, unknown>;
  follow_ups?: string[];
  message?: string;
}

function parseSseLine(line: string): SseEvent | null {
  if (!line.startsWith("data: ")) return null;
  try {
    return JSON.parse(line.slice(6)) as SseEvent;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseMiraChatOptions {
  scopeKey: string;
  activeModuleLaunchState: MiraModuleChatLaunchState | null;
}

export function useMiraChat({ scopeKey, activeModuleLaunchState }: UseMiraChatOptions) {
  const storageKey = useMemo(() => conversationStorageKey(scopeKey), [scopeKey]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatUiMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState<StreamingMessage | null>(null);
  const [conversationLoaded, setConversationLoaded] = useState(false);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamContentRef = useRef("");
  const currentOptimisticIdRef = useRef<string | null>(null);
  const streamMetaRef = useRef<{
    engineId: string | null;
    verdict: string | null;
    mode: string | null;
    auditId: string | null;
    sessionId: string | null;
    entities: Record<string, unknown>;
    followUps: string[];
  }>({
    engineId: null,
    verdict: null,
    mode: null,
    auditId: null,
    sessionId: null,
    entities: {},
    followUps: [],
  });

  // -----------------------------------------------------------------------
  // Conversation persistence
  // -----------------------------------------------------------------------

  useEffect(() => {
    setConversationLoaded(false);
    const stored = loadStoredConversation(
      storageKey,
      scopeKey === MIRA_CHAT_GLOBAL_SCOPE_KEY ? [MIRA_CHAT_LEGACY_STORAGE_KEY] : [],
    );
    setSessionId(stored.sessionId);
    setMessages(stored.messages);
    setDraft("");
    setError(null);
    setStreamingMessage(null);
    setConversationLoaded(true);
  }, [scopeKey, storageKey]);

  useEffect(() => {
    if (!conversationLoaded) return;
    saveStoredConversation(
      storageKey,
      { sessionId, messages } as MiraChatStoredConversation,
      scopeKey === MIRA_CHAT_GLOBAL_SCOPE_KEY,
    );
  }, [conversationLoaded, messages, scopeKey, sessionId, storageKey]);

  // -----------------------------------------------------------------------
  // Auto-scroll
  // -----------------------------------------------------------------------

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isSending, streamingMessage]);

  // -----------------------------------------------------------------------
  // Abort on unmount
  // -----------------------------------------------------------------------

  useEffect(() => () => {
    abortControllerRef.current?.abort();
  }, []);

  // -----------------------------------------------------------------------
  // Promote partial content (mid-stream abort)
  // -----------------------------------------------------------------------

  const promotePartialContent = () => {
    const content = streamContentRef.current;
    const optimisticId = currentOptimisticIdRef.current;
    const meta = streamMetaRef.current;

    if (content && optimisticId) {
      setMessages((current) => {
        const updated = current.map((m) =>
          m.id === optimisticId ? { ...m, entities: meta.entities } : m,
        );
        updated.push({
          id: messageId("assistant"),
          role: "assistant",
          content,
          engineUsed: meta.engineId ?? null,
          verdict: (meta.verdict as Verdict) ?? null,
          auditId: meta.auditId ?? null,
          followUps: meta.followUps,
          entities: meta.entities,
        });
        return updated.slice(-MAX_STORED_MESSAGES);
      });
      if (meta.sessionId) setSessionId(meta.sessionId);
    }

    streamContentRef.current = "";
    currentOptimisticIdRef.current = null;
    setStreamingMessage(null);
  };

  // -----------------------------------------------------------------------
  // Submit message (streaming SSE)
  // -----------------------------------------------------------------------

  const submitMessage = async (rawMessage: string) => {
    const message = rawMessage.trim();
    if (!message) return;

    // Abort in-flight stream and promote partial content
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      promotePartialContent();
    }

    const optimisticId = messageId("user");
    currentOptimisticIdRef.current = optimisticId;
    streamContentRef.current = "";
    streamMetaRef.current = {
      engineId: null,
      verdict: null,
      mode: null,
      auditId: null,
      sessionId: null,
      entities: {},
      followUps: [],
    };

    setError(null);
    setIsSending(true);
    setDraft("");
    setStreamingMessage(null);
    setMessages((current) => [
      ...current,
      { id: optimisticId, role: "user", content: message, entities: {} },
    ]);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch(CHAT_STREAM_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          session_id: sessionId,
          history: toHistoryMessages(messages),
          module_context: activeModuleLaunchState?.moduleContext,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        const errorMsg =
          typeof detail?.detail === "string"
            ? detail.detail
            : `Chat request failed: ${response.statusText}`;
        throw new Error(errorMsg);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          const event = parseSseLine(trimmed);
          if (!event) continue;

          switch (event.type) {
            case "meta":
              streamMetaRef.current.engineId = event.engine_id ?? null;
              streamMetaRef.current.verdict = event.verdict ?? null;
              streamMetaRef.current.mode = event.mode ?? null;
              setStreamingMessage({ content: "", thinking: false });
              break;

            case "thinking_start":
              setStreamingMessage((prev) =>
                prev ? { ...prev, thinking: true } : { content: "", thinking: true },
              );
              break;

            case "thinking_end":
              setStreamingMessage((prev) =>
                prev ? { ...prev, thinking: false } : null,
              );
              break;

            case "text": {
              const delta = event.content ?? "";
              streamContentRef.current += delta;
              setStreamingMessage((prev) =>
                prev
                  ? { ...prev, content: prev.content + delta }
                  : { content: delta, thinking: false },
              );
              break;
            }

            case "done": {
              streamMetaRef.current.auditId = event.audit_id ?? null;
              streamMetaRef.current.sessionId = event.session_id ?? null;
              streamMetaRef.current.entities = event.entities ?? {};
              streamMetaRef.current.followUps = event.follow_ups ?? [];

              const finalContent = streamContentRef.current;
              const meta = streamMetaRef.current;

              setMessages((current) => {
                const updated = current.map((m) =>
                  m.id === optimisticId ? { ...m, entities: meta.entities } : m,
                );
                if (finalContent) {
                  updated.push({
                    id: messageId("assistant"),
                    role: "assistant",
                    content: finalContent,
                    engineUsed: meta.engineId ?? null,
                    verdict: (meta.verdict as Verdict) ?? null,
                    auditId: meta.auditId ?? null,
                    followUps: meta.followUps,
                    entities: meta.entities,
                  });
                }
                return updated.slice(-MAX_STORED_MESSAGES);
              });
              if (meta.sessionId) setSessionId(meta.sessionId);
              setStreamingMessage(null);
              streamContentRef.current = "";
              currentOptimisticIdRef.current = null;
              break;
            }

            case "error":
              setError(event.message ?? "Streaming error");
              break;
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name === "AbortError") return;
      setMessages((current) => current.filter((m) => m.id !== optimisticId));
      setDraft(message);
      setError(err instanceof Error ? err.message : "Chat request failed.");
      setStreamingMessage(null);
      streamContentRef.current = "";
      currentOptimisticIdRef.current = null;
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
      setIsSending(false);
    }
  };

  // -----------------------------------------------------------------------
  // Clear conversation
  // -----------------------------------------------------------------------

  const clearConversation = () => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    streamContentRef.current = "";
    currentOptimisticIdRef.current = null;
    setSessionId(null);
    setMessages([]);
    setDraft("");
    setError(null);
    setIsSending(false);
    setStreamingMessage(null);
    saveStoredConversation(
      storageKey,
      { sessionId: null, messages: [] },
      scopeKey === MIRA_CHAT_GLOBAL_SCOPE_KEY,
    );
  };

  return {
    messages,
    sessionId,
    draft,
    setDraft,
    error,
    isSending,
    streamingMessage,
    conversationLoaded,
    conversationEndRef,
    submitMessage,
    clearConversation,
  };
}
