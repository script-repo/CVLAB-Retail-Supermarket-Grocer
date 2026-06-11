/* REST + WebSocket client for the CV Live-Analysis backend.
   Same-origin by default; override with ?api=http://host:port */
(function () {
  "use strict";

  var params = new URLSearchParams(location.search);
  var API_BASE = params.get("api") || "";

  function wsUrl(path) {
    if (API_BASE) {
      return API_BASE.replace(/^http/, "ws") + path;
    }
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + path;
  }

  var API = {
    base: API_BASE,

    listUsecases: function () {
      return fetch(API_BASE + "/api/usecases").then(function (r) { return r.json(); });
    },

    listVideos: function () {
      return fetch(API_BASE + "/api/videos").then(function (r) { return r.json(); });
    },

    getGpu: function () {
      return fetch(API_BASE + "/api/gpu").then(function (r) { return r.json(); });
    },

    // NAI liveness probe — used by status badges. Reflects actual endpoint
    // reachability independent of how slow a given generation is.
    pingNai: function (signal) {
      return fetch(API_BASE + "/api/agent/ping", { signal: signal }).then(function (r) { return r.json(); });
    },

    // Ops dashboard: NAI 12h summary + recommendation. Optional AbortSignal lets
    // the caller enforce a client-side deadline (falls back to a placeholder).
    opsSummary: function (signal) {
      return fetch(API_BASE + "/api/agent/summary", { method: "POST", signal: signal })
        .then(function (r) { return r.json(); });
    },

    // Ops dashboard: free-form question answered by NAI over recent store context.
    opsAsk: function (question, signal) {
      return fetch(API_BASE + "/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question }),
        signal: signal
      }).then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("HTTP " + r.status)); });
        return r.json();
      });
    },

    deleteVideo: function (id) {
      return fetch(API_BASE + "/api/videos/" + id, { method: "DELETE" }).then(function (r) { return r.json(); });
    },

    thumbUrl: function (id) { return API_BASE + "/api/videos/" + id + "/thumb"; },

    rtspPreviewUrl: function (url) {
      return API_BASE + "/api/rtsp/preview?url=" + encodeURIComponent(url);
    },

    // Upload with progress via XHR.
    uploadVideo: function (file, onProgress) {
      return new Promise(function (resolve, reject) {
        var xhr = new XMLHttpRequest();
        xhr.open("POST", API_BASE + "/api/videos");
        xhr.upload.onprogress = function (e) {
          if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
        };
        xhr.onload = function () {
          if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
          else reject(new Error(xhr.responseText || ("HTTP " + xhr.status)));
        };
        xhr.onerror = function () { reject(new Error("Network error")); };
        var fd = new FormData();
        fd.append("file", file);
        xhr.send(fd);
      });
    },

    openStream: function () { return new WebSocket(wsUrl("/ws/analyze")); }
  };

  window.API = API;
})();
