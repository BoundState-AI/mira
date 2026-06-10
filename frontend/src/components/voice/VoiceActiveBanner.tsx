import { MicOff, Radio } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useVoiceStatus } from "@/lib/voice/useVoiceStatus";
import type { VoiceState } from "@/lib/voice/types";
import { TtsProviderChip } from "./TtsProviderChip";

interface VoiceActiveBannerProps {
  state: VoiceState;
  onDisable: () => void;
}

const STATE_TEXT: Record<VoiceState, string> = {
  idle: "",
  connecting: "Connecting to the voice service…",
  ready: "Voice mode is on — Mira is listening on this page.",
  listening: "Mira is hearing you…",
  thinking: "Mira is thinking…",
  speaking: "Mira is speaking — interrupt by talking over her.",
  error: "Voice mode hit an error. Try toggling it off and on.",
};

export function VoiceActiveBanner({ state, onDisable }: VoiceActiveBannerProps) {
  const status = useVoiceStatus();
  if (state === "idle") return null;
  return (
    <div className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-teal-300/50 bg-teal-50/95 px-4 py-2 text-sm text-teal-900 backdrop-blur">
      <div className="flex flex-wrap items-center gap-2">
        <Radio className="h-4 w-4 text-teal-700" />
        <span>{STATE_TEXT[state]}</span>
        {status ? (
          <TtsProviderChip
            provider={status.tts_provider}
            isCommercial={status.tts_is_commercial}
            compact
          />
        ) : null}
        <span className="ml-2 hidden text-xs uppercase tracking-[0.18em] text-teal-700/70 sm:inline">
          Click "Voice off" when you're done
        </span>
      </div>
      <Button type="button" variant="ghost" size="sm" onClick={onDisable} className="text-teal-900 hover:bg-teal-100">
        <MicOff className="mr-2 h-4 w-4" />
        Voice off
      </Button>
    </div>
  );
}
