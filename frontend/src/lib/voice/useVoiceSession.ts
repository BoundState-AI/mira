import { useCallback, useEffect, useRef, useState } from "react";

import type { MiraChatMessage } from "@/lib/chat-api";
import { VoiceClient } from "./voiceClient";
import type { VoiceState, VoiceTurnSummary } from "./types";

export interface UseVoiceSessionOptions {
  voiceId: string | null;
  chatSessionId: string | null;
  moduleContext: Record<string, unknown> | null;
  history: MiraChatMessage[];
  onTurnComplete?: (summary: VoiceTurnSummary) => void;
  onError?: (message: string) => void;
  onTranscript?: (text: string) => void;
  onAssistantDelta?: (delta: string) => void;
}

export interface UseVoiceSessionResult {
  state: VoiceState;
  liveTranscript: string;
  liveAssistantText: string;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  interrupt: () => void;
  setVoiceId: (value: string | null) => void;
}

export function useVoiceSession(opts: UseVoiceSessionOptions): UseVoiceSessionResult {
  const clientRef = useRef<VoiceClient | null>(null);
  const [state, setState] = useState<VoiceState>("idle");
  const [liveTranscript, setLiveTranscript] = useState("");
  const [liveAssistantText, setLiveAssistantText] = useState("");

  const optsRef = useRef(opts);
  optsRef.current = opts;

  useEffect(() => () => {
    void clientRef.current?.stop();
    clientRef.current = null;
  }, []);

  useEffect(() => {
    clientRef.current?.setModuleContext(opts.moduleContext);
  }, [opts.moduleContext]);

  useEffect(() => {
    clientRef.current?.setHistory(opts.history);
  }, [opts.history]);

  useEffect(() => {
    clientRef.current?.setVoiceId(opts.voiceId);
  }, [opts.voiceId]);

  const start = useCallback(async () => {
    // A client left over from a failed session blocks restart — tear it
    // down and build fresh so the toggle recovers after an error.
    if (clientRef.current) {
      if (clientRef.current.currentState !== "error") return;
      const stale = clientRef.current;
      clientRef.current = null;
      await stale.stop().catch(() => undefined);
    }
    setLiveTranscript("");
    setLiveAssistantText("");
    const client = new VoiceClient({
      voiceId: optsRef.current.voiceId,
      chatSessionId: optsRef.current.chatSessionId,
      moduleContext: optsRef.current.moduleContext,
      history: optsRef.current.history,
      onStateChange: (next) => setState(next),
      onTranscript: (text) => {
        setLiveTranscript(text);
        optsRef.current.onTranscript?.(text);
      },
      onAssistantDelta: (delta) => {
        setLiveAssistantText((prev) => prev + delta);
        optsRef.current.onAssistantDelta?.(delta);
      },
      onTurnComplete: (summary) => {
        setLiveTranscript("");
        setLiveAssistantText("");
        optsRef.current.onTurnComplete?.(summary);
      },
      onError: (message) => {
        optsRef.current.onError?.(message);
      },
    });
    clientRef.current = client;
    try {
      await client.start();
    } catch (err) {
      optsRef.current.onError?.((err as Error).message);
      clientRef.current = null;
    }
  }, []);

  const stop = useCallback(async () => {
    const client = clientRef.current;
    clientRef.current = null;
    if (client) {
      await client.stop();
    }
    setState("idle");
    setLiveTranscript("");
    setLiveAssistantText("");
  }, []);

  const interrupt = useCallback(() => {
    clientRef.current?.interrupt();
  }, []);

  const setVoiceId = useCallback((value: string | null) => {
    clientRef.current?.setVoiceId(value);
  }, []);

  return {
    state,
    liveTranscript,
    liveAssistantText,
    start,
    stop,
    interrupt,
    setVoiceId,
  };
}
