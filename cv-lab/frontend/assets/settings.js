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
    renderVisGrid();
  }

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
    document.getElementById("settingsModal").hidden = false;
  }
  function close() {
    var m = document.getElementById("settingsModal");
    if (m) m.hidden = true;
  }

  function injectGear() {
    var headerInner = document.querySelector(".header-inner");
    if (!headerInner) return;
    var btn = document.createElement("button");
    btn.className = "gear-btn";
    btn.title = "Settings";
    btn.setAttribute("aria-label", "Settings");
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">' +
      '<circle cx="12" cy="12" r="3.2"/>' +
      '<path d="M19.4 13.5a7.6 7.6 0 0 0 0-3l2-1.5-2-3.5-2.4 1a7.6 7.6 0 0 0-2.6-1.5L14 2.5h-4l-.4 2.5a7.6 7.6 0 0 0-2.6 1.5l-2.4-1-2 3.5 2 1.5a7.6 7.6 0 0 0 0 3l-2 1.5 2 3.5 2.4-1a7.6 7.6 0 0 0 2.6 1.5l.4 2.5h4l.4-2.5a7.6 7.6 0 0 0 2.6-1.5l2.4 1 2-3.5-2-1.5Z"/></svg>';
    btn.addEventListener("click", open);
    headerInner.appendChild(btn);
  }

  document.addEventListener("DOMContentLoaded", injectGear);
})();
