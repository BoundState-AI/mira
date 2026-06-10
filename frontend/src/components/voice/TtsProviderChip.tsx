import { CloudCog, ShieldCheck, TestTube2 } from "lucide-react";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface TtsProviderChipProps {
  provider: string;
  isCommercial?: boolean;
  className?: string;
  compact?: boolean;
}

/**
 * Surfaces the active TTS provider with a colour-coded chip so neither the
 * demoer nor the audience can miss when response text is leaving GovCloud.
 *
 *   polly / mock           → neutral (in-region or stub)
 *   elevenlabs / cartesia  → amber + tooltip explaining the egress
 */
export function TtsProviderChip({ provider, isCommercial, className, compact }: TtsProviderChipProps) {
  const isMock = provider === "mock" || provider.startsWith("mock");
  const commercial = Boolean(isCommercial) || provider === "elevenlabs" || provider === "cartesia";

  if (isMock) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-700",
          className,
        )}
        title="Mock TTS — no real audio. Set MIRA_VOICE_TTS_PROVIDER to enable a real voice."
      >
        <TestTube2 className="h-3 w-3" />
        mock TTS
      </span>
    );
  }

  if (!commercial) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-900",
          className,
        )}
        title={`In-region TTS via ${provider}`}
      >
        <ShieldCheck className="h-3 w-3" />
        {provider}
      </span>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border border-amber-400 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-900",
              className,
            )}
          >
            <CloudCog className="h-3 w-3" />
            {compact ? provider : `${provider} · commercial cloud`}
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-xs text-xs">
          <div className="font-semibold">Split-serving TTS</div>
          <div className="mt-1">
            Response text leaves GovCloud and is sent to{" "}
            <code>api.{provider}.{provider === "elevenlabs" ? "io" : "ai"}</code> for synthesis.
          </div>
          <div className="mt-1 opacity-90">
            Mic audio, identity, citations, and audit records stay in GovCloud. Use only with
            non-sensitive example queries until a FedRAMP path is in place.
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
