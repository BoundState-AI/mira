import { Loader2, Mic, MicOff, Square, Volume2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { VoiceState } from "@/lib/voice/types";

interface VoiceControlProps {
  enabled: boolean;
  state: VoiceState;
  onToggle: () => void;
  onInterrupt: () => void;
  className?: string;
  disabled?: boolean;
}

const STATE_LABEL: Record<VoiceState, string> = {
  idle: "Voice off",
  connecting: "Connecting",
  ready: "Listening",
  listening: "Hearing you",
  thinking: "Thinking",
  speaking: "Speaking",
  error: "Voice error",
};

export function VoiceControl({
  enabled,
  state,
  onToggle,
  onInterrupt,
  className,
  disabled,
}: VoiceControlProps) {
  const isActive = enabled && state !== "idle" && state !== "error";
  const showInterrupt = state === "speaking" || state === "thinking";

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Button
        type="button"
        variant={isActive ? "default" : "outline"}
        size="sm"
        onClick={onToggle}
        disabled={disabled}
        className={cn(
          "transition-colors",
          isActive && "bg-teal-700 text-white hover:bg-teal-600",
        )}
      >
        {state === "connecting" ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : isActive ? (
          <Mic className="mr-2 h-4 w-4" />
        ) : (
          <MicOff className="mr-2 h-4 w-4" />
        )}
        {isActive ? "Voice on" : "Voice off"}
      </Button>

      {isActive && (
        <div className="flex items-center gap-2 rounded-full border border-teal-300/50 bg-teal-50 px-3 py-1 text-xs font-medium text-teal-900">
          <StatePulse state={state} />
          {STATE_LABEL[state]}
        </div>
      )}

      {showInterrupt && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onInterrupt}
          className="text-xs"
        >
          <Square className="mr-1.5 h-3 w-3" />
          Stop
        </Button>
      )}
    </div>
  );
}

function StatePulse({ state }: { state: VoiceState }) {
  if (state === "speaking") {
    return <Volume2 className="h-3.5 w-3.5 text-teal-700" />;
  }
  const animate = state === "listening" || state === "ready";
  return (
    <span className="relative inline-flex h-2 w-2">
      {animate && (
        <span className="absolute inset-0 inline-flex animate-ping rounded-full bg-teal-500 opacity-75" />
      )}
      <span
        className={cn(
          "relative inline-flex h-2 w-2 rounded-full",
          state === "thinking" ? "bg-amber-500" : "bg-teal-600",
        )}
      />
    </span>
  );
}
