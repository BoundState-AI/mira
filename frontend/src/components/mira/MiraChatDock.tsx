import { useEffect, useMemo, useState } from "react";
import { Bot, Compass, Expand, Loader2, MessageSquare, Minimize2, SendHorizonal, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { fetchMiraChatPing } from "@/lib/chat-api";
import {
  buildChatScopeSearch,
  createModuleChatLaunchState,
  loadRouteModuleChatState,
  MIRA_CHAT_GLOBAL_SCOPE_KEY,
  MIRA_CHAT_ROUTE_STATE_EVENT,
  type MiraModuleChatLaunchState,
} from "@/lib/mira-chat-context";
import { cn } from "@/lib/utils";
import { useMiraChat, verdictVariant } from "@/hooks/useMiraChat";

const GLOBAL_WIDGET_PROMPTS = [
  "Is 316L compatible with GOX at 3000 psi?",
  "What galvanic risk do I have between 7075-T73 and CRES 304?",
];

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
    default:
      return null;
  }
}

export function MiraChatDock() {
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [routeStateVersion, setRouteStateVersion] = useState(0);
  const [serviceHealthy, setServiceHealthy] = useState(true);

  const activeModuleLaunchState = useMemo(
    () => loadRouteModuleChatState(location.pathname) ?? fallbackLaunchState(location.pathname),
    [location.pathname, routeStateVersion],
  );
  const scopeKey = activeModuleLaunchState?.scopeKey ?? MIRA_CHAT_GLOBAL_SCOPE_KEY;
  const starterPrompts = activeModuleLaunchState?.starterPrompts.length
    ? activeModuleLaunchState.starterPrompts.slice(0, 2)
    : GLOBAL_WIDGET_PROMPTS;

  const {
    messages,
    draft,
    setDraft,
    error,
    isSending,
    streamingMessage,
    conversationEndRef,
    submitMessage,
    clearConversation,
  } = useMiraChat({ scopeKey, activeModuleLaunchState });

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

  // Scroll into view when dock opens
  useEffect(() => {
    if (open) {
      conversationEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [open, conversationEndRef]);

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

  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex max-w-[calc(100vw-1.5rem)] flex-col items-end gap-3">
      {open ? (
        <Card className="pointer-events-auto flex h-[36rem] w-[24rem] max-w-[calc(100vw-1.5rem)] flex-col overflow-hidden border-border/80 shadow-2xl">
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

          <ScrollArea className="flex-1 bg-[linear-gradient(180deg,rgba(248,250,252,0.98),rgba(241,245,249,0.96))]">
            <div className="flex min-h-full flex-col gap-3 p-4">
              {!messages.length && !streamingMessage ? (
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
                const isAssistant = message.role === "assistant";
                return (
                  <div
                    key={message.id}
                    className={cn("flex", isAssistant ? "justify-start" : "justify-end")}
                  >
                    <div
                      className={cn(
                        "max-w-[90%] rounded-2xl border px-3 py-2 shadow-sm",
                        isAssistant
                          ? "border-slate-200 bg-white text-slate-900"
                          : "border-teal-700 bg-teal-700 text-white",
                      )}
                    >
                      <div className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] opacity-80">
                        {isAssistant ? "MIRA" : "You"}
                        {isAssistant && message.engineUsed ? (
                          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[9px] font-medium text-slate-600">
                            {message.engineUsed}
                          </span>
                        ) : null}
                        {isAssistant && message.verdict ? (
                          <Badge variant={verdictVariant(message.verdict)} className="ml-auto text-[10px]">
                            {message.verdict}
                          </Badge>
                        ) : null}
                      </div>
                      <div className="whitespace-pre-wrap text-sm leading-5">{message.content}</div>
                      {isAssistant && message.followUps?.length ? (
                        <div className="mt-2 flex flex-wrap gap-1.5 border-t border-slate-200 pt-2">
                          {message.followUps.slice(0, 2).map((followUp) => (
                            <Button
                              key={`${message.id}-${followUp}`}
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-auto px-2 py-1 text-[11px]"
                              onClick={() => {
                                void submitMessage(followUp);
                              }}
                            >
                              {followUp}
                            </Button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}

              {streamingMessage && (
                <div className="flex justify-start">
                  <div className="max-w-[90%] rounded-2xl border border-slate-200 bg-white px-3 py-2 shadow-sm text-slate-900">
                    <div className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      MIRA
                    </div>
                    {streamingMessage.content ? (
                      <div className="whitespace-pre-wrap text-sm leading-5">
                        {streamingMessage.content}
                      </div>
                    ) : streamingMessage.thinking ? (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Thinking
                      </div>
                    ) : null}
                  </div>
                </div>
              )}

              {isSending && !streamingMessage ? (
                <div className="flex justify-start">
                  <div className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-xs text-muted-foreground shadow-sm">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Running the engine
                  </div>
                </div>
              ) : null}

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
                  onClick={clearConversation}
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
