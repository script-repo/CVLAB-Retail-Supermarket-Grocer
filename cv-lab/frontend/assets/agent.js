/* Retail-Supermarket-Grocery CV Live-Analysis — Agentic Ops panel.
   Connects to /ws/agent and renders CV events, the agent's tool-use steps,
   work orders, and notifications as they stream in. Also drives the
   NAI-generated shift report modal. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var feed = null, woHost = null;
  var workOrders = {};   // id -> wo
  var feedEmpty = true;

  function init() {
    feed = $("agentFeed");
    woHost = $("woList");
    if (!feed) return;
    $("reportBtn").addEventListener("click", generateReport);
    $("reportClose").addEventListener("click", function () { $("reportModal").hidden = true; });
    $("reportModal").addEventListener("click", function (e) {
      if (e.target === $("reportModal")) $("reportModal").hidden = true;
    });
    pingNai();
    connect();
  }

  // ---------- NAI status badge ----------
  function pingNai() {
    fetch(API.base + "/api/agent/ping")
      .then(function (r) { return r.json(); })
      .then(function (res) {
        $("naiModel").textContent = res.model || "?";
        $("naiDot").className = "nai-dot " + (res.ok ? "ok" : "bad");
        $("naiBadge").title = (res.ok ? "Connected: " : "UNREACHABLE: ") + res.base_url;
      })
      .catch(function () { $("naiDot").className = "nai-dot bad"; });
  }

  // ---------- WebSocket ----------
  function wsUrl() {
    if (API.base) return API.base.replace(/^http/, "ws") + "/ws/agent";
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + "/ws/agent";
  }

  function connect() {
    var ws = new WebSocket(wsUrl());
    ws.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      handle(msg);
    };
    ws.onclose = function () { setTimeout(connect, 2000); };  // auto-reconnect
  }

  function handle(msg) {
    switch (msg.type) {
      case "init": return renderInit(msg.state);
      case "event": return addEventCard(msg.event, msg.has_snapshot);
      case "agent_run": return addRunHeader(msg);
      case "agent_step": return addStep(msg);
      case "agent_done": return;
      case "workorder": return upsertWorkOrder(msg.workorder);
      case "notification": return addNotification(msg);
    }
  }

  function renderInit(state) {
    (state.events || []).forEach(function (e) { addEventCard(e, true); });
    (state.steps || []).forEach(function (s) { handle(s); });
    (state.work_orders || []).forEach(upsertWorkOrder);
  }

  // ---------- feed rendering ----------
  function clearEmpty() {
    if (feedEmpty) { feed.innerHTML = ""; feedEmpty = false; }
  }

  function append(el) {
    clearEmpty();
    feed.appendChild(el);
    feed.scrollTop = feed.scrollHeight;
  }

  function addEventCard(ev, hasSnapshot) {
    var card = document.createElement("div");
    card.className = "feed-item feed-event " + (ev.kind === "detected" ? "is-alert" : "is-clear");
    var snap = hasSnapshot
      ? '<img class="feed-snap" src="' + API.base + '/api/events/' + ev.id + '/snapshot" alt="" onerror="this.remove()"/>'
      : "";
    card.innerHTML =
      '<div class="feed-tag">' + (ev.kind === "detected" ? "CV DETECTION" : "CV CLEARED") + " &middot; " +
        esc(ev.usecase.toUpperCase()) + " &middot; " + esc(ev.timestamp) + "</div>" +
      '<div class="feed-title">' + esc(ev.headline) + "</div>" + snap;
    append(card);
  }

  function addRunHeader(msg) {
    var el = document.createElement("div");
    el.className = "feed-item feed-run";
    el.innerHTML = '<span class="spinner"></span> Agent run <b>' + esc(msg.run_id) + "</b> &middot; " +
      (msg.mode === "incident" ? "incident response" : "clearance verification") +
      ' <span class="muted small">(llm reasoning via NAI)</span>';
    el.id = "hdr-" + msg.run_id;
    append(el);
  }

  function addStep(msg) {
    var hdr = $("hdr-" + msg.run_id);
    if (hdr) { var sp = hdr.querySelector(".spinner"); if (sp && msg.kind === "final") sp.remove(); }
    var el = document.createElement("div");
    if (msg.kind === "tool_call") {
      el.className = "feed-item feed-step";
      el.innerHTML = '<span class="step-kind">tool</span> <code>' + esc(msg.label) + "</code> " +
        '<span class="step-args">' + esc(trunc(msg.detail, 110)) + "</span>";
    } else if (msg.kind === "tool_result") {
      el.className = "feed-item feed-step feed-result";
      el.innerHTML = '<span class="step-kind ret">&rarr;</span> <span class="step-args">' +
        esc(trunc(msg.detail, 130)) + "</span>";
    } else if (msg.kind === "final") {
      el.className = "feed-item feed-final";
      el.innerHTML = '<span class="step-kind ok">done</span> ' + esc(msg.detail);
    } else if (msg.kind === "error") {
      el.className = "feed-item feed-final is-error";
      el.innerHTML = '<span class="step-kind err">fallback</span> ' + esc(msg.label);
    } else { return; }
    append(el);
  }

  function addNotification(msg) {
    var el = document.createElement("div");
    el.className = "feed-item feed-notify";
    el.innerHTML = '<span class="step-kind notify">notify</span> <b>' + esc(msg.recipient) +
      "</b>: " + esc(msg.message);
    append(el);
  }

  // ---------- work orders ----------
  function upsertWorkOrder(wo) {
    workOrders[wo.id] = wo;
    var items = Object.keys(workOrders).map(function (k) { return workOrders[k]; });
    items.sort(function (a, b) { return a.id < b.id ? 1 : -1; });
    woHost.innerHTML = "";
    items.forEach(function (w) {
      var card = document.createElement("div");
      card.className = "wo-card prio-" + w.priority + (w.status === "resolved" ? " is-resolved" : "");
      card.innerHTML =
        '<div class="wo-top"><b>' + esc(w.id) + "</b>" +
        '<span class="wo-chip prio">' + esc(w.priority) + "</span>" +
        '<span class="wo-chip status">' + esc(w.status) + "</span></div>" +
        '<div class="wo-title">' + esc(w.title) + "</div>" +
        '<div class="wo-meta">' + esc(w.assignee) + (w.area ? " &middot; " + esc(w.area) : "") +
        " &middot; " + esc(w.created_at) + "</div>" +
        (w.instructions ? '<div class="wo-instr">' + esc(w.instructions) + "</div>" : "") +
        (w.resolution_note ? '<div class="wo-res">&check; ' + esc(w.resolution_note) + "</div>" : "");
      woHost.appendChild(card);
    });
  }

  // ---------- shift report ----------
  // Client-side backstop: the server already caps the NAI call and falls back to
  // an instant local briefing, so a response should arrive well within this. This
  // just guarantees the modal never spins forever on a network/pod stall.
  var REPORT_DEADLINE_MS = 35000;

  function generateReport() {
    var modal = $("reportModal"), body = $("reportBody");
    modal.hidden = false;
    body.innerHTML = '<p class="muted"><span class="spinner"></span> Writing the briefing&hellip;</p>';

    var settled = false;
    var ctrl = new AbortController();
    var timer = setTimeout(function () {
      if (settled) return; settled = true; ctrl.abort();
      body.innerHTML = '<p class="error">The report is taking longer than expected. ' +
        'NAI may be busy — please try again.</p>';
    }, REPORT_DEADLINE_MS);

    fetch(API.base + "/api/agent/report", { method: "POST", signal: ctrl.signal })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
        return r.json();
      })
      .then(function (res) {
        if (settled) return; settled = true; clearTimeout(timer);
        body.innerHTML = mdToHtml(res.report || "(empty)");
      })
      .catch(function (e) {
        if (settled) return; settled = true; clearTimeout(timer);
        body.innerHTML = '<p class="error">Report failed: ' + esc(e.message) + "</p>";
      });
  }

  // Minimal markdown renderer (headers, bold, lists, paragraphs).
  function mdToHtml(md) {
    var lines = esc(md).split(/\r?\n/), out = [], inList = false;
    lines.forEach(function (ln) {
      var h = ln.match(/^(#{1,4})\s+(.*)/);
      var li = ln.match(/^\s*[-*]\s+(.*)/);
      if (h) {
        if (inList) { out.push("</ul>"); inList = false; }
        var lvl = Math.min(h[1].length + 2, 5);
        out.push("<h" + lvl + ">" + inline(h[2]) + "</h" + lvl + ">");
      } else if (li) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + inline(li[1]) + "</li>");
      } else if (ln.trim() === "") {
        if (inList) { out.push("</ul>"); inList = false; }
      } else {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push("<p>" + inline(ln) + "</p>");
      }
    });
    if (inList) out.push("</ul>");
    return out.join("");
    function inline(s) {
      return s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/\*([^*]+)\*/g, "<i>$1</i>");
    }
  }

  // ---------- utils ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c];
    });
  }
  function trunc(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n) + "…" : s; }

  document.addEventListener("DOMContentLoaded", init);
})();
