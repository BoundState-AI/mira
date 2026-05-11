import { useEffect, useState } from "react";
import { Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchVoiceList } from "@/lib/voice/voiceApi";
import type { VoiceListEntry, VoiceListResponse } from "@/lib/voice/types";

interface VoiceSettingsProps {
  voiceId: string | null;
  onVoiceIdChange: (value: string) => void;
  disabled?: boolean;
}

export function VoiceSettings({ voiceId, onVoiceIdChange, disabled }: VoiceSettingsProps) {
  const [voices, setVoices] = useState<VoiceListEntry[]>([]);
  const [provider, setProvider] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchVoiceList()
      .then((data: VoiceListResponse) => {
        if (cancelled) return;
        setVoices(data.voices);
        setProvider(data.provider);
        if (!voiceId && data.default_voice_id) {
          onVoiceIdChange(data.default_voice_id);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load voices");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [onVoiceIdChange, voiceId]);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm" disabled={disabled}>
          <Settings2 className="mr-2 h-4 w-4" />
          Voice settings
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 space-y-3">
        <div className="space-y-1">
          <Label className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
            TTS provider
          </Label>
          <div className="text-sm font-medium">{provider || "—"}</div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="voice-id-select" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
            Voice
          </Label>
          <Select
            value={voiceId ?? ""}
            onValueChange={(value) => onVoiceIdChange(value)}
            disabled={disabled || loading || voices.length === 0}
          >
            <SelectTrigger id="voice-id-select">
              <SelectValue placeholder={loading ? "Loading voices…" : "Select voice"} />
            </SelectTrigger>
            <SelectContent>
              {voices.map((voice) => (
                <SelectItem key={voice.voice_id} value={voice.voice_id}>
                  {voice.name}
                  {voice.language ? ` · ${voice.language}` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {error && (
          <div className="rounded border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs text-destructive">
            {error}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
