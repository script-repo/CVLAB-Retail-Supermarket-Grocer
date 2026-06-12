# LLM Strategy: Showcasing Nutanix Enterprise AI in the CV Lab

**Audience:** SEs, field teams, and anyone demoing this app to company staff or customers.
**Goal:** make the LLM/NAI portion of the demo as impactful and as easy to explain as the
computer-vision portion already is — and make every LLM moment map to a clear Nutanix
platform message.

---

## 1. Where we are today

The app already has a real LLM integration, and it is technically solid:

| What exists | Where | State |
|---|---|---|
| Async OpenAI-compatible client (works with NAI, vLLM, Ollama) | `cv-lab/backend/app/core/llm.py` | Solid: retries, timeouts, non-blocking |
| Event-driven agent with a 5-tool function-calling loop | `cv-lab/backend/app/core/agent.py` | Working end to end |
| Shift report, 12-hour ops summary, free-form ops chat | `core/agent.py` + `api/agent.py` | Implemented, with deterministic fallbacks |
| K8s secret wiring for NAI credentials | `cv-lab/deploy/k8s/nai-secret.example.yaml` | Ready |
| E2E test of the full detect → agent → work-order chain | `cv-lab/e2e_agent_test.py` | Ready |

**So why does the LLM showcase feel weak?** Not because the integration is missing —
because it is *invisible*. Three specific problems:

1. **The fallback is too good.** If NAI is unreachable, deterministic rules open and
   resolve the same work orders. Great for demo resilience, terrible for storytelling:
   an audience cannot tell what the LLM contributed, so the honest answer to "what is
   the AI doing here?" is "you could do most of this with if-statements."
2. **The LLM does back-office work.** Tool-calling and work-order creation are the
   *least legible* LLM capabilities — they look like workflow automation. The most
   legible capabilities (talking to your data in plain English, narrating what a camera
   sees, writing a report in front of you) are either buried (`/api/agent/chat` has no
   prominent UI) or absent (no vision-language model use at all).
3. **No NAI branding or telemetry on screen.** Nothing on the dashboard says which
   model answered, from which endpoint, or how fast. The GPU badge proves the CV story;
   nothing equivalent proves the LLM story.

**Strategy in one sentence:** stop hiding the LLM inside the agent loop, and put three
audience-facing LLM moments on the main screen — chat, a streaming report, and
vision-language incident narration — each visibly badged as "served by Nutanix
Enterprise AI."

---

## 2. Principles for choosing what to build

1. **Showcase what only an LLM can do.** Anything a rule could do (threshold → ticket)
   is not an LLM demo. Natural-language Q&A, narrative summarization, cross-event
   reasoning, and image understanding are.
2. **Make the inference visible.** Model name, endpoint, time-to-first-token, and
   streaming output should be on screen. Watching tokens arrive *is* the demo.
3. **Turn the fallback into a feature.** A visible "Rules mode vs. NAI mode" toggle
   converts our biggest storytelling weakness into the clearest value contrast in the app.
4. **Stay in character.** This is a self-contained lab: no new services, no frameworks,
   no build step. Every proposal below fits the existing plugin/single-container design.

---

## 3. Recommended showcases, ranked by impact ÷ effort

### Tier 1 — do these first (days, not weeks)

#### 1.1 "Ask the Store" copilot panel ⭐ flagship
The backend already answers free-form questions over live CV context
(`POST /api/agent/chat`, grounded in recent events, work orders, live metrics, and the
staff roster) — but there is no visible UI for it. Add a prominent chat panel to the
agentic-ops section of `index.html`.

- **Demo moment:** type *"What happened in dairy in the last hour, and who's handling
  it?"* and get a grounded, bulleted answer naming the empty-shelf event, the work
  order, and the assignee.
- **Why it wins:** "talk to your cameras in plain English" is the single easiest LLM
  value proposition to explain to a non-technical audience, and it cannot be faked
  with rules.
- **Effort:** small — frontend only (`frontend/assets/agent.js`, `index.html`); the
  endpoint exists. Add 3–4 suggested-question chips so presenters never face a blank box.

#### 1.2 Vision-language incident narration ⭐ best NAI differentiator
Every event already stores a JPEG snapshot (`GET /api/events/{id}/snapshot`). NAI
serves multimodal models (e.g. Llama 3.2 Vision, Qwen2.5-VL). Send the snapshot plus
the event headline to a VLM and display a one-paragraph plain-English description on
the event card: *"A customer is standing at an empty bread shelf; two facings remain
on the top row."*

- **Why it wins:** it is the only proposal that showcases NAI serving **multiple model
  types on one platform** (a text model for the agent, a vision model for narration),
  and "the AI describes what the camera sees" lands instantly with any audience.
- **Effort:** moderate — extend `core/llm.py` to send `image_url` content parts
  (base64 data URLs work with the standard chat-completions contract), add
  `NAI_VISION_MODEL` to `config.py`, render the caption on the event card. Keep it
  on-demand (a "Describe" button per event) so it never blocks the event loop.

#### 1.3 Streaming shift report with visible NAI telemetry
The shift report exists but returns as one blob after up to 30 seconds — dead air in a
demo. Stream it token-by-token into a modal, with a header showing **model, endpoint
host, and time-to-first-token**.

- **Why it wins:** the audience watches the model write the manager briefing live.
  Streaming turns the report's weakness (latency on a shared endpoint) into theater,
  and the telemetry header is the proof point that this is *your* NAI endpoint, not a
  cloud API.
- **Effort:** moderate — add SSE streaming to `core/llm.py` (`stream: true`) and a
  streaming variant of `/api/agent/report`.

#### 1.4 "Rules vs. NAI" mode toggle + NAI status badge
Add a visible toggle (or at minimum a status badge mirroring the GPU badge) that shows
whether agent runs are LLM-driven or fallback-driven, and lets the presenter switch
live. Responses already carry an `nai: true/false` flag — surface it on every card.

- **Demo moment:** run the same empty-shelf scenario in both modes. Rules mode: a
  terse templated work order. NAI mode: a reasoned trace, a context-aware priority, a
  human-readable instruction to the assignee. The delta *is* the pitch.
- **Effort:** small — config flag + frontend badge; the dual code paths already exist.

### Tier 2 — next quarter (each ~1–2 weeks)

#### 2.1 Ground the agent in store context
Today the agent sees only the event, live metrics, and a mock roster, so its reasoning
traces look thin. Add a small store-context layer — product catalog, floor plan / zone
map, SLA table — as YAML/JSON shipped in the existing ConfigMap, exposed as 2–3 new
tools (`lookup_product`, `get_zone_info`). Traces then read like *"Aisle 4 is dairy,
high-margin, 15-minute restock SLA → priority HIGH, assign Maria (zone 4)"* — visibly
intelligent, still fully self-contained.

#### 2.2 RAG over store SOPs (the enterprise-AI story)
Ship a handful of markdown SOPs ("Spill response", "Cold-chain breach", "Age
verification policy") and have the agent cite them when acting: *"Per SOP-07, a spill
requires a wet-floor sign within 2 minutes."* With ~10 short documents, simple keyword
retrieval (or NAI's embeddings endpoint if you want to demo it) is enough — no vector
database needed. **Why it matters:** "the LLM is grounded in *your* company's
documents, and those documents never leave your datacenter" is the core enterprise-AI
message, demonstrated in 30 seconds.

#### 2.3 Cross-event correlation in the ops summary
Extend the ops summary to reason across simultaneous use cases: *"The queue spike at
14:02 coincided with the self-checkout fraud alerts — both trace to one open lane."*
Multi-signal narrative reasoning is another thing rules visibly cannot do; it mostly
needs richer prompt context, not new infrastructure.

### Tier 3 — strategic (when the audience is infrastructure-focused)

- **In-cluster NAI on the same NKP cluster.** Deploy NAI beside the CV lab and point
  `NAI_BASE_URL` at the in-cluster service. The pitch becomes: *one NKP cluster runs
  YOLO on GPUs, serves Llama via NAI, and hosts the app — one platform, one GPU pool,
  zero data egress.* This is a deployment-docs and runbook effort
  (extend `DEPLOYMENT.md`), not an app change.
- **Real-system integrations** (ticketing, LDAP roster) — only if the demo is evolving
  into a PoC; mock systems are fine for showcase purposes.

### Explicitly not recommended

- **Fine-tuning a retail model** — high effort, invisible on stage, and undermines the
  "works with any open model, day one" message.
- **A heavyweight agent framework (LangChain etc.)** — the hand-rolled tool loop is a
  *selling point*: ~200 readable lines of Python against a standard OpenAI-compatible
  API is the "no lock-in" story made concrete.
- **Auto-narrating every frame with the VLM** — cost/latency with no added demo value;
  keep narration per-event and on-demand.

---

## 4. The 5-minute demo talk track (after Tier 1 ships)

| Step | What you do | What you say (the Nutanix message) |
|---|---|---|
| 1 | Run UC-2 (out-of-stock); shelf empties; event fires | "YOLO runs on GPUs in this NKP cluster — note the GPU badge." |
| 2 | Agent trace appears; work order opens; **NAI badge** lit | "Detections become operations. The reasoning here is a Llama model served by **Nutanix Enterprise AI** — same cluster, OpenAI-compatible API, no public cloud." |
| 3 | Click **Describe** on the event snapshot | "And NAI isn't one model — a vision-language model just looked at the camera frame and explained it in plain English." |
| 4 | Type into **Ask the Store**: "What's open right now and who owns it?" | "Plain-English questions over live store data. The footage, the events, and the model all stay on-prem." |
| 5 | Generate the **shift report**; tokens stream in with model/latency header | "End of shift, the manager's briefing writes itself. That's the endpoint, the model, and the latency — your infrastructure, your data." |
| 6 | (Optional) flip to **Rules mode**, re-run step 2 | "Here's the same pipeline without the LLM — this delta is what NAI adds." |

Every step has a fallback (the deterministic path), so the demo cannot dead-end even
if the shared endpoint is slow — say so out loud; resilience is itself a platform message.

---

## 5. Practical notes

- **Model sizing:** an 8B model (`llama3-1-8b`, the current default) is fine for chat,
  summaries, and narration. For *reliable* multi-step tool calling in the agent loop,
  recommend ≥70B-class or a strong mid-size instruct model on the NAI endpoint —
  document this in `CONFIGURATION.md` so field teams don't demo tool use on a model
  that fumbles function calls.
- **Latency:** shared NAI endpoints vary widely (the code already comments on this).
  Streaming (1.3) is the main mitigation; keep `max_tokens` tight on everything else.
- **New config:** `NAI_VISION_MODEL` (Tier 1.2), `AGENT_MODE=auto|nai|rules` (1.4).
  Both default to today's behavior, so nothing breaks for existing users.
- **Files most affected:** `core/llm.py` (streaming + image parts), `core/agent.py`
  (prompts, narration, mode flag), `api/agent.py` (streaming route),
  `frontend/index.html` + `assets/agent.js` (chat panel, badges, report modal),
  `docs/AGENTIC_OPS.md` and `docs/CONFIGURATION.md` (documentation).

---

## 6. Summary

The plumbing for LLM inferencing is already built and already NAI-compatible; the gap
is presentation, not engineering. Four small Tier-1 changes — a visible copilot chat,
VLM incident narration, a streaming branded shift report, and a rules-vs-NAI toggle —
turn the LLM from invisible back-office glue into three or four unmistakable on-stage
moments, each tied to a one-line Nutanix message: *CV on GPUs and LLMs on NAI, side by
side on one NKP cluster, against open models through a standard API, with your data
never leaving the building.*
