import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Loader2, RotateCcw, SendHorizonal, User2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { fetchMiraChatPing, sendMiraChatMessage, type MiraChatMessage } from "@/lib/chat-api";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "mira-chat-session-v1";
const MAX_HISTORY_MESSAGES = 10;
const MAX_STORED_MESSAGES = 24;
const EXAMPLE_PROMPTS = [
  "Is 316L compatible with GOX at 3000 psi?",
  "What galvanic risk do I have between 7075-T73 and CRES 304 in seawater proxy?",
  "Can you compare hydrogen compatibility for Inconel 718 and A286?",
  "What MAPTIS evidence exists for Inconel 625 in aged versus cast condition?",
];

type Verdict = "PASS" | "CONDITIONAL_PASS" | "FAIL" | "REFUSE" | "INSUFFICIENT_DATA" | "ERROR" | null;

interface ChatUiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  engineUsed?: string | null;
  verdict?: Verdict;
  auditId?: string | null;
  followUps?: string[];
  entities: Record<string, unknown>;
}

interface StoredConversation {
  sessionId: string | null;
  messages: ChatUiMessage[];
}

function verdictVariant(verdict: Verdict): "default" | "secondary" | "destructive" | "outline" {
  if (verdict === "PASS") return "default";
  if (verdict === "FAIL" || verdict === "ERROR" || verdict === "REFUSE") return "destructive";
  if (verdict === "CONDITIONAL_PASS") return "secondary";
  return "outline";
}

function loadConversation(): StoredConversation {
  if (typeof window === "undefined") {
    return { sessionId: null, messages: [] };
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return { sessionId: null, messages: [] };
    }
    const parsed = JSON.parse(raw) as StoredConversation;
    return {
      sessionId: parsed.sessionId ?? null,
      messages: Array.isArray(parsed.messages) ? parsed.messages : [],
    };
  } catch {
    return { sessionId: null, messages: [] };
  }
}

function saveConversation(conversation: StoredConversation): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversation));
  } catch {
    // Ignore storage failures; the chat still works without persistence.
  }
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

export default function MiraChat() {
  const initialConversation = useMemo(() => loadConversation(), []);
  const [sessionId, setSessionId] = useState<string | null>(initialConversation.sessionId);
  const [messages, setMessages] = useState<ChatUiMessage[]>(initialConversation.messages);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [adapters, setAdapters] = useState<string[]>([]);
  const [pingError, setPingError] = useState<string | null>(null);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    saveConversation({ sessionId, messages });
  }, [messages, sessionId]);

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
    saveConversation({ sessionId: null, messages: [] });
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
                <Bot className="h-3.5 w-3.5" />
                Unified MIRA Chat
              </div>
              <div className="space-y-2">
                <h1 className="text-3xl font-semibold tracking-tight">Multi-domain engineering chat</h1>
                <p className="max-w-2xl text-sm text-slate-200/85">
                  Ask one question, route into OCA, H2, galvanic, fracture, MAPTIS, BSMH, or
                  compliance logic, and keep the conversation grounded with browser-held history.
                </p>
              </div>
            </div>

            <div className="grid gap-3 text-sm text-slate-100 sm:grid-cols-2">
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
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="border-border/70">
          <div className="flex items-center justify-between border-b border-border/70 px-5 py-4">
            <div>
              <h2 className="text-lg font-semibold">Conversation</h2>
              <p className="text-sm text-muted-foreground">
                The client sends the last 10 messages back to the API so follow-ups survive a server
                recycle.
              </p>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={clearConversation}>
              <RotateCcw className="mr-2 h-4 w-4" />
              New chat
            </Button>
          </div>

          <ScrollArea className="h-[58vh]">
            <div
              className="flex min-h-full flex-col gap-4 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(241,245,249,0.95))] p-5"
            >
              {!messages.length && (
                <div className="space-y-4 rounded-2xl border border-dashed border-border bg-background/80 p-5">
                  <div className="space-y-1">
                    <h3 className="font-medium">Starting points</h3>
                    <p className="text-sm text-muted-foreground">
                      Pick a grounded engineering question or write your own.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {EXAMPLE_PROMPTS.map((prompt) => (
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
                        "max-w-[85%] rounded-2xl border px-4 py-3 shadow-sm",
                        isAssistant
                          ? "border-slate-200 bg-white text-slate-900"
                          : "border-teal-700 bg-teal-700 text-white",
                      )}
                    >
                      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.18em] opacity-80">
                        {isAssistant ? <Bot className="h-3.5 w-3.5" /> : <User2 className="h-3.5 w-3.5" />}
                        {isAssistant ? "MIRA" : "Engineer"}
                        {isAssistant && message.engineUsed && (
                          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                            {message.engineUsed}
                          </span>
                        )}
                        {isAssistant && message.verdict && (
                          <Badge variant={verdictVariant(message.verdict)} className="ml-auto">
                            {message.verdict}
                          </Badge>
                        )}
                      </div>
                      <p className="whitespace-pre-wrap text-sm leading-6">{message.content}</p>

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
                  Chat history stays in this browser and the API receives the last 10 messages each turn.
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
              <h2 className="text-base font-semibold">Module coverage</h2>
              <p className="text-sm text-muted-foreground">
                The current runtime exposes a single conversational entrypoint and routes into the
                domain engines listed below.
              </p>
              <div className="flex flex-wrap gap-2">
                {(adapters.length ? adapters : ["oca", "h2", "galvanic", "fracture", "maptis_search", "bsmh", "gpcm"]).map((adapter) => (
                  <Badge key={adapter} variant="secondary" className="px-2.5 py-1">
                    {adapter}
                  </Badge>
                ))}
              </div>
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
                {EXAMPLE_PROMPTS.map((prompt) => (
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
                For module-specific follow-ups, this page relies on echoed entities and recent history.
                That keeps the current single-replica AWS deployment usable even without a dedicated chat DB.
              </p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
