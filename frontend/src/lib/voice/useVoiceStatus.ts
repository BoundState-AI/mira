// Cached fetch of /api/chat/voice/status so the safety chips and banners
// don't each hit the endpoint. Status doesn't change at runtime, so one
// request per page load covers every consumer.

import { useEffect, useState } from "react";

import { fetchVoiceStatus } from "./voiceApi";
import type { VoiceConfigInfo } from "./types";

let cachedPromise: Promise<VoiceConfigInfo> | null = null;

function load(): Promise<VoiceConfigInfo> {
  if (!cachedPromise) {
    cachedPromise = fetchVoiceStatus().catch((err) => {
      cachedPromise = null;
      throw err;
    });
  }
  return cachedPromise;
}

export function useVoiceStatus(): VoiceConfigInfo | null {
  const [status, setStatus] = useState<VoiceConfigInfo | null>(null);
  useEffect(() => {
    let cancelled = false;
    load()
      .then((value) => {
        if (!cancelled) setStatus(value);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return status;
}
