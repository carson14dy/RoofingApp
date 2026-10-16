/* Montana Hail Watch: the interactive map (map.html).

   Why this is JavaScript (AGENTS.md rule 4): only the browser can run a playback timer, follow a
   finger along the timeline, open menus and sheets, and ask for the viewer's location. Python builds
   everything else at each build (website/build.py, website/gridded.py, tools/build_basemap.py):
   every radar and model picture, every number, the legends, the basemap and data/map.json. This file
   only places those finished pieces with Leaflet 1.9.4 (served from static/leaflet) and plays them.

   - Vanilla JavaScript: no framework, no build step, no request to anything but this site's files.
   - Evidence honesty: before "Now" a frame is NOAA's radar estimate, after it the HRRR model; the
     timeline title and subtitle always say which. Town numbers are the NWS hourly forecast. Missing
     data is said in words and never drawn as a clear sky.
   - The viewer's location never leaves the browser: it draws the dot and finds the nearest town.
*/
(function () {
  "use strict";

  // ------------------------------------------------------------------ settings and page state
  var STEP_MS = 700;                 // per frame while playing
  var HOLD_MS = 1500;                // pause on "Now" and on the last frame
  var STALE_MIN = 25;                // the site rebuilds every 10 minutes; older than this, say so
  var TZ = "America/Denver";         // every time on the map is Montana time
  var MIN = 60000, HOUR = 3600000;
  var BLANK = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
  var FALLBACK_VIEW = { bounds: [[44.35, -116.06], [49.01, -104.03]], min_zoom: 5, max_zoom: 11 };
  var KIND_WORD = { warning: "Warning", watch: "Watch", advisory: "Advisory", statement: "Statement" };
  var LAYER_WORD = { precip: "Precipitation", temp: "Temperature", wind: "Wind gusts" };

  var app = document.getElementById("app");
  var params = new URLSearchParams(location.search);
  var CARD = params.get("card") === "1";
  var motionQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var builtMs = Number(document.body.getAttribute("data-built")) || 0;
  var limits = readJSON(app.getAttribute("data-limits")) || {};

  var el = {
    banners: byId("banners"), legendTitle: byId("legend-title"), legendScale: byId("legend-scale"),
    legendBar: byId("legend-bar"), legendStops: byId("legend-stops"), legendNote: byId("legend-note"),
    legendKeys: byId("legend-keys"), layersBtn: byId("btn-layers"), locateBtn: byId("btn-locate"),
    listBtn: byId("btn-list"), layers: byId("layers"), warnings: byId("tg-warnings"), reports: byId("tg-reports"),
    note: byId("frame-note"), toast: byId("toast"), near: byId("near-chip"), timeline: byId("timeline"),
    play: byId("play"), title: byId("tl-title"), sub: byId("tl-sub"), seg: byId("seg"), scrub: byId("scrub"),
    range: byId("range"), fill: byId("fill-bar"), knob: byId("knob"), ticks: byId("ticks"), labels: byId("labels"),
    cardChip: byId("card-chip"), cardOpen: byId("card-open"), scrim: byId("scrim"), sheet: byId("sheet"),
    sheetTitle: byId("sheet-title"), sheetBody: byId("sheet-body"), sheetBack: byId("sheet-back"),
    sheetClose: byId("sheet-close"), top: byId("top"), bottom: byId("bottom"), canvas: byId("map"),
    cardUi: byId("card-ui"), legend: byId("legend"), legendInfo: byId("legend-info"),
    legendWrap: document.querySelector(".legend-wrap"), buttons: byId("buttons")
  };
  var whenEl = el.sub.querySelector(".tl-when");
  var srcEl = el.sub.querySelector(".tl-src");

  var data = null;                   // data/map.json
  var map = null;                    // the Leaflet map
  var state = {
    layer: "precip", mode: "12h", frames: [], times: [], pos: 0, nowPos: 0,
    playing: false, timer: null, resumeOnShow: false, dragging: false,
    warnings: true, reports: params.get("overlay") === "reports", goToken: 0, userMoved: false
  };
  var overlays = [], front = 0, swapToken = 0;   // two image overlays, crossfaded
  var cache = {};                                // picture src -> {ok: null|true|false, cbs: []}
  var preloaded = {};                            // layer key -> true once its frames are queued
  var renderers = {};
  var alertLayer = null, reportLayer = null, locLayer = null;
  var sheetState = null;                         // {opener, kind, listScroll, listFocus}
  var toastTimer = null;

  // ------------------------------------------------------------------ small helpers

  /** Element by id. */
  function byId(id) { return document.getElementById(id); }

  /** JSON.parse that returns null instead of throwing. */
  function readJSON(text) { try { return JSON.parse(text); } catch (e) { return null; } }

  /** Text made safe to put inside HTML. */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** Keep a number inside [lo, hi]. */
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  /** True when the viewer asked the system for less motion (checked live: it can change). */
  function reducedMotion() { return !!(motionQuery && motionQuery.matches); }

  /** fetch() a JSON file from this site; rejects with a plain reason. */
  function fetchJSON(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  // ------------------------------------------------------------------ Montana time, in the site's words

  var dtf = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "long", hour: "numeric", minute: "2-digit", hour12: true });
  var dtfDay = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric" });

  /** {weekday, hour, minute, dayPeriod} of an instant in Montana time. */
  function parts(ms) {
    var o = {};
    dtf.formatToParts(new Date(ms)).forEach(function (p) { o[p.type] = p.value; });
    return o;
  }

  /** "4:56 pm", or "7 pm" on the hour (lowercase am/pm, like the rest of the site). */
  function clock(ms) {
    var p = parts(ms), ap = (p.dayPeriod || "").toLowerCase();
    return (p.minute === "00" ? p.hour : p.hour + ":" + p.minute) + "\u00a0" + ap;
  }

  /** "Thursday 4:56 pm". */
  function dayClock(ms) { return parts(ms).weekday + " " + clock(ms); }

  /** "Thu Oct 15, 4:56 pm" for reports and alerts, which can be days away. */
  function dateClock(ms) { return dtfDay.format(new Date(ms)).replace(",", "") + ", " + clock(ms); }

  // ------------------------------------------------------------------ start-up

  /** Load the two data files, then build the map. The age banner does not wait for them. */
  function boot() {
    if (CARD) document.documentElement.classList.add("is-card");
    checkAge();
    setInterval(checkAge, MIN);
    whenEl.textContent = "Loading the map";
    el.play.disabled = true;
    el.range.disabled = true;
    var gotData = fetchJSON(app.getAttribute("data-map")).then(null, function (e) { return { _error: e.message || "it didn't load" }; });
    var gotBase = fetchJSON(app.getAttribute("data-basemap")).then(null, function (e) { return { _error: e.message || "it didn't load" }; });
    Promise.all([gotData, gotBase]).then(function (res) { start(res[0], res[1]); });
  }

  /** Build everything once the data files have answered (either may have failed). */
  function start(mapData, basemap) {
    var ok = mapData && !mapData._error && mapData.layers;
    data = ok ? mapData : null;
    createMap(ok && mapData.view ? mapData.view : FALLBACK_VIEW, ok ? mapData.image_bounds : null);
    if (basemap && !basemap._error) drawBasemap(basemap);
    else banner("warn", "<strong>The map outlines didn't load</strong> (" + esc(basemap && basemap._error) + "). The weather and towns still show.");
    if (!ok) {
      banner("warn", "<strong>The map data didn't load</strong> (" + esc(mapData && mapData._error) + "). No radar, forecast or warnings are shown. " +
        "This is not an all-clear. <a href=\"index.html\" target=\"_top\">See the Now page</a> or reload.");
      whenEl.textContent = "Map data unavailable";
      srcEl.textContent = "";
      el.title.textContent = "No data";
      app.classList.add("no-data");      // CSS hides the legend scale and the controls that need data
      return;
    }
    noteLastKnownAlerts();
    drawOutsideMask();
    drawTowns();
    drawAlerts();
    drawReports();
    paintSwatches();
    wireControls();
    var want = params.get("layer");
    var mode = params.get("mode");
    if (mode === "1h" || mode === "12h") state.mode = mode;
    el.warnings.checked = state.warnings;
    el.reports.checked = state.reports;
    setReports(state.reports, true);
    setLayer(want && data.layers[want] ? want : "precip", { atNow: true, first: true });
    fitView();
    fitMinZoom();
    if (CARD) setupCard();
    var town = params.get("town");
    if (town && !CARD) {
      var t = findTown(town);
      if (t) {
        state.userMoved = true;
        map.setView([t.lat, t.lon], Math.max(map.getZoom(), 7.5), { animate: false });
        openTown(t, t._el);
      }
    }
  }

  /** The Leaflet map: no tiles (Python drew the basemap), one pane per kind of thing. */
  function createMap(view, imageBounds) {
    var interactive = !CARD;
    map = L.map(el.canvas, {
      zoomControl: false, attributionControl: false, zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 110,
      minZoom: view.min_zoom || 5, maxZoom: view.max_zoom || 11, keyboard: interactive, dragging: interactive,
      touchZoom: interactive, scrollWheelZoom: interactive, doubleClickZoom: interactive, boxZoom: interactive,
      tap: false, maxBoundsViscosity: 0.9, fadeAnimation: !reducedMotion(), zoomAnimation: !reducedMotion(),
      markerZoomAnimation: !reducedMotion()
    });
    pane("frames", 410, false);
    pane("mask", 415, false);
    pane("alerts", 430, true);
    pane("reports", 440, true);
    pane("labels", 450, false);
    pane("loc", 620, false);
    renderers.base = L.svg({ padding: 0.6 });
    renderers.mask = L.svg({ pane: "mask", padding: 0.6 });
    renderers.alerts = L.svg({ pane: "alerts", padding: 0.6 });
    renderers.reports = L.svg({ pane: "reports", padding: 0.6 });
    renderers.loc = L.svg({ pane: "loc", padding: 0.6 });
    map._viewBounds = L.latLngBounds(view.bounds);
    map.fitBounds(map._viewBounds, { padding: [8, 8], animate: false });
    if (imageBounds) {
      var ib = L.latLngBounds(imageBounds);
      // Generous on purpose: Leaflet centres a box smaller than the screen, which would undo the
      // fit that keeps Montana clear of the legend and the timeline on a tall phone.
      map.setMaxBounds(L.latLngBounds([ib.getSouth() - 16, ib.getWest() - 14], [ib.getNorth() + 16, ib.getEast() + 14]));
      map._imageBounds = ib;
      for (var i = 0; i < 2; i++) {
        overlays.push(L.imageOverlay(BLANK, ib, { pane: "frames", opacity: 0, className: "frame", interactive: false }).addTo(map));
      }
      fitMinZoom();
    }
    map.on("zoomend", zoomClasses);
    map.on("moveend", function () { renderKeys(); });
    map.on("dragstart", function () { state.userMoved = true; });
    el.canvas.addEventListener("wheel", function () { state.userMoved = true; }, { passive: true });
    el.canvas.addEventListener("keydown", function (e) { if (/^Arrow|^[+-]$/.test(e.key)) state.userMoved = true; });
    el.canvas.addEventListener("touchstart", function (e) { if (e.touches.length > 1) state.userMoved = true; }, { passive: true });
    map.on("resize", function () { if (!state.userMoved) fitView(); fitMinZoom(); });
    zoomClasses();
  }

  /** A Leaflet pane at a fixed stacking level; non-interactive panes let taps through. */
  function pane(name, z, interactive) {
    var p = map.createPane(name);
    p.style.zIndex = String(z);
    if (!interactive) p.style.pointerEvents = "none";
    return p;
  }

  /** Fit Montana into the space the controls leave free: below the legend on a phone, right of it
      on a wide screen, and always above the timeline. Measured from the page, so banners count. */
  function fitView() {
    if (!map || !map._viewBounds) return;
    var vw = el.canvas.clientWidth, vh = el.canvas.clientHeight, tl, br;
    if (CARD) {
      var top = el.banners.getBoundingClientRect().bottom, chip = el.cardOpen.getBoundingClientRect().top;
      map.fitBounds(map._viewBounds, { paddingTopLeft: [6, Math.max(6, top + 4)], paddingBottomRight: [6, Math.max(6, vh - chip + 2)], animate: false });
      return;
    }
    var legend = el.legendWrap.getBoundingClientRect();
    var tlTop = el.timeline.getBoundingClientRect().top;
    var right = el.buttons.getBoundingClientRect().left;
    var bottomPad = Math.max(8, vh - tlTop + 8);
    if (vw >= 760) {
      tl = [legend.right + 12, Math.max(16, el.banners.getBoundingClientRect().bottom + 8)];
      br = [vw - right + 12, bottomPad];
    } else {
      tl = [6, legend.bottom + 4];
      br = [6, bottomPad];
      if (vh - tl[1] - br[1] < 170) tl[1] = el.legendWrap.offsetTop ? legend.top : 60;   // short screens: let the legend overlap
    }
    map.fitBounds(map._viewBounds, { paddingTopLeft: tl, paddingBottomRight: br, animate: false });
  }

  /** Don't let the viewer zoom out past the area the pictures cover (on big screens it is small). */
  function fitMinZoom() {
    if (!map || !map._imageBounds) return;
    var z = Math.floor(map.getBoundsZoom(map._imageBounds, false) * 4) / 4;
    var base = (data && data.view && data.view.min_zoom) || 5;
    map.setMinZoom(Math.max(base, Math.min(z, map.getZoom())));
  }

  /** Mark every whole zoom level reached on the map element; CSS shows the detail for each. */
  function zoomClasses() {
    var z = Math.floor(map.getZoom() + 1e-6);
    for (var i = 5; i <= 11; i++) el.canvas.classList.toggle("z-ge-" + i, z >= i);
  }

  // ------------------------------------------------------------------ basemap (drawn from basemap.json)

  /** Land, counties, rivers, lakes, roads, borders, then labels: the order the basemap expects. */
  function drawBasemap(bm) {
    var r = renderers.base;
    function lines(fc, base) {
      if (!fc || !fc.features) return;
      L.geoJSON(fc, {
        renderer: r, interactive: false, smoothFactor: 0.8,
        style: function (f) {
          var p = f.properties || {}, c = base;
          if (p.min_zoom && p.min_zoom > 5) c += " mz" + p.min_zoom;
          if (p.type) c += " bm-" + (p.type === "interstate" ? "interstate" : "us");
          if (p.kind) c += " bm-" + p.kind;
          if (p.montana) c += " bm-mt";
          if (p.rank) c += " rank-" + p.rank;
          return { className: c, weight: 1, fill: false };
        }
      }).addTo(map);
    }
    if (bm.land) {
      L.geoJSON(bm.land, {
        renderer: r, interactive: false, smoothFactor: 0.6,
        style: function (f) { return { className: "bm-land" + (f.properties && f.properties.montana ? " bm-mt" : ""), stroke: false, fillOpacity: 1 }; }
      }).addTo(map);
    }
    lines(bm.counties, "bm-county mz7");
    lines(bm.rivers, "bm-river");
    if (bm.lakes) {
      L.geoJSON(bm.lakes, {
        renderer: r, interactive: false,
        style: function (f) {
          var p = f.properties || {};
          return { className: "bm-lake" + (p.min_zoom > 5 ? " mz" + p.min_zoom : ""), stroke: false, fillOpacity: 1 };
        }
      }).addTo(map);
    }
    lines(bm.roads, "bm-road");
    lines(bm.borders, "bm-border");
    (bm.labels || []).forEach(function (lb) {
      var cls = "bm-label lbl-" + lb.kind + zoomCls(lb.min_zoom, lb.max_zoom);
      L.marker([lb.lat, lb.lon], {
        pane: "labels", interactive: false, keyboard: false,
        icon: L.divIcon({ className: cls, html: "<span>" + esc(lb.text) + "</span>", iconSize: [0, 0], iconAnchor: [0, 0] })
      }).addTo(map);
    });
    (bm.places || []).forEach(function (p) {
      if (p.site) return;          // the 14 site towns are drawn as bubbles instead
      L.marker([p.lat, p.lon], {
        pane: "labels", interactive: false, keyboard: false,
        icon: L.divIcon({ className: "bm-label place" + zoomCls(p.min_zoom, p.max_zoom),
          html: "<i></i><span>" + esc(p.name) + "</span>", iconSize: [0, 0], iconAnchor: [0, 0] })
      }).addTo(map);
    });
    zoomClasses();
  }

  /** Classes that show a feature only between its min and max zoom. */
  function zoomCls(minZ, maxZ) {
    var c = "";
    if (minZ && minZ > 5) c += " mz" + minZ;
    if (maxZ) c += " xz" + maxZ;
    return c;
  }

  /** Hatch everything outside the pictures' box: no radar or model there, so it must not look dry. */
  function drawOutsideMask() {
    if (!map._imageBounds) return;
    var ib = map._imageBounds;
    var world = [[-85, -179.9], [85, -179.9], [85, 179.9], [-85, 179.9]];
    var hole = [[ib.getSouth(), ib.getWest()], [ib.getNorth(), ib.getWest()], [ib.getNorth(), ib.getEast()], [ib.getSouth(), ib.getEast()]];
    L.polygon([world, hole], { renderer: renderers.mask, interactive: false, className: "bm-outside", stroke: false, fillOpacity: 1 }).addTo(map);
  }

  // ------------------------------------------------------------------ towns

  /** One bubble per site town: the NWS forecast value for the hour on the timeline. */
  function drawTowns() {
    data.towns.forEach(function (t) {
      var side = /^(right|left|top|bottom)$/.test(t.label || "") ? t.label : "right";
      var icon = L.divIcon({
        className: "town side-" + side + (t.minor ? " minor" : ""),
        html: '<span class="bubble" aria-hidden="true">\u2014</span><span class="tname" aria-hidden="true">' + esc(t.name) + "</span>",
        iconSize: [30, 30], iconAnchor: [15, 15]
      });
      var m = L.marker([t.lat, t.lon], { icon: icon, keyboard: !CARD, riseOnHover: true, interactive: true }).addTo(map);
      t._marker = m;
      t._el = m.getElement();
      t._bubble = t._el.querySelector(".bubble");
      t._el.setAttribute("role", CARD ? "link" : "button");
      m.on("click", function () { activateTown(t); });
      t._el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activateTown(t); }
      });
    });
  }

  /** A bubble was chosen: open its sheet (in the card, open the full map on that town). */
  function activateTown(t) {
    if (CARD) { window.open("map.html?town=" + encodeURIComponent(t.slug) + layerQuery("&"), "_top"); return; }
    openTown(t, t._el);
  }

  /** Town by slug. */
  function findTown(slug) {
    for (var i = 0; i < data.towns.length; i++) if (data.towns[i].slug === slug) return data.towns[i];
    return null;
  }

  /** The NWS hour shown for a frame time. Past frames show the current hour (NWS hourly forecasts
      start at the current hour); later frames show the hour they fall in. Null when NWS has none. */
  function townHour(t, ms) {
    var target = Math.max(ms, Date.parse(data.built));
    for (var i = 0; i < t.hours.length; i++) {
      var s = Date.parse(t.hours[i].time);
      if (s <= target && target < s + HOUR) return t.hours[i];
    }
    return null;
  }

  /** What a bubble says for an hour: temperature (precip/temp layers) or gusts (wind layer). */
  function bubbleValue(h) {
    if (!h) return { text: "\u2014", over: false, words: "no NWS forecast for this hour" };
    if (state.layer === "wind") {
      if (h.gust_mph == null) return { text: "\u2014", over: false, words: "gusts not in the NWS forecast" };
      var g = h.gust_mph;
      return { text: String(g), over: limits.gust_mph != null && g >= limits.gust_mph, words: "gusts " + g + " mph" };
    }
    if (h.temp_f == null) return { text: "\u2014", over: false, words: "temperature not in the NWS forecast" };
    var v = h.temp_f;
    var over = (limits.cold_f != null && v < limits.cold_f) || (limits.hot_f != null && v > limits.hot_f);
    return { text: String(v), over: over, words: v + " degrees" };
  }

  /** Time used for town values: the frame on the timeline, or the build time with no frames. */
  function valueTime() {
    return state.frames.length ? state.times[state.pos] : Date.parse(data.built);
  }

  /** Update every bubble for the frame on the timeline. */
  function renderBubbles() {
    var ms = valueTime();
    data.towns.forEach(function (t) {
      var h = townHour(t, ms), v = bubbleValue(h);
      if (t._text !== v.text) { t._bubble.textContent = v.text; t._text = v.text; }
      t._bubble.classList.toggle("over", v.over);
      t._bubble.classList.toggle("unknown", v.text === "\u2014");
      t._over = v.over;
      var label = t.name + ", " + v.words + (h ? " at " + clock(Date.parse(h.time)) + ", NWS forecast" : "") + (v.over ? ", over limit" : "");
      t._el.setAttribute("aria-label", CARD ? label + ". Opens the full map." : label);
    });
  }

  // ------------------------------------------------------------------ warnings and storm reports

  /** NWS warning outlines. Alerts without one are listed in the List sheet, never dropped. */
  function drawAlerts() {
    alertLayer = L.layerGroup();
    state.alertKinds = [];
    (data.alerts.items || []).forEach(function (a) {
      if (!a.geometry) return;
      var g = L.geoJSON(a.geometry, {
        renderer: renderers.alerts, interactive: !CARD,
        style: function () { return { className: "hz hz-" + a.kind, weight: 2, fillOpacity: 0.12 }; }
      });
      g.on("click", function (e) { L.DomEvent.stop(e); openAlert(a, null); });
      alertLayer.addLayer(g);
      if (state.alertKinds.indexOf(a.kind) < 0) state.alertKinds.push(a.kind);
    });
    if (state.warnings) alertLayer.addTo(map);
  }

  /** SPC storm reports: hail circles sized by stone size, wind circles; a wider invisible tap ring. */
  function drawReports() {
    reportLayer = L.layerGroup();
    (data.reports || []).forEach(function (r) {
      var radius = r.kind === "hail" ? 5 + 3.5 * clamp(r.size_in || 0.75, 0.5, 3) : 6;
      var dot = L.circleMarker([r.lat, r.lon], { renderer: renderers.reports, radius: radius, className: "rep rep-" + r.kind, interactive: false });
      reportLayer.addLayer(dot);
      if (!CARD) {
        var hit = L.circleMarker([r.lat, r.lon], { renderer: renderers.reports, radius: 22, className: "rep-hit", stroke: false, fillOpacity: 0 });
        hit.on("click", function (e) { L.DomEvent.stop(e); openReport(r, null); });
        reportLayer.addLayer(hit);
      }
    });
  }

  /** Warnings overlay on or off. */
  function setWarnings(on) {
    state.warnings = on;
    if (alertLayer) { if (on) alertLayer.addTo(map); else alertLayer.remove(); }
    renderKeys();
    saveUrl();
  }

  /** Storm reports overlay on or off. */
  function setReports(on, quiet) {
    state.reports = on;
    if (reportLayer) { if (on) reportLayer.addTo(map); else reportLayer.remove(); }
    renderKeys();
    renderReportNote();
    if (!quiet) saveUrl();
  }

  /** When the reports overlay is on: say how many, or that the report files failed. */
  function renderReportNote() {
    var old = byId("reports-banner");
    if (old) old.remove();
    if (!state.reports || !data) return;
    var st = data.status && data.status.reports;
    if (st && !st.ok) {
      banner("warn", "<strong>Storm reports didn't all load</strong> (" + esc(st.detail) + "). No report is not \u201cno hail\u201d.", "reports-banner");
    } else if (!data.reports.length) {
      banner("info", "No SPC storm reports in or near Montana in the last 3 days. No report is not \u201cno hail\u201d.", "reports-banner");
    }
  }

  // ------------------------------------------------------------------ layers, modes and the timeline

  /** The active layer's data. */
  function layer() { return data.layers[state.layer] || { frames: [], modes: {}, now_index: {} }; }

  /** Switch the weather layer; keep the time on the timeline when the new layer has it. */
  function setLayer(key, opts) {
    opts = opts || {};
    var keep = (!opts.atNow && state.frames.length) ? state.times[state.pos] : null;
    state.layer = key;
    var radios = el.layers.querySelectorAll("input[name=layer]");
    for (var i = 0; i < radios.length; i++) radios[i].checked = radios[i].value === key;
    var L_ = layer();
    var modes = Object.keys(L_.modes || {});
    if (modes.indexOf(state.mode) < 0) state.mode = modes.indexOf("12h") >= 0 ? "12h" : (modes[0] || "12h");
    renderLegend();
    buildTimeline(keep, opts.first);
    if (!opts.first) saveUrl();
  }

  /** Switch 1h / 12h for layers that have both; keep the time when possible. */
  function setMode(mode) {
    if (mode === state.mode) return;
    var keep = state.frames.length ? state.times[state.pos] : null;
    state.mode = mode;
    buildTimeline(keep, false);
    saveUrl();
  }

  /** Rebuild the timeline for the active layer and mode, then show a frame. */
  function buildTimeline(keepTime, first) {
    var L_ = layer();
    var idx = (L_.modes && L_.modes[state.mode]) || [];
    state.frames = idx.map(function (i) { return L_.frames[i]; }).filter(Boolean);
    state.times = state.frames.map(function (f) { return Date.parse(f.time); });
    state.nowPos = clamp((L_.now_index && L_.now_index[state.mode]) || 0, 0, Math.max(0, state.frames.length - 1));
    var modes = Object.keys(L_.modes || {}).filter(function (m) { return (L_.modes[m] || []).length; });
    el.seg.hidden = modes.length < 2;
    var segBtns = el.seg.querySelectorAll("button");
    for (var i = 0; i < segBtns.length; i++) {
      var on = segBtns[i].getAttribute("data-mode") === state.mode;
      segBtns[i].setAttribute("aria-checked", on ? "true" : "false");
      segBtns[i].tabIndex = on ? 0 : -1;
    }
    var n = state.frames.length;
    el.range.disabled = n < 2;
    el.play.disabled = n < 2;
    if (n) {
      el.range.min = String(state.times[0]);
      el.range.max = String(n > 1 ? state.times[n - 1] : state.times[0] + MIN);
      el.range.step = String(MIN);
    }
    renderTicks();
    layoutLabels();
    var pos = state.nowPos;
    if (keepTime != null && n) pos = nearest(keepTime);
    if (!n) {
      if (state.playing) setPlaying(false);
      showPicture(null);
      renderAll();
      return;
    }
    go(pos, {
      done: function () {
        preload();
        if (first && !CARD && !reducedMotion() && !sheetState && n > 1) { setPlaying(true); schedule(HOLD_MS); }
      }
    });
  }

  /** Position of the frame nearest to a time. */
  function nearest(ms) {
    var best = 0, d = Infinity;
    for (var i = 0; i < state.times.length; i++) {
      var di = Math.abs(state.times[i] - ms);
      if (di < d) { d = di; best = i; }
    }
    return best;
  }

  /** Fraction (0..1) along the track for a time; the track is linear in time like the reference. */
  function frac(ms) {
    var n = state.times.length;
    if (n < 2) return 0;
    return clamp((ms - state.times[0]) / (state.times[n - 1] - state.times[0]), 0, 1);
  }

  /** The "Now" time on the track: the newest radar frame (the build's "now"), or the build time when
      the radar is stale (its newest frame is then not "now"); kept inside the track. */
  function nowMs() {
    var radar = data.status && data.status.radar;
    var t = Date.parse(radar && radar.ok === false ? data.built : data.now);
    if (!state.times.length) return t;
    return clamp(t, state.times[0], state.times[state.times.length - 1]);
  }

  /** Small ticks under the track, one per frame where there is room, and a taller one at Now. */
  function renderTicks() {
    el.ticks.innerHTML = "";
    var w = el.ticks.clientWidth || 300, last = -99, html = "";
    for (var i = 0; i < state.times.length; i++) {
      var x = frac(state.times[i]) * w;
      if (x - last < 6 || i === state.nowPos) continue;
      last = x;
      html += '<i style="left:' + (frac(state.times[i]) * 100).toFixed(3) + '%"></i>';
    }
    if (state.times.length) html += '<i class="now" style="left:' + (frac(nowMs()) * 100).toFixed(3) + '%"></i>';
    el.ticks.innerHTML = html;
  }

  /** Time labels under the track: "Now" first, then whole hours (or half hours) that fit
      without touching each other at the current width. */
  function layoutLabels() {
    var box = el.labels, w = box.clientWidth;
    box.innerHTML = "";
    var n = state.times.length;
    if (!n || n < 2 || !w) return;
    var t0 = state.times[0], t1 = state.times[n - 1], span = t1 - t0;
    var nowT = nowMs();
    var steps = span > 4 * HOUR ? [HOUR, 2 * HOUR, 3 * HOUR, 4 * HOUR, 6 * HOUR] : [15 * MIN, 30 * MIN, HOUR, 2 * HOUR];
    var nowEl = makeLabel("Now", null, true);
    var nowBox = place(nowEl, frac(nowT) * w);
    var GAP = 10, EDGE = 6;
    for (var s = 0; s < steps.length; s++) {
      var marks = [], okAll = true;
      for (var t = Math.ceil(t0 / (15 * MIN)) * 15 * MIN; t <= t1; t += 15 * MIN) {
        if (!onStep(t, steps[s])) continue;
        if (Math.abs(t - nowT) < 1) continue;
        marks.push(t);
      }
      var placed = [nowBox], els = [];
      for (var k = 0; k < marks.length; k++) {
        var lab = makeLabel(null, marks[k], false);
        var b = place(lab, frac(marks[k]) * w);
        els.push(lab);
        if (b.left < -EDGE || b.right > w + EDGE) { lab.remove(); els.pop(); continue; }
        var hit = false;
        for (var q = 0; q < placed.length; q++) if (b.left < placed[q].right + GAP && b.right > placed[q].left - GAP) { hit = true; break; }
        if (hit) {
          if (marks.length > 1 && placed.length > 1) { okAll = false; break; }
          lab.remove(); els.pop(); continue;     // one label too close to "Now" is simply left out
        }
        placed.push(b);
      }
      if (okAll && els.length) { els.forEach(function (x) { x.classList.remove("measure"); }); break; }
      els.forEach(function (x) { x.remove(); });
    }
    nowEl.classList.remove("measure");
  }

  /** Whether a time falls on a label step in Montana time (hours on even local hours etc.). */
  function onStep(ms, step) {
    var p = parts(ms), m = Number(p.minute), h = Number(p.hour) % 12 + (p.dayPeriod === "PM" ? 12 : 0);
    if (step < HOUR) return m % (step / MIN) === 0;
    return m === 0 && h % (step / HOUR) === 0;
  }

  /** A label element (measured before it is shown). */
  function makeLabel(text, ms, isNow) {
    var s = document.createElement("span");
    s.className = "measure" + (isNow ? " now" : "");
    if (text) s.textContent = text;
    else {
      var p = parts(ms);
      if (p.minute === "00") s.innerHTML = esc(p.hour) + "<small>\u00a0" + esc((p.dayPeriod || "").toLowerCase()) + "</small>";
      else s.textContent = p.hour + ":" + p.minute;
    }
    el.labels.appendChild(s);
    return s;
  }

  /** Put a label centred at x px and return its box. */
  function place(s, x) {
    s.style.left = x.toFixed(1) + "px";
    var half = s.offsetWidth / 2;
    return { left: x - half, right: x + half };
  }

  // ------------------------------------------------------------------ showing a frame

  /** Show frame `pos` of the timeline. The picture changes only once it has loaded; until then the
      previous one stays, dimmed, and the subtitle says "loading". */
  function go(pos, opts) {
    var n = state.frames.length;
    if (!n) return;
    pos = clamp(pos, 0, n - 1);
    state.pos = pos;
    var f = state.frames[pos], token = ++state.goToken;
    renderAll();
    load(f.src, function (ok) {
      if (token !== state.goToken) return;
      f._failed = !ok;
      app.classList.remove("is-loading");
      showPicture(ok ? f.src : null);
      renderNote();
      if (opts && opts.done) opts.done(ok);
    });
    if (cache[f.src] && cache[f.src].ok === null) {
      app.classList.add("is-loading");
      if (overlays[front]) overlays[front].setOpacity(0.45);
    }
  }

  /** Everything that follows the frame on the timeline. */
  function renderAll() {
    renderTimeline();
    renderBubbles();
    renderNote();
    renderKeys();
    if (CARD) renderCardChip();
  }

  /** Load a picture once (shared by playback and preloading); cb(ok) when it has loaded or failed. */
  function load(src, cb) {
    var c = cache[src];
    if (!c) {
      c = cache[src] = { ok: null, cbs: [] };
      var img = new Image();
      img.decoding = "async";
      img.onload = function () { c.ok = true; flush(c); };
      img.onerror = function () { c.ok = false; flush(c); };
      img.src = src;
      c.img = img;
    }
    if (cb) { if (c.ok === null) c.cbs.push(cb); else cb(c.ok); }
  }

  /** Run the callbacks waiting for a picture. */
  function flush(c) { var cbs = c.cbs; c.cbs = []; cbs.forEach(function (cb) { cb(c.ok); }); }

  /** Queue the active layer's pictures: this mode from the shown frame on, then the other mode. */
  function preload() {
    if (preloaded[state.layer + state.mode]) return;
    preloaded[state.layer + state.mode] = true;
    var n = state.frames.length, order = [];
    for (var i = 1; i <= n; i++) order.push(state.frames[(state.pos + i) % n].src);
    order.forEach(function (src) { load(src); });
    var L_ = layer();
    Object.keys(L_.modes || {}).forEach(function (m) {
      if (m === state.mode) return;
      (L_.modes[m] || []).forEach(function (k) { if (L_.frames[k]) load(L_.frames[k].src); });
    });
  }

  /** Crossfade the two overlays to a loaded picture (no fade with reduced motion); null hides both. */
  function showPicture(src) {
    if (!overlays.length) return;
    var tok = ++swapToken, cur = overlays[front], nxt = overlays[1 - front];
    if (!src) { cur.setOpacity(0); nxt.setOpacity(0); return; }
    if (cur._url === src) { cur.setOpacity(1); nxt.setOpacity(0); return; }
    var img = nxt.getElement();
    if (img) {                      // stop any fade on the back picture before changing it
      img.classList.add("instant");
      nxt.setOpacity(0);
      void img.offsetWidth;
      img.classList.remove("instant");
    }
    var done = function () {
      if (tok !== swapToken) return;
      nxt.setOpacity(1);
      cur.setOpacity(0);
      front = 1 - front;
    };
    if (nxt._url === src && img && img.complete && img.naturalWidth) { done(); return; }
    nxt.once("load", done);
    nxt.setUrl(src);
  }

  /** Title, subtitle, slider value and fill for the frame on the timeline. */
  function renderTimeline() {
    var n = state.frames.length;
    if (!n) {
      el.title.textContent = state.layer === "precip" ? "No radar or forecast" : "No forecast";
      whenEl.textContent = "Nothing to show for " + LAYER_WORD[state.layer].toLowerCase();
      srcEl.textContent = "";
      el.range.setAttribute("aria-valuetext", "No pictures in this update");
      el.fill.style.width = "0";
      el.knob.style.left = "0";
      return;
    }
    var f = state.frames[state.pos], ms = state.times[state.pos];
    el.title.textContent = f.kind === "radar" ? "Radar" : "Forecast";
    whenEl.textContent = dayClock(ms);
    srcEl.textContent = sourceWords(f);
    el.range.value = String(ms);
    el.range.setAttribute("aria-valuetext", (f.kind === "radar" ? "Radar, " : "Forecast, ") + dayClock(ms) + ", " +
      sourceWords(f) + (state.pos === state.nowPos ? ", now" : ""));
    var pct = (frac(ms) * 100).toFixed(3) + "%";
    el.fill.style.width = pct;
    el.knob.style.left = pct;
  }

  /** The source in plain words: radar estimate or model forecast, never blended. */
  function sourceWords(f) {
    var sample = /^SAMPLE/.test(f.source || "");
    if (f.kind === "radar") return sample ? "sample, not NOAA radar" : "NOAA radar estimate";
    var run = f.run ? ", run " + clock(Date.parse(f.run)) : "";
    return sample ? "sample, not the HRRR model" : "HRRR model" + run;
  }

  /** The line above the timeline: a failed picture, hatched areas, the end of the forecast, or a
      layer with no pictures at all. Plain words; a failure is never left looking like clear sky. */
  function renderNote() {
    var text = "", warn = false;
    var n = state.frames.length;
    var st = data.status || {};
    if (!n) {
      var why = [];
      if (state.layer === "precip" && st.radar && !st.radar.ok) why.push("radar: " + st.radar.detail);
      if (st.forecast && !st.forecast.ok) why.push("model forecast: " + st.forecast.detail);
      text = "No " + LAYER_WORD[state.layer].toLowerCase() + " pictures in this update" + (why.length ? " (" + why.join("; ") + ")" : "") +
        ". This is not an all-clear.";
      warn = true;
    } else {
      var f = state.frames[state.pos], parts_ = [];
      if (f._failed) { parts_.push("The " + clock(state.times[state.pos]) + " picture didn't load. This is not an all-clear."); warn = true; }
      if (state.pos === n - 1 && f.kind === "radar") {
        parts_.push("No model forecast after now in this update" + (st.forecast && !st.forecast.ok ? " (" + st.forecast.detail + ")" : "") + ".");
        warn = true;
      }
      if (f.nodata && !f._failed) parts_.push("Hatched areas have no radar coverage.");
      text = parts_.join(" ");
    }
    el.note.textContent = text;
    el.note.hidden = !text || CARD;
    el.note.classList.toggle("warn", warn);
  }

  // ------------------------------------------------------------------ legend

  /** Legend for the active layer: title, gradient bar with its stop labels, note and keys. */
  function renderLegend() {
    var L_ = layer();
    el.legendTitle.textContent = L_.title || LAYER_WORD[state.layer];
    var stops = L_.legend || [];
    el.legendScale.hidden = !stops.length;
    el.legendBar.style.background = L_.gradient || "";
    el.legendScale.style.setProperty("--bar-h", Math.max(96, (stops.length - 1) * 16) + "px");
    el.legendStops.innerHTML = stops.map(function (s) {
      var pos = s.pos != null ? s.pos : 0;
      return '<li style="--pos:' + pos + '"' + (s.limit ? ' class="limit"' : "") + ">" + esc(s.label) + (s.limit ? " limit" : "") + "</li>";
    }).join("");
    el.legendNote.textContent = L_.legend_note || "";
    renderKeys();
  }

  /** Keys under the legend, only for what is on the map now: hatching, the limit ring, warning
      outline colours and storm-report circles. Every colour carries its word. */
  function renderKeys() {
    if (!data) return;
    var keys = [];
    var f = state.frames[state.pos];
    if (f && f.nodata) keys.push(["key-hatch", "No radar coverage"]);
    if (data.towns.some(function (t) { return t._over && townVisible(t); })) keys.push(["key-ring", ringWords()]);
    if (state.warnings) (state.alertKinds || []).forEach(function (k) { keys.push(["key-hz key-" + k, KIND_WORD[k] + " area (NWS)"]); });
    if (state.reports && data.reports.length) {
      if (data.reports.some(function (r) { return r.kind === "hail"; })) keys.push(["key-hail", "Hail report (size)"]);
      if (data.reports.some(function (r) { return r.kind === "wind"; })) keys.push(["key-wind", "Wind report"]);
    }
    var html = keys.map(function (k) { return '<li><span class="key ' + k[0] + '" aria-hidden="true"></span>' + esc(k[1]) + "</li>"; }).join("");
    if (el.legendKeys.innerHTML !== html) el.legendKeys.innerHTML = html;
  }

  /** Whether a town's bubble is on screen (minor towns appear from zoom 7). */
  function townVisible(t) {
    if (t.minor && map.getZoom() < 7) return false;
    return map.getBounds().contains([t.lat, t.lon]);
  }

  /** What the orange ring means for the layer on screen. */
  function ringWords() {
    if (state.layer === "wind") return "Gusts " + limits.gust_mph + "\u00a0mph or more";
    return "Below " + limits.cold_f + "\u00a0\u00b0F or above " + limits.hot_f + "\u00a0\u00b0F";
  }

  /** The layer menu's swatches use each layer's own legend colours (built by Python). */
  function paintSwatches() {
    ["precip", "temp", "wind"].forEach(function (k) {
      var sw = el.layers.querySelector(".sw-" + k);
      var L_ = data.layers[k];
      if (sw && L_ && L_.gradient) sw.style.background = L_.gradient;
    });
  }

  // ------------------------------------------------------------------ playback

  /** Start or stop playing (the button's aria-pressed says which). */
  function setPlaying(on) {
    state.playing = !!on && state.frames.length > 1;
    el.play.setAttribute("aria-pressed", state.playing ? "true" : "false");
    clearTimeout(state.timer);
    state.timer = null;
    if (state.playing) schedule(STEP_MS);
  }

  /** Next playback step after `ms`. */
  function schedule(ms) {
    clearTimeout(state.timer);
    state.timer = setTimeout(step, ms);
  }

  /** One playback step: the next frame once its picture is ready; hold on Now and on the end; loop. */
  function step() {
    state.timer = null;
    if (!state.playing) return;
    var n = state.frames.length, next = (state.pos + 1) % n, guard = 0;
    while (state.frames[next]._failed && guard++ < n) next = (next + 1) % n;
    go(next, {
      done: function () {
        if (!state.playing) return;
        schedule(next === state.nowPos || next === n - 1 ? HOLD_MS : STEP_MS);
      }
    });
  }

  /** Step one frame back or forward (keyboard, buttons); stepping pauses playback. */
  function stepBy(d) {
    if (state.frames.length < 2) return;
    setPlaying(false);
    go(clamp(state.pos + d, 0, state.frames.length - 1));
  }

  // ------------------------------------------------------------------ controls

  /** Connect buttons, the slider, menus and keys. */
  function wireControls() {
    el.play.addEventListener("click", function () { setPlaying(!state.playing); });

    el.seg.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-mode]");
      if (b) setMode(b.getAttribute("data-mode"));
    });
    el.seg.addEventListener("keydown", function (e) {      // radio group: arrows move the choice
      if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].indexOf(e.key) < 0) return;
      e.preventDefault();
      var btns = [].slice.call(el.seg.querySelectorAll("button"));
      var i = btns.indexOf(document.activeElement);
      var j = (i + (e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1) + btns.length) % btns.length;
      setMode(btns[j].getAttribute("data-mode"));
      btns[j].focus();
    });

    var r = el.range;
    r.addEventListener("pointerdown", function () { state.dragging = true; setPlaying(false); });
    window.addEventListener("pointerup", function () { state.dragging = false; });
    window.addEventListener("pointercancel", function () { state.dragging = false; });
    r.addEventListener("input", onRangeInput);
    r.addEventListener("keydown", onRangeKey);

    el.layersBtn.addEventListener("click", function () { toggleLayers(el.layers.hidden); });
    el.layers.addEventListener("focusout", function (e) {      // Tab out of the menu closes it
      var to = e.relatedTarget;
      if (to && !el.layers.contains(to) && to !== el.layersBtn) toggleLayers(false);
    });
    el.layers.addEventListener("change", function (e) {
      if (e.target.name === "layer") setLayer(e.target.value);
      else if (e.target === el.warnings) setWarnings(el.warnings.checked);
      else if (e.target === el.reports) setReports(el.reports.checked);
    });
    el.legendInfo.addEventListener("click", function () {
      var open = !el.legend.classList.contains("show-note");
      el.legend.classList.toggle("show-note", open);
      el.legendInfo.setAttribute("aria-expanded", open ? "true" : "false");
    });
    el.locateBtn.addEventListener("click", locate);
    el.listBtn.addEventListener("click", function () { openList(el.listBtn); });
    el.near.addEventListener("click", function () { var t = findTown(el.near.getAttribute("data-town")); if (t) openTown(t, el.near); });

    el.sheetClose.addEventListener("click", closeSheet);
    el.scrim.addEventListener("click", closeSheet);
    el.sheetBack.addEventListener("click", backToList);
    el.sheetBody.addEventListener("click", onSheetClick);
    el.sheet.addEventListener("keydown", trapFocus);

    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", function (e) {     // a tap outside closes the layer menu
      if (!el.layers.hidden && !el.layers.contains(e.target) && !el.layersBtn.contains(e.target)) toggleLayers(false);
    });
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { state.resumeOnShow = state.playing; setPlaying(false); }
      else if (state.resumeOnShow) { state.resumeOnShow = false; setPlaying(true); }
    });
    if (motionQuery && motionQuery.addEventListener) {
      motionQuery.addEventListener("change", function () { if (reducedMotion()) setPlaying(false); });
    }
    if (window.ResizeObserver) new ResizeObserver(function () { renderTicks(); layoutLabels(); }).observe(el.scrub);
    else window.addEventListener("resize", function () { renderTicks(); layoutLabels(); });
  }

  /** Dragging snaps to the nearest frame. A keyboard or screen-reader nudge (no finger down) that
      lands between frames moves to the next frame in that direction instead. */
  function onRangeInput() {
    var v = Number(el.range.value), k = nearest(v);
    if (!state.dragging && k === state.pos && v !== state.times[state.pos]) {
      k = clamp(state.pos + (v > state.times[state.pos] ? 1 : -1), 0, state.frames.length - 1);
    }
    setPlaying(false);
    if (k !== state.pos) go(k);
    else renderTimeline();
  }

  /** Arrow keys step one frame, Page keys three, Home/End jump; Space plays or pauses. */
  function onRangeKey(e) {
    var n = state.frames.length, d = 0;
    switch (e.key) {
      case "ArrowLeft": case "ArrowDown": d = -1; break;
      case "ArrowRight": case "ArrowUp": d = 1; break;
      case "PageDown": d = -3; break;
      case "PageUp": d = 3; break;
      case "Home": e.preventDefault(); setPlaying(false); go(0); return;
      case "End": e.preventDefault(); setPlaying(false); go(n - 1); return;
      case " ": e.preventDefault(); setPlaying(!state.playing); return;
      default: return;
    }
    e.preventDefault();
    stepBy(d);
  }

  /** Page keys: Escape closes the menu or sheet; Space plays; arrows step (outside text fields). */
  function onKey(e) {
    if (CARD) return;
    if (e.key === "Escape") {
      if (!el.layers.hidden) { e.preventDefault(); toggleLayers(false, true); return; }
      if (sheetState) { e.preventDefault(); closeSheet(); return; }
      return;
    }
    if (sheetState || !el.layers.hidden || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target, tag = (t && t.tagName) || "";
    var onPage = t === document.body || t === el.play || t === el.timeline || t === document.documentElement;
    if (e.key === " " && (t === document.body || t === document.documentElement)) { e.preventDefault(); setPlaying(!state.playing); return; }
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && onPage && tag !== "INPUT") {
      e.preventDefault();
      stepBy(e.key === "ArrowLeft" ? -1 : 1);
    }
  }

  /** Open or close the layer menu (focus goes in on open and back to the button on close). */
  function toggleLayers(open, refocus) {
    el.layers.hidden = !open;
    el.layersBtn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      var checked = el.layers.querySelector("input[name=layer]:checked") || el.layers.querySelector("input");
      if (checked) checked.focus();
    } else if (refocus) el.layersBtn.focus();
  }

  /** Keep the chosen layer, mode and overlay in the address so a reload keeps them. */
  function saveUrl() {
    if (CARD || !window.history || !history.replaceState || !data) return;
    var q = new URLSearchParams(location.search);
    q.delete("town");
    if (state.layer !== "precip") q.set("layer", state.layer); else q.delete("layer");
    var modes = Object.keys(layer().modes || {});
    if (modes.length > 1 && state.mode !== "12h") q.set("mode", state.mode); else q.delete("mode");
    if (state.reports) q.set("overlay", "reports"); else q.delete("overlay");
    var s = q.toString();
    history.replaceState(null, "", location.pathname + (s ? "?" + s : "") + location.hash);
  }

  /** "&layer=temp&overlay=reports" for links to the full map (prefix "?" or "&"). */
  function layerQuery(prefix) {
    var q = [];
    if (state.layer !== "precip") q.push("layer=" + state.layer);
    if (state.reports) q.push("overlay=reports");
    return q.length ? prefix + q.join("&") : "";
  }

  // ------------------------------------------------------------------ banners, toast, page age

  /** A small banner at the top. kind: warn | info. Replaces an earlier one with the same id. */
  function banner(kind, html, id) {
    if (id && byId(id)) byId(id).remove();
    var p = document.createElement("p");
    p.className = "banner banner-" + kind;
    if (id) p.id = id;
    if (kind === "warn") p.setAttribute("role", "alert");
    p.innerHTML = html;
    el.banners.appendChild(p);
    return p;
  }

  /** When the alert check failed but an earlier verified list is shown, say from when. */
  function noteLastKnownAlerts() {
    var a = data.alerts || {};
    var slot = document.querySelector('[data-source="alerts"] .last-known');
    if (!a.ok && slot) {
      slot.textContent = a.last_known
        ? " Showing the last list we verified, from " + dateClock(Date.parse(a.last_known)) + "."
        : " No earlier verified list to show.";
    }
  }

  /** "This map is 40 minutes old" once the page is older than the rebuild cycle allows. */
  function checkAge() {
    if (!builtMs) return;
    var minutes = Math.round((Date.now() - builtMs) / MIN);
    if (minutes <= STALE_MIN) return;
    var html = "<strong>This map is " + minutes + " minutes old.</strong> Reload for the latest." +
      (CARD ? "" : ' <button type="button" class="banner-btn" data-reload>Reload</button>');
    var b = byId("age-banner");
    if (b) b.querySelector("strong").textContent = "This map is " + minutes + " minutes old.";
    else {
      b = banner("warn", html, "age-banner");
      var btn = b.querySelector("[data-reload]");
      if (btn) btn.addEventListener("click", function () { location.reload(); });
    }
  }

  /** A short message above the timeline that fades after a few seconds. */
  function toast(text) {
    el.toast.textContent = text;
    el.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.toast.classList.remove("show"); el.toast.textContent = ""; }, 4500);
  }

  // ------------------------------------------------------------------ location

  /** Ask the browser for the viewer's position (only on this button); show a dot, an accuracy ring
      and the nearest town. Nothing is sent anywhere. */
  function locate() {
    if (!navigator.geolocation) { toast("Location isn't available."); return; }
    el.locateBtn.classList.add("is-busy");
    toast("Finding your location\u2026");
    navigator.geolocation.getCurrentPosition(function (pos) {
      el.locateBtn.classList.remove("is-busy");
      el.toast.classList.remove("show");
      el.toast.textContent = "";
      el.locateBtn.classList.add("is-on");
      var ll = L.latLng(pos.coords.latitude, pos.coords.longitude), acc = pos.coords.accuracy || 0;
      if (locLayer) locLayer.remove();
      locLayer = L.layerGroup([
        L.circle(ll, { radius: acc, renderer: renderers.loc, className: "loc-acc", interactive: false }),
        L.marker(ll, { pane: "loc", interactive: false, keyboard: false,
          icon: L.divIcon({ className: "loc-dot", html: "<i></i>", iconSize: [16, 16], iconAnchor: [8, 8] }) })
      ]).addTo(map);
      var best = null, bestKm = Infinity;
      data.towns.forEach(function (t) {
        var km = ll.distanceTo([t.lat, t.lon]) / 1000;
        if (km < bestKm) { bestKm = km; best = t; }
      });
      var inside = map._imageBounds && map._imageBounds.contains(ll);
      if (inside) { state.userMoved = true; map.setView(ll, Math.max(map.getZoom(), 7), { animate: !reducedMotion() }); }
      else toast("You're outside the area this map covers.");
      if (best) {
        var mi = Math.round(bestKm * 0.621371);
        el.near.textContent = "Nearest town: " + best.name + " \u00b7 " + mi + " mi";
        el.near.setAttribute("data-town", best.slug);
        el.near.setAttribute("aria-label", "Nearest town: " + best.name + ", " + mi + " miles. Open its forecast.");
        el.near.hidden = false;
      }
    }, function () {
      el.locateBtn.classList.remove("is-busy");
      toast("Location isn't available.");
    }, { enableHighAccuracy: false, timeout: 12000, maximumAge: 300000 });
  }

  // ------------------------------------------------------------------ sheets (town, alert, report, list)

  /** Open the bottom sheet (a modal dialog). The opener gets focus back when it closes. */
  function openSheet(kind, title, html, opener, opts) {
    opts = opts || {};
    if (!sheetState) {
      sheetState = { opener: opener || document.activeElement };
      setPlaying(false);
    }
    sheetState.kind = kind;
    toggleLayers(false);
    el.sheet.className = "glass sheet sheet-" + kind;
    el.sheetBack.hidden = !opts.back;
    el.sheetTitle.textContent = title;
    el.sheetBody.innerHTML = (data && data.sample ? '<p class="sample-tag">Sample data: invented to review the layout. It is not weather.</p>' : "") + html;
    el.sheetBody.scrollTop = 0;
    el.sheet.hidden = false;
    el.scrim.hidden = false;
    setInert(true);
    var f = opts.focus ? el.sheetBody.querySelector(opts.focus) : null;
    (f || el.sheetTitle).focus();
  }

  /** Close the sheet and put focus back where it came from. */
  function closeSheet() {
    if (!sheetState) return;
    var opener = sheetState.opener;
    sheetState = null;
    el.sheet.hidden = true;
    el.scrim.hidden = true;
    setInert(false);
    if (opener && document.contains(opener) && opener.focus && opener.offsetParent !== null) opener.focus();
    else el.canvas.focus();
  }

  /** Everything behind an open sheet is inert, so Tab and screen readers stay in the sheet. */
  function setInert(on) {
    [el.top, el.bottom, el.canvas, el.cardUi].forEach(function (x) {
      if (!x) return;
      if (on) x.setAttribute("inert", ""); else x.removeAttribute("inert");
    });
  }

  /** Fallback focus trap for browsers without `inert`: Tab cycles inside the sheet. */
  function trapFocus(e) {
    if (e.key !== "Tab") return;
    var f = [].slice.call(el.sheet.querySelectorAll("button:not([hidden]), a[href], [tabindex='0']")).filter(function (x) { return x.offsetParent !== null; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === el.sheetTitle)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  /** Clicks inside the sheet: rows open towns, alerts and reports (with a way back to the list). */
  function onSheetClick(e) {
    var b = e.target.closest("[data-town],[data-alert],[data-report]");
    if (!b) return;
    var fromList = sheetState && sheetState.kind === "list";
    if (fromList) { sheetState.listScroll = el.sheetBody.scrollTop; sheetState.listFocus = b.getAttribute("data-key"); }
    var back = fromList || (sheetState && sheetState.back);
    if (b.hasAttribute("data-town")) {
      var t = findTown(b.getAttribute("data-town"));
      if (t) openTown(t, null, back);
    } else if (b.hasAttribute("data-alert")) {
      var id = b.getAttribute("data-alert");
      var a = (data.alerts.items || []).filter(function (x) { return x.id === id; })[0];
      if (a) openAlert(a, null, back);
    } else {
      var r = data.reports[Number(b.getAttribute("data-report"))];
      if (r) openReport(r, null, back);
    }
  }

  /** Back from a town, alert or report to the list, where it was. */
  function backToList() {
    var scroll = sheetState && sheetState.listScroll, key = sheetState && sheetState.listFocus;
    openList(null);
    if (scroll) el.sheetBody.scrollTop = scroll;
    var b = key ? el.sheetBody.querySelector('[data-key="' + key + '"]') : null;
    if (b) b.focus();
  }

  /** Town sheet: the NWS forecast for the hour on the timeline, flags in words, alerts, a link. */
  function openTown(t, opener, back) {
    var ms = valueTime(), h = townHour(t, ms), html = "";
    if (h) {
      var hs = Date.parse(h.time), cur = hs <= Date.parse(data.built) && Date.parse(data.built) < hs + HOUR;
      html += '<p class="sub">NWS forecast for ' + esc(dayClock(hs)) + (cur ? " (this hour)" : "") + "</p>";
      var tOver = h.temp_f != null && ((limits.cold_f != null && h.temp_f < limits.cold_f) || (limits.hot_f != null && h.temp_f > limits.hot_f));
      var gOver = h.gust_mph != null && limits.gust_mph != null && h.gust_mph >= limits.gust_mph;
      var wOver = h.wind_mph != null && limits.wind_mph != null && h.wind_mph >= limits.wind_mph;
      var pOver = h.precip != null && limits.pop_pct != null && h.precip >= limits.pop_pct;
      html += '<dl class="stats">' +
        stat("Temperature", h.temp_f, "\u00a0\u00b0F", tOver) +
        stat("Wind" + (h.wind_dir ? " from the " + h.wind_dir : ""), h.wind_mph, " mph", wOver) +
        stat("Gusts", h.gust_mph, " mph", gOver) +
        stat("Chance of rain or snow", h.precip, "%", pOver) + "</dl>";
      if (h.sky) html += "<p>" + esc(h.sky) + ".</p>";
      if (h.flags && h.flags.length) {
        html += '<p class="sub">Needs a look at ' + esc(clock(hs)) + ":</p><ul class=\"flags\">" +
          h.flags.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>";
      } else {
        var missing = [];
        if (h.gust_mph == null) missing.push("gusts");
        if (h.wind_mph == null) missing.push("wind");
        if (h.precip == null) missing.push("chance of rain or snow");
        if (h.temp_f == null) missing.push("temperature");
        html += "<p>No value for " + esc(clock(hs)) + " reaches a limit" + (missing.length ? "; " + esc(missing.join(", ")) + " not in the forecast, so not checked" : "") + ".</p>";
      }
    } else if (!t.hours.length) {
      html += '<p class="warn">The NWS forecast for ' + esc(t.name) + " didn't load in this update. This is not an all-clear.</p>";
    } else {
      html += '<p class="warn">The NWS forecast has no value for this hour. This is not an all-clear.</p>';
    }
    html += "<h3>Official alerts</h3>";
    var checked = Date.parse(data.alerts.checked || data.built);
    if (t.alert_ids === null) {
      html += '<p class="warn">Couldn\u2019t check NWS alerts for ' + esc(t.name) + " in this update. This is not an all-clear.</p>";
    } else if (!t.alert_ids.length) {
      html += "<p>No active NWS alerts for this location at " + esc(clock(checked)) + ". That is not an all-clear.</p>";
    } else {
      html += '<div class="rows">' + t.alert_ids.map(function (id) {
        var a = (data.alerts.items || []).filter(function (x) { return x.id === id; })[0];
        if (!a) return '<p class="muted">An alert that is listed on the Now page.</p>';
        return alertRow(a);
      }).join("") + "</div>";
    }
    html += '<p><a class="go" href="' + esc(t.url) + '">Full forecast for ' + esc(t.name) + "</a></p>";
    openSheet("town", t.name, html, opener, { back: back });
    reveal(L.latLng(t.lat, t.lon));
  }

  /** Pan just enough that a point stays in sight beside or above the open sheet and below the
      top controls (like a maps app does when a place card opens). */
  function reveal(ll) {
    var size = map.getSize(), p = map.latLngToContainerPoint(ll);
    var mapR = el.canvas.getBoundingClientRect(), sh = el.sheet.getBoundingClientRect();
    var free = { left: 0, top: el.buttons.getBoundingClientRect().top - mapR.top + 52, right: size.x, bottom: size.y };
    if (sh.left - mapR.left > size.x / 3) free.right = sh.left - mapR.left;      // side panel (wide screens)
    else free.bottom = sh.top - mapR.top;                                       // bottom sheet (phones)
    var m = 36;
    if (free.bottom - free.top < 2 * m || free.right - free.left < 2 * m) return;
    var x = clamp(p.x, free.left + m, free.right - m), y = clamp(p.y, free.top + m, free.bottom - m);
    if (Math.abs(x - p.x) > 1 || Math.abs(y - p.y) > 1) {
      state.userMoved = true;
      map.panBy([p.x - x, p.y - y], { animate: !reducedMotion() });
    }
  }

  /** One figure in the town sheet; a missing value is a dash with words for screen readers. */
  function stat(label, v, unit, over) {
    var val = v == null ? '\u2014<span class="visually-hidden"> not in the forecast</span>'
      : esc(v) + "<small>" + esc(unit) + "</small>" + (over ? '<span class="visually-hidden"> (over limit)</span>' : "");
    return "<div" + (over ? ' class="over"' : "") + "><dt>" + esc(label) + "</dt><dd>" + val + "</dd></div>";
  }

  /** A row that opens an alert, with its kind in words and colour. */
  function alertRow(a) {
    var until = a.until ? "until " + dateClock(Date.parse(a.until)) : "no end time given";
    return '<button type="button" class="row" data-alert="' + esc(a.id) + '" data-key="a-' + esc(a.id) + '">' +
      '<span class="row-main"><span class="row-title"><span class="chip-k chip-' + esc(a.kind) + '">' + esc(KIND_WORD[a.kind] || a.kind) + "</span> " + esc(a.event) + "</span>" +
      '<span class="row-meta">' + esc(until) + (a.geometry ? "" : " \u00b7 no outline on the map") + "</span></span></button>";
  }

  /** Alert sheet: the official NWS text, unchanged. */
  function openAlert(a, opener, back) {
    var html = '<p><span class="chip-k chip-' + esc(a.kind) + '">' + esc(KIND_WORD[a.kind] || a.kind) + "</span></p>";
    html += '<p class="sub">' + (a.until ? "Until " + esc(dateClock(Date.parse(a.until))) : "No end time given") +
      (a.onset ? " \u00b7 from " + esc(dateClock(Date.parse(a.onset))) : "") + "</p>";
    if (a.area) html += "<p><strong>Area:</strong> " + esc(a.area) + "</p>";
    if (!a.geometry) html += '<p class="muted">This alert has no outline, so it is not drawn on the map. It covers the counties or zones named above.</p>';
    if (!data.alerts.ok) {
      html += '<p class="warn">The latest alert check failed' + (data.alerts.last_known ? "; this is from the list verified at " + esc(dateClock(Date.parse(data.alerts.last_known))) : "") + ".</p>";
    }
    if (a.headline) html += "<p><strong>" + esc(a.headline) + "</strong></p>";
    if (a.description) html += '<p class="official">' + esc(a.description) + "</p>";
    if (a.instruction) html += "<h3>Instructions</h3><p class=\"official\">" + esc(a.instruction) + "</p>";
    html += '<p class="muted">From ' + esc(a.sender || "the National Weather Service") + ". Official text, shown as issued.</p>";
    html += '<p><a class="go" href="index.html">All warnings on the Now page</a></p>';
    openSheet("alert", a.event, html, opener, { back: back });
  }

  /** Report sheet: one SPC preliminary report, with what it can't tell you. */
  function openReport(r, opener, back) {
    var what = r.kind === "hail" ? (r.size_in != null ? r.size_in.toFixed(2) + " in hail" : "Hail, size not given")
      : (r.mph != null ? "Wind " + r.mph + " mph" : "Wind damage or gust, speed unknown");
    var html = '<p><span class="chip-k chip-' + esc(r.kind) + '">' + (r.kind === "hail" ? "Hail report" : "Wind report") + "</span></p>";
    html += '<p class="sub">' + esc(dateClock(Date.parse(r.time))) + "</p>";
    html += "<p><strong>" + esc(r.place) + "</strong>" + (r.county ? ", " + esc(r.county) + " County" : "") + (r.state ? ", " + esc(r.state) : "") + "</p>";
    if (r.comments) html += '<p class="official">' + esc(r.comments) + "</p>";
    html += '<p class="muted">SPC preliminary storm report: one observation at one place. It does not confirm damage, and no report is not \u201cno hail\u201d.</p>';
    html += '<p><a class="go" href="reports.html">All storm reports</a></p>';
    openSheet("report", what, html, opener, { back: back });
  }

  /** List sheet: the map as text. Every active alert (with or without an outline), every town's
      value for the hour on the timeline, and the storm reports when that overlay is on. */
  function openList(opener) {
    var a = data.alerts || {}, items = a.items || [], html = "";
    var hourMs = Math.floor(Math.max(valueTime(), Date.parse(data.built)) / HOUR) * HOUR;   // Montana is a whole-hour offset
    html += '<p class="sub">Town values are the NWS forecast for ' + esc(dayClock(hourMs)) + ", the hour on the timeline.</p>";
    html += "<h3>Official alerts (" + items.length + ")</h3>";
    if (!a.ok) html += '<p class="warn">The NWS alert check failed in this update' + (a.last_known ? "; showing the list verified at " + esc(dateClock(Date.parse(a.last_known))) : "") + ". This is not an all-clear.</p>";
    if (items.length) html += '<div class="rows">' + items.map(alertRow).join("") + "</div>";
    else if (a.ok) html += "<p>No active NWS warnings, watches or advisories for Montana at " + esc(clock(Date.parse(a.checked))) + ".</p>";
    var what = state.layer === "wind" ? "NWS gust forecast" : "NWS temperature forecast";
    html += "<h3>Towns \u00b7 " + esc(what) + "</h3><div class=\"rows\">";
    var ms = valueTime();
    data.towns.forEach(function (t) {
      var h = townHour(t, ms), v = bubbleValue(h);
      var meta = h ? (h.flags && h.flags.length ? "Needs a look: " + h.flags.join(", ") : "No value reaches a limit at " + clock(Date.parse(h.time)))
        : (t.hours.length ? "No NWS value for this hour" : "NWS forecast didn't load");
      if (t.alert_ids === null) meta += " \u00b7 alerts not checked";
      else if (t.alert_ids.length) meta += " \u00b7 " + t.alert_ids.length + (t.alert_ids.length > 1 ? " alerts" : " alert");
      var unit = state.layer === "wind" ? " mph gusts" : " \u00b0F";
      html += '<button type="button" class="row" data-town="' + esc(t.slug) + '" data-key="t-' + esc(t.slug) + '">' +
        '<span class="mini-bubble' + (v.over ? " over" : "") + (v.text === "\u2014" ? " unknown" : "") + '" aria-hidden="true">' + esc(v.text) + "</span>" +
        '<span class="row-main"><span class="row-title">' + esc(t.name) + '<span class="visually-hidden">, ' + esc(v.text === "\u2014" ? "no value" : v.text + unit) + (v.over ? ", over limit" : "") + "</span></span>" +
        '<span class="row-meta' + (h ? "" : " warn") + '">' + esc(meta) + "</span></span></button>";
    });
    html += "</div>";
    if (state.reports) {
      html += "<h3>Storm reports, last 3 days (" + data.reports.length + ")</h3>";
      if (data.reports.length) {
        html += '<div class="rows">' + data.reports.map(function (r, i) {
          var what = r.kind === "hail" ? (r.size_in != null ? r.size_in.toFixed(2) + " in hail" : "Hail") : (r.mph != null ? "Wind " + r.mph + " mph" : "Wind, speed unknown");
          return '<button type="button" class="row" data-report="' + i + '" data-key="r-' + i + '"><span class="row-main"><span class="row-title">' + esc(what) + "</span>" +
            '<span class="row-meta">' + esc(r.place) + ", " + esc(r.state) + " \u00b7 " + esc(dateClock(Date.parse(r.time))) + "</span></span></button>";
        }).join("") + "</div>";
      } else html += "<p>No reports. No report is not \u201cno hail\u201d.</p>";
    }
    var st = data.status || {};
    var bad = ["radar", "forecast", "alerts", "forecasts", "reports"].filter(function (k) { return st[k] && !st[k].ok; });
    if (bad.length) {
      html += "<h3>Sources with problems</h3><ul>" + bad.map(function (k) {
        return "<li>" + esc(st[k].label) + ": " + esc(st[k].detail) + ".</li>";
      }).join("") + "</ul>";
    }
    openSheet("list", "List", html, opener, {});
  }

  // ------------------------------------------------------------------ card mode (inside other pages)

  /** The card: latest frame, outlines and bubbles; no controls except "Open map". */
  function setupCard() {
    el.cardOpen.href = "map.html" + layerQuery("?");
    renderCardChip();
  }

  /** The card's caption: which picture this is and when. */
  function renderCardChip() {
    var f = state.frames[state.pos];
    var L_ = layer();
    if (!f) { el.cardChip.textContent = "No " + LAYER_WORD[state.layer].toLowerCase() + " picture in this update"; return; }
    var what = f.kind === "radar" ? (/^SAMPLE/.test(f.source) ? "Sample radar, not real" : "NOAA radar estimate") : (/^SAMPLE/.test(f.source) ? "Sample forecast, not real" : "HRRR model forecast");
    el.cardChip.innerHTML = '<span class="card-bar" style="background:' + esc((L_.gradient || "").replace("to top", "to right")) + '" aria-hidden="true"></span>' +
      "<span>" + esc(what) + " \u00b7 " + esc(clock(state.times[state.pos])) + "</span>";
  }

  boot();
})();
