import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Bot, ClipboardList, Compass, Loader2, RotateCcw, SendHorizonal, User2 } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { fetchMiraChatPing, sendMiraChatStream } from "@/lib/chat-api";
import {
  assistantScopeLabel,
  messageId,
  toHistoryMessages,
  verdictVariant,
  MAX_STORED_MESSAGES,
  type ChatUiMessage,
  type Verdict,
} from "@/lib/chat-utils";
import {
  conversationStorageKey,
  isMiraModuleChatLaunchState,
  loadStoredConversation,
  loadPersistedModuleChatLaunchState,
  MIRA_CHAT_GLOBAL_SCOPE_KEY,
  MIRA_CHAT_LEGACY_STORAGE_KEY,
  persistModuleChatLaunchState,
  saveStoredConversation,
  type MiraChatStoredConversation,
  type MiraModuleChatLaunchState,
} from "@/lib/mira-chat-context";
import { cn } from "@/lib/utils";
import { VoiceControl } from "@/components/voice/VoiceControl";
import { VoiceActiveBanner } from "@/components/voice/VoiceActiveBanner";
import { VoiceEnableModal } from "@/components/voice/VoiceEnableModal";
import { VoiceSettings } from "@/components/voice/VoiceSettings";
import { useVoiceChatIntegration } from "@/lib/voice/useVoiceChatIntegration";
import type { VoiceTurnSummary } from "@/lib/voice/types";
import { AuditDrawer } from "@/components/audit/AuditDrawer";
import { PivIdentityChip } from "@/components/audit/PivIdentityChip";

const GLOBAL_EXAMPLE_PROMPTS = [
  "Is 316L compatible with GOX at 3000 psi?",
  "What galvanic risk do I have between 7075-T73 and CRES 304 in seawater proxy?",
  "Can you compare hydrogen compatibility for Inconel 718 and A286?",
  "What MAPTIS evidence exists for Inconel 625 in aged versus cast condition?",
];

function renderInlineText(text: string) {
  const matches = Array.from(text.matchAll(/\*\*(.+?)\*\*/g));
  if (!matches.length) {
    return text;
  }

  const nodes: Array<string | JSX.Element> = [];
  let cursor = 0;

  matches.forEach((match, index) => {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    if (start > cursor) {
      nodes.push(text.slice(cursor, start));
    }
    nodes.push(
      <strong key={`strong-${index}`} className="font-semibold text-inherit">
        {match[1]}
      </strong>,
    );
    cursor = end;
  });

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes;
}

function renderMessageContent(text: string) {
  const blocks = text
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);

  return blocks.map((block, blockIndex) => {
    const lines = block.split("\n").map((line) => line.trimEnd());
    const bulletLines = lines.filter((line) => /^[-*]\s+/.test(line.trim()));

    if (bulletLines.length === lines.length) {
      return (
        <ul key={`list-${blockIndex}`} className="list-disc space-y-1 pl-5 marker:text-slate-400">
          {bulletLines.map((line, lineIndex) => (
            <li key={`item-${blockIndex}-${lineIndex}`}>{renderInlineText(line.replace(/^[-*]\s+/, ""))}</li>
          ))}
        </ul>
      );
    }

    return (
      <p key={`paragraph-${blockIndex}`} className="whitespace-pre-wrap">
        {lines.map((line, lineIndex) => (
          <span key={`line-${blockIndex}-${lineIndex}`}>
            {renderInlineText(line)}
            {lineIndex < lines.length - 1 ? <br /> : null}
          </span>
        ))}
      </p>
    );
  });
}

export default function MiraChat() {
  const location = useLocation();
  const navigate = useNavigate();
  const scopeKeyFromQuery = useMemo(() => {
    const value = new URLSearchParams(location.search).get("scope");
    return value?.trim() ?? "";
  }, [location.search]);
  const activeModuleLaunchState = useMemo<MiraModuleChatLaunchState | null>(() => {
    if (isMiraModuleChatLaunchState(location.state)) {
      return location.state;
    }
    if (scopeKeyFromQuery) {
      return loadPersistedModuleChatLaunchState(scopeKeyFromQuery);
    }
    return null;
  }, [location.state, scopeKeyFromQuery]);
  const isModuleChat = Boolean(activeModuleLaunchState);
  const scopeKey = activeModuleLaunchState?.scopeKey ?? MIRA_CHAT_GLOBAL_SCOPE_KEY;
  const storageKey = useMemo(() => conversationStorageKey(scopeKey), [scopeKey]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatUiMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [adapters, setAdapters] = useState<string[]>([]);
  const [pingError, setPingError] = useState<string | null>(null);
  const [conversationLoaded, setConversationLoaded] = useState(false);
  const [voiceId, setVoiceId] = useState<string | null>(null);
  const [auditDrawerOpen, setAuditDrawerOpen] = useState(false);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);
  const starterPrompts = activeModuleLaunchState?.starterPrompts.length
    ? activeModuleLaunchState.starterPrompts
    : GLOBAL_EXAMPLE_PROMPTS;
  const scopeLabel = activeModuleLaunchState?.moduleLabel ?? "Global Chat";
  const scopeDescription = activeModuleLaunchState?.description
    ?? "Ask one question, route into OCA, H2, galvanic, fracture, MAPTIS, BSMH, or compliance logic, and keep the conversation grounded with browser-held history.";

  useEffect(() => {
    if (activeModuleLaunchState) {
      persistModuleChatLaunchState(activeModuleLaunchState);
    }
  }, [activeModuleLaunchState]);

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
    let cancelled = false;

    void fetchMiraChatPing()
      .then((payload) => {
        if (cancelled) return;
        setAdapters(payload.adapters_loaded.split(",").filter(Boolean));
      })
      .catch((fetchError: unknown) => {
        if (cancelled) return;
        setPingError(fetchError instanceof Error ? fetchError.message : "Unable to load chat status.");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const endMarker = conversationEndRef.current;
    if (!endMarker) {
      return;
    }
    endMarker.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isSending]);

  const clearConversation = () => {
    setSessionId(null);
    setMessages([]);
    setDraft("");
    setError(null);
    saveStoredConversation(
      storageKey,
      { sessionId: null, messages: [] },
      scopeKey === MIRA_CHAT_GLOBAL_SCOPE_KEY,
    );
  };

  // -----------------------------------------------------------------
  // Voice + audit integration (shared hook with MiraChatDock)
  // -----------------------------------------------------------------
  const appendVoiceTurn = useCallback((summary: VoiceTurnSummary) => {
    if (!summary.userTranscript.trim() && !summary.assistantText.trim()) {
      return;
    }
    setMessages((current) => {
      const merged = [
        ...current,
        {
          id: messageId("user"),
          role: "user" as const,
          content: summary.userTranscript,
          entities: summary.entities,
        },
        {
          id: messageId("assistant"),
          role: "assistant" as const,
          content: summary.assistantText,
          engineUsed: summary.engineUsed,
          verdict: (summary.verdict ?? null) as Verdict,
          entities: summary.entities,
          auditId: summary.auditId,
          followUps: summary.followUps,
        },
      ];
      return merged.slice(-MAX_STORED_MESSAGES);
    });
  }, []);

  const appendGreeting = useCallback((text: string) => {
    setMessages((current) => [
      ...current,
      {
        id: messageId("assistant"),
        role: "assistant" as const,
        content: text,
        entities: {},
      },
    ]);
  }, []);

  const {
    voiceSession,
    voiceActive,
    voiceError,
    voiceModalOpen,
    closeVoiceModal,
    handleVoiceToggle,
    handleVoiceConfirm,
    auditRefreshKey,
    bumpAuditRefresh,
  } = useVoiceChatIntegration({
    sessionId,
    history: useMemo(() => toHistoryMessages(messages), [messages]),
    moduleContext: activeModuleLaunchState?.moduleContext ?? null,
    conversationLoaded,
    hasMessages: messages.length > 0,
    surfaceOpen: true,
    voiceId,
    onVoiceTurn: appendVoiceTurn,
    onGreeting: appendGreeting,
  });

  const submitMessage = async (rawMessage: string) => {
    const message = rawMessage.trim();
    if (!message || isSending) {
      return;
    }

    const optimisticId = messageId("user");
    const assistantId = messageId("assistant");
    let sawDone = false;
    let sawStreamContent = false;
    setError(null);
    setIsSending(true);
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
              bumpAuditRefresh();
              const turnEntities = event.entities && typeof event.entities === "object"
                ? event.entities as Record<string, unknown>
                : {};
              const followUps = Array.isArray(event.follow_ups)
                ? event.follow_ups.filter((item): item is string => typeof item === "string")
                : [];
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
    <div className="space-y-6">
      <VoiceActiveBanner
        state={voiceSession.state}
        onDisable={() => void voiceSession.stop()}
      />
      <VoiceEnableModal
        open={voiceModalOpen}
        onClose={closeVoiceModal}
        onConfirm={() => void handleVoiceConfirm()}
      />
      <AuditDrawer
        open={auditDrawerOpen}
        onOpenChange={setAuditDrawerOpen}
        sessionId={sessionId}
        refreshKey={auditRefreshKey}
      />
      <Card className="overflow-hidden border-border/70">
        <div className="bg-[radial-gradient(circle_at_top_left,_rgba(15,118,110,0.18),_transparent_45%),linear-gradient(135deg,_rgba(8,47,73,0.96),_rgba(15,23,42,0.98))] px-6 py-6 text-slate-50">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-200">
                {isModuleChat ? <Compass className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                {isModuleChat ? "Module Chat" : "Unified MIRA Chat"}
              </div>
              <div className="space-y-2">
                <h1 className="text-3xl font-semibold tracking-tight">
                  {isModuleChat ? `${scopeLabel} grounded chat` : "Multi-domain engineering chat"}
                </h1>
                <p className="max-w-2xl text-sm text-slate-200/85">
                  {scopeDescription}
                </p>
              </div>
            </div>

            <div className="grid gap-3 text-sm text-slate-100 sm:grid-cols-3">
              <div className="rounded-xl border border-white/10 bg-white/8 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-300">Scope</div>
                <div className="mt-1 font-medium">{scopeLabel}</div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/8 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-300">Session</div>
                <div className="mt-1 font-medium">{sessionId ?? "new conversation"}</div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/8 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-300">Adapters</div>
                <div className="mt-1 font-medium">
                  {pingError ? "status unavailable" : adapters.length ? adapters.join(", ") : "loading"}
                </div>
              </div>
            </div>
          </div>
          {isModuleChat && activeModuleLaunchState?.contextSummary.length ? (
            <div className="mt-5 flex flex-wrap gap-2">
              {activeModuleLaunchState.contextSummary.map((item) => (
                <div
                  key={`${item.label}-${item.value}`}
                  className="rounded-full border border-white/12 bg-white/10 px-3 py-1.5 text-xs text-slate-100/90"
                >
                  <span className="mr-2 uppercase tracking-[0.14em] text-slate-300">{item.label}</span>
                  <span className="font-medium">{item.value}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </Card>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Card className="border-border/70">
          <div className="flex items-center justify-between border-b border-border/70 px-5 py-4">
            <div>
              <h2 className="text-lg font-semibold">Conversation</h2>
              <p className="text-sm text-muted-foreground">
                {isModuleChat
                  ? "This conversation keeps module context attached on every turn. Ask explicitly if you want to switch engines."
                  : "The client sends the last 10 messages back to the API so follow-ups survive a server recycle."}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {isModuleChat && activeModuleLaunchState ? (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => navigate(activeModuleLaunchState.originPath)}
                  >
                    <ArrowLeft className="mr-2 h-4 w-4" />
                    Back to {activeModuleLaunchState.originTitle}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => navigate("/chat")}
                  >
                    Open global chat
                  </Button>
                </>
              ) : null}
              <PivIdentityChip />
              <VoiceControl
                enabled={voiceActive}
                state={voiceSession.state}
                onToggle={handleVoiceToggle}
                onInterrupt={voiceSession.interrupt}
              />
              <VoiceSettings
                voiceId={voiceId}
                onVoiceIdChange={setVoiceId}
                disabled={voiceActive}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setAuditDrawerOpen(true)}
                title="Show audit trail"
              >
                <ClipboardList className="mr-2 h-4 w-4" />
                Show audit
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={clearConversation}>
                <RotateCcw className="mr-2 h-4 w-4" />
                New chat
              </Button>
            </div>
          </div>
          {voiceError && (
            <div className="border-t border-destructive/30 bg-destructive/5 px-5 py-2 text-sm text-destructive">
              Voice: {voiceError}
            </div>
          )}
          {voiceActive && (voiceSession.liveTranscript || voiceSession.liveAssistantText) && (
            <div className="border-t border-border/70 bg-slate-50 px-5 py-2 text-sm text-slate-700">
              {voiceSession.liveTranscript && (
                <div>
                  <span className="text-xs uppercase tracking-[0.16em] text-slate-500">You</span>
                  <span className="ml-2">{voiceSession.liveTranscript}</span>
                </div>
              )}
              {voiceSession.liveAssistantText && (
                <div className="mt-1">
                  <span className="text-xs uppercase tracking-[0.16em] text-slate-500">Mira</span>
                  <span className="ml-2">{voiceSession.liveAssistantText}</span>
                </div>
              )}
            </div>
          )}

          <ScrollArea className="h-[62vh] 2xl:h-[68vh]">
            <div
              className="flex min-h-full flex-col gap-4 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(241,245,249,0.95))] p-5"
            >
              {!messages.length && (
                <div className="space-y-4 rounded-2xl border border-dashed border-border bg-background/80 p-5">
                  <div className="space-y-1">
                    <h3 className="font-medium">Starting points</h3>
                    <p className="text-sm text-muted-foreground">
                      {isModuleChat
                        ? "These prompts stay inside the current module unless you explicitly ask to switch."
                        : "Pick a grounded engineering question or write your own."}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {starterPrompts.map((prompt) => (
                      <Button
                        key={prompt}
                        type="button"
                        variant="outline"
                        className="h-auto whitespace-normal px-3 py-2 text-left"
                        onClick={() => {
                          setDraft(prompt);
                        }}
                      >
                        {prompt}
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((message) => {
                const isAssistant = message.role === "assistant";
                return (
                  <div
                    key={message.id}
                    className={cn("flex", isAssistant ? "justify-start" : "justify-end")}
                  >
                    <div
                      className={cn(
                        "max-w-[92%] rounded-2xl border px-4 py-3 shadow-sm 2xl:max-w-[88%]",
                        isAssistant
                          ? "border-slate-200 bg-white text-slate-900"
                          : "border-teal-700 bg-teal-700 text-white",
                      )}
                    >
                      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.18em] opacity-80">
                        {isAssistant ? <Bot className="h-3.5 w-3.5" /> : <User2 className="h-3.5 w-3.5" />}
                        {isAssistant ? assistantScopeLabel(activeModuleLaunchState, message.engineUsed) : "Engineer"}
                        {isAssistant && message.engineUsed && message.content.trim() && (
                          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                            {message.engineUsed}
                          </span>
                        )}
                        {isAssistant && message.verdict && message.content.trim() && (
                          <Badge variant={verdictVariant(message.verdict)} className="ml-auto">
                            {message.verdict}
                          </Badge>
                        )}
                      </div>
                      <div className="space-y-3 text-sm leading-6">
                        {isAssistant && !message.content && isSending ? (
                          <span className="inline-flex items-center gap-2 text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            {activeModuleLaunchState ? `Running ${activeModuleLaunchState.moduleLabel}` : "Streaming response"}
                          </span>
                        ) : renderMessageContent(message.content)}
                      </div>

                      {isAssistant && (message.auditId || message.followUps?.length) && (
                        <div className="mt-4 space-y-3 border-t border-slate-200 pt-3">
                          {message.auditId && (
                            <div className="text-xs text-muted-foreground">
                              Audit ID: <span className="font-mono">{message.auditId}</span>
                            </div>
                          )}
                          {!!message.followUps?.length && (
                            <div className="flex flex-wrap gap-2">
                              {message.followUps.map((followUp) => (
                                <Button
                                  key={`${message.id}-${followUp}`}
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-auto px-3 py-1.5"
                                  onClick={() => {
                                    void submitMessage(followUp);
                                  }}
                                >
                                  {followUp}
                                </Button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}

              {isSending && (
                <div className="flex justify-start">
                  <div className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-muted-foreground shadow-sm">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Running domain engine and formatter
                  </div>
                </div>
              )}

              <div ref={conversationEndRef} />
            </div>
          </ScrollArea>

          <div className="border-t border-border/70 p-5">
            <div className="space-y-3">
              <Textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submitMessage(draft);
                  }
                }}
                placeholder="Ask an engineering question. Press Enter to send, Shift+Enter for a new line."
                className="min-h-[116px] resize-none"
              />

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-sm text-muted-foreground">
                  {isModuleChat
                    ? "Chat history stays in this browser, the API receives the last 10 messages, and the current module context is sent each turn."
                    : "Chat history stays in this browser and the API receives the last 10 messages each turn."}
                </div>
                <Button type="button" onClick={() => void submitMessage(draft)} disabled={isSending || !draft.trim()}>
                  {isSending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <SendHorizonal className="mr-2 h-4 w-4" />}
                  Send
                </Button>
              </div>

              {error && (
                <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {error}
                </div>
              )}
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="border-border/70 p-5">
            <div className="space-y-3">
              <h2 className="text-base font-semibold">{isModuleChat ? "Active grounding" : "Module coverage"}</h2>
              <p className="text-sm text-muted-foreground">
                {isModuleChat
                  ? "This chat stays grounded in the originating page context until you explicitly ask to cross into another engine."
                  : "The current runtime exposes a single conversational entrypoint and routes into the domain engines listed below."}
              </p>
              {isModuleChat && activeModuleLaunchState?.contextSummary.length ? (
                <div className="space-y-2">
                  {activeModuleLaunchState.contextSummary.map((item) => (
                    <div
                      key={`context-${item.label}-${item.value}`}
                      className="rounded-xl border border-border/70 bg-muted/30 px-3 py-2"
                    >
                      <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                        {item.label}
                      </div>
                      <div className="mt-1 text-sm font-medium text-foreground">{item.value}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {(adapters.length ? adapters : ["oca", "h2", "galvanic", "fracture", "maptis_search", "bsmh", "gpcm"]).map((adapter) => (
                    <Badge key={adapter} variant="secondary" className="px-2.5 py-1">
                      {adapter}
                    </Badge>
                  ))}
                </div>
              )}
              {pingError && (
                <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {pingError}
                </div>
              )}
            </div>
          </Card>

          <Card className="border-border/70 p-5">
            <div className="space-y-3">
              <h2 className="text-base font-semibold">Suggested prompts</h2>
              <div className="space-y-2">
                {starterPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    className="w-full rounded-xl border border-border bg-background px-3 py-3 text-left text-sm transition-colors hover:border-teal-400 hover:bg-teal-50"
                    onClick={() => {
                      setDraft(prompt);
                    }}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          </Card>

          <Card className="border-border/70 p-5">
            <div className="space-y-2">
              <h2 className="text-base font-semibold">Context notes</h2>
              <p className="text-sm text-muted-foreground">
                {isModuleChat
                  ? "Module chat relies on explicit page context plus echoed entities from prior turns. That keeps follow-ups stable even if the chat worker recycles."
                  : "Global chat relies on echoed entities and recent history. That keeps the current single-replica AWS deployment usable even without a dedicated chat DB."}
              </p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
