"""Agentic incident response on top of CV events.

When a ``detected`` event fires, an agent run starts against the NAI endpoint:
the model reasons over the event, checks live metrics and the staff roster via
tools, opens a work order, and drafts a notification. When the matching
``cleared`` event arrives, a second run verifies via live metrics and resolves
the work order. Every step (tool call, tool result, final summary) is broadcast
over the event bus so the UI shows the agent thinking in real time.

If NAI is unreachable mid-demo, a deterministic fallback still creates/resolves
the work order so the demo never stalls.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.core import persist
from app.core.events import LIVE_METRICS, Event, get_event_bus, _now_iso
from app.core.llm import NaiError, get_nai_client

logger = logging.getLogger(__name__)

_wo_ids = itertools.count(1)
_run_ids = itertools.count(1)

# --- Mock store data (clearly labeled simulation in the UI) -----------------

STAFF_ROSTER = [
    {"name": "Maria Santos", "role": "floor lead", "zone": "front of store", "on_shift": True},
    {"name": "Devon Clarke", "role": "maintenance", "zone": "all areas", "on_shift": True},
    {"name": "Priya Patel", "role": "stock clerk", "zone": "grocery aisles 1-8", "on_shift": True},
    {"name": "James Liu", "role": "stock clerk", "zone": "dairy & frozen", "on_shift": False},
    {"name": "Aisha Mohammed", "role": "cashier", "zone": "checkout lanes", "on_shift": True},
]

# --- Tool schemas (OpenAI function-calling format) ---------------------------

TOOLS = [
    {"type": "function", "function": {
        "name": "get_live_metrics",
        "description": "Get the current live metrics from the in-store computer vision system. Use this to verify whether a detected condition is still present right now.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "check_staff_roster",
        "description": "List store staff currently on shift, with role and assigned zone. Use this to pick the right assignee for a task.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "create_work_order",
        "description": "Create a work order for store staff. Returns the work order id.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "Short task title"},
            "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            "assignee": {"type": "string", "description": "Staff member name from the roster"},
            "area": {"type": "string", "description": "Store area, e.g. 'Aisle 4'"},
            "instructions": {"type": "string", "description": "1-2 sentence instructions"},
        }, "required": ["title", "priority", "assignee", "instructions"]},
    }},
    {"type": "function", "function": {
        "name": "notify_staff",
        "description": "Send a short notification message to a staff member or team channel.",
        "parameters": {"type": "object", "properties": {
            "recipient": {"type": "string"},
            "message": {"type": "string"},
        }, "required": ["recipient", "message"]},
    }},
    {"type": "function", "function": {
        "name": "resolve_work_order",
        "description": "Mark a work order as resolved once the condition is verified clear.",
        "parameters": {"type": "object", "properties": {
            "work_order_id": {"type": "string"},
            "resolution_note": {"type": "string"},
        }, "required": ["work_order_id", "resolution_note"]},
    }},
]


class AgentRuntime:
    """Owns work orders, notifications, and the per-event agent runs."""

    def __init__(self) -> None:
        global _wo_ids
        self.settings = get_settings()
        self.work_orders: dict[str, dict[str, Any]] = {}
        self.notifications: deque[dict[str, Any]] = deque(maxlen=100)
        self.steps: deque[dict[str, Any]] = deque(maxlen=300)   # replay buffer for late joiners
        self._lock = asyncio.Lock()                              # one run at a time → readable UI
        try:
            saved = persist.load_state()
            self.work_orders.update(saved["work_orders"])
            self.notifications.extend(saved["notifications"])
            _wo_ids = itertools.count(persist.max_numeric_id("work_orders") + 1)
            if self.work_orders:
                logger.info("rehydrated %d work orders from disk", len(self.work_orders))
        except Exception:  # noqa: BLE001
            logger.exception("could not rehydrate agent state; starting empty")

    # --- event-bus entrypoint ---
    async def on_event(self, event: Event) -> None:
        async with self._lock:
            if event.kind == "detected":
                await self._run(event, mode="incident")
            elif event.kind == "cleared":
                if self._open_wo_for(event.usecase):
                    await self._run(event, mode="clearance")

    def _open_wo_for(self, usecase: str) -> dict[str, Any] | None:
        return next((w for w in self.work_orders.values()
                     if w["usecase"] == usecase and w["status"] == "open"), None)

    # --- broadcast helpers ---
    def _emit(self, msg: dict[str, Any]) -> None:
        self.steps.append(msg)
        get_event_bus().broadcast(msg)

    def _step(self, run_id: str, kind: str, label: str, detail: str = "") -> None:
        self._emit({"type": "agent_step", "run_id": run_id, "kind": kind,
                    "label": label, "detail": detail})

    # --- the agent loop ---
    async def _run(self, event: Event, mode: str) -> None:
        run_id = f"run-{next(_run_ids):03d}"
        self._emit({"type": "agent_run", "run_id": run_id, "mode": mode,
                    "event": event.to_dict()})
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._task_prompt(event, mode)},
        ]
        client = get_nai_client()
        # Restrict the toolset per mode — small models wander otherwise (e.g.
        # opening a fresh work order during a clearance instead of resolving).
        if mode == "incident":
            allowed = {"get_live_metrics", "check_staff_roster", "create_work_order", "notify_staff"}
        else:
            allowed = {"get_live_metrics", "resolve_work_order", "notify_staff"}
        tools = [t for t in TOOLS if t["function"]["name"] in allowed]
        try:
            for _ in range(self.settings.agent_max_steps):
                # Small budget: tool calls are ~40-80 tokens and the shared NAI
                # endpoint decodes slowly, so brevity keeps runs demo-speed.
                msg = await client.chat(messages, tools=tools, max_tokens=220)
                tool_calls = msg.get("tool_calls") or []
                if not tool_calls:
                    final = (msg.get("content") or "").strip()
                    self._step(run_id, "final", "Agent summary", final or "Done.")
                    break
                messages.append({"role": "assistant", "content": msg.get("content"),
                                 "tool_calls": tool_calls})
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    self._step(run_id, "tool_call", name, json.dumps(args))
                    result = self._exec_tool(name, args, event)
                    self._step(run_id, "tool_result", name, json.dumps(result)[:500])
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": json.dumps(result)})
            else:
                self._step(run_id, "final", "Agent summary",
                           "Step limit reached; actions above were applied.")
        except NaiError as exc:
            logger.warning("agent run %s falling back: %s", run_id, exc)
            self._step(run_id, "error", "NAI unavailable — deterministic fallback", str(exc))
            self._fallback(run_id, event, mode)
        self._emit({"type": "agent_done", "run_id": run_id})

    def _system_prompt(self) -> str:
        return (
            f"You are the autonomous store-operations agent for {self.settings.store_name}. "
            "A computer-vision system monitors the store and raises incidents. You respond by "
            "using the provided tools. Be decisive and brief. Rules: (1) verify the condition "
            "with get_live_metrics first; (2) pick an appropriate on-shift assignee via "
            "check_staff_roster; (3) for incidents create exactly one work order and notify the "
            "assignee; (4) for clearances verify metrics, resolve the work order, and notify the "
            "floor lead; (5) safety hazards (spills, blocked exits) are 'urgent'; stock issues "
            "are 'medium'; queue issues are 'high'. Finish with a one-sentence summary. "
            "Keep every response under 60 words; never write prose alongside a tool call."
        )

    def _task_prompt(self, event: Event, mode: str) -> str:
        ctx = json.dumps({"headline": event.headline, "metrics": event.values,
                          "use_case": event.usecase_title, "time": event.timestamp})
        if mode == "incident":
            return (
                f"NEW INCIDENT detected by camera analytics: {ctx}. Handle it: verify with "
                "get_live_metrics, pick an assignee from check_staff_roster (use their exact "
                "name), create one work order, notify that assignee."
            )
        wo = self._open_wo_for(event.usecase)
        wo_ref = f" The open work order is {wo['id']} ('{wo['title']}', assignee {wo['assignee']})." if wo else ""
        return (
            f"CLEARANCE SIGNAL from camera analytics: {ctx}.{wo_ref} Verify with "
            f"get_live_metrics, then call resolve_work_order with work_order_id='{wo['id'] if wo else ''}' "
            "and notify the floor lead. Do NOT create anything new."
        )

    # --- tools ---
    def _exec_tool(self, name: str, args: dict[str, Any], event: Event) -> dict[str, Any]:
        if name == "get_live_metrics":
            live = LIVE_METRICS.get(event.usecase)
            return live or {"note": "stream ended", "last_event": event.to_dict()}
        if name == "check_staff_roster":
            return {"staff": [s for s in STAFF_ROSTER if s["on_shift"]]}
        if name == "create_work_order":
            return self._create_wo(event, args)
        if name == "notify_staff":
            note = {"type": "notification", "recipient": args.get("recipient", "team"),
                    "message": args.get("message", ""), "timestamp": event.timestamp}
            self.notifications.append(note)
            persist.save_notification(note)
            self._emit(note)
            return {"sent": True}
        if name == "resolve_work_order":
            return self._resolve_wo(args.get("work_order_id", ""),
                                    args.get("resolution_note", ""))
        return {"error": f"unknown tool {name}"}

    def _valid_assignee(self, name: str, priority: str) -> str:
        """Snap a hallucinated assignee to a real on-shift staff member."""
        on_shift = [s for s in STAFF_ROSTER if s["on_shift"]]
        for s in on_shift:
            if s["name"].lower() == str(name).lower().strip():
                return s["name"]
        want_role = "maintenance" if priority == "urgent" else "stock clerk"
        pick = next((s for s in on_shift if s["role"] == want_role), on_shift[0])
        return pick["name"]

    def _create_wo(self, event: Event, args: dict[str, Any]) -> dict[str, Any]:
        priority = args.get("priority", "medium")
        wo = {
            "id": f"WO-{next(_wo_ids):04d}",
            "title": args.get("title", event.headline)[:120],
            "priority": priority,
            "assignee": self._valid_assignee(args.get("assignee", ""), priority),
            "area": args.get("area", ""),
            "instructions": args.get("instructions", ""),
            "status": "open",
            "usecase": event.usecase,
            "event_id": event.id,
            "created_at": event.timestamp,
            "resolved_at": None,
            "resolution_note": None,
        }
        self.work_orders[wo["id"]] = wo
        persist.save_work_order(wo)
        self._emit({"type": "workorder", "workorder": wo})
        return {"work_order_id": wo["id"], "status": "created"}

    def _resolve_wo(self, wo_id: str, note: str) -> dict[str, Any]:
        wo = self.work_orders.get(wo_id)
        if not wo:
            # Model sometimes paraphrases the id; fall back to oldest open WO.
            wo = next((w for w in self.work_orders.values() if w["status"] == "open"), None)
        if not wo:
            return {"error": "no open work order"}
        wo["status"] = "resolved"
        wo["resolved_at"] = _now_iso()
        wo["resolution_note"] = note
        persist.save_work_order(wo)
        self._emit({"type": "workorder", "workorder": wo})
        return {"work_order_id": wo["id"], "status": "resolved"}

    # --- deterministic fallback (demo never stalls) ---
    def _fallback(self, run_id: str, event: Event, mode: str) -> None:
        if mode == "incident":
            urgent = any(k in event.usecase_title.lower() for k in ("spill", "hazard"))
            res = self._create_wo(event, {
                "title": event.headline,
                "priority": "urgent" if urgent else "medium",
                "assignee": "Devon Clarke" if urgent else "Priya Patel",
                "instructions": f"Respond to: {event.headline}. Raised automatically by CV analytics.",
            })
            self._step(run_id, "final", "Agent summary",
                       f"Created {res['work_order_id']} via fallback rules.")
        else:
            wo = self._open_wo_for(event.usecase)
            if wo:
                self._resolve_wo(wo["id"], "Condition verified clear by CV analytics (fallback).")
                self._step(run_id, "final", "Agent summary",
                           f"Resolved {wo['id']} via fallback rules.")

    # --- shift report ---
    async def shift_report(self) -> str:
        bus = get_event_bus()
        payload = {
            "store": self.settings.store_name,
            "events": [e.to_dict() for e in bus.events],
            "work_orders": list(self.work_orders.values()),
            "notifications": list(self.notifications),
        }
        prompt = (
            "Write a concise end-of-shift operations briefing for the store manager based on "
            "this JSON log of computer-vision incidents, agent-created work orders, and "
            "notifications. Use markdown with sections: Summary, Incidents & Response, "
            "Open Items, Recommendations. Mention response handling by the AI agent where "
            "relevant. Recommendations must be store-operations actions only; do not recommend "
            "restoring, enabling, or repairing the NAI inference endpoint. Keep it under 200 "
            "words total. Data:\n" + json.dumps(payload)
        )
        try:
            # Hard wall-clock deadline so a slow/loaded shared NAI endpoint can't
            # hang the report: no retries, and if it overruns we fall back to the
            # instant local briefing. (Decode speed on the shared endpoint varies
            # widely; 400-token reports could otherwise block for minutes.)
            msg = await asyncio.wait_for(
                get_nai_client().chat(
                    [{"role": "system", "content": "You are a retail operations analyst. Output clean markdown only."},
                     {"role": "user", "content": prompt}],
                    max_tokens=320, temperature=0.3, retries=0,
                ),
                timeout=self.settings.report_deadline_s,
            )
            report = (msg.get("content") or "").strip()
            return self._clean_shift_report(report) if report else self._local_report(payload)
        except (NaiError, asyncio.TimeoutError) as exc:
            # NAI down or too slow: never hang the demo — build the briefing
            # locally from the same event/work-order data.
            logger.warning("shift report falling back to local generation: %s", exc)
            return self._local_report(payload, str(exc))

    def _local_report(self, payload: dict[str, Any], nai_error: str = "") -> str:
        """Deterministic, no-LLM shift report from the event log (NAI fallback)."""
        events = payload["events"]
        wos = payload["work_orders"]
        notes = payload["notifications"]
        detected = [e for e in events if e.get("kind") == "detected"]
        cleared = [e for e in events if e.get("kind") == "cleared"]
        open_wos = [w for w in wos if w.get("status") == "open"]
        resolved = [w for w in wos if w.get("status") == "resolved"]

        out: list[str] = [f"# Shift Report — {payload['store']}", ""]
        note = "NAI endpoint unavailable" + (f" ({nai_error})" if nai_error else "")
        out.append(f"> _{note}. This briefing was generated locally from the event log (no LLM)._")
        out += [
            "", "## Summary",
            f"- {len(detected)} incident(s) detected, {len(cleared)} clearance signal(s).",
            f"- {len(wos)} work order(s): {len(open_wos)} open, {len(resolved)} resolved.",
            f"- {len(notes)} staff notification(s) sent.",
        ]

        out += ["", "## Incidents & Response"]
        if wos:
            for w in wos:
                state = "resolved" if w.get("status") == "resolved" else "OPEN"
                out.append(
                    f"- **{w.get('id')}** [{w.get('priority')}/{state}] {w.get('title')} "
                    f"— {w.get('assignee')}"
                    + (f"; {w.get('resolution_note')}" if w.get("resolution_note") else "")
                )
        else:
            out.append("- No incidents required a work order this shift.")

        out += ["", "## Open Items"]
        if open_wos:
            out += [f"- {w.get('id')}: {w.get('title')} ({w.get('assignee')})" for w in open_wos]
        else:
            out.append("- None — all work orders resolved.")

        out += ["", "## Recommendations",
                "- Continue monitoring open work orders and assign associates to any unresolved incidents."
                if nai_error else
                "- Maintain current monitoring coverage; no anomalies outstanding."]
        return "\n".join(out)

    def _clean_shift_report(self, report: str) -> str:
        """Remove infrastructure recovery advice from NAI-authored reports."""
        cleaned: list[str] = []
        for line in report.splitlines():
            if re.search(r"\b(restore|enable|repair|restart)\b.*\bNAI\b.*\b(inference|endpoint)\b", line, re.I):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip() or "## Recommendations\n- Continue monitoring open work orders and unresolved incidents."

    # --- operations dashboard: 12h summary + free-form Q&A -----------------
    def _recent(self, hours: int = 12) -> dict[str, Any]:
        """Event/work-order/notification payload limited to the last N hours."""
        bus = get_event_bus()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        def _keep(ts: Any) -> bool:
            if not ts:
                return True
            try:
                return datetime.fromisoformat(str(ts)) >= cutoff
            except (ValueError, TypeError):
                return True  # unparseable → keep rather than silently drop

        events = [e.to_dict() for e in bus.events if _keep(e.to_dict().get("timestamp"))]
        wos = [w for w in self.work_orders.values() if _keep(w.get("created_at"))]
        notes = [n for n in self.notifications if _keep(n.get("timestamp"))]
        return {
            "store": self.settings.store_name,
            "hours": hours,
            "events": events,
            "work_orders": wos,
            "notifications": notes,
            "live_metrics": dict(LIVE_METRICS),
        }

    @staticmethod
    def _counts(payload: dict[str, Any]) -> dict[str, Any]:
        events = payload["events"]
        detected = [e for e in events if e.get("kind") == "detected"]
        cleared = [e for e in events if e.get("kind") == "cleared"]
        wos = payload["work_orders"]
        types: dict[str, int] = {}
        for e in detected:
            t = e.get("usecase_title") or e.get("usecase") or "incident"
            types[t] = types.get(t, 0) + 1
        top = sorted(types.items(), key=lambda kv: kv[1], reverse=True)
        return {
            "detected": detected,
            "cleared": cleared,
            "wos": wos,
            "open": [w for w in wos if w.get("status") == "open"],
            "resolved": [w for w in wos if w.get("status") == "resolved"],
            "top_types": top,
            "notifications": payload["notifications"],
        }

    @staticmethod
    def _clip_sentences(text: str, n: int) -> str:
        """Keep at most the first ``n`` sentences (the UI asks for a fixed count)."""
        text = " ".join((text or "").split())
        if not text:
            return text
        parts = re.split(r"(?<=[.!?])\s+", text)
        clip = " ".join(parts[:n]).strip()
        if clip and clip[-1] not in ".!?":
            clip += "."
        return clip

    @staticmethod
    def _split_reco(text: str) -> tuple[str, str]:
        """Split an LLM reply into (summary_markdown, recommendation).

        Newlines/bullets in the summary are preserved so the UI can render the
        markdown as a bulleted list.
        """
        reco = ""
        kept: list[str] = []
        for line in text.splitlines():
            m = re.match(r"\s*[-*]?\s*\**\s*recommendation\**\s*:\s*(.*)", line, re.I)
            if m and not reco:
                reco = m.group(1).strip().strip("*").strip()
            else:
                kept.append(line)
        summary = "\n".join(kept).strip()
        if not reco:  # model may have inlined "Recommendation:" mid-text
            m = re.search(r"recommendation\s*:\s*(.*)", summary, re.I | re.S)
            if m:
                reco = m.group(1).strip()
                summary = summary[: m.start()].strip()
        return summary, reco

    def _local_summary(self, c: dict[str, Any]) -> tuple[str, str]:
        """Deterministic markdown summary + 1-sentence recommendation (NAI fallback)."""
        nd, nw = len(c["detected"]), len(c["wos"])
        no, nr = len(c["open"]), len(c["resolved"])
        nn = len(c["notifications"])
        if nd == 0 and nw == 0:
            return (
                "Store operations were quiet over the last 12 hours — no computer-vision "
                "incidents and no work orders raised.\n\n"
                "- **Incidents:** 0 detected\n"
                "- **Work orders:** none raised\n"
                "- **Monitored zones:** all within normal thresholds",
                "Maintain current monitoring coverage and staffing levels.",
            )
        top_txt = ", ".join(f"{name} ({n})" for name, n in c["top_types"][:3]) or "various conditions"
        summary = (
            f"Over the last 12 hours the CV system detected {nd} incident(s) and the operations "
            f"agent opened {nw} work order(s).\n\n"
            f"- **Top issues:** {top_txt}\n"
            f"- **Work orders:** {nr} resolved, {no} open\n"
            f"- **Notifications:** {nn} sent to staff"
        )
        reco = (
            "Prioritize closing the open work orders, starting with any safety hazards."
            if no else
            "Continue the current response playbooks; all incidents this period were handled."
        )
        return (summary, reco)

    async def ops_summary(self, hours: int = 12) -> dict[str, Any]:
        payload = self._recent(hours)
        counts = self._counts(payload)
        prompt = (
            f"You are the operations analyst for {payload['store']}. Based on this JSON log of the "
            f"last {hours} hours of computer-vision incidents, agent work orders, and notifications, "
            "write a brief markdown summary of store operations: one short intro sentence, then a "
            "markdown bulleted list of 2-4 key points (each line starting with '- '), covering "
            "incident volume, the main issue types, how they were handled, and any open items. "
            "Then on a NEW LINE write a single sentence of actionable recommendation prefixed with "
            "'Recommendation:' (no bullet). Data:\n" + json.dumps(payload)
        )
        try:
            msg = await get_nai_client().chat(
                [{"role": "system", "content": "You are a concise retail operations analyst who writes clean markdown."},
                 {"role": "user", "content": prompt}],
                max_tokens=260, temperature=0.3,
            )
            text = (msg.get("content") or "").strip()
            if text:
                summary, recommendation = self._split_reco(text)
                if summary:
                    if not recommendation:
                        recommendation = self._local_summary(counts)[1]
                    # Recommendation stays a single sentence; summary keeps its markdown bullets.
                    recommendation = self._clip_sentences(recommendation, 1)
                    return {"summary": summary, "recommendation": recommendation, "nai": True}
        except NaiError as exc:
            logger.warning("ops summary falling back to local generation: %s", exc)
        summary, recommendation = self._local_summary(counts)
        return {"summary": summary, "recommendation": recommendation, "nai": False}

    def _local_answer(self, question: str, payload: dict[str, Any]) -> str:
        c = self._counts(payload)
        lines = [
            "NAI is currently unreachable — here is a data-only snapshot:",
            "",
            f"- **Incidents (12h):** {len(c['detected'])} detected",
            f"- **Work orders:** {len(c['wos'])} total ({len(c['open'])} open, {len(c['resolved'])} resolved)",
            f"- **Notifications:** {len(c['notifications'])} sent to staff",
        ]
        if c["top_types"]:
            lines.append("- **Most common:** " + ", ".join(f"{n} ({k})" for n, k in c["top_types"][:3]))
        if c["open"]:
            w = c["open"][0]
            lines.append(f"- **Oldest open item:** {w.get('id')} — {w.get('title')} ({w.get('assignee')})")
        return "\n".join(lines)

    async def answer_question(self, question: str) -> dict[str, Any]:
        payload = self._recent(12)
        system = (
            f"You are the store-operations assistant for {payload['store']}. Answer the manager's "
            "question using ONLY the provided JSON context (recent CV incidents, work orders, "
            "notifications, live metrics, and staff roster). Be specific and concise. Format the "
            "answer as clean markdown: a short lead sentence, then a markdown bulleted list (lines "
            "starting with '- ') whenever you enumerate multiple items. If the context does not "
            "contain the answer, say so briefly."
        )
        ctx = json.dumps({**payload, "staff_roster": STAFF_ROSTER})
        try:
            msg = await get_nai_client().chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {question}"}],
                max_tokens=320, temperature=0.3,
            )
            ans = (msg.get("content") or "").strip()
            if ans:
                return {"answer": ans, "nai": True}
        except NaiError as exc:
            logger.warning("ops chat falling back to local generation: %s", exc)
        return {"answer": self._local_answer(question, payload), "nai": False}

    # --- state snapshot for late-joining UI clients ---
    def state(self) -> dict[str, Any]:
        bus = get_event_bus()
        return {
            "events": [e.to_dict() for e in bus.events],
            "work_orders": list(self.work_orders.values()),
            "notifications": list(self.notifications),
            "steps": list(self.steps),
            "nai": {"base_url": self.settings.nai_base_url, "model": self.settings.nai_model},
        }


_runtime: AgentRuntime | None = None


def get_agent_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
        get_event_bus().add_listener(_runtime.on_event)
    return _runtime
