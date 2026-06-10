// Reusable glue between a chat surface and the voice subsystem.
//
// Any component that renders a chat conversation (full-page MiraChat, the
// floating MiraChatDock, or a future build embedding Mira chat) gets the
// complete voice lifecycle from this one hook: session management, the
// enable-confirmation modal, error surfacing, the page-aware presence
// greeting, and audit-drawer refresh signaling. The component keeps
// ownership of its message list — it supplies callbacks for inserting
// voice turns and greetings in whatever shape its local state uses.

import { useCallback, useEffect, useRef, useState } from "react";

import type { MiraChatMessage } from "@/lib/chat-api";
import { useVoiceSession, type UseVoiceSessionResult } from "./useVoiceSession";
import { fetchPresenceGreeting } from "./voiceApi";
import type { VoiceTurnSummary } from "./types";

export interface UseVoiceChatIntegrationOptions {
  sessionId: string | null;
  history: MiraChatMessage[];
  moduleContext: Record<string, unknown> | null;
  /** True once the stored conversation has been loaded from persistence. */
  conversationLoaded: boolean;
  /** True when the conversation has at least one message (suppresses greeting). */
  hasMessages: boolean;
  /**
   * Whether the chat surface is currently visible. Gates the presence
   * greeting, and when it flips false any active voice session is stopped
   * so a collapsed surface never keeps the mic open. Surfaces that are
   * always visible while mounted pass true.
   */
  surfaceOpen: boolean;
  voiceId: string | null;
  /** Insert a completed voice turn into the surface's message list. */
  onVoiceTurn: (summary: VoiceTurnSummary) => void;
  /** Insert a proactive page-aware greeting as an assistant message. */
  onGreeting: (text: string) => void;
}

export interface VoiceChatIntegration {
  voiceSession: UseVoiceSessionResult;
  voiceActive: boolean;
  voiceError: string | null;
  voiceModalOpen: boolean;
  closeVoiceModal: () => void;
  handleVoiceToggle: () => void;
  handleVoiceConfirm: () => Promise<void>;
  /** Bumps whenever a turn completes; wire to AuditDrawer's refreshKey. */
  auditRefreshKey: number;
  /** Call when a text turn completes so the audit drawer refreshes too. */
  bumpAuditRefresh: () => void;
}

export function useVoiceChatIntegration(
  opts: UseVoiceChatIntegrationOptions,
): VoiceChatIntegration {
  const [voiceModalOpen, setVoiceModalOpen] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [auditRefreshKey, setAuditRefreshKey] = useState(0);
  const greetedStepRef = useRef<string | null>(null);

  const optsRef = useRef(opts);
  optsRef.current = opts;

  const bumpAuditRefresh = useCallback(() => setAuditRefreshKey((k) => k + 1), []);

  const handleVoiceTurn = useCallback((summary: VoiceTurnSummary) => {
    setAuditRefreshKey((k) => k + 1);
    optsRef.current.onVoiceTurn(summary);
  }, []);

  const voiceSession = useVoiceSession({
    voiceId: opts.voiceId,
    chatSessionId: opts.sessionId,
    moduleContext: opts.moduleContext,
    history: opts.history,
    onTurnComplete: handleVoiceTurn,
    onError: (message) => setVoiceError(message),
  });

  const voiceActive = voiceSession.state !== "idle" && voiceSession.state !== "error";

  const handleVoiceToggle = useCallback(() => {
    if (voiceSession.state !== "idle" && voiceSession.state !== "error") {
      void voiceSession.stop();
      return;
    }
    setVoiceError(null);
    setVoiceModalOpen(true);
  }, [voiceSession]);

  const handleVoiceConfirm = useCallback(async () => {
    setVoiceModalOpen(false);
    setVoiceError(null);
    await voiceSession.start();
  }, [voiceSession]);

  const closeVoiceModal = useCallback(() => setVoiceModalOpen(false), []);

  // A hidden surface must never keep the microphone open.
  useEffect(() => {
    if (!opts.surfaceOpen && voiceActive) {
      void voiceSession.stop();
    }
  }, [opts.surfaceOpen, voiceActive, voiceSession]);

  // Proactive page-aware greeting: when the surface opens on a module page
  // with a non-empty chat_workflow.current_step and an empty conversation,
  // fetch the templated greeting once per step value.
  useEffect(() => {
    if (!opts.surfaceOpen || !opts.conversationLoaded || opts.hasMessages) return;
    const moduleContext = opts.moduleContext;
    if (!moduleContext || typeof moduleContext !== "object") return;
    const workflow = (moduleContext as { chat_workflow?: { current_step?: string } }).chat_workflow;
    const currentStep = workflow?.current_step;
    if (!currentStep) return;
    if (greetedStepRef.current === currentStep) return;
    greetedStepRef.current = currentStep;

    let cancelled = false;
    fetchPresenceGreeting({
      module_context: moduleContext as Record<string, unknown>,
      session_id: opts.sessionId,
    })
      .then((greeting) => {
        if (cancelled || !greeting) return;
        optsRef.current.onGreeting(greeting.text);
      })
      .catch(() => {
        // The greeting is a nice-to-have; failures stay silent.
      });
    return () => {
      cancelled = true;
    };
  }, [
    opts.surfaceOpen,
    opts.conversationLoaded,
    opts.hasMessages,
    opts.moduleContext,
    opts.sessionId,
  ]);

  return {
    voiceSession,
    voiceActive,
    voiceError,
    voiceModalOpen,
    closeVoiceModal,
    handleVoiceToggle,
    handleVoiceConfirm,
    auditRefreshKey,
    bumpAuditRefresh,
  };
}
