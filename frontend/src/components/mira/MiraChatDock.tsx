import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Compass, Expand, Loader2, MessageSquare, Minimize2, SendHorizonal, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { MiraChatMessageBubble } from "@/components/mira/MiraChatMessageBubble";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { fetchMiraChatPing, sendMiraChatStream, type MiraChatMessage } from "@/lib/chat-api";
import {
  buildChatScopeSearch,
  conversationStorageKey,
  createModuleChatLaunchState,
  loadRouteModuleChatState,
  loadStoredConversation,
  MIRA_CHAT_GLOBAL_SCOPE_KEY,
  MIRA_CHAT_LEGACY_STORAGE_KEY,
  MIRA_CHAT_ROUTE_STATE_EVENT,
  saveStoredConversation,
  type MiraChatStoredConversation,
  type MiraChatStoredMessage,
  type MiraModuleChatLaunchState,
} from "@/lib/mira-chat-context";

const MAX_HISTORY_MESSAGES = 10;
const MAX_STORED_MESSAGES = 24;
const GLOBAL_WIDGET_PROMPTS = [
  "Is 316L compatible with GOX at 3000 psi?",
  "What galvanic risk do I have between 7075-T73 and CRES 304?",
  "What does NASA-STD-5009C say about tin whiskers?",
];

type Verdict = "PASS" | "CONDITIONAL_PASS" | "FAIL" | "REFUSE" | "INSUFFICIENT_DATA" | "ERROR" | null;
type ChatUiMessage = MiraChatStoredMessage & { verdict?: Verdict };

const ENGINE_LABELS: Record<string, string> = {
  knowledge_twins: "Knowledge Twins",
  miul: "MIUL Builder",
  mua: "MUA Writer",
  mp_plan: "M&P Plan",
  galvanic: "Galvanic",
  fracture: "Fracture Control",
  h2: "Hydrogen",
  oca: "Oxygen Compatibility",
  gpcm: "GPCM",
  maptis_search: "MAPTIS Search",
  forge_build: "FORGE Build",
  forge_explorer: "FORGE Explorer",
  tocr: "TOCR Review",
  oracle: "Oracle Standards",
  bsmh: "MIRA",
};

function messageId(prefix: "user" | "assistant"): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function toHistoryMessages(messages: ChatUiMessage[]): MiraChatMessage[] {
  return messages.slice(-MAX_HISTORY_MESSAGES).map((message) => ({
    role: message.role,
    content: message.content,
    engine_used: message.engineUsed ?? undefined,
    entities: message.entities,
  }));
}

function assistantScopeLabel(
  activeModuleLaunchState: MiraModuleChatLaunchState | null,
  engineUsed?: string | null,
): string {
  if (activeModuleLaunchState?.moduleLabel) {
    return activeModuleLaunchState.moduleLabel;
  }
  if (engineUsed && ENGINE_LABELS[engineUsed]) {
    return ENGINE_LABELS[engineUsed];
  }
  return "MIRA";
}

function fallbackLaunchState(pathname: string): MiraModuleChatLaunchState | null {
  switch (pathname) {
    case "/gas-compatibility":
      return createModuleChatLaunchState({
        scopeKey: "gas-compatibility-o2",
        moduleLabel: "Gas Compatibility",
        moduleContext: { module: "oca" },
        originPath: pathname,
        originTitle: "Gas Compatibility",
        description: "Ground the chat in the active gas-compatibility module.",
      });
    case "/galvanic-compatibility":
      return createModuleChatLaunchState({
        scopeKey: "galvanic-compatibility",
        moduleLabel: "Galvanic Compatibility",
        moduleContext: { module: "galvanic" },
        originPath: pathname,
        originTitle: "Galvanic Compatibility",
        description: "Ground the chat in the active galvanic module.",
      });
    case "/fracture-control":
      return createModuleChatLaunchState({
        scopeKey: "fracture-control",
        moduleLabel: "Fracture Control",
        moduleContext: { module: "fracture" },
        originPath: pathname,
        originTitle: "Fracture Control",
        description: "Ground the chat in the active fracture module.",
      });
    case "/oca/workbench":
      return createModuleChatLaunchState({
        scopeKey: "oca-workbench",
        moduleLabel: "OCA Workbench",
        moduleContext: { module: "oca" },
        originPath: pathname,
        originTitle: "OCA Workbench",
        description: "Ground the chat in the active oxygen compatibility module.",
      });
    case "/oca/system-builder":
      return createModuleChatLaunchState({
        scopeKey: "oca-system-builder",
        moduleLabel: "OCA System Builder",
        moduleContext: { module: "oca" },
        originPath: pathname,
        originTitle: "OCA System Builder",
        description: "Ground the chat in the active system-builder module.",
      });
    case "/mp-plan":
      return createModuleChatLaunchState({
        scopeKey: "mp-plan",
        moduleLabel: "M&P Plan",
        moduleContext: { module: "bsmh", standard_ref: "NASA-STD-6016C" },
        originPath: pathname,
        originTitle: "M&P Plan Generator",
        description: "Ground the chat in the active M&P plan workflow.",
      });
    case "/mua-v10":
      return createModuleChatLaunchState({
        scopeKey: "mua",
        moduleLabel: "MUA Writer",
        moduleContext: { module: "mua" },
        originPath: pathname,
        originTitle: "MUA Writer",
        description: "Answer only from the active MUA workflow state and guidance pack.",
      });
    case "/miul":
      return createModuleChatLaunchState({
        scopeKey: "miul",
        moduleLabel: "MIUL Builder",
        moduleContext: { module: "miul" },
        originPath: pathname,
        originTitle: "MIUL Builder",
        description: "Answer only from the active MIUL workflow state and guidance pack.",
      });
    case "/dt-editor":
      return createModuleChatLaunchState({
        scopeKey: "dt-editor",
        moduleLabel: "Drawing Tree Editor",
        moduleContext: { module: "miul", submodule: "dt_editor" },
        originPath: pathname,
        originTitle: "Drawing Tree Editor",
        description: "Answer only from the active drawing-tree editor state and MIUL guidance.",
      });
    case "/forge":
      return createModuleChatLaunchState({
        scopeKey: "forge-build",
        moduleLabel: "FORGE Build Console",
        moduleContext: { module: "forge_build" },
        originPath: pathname,
        originTitle: "FORGE Build Console",
        description: "Answer only from the active FORGE build-console state and compile artifacts.",
      });
    case "/forge-explorer":
      return createModuleChatLaunchState({
        scopeKey: "forge-explorer",
        moduleLabel: "FORGE Explorer",
        moduleContext: { module: "forge_explorer" },
        originPath: pathname,
        originTitle: "FORGE Explorer",
        description: "Answer only from the active FORGE explorer state and BSMS query results.",
      });
    case "/oracle":
      return createModuleChatLaunchState({
        scopeKey: "oracle-standards",
        moduleLabel: "Oracle Standards",
        moduleContext: { module: "oracle", standard_ref: "NASA-STD-5009C" },
        originPath: pathname,
        originTitle: "Oracle Standards",
        description: "Ground the chat in Oracle rule packs for clause lookup, applicability, and standards comparison.",
      });
    case "/tocr":
      return createModuleChatLaunchState({
        scopeKey: "tocr",
        moduleLabel: "TOCR Review",
        moduleContext: { module: "tocr" },
        originPath: pathname,
        originTitle: "TOCR Review",
        description: "Answer only from the active TOCR review state and guidance pack.",
      });
    case "/":
    case "/knowledge-twins":
      return createModuleChatLaunchState({
        scopeKey: "knowledge-twins",
        moduleLabel: "Knowledge Twins",
        moduleContext: { module: "knowledge_twins" },
        originPath: pathname,
        originTitle: "Knowledge Twins",
        description: "Answer only from the active Knowledge Twins fluid, mode, and visible evidence.",
      });
    default:
      return null;
  }
}

export function MiraChatDock() {
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [routeStateVersion, setRouteStateVersion] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatUiMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [conversationLoaded, setConversationLoaded] = useState(false);
  const [serviceHealthy, setServiceHealthy] = useState(true);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);

  const activeModuleLaunchState = useMemo(
    () => loadRouteModuleChatState(location.pathname) ?? fallbackLaunchState(location.pathname),
    [location.pathname, routeStateVersion],
  );
  const scopeKey = activeModuleLaunchState?.scopeKey ?? MIRA_CHAT_GLOBAL_SCOPE_KEY;
  const storageKey = useMemo(() => conversationStorageKey(scopeKey), [scopeKey]);
  const starterPrompts = activeModuleLaunchState?.starterPrompts.length
    ? activeModuleLaunchState.starterPrompts.slice(0, 2)
    : GLOBAL_WIDGET_PROMPTS;

  useEffect(() => {
    if (location.pathname === "/chat") {
      setOpen(false);
    }
  }, [location.pathname]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ pathname?: string }>).detail;
      if (!detail?.pathname || detail.pathname !== location.pathname) {
        return;
      }
      setRouteStateVersion((current) => current + 1);
    };

    window.addEventListener(MIRA_CHAT_ROUTE_STATE_EVENT, handler as EventListener);
    return () => {
      window.removeEventListener(MIRA_CHAT_ROUTE_STATE_EVENT, handler as EventListener);
    };
  }, [location.pathname]);

  useEffect(() => {
    setConversationLoaded(false);
    const storedConversation = loadStoredConversation(
      storageKey,
      scopeKey === MIRA_CHAT_GLOBAL_SCOPE_KEY ? [MIRA_CHAT_LEGACY_STORAGE_KEY] : [],
    );
    setSessionId(storedConversation.sessionId);
    setMessages(storedConversation.messages);
    setDraft("");
    setError(null);
    setConversationLoaded(true);
  }, [scopeKey, storageKey]);

  useEffect(() => {
    if (!conversationLoaded) {
      return;
    }
    saveStoredConversation(
      storageKey,
      { sessionId, messages } as MiraChatStoredConversation,
      scopeKey === MIRA_CHAT_GLOBAL_SCOPE_KEY,
    );
  }, [conversationLoaded, messages, scopeKey, sessionId, storageKey]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const endMarker = conversationEndRef.current;
    if (!endMarker) {
      return;
    }
    endMarker.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, open, isSending]);

  useEffect(() => {
    let cancelled = false;

    if (!open) {
      return () => {
        cancelled = true;
      };
    }

    void fetchMiraChatPing()
      .then(() => {
        if (!cancelled) {
          setServiceHealthy(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setServiceHealthy(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [open]);

  if (location.pathname === "/chat") {
    return null;
  }

  const submitMessage = async (rawMessage: string) => {
    const message = rawMessage.trim();
    if (!message || isSending) {
      return;
    }

    const optimisticId = messageId("user");
    const assistantId = messageId("assistant");
    let sawDone = false;
    let sawStreamContent = false;
    setIsSending(true);
    setError(null);
    setDraft("");
    setMessages((current) => [
      ...current,
      {
        id: optimisticId,
        role: "user",
        content: message,
        entities: {},
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        entities: {},
      },
    ]);

    try {
      await sendMiraChatStream({
        message,
        session_id: sessionId ?? undefined,
        history: toHistoryMessages(messages),
        module_context: activeModuleLaunchState?.moduleContext,
      }, {
        onEvent: (event) => {
          switch (event.type) {
            case "meta": {
              setMessages((current) => current.map((currentMessage) => (
                currentMessage.id === assistantId
                  ? {
                      ...currentMessage,
                      engineUsed: typeof event.engine_id === "string" ? event.engine_id : null,
                      verdict: (typeof event.verdict === "string" ? event.verdict : null) as Verdict,
                    }
                  : currentMessage
              )));
              break;
            }
            case "text": {
              const delta = typeof event.content === "string" ? event.content : "";
              if (!delta) {
                break;
              }
              sawStreamContent = true;
              setMessages((current) => current.map((currentMessage) => (
                currentMessage.id === assistantId
                  ? { ...currentMessage, content: `${currentMessage.content}${delta}` }
                  : currentMessage
              )));
              break;
            }
            case "done": {
              sawDone = true;
              const turnEntities = event.entities && typeof event.entities === "object"
                ? event.entities as Record<string, unknown>
                : {};
              const followUps = Array.isArray(event.follow_ups)
                ? event.follow_ups.filter((item): item is string => typeof item === "string")
                : [];
              const citations = Array.isArray(event.citations)
                ? event.citations.filter((item): item is string => typeof item === "string")
                : [];
              const advisoryOnly = event.advisory_only === true;
              if (typeof event.session_id === "string" && event.session_id.trim()) {
                setSessionId(event.session_id);
              }
              setMessages((current) => current.map((currentMessage) => {
                if (currentMessage.id === optimisticId) {
                  return { ...currentMessage, entities: turnEntities };
                }
                if (currentMessage.id === assistantId) {
                  return {
                    ...currentMessage,
                    auditId: typeof event.audit_id === "string" ? event.audit_id : null,
                    followUps,
                    citations,
                    advisoryOnly,
                    entities: turnEntities,
                  };
                }
                return currentMessage;
              }).slice(-MAX_STORED_MESSAGES));
              break;
            }
            case "error":
              break;
            default:
              break;
          }
        },
      });
      if (!sawDone) {
        throw new Error("Chat stream ended before the final done event.");
      }
    } catch (submitError: unknown) {
      setMessages((current) => {
        const assistantMessage = current.find((currentMessage) => currentMessage.id === assistantId);
        const hasAssistantContent = Boolean(assistantMessage?.content?.trim());
        if (hasAssistantContent) {
          return current;
        }
        return current.filter(
          (currentMessage) => currentMessage.id !== optimisticId && currentMessage.id !== assistantId,
        );
      });
      if (!sawStreamContent) {
        setDraft(message);
      }
      setError(submitError instanceof Error ? submitError.message : "Chat request failed.");
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="pointer-events-none fixed bottom-5 left-3 right-3 z-50 flex flex-col items-stretch gap-3 sm:left-auto sm:right-5 sm:max-w-[calc(100vw-1.5rem)] sm:items-end">
      {open ? (
        <Card className="pointer-events-auto flex h-[40rem] max-h-[calc(100vh-6.5rem)] w-full max-w-full flex-col overflow-hidden border-border/80 shadow-2xl sm:w-[28rem] sm:max-w-[calc(100vw-1.5rem)]">
          <div className="border-b border-border/70 bg-[radial-gradient(circle_at_top_left,_rgba(15,118,110,0.14),_transparent_40%),linear-gradient(135deg,_rgba(8,47,73,0.98),_rgba(15,23,42,0.98))] px-4 py-3 text-slate-50">
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1">
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.16em] text-slate-200">
                  {activeModuleLaunchState ? <Compass className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                  {activeModuleLaunchState ? "Module Chat" : "MIRA Chat"}
                </div>
                <div className="text-sm font-semibold">
                  {activeModuleLaunchState?.moduleLabel ?? "Engineering assistant"}
                </div>
                <div className="text-xs text-slate-200/80">
                  {activeModuleLaunchState
                    ? "Stays in this module unless you explicitly ask to switch."
                    : "Ask a cross-domain engineering question."}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-slate-100 hover:bg-white/10 hover:text-white"
                  onClick={() => {
                    if (activeModuleLaunchState) {
                      navigate(
                        {
                          pathname: "/chat",
                          search: buildChatScopeSearch(activeModuleLaunchState.scopeKey),
                        },
                        { state: activeModuleLaunchState },
                      );
                    } else {
                      navigate("/chat");
                    }
                  }}
                >
                  <Expand className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-slate-100 hover:bg-white/10 hover:text-white"
                  onClick={() => setOpen(false)}
                >
                  <Minimize2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>

          <ScrollArea className="min-h-0 flex-1 bg-[linear-gradient(180deg,rgba(248,250,252,0.98),rgba(241,245,249,0.96))]">
            <div className="flex min-h-full flex-col gap-3 p-4 sm:pr-5">
              {!messages.length ? (
                <div className="space-y-3 rounded-2xl border border-dashed border-border bg-background/85 p-4">
                  <div className="text-sm font-medium">Start here</div>
                  <div className="flex flex-wrap gap-2">
                    {starterPrompts.map((prompt) => (
                      <Button
                        key={prompt}
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-auto whitespace-normal px-3 py-2 text-left text-xs"
                        onClick={() => {
                          setDraft(prompt);
                        }}
                      >
                        {prompt}
                      </Button>
                    ))}
                  </div>
                </div>
              ) : null}

              {messages.map((message) => {
                return (
                  <MiraChatMessageBubble
                    key={message.id}
                    message={message}
                    assistantLabel={assistantScopeLabel(activeModuleLaunchState, message.engineUsed)}
                    isSending={isSending}
                    compact
                    onFollowUp={(followUp) => {
                      void submitMessage(followUp);
                    }}
                  />
                );
              })}

              <div ref={conversationEndRef} />
            </div>
          </ScrollArea>

          <div className="space-y-3 border-t border-border/70 bg-background p-3">
            {!serviceHealthy ? (
              <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                Chat status could not be verified right now. You can still try a message.
              </div>
            ) : null}
            <Textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submitMessage(draft);
                }
              }}
              placeholder="Ask MIRA..."
              className="min-h-[88px] resize-none text-sm"
            />
            <div className="flex items-center justify-between gap-3">
              <div className="text-[11px] text-muted-foreground">
                {activeModuleLaunchState ? activeModuleLaunchState.moduleLabel : "Global scope"}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSessionId(null);
                    setMessages([]);
                    setDraft("");
                    setError(null);
                    saveStoredConversation(
                      storageKey,
                      { sessionId: null, messages: [] },
                      scopeKey === MIRA_CHAT_GLOBAL_SCOPE_KEY,
                    );
                  }}
                >
                  <X className="h-4 w-4" />
                  Clear
                </Button>
                <Button type="button" size="sm" onClick={() => void submitMessage(draft)} disabled={isSending || !draft.trim()}>
                  {isSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizonal className="h-4 w-4" />}
                </Button>
              </div>
            </div>
            {error ? (
              <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {error}
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}

      <Button
        type="button"
        size="lg"
        className="pointer-events-auto h-14 rounded-full px-5 shadow-xl"
        onClick={() => setOpen(true)}
      >
        <MessageSquare className="h-5 w-5" />
        {messages.length ? "Continue chat" : "Chat with MIRA"}
      </Button>
    </div>
  );
}
