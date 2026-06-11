/* Retail-Supermarket-Grocery CV Live-Analysis — UI logic.
   Flow: upload/select video -> pick use case -> (optional) draw zones / tune ->
   start WebSocket stream -> render annotated frames + live metrics. */
(function () {
  "use strict";

  // Client-side tunable schemas, keyed by use-case id.
  var PARAM_SCHEMA = {
    "uc-02": [
      { key: "threshold", label: "Out-of-stock threshold", min: 0.1, max: 0.9, step: 0.05, def: 0.5, pct: true }
    ],
    "uc-06": [
      { key: "queue_limit", label: "Open-lane threshold (people)", min: 1, max: 20, step: 1, def: 5 },
      { key: "service_time_s", label: "Service time / person (s)", min: 5, max: 90, step: 5, def: 25 },
      { key: "open_lanes", label: "Open lanes", min: 1, max: 8, step: 1, def: 1 }
    ],
    "uc-07": [
      { key: "opacity", label: "Heatmap opacity", min: 0.1, max: 0.9, step: 0.05, def: 0.55, pct: true },
      { key: "radius", label: "Heat radius (px)", min: 8, max: 60, step: 2, def: 24 }
    ],
    "uc-16": [
      { key: "diff_thresh", label: "Change sensitivity", min: 10, max: 90, step: 5, def: 35 },
      { key: "min_area_frac", label: "Min spill area (% of floor)", min: 0.002, max: 0.08, step: 0.002, def: 0.01, pct: true },
      { key: "persist_frames", label: "Persistence (frames)", min: 2, max: 40, step: 1, def: 12 }
    ]
  };

  var state = {
    videos: [],
    usecases: [],
    selectedVideo: null,
    selectedUsecase: null,
    zones: [],          // [{name, points:[[x,y],...]}] normalized
    drawing: [],        // current polygon points (normalized)
    ws: null,
    running: false,
    paused: false,
    lastUrl: null,
    // Frame source: "video" | "camera" | "rtsp"
    source: "video",
    cameraStream: null,
    cameraReady: false,
    captureTimer: null,
    rtspUrl: null,
    rtspReady: false
  };

  var $ = function (id) { return document.getElementById(id); };

  // ---------- per-use-case favorite source ----------
  // A "favorite" remembers the video (or RTSP/HTTP stream) for a use case so it
  // is auto-selected whenever that use case is picked — no re-selecting each time.
  function favKey(ucId) { return "cvlab-fav-" + ucId; }
  function getFav(ucId) {
    try { return JSON.parse(localStorage.getItem(favKey(ucId)) || "null"); } catch (e) { return null; }
  }
  function setFav(ucId, fav) {
    try {
      if (fav) localStorage.setItem(favKey(ucId), JSON.stringify(fav));
      else localStorage.removeItem(favKey(ucId));
    } catch (e) {}
  }
  function currentFav() { return state.selectedUsecase ? getFav(state.selectedUsecase.id) : null; }

  // ---------- per-use-case zones and tuning ----------
  function zonesKey(ucId) { return "cvlab-zones-" + ucId; }
  function paramsKey(ucId) { return "cvlab-params-" + ucId; }

  function validZone(z) {
    return z && Array.isArray(z.points) && z.points.length >= 3;
  }

  function loadZones(ucId) {
    try {
      var zones = JSON.parse(localStorage.getItem(zonesKey(ucId)) || "[]");
      return Array.isArray(zones) ? zones.filter(validZone) : [];
    } catch (e) {
      return [];
    }
  }

  function saveZonesForCurrent() {
    if (!state.selectedUsecase || !state.selectedUsecase.needs_zones) return;
    try { localStorage.setItem(zonesKey(state.selectedUsecase.id), JSON.stringify(state.zones)); } catch (e) {}
  }

  function clearZonesForCurrent() {
    if (!state.selectedUsecase) return;
    try { localStorage.removeItem(zonesKey(state.selectedUsecase.id)); } catch (e) {}
  }

  function loadParams(ucId) {
    try {
      var params = JSON.parse(localStorage.getItem(paramsKey(ucId)) || "{}");
      return params && typeof params === "object" ? params : {};
    } catch (e) {
      return {};
    }
  }

  function saveParamsForCurrent() {
    if (!state.selectedUsecase) return;
    try { localStorage.setItem(paramsKey(state.selectedUsecase.id), JSON.stringify(collectParams())); } catch (e) {}
  }

  function toggleFavVideo(id) {
    if (!state.selectedUsecase) { setStatus("Select a use case first to set a favorite.", true); return; }
    var uc = state.selectedUsecase.id, cur = getFav(uc);
    if (cur && cur.source === "video" && cur.videoId === id) {
      setFav(uc, null);
      setStatus("Removed favorite for " + uc.toUpperCase() + ".");
    } else {
      setFav(uc, { source: "video", videoId: id });
      setStatus("Favorite video set for " + uc.toUpperCase() + " — it loads automatically when selected.");
    }
    renderVideos();
  }

  function toggleFavRtsp() {
    if (!state.selectedUsecase) { setStatus("Select a use case first to set a favorite.", true); return; }
    var url = ($("rtspUrl").value || "").trim();
    if (!url) { setStatus("Enter a stream URL first.", true); return; }
    var uc = state.selectedUsecase.id, cur = getFav(uc);
    if (cur && cur.source === "rtsp" && cur.rtspUrl === url) {
      setFav(uc, null);
      setStatus("Removed favorite for " + uc.toUpperCase() + ".");
    } else {
      setFav(uc, { source: "rtsp", rtspUrl: url });
      setStatus("Favorite stream set for " + uc.toUpperCase() + " — it loads automatically when selected.");
    }
  }

  // Auto-apply the saved favorite (if any) for the selected use case.
  function applyFavorite() {
    if (state.running) return;
    var uc = state.selectedUsecase;
    if (!uc) return;
    var fav = getFav(uc.id);
    if (!fav) return;
    if (fav.source === "video") {
      var v = state.videos.find(function (x) { return x.id === fav.videoId; });
      if (v) {
        if (state.source !== "video") setSource("video");
        if (!state.selectedVideo || state.selectedVideo.id !== v.id) selectVideo(v);
        setStatus("Loaded favorite video for " + uc.id.toUpperCase() + ". Ready to start.");
      }
    } else if (fav.source === "rtsp" && fav.rtspUrl) {
      if (state.source !== "rtsp") setSource("rtsp");
      $("rtspUrl").value = fav.rtspUrl;
      connectRtsp();
    }
  }

  // ---------- bootstrap ----------
  function init() {
    Promise.all([API.listUsecases(), API.listVideos()])
      .then(function (res) {
        state.usecases = res[0].usecases || [];
        state.videos = (res[1].videos) || [];
        renderUsecases();
        renderVideos();
        applyDeepLink();
      })
      .catch(function (e) { setStatus("Backend unreachable: " + e.message, true); });

    $("fileInput").addEventListener("change", function (e) {
      if (e.target.files[0]) doUpload(e.target.files[0]);
    });
    setupDropzone();
    setupSourceControls();
    $("refreshVideos").addEventListener("click", reloadVideos);
    $("startBtn").addEventListener("click", start);
    $("pauseBtn").addEventListener("click", togglePause);
    $("stopBtn").addEventListener("click", stop);
    $("zoneFinish").addEventListener("click", function () { commitDrawing(); drawZoneOverlay(); });
    $("zoneUndo").addEventListener("click", undoPoint);
    $("zoneClear").addEventListener("click", clearZones);
    setupZoneDrawing();
    setupPanes();
    updateConfigPane();
    startGpuPolling();
    window.addEventListener("resize", drawZoneOverlay);
    document.addEventListener("cvlab-settings-changed", function () {
      renderUsecases();
      pollGpu();
    });
  }

  // ---------- GPU telemetry ----------
  var gpuTimer = null;

  function startGpuPolling() {
    pollGpu();
    if (gpuTimer) clearInterval(gpuTimer);
    gpuTimer = setInterval(function () {
      // Poll faster while a run is active, slower when idle.
      pollGpu();
    }, 2000);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) pollGpu();
    });
  }

  function pollGpu() {
    if (document.hidden) return;
    API.getGpu().then(renderGpu).catch(function () { renderGpuError(); });
  }

  function setBar(id, pct) {
    var bar = $(id);
    if (!bar) return;
    clearStackedBar(id);
    var p = Math.max(0, Math.min(100, pct || 0));
    bar.style.width = p + "%";
    bar.className = "meter-fill" + (p >= 85 ? " hot" : p >= 50 ? " warm" : "");
  }

  function renderGpu(d) {
    var badge = $("gpuBadge");
    var name = $("gpuName");
    var stats = $("gpuStats");
    if (!d || !d.available) {
      badge.textContent = "CPU";
      badge.className = "gpu-badge cpu";
      name.textContent = d && d.device ? "Running on " + d.device + " (no GPU detected)" : "No GPU detected — CPU mode";
      $("gpuUtilVal").textContent = "—"; setBar("gpuUtilBar", 0);
      $("gpuMemVal").textContent = "—"; setBar("gpuMemBar", 0);
      stats.innerHTML = "";
      return;
    }
    var g = d.gpu || {};
    badge.textContent = d.in_use ? "Active" : "Idle";
    badge.className = "gpu-badge " + (d.in_use ? "active" : "idle");
    name.textContent = (g.name || "GPU") + "  ·  " + (d.device || "");

    var util = g.util_pct != null ? g.util_pct : 0;
    $("gpuUtilVal").textContent = g.util_pct != null ? Math.round(g.util_pct) + "%" : "—";
    if (window.CVSettings && CVSettings.get().advancedGpu && d.streams && d.streams.length) {
      setStackedBar("gpuUtilBar", util, d.streams);
    } else {
      setBar("gpuUtilBar", util);
    }

    var memPct = g.mem_pct != null ? g.mem_pct : 0;
    var memTxt = (g.mem_used_mb != null && g.mem_total_mb != null)
      ? fmtGb(g.mem_used_mb) + " / " + fmtGb(g.mem_total_mb)
      : "—";
    $("gpuMemVal").textContent = memTxt;
    setBar("gpuMemBar", memPct);

    stats.innerHTML = "";
    if (g.temp_c != null) addGpuStat(stats, "Temp", Math.round(g.temp_c) + "°C");
    if (g.power_w != null) {
      var pw = Math.round(g.power_w) + (g.power_cap_w != null ? " / " + Math.round(g.power_cap_w) + " W" : " W");
      addGpuStat(stats, "Power", pw);
    }
  }

  // Per-use-case palette for the stacked utilization bar (brand-adjacent hues).
  var STACK_COLORS = ["#3EB36C", "#EF9300", "#00A0D6", "#8b5cf6", "#D44325",
                      "#14b8a6", "#f59e0b", "#3b82f6", "#10b981", "#ef4444"];

  function stackColor(usecase) {
    var n = parseInt(usecase.replace(/\D/g, ""), 10) || 0;
    return STACK_COLORS[n % STACK_COLORS.length];
  }

  // Advanced mode: one segment per active use case. Total width = measured GPU
  // utilization; each segment's width = that use case's share of processing
  // time (the driver can't attribute utilization per use case directly).
  function setStackedBar(id, utilPct, streams) {
    var bar = $(id);
    if (!bar) return;
    var meter = bar.parentElement;
    bar.style.width = "0%";
    bar.className = "meter-fill";
    var old = meter.querySelector(".meter-stack");
    if (old) old.remove();
    var stack = document.createElement("div");
    stack.className = "meter-stack";
    var total = Math.max(0, Math.min(100, utilPct || 0));
    // CPU-only / idle GPU: show shares across the full meter instead.
    if (total < 1) total = 100;
    streams.forEach(function (s) {
      var seg = document.createElement("div");
      seg.className = "meter-seg";
      seg.style.width = (total * s.share_pct / 100) + "%";
      seg.style.background = stackColor(s.usecase);
      seg.title = s.title + "\n" + s.share_pct + "% of inference time · " +
        s.ms_per_frame + " ms/frame · " + s.fps + " fps";
      stack.appendChild(seg);
    });
    meter.appendChild(stack);
  }

  function clearStackedBar(id) {
    var bar = $(id);
    if (!bar) return;
    var old = bar.parentElement.querySelector(".meter-stack");
    if (old) old.remove();
  }

  function renderGpuError() {
    var badge = $("gpuBadge");
    badge.textContent = "—";
    badge.className = "gpu-badge cpu";
    $("gpuName").textContent = "GPU status unavailable";
  }

  function addGpuStat(host, label, value) {
    var li = document.createElement("li");
    li.innerHTML = '<span>' + escapeHtml(label) + '</span><b>' + escapeHtml(value) + '</b>';
    host.appendChild(li);
  }

  function fmtGb(mb) { return (mb / 1024).toFixed(1) + " GB"; }

  // ---------- collapsible side panes ----------
  function setupPanes() {
    $("toggleUsecases").addEventListener("click", function () { togglePane("usecasesPane", this); });
    $("toggleConfig").addEventListener("click", function () { togglePane("configPane", this); });
    // Clicking the vertical tab of a collapsed pane re-expands it.
    document.querySelectorAll(".pane-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        var pane = tab.closest(".pane");
        if (pane && pane.classList.contains("is-collapsed")) {
          setCollapsed(pane, false, pane.querySelector(".pane-toggle"));
        }
      });
    });
  }

  function togglePane(paneId, btn) {
    var pane = $(paneId);
    setCollapsed(pane, !pane.classList.contains("is-collapsed"), btn);
  }

  function setCollapsed(pane, collapsed, btn) {
    pane.classList.toggle("is-collapsed", collapsed);
    if (btn) {
      var left = pane.id === "usecasesPane";
      btn.innerHTML = collapsed ? (left ? "&raquo;" : "&laquo;") : (left ? "&laquo;" : "&raquo;");
      btn.title = collapsed ? "Expand panel" : "Collapse panel";
    }
    // Center width changed; resync the overlay canvas after the transition.
    setTimeout(function () { syncCanvasSize(); drawZoneOverlay(); }, 220);
  }

  // Show zones/tuning when relevant; otherwise a placeholder. Auto-expand if collapsed.
  function updateConfigPane() {
    var hasZones = !!(state.selectedUsecase && state.selectedUsecase.needs_zones);
    var hasParams = !$("paramBlock").hidden;
    var empty = $("configEmpty");
    if (empty) empty.hidden = hasZones || hasParams;
    if (hasZones || hasParams) {
      var pane = $("configPane");
      if (pane.classList.contains("is-collapsed")) setCollapsed(pane, false, $("toggleConfig"));
    }
  }

  function applyDeepLink() {
    var uc = new URLSearchParams(location.search).get("usecase");
    if (uc) {
      var match = state.usecases.find(function (u) { return u.id === uc; });
      if (match) selectUsecase(match);
    }
  }

  // ---------- upload ----------
  function setupDropzone() {
    var drop = $("drop");
    ["dragover", "dragenter"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("over"); });
    });
    drop.addEventListener("drop", function (e) {
      var f = e.dataTransfer.files[0];
      if (f) doUpload(f);
    });
  }

  function doUpload(file) {
    var prog = $("uploadProgress");
    var bar = prog.querySelector(".bar");
    prog.hidden = false; bar.style.width = "0%";
    $("dropText").textContent = "Uploading " + file.name + "…";
    API.uploadVideo(file, function (f) { bar.style.width = Math.round(f * 100) + "%"; })
      .then(function (meta) {
        $("dropText").textContent = "Click or drop a video to upload";
        prog.hidden = true;
        return reloadVideos().then(function () { selectVideo(meta); });
      })
      .catch(function (e) {
        prog.hidden = true;
        $("dropText").textContent = "Click or drop a video to upload";
        setStatus("Upload failed: " + e.message, true);
      });
  }

  function reloadVideos() {
    return API.listVideos().then(function (res) {
      state.videos = res.videos || [];
      renderVideos();
    });
  }

  // ---------- source selection (video / camera / rtsp) ----------
  function setupSourceControls() {
    document.querySelectorAll("#sourceToggle .src-btn").forEach(function (btn) {
      btn.addEventListener("click", function () { setSource(btn.getAttribute("data-source")); });
    });
    $("cameraEnable").addEventListener("click", enableCamera);
    $("rtspConnect").addEventListener("click", connectRtsp);
    $("rtspFav").addEventListener("click", toggleFavRtsp);
    $("rtspUrl").addEventListener("keydown", function (e) { if (e.key === "Enter") connectRtsp(); });
  }

  function setSource(src) {
    if (state.running) return;            // don't switch mid-run
    state.source = src;
    document.querySelectorAll("#sourceToggle .src-btn").forEach(function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-source") === src);
    });
    $("srcVideo").hidden = src !== "video";
    $("srcCamera").hidden = src !== "camera";
    $("srcRtsp").hidden = src !== "rtsp";
    // Release the camera when leaving camera mode.
    if (src !== "camera") stopCameraStream();
    updateStartEnabled();
    if (src === "camera") listCameras();
  }

  // --- camera ---
  function listCameras() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    navigator.mediaDevices.enumerateDevices().then(function (devs) {
      var sel = $("cameraSelect");
      var current = sel.value;
      sel.innerHTML = '<option value="">Default camera</option>';
      devs.filter(function (d) { return d.kind === "videoinput"; }).forEach(function (d, i) {
        var opt = document.createElement("option");
        opt.value = d.deviceId;
        opt.textContent = d.label || ("Camera " + (i + 1));
        sel.appendChild(opt);
      });
      sel.value = current;
    });
  }

  function enableCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("Camera not supported in this browser.", true);
      return;
    }
    stopCameraStream();
    var deviceId = $("cameraSelect").value;
    var constraints = { video: deviceId ? { deviceId: { exact: deviceId } } : true, audio: false };
    setStatus("Requesting camera…");
    navigator.mediaDevices.getUserMedia(constraints).then(function (stream) {
      state.cameraStream = stream;
      var video = $("cameraPreview");
      video.srcObject = stream;
      video.play().catch(function () {});
      video.onloadedmetadata = function () {
        var w = video.videoWidth, h = video.videoHeight;
        if (w && h) $("stage").style.aspectRatio = w + " / " + h;
        freezeCameraFrame();
        state.cameraReady = true;
        state.drawing = []; renderZoneChips();
        updateStartEnabled();
        setStatus("Camera ready. Pick a use case" + (needsZones() ? ", draw zones," : "") + " then Start.");
      };
      listCameras();   // labels become available after permission is granted
    }).catch(function (e) {
      setStatus("Camera access denied: " + e.message, true);
    });
  }

  // Paint the current camera frame into the stage <img> so zones can be drawn.
  function freezeCameraFrame() {
    var video = $("cameraPreview");
    var w = video.videoWidth, h = video.videoHeight;
    if (!w || !h) return;
    var c = document.createElement("canvas");
    c.width = w; c.height = h;
    c.getContext("2d").drawImage(video, 0, 0, w, h);
    var img = $("frame");
    img.src = c.toDataURL("image/jpeg", 0.8);
    img.onload = drawZoneOverlay;
  }

  function stopCameraStream() {
    stopCameraCapture();
    if (state.cameraStream) {
      state.cameraStream.getTracks().forEach(function (t) { t.stop(); });
      state.cameraStream = null;
    }
    state.cameraReady = false;
  }

  function startCameraCapture() {
    stopCameraCapture();
    var video = $("cameraPreview");
    var canvas = document.createElement("canvas");
    var fpsTarget = 12;
    state.captureTimer = setInterval(function () {
      if (!state.running || state.paused) return;
      if (!state.ws || state.ws.readyState !== 1) return;
      var w = video.videoWidth, h = video.videoHeight;
      if (!w || !h) return;
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(video, 0, 0, w, h);
      canvas.toBlob(function (blob) {
        if (!blob || !state.ws || state.ws.readyState !== 1) return;
        blob.arrayBuffer().then(function (buf) {
          if (state.ws && state.ws.readyState === 1) state.ws.send(buf);
        });
      }, "image/jpeg", 0.7);
    }, 1000 / fpsTarget);
  }

  function stopCameraCapture() {
    if (state.captureTimer) { clearInterval(state.captureTimer); state.captureTimer = null; }
  }

  // --- network stream ---
  function connectRtsp() {
    var url = ($("rtspUrl").value || "").trim();
    if (!/^(rtsp|rtsps|http|https):\/\//i.test(url)) {
      setStatus("Enter a valid stream URL: rtsp://, rtsps://, http://, or https://.", true);
      return;
    }
    state.rtspUrl = url;
    state.rtspReady = false;
    setStatus("Connecting to network stream...");
    var img = $("frame");
    img.onload = function () {
      if (img.naturalWidth && img.naturalHeight) {
        $("stage").style.aspectRatio = img.naturalWidth + " / " + img.naturalHeight;
      }
      state.rtspReady = true;
      state.drawing = []; renderZoneChips();
      drawZoneOverlay();
      updateStartEnabled();
      setStatus("Network stream connected. Pick a use case" + (needsZones() ? ", draw zones," : "") + " then Start.");
    };
    img.onerror = function () {
      state.rtspReady = false;
      updateStartEnabled();
      setStatus("Could not reach the network stream (unreachable or invalid URL).", true);
    };
    img.src = API.rtspPreviewUrl(url) + "&t=" + Date.now();
  }

  function needsZones() {
    return !!(state.selectedUsecase && state.selectedUsecase.needs_zones);
  }

  // ---------- video list ----------
  function renderVideos() {
    var host = $("savedList");
    host.innerHTML = "";
    if (!state.videos.length) {
      host.innerHTML = '<p class="muted">No videos yet.</p>';
      return;
    }
    var fav = currentFav();
    state.videos.forEach(function (v) {
      var item = document.createElement("div");
      item.className = "saved-item" + (state.selectedVideo && state.selectedVideo.id === v.id ? " is-active" : "");
      var dur = v.duration_s ? v.duration_s.toFixed(0) + "s" : "";
      var isFav = !!(fav && fav.source === "video" && fav.videoId === v.id);
      var favTitle = state.selectedUsecase
        ? (isFav ? "Favorite for " + state.selectedUsecase.id.toUpperCase() + " (click to clear)"
                 : "Set as favorite for " + state.selectedUsecase.id.toUpperCase())
        : "Select a use case to set a favorite";
      item.innerHTML =
        '<img src="' + API.thumbUrl(v.id) + '" alt="" onerror="this.style.visibility=\'hidden\'"/>' +
        '<div class="meta"><strong>' + escapeHtml(v.filename) + '</strong>' +
        '<span>' + v.width + '×' + v.height + ' · ' + dur + '</span></div>' +
        '<div class="saved-actions">' +
          '<button class="fav' + (isFav ? " is-fav" : "") + '" title="' + favTitle + '" data-fav="' + v.id + '">' +
            (isFav ? "\u2605" : "\u2606") + '</button>' +
          '<button class="del" title="Delete" data-id="' + v.id + '">&times;</button>' +
        '</div>';
      item.addEventListener("click", function (e) {
        if (e.target.classList.contains("fav")) { e.stopPropagation(); toggleFavVideo(v.id); return; }
        if (e.target.classList.contains("del")) { e.stopPropagation(); doDelete(v.id); return; }
        selectVideo(v);
      });
      host.appendChild(item);
    });
  }

  function doDelete(id) {
    API.deleteVideo(id).then(function () {
      if (state.selectedVideo && state.selectedVideo.id === id) state.selectedVideo = null;
      reloadVideos();
      updateStartEnabled();
    });
  }

  function selectVideo(v) {
    state.selectedVideo = v;
    state.drawing = [];
    renderVideos();
    // Match the stage to the video's real aspect ratio so the overlay canvas maps
    // 1:1 to the frame the backend analyzes (otherwise letterboxing offsets zones).
    if (v.width && v.height) {
      $("stage").style.aspectRatio = v.width + " / " + v.height;
    }
    // Show thumbnail in the stage for zone drawing.
    var img = $("frame");
    img.src = API.thumbUrl(v.id);
    img.onload = drawZoneOverlay;
    renderZoneChips();
    updateStartEnabled();
    setStatus("Loaded " + v.filename + ". Pick a use case.");
  }

  // ---------- use cases ----------
  function renderUsecases() {
    var host = $("usecaseList");
    host.innerHTML = "";
    var visible = state.usecases.filter(function (u) {
      return !(window.CVSettings && CVSettings.isHidden(u.id));
    });
    visible.forEach(function (u) {
      var b = document.createElement("button");
      b.className = "usecase" + (state.selectedUsecase && state.selectedUsecase.id === u.id ? " is-active" : "");
      b.innerHTML = '<span class="uc-id">' + u.id.toUpperCase() + '</span>' +
        '<span class="uc-title">' + escapeHtml(u.title) + '</span>' +
        (u.needs_zones ? '<span class="uc-tag">zones</span>' : '');
      b.addEventListener("click", function () { selectUsecase(u); });
      host.appendChild(b);
    });
  }

  function selectUsecase(u) {
    state.selectedUsecase = u;
    state.zones = u.needs_zones ? loadZones(u.id) : [];
    state.drawing = [];
    renderUsecases();
    $("zoneBlock").hidden = !u.needs_zones;
    renderZoneChips();
    renderParams();
    updateConfigPane();
    renderVideos();      // refresh favorite stars for this use case
    applyFavorite();     // auto-load the saved favorite source, if any
    updateStartEnabled();
  }

  // ---------- params ----------
  function renderParams() {
    var schema = PARAM_SCHEMA[state.selectedUsecase.id] || [];
    var saved = loadParams(state.selectedUsecase.id);
    var block = $("paramBlock");
    var host = $("params");
    host.innerHTML = "";
    block.hidden = schema.length === 0;
    schema.forEach(function (p) {
      var row = document.createElement("div");
      row.className = "param";
      var val = typeof saved[p.key] === "number" ? saved[p.key] : p.def;
      var valLabel = p.pct ? Math.round(val * 100) + "%" : val;
      row.innerHTML =
        '<label>' + p.label + ' <b id="pv-' + p.key + '">' + valLabel + '</b></label>' +
        '<input type="range" id="pp-' + p.key + '" min="' + p.min + '" max="' + p.max +
        '" step="' + p.step + '" value="' + val + '"/>';
      host.appendChild(row);
      var input = row.querySelector("input");
      input.addEventListener("input", function () {
        var v = parseFloat(input.value);
        $("pv-" + p.key).textContent = p.pct ? Math.round(v * 100) + "%" : v;
        saveParamsForCurrent();
        if (state.running) sendControl({ action: "config", params: collectParams() });
      });
    });
  }

  function collectParams() {
    var schema = PARAM_SCHEMA[state.selectedUsecase.id] || [];
    var out = {};
    schema.forEach(function (p) {
      var el = $("pp-" + p.key);
      if (el) out[p.key] = parseFloat(el.value);
    });
    return out;
  }

  // ---------- zone drawing ----------
  function setupZoneDrawing() {
    var canvas = $("overlay");
    canvas.addEventListener("click", function (e) {
      if (!state.selectedUsecase || !state.selectedUsecase.needs_zones || state.running) return;
      var rect = canvas.getBoundingClientRect();
      var x = (e.clientX - rect.left) / rect.width;
      var y = (e.clientY - rect.top) / rect.height;
      state.drawing.push([clamp01(x), clamp01(y)]);
      drawZoneOverlay();
    });
    canvas.addEventListener("dblclick", function () {
      commitDrawing();
      drawZoneOverlay();
    });
  }

  // Close the in-progress polygon into a saved zone (needs >= 3 points).
  function commitDrawing() {
    var added = false;
    if (state.drawing.length >= 3) {
      state.zones.push({ name: "Zone " + (state.zones.length + 1), points: state.drawing.slice() });
      added = true;
    }
    state.drawing = [];
    renderZoneChips();
    if (added) saveZonesForCurrent();
  }

  function undoPoint() {
    var changedZones = false;
    if (state.drawing.length) state.drawing.pop();
    else if (state.zones.length) { state.zones.pop(); changedZones = true; }
    renderZoneChips();
    if (changedZones) saveZonesForCurrent();
    drawZoneOverlay();
  }

  function clearZones() {
    state.zones = []; state.drawing = [];
    clearZonesForCurrent();
    renderZoneChips();
    drawZoneOverlay();
  }

  function renderZoneChips() {
    var host = $("zoneChips");
    host.innerHTML = "";
    state.zones.forEach(function (z, i) {
      var li = document.createElement("li");
      li.textContent = z.name + " (" + z.points.length + ")";
      host.appendChild(li);
    });
  }

  function syncCanvasSize() {
    var img = $("frame");
    var canvas = $("overlay");
    var w = img.clientWidth || img.naturalWidth;
    var h = img.clientHeight || img.naturalHeight;
    if (w && h) { canvas.width = w; canvas.height = h; }
  }

  function drawZoneOverlay() {
    var canvas = $("overlay");
    if (state.running) { canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height); return; }
    syncCanvasSize();
    var ctx = canvas.getContext("2d");
    var W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    function poly(points, closed, color) {
      if (!points.length) return;
      ctx.beginPath();
      points.forEach(function (p, i) {
        var x = p[0] * W, y = p[1] * H;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      if (closed) ctx.closePath();
      ctx.fillStyle = color + "22";
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      if (closed) ctx.fill();
      ctx.stroke();
      points.forEach(function (p) {
        ctx.beginPath(); ctx.arc(p[0] * W, p[1] * H, 4, 0, 7); ctx.fillStyle = color; ctx.fill();
      });
    }
    state.zones.forEach(function (z) { poly(z.points, true, "#003D2A"); });
    poly(state.drawing, false, "#EF9300");
  }

  // ---------- run / stream ----------
  function sourceReady() {
    if (state.source === "video") return !!state.selectedVideo;
    if (state.source === "camera") return state.cameraReady;
    if (state.source === "rtsp") return state.rtspReady;
    return false;
  }

  function updateStartEnabled() {
    $("startBtn").disabled = !(state.selectedUsecase && sourceReady()) || state.running;
  }

  function start() {
    if (!state.selectedUsecase || !sourceReady()) return;
    // Auto-commit an in-progress polygon so a half-drawn zone still takes effect.
    commitDrawing();
    var ws = API.openStream();
    ws.binaryType = "arraybuffer";
    state.ws = ws;

    ws.onopen = function () {
      var config = {
        usecase: state.selectedUsecase.id,
        source: state.source,
        zones: state.zones,
        params: collectParams(),
        loop: true
      };
      if (state.source === "video") {
        config.video_id = state.selectedVideo.id;
        try { localStorage.setItem("cvlab-lastvideo-" + config.usecase, config.video_id); } catch (e) {}
      } else if (state.source === "rtsp") {
        config.rtsp_url = state.rtspUrl;
      }
      ws.send(JSON.stringify({ action: "start", config: config }));
      // Camera: begin pushing frames once the start message is sent.
      if (state.source === "camera") startCameraCapture();
    };

    ws.onmessage = function (ev) {
      if (typeof ev.data !== "string") { renderFrame(ev.data); return; }
      var msg = JSON.parse(ev.data);
      handleMessage(msg);
    };

    ws.onclose = function () { if (state.running) endRun("Stream closed."); };
    ws.onerror = function () { setStatus("WebSocket error.", true); };

    state.running = true; state.paused = false;
    $("overlay").getContext("2d").clearRect(0, 0, $("overlay").width, $("overlay").height);
    $("startBtn").disabled = true;
    $("pauseBtn").disabled = false; $("pauseBtn").textContent = "Pause";
    $("stopBtn").disabled = false;
    setStatus("Analyzing…");
  }

  function handleMessage(msg) {
    if (msg.type === "metrics") renderMetrics(msg);
    else if (msg.type === "error") { setStatus("Error: " + msg.message, true); endRun(); }
    else if (msg.type === "started") setStatus("Streaming " + msg.usecase.toUpperCase() + "…");
  }

  function renderFrame(buffer) {
    var blob = new Blob([buffer], { type: "image/jpeg" });
    var url = URL.createObjectURL(blob);
    var img = $("frame");
    img.src = url;
    if (state.lastUrl) URL.revokeObjectURL(state.lastUrl);
    state.lastUrl = url;
  }

  function renderMetrics(m) {
    var head = $("metricHeadline");
    head.textContent = m.headline || "";
    head.className = "metric-headline" + (m.status === "alert" ? " alert" : "");
    var grid = $("metricGrid");
    grid.innerHTML = "";
    addMetric(grid, "Frame", m.frame_index);
    addMetric(grid, "Time", (m.timestamp_s != null ? m.timestamp_s + "s" : "—"));
    var values = m.values || {};
    Object.keys(values).forEach(function (k) {
      var v = values[k];
      if (v && typeof v === "object") v = JSON.stringify(v);
      addMetric(grid, prettyKey(k), v);
    });
  }

  function addMetric(grid, label, value) {
    var cell = document.createElement("div");
    cell.className = "metric-cell";
    cell.innerHTML = '<span class="m-label">' + escapeHtml(String(label)) + '</span>' +
      '<span class="m-value">' + escapeHtml(String(value)) + '</span>';
    grid.appendChild(cell);
  }

  function togglePause() {
    if (!state.running) return;
    state.paused = !state.paused;
    sendControl({ action: state.paused ? "pause" : "resume" });
    $("pauseBtn").textContent = state.paused ? "Resume" : "Pause";
    setStatus(state.paused ? "Paused." : "Analyzing…");
  }

  function stop() {
    sendControl({ action: "stop" });
    endRun("Stopped.");
  }

  function endRun(msg) {
    state.running = false; state.paused = false;
    stopCameraCapture();   // stop pushing camera frames (keep the stream for restart)
    if (state.ws) { try { state.ws.close(); } catch (e) {} state.ws = null; }
    $("pauseBtn").disabled = true; $("stopBtn").disabled = true;
    updateStartEnabled();
    if (msg) setStatus(msg);
    drawZoneOverlay();
  }

  function sendControl(obj) {
    if (state.ws && state.ws.readyState === 1) state.ws.send(JSON.stringify(obj));
  }

  // ---------- utils ----------
  function setStatus(text, isError) {
    var s = $("status");
    s.textContent = text;
    s.classList.toggle("error", !!isError);
  }
  function clamp01(v) { return Math.max(0, Math.min(1, v)); }
  function prettyKey(k) { return k.replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); }); }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c];
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
