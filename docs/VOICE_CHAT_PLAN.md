# Two-Way Voice for Mira Chat — Implementation Plan

**Branch:** `claude/add-voice-chat-GB0Xm`
**Status:** Plan approved, pre-implementation
**Last updated:** 2026-04-26

> **Two tracks in this doc:**
> - **Demo Mode** (next section) — leaner ~2.5-day build optimized for NASA SR management demo. Build this first.
> - **Production target** (rest of doc) — full hardened design for 10 concurrent users in GovCloud. Build this *after* the demo if it lands.
>
> **Two narratives in the demo, both required:**
> - *Voice* makes leadership pay attention (the "look how cool" moment)
> - *PIV-bound audit trail* makes security / IT leadership pay attention (the "and we can prove it" moment)

---

## Demo Mode (NASA SR Management Presentation)

The first deliverable is a demo-quality build. The production sections below are the eventual target if the demo lands and full rollout is funded.

### What changes from production

| Production plan | Demo build |
|---|---|
| 10 concurrent worker pool | 1-2 sessions, no pool |
| AWS Polly (GovCloud-native) | **ElevenLabs Flash v2.5** — the wow factor matters here |
| Whisper on SageMaker async endpoint | Whisper on a single warm GPU EC2 instance (or Deepgram trial) |
| Auto-disable timers + persistent banner | Skip — demoer controls the mic |
| GovCloud compliance review | Skip if demo environment is approved separately |
| Page-aware greeting on all 5 domain pages | Polish 1-2 pages used in the demo |
| Telemetry, rate limits, cost tracking | Skip |

### What becomes critical

1. **Voice quality and personality.** ElevenLabs >> Polly for this audience. Pick a calm, authoritative "Mira voice" and stick with it.
2. **The proactive page-aware greeting.** This is the hero moment — *"I see you're at step 3 of the H2 compatibility check. Looks like the operating pressure isn't entered yet — want to walk through it?"*
3. **First-word latency under 1.5s.** Sentence-buffered streaming + ElevenLabs Flash + pre-warmed Whisper. Anything over 2.5s feels like a science fair project.
4. **Visual choreography.** Live transcription appearing as user speaks. Waveform pulse. Smooth thinking→speaking transitions. Subtle chime on barge-in. Polish > features.
5. **Failsafe.** Pre-record a perfect run as video backup. Live voice demos fail in conference rooms.

### Demo build sequence (~2.5 days)

| Phase | Task | Effort |
|---|---|---|
| 1 | Backend voice WS — Whisper (warm GPU) + ElevenLabs streaming | 1 day |
| 2 | Frontend voice session — capture, VAD, MediaSource, live transcription overlay | 1 day |
| 3 | Page-aware greeting on 1-2 demo pages, scripted copy | ½ day |
| 4 | Polish — waveform, transitions, voice selection, dry runs | ½ day |

### Demo day recommendations

- **Storyboard three ~30-second moments**, not a full product tour:
  1. Mira greets contextually on a page
  2. Hands-free question → watch it think and answer
  3. Barge-in mid-sentence to show responsiveness
- **Wired headset**, not laptop mic
- **Wired ethernet** if available
- **Pre-warm Whisper** before walking in (first inference is always slow)
- **Record a perfect run** the day before as fallback video

### Implementation status (demo build)

Backend (`mira/voice/`):
- `config.py` — `VoiceConfig` with env-driven provider/feature flags
- `providers/` — `STTProvider` / `TTSProvider` base classes, plus
  - `mock.py` (default; exercises the WS pipeline without keys/GPU)
  - `whisper_sagemaker.py` (SageMaker async endpoint client)
  - `elevenlabs_tts.py` (streaming via `httpx`)
  - `polly_tts.py` (boto3 `synthesize_speech` with Generative engine)
  - `factory.py` builds providers with graceful mock fallback when keys missing
- `sentence_buffer.py` — clause/sentence flusher (min 40 / max 120 chars)
- `session.py` — per-WS state machine (idle/listening/thinking/speaking)
  with barge-in cancellation and history accumulation
- `chat_bridge.py` — invokes existing `chat_stream` in-process and yields
  parsed SSE event dicts; voice never reimplements multi-turn state
- `presence.py` — templated page-aware greeting from `chat_workflow`
- `ws_endpoint.py` — `/api/chat/voice` WS plus `/api/chat/voice/voices`,
  `/api/chat/voice/status`, `/api/chat/presence` HTTP helpers
- `mira/api/app_factory.py` — voice router registered, `Permissions-Policy`
  changed from `microphone=()` to `microphone=(self)`

Frontend (`frontend/src/lib/voice/`, `frontend/src/components/voice/`):
- `public/voice/pcm-worklet.js` — AudioWorklet downsampler to 16 kHz Int16
- `audioCapture.ts`, `vad.ts`, `audioPlayer.ts`, `voiceClient.ts`,
  `useVoiceSession.ts`, `voiceApi.ts`
- `VoiceControl`, `VoiceActiveBanner`, `VoiceEnableModal`, `VoiceSettings`
- Integrated into `pages/MiraChat.tsx` (full-page chat) and
  `components/mira/MiraChatDock.tsx` (per-page floating dock) — voice
  applies to both the main chat surface and every page-wise chat

### Demo-mode env vars

```
# Provider selection
MIRA_VOICE_ENABLED=true
MIRA_VOICE_DEMO_MODE=true              # disables some safeguards
MIRA_VOICE_STT_PROVIDER=whisper        # or "mock"
MIRA_VOICE_TTS_PROVIDER=elevenlabs     # or "polly" | "mock"

# Whisper / SageMaker
MIRA_VOICE_WHISPER_ENDPOINT=<sagemaker endpoint name>
AWS_REGION=us-gov-west-1

# ElevenLabs (demo TTS)
MIRA_VOICE_ELEVENLABS_API_KEY=<key>
MIRA_VOICE_ELEVENLABS_VOICE_ID=<chosen voice id>
MIRA_VOICE_ELEVENLABS_MODEL=eleven_flash_v2_5

# Polly (production TTS fallback / GovCloud-native)
MIRA_VOICE_POLLY_VOICE_ID=Ruth
MIRA_VOICE_POLLY_ENGINE=generative

# Concurrency + sentence buffer tuning
MIRA_VOICE_MAX_CONCURRENT=10
MIRA_VOICE_FLUSH_MIN_CHARS=40
MIRA_VOICE_FLUSH_MAX_CHARS=120
```

With no env vars set, the system falls back to mock STT/TTS so the
WebSocket pipeline + UI choreography can be exercised end-to-end without
credentials or GPU.

### PIV identity + audit trail (the Seemann / Tawnya beat)

Voice is the headline; the audit story is the part that gets the program
funded. Both ship in the same demo build.

**What's built on this branch:**

Backend:
- `mira/chat/models.py` — `UserIdentity` model (sub, username, email,
  EDIPI, PIV subject, agency, role, groups, ITAR, US-person, auth_method)
  attached to every `AuditRecord`, plus a `turn_modality: "text" | "voice"`
  field so the record distinguishes how the question was asked
- `mira/chat/audit_identity.py` — converts Cognito claims (or a `MIRAUser`)
  into a `UserIdentity`. When `custom:edipi` / `custom:piv_subject` are
  present (Cognito federated with NASA Launchpad → SAML), `auth_method`
  auto-flips to `cognito+piv`
- `mira/chat/router.py` — both `/api/chat` and `/api/chat/stream` now read
  `request.state.user` (set by the existing Cognito middleware) and write
  the identity into the audit record. Voice turns are stamped
  `turn_modality="voice"` via a synthetic Request scope the WS bridge
  carries
- `mira/voice/ws_endpoint.py` — WebSocket extracts the Cognito claims at
  accept time and attaches the resulting `UserIdentity` to the
  `VoiceSession`, which the chat bridge then carries into the audit write
- New endpoints:
  - `GET /api/chat/whoami` — current caller identity for the PIV chip
  - `GET /api/chat/audit/recent?limit=&session_id=` — recent audit records
    filtered to `user_identity.sub == caller.sub` (callers only see their
    own history; records without identity are excluded so anonymous turns
    never leak)

Frontend:
- `components/audit/PivIdentityChip.tsx` — emerald `ShieldCheck` chip with
  EDIPI + agency when PIV-federated; tooltip exposes full PIV subject DN
- `components/audit/AuditDrawer.tsx` — side sheet of recent turns, each
  showing: audit ID, modality badge (text/voice), verdict, engine, the
  question, citations, authority basis, truncated response hash, model,
  session ID. Identity card at the top.
- Wired into both `MiraChat` (page) and `MiraChatDock` (per-page floating).
  Drawer auto-refreshes whenever a turn completes — text or voice.

### The demo beat

1. **Open a domain page.** Top of the dock shows the PIV chip:
   *"J.Engineer · EDIPI 1234567890 · NASA-MAF"* with ShieldCheck.
2. **Click voice on.** Ask: *"Is 316L compatible with GOX at 3000 psi?"*
3. **Mira speaks the answer.** Citations stream in.
4. **Click the audit-trail icon (📋).** Drawer slides in:
   - Identity card: emerald, PIV subject DN visible
   - Top record: `CHAT-2026-0511-042` · `voice` badge · `CONDITIONAL_PASS`
     · `oca` · just now
   - Question: "Is 316L compatible with GOX at 3000 psi?"
   - Citations: NASA-STD-6001B §4.3.2, ASTM G88-13
   - Authority basis: NASA-STD-6001B
   - Hash: `sha256:8a4f…b2c1` · model: `claude-sonnet-4-5`
5. **Compare with a keyboard turn.** Type the same question. New record
   appears, identical shape, modality badge reads `text`.

Message to the room: *same identity-bound, citation-grounded,
content-hashed audit record regardless of input modality.*

### PIV federation modes for the demo

- **(a) Real PIV federation** — Cognito user pool federated with NASA
  Launchpad (or equivalent PIV IdP). `custom:edipi`, `custom:piv_subject`,
  `custom:agency` flow through SAML attribute mapping. Highest fidelity;
  requires IT cooperation to set up.
- **(b) Cognito custom attributes mimicking PIV** — set `custom:edipi`,
  `custom:piv_subject`, `custom:agency` on the demo user records via the
  Cognito admin API. Same code path on the read side; `auth_method`
  auto-flips to `cognito+piv` so the chip still shows the emerald shield.

For the demo, **(b) is sufficient and ships today.** Promote to (a) when
the real PIV federation is wired.

### Demo day dry-run checklist

The night before:
- [ ] Confirm SageMaker endpoint is warm and responsive (`aws sagemaker-runtime invoke-endpoint`)
- [ ] Confirm ElevenLabs API key works (`curl -H "xi-api-key: $KEY" https://api.elevenlabs.io/v1/voices`)
- [ ] Confirm demo user has PIV-shaped Cognito attributes (`custom:edipi`,
      `custom:piv_subject`, `custom:agency`) — chip should be emerald
- [ ] Confirm a fresh audit log exists; do one warm-up turn so the drawer
      doesn't open empty
- [ ] Run a full storyboard pass: page-aware greeting → hands-free Q →
      barge-in → audit drawer reveal
- [ ] Record a perfect run as MP4 backup
- [ ] Test the wired headset on the actual demo laptop
- [ ] Test from the actual demo network if possible

Demo day, T-30:
- [ ] Open the demo page; click voice on; speak one sentence to warm Whisper
- [ ] Click audit-trail icon; verify identity card renders emerald with EDIPI
- [ ] Verify the persistent voice banner is visible
- [ ] Verify barge-in latency is acceptable
- [ ] Have the backup video queued up in a second tab

If voice fails live:
- Calmly switch tabs to the backup video
- Continue narration over the video
- **The audit story still works on a text turn** — fallback message: "Let
  me type that one. Watch the audit record — same identity, same
  citations, same hash, modality just changed to text." That's still the
  Seemann/Tawnya beat.

### Promotion to production

When demo→production happens, the changes are mechanical:
1. Swap `MIRA_VOICE_TTS_PROVIDER` from `elevenlabs` to `polly`
2. Confirm SageMaker is running with provisioned concurrency + autoscaling
3. Flip `MIRA_VOICE_DEMO_MODE=false`; enables rate limits, auto-disable
   timers, persistent banner (already coded — gated by flag)
4. Extend page-aware greeting copy to all 5 domain pages
5. Run GovCloud compliance review (Polly is native; if keeping ElevenLabs,
   that's the long pole)
6. (Optional) Swap energy VAD for `@ricky0123/vad-web` Silero in the
   frontend if accuracy is a problem in the field

The provider abstraction in `mira/voice/providers/` already supports both
TTS backends; the swap is a single env var.

---

## Goals

1. Two-way voice on Mira chat (main chat + page-wise chats) across all major browsers
2. Continuous listening with barge-in support
3. Highest-quality voice within GovCloud constraints
4. Page-aware proactive greeting leveraging existing `chat_workflow` context (e.g., "I see you're at step 3...")
5. Initial scale: 10 concurrent voice users

## Stack

| Concern | Choice | Notes |
|---|---|---|
| **STT** | faster-whisper large-v3 on **SageMaker async endpoint** | GovCloud us-gov-west-1 |
| **TTS** | **AWS Polly Generative engine**, streaming | Native to GovCloud, no third-party compliance review |
| **VAD (client)** | Silero VAD via `@ricky0123/vad-web` | ONNX in browser, no server roundtrip for silence |
| **Transport** | WebSocket `/api/chat/voice` | Bidirectional, single connection per session |
| **Audio in** | `getUserMedia` + AudioWorklet → 16kHz Int16 PCM | Cross-browser, low-latency |
| **Audio out** | MediaSource + SourceBuffer streaming MP3/Opus from Polly | Streaming playback, supports barge-in |

### Why Polly over ElevenLabs

ElevenLabs would require GovCloud compliance review and adds a third-party SaaS dependency. AWS Polly Generative (released 2024) is now in the same neighborhood for assistant use cases — slightly less expressive but very natural, native to GovCloud us-gov-west-1, ~3x cheaper, and zero vendor add. The expressiveness gap is tolerable for a technical assistant chatbot. Latency is the only real loss (~300-500ms TTFB vs ~75ms), masked by sentence-level streaming.

## Architecture

```
[Mic] → AudioWorklet (16kHz PCM) → Silero VAD (browser, gated during TTS playback)
            │ (only on detected speech)
            ▼
    WebSocket /api/chat/voice
            │
            ▼
    Worker pool router (max 10 concurrent, backpressure beyond)
            │
            ▼
    SageMaker async endpoint (faster-whisper) → text
            │
            ▼
    Existing /api/chat/stream pipeline → SSE text deltas
            │
            ▼
    Sentence buffer → AWS Polly synthesize_speech (streaming) → audio chunks
            │
            ▼
    WebSocket → MediaSource → [Speakers]
```

## Worker Pool (10 concurrent users)

- **SageMaker endpoint:** 1× `ml.g5.xlarge` (24GB GPU). Capacity ~10 concurrent whisper sessions. Auto-scaling: target 70% utilization, scale-out to 2 instances at 8 concurrent.
- **Connection cap:** backend WS handler refuses new sessions past N=10, returns queued state. Configurable via `VOICE_MAX_CONCURRENT`.
- **TTS:** Polly is per-request, no pool. Backend rate-limits at 30 req/sec aggregate.
- **Per-session pinning:** each WebSocket session uses a SageMaker invocation slot for utterance duration only (released between turns).

## Echo Cancellation

Belt-and-suspenders since users may use external speakers:

1. `getUserMedia({ echoCancellation: true, noiseSuppression: true, autoGainControl: true })`
2. **Gate VAD while TTS is playing** — suppress speech detection until output buffer drops + 200ms tail
3. **Barge-in override** — if input energy is well above masked TTS energy, allow interrupt → cancel TTS stream → cancel in-flight LLM stream → start new turn

## Continuous Listening UX

- Mic **off by default**
- Toggle: "Voice mode: Off / On" in chat header
- On enable: modal — *"Voice mode is on. Mira is always listening on this page. Click the mic icon to turn it off when you're done."*
- **Persistent banner** at top of viewport while active (more visible than a header dot)
- Pulsing dot + "Listening" text in chat header
- **Auto-disable triggers:**
  - Tab inactive for 5 min (safety net)
  - Idle-while-focused: no detected speech for 10 min
  - Toast on return / on auto-disable: "Voice mode turned off automatically"

## Voice Settings UI

New panel (gear icon in chat header):

- **Voice dropdown** — populated from Polly `describe_voices` filtered to `Engine=generative`, cached server-side
- Stability/expressiveness sliders (Polly: SSML prosody controls)
- Mic input device picker
- Speaker output device picker
- "Test mic" / "Test voice" buttons

## Sentence Buffering (latency mitigation)

To compensate for Polly's higher TTFB:

- Buffer SSE text deltas as they arrive
- Flush to Polly on first **clause boundary** (`,;:` or `.!?`) past 40 chars, OR hard-flush at 120 chars
- Pipeline overlap: while sentence N plays, sentence N+1 synthesizes
- **Target end-to-end first-word-spoken latency:** ~1.5s after user stops talking

## Page-Aware Proactive Greeting

The plumbing already exists. `frontend/src/lib/mira-chat-context.ts:124-149` (`buildWorkflowContext`) sends `current_step`, `active_field`, `field_states`, `blockers`, `next_steps`, etc. to the backend, and `mira/chat/module_context.py:404-419` extracts these into session entities.

What's missing is **proactive surfacing**:

1. **Frontend:** on chat open with voice enabled and non-empty `chat_workflow.current_step`, fire `POST /api/chat/presence`
2. **Backend** (`mira/chat/router.py`): new endpoint returns templated greeting:
   - With blockers: *"I see you're at **{step_label}**. Looks like **{first_blocker}** is missing — want help with that?"*
   - Without blockers: *"I see you're at **{step_label}**. Anything I can help with?"*
3. If voice is enabled, auto-pipe greeting through Polly to speakers
4. **Throttle:** fire once per `(page, current_step)` per session — no repeat on every focus
5. **Active-field instruction:** prepend system prompt with: *"If `chat_workflow.active_field` is set and the user asks a vague question ('this', 'help me'), assume they mean that field unless context says otherwise."*

This part is independently valuable from voice — could ship on its own.

## File Layout

### Backend (Python)

```
mira/voice/
├── __init__.py
├── stt_client.py        # SageMaker invoke, streaming partial+final
├── tts_client.py        # Polly streaming wrapper
├── vad_server.py        # webrtcvad silence trim (defense-in-depth)
├── session.py           # per-WS state machine (idle/listening/thinking/speaking)
├── worker_pool.py       # SageMaker invocation routing + backpressure
└── sentence_buffer.py   # SSE → sentence flush logic

mira/api/
├── voice_ws.py          # WebSocket handler /api/chat/voice
└── voice_routes.py      # GET /api/voice/voices, presence endpoint

mira/chat/router.py      # add POST /api/chat/presence
mira/chat/module_context.py  # active-field prompt instruction
```

**`pyproject.toml` deps to add:** `faster-whisper`, `boto3` (likely already present), `websockets`, `webrtcvad`, `numpy`

### Frontend (TypeScript)

```
frontend/src/lib/voice/
├── audioCapture.ts      # AudioWorklet capture wrapper
├── audioWorklet.ts      # 16kHz PCM downsampler
├── vad.ts               # Silero VAD wrapper
├── audioPlayer.ts       # MediaSource streaming player + barge-in stop
└── voiceSession.ts      # WS client + state machine

frontend/src/components/voice/
├── VoiceControl.tsx     # mic toggle + listening indicator
├── VoiceSettings.tsx    # voice/device dropdowns
├── VoiceWaveform.tsx    # visualizer
└── VoiceActiveBanner.tsx # persistent top-of-viewport banner

frontend/src/pages/MiraChat.tsx   # embed VoiceControl + settings
```

**`package.json` deps to add:** `@ricky0123/vad-web`, `onnxruntime-web`

## Infrastructure

- **SageMaker endpoint:** 1× `ml.g5.xlarge` initial, auto-scale 1-2 instances, provisioned concurrency 1 (no cold start)
- **Polly:** native, no infra setup
- **IAM:** backend role needs `sagemaker:InvokeEndpoint`, `polly:SynthesizeSpeech`, `polly:DescribeVoices`
- **Env vars:**
  - `SAGEMAKER_WHISPER_ENDPOINT`
  - `AWS_REGION=us-gov-west-1`
  - `POLLY_DEFAULT_VOICE_ID`
  - `VOICE_MAX_CONCURRENT=10`

## Build Sequence

| Phase | Task | Effort |
|---|---|---|
| 1 | SageMaker Whisper endpoint provisioned + smoke-tested | ½ day (mostly waiting for endpoint) |
| 2 | Backend voice WS, STT/TTS clients, worker pool | 1.5 days |
| 3 | Frontend voice session: capture, VAD, MediaSource player | 1 day |
| 4 | MiraChat integration: VoiceControl, settings, enable warning, persistent banner | ½ day |
| 5 | Barge-in + echo gating state machine | ½ day |
| 6 | Page-aware greeting + auto-speak + active-field prompt | ½ day |
| 7 | Sentence buffer tuning + load test 10 concurrent | ½ day |
| **Total** | | **~5 days** |

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| SageMaker cold start adds seconds on first call | Provisioned concurrency 1, keep warm |
| Whisper hallucinates on silence | Server-side VAD trim before invoke |
| Polly latency feels sluggish | Sentence-level streaming + early clause flush |
| Whisper accuracy on technical/material jargon ("4140 steel", "5000 psi", "H2 embrittlement") | Evaluate on domain audio; fall back to fine-tune or custom vocabulary biasing if needed |
| Browser audio capture inconsistencies (especially Safari) | AudioWorklet fallback to ScriptProcessor on older Safari |
| User forgets mic is on | 5-min tab-inactive auto-disable + 10-min idle-while-focused auto-disable + persistent banner + enable-time reminder |
| Cost surprise | Backend rate-limit Polly to 30 req/sec, log per-session char/audio totals |

## Success Criteria

- [ ] 10 simultaneous voice sessions sustained for 5 minutes without degradation
- [ ] First-word-spoken latency ≤ 2s p50, ≤ 3s p95 after user stops talking
- [ ] Barge-in cancels TTS within 200ms of detected speech
- [ ] Works on Chrome, Edge, Firefox, Safari (latest 2 versions)
- [ ] Page-aware greeting triggers correctly on all 5 domain pages (OCA, H2, Galvanic, Fracture, MP Plan)
- [ ] No audio data sent outside GovCloud region
- [ ] Whisper transcription accuracy ≥ 95% on domain test set (materials, units, identifiers)

## Open Items / Followups

- Validate Whisper accuracy on a representative sample of engineer voice queries before full rollout
- Consider whether the page-aware greeting should ship independently (text-only) ahead of voice, since plumbing already exists
- Decide on telemetry: per-session metrics (turn count, transcription failures, barge-in count) for tuning
