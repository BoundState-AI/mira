import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Bot, Compass, Loader2, RotateCcw, SendHorizonal, User2 } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { fetchMiraChatPing, sendMiraChatMessage, type MiraChatMessage } from "@/lib/chat-api";
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
  type MiraChatStoredMessage,
  type MiraModuleChatLaunchState,
} from "@/lib/mira-chat-context";
import { cn } from "@/lib/utils";

const MAX_HISTORY_MESSAGES = 10;
const MAX_STORED_MESSAGES = 24;
const GLOBAL_EXAMPLE_PROMPTS = [
  "Is 316L compatible with GOX at 3000 psi?",
  "What galvanic risk do I have between 7075-T73 and CRES 304 in seawater proxy?",
  "Can you compare hydrogen compatibility for Inconel 718 and A286?",
  "What MAPTIS evidence exists for Inconel 625 in aged versus cast condition?",
];

type Verdict = "PASS" | "CONDITIONAL_PASS" | "FAIL" | "REFUSE" | "INSUFFICIENT_DATA" | "ERROR" | null;

type ChatUiMessage = MiraChatStoredMessage & { verdict?: Verdict };

function verdictVariant(verdict: Verdict): "default" | "secondary" | "destructive" | "outline" {
  if (verdict === "PASS") return "default";
  if (verdict === "FAIL" || verdict === "ERROR" || verdict === "REFUSE") return "destructive";
  if (verdict === "CONDITIONAL_PASS") return "secondary";
  return "outline";
}

function toHistoryMessages(messages: ChatUiMessage[]): MiraChatMessage[] {
  return messages.slice(-MAX_HISTORY_MESSAGES).map((message) => ({
    role: message.role,
    content: message.content,
    engine_used: message.engineUsed ?? undefined,
    entities: message.entities,
  }));
}

function messageId(prefix: "user" | "assistant"): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function resizeComposer(textarea: HTMLTextAreaElement | null, minHeight: number, maxHeight: number) {
  if (!textarea) {
    return;
  }
  textarea.style.height = "0px";
  const nextHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
  textarea.style.height = `${nextHeight}px`;
}

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
  const conversationEndRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
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

  useEffect(() => {
    resizeComposer(composerRef.current, 132, 288);
  }, [draft]);

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

  const submitMessage = async (rawMessage: string) => {
    const message = rawMessage.trim();
    if (!message || isSending) {
      return;
    }

    const optimisticId = messageId("user");
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
    ]);

    try {
      const response = await sendMiraChatMessage({
        message,
        session_id: sessionId ?? undefined,
        history: toHistoryMessages(messages),
        module_context: activeModuleLaunchState?.moduleContext,
      });

      const turnEntities = response.entities ?? {};
      setSessionId(response.session_id);
      setMessages((current) => {
        const updated = current.map((currentMessage) =>
          currentMessage.id === optimisticId
            ? { ...currentMessage, entities: turnEntities }
            : currentMessage,
        );
        updated.push({
          id: messageId("assistant"),
          role: "assistant",
          content: response.response,
          engineUsed: response.engine_used ?? null,
          verdict: (response.verdict as Verdict | undefined) ?? null,
          auditId: response.audit_id ?? null,
          followUps: response.follow_up_suggestions ?? [],
          entities: turnEntities,
        });
        return updated.slice(-MAX_STORED_MESSAGES);
      });
    } catch (submitError: unknown) {
      setMessages((current) => current.filter((currentMessage) => currentMessage.id !== optimisticId));
      setDraft(message);
      setError(submitError instanceof Error ? submitError.message : "Chat request failed.");
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="space-y-6">
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
                  {isModuleChat ? `${scopeLabel} expert chat` : "Multi-domain engineering chat"}
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
              <Button type="button" variant="outline" size="sm" onClick={clearConversation}>
                <RotateCcw className="mr-2 h-4 w-4" />
                New chat
              </Button>
            </div>
          </div>

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
                    className={cn("flex min-w-0", isAssistant ? "justify-start" : "justify-end")}
                  >
                    <div
                      className={cn(
                        "min-w-0 max-w-[92%] rounded-2xl border px-4 py-3 shadow-sm 2xl:max-w-[88%]",
                        isAssistant
                          ? "border-slate-200 bg-white text-slate-900"
                          : "border-teal-700 bg-teal-700 text-white",
                      )}
                    >
                      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.18em] opacity-80">
                        {isAssistant ? <Bot className="h-3.5 w-3.5" /> : <User2 className="h-3.5 w-3.5" />}
                        {isAssistant ? "MIRA" : "Engineer"}
                        {isAssistant && message.engineUsed && (
                          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                            {message.engineUsed}
                          </span>
                        )}
                        {isAssistant && message.verdict && (
                          <Badge variant={verdictVariant(message.verdict)} className="sm:ml-auto">
                            {message.verdict}
                          </Badge>
                        )}
                      </div>
                      <div className="space-y-3 break-words text-sm leading-6">{renderMessageContent(message.content)}</div>

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
                ref={composerRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submitMessage(draft);
                  }
                }}
                placeholder="Ask an engineering question. Press Enter to send, Shift+Enter for a new line."
                className="min-h-[132px] max-h-[288px] resize-none overflow-y-auto px-4 py-3 leading-6"
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
