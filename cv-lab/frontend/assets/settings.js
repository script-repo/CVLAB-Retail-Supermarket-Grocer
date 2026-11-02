/* Retail-Supermarket-Grocery CV — global settings (gear in the header, persisted in localStorage).
   Shared by both pages. Exposes window.CVSettings and fires a
   "cvlab-settings-changed" event on document when anything changes. */
(function () {
  "use strict";

  var KEY = "cvlab-settings";

  var defaults = {
    hidden: [],          // use-case ids hidden across the UI, e.g. ["uc-04"]
    advancedGpu: false,  // stacked per-use-case GPU bar instead of single bar
    multiView: false     // CCTV-style live tiles on the library page
  };

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      var s = raw ? JSON.parse(raw) : {};
      return {
        hidden: Array.isArray(s.hidden) ? s.hidden : [],
        advancedGpu: !!s.advancedGpu,
        multiView: !!s.multiView
      };
    } catch (e) { return JSON.parse(JSON.stringify(defaults)); }
  }

  var state = load();

  function save() {
    localStorage.setItem(KEY, JSON.stringify(state));
    document.dispatchEvent(new CustomEvent("cvlab-settings-changed", { detail: get() }));
  }

  function get() {
    return { hidden: state.hidden.slice(), advancedGpu: state.advancedGpu, multiView: state.multiView };
  }

  window.CVSettings = {
    get: get,
    isHidden: function (ucId) { return state.hidden.indexOf(ucId) !== -1; },
    setHidden: function (ucId, hide) {
      var i = state.hidden.indexOf(ucId);
      if (hide && i === -1) state.hidden.push(ucId);
      if (!hide && i !== -1) state.hidden.splice(i, 1);
      save();
    },
    set: function (key, val) {
      if (key in state && key !== "hidden") { state[key] = !!val; save(); }
    }
  };

  // ---------- UI: gear button + modal ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c];
    });
  }

  // Use cases for the visibility list: prefer the catalog (library page),
  // else fetch from the API (analysis page).
  function getUsecaseList() {
    if (typeof USE_CASES !== "undefined") {
      return Promise.resolve(USE_CASES.map(function (u) {
        return { id: u.live, title: u.title };
      }));
    }
    if (window.API && API.listUsecases) {
      return API.listUsecases().then(function (res) {
        return (res.usecases || []).map(function (u) { return { id: u.id, title: u.title }; });
      });
    }
    return Promise.resolve([]);
  }

  function buildModal() {
    var wrap = document.createElement("div");
    wrap.className = "settings-modal";
    wrap.id = "settingsModal";
    wrap.hidden = true;
    wrap.innerHTML =
      '<div class="settings-box">' +
      '  <div class="settings-head"><h2>Settings</h2>' +
      '    <button class="btn ghost" id="settingsClose">Close</button></div>' +
      '  <div class="settings-body">' +
      '    <section class="settings-sec">' +
      '      <h3>Display</h3>' +
      '      <label class="toggle-row"><input type="checkbox" id="setAdvGpu"/>' +
      '        <span><b>Advanced GPU stats</b><br/><small>Stacked per-use-case utilization bar (hover a segment for the use-case name and share).</small></span></label>' +
      '      <label class="toggle-row"><input type="checkbox" id="setMultiView"/>' +
      '        <span><b>Multi-view (CCTV wall)</b><br/><small>Library cards become simultaneous live analyzer tiles. Frame rate adapts to the number of active tiles.</small></span></label>' +
      '    </section>' +
      '    <section class="settings-sec">' +
      '      <h3>Use-case visibility</h3>' +
      '      <p class="muted small">Unchecked use cases are hidden from the analysis sidebar, the library grid, and multi-view.</p>' +
      '      <div class="uc-vis-actions">' +
      '        <button class="link-btn" id="visAll">Show all</button>' +
      '        <button class="link-btn" id="visNone">Hide all</button>' +
      '      </div>' +
      '      <div class="uc-vis-grid" id="ucVisGrid"><p class="muted small">Loading…</p></div>' +
      '    </section>' +
      '    <section class="settings-sec">' +
      '      <h3>Inference</h3>' +
      '      <div class="source-toggle" id="naiModeToggle">' +
      '        <button type="button" class="src-btn is-active" data-mode="live">Live inference</button>' +
      '        <button type="button" class="src-btn" data-mode="demo">Demo data</button>' +
      '      </div>' +
      '      <p class="muted small">Live inference calls the NAI endpoint. Demo data skips the model: the library shows prepared sample answers, and agent runs use local rules.</p>' +
      '      <p class="muted small">Any OpenAI-compatible base URL. The API key stays on this server and is not shown again after you save.</p>' +
      '      <label class="field-label">Base URL' +
      '        <input type="url" id="naiBaseUrl" class="src-input" placeholder="https://your-llm-endpoint/v1" autocomplete="off" spellcheck="false"/></label>' +
      '      <label class="field-label">Model' +
      '        <input type="text" id="naiModelInput" class="src-input" placeholder="llama3-1-8b" autocomplete="off" spellcheck="false"/></label>' +
      '      <label class="field-label">API key' +
      '        <input type="password" id="naiApiKey" class="src-input" placeholder="Bearer token" autocomplete="new-password" spellcheck="false"/></label>' +
      '      <p class="muted small" id="naiKeyHint">Loading…</p>' +
      '      <div class="settings-actions">' +
      '        <button class="btn primary" type="button" id="naiSave">Save and test</button>' +
      '        <button class="link-btn" type="button" id="naiClearKey">Clear saved key</button>' +
      '      </div>' +
      '      <p class="nai-status muted small" id="naiStatus"></p>' +
      '    </section>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(wrap);

    wrap.addEventListener("click", function (e) { if (e.target === wrap) close(); });
    document.getElementById("settingsClose").addEventListener("click", close);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });

    var adv = document.getElementById("setAdvGpu");
    var mv = document.getElementById("setMultiView");
    adv.checked = state.advancedGpu;
    mv.checked = state.multiView;
    adv.addEventListener("change", function () { window.CVSettings.set("advancedGpu", adv.checked); });
    mv.addEventListener("change", function () { window.CVSettings.set("multiView", mv.checked); });

    document.getElementById("visAll").addEventListener("click", function () {
      state.hidden = []; save(); renderVisGrid();
    });
    document.getElementById("visNone").addEventListener("click", function () {
      getUsecaseList().then(function (list) {
        state.hidden = list.map(function (u) { return u.id; });
        save(); renderVisGrid();
      });
    });
    document.getElementById("naiSave").addEventListener("click", function () { saveNai(false); });
    document.getElementById("naiClearKey").addEventListener("click", function () { saveNai(true); });
    document.getElementById("naiModeToggle").addEventListener("click", function (e) {
      var btn = e.target.closest(".src-btn");
      if (!btn) return;
      setNaiMode(btn.getAttribute("data-mode") === "live");
    });
    renderVisGrid();
  }

  function naiStatus(text, kind) {
    var el = document.getElementById("naiStatus");
    if (!el) return;
    el.textContent = text || "";
    el.className = "nai-status muted small" + (kind ? " " + kind : "");
  }

  function setNaiBusy(busy) {
    ["naiSave", "naiClearKey"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.disabled = busy;
    });
  }

  function fillNaiForm(cfg) {
    var base = document.getElementById("naiBaseUrl");
    var model = document.getElementById("naiModelInput");
    var hint = document.getElementById("naiKeyHint");
    if (!base || !model || !hint || !cfg) return;
    base.value = cfg.base_url || "";
    model.value = cfg.model || "";
    document.getElementById("naiApiKey").value = "";
    setNaiModeButtons(cfg.use_live_llm !== false);
    hint.textContent = cfg.api_key_set
      ? "A key is saved (" + (cfg.api_key_hint || "hidden") + "). Leave the field blank to keep it."
      : "No API key saved. Paste one if the endpoint requires a bearer token.";
  }

  function setNaiModeButtons(live) {
    document.querySelectorAll("#naiModeToggle .src-btn").forEach(function (btn) {
      var on = (btn.getAttribute("data-mode") === "live") === !!live;
      btn.classList.toggle("is-active", on);
    });
  }

  function setNaiMode(live) {
    if (!window.API || !API.saveNaiConfig) {
      naiStatus("Settings API is unavailable.", "bad");
      return;
    }
    var gen = ++naiLoadGen;
    setNaiModeButtons(live);
    naiStatus(live ? "Switching to live inference…" : "Switching to demo data…");
    API.saveNaiConfig({ use_live_llm: !!live }).then(function (cfg) {
      if (gen !== naiLoadGen) return;
      setNaiModeButtons(cfg.use_live_llm !== false);
      naiStatus(cfg.use_live_llm
        ? "Live inference is on. Agentic Ops will call the NAI endpoint."
        : "Demo data is on. Agentic Ops will not call the model.");
      document.dispatchEvent(new CustomEvent("cvlab-nai-changed", {
        detail: {
          use_live_llm: cfg.use_live_llm !== false,
          configured: !!cfg.configured,
          model: cfg.model,
          base_url: cfg.base_url || "",
          ok: false
        }
      }));
    }).catch(function (err) {
      if (gen !== naiLoadGen) return;
      setNaiModeButtons(!live);
      naiStatus(err && err.message ? err.message : "Couldn't update the inference mode.", "bad");
    });
  }

  function loadNaiForm() {
    if (!window.API || !API.getNaiConfig) {
      naiStatus("Settings API is unavailable.", "bad");
      return;
    }
    var gen = ++naiLoadGen;
    naiStatus("");
    API.getNaiConfig().then(function (cfg) {
      if (gen !== naiLoadGen) return;
      fillNaiForm(cfg);
    }).catch(function () {
      if (gen !== naiLoadGen) return;
      naiStatus("Couldn't load the current endpoint.", "bad");
    });
  }

  function saveNai(clearKey) {
    if (!window.API || !API.saveNaiConfig) {
      naiStatus("Settings API is unavailable.", "bad");
      return;
    }
    if (clearKey && !window.confirm("Remove the saved API key?")) return;
    var gen = ++naiLoadGen;
    var base = document.getElementById("naiBaseUrl").value.trim();
    var model = document.getElementById("naiModelInput").value.trim();
    var key = document.getElementById("naiApiKey").value;
    var body = { base_url: base, model: model, clear_api_key: !!clearKey };
    if (!clearKey && key) body.api_key = key;
    naiStatus(clearKey ? "Clearing the saved key…" : "Saving and checking the endpoint…");
    setNaiBusy(true);
    API.saveNaiConfig(body).then(function (cfg) {
      if (gen !== naiLoadGen) return null;
      fillNaiForm(cfg);
      if (!cfg.configured) {
        naiStatus("Saved. No endpoint is set, so Agentic Ops uses the local fallback.");
        document.dispatchEvent(new CustomEvent("cvlab-nai-changed", {
          detail: { ok: false, model: cfg.model, base_url: "", configured: false }
        }));
        return null;
      }
      var ctrl = new AbortController();
      var timer = setTimeout(function () { ctrl.abort(); }, 20000);
      return API.pingNai(ctrl.signal).then(function (res) {
        clearTimeout(timer);
        return res;
      }).catch(function () {
        clearTimeout(timer);
        return { ok: false, model: cfg.model, base_url: cfg.base_url, configured: true, timedOut: true };
      });
    }).then(function (res) {
      if (gen !== naiLoadGen || !res) return;
      if (res.ok) naiStatus("Connected to " + (res.model || "the endpoint") + ".", "ok");
      else if (res.timedOut) naiStatus("Saved, but the connection check timed out. Check the base URL, model, and API key.", "bad");
      else naiStatus("Saved, but the endpoint did not respond. Check the base URL, model, and API key.", "bad");
      document.dispatchEvent(new CustomEvent("cvlab-nai-changed", { detail: res }));
    }).catch(function (err) {
      if (gen !== naiLoadGen) return;
      naiStatus(err && err.message ? err.message : "Couldn't save the endpoint.", "bad");
    }).then(function () { setNaiBusy(false); });
  }

  var naiLoadGen = 0;
  var ucCache = null;
  function renderVisGrid() {
    var host = document.getElementById("ucVisGrid");
    if (!host) return;
    var render = function (list) {
      ucCache = list;
      host.innerHTML = "";
      list.forEach(function (u) {
        var lbl = document.createElement("label");
        lbl.className = "uc-vis-item";
        lbl.innerHTML = '<input type="checkbox" ' +
          (window.CVSettings.isHidden(u.id) ? "" : "checked") + '/>' +
          '<span class="uc-id">' + esc(u.id.toUpperCase()) + '</span> ' + esc(u.title);
        lbl.querySelector("input").addEventListener("change", function (e) {
          window.CVSettings.setHidden(u.id, !e.target.checked);
        });
        host.appendChild(lbl);
      });
    };
    if (ucCache) render(ucCache);
    else getUsecaseList().then(render);
  }

  function open() {
    if (!document.getElementById("settingsModal")) buildModal();
    renderVisGrid();
    loadNaiForm();
    document.getElementById("settingsModal").hidden = false;
  }
  function close() {
    var m = document.getElementById("settingsModal");
    if (m) m.hidden = true;
  }

  function injectGear() {
    var headerInner = document.querySelector(".header-inner");
    if (!headerInner || document.getElementById("settingsGear")) return;
    var btn = document.createElement("button");
    btn.className = "gear-btn";
    btn.id = "settingsGear";
    btn.title = "Settings";
    btn.setAttribute("aria-label", "Settings");
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">' +
      '<circle cx="12" cy="12" r="3.2"/>' +
      '<path d="M19.4 13.5a7.6 7.6 0 0 0 0-3l2-1.5-2-3.5-2.4 1a7.6 7.6 0 0 0-2.6-1.5L14 2.5h-4l-.4 2.5a7.6 7.6 0 0 0-2.6 1.5l-2.4-1-2 3.5 2 1.5a7.6 7.6 0 0 0 0 3l-2 1.5 2 3.5 2.4-1a7.6 7.6 0 0 0 2.6 1.5l.4 2.5h4l.4-2.5a7.6 7.6 0 0 0 2.6-1.5l2.4 1 2-3.5-2-1.5Z"/></svg>';
    btn.addEventListener("click", open);
    var tools = document.createElement("div");
    tools.className = "header-tools";
    var link = headerInner.querySelector(".header-link");
    if (link) tools.appendChild(link);
    tools.appendChild(btn);
    headerInner.appendChild(tools);
  }

  document.addEventListener("DOMContentLoaded", injectGear);
})();
