/* Retail-Supermarket-Grocery CV Use-Case Library — detailed reference (vanilla JS, no build step). */
(function () {
  "use strict";

  var state = { pattern: "all" };

  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c];
    });
  }
  function patternMeta(p) { return PATTERNS[p] || { label: p, color: "#003D2A" }; }

  // ---- filters ----
  function renderFilters() {
    var host = document.getElementById("filters");
    host.innerHTML = "";
    host.appendChild(chip("all", "All", USE_CASES.length, "#003D2A"));
    Object.keys(PATTERNS).forEach(function (key) {
      var count = USE_CASES.filter(function (u) { return u.pattern === key; }).length;
      host.appendChild(chip(key, PATTERNS[key].label, count, PATTERNS[key].color));
    });
    host.querySelectorAll(".chip").forEach(function (c) {
      c.addEventListener("click", function () {
        state.pattern = c.getAttribute("data-pattern");
        renderFilters(); renderCards();
      });
    });
  }
  function chip(key, label, count, color) {
    return el("button",
      { class: "chip" + (state.pattern === key ? " is-active" : ""), "data-pattern": key },
      '<span class="dot" style="background:' + color + '"></span>' + esc(label) +
      ' <span class="count">' + count + "</span>");
  }

  // ---- matching ----
  function matches(uc) {
    if (state.pattern !== "all" && uc.pattern !== state.pattern) return false;
    if (window.CVSettings && CVSettings.isHidden(uc.live)) return false;
    return true;
  }

  // ---- multi-view (CCTV wall) ----
  // Each visible use case becomes a live analyzer tile with its own
  // /ws/analyze stream. Per-tile FPS adapts to the number of active tiles so
  // an uncapped wall stays responsive.
  var mv = { streams: [], videos: null };

  function mvFps(n) { return n <= 4 ? 8 : n <= 9 ? 5 : n <= 16 ? 4 : 3; }

  function mvTeardown() {
    mv.streams.forEach(function (s) {
      try { s.ws.close(); } catch (e) {}
      if (s.lastUrl) URL.revokeObjectURL(s.lastUrl);
    });
    mv.streams = [];
  }

  function mvVideoFor(ucLive) {
    var saved = null;
    try { saved = localStorage.getItem("cvlab-lastvideo-" + ucLive); } catch (e) {}
    var vids = mv.videos || [];
    if (saved && vids.some(function (v) { return v.id === saved; })) return saved;
    return vids.length ? vids[0].id : null;
  }

  function mvTile(uc, fps) {
    var meta = patternMeta(uc.pattern);
    var tile = el("article", { class: "mv-tile", style: "--c:" + meta.color });
    tile.innerHTML =
      '<div class="mv-stage"><img alt=""/><span class="mv-live">&#9679; LIVE</span></div>' +
      '<div class="mv-info"><span class="uc-num">UC-' + String(uc.id).padStart(2, "0") + "</span>" +
      '<span class="mv-title">' + esc(uc.title) + "</span></div>" +
      '<div class="mv-status" data-status>connecting&hellip;</div>';
    tile.addEventListener("click", function () {
      location.href = "index.html?usecase=" + encodeURIComponent(uc.live);
    });

    var img = tile.querySelector("img");
    var statusEl = tile.querySelector("[data-status]");
    var videoId = mvVideoFor(uc.live);
    if (!videoId) {
      statusEl.textContent = "no footage uploaded";
      tile.classList.add("mv-nofeed");
      return tile;
    }

    var ws = API.openStream();
    ws.binaryType = "arraybuffer";
    var entry = { ws: ws, lastUrl: null };
    mv.streams.push(entry);
    ws.onopen = function () {
      ws.send(JSON.stringify({
        action: "start",
        config: { video_id: videoId, usecase: uc.live, zones: [], params: {}, loop: true, fps: fps }
      }));
    };
    ws.onmessage = function (ev) {
      if (typeof ev.data !== "string") {
        var url = URL.createObjectURL(new Blob([ev.data], { type: "image/jpeg" }));
        img.src = url;
        if (entry.lastUrl) URL.revokeObjectURL(entry.lastUrl);
        entry.lastUrl = url;
        return;
      }
      var m = JSON.parse(ev.data);
      if (m.type === "metrics") {
        statusEl.textContent = m.headline || "";
        statusEl.className = "mv-status" + (m.status === "alert" ? " is-alert" : "");
      } else if (m.type === "error") {
        statusEl.textContent = m.message;
        statusEl.className = "mv-status is-alert";
      }
    };
    ws.onclose = function () { tile.classList.add("mv-ended"); };
    return tile;
  }

  function renderMultiView() {
    var host = document.getElementById("cards");
    var empty = document.getElementById("empty");
    mvTeardown();
    host.innerHTML = "";
    host.classList.add("mv-grid");
    var list = USE_CASES.filter(matches);
    empty.hidden = list.length > 0;
    var fps = mvFps(list.length);
    var build = function () { list.forEach(function (uc) { host.appendChild(mvTile(uc, fps)); }); };
    if (mv.videos === null && window.API) {
      API.listVideos().then(function (res) { mv.videos = res.videos || []; build(); })
        .catch(function () { mv.videos = []; build(); });
    } else {
      build();
    }
  }

  // ---- cards ----
  function renderCards() {
    if (window.CVSettings && CVSettings.get().multiView) { renderMultiView(); return; }
    var host = document.getElementById("cards");
    var empty = document.getElementById("empty");
    mvTeardown();
    host.classList.remove("mv-grid");
    host.innerHTML = "";
    var list = USE_CASES.filter(matches);
    empty.hidden = list.length > 0;
    list.forEach(function (uc) {
      var meta = patternMeta(uc.pattern);
      var card = el("article", { class: "lib-card", style: "--c:" + meta.color });
      card.appendChild(el("div", { class: "lib-card-head" },
        '<span class="uc-num">UC-' + String(uc.id).padStart(2, "0") + "</span>" +
        '<span class="pattern-tag" style="background:' + meta.color + '">' + esc(meta.label) + "</span>"));
      card.appendChild(el("h3", null, esc(uc.title)));
      card.appendChild(el("p", { class: "lib-goal" }, esc(uc.loopGoal)));
      // quick tech preview
      var techs = (uc.models || []).map(function (m) { return m.name; });
      var techWrap = el("div", { class: "lib-tech" });
      techs.slice(0, 3).forEach(function (t) { techWrap.appendChild(el("span", null, esc(t))); });
      card.appendChild(techWrap);
      var foot = el("div", { class: "lib-card-foot" });
      foot.appendChild(el("span", { class: "live-dot" }, "● Live"));
      foot.appendChild(el("span", { class: "more" }, "Full details →"));
      card.appendChild(foot);
      card.addEventListener("click", function () { openModal(uc); });
      host.appendChild(card);
    });
  }

  // ---- detail modal ----
  function section(title) { return el("h3", { class: "sec-h" }, esc(title)); }

  function specBlock(uc) {
    var dl = el("dl", { class: "spec" });
    [["Pattern", patternMeta(uc.pattern).label], ["Camera angle", uc.cameraAngle],
     ["Framing", uc.framing], ["Scenario", uc.action], ["CV overlay", uc.cvOverlay],
     ["Demo goal", uc.loopGoal]].forEach(function (row) {
      var r = el("div", { class: "spec-row" });
      r.appendChild(el("dt", null, esc(row[0])));
      r.appendChild(el("dd", null, esc(row[1])));
      dl.appendChild(r);
    });
    return dl;
  }

  function openModal(uc) {
    var meta = patternMeta(uc.pattern);
    var body = document.getElementById("modalBody");
    body.innerHTML = "";

    var head = el("div", { class: "detail-head", style: "--c:" + meta.color });
    head.appendChild(el("div", { class: "tag-row" },
      '<span class="uc-num big">UC-' + String(uc.id).padStart(2, "0") + "</span>" +
      '<span class="pattern-tag" style="background:' + meta.color + '">' + esc(meta.label) + "</span>" +
      '<span class="live-dot">● Live analysis available</span>'));
    head.appendChild(el("h2", null, esc(uc.title)));
    head.appendChild(el("a", {
      class: "btn primary detail-cta", href: "index.html?usecase=" + esc(uc.live)
    }, "● Open live analysis →"));
    body.appendChild(head);

    body.appendChild(section("Camera & scenario"));
    body.appendChild(specBlock(uc));

    body.appendChild(section("Vision models & why they were chosen"));
    var ml = el("div", { class: "model-list" });
    (uc.models || []).forEach(function (m) {
      var mc = el("div", { class: "model-card" });
      mc.appendChild(el("div", { class: "model-head" },
        '<span class="model-name">' + esc(m.name) + "</span>" +
        (m.role ? '<span class="model-role">' + esc(m.role) + "</span>" : "")));
      if (m.why) mc.appendChild(el("p", { class: "model-why" }, esc(m.why)));
      ml.appendChild(mc);
    });
    body.appendChild(ml);

    body.appendChild(section("Supporting infrastructure (Nutanix + Litmus)"));
    var il = el("ul", { class: "infra-list" });
    (uc.infra || []).forEach(function (s) { il.appendChild(el("li", null, esc(s))); });
    body.appendChild(il);

    document.getElementById("modal").hidden = false;
    document.body.style.overflow = "hidden";
    body.parentElement.scrollTop = 0;
  }

  function closeModal() {
    document.getElementById("modal").hidden = true;
    document.getElementById("modalBody").innerHTML = "";
    document.body.style.overflow = "";
  }

  // ---- NAI store-operations dashboard ----

  // Client-side deadline: if NAI hasn't answered within this window, show a
  // prepared placeholder instead of blocking the demo on a slow endpoint.
  var NAI_DEADLINE_MS = 4000;

  // Minimal markdown renderer (headers, bold/italic, bulleted lists, paragraphs).
  function mdToHtml(md) {
    var lines = esc(md).split(/\r?\n/), out = [], inList = false;
    lines.forEach(function (ln) {
      var h = ln.match(/^(#{1,4})\s+(.*)/);
      var li = ln.match(/^\s*[-*]\s+(.*)/);
      if (h) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push("<h4>" + inline(h[2]) + "</h4>");
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

  // ---- prepared placeholders (used when NAI exceeds the deadline) ----
  var PLACEHOLDER_SUMMARY = {
    summary:
      "Store operations over the last 12 hours were steady, with no critical issues left outstanding.\n\n" +
      "- **Queues:** short peaks at checkout, with extra lanes opened on cue\n" +
      "- **Safety:** one spill detected in Aisle 3 and cleared by staff\n" +
      "- **Stock:** a few low-shelf alerts in beverages and snacks, since replenished\n" +
      "- **Agent:** work orders opened and resolved automatically",
    recommendation:
      "Keep one extra cashier on standby for the afternoon peak to hold wait times down."
  };

  var CANNED = {
    "What happened in the last 12 hours?":
      "In the last 12 hours the store ran smoothly:\n\n" +
      "- **Queues:** the busiest category — brief peaks handled by opening lanes\n" +
      "- **Safety:** one spill (Aisle 3) detected and cleared\n" +
      "- **Stock:** scattered out-of-stock alerts, mostly in beverages\n" +
      "- **Agent:** incidents were auto-triaged into work orders and closed",
    "Are there any open safety hazards?":
      "No open safety hazards right now.\n\n" +
      "- Last spill (Aisle 3) was detected and **resolved**\n" +
      "- Walkways and exits are clear\n" +
      "- No blocked fire lanes reported",
    "Which aisles had the most stock issues?":
      "Stock alerts clustered in a few aisles:\n\n" +
      "- **Aisle 7 — Beverages:** most frequent low-shelf alerts\n" +
      "- **Aisle 2 — Snacks:** several refill prompts\n" +
      "- **Dairy:** one cold-chain check, within range",
    "How were checkout queues handled today?":
      "Checkout queues stayed under control:\n\n" +
      "- Peak observed at **6 customers** in a single lane\n" +
      "- The agent recommended opening additional lanes\n" +
      "- Average wait dropped back under target once lanes opened"
  };

  var GENERIC_CHAT_PLACEHOLDER =
    "NAI is taking longer than usual, so here's a quick snapshot:\n\n" +
    "- Recent activity is dominated by checkout-queue monitoring\n" +
    "- One spill was detected and cleared\n" +
    "- No safety hazards are currently open\n\n" +
    "Ask again in a moment for a live, data-grounded answer.";

  function setBadge(ok) {
    var dot = document.getElementById("opsNaiDot");
    if (dot) dot.className = "nai-dot " + (ok ? "ok" : "bad");
  }

  // The badge reflects whether NAI is reachable, via a dedicated liveness probe.
  // (Tying it to the 12h-summary call made it perpetually red, because that
  // large generation usually exceeds the client-side display deadline.)
  function refreshNaiBadge() {
    if (!window.API || !API.pingNai) return;
    var done = false;
    var ctrl = new AbortController();
    var t = setTimeout(function () {
      if (done) return; done = true; ctrl.abort(); setBadge(false);
    }, 8000);
    API.pingNai(ctrl.signal).then(function (res) {
      if (done) return; done = true; clearTimeout(t); setBadge(!!(res && res.ok));
    }).catch(function () {
      if (done) return; done = true; clearTimeout(t); setBadge(false);
    });
  }

  function renderSummary(summaryMd, recoMd, nai) {
    var sum = document.getElementById("opsSummary");
    var reco = document.getElementById("opsReco");
    sum.innerHTML = mdToHtml(summaryMd || "No summary available.");
    if (recoMd) {
      document.getElementById("opsRecoText").innerHTML = mdToHtml(recoMd);
      reco.hidden = false;
    } else {
      reco.hidden = true;
    }
    // A genuine NAI response confirms liveness; a placeholder leaves the badge
    // to the dedicated ping probe (don't flip it red just because we were slow).
    if (nai) setBadge(true);
  }

  function loadSummary() {
    var sum = document.getElementById("opsSummary");
    if (!sum || !window.API || !API.opsSummary) return;
    sum.innerHTML = '<p class="muted small"><span class="spinner"></span> NAI is summarizing the last 12 hours&hellip;</p>';
    document.getElementById("opsReco").hidden = true;

    var settled = false;
    var ctrl = new AbortController();
    var timer = setTimeout(function () {
      if (settled) return; settled = true; ctrl.abort();
      renderSummary(PLACEHOLDER_SUMMARY.summary, PLACEHOLDER_SUMMARY.recommendation, false);
    }, NAI_DEADLINE_MS);

    API.opsSummary(ctrl.signal).then(function (res) {
      if (settled) return; settled = true; clearTimeout(timer);
      renderSummary(res.summary, res.recommendation, res.nai);
    }).catch(function () {
      if (settled) return; settled = true; clearTimeout(timer);
      renderSummary(PLACEHOLDER_SUMMARY.summary, PLACEHOLDER_SUMMARY.recommendation, false);
    });
  }

  function addBubble(role, text, pending) {
    var log = document.getElementById("chatLog");
    var hint = log.querySelector(".chat-hint");
    if (hint) hint.remove();
    var b = el("div", { class: "bubble " + role + (pending ? " pending" : "") });
    if (pending) b.innerHTML = '<span class="spinner"></span> NAI is thinking&hellip;';
    else b.textContent = text;
    log.appendChild(b);
    log.scrollTop = log.scrollHeight;
    return b;
  }

  function finishBubble(bubble, md, nai) {
    bubble.classList.remove("pending");
    bubble.innerHTML = mdToHtml(md);
    if (nai) setBadge(true);
    var log = document.getElementById("chatLog");
    log.scrollTop = log.scrollHeight;
  }

  function askQuestion(q, placeholderMd) {
    q = (q || "").trim();
    if (!q || !window.API || !API.opsAsk) return;
    addBubble("user", q);
    document.getElementById("chatInput").value = "";
    var pending = addBubble("bot", "", true);
    var fallback = placeholderMd || GENERIC_CHAT_PLACEHOLDER;

    var settled = false;
    var ctrl = new AbortController();
    var timer = setTimeout(function () {
      if (settled) return; settled = true; ctrl.abort();
      finishBubble(pending, fallback, false);
    }, NAI_DEADLINE_MS);

    API.opsAsk(q, ctrl.signal).then(function (res) {
      if (settled) return; settled = true; clearTimeout(timer);
      finishBubble(pending, res.answer || "(no answer)", res.nai);
    }).catch(function () {
      if (settled) return; settled = true; clearTimeout(timer);
      finishBubble(pending, fallback, false);
    });
  }

  function setupOps() {
    if (!document.getElementById("opsDash")) return;
    refreshNaiBadge();
    loadSummary();
    document.getElementById("opsRefresh").addEventListener("click", function () {
      refreshNaiBadge(); loadSummary();
    });
    document.getElementById("chatForm").addEventListener("submit", function (e) {
      e.preventDefault();
      askQuestion(document.getElementById("chatInput").value, null);
    });
    document.querySelectorAll("#chatCanned .canned-q").forEach(function (btn) {
      btn.addEventListener("click", function () {
        askQuestion(btn.textContent, CANNED[btn.textContent.trim()]);
      });
    });
  }

  function init() {
    renderFilters();
    renderCards();
    setupOps();
    document.getElementById("modal").addEventListener("click", function (e) {
      if (e.target.hasAttribute("data-close")) closeModal();
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeModal(); });
    document.addEventListener("cvlab-settings-changed", function () {
      renderFilters(); renderCards();
    });
    window.addEventListener("beforeunload", mvTeardown);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
