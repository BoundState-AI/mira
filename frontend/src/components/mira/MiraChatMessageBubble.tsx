import { Bot, FileText, Loader2, User2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Verdict = "PASS" | "CONDITIONAL_PASS" | "FAIL" | "REFUSE" | "INSUFFICIENT_DATA" | "ERROR" | null;

type MiraChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  engineUsed?: string | null;
  verdict?: string | null;
  auditId?: string | null;
  followUps?: string[];
  citations?: string[];
  advisoryOnly?: boolean;
};

interface MiraChatMessageBubbleProps {
  message: MiraChatMessage;
  assistantLabel: string;
  isSending: boolean;
  onFollowUp: (query: string) => void;
  compact?: boolean;
  showAuditId?: boolean;
}

function verdictVariant(verdict: Verdict): "default" | "secondary" | "destructive" | "outline" {
  if (verdict === "PASS") return "default";
  if (verdict === "FAIL" || verdict === "ERROR" || verdict === "REFUSE") return "destructive";
  if (verdict === "CONDITIONAL_PASS") return "secondary";
  return "outline";
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

export function MiraChatMessageBubble({
  message,
  assistantLabel,
  isSending,
  onFollowUp,
  compact = false,
  showAuditId = false,
}: MiraChatMessageBubbleProps) {
  const isAssistant = message.role === "assistant";
  const verdict = (typeof message.verdict === "string" ? message.verdict : null) as Verdict;
  const citations = Array.isArray(message.citations) ? message.citations.filter(Boolean) : [];
  const followUps = Array.isArray(message.followUps) ? message.followUps.filter(Boolean) : [];
  const isStreamingPlaceholder = isAssistant && !message.content && isSending;

  return (
    <div className={cn("flex min-w-0", isAssistant ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "min-w-0 rounded-2xl border shadow-sm",
          compact
            ? isAssistant
              ? "max-w-[96%] px-3 py-2"
              : "max-w-[90%] px-4 py-3 sm:max-w-[80%]"
            : "max-w-[92%] px-4 py-3 2xl:max-w-[88%]",
          isAssistant
            ? "border-slate-200 bg-white text-slate-900"
            : "border-teal-700 bg-teal-700 text-white",
        )}
      >
        <div className={cn("mb-2 flex flex-wrap items-center gap-2 opacity-80", compact ? "text-[10px] uppercase tracking-[0.14em]" : "text-xs uppercase tracking-[0.18em]")}>
          {isAssistant ? <Bot className="h-3.5 w-3.5" /> : <User2 className="h-3.5 w-3.5" />}
          {isAssistant ? assistantLabel : "Engineer"}
          {isAssistant && message.engineUsed && message.content.trim() ? (
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-medium text-slate-600">
              {message.engineUsed}
            </span>
          ) : null}
          {isAssistant && verdict && message.content.trim() ? (
            <Badge variant={verdictVariant(verdict)} className="ml-auto text-[10px]">
              {verdict}
            </Badge>
          ) : null}
        </div>

        <div className={cn("space-y-3 break-words", compact ? "text-sm leading-5" : "text-sm leading-6")}>
          {isStreamingPlaceholder ? (
            <span className="inline-flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Running {assistantLabel}
            </span>
          ) : renderMessageContent(message.content)}
        </div>

        {isAssistant && (message.advisoryOnly || citations.length > 0 || showAuditId || followUps.length > 0) ? (
          <div className="mt-3 space-y-3 border-t border-slate-200 pt-3">
            {message.advisoryOnly ? (
              <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] text-amber-800">
                <FileText className="h-3.5 w-3.5" />
                Advisory only. Oracle surfaces governing clauses; it does not sign off or approve.
              </div>
            ) : null}

            {citations.length > 0 ? (
              <div className="space-y-2">
                <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-500">
                  Citations
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {citations.map((citation) => (
                    <span
                      key={`${message.id}-${citation}`}
                      className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] text-slate-700"
                    >
                      {citation}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {showAuditId && message.auditId ? (
              <div className="text-xs text-muted-foreground">
                Audit ID: <span className="font-mono">{message.auditId}</span>
              </div>
            ) : null}

            {followUps.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {followUps.slice(0, compact ? 2 : followUps.length).map((followUp) => (
                  <Button
                    key={`${message.id}-${followUp}`}
                    type="button"
                    size="sm"
                    variant="outline"
                    className={cn("h-auto", compact ? "px-2 py-1 text-[11px]" : "px-3 py-1.5")}
                    onClick={() => {
                      onFollowUp(followUp);
                    }}
                  >
                    {followUp}
                  </Button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
