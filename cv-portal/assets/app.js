/* Retail-Supermarket-Grocery CV Portal — app logic (vanilla JS, no build step). */

(function () {
  "use strict";

  var state = { pattern: "all", query: "" };

  // ---- helpers ----
  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (html != null) n.innerHTML = html;
    return n;
  }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function videoPath(uc) { return uc.video || ("videos/" + pad(uc.id) + "-" + uc.slug + ".mp4"); }
  function patternColor(p) { return (PATTERNS[p] || {}).color || "var(--brand-green)"; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]; }); }

  // ---- hero stats ----
  function renderStats() {
    var host = document.getElementById("heroStats");
    var patterns = Object.keys(PATTERNS).length;
    var stats = [
      [USE_CASES.length, "Use cases"],
      [patterns, "CV patterns"],
      [TOOLS.length, "Demo tools"]
    ];
    host.innerHTML = "";
    stats.forEach(function (s) {
      host.appendChild(el("div", { class: "stat" }, "<b>" + s[0] + "</b><span>" + s[1] + "</span>"));
    });
  }

  // ---- filters ----
  function renderFilters() {
    var host = document.getElementById("filters");
    host.innerHTML = "";
    var all = el("button", { class: "chip" + (state.pattern === "all" ? " is-active" : ""), "data-pattern": "all" },
      '<span class="dot" style="--c:var(--brand-green)"></span>All <span class="count">' + USE_CASES.length + "</span>");
    host.appendChild(all);
    Object.keys(PATTERNS).forEach(function (key) {
      var count = USE_CASES.filter(function (u) { return u.pattern === key; }).length;
      var chip = el("button",
        { class: "chip" + (state.pattern === key ? " is-active" : ""), "data-pattern": key },
        '<span class="dot" style="--c:' + PATTERNS[key].color + '"></span>' + esc(PATTERNS[key].label) + ' <span class="count">' + count + "</span>");
      host.appendChild(chip);
    });
    host.querySelectorAll(".chip").forEach(function (c) {
      c.addEventListener("click", function () { state.pattern = c.getAttribute("data-pattern"); renderFilters(); renderCards(); });
    });
  }

  // ---- cards ----
  function matches(uc) {
    if (state.pattern !== "all" && uc.pattern !== state.pattern) return false;
    if (state.query) {
      var hay = (uc.title + " " + uc.loopGoal + " " + uc.cvOverlay + " " + uc.action + " " + uc.framing + " " + (PATTERNS[uc.pattern] || {}).label).toLowerCase();
      if (hay.indexOf(state.query.toLowerCase()) === -1) return false;
    }
    return true;
  }

  function mediaForCard(uc) {
    var wrap = el("div", { class: "card-media" });
    wrap.appendChild(el("span", { class: "card-num" }, "" + uc.id));
    var v = document.createElement("video");
    v.muted = true; v.loop = true; v.playsInline = true; v.preload = "metadata";
    v.src = videoPath(uc);
    v.addEventListener("loadeddata", function () { v.play().catch(function () {}); });
    v.addEventListener("error", function () {
      if (v.parentNode) {
        var ph = el("div", { class: "placeholder" },
          '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2" y="5" width="14" height="14" rx="2"/><path d="m16 9 6-3v12l-6-3"/></svg>Footage pending');
        v.replaceWith(ph);
      }
    });
    wrap.appendChild(v);
    return wrap;
  }

  function renderCards() {
    var host = document.getElementById("cards");
    var empty = document.getElementById("empty");
    host.innerHTML = "";
    var list = USE_CASES.filter(matches);
    empty.hidden = list.length > 0;
    list.forEach(function (uc) {
      var color = patternColor(uc.pattern);
      var card = el("article", { class: "card", style: "--c:" + color });
      card.appendChild(mediaForCard(uc));
      var body = el("div", { class: "card-body" });
      body.appendChild(el("div", { class: "card-pattern" }, esc((PATTERNS[uc.pattern] || {}).label || "")));
      body.appendChild(el("h3", null, esc(uc.title)));
      body.appendChild(el("p", { class: "card-goal" }, esc(uc.loopGoal)));
      var foot = el("div", { class: "card-foot" });
      if (uc.live) {
        foot.appendChild(el("span", { class: "badge recorded" }, "● Live analysis"));
        foot.appendChild(el("span", { class: "more" }, "Open →"));
      } else {
        foot.appendChild(el("span", { class: "badge pending" }, "Footage pending"));
        foot.appendChild(el("span", { class: "more" }, "View plan →"));
      }
      body.appendChild(foot);
      card.appendChild(body);
      card.addEventListener("click", function () { openModal(uc); });
      host.appendChild(card);
    });
  }

  // ---- modal ----
  function openModal(uc) {
    var color = patternColor(uc.pattern);
    var body = document.getElementById("modalBody");
    var media = el("div", { class: "modal-media" });
    var v = document.createElement("video");
    v.controls = true; v.muted = true; v.loop = true; v.playsInline = true; v.preload = "metadata";
    v.src = videoPath(uc);
    v.addEventListener("error", function () {
      if (v.parentNode) {
        v.replaceWith(el("div", { class: "placeholder" },
          '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="5" width="14" height="14" rx="2"/><path d="m16 9 6-3v12l-6-3"/></svg>Footage pending — drop <code>' + esc(videoPath(uc)) + "</code>"));
      }
    });
    media.appendChild(v);

    var content = el("div", { class: "modal-content" });
    content.appendChild(el("div", { class: "tag-row" },
      '<span class="pill" style="background:' + color + '">' + esc((PATTERNS[uc.pattern] || {}).label) + "</span>" +
      '<span class="badge pending">Use case ' + uc.id + "</span>"));
    content.appendChild(el("h2", null, esc(uc.title)));

    if (uc.live) {
      content.appendChild(el("a", {
        class: "btn live-btn", href: "../cv-lab/index.html?usecase=" + uc.live, target: "_blank", rel: "noopener"
      }, "● Open live analysis →"));
    }

    var spec = el("dl", { class: "spec" });
    [["Camera angle", uc.cameraAngle], ["Framing", uc.framing], ["Action", uc.action], ["CV overlay", uc.cvOverlay], ["Loop goal", uc.loopGoal]]
      .forEach(function (row) {
        var r = el("div", { class: "spec-row" });
        r.appendChild(el("dt", null, row[0]));
        r.appendChild(el("dd", null, esc(row[1])));
        spec.appendChild(r);
      });
    content.appendChild(spec);

    if (uc.models && uc.models.length) {
      content.appendChild(el("h3", { class: "modal-h3" }, "Models & why they were chosen"));
      var ml = el("div", { class: "model-list" });
      uc.models.forEach(function (m) {
        var mc = el("div", { class: "model-card" });
        mc.appendChild(el("div", { class: "model-head" },
          '<span class="model-name">' + esc(m.name) + "</span>" +
          (m.role ? '<span class="model-role">' + esc(m.role) + "</span>" : "")));
        if (m.why) mc.appendChild(el("p", { class: "model-why" }, esc(m.why)));
        ml.appendChild(mc);
      });
      content.appendChild(ml);
    }

    if (uc.infra && uc.infra.length) {
      content.appendChild(el("h3", { class: "modal-h3" }, "Supporting infrastructure (Nutanix + Litmus)"));
      var il = el("ul", { class: "infra-list" });
      uc.infra.forEach(function (s) { il.appendChild(el("li", null, esc(s))); });
      content.appendChild(il);
    }

    body.innerHTML = "";
    body.appendChild(media);
    body.appendChild(content);
    document.getElementById("modal").hidden = false;
    document.body.style.overflow = "hidden";
  }
  function closeModal() {
    document.getElementById("modal").hidden = true;
    document.getElementById("modalBody").innerHTML = "";
    document.body.style.overflow = "";
  }

  // ---- tools ----
  function renderTools() {
    var host = document.getElementById("tools");
    host.innerHTML = "";
    var colors = [getC("--brand-cyan"), getC("--brand-orange"), getC("--brand-purple"), getC("--brand-magenta")];
    TOOLS.forEach(function (t, i) {
      var card = el("article", { class: "tool-card", style: "border-left-color:" + (colors[i % colors.length]) });
      card.appendChild(el("h3", null, esc(t.name)));
      card.appendChild(el("p", null, esc(t.best)));
      var modes = el("div", { class: "tool-modes" });
      (t.modes || []).forEach(function (m) { modes.appendChild(el("span", null, esc(m))); });
      card.appendChild(modes);
      card.appendChild(el("a", { class: "btn", href: t.url, target: "_blank", rel: "noopener" }, "Open tool ↗"));
      host.appendChild(card);
    });
  }
  function getC(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  // ---- recording guide ----
  function renderRecording() {
    var t = document.getElementById("recSettings");
    t.innerHTML = "";
    RECORDING.settings.forEach(function (row) {
      var tr = el("tr");
      tr.appendChild(el("td", null, esc(row[0])));
      tr.appendChild(el("td", null, esc(row[1])));
      t.appendChild(tr);
    });
    var ul = document.getElementById("recGuidance");
    ul.innerHTML = "";
    RECORDING.guidance.forEach(function (g) { ul.appendChild(el("li", null, esc(g))); });
  }

  // ---- tabs ----
  function setView(view) {
    document.querySelectorAll(".tab").forEach(function (t) { t.classList.toggle("is-active", t.getAttribute("data-view") === view); });
    document.querySelectorAll(".view").forEach(function (v) { v.classList.toggle("is-active", v.id === "view-" + view); });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ---- init ----
  function init() {
    renderStats();
    renderFilters();
    renderCards();
    renderTools();
    renderRecording();

    document.getElementById("search").addEventListener("input", function (e) { state.query = e.target.value; renderCards(); });
    document.getElementById("tabs").addEventListener("click", function (e) {
      var btn = e.target.closest(".tab"); if (btn) setView(btn.getAttribute("data-view"));
    });
    document.getElementById("modal").addEventListener("click", function (e) {
      if (e.target.hasAttribute("data-close")) closeModal();
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeModal(); });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
