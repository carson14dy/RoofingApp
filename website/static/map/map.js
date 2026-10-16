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
  var RETRY_MS = 10000;              // a picture that failed is asked for again after this, on the viewer's own step
  var TZ = "America/Denver";         // every time on the map is Montana time
  var MIN = 60000, HOUR = 3600000;
  var BLANK = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
  var FALLBACK_VIEW = { bounds: [[44.35, -116.06], [49.01, -104.03]], min_zoom: 5, max_zoom: 11 };
  var KIND_WORD = { warning: "Warning", watch: "Watch", advisory: "Advisory", statement: "Statement" };
  var LAYER_WORD = { precip: "Precipitation", temp: "Temperature", wind: "Wind gusts" };
  // the note line's words for hatching in view (one line each, so noteRoom's one-line room holds):
  // a gap inside a picture, the band outside the pictures' box, or both ("on this map" is true of both)
  var HATCH_NOTE = {
    radar: "Hatched areas have no radar coverage.", model: "Hatched areas have no model data.",
    radarOut: "Hatched areas have no radar data on this map.", modelOut: "Hatched areas have no model data on this map.",
    outside: "Hatched areas are outside this map's area."
  };
  var OUTSIDE_WORDS = "Outside the map's area";

  var app = document.getElementById("app");
  var params = new URLSearchParams(location.search);
  var CARD = params.get("card") === "1";
  var motionQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  // keep these in step with the media queries of the same layouts in map.css
  // (not under 301 px tall or 521 px wide: those fold the legend instead, map.css "very short or narrow")
  var sideQuery = window.matchMedia ? window.matchMedia("(min-height: 301px) and (max-height: 500px) and (min-width: 521px) and (orientation: landscape)") : null;
  var compactQuery = window.matchMedia ? window.matchMedia("(max-width: 520px) and (max-height: 760px), (max-height: 500px)") : null;
  var phoneQuery = window.matchMedia ? window.matchMedia("(max-width: 520px) and (orientation: portrait)") : null;
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
    warnings: true, reports: params.get("overlay") === "reports", goToken: 0, userMoved: false,
    ready: false,                    // true once the first timeline is built
    autoplay: true                   // play once the first picture shows, unless the viewer chose first (setPlaying)
  };
  var overlays = [], front = 0, swapToken = 0;   // two image overlays, crossfaded
  var cache = {};                                // picture src -> {ok: null|true|false, cbs: []}
  var preloaded = {};                            // layer key -> true once its frames are queued
  var renderers = {};
  var alertLayer = null, reportLayer = null, locLayer = null;
  var sheetState = null;                         // {opener, kind, ll, view, watcher, listScroll, listFocus}
  var sheetOpenedAt = 0;                         // when the sheet last opened from closed (scrim double-click guard)
  var panLimits = null;                          // the map's max bounds, lifted while a sheet is open
  var locState = null;                           // {ll, dot}: the viewer's location once found
  var updateChecked = 0;                         // when checkForUpdate last asked for map.json
  var toastTimer = null;
  var cardFitting = false;                       // fitCard is running (the caption must not re-fit)
  var legendForm = null;                         // the legend's form when last drawn (legendFormNow)
  var legendCrowded = false;                     // fitView found no room for Montana under the one-column legend
  var noteFit = { sig: null, room: 0 };          // the note warnings and room the last fit allowed for
  var noteSizes = { width: -1, px: {} };         // measured note sizes by text, at one note width

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

  /** fetch() a JSON file from this site; rejects with a reason in plain words (never a parser's
      message such as "Unexpected token '<'"). */
  function fetchJSON(url, opts) {
    return fetch(url, opts || { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("the server answered HTTP " + r.status);
      return r.json().then(null, function () { throw new Error("the file was incomplete or damaged"); });
    }, function () { throw new Error("no connection to the site"); });
  }

  // ------------------------------------------------------------------ Montana time, in the site's words

  var dtf = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "long", hour: "numeric", minute: "2-digit", hour12: true, timeZoneName: "short" });
  var dtfDay = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric" });

  /** {weekday, hour, minute, dayPeriod, timeZoneName} of an instant in Montana time. */
  function parts(ms) {
    var o = {};
    dtf.formatToParts(new Date(ms)).forEach(function (p) { o[p.type] = p.value; });
    return o;
  }

  var baseZone = null;
  /** " MST" when an instant's zone (MST or MDT) differs from the build time's, else "": on the night
      the clocks fall back, 1 am happens twice and only the zone tells the two apart. The rest of
      the year the times stay as short as Apple's. */
  function zoneMark(p) {
    if (baseZone === null) baseZone = parts(builtMs || Date.now()).timeZoneName || "";
    return p.timeZoneName && p.timeZoneName !== baseZone ? "\u00a0" + p.timeZoneName : "";
  }

  /** "4:56 pm", or "7 pm" on the hour (lowercase am/pm, like the rest of the site); "1 am MST" when
      the zone differs from the build time's (zoneMark). */
  function clock(ms) {
    var p = parts(ms), ap = (p.dayPeriod || "").toLowerCase();
    return (p.minute === "00" ? p.hour : p.hour + ":" + p.minute) + "\u00a0" + ap + zoneMark(p);
  }

  /** "Thursday 4:56 pm". */
  function dayClock(ms) { return parts(ms).weekday + " " + clock(ms); }

  /** "Thu Oct 15, 4:56 pm" for reports and alerts, which can be days away. */
  function dateClock(ms) { return dtfDay.format(new Date(ms)).replace(",", "") + ", " + clock(ms); }

  // ------------------------------------------------------------------ start-up

  /** Load the two data files and build the map from map.json as soon as it answers: towns, warning
      outlines and the first picture don't wait for the basemap (the largest file, outlines only),
      which is drawn underneath when it arrives (its panes sit below). The age banner waits for
      neither. An error while starting is shown in words (showNoData), never left on "Loading". */
  function boot() {
    if (CARD) document.documentElement.classList.add("is-card");
    checkAge();
    setInterval(checkAge, MIN);
    whenEl.textContent = "Loading the map";
    el.play.disabled = true;
    el.range.disabled = true;
    var gotData = fetchJSON(app.getAttribute("data-map")).then(null, function (e) { return { _error: e.message }; });
    var gotBase = fetchJSON(app.getAttribute("data-basemap")).then(null, function (e) { return { _error: e.message }; });
    gotData.then(function (d) {
      try { start(d); } catch (e) { showNoData("the map couldn\u2019t start with this update\u2019s data"); return; }
      gotBase.then(function (bm) {
        try {
          if (bm && !bm._error) { drawBasemap(bm); tidyLabels(); }
          else banner("warn", "<strong>The map outlines didn't load</strong> (" + esc((bm && bm._error) || "it didn't load") + "). The weather and towns still show.");
        } catch (e) { banner("warn", "<strong>The map outlines couldn't be drawn.</strong> The weather and towns still show."); }
      });
    });
  }

  /** No map data (it didn't load, or the map couldn't start with it): say so in words and hide the
      controls that need data. No Leaflet call here: a Leaflet failure is one way to get here. */
  function showNoData(why) {
    data = null;
    setPlaying(false);
    banner("warn", "<strong>The map data didn't load</strong> (" + esc(why || "it didn't load") + "). No radar, forecast or warnings are shown. " +
      "This is not an all-clear. <a href=\"index.html\" target=\"_top\">See the Now page</a> or reload.");
    whenEl.textContent = "Map data unavailable";
    srcEl.textContent = "";
    el.title.textContent = "No data";
    el.play.disabled = true;
    el.range.disabled = true;
    app.classList.remove("is-loading");
    app.classList.add("no-data");      // CSS hides the legend scale and the controls that need data
  }

  /** Build everything once map.json has answered (it may have failed); the basemap comes later. */
  function start(mapData) {
    var ok = mapData && !mapData._error && mapData.layers;
    data = ok ? mapData : null;
    createMap(ok && mapData.view ? mapData.view : FALLBACK_VIEW, ok ? mapData.image_bounds : null);
    if (!ok) {
      showNoData((mapData && mapData._error) || "the file has no map in it");
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
    if (CARD) setupCard();        // before the fit: the card's fit keeps Montana above the caption
    fitView();
    if (document.fonts && document.fonts.ready) {   // text first measured in a fallback font: measure again
      document.fonts.ready.then(function () {
        noteSizes.width = -1;                       // the note's measured sizes too
        renderTicks();
        layoutLabels();
        if (!state.userMoved) fitView();
      });
    }
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
      markerZoomAnimation: !reducedMotion(), inertia: !reducedMotion()
    });
    // With reduced motion every pan jumps instead of gliding: Leaflet's arrow-key pan, bounds pans
    // and our own (reveal) all go through panBy. Checked at each pan, since the setting can change.
    var panBy = map.panBy;
    map.panBy = function (offset, opts) {
      return panBy.call(this, offset, reducedMotion() ? L.extend({}, opts, { animate: false }) : opts);
    };
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
    map.on("zoomend", placeLocDot);
    map.on("moveend", function () {          // hatching and ringed bubbles come into or out of view
      tidyLabels();
      if (!state.ready) return;
      renderKeys();
      renderNote();
      if (CARD) renderCardChip();
    });
    map.on("dragstart", function () { state.userMoved = true; });
    el.canvas.addEventListener("wheel", function () { state.userMoved = true; }, { passive: true });
    el.canvas.addEventListener("keydown", function (e) { if (/^Arrow|^[+-]$/.test(e.key)) state.userMoved = true; });
    el.canvas.addEventListener("touchstart", function (e) { if (e.touches.length > 1) state.userMoved = true; }, { passive: true });
    map.on("resize", function () {
      if (data && state.ready && legendFormNow() !== legendForm) renderLegend();   // turned or resized past a breakpoint
      if (!state.userMoved) fitView();
      fitMinZoom();
      if (!el.layers.hidden) fitLayersMenu();
      if (sheetState) {
        sheetState.resized = true;
        placeSheet();
        if (sheetState.ll) reveal(sheetState.ll);    // a turn can put the town under the side panel
      }
      tidyLabels();
    });
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
      on a wide screen or a short landscape one (where the timeline also starts right of it), and
      always above the timeline and the note (noteRoom). Measured from the page, so banners count.
      Below the legend wins on a phone whenever Montana fits there at the minimum zoom or more (every
      town visible beats a bigger Montana). When it can't, even with the two-column legend (or, on a
      short landscape screen, below the banners), Montana stays at the minimum zoom, bigger would
      only hide more, and goes where it hides the least of the town bubbles (placeCrowded). */
  function fitView() {
    if (!map || !map._viewBounds) return;
    if (CARD) { fitCard(); return; }
    var base = (data && data.view && data.view.min_zoom) || 5;
    if (map.getMinZoom() > base) map.setMinZoom(base);   // fitMinZoom may have raised it for a bigger box
    var vw = el.canvas.clientWidth, vh = el.canvas.clientHeight, tl, br;
    var legend = el.legendWrap.getBoundingClientRect();
    var tlTop = el.timeline.getBoundingClientRect().top;
    var right = el.buttons.getBoundingClientRect().left;
    noteFit.sig = data && state.ready ? noteWarningSet().join("\n") : null;
    noteFit.room = noteRoom();
    var bottomPad = Math.max(8, vh - tlTop + 8 + noteFit.room);
    var vb = map._viewBounds, sum = function (top) { return L.point(tl[0] + br[0], top + br[1]); };
    if (vw >= 760 || sideLegend()) {
      tl = [legend.right + 12, Math.max(16, el.banners.getBoundingClientRect().bottom + 8)];
      br = [vw - right + 12, bottomPad];
      // a short landscape screen can be too short for Montana even at the minimum zoom
      var zs = boundsZoom(vb, sum(tl[1]));
      if (boundsSize(vb, zs).y > vh - tl[1] - br[1]) placeCrowded(vb, zs, tl, br, vw, vh, tlTop);
    } else {
      // a taller phone keeps the one-column legend unless banners and the note leave Montana no room
      // under it even at the minimum zoom; then it takes the short phones' two-column legend
      if (data && state.ready && phoneQuery && phoneQuery.matches && !(compactQuery && compactQuery.matches)) {
        setCrowded(false);
        if (!fitsBelow(vb, el.legendWrap.getBoundingClientRect().bottom + 4, bottomPad, vh)) setCrowded(true);
        legend = el.legendWrap.getBoundingClientRect();
      }
      tl = [6, legend.bottom + 4];
      br = [6, bottomPad];
      var zBelow = boundsZoom(vb, sum(tl[1]));
      if (boundsSize(vb, zBelow).y > vh - tl[1] - br[1] + 1) placeCrowded(vb, zBelow, tl, br, vw, vh, tlTop);
    }
    map.fitBounds(vb, { paddingTopLeft: tl, paddingBottomRight: br, animate: false });
    fitMinZoom();
  }

  /** A country or region name (a basemap label) under one of the two controls that are plain text on
      the map, the "Map data" link and the note line, is hidden until the map moves: two texts on top
      of each other read as neither. The glass panels hide what is under them anyway, and names may
      run off the edge as in the reference. Runs after every move, resize and note change. */
  function tidyLabels() {
    if (!map || CARD) return;
    var boxes = [], link = el.legendWrap.querySelector(".mapdata");
    if (link && link.offsetParent !== null) {          // the link's text, not its 44 px tap area
      var rg = document.createRange();
      rg.selectNodeContents(link);
      boxes.push(rg.getBoundingClientRect());
    }
    if (!el.note.hidden) boxes.push(el.note.getBoundingClientRect());
    boxes = boxes.filter(function (b) { return b.width && b.height; });
    var spans = el.canvas.querySelectorAll(".lbl-country span, .lbl-region span");
    for (var i = 0; i < spans.length; i++) {
      var r = spans[i].getBoundingClientRect(), hide = false;
      for (var k = 0; r.width && !hide && k < boxes.length; k++) {
        var b = boxes[k];
        hide = r.left < b.right + 2 && r.right > b.left - 2 && r.top < b.bottom + 2 && r.bottom > b.top - 2;
      }
      spans[i].classList.toggle("bm-hide", hide);
    }
  }

  /** Montana (box vb at zoom z, centred across) has no room between the controls at the top and the
      note: something will be hidden whatever we do. Try each spot from Montana touching the note
      down to it touching the timeline, measure how much of every town bubble the legend, the
      banners, the buttons, the note (noteBox) and the timeline would cover there, and keep the spot
      that hides the least (on a tie, the highest: the note stays clear). Each edge of Montana has
      towns close to it, so where the overflow goes decides how many are lost. Sets the paddings in
      tl and br for fitBounds. */
  function placeCrowded(vb, z, tl, br, vw, vh, tlTop) {
    var size = boundsSize(vb, z), R = 15, AREA = 4 * R * R;     // bubbles are 30 px
    var y0 = Math.max(0, Math.round(vh - br[1] - size.y - 2));  // touching the note
    var y1 = Math.max(y0, Math.floor(tlTop - size.y - 2));      // touching the timeline
    var left = tl[0] + (vw - tl[0] - br[0] - size.x) / 2;
    var nw = map.project(vb.getNorthWest(), z), pts = [];
    (data ? data.towns : []).forEach(function (t) { if (!t.minor) pts.push(map.project([t.lat, t.lon], z).subtract(nw)); });
    var boxes = [];
    [el.legend, el.legendWrap.querySelector(".mapdata"), el.top.querySelector(".close"), el.buttons, el.timeline]
      .concat([].slice.call(el.banners.children)).forEach(function (e) {
        var r = e && e.getBoundingClientRect();
        if (r && r.width && r.height) boxes.push(r);
      });
    var nb = noteBox(tlTop);
    if (nb) boxes.push(nb);
    var best = y0, bestScore = Infinity;
    for (var y = y0; y <= y1; y += 2) {
      var score = 0;
      for (var i = 0; i < pts.length; i++) {
        var x0 = left + pts[i].x - R, x1 = x0 + 2 * R, t0 = y + pts[i].y - R, t1 = t0 + 2 * R;
        var hid = AREA - Math.max(0, Math.min(x1, vw) - Math.max(x0, 0)) * Math.max(0, Math.min(t1, vh) - Math.max(t0, 0));
        for (var k = 0; k < boxes.length; k++) {
          var r = boxes[k];
          hid += Math.max(0, Math.min(x1, r.right) - Math.max(x0, r.left)) * Math.max(0, Math.min(t1, r.bottom) - Math.max(t0, r.top));
        }
        score += Math.min(1, hid / AREA);
      }
      if (score < bestScore - 0.02) { bestScore = score; best = y; }
    }
    tl[1] = best - 1;
    br[1] = vh - best - size.y - 1;
  }

  /** The zoom that fits box vb in the map less `pad` px; the minimum zoom when the controls leave no
      room at all (a very short screen), where Leaflet would answer with its maximum zoom. */
  function boundsZoom(vb, pad) {
    var size = map.getSize();
    if (size.x - pad.x < 1 || size.y - pad.y < 1) return map.getMinZoom();
    return map.getBoundsZoom(vb, false, pad);
  }

  /** Whether box vb fits, at the minimum zoom or more, between `top` and `bottomPad` px from the
      bottom (phone width, 6 px each side). */
  function fitsBelow(vb, top, bottomPad, vh) {
    var z = boundsZoom(vb, L.point(12, top + bottomPad));
    return boundsSize(vb, z).y <= vh - top - bottomPad + 1;
  }

  /** Crowded or not (see fitView); the legend is drawn again in its new form. */
  function setCrowded(on) {
    if (legendCrowded === on) return;
    legendCrowded = on;
    renderLegend();
  }

  /** Room to keep free above the timeline for the note line: the tallest warning this timeline can
      show at any of its frames (a layer with no pictures, a picture that failed, the end of the
      forecast; each on its solid backing, often 2 or 3 lines on a phone), measured at the note's
      real width; at least one line, for the hatching note. Reserved for the whole timeline, so the
      warning that comes and goes with one frame never covers a town and playback never moves the map. */
  function noteRoom() {
    var LINE = 26;                   // one line of note text, the 8 px gap under it and a pixel to spare
    if (!data || !state.ready) return LINE;
    var room = LINE;
    noteWarningSet().forEach(function (t) { room = Math.max(room, noteSize(t, true).height + 8); });
    return Math.ceil(room);
  }

  /** Size of the note when it shows text `t`, as a warning (on its backing) or as the hatching
      note. Measured on the note itself (its width depends on the layout) and put back at once,
      before anything is painted; kept per text until the note's width changes (or the fonts
      arrive). */
  function noteSize(t, warn) {
    var w = el.bottom.clientWidth, key = (warn ? "w:" : "i:") + t;
    if (noteSizes.width !== w) noteSizes = { width: w, px: {} };
    if (!noteSizes.px[key]) {
      var n = el.note, html = n.innerHTML, hid = n.hidden, was = n.classList.contains("warn");
      n.innerHTML = '<span class="' + (warn ? "note-warn" : "note-info") + '">' + esc(t) + "</span>";
      n.hidden = false;
      n.classList.toggle("warn", !!warn);
      var r = n.getBoundingClientRect();
      noteSizes.px[key] = { width: r.width, height: r.height };
      n.innerHTML = html;
      n.hidden = hid;
      n.classList.toggle("warn", was);
    }
    return noteSizes.px[key];
  }

  /** Where the note sits above the timeline at its biggest on this timeline: the tallest warning,
      or else the one-line hatching note (shown whenever hatching is in view, as it nearly always
      is on a phone). placeCrowded counts the towns it would cover. */
  function noteBox(tlTop) {
    if (!data || !state.ready) return null;
    var big = null;
    noteWarningSet().forEach(function (t) { var s = noteSize(t, true); if (!big || s.height > big.height) big = s; });
    if (!big) {
      Object.keys(HATCH_NOTE).forEach(function (k) { var s = noteSize(HATCH_NOTE[k], false); if (!big || s.width > big.width) big = s; });
    }
    var b = el.bottom.getBoundingClientRect(), left = b.left + (b.width - big.width) / 2;
    return { left: left, right: left + big.width, top: tlTop - 8 - big.height, bottom: tlTop - 8 };
  }

  /** Fit again when the warnings this timeline can show have changed (another layer or 1h/12h, or a
      picture found to have failed) and they need a different room, unless the viewer has moved the
      map or a sheet is open. */
  function refitForNote() {
    if (CARD || !state.ready || state.userMoved || sheetState) return;
    var sig = noteWarningSet().join("\n");
    if (sig === noteFit.sig) return;
    if (Math.abs(noteRoom() - noteFit.room) > 1) fitView();
    else noteFit.sig = sig;
  }

  /** The card: Montana between the banners and the caption and "Open map" at the bottom. The caption
      can change height once the fit brings hatching into view, so fit again (at most twice) until
      it stops changing. The card can't be panned or zoomed, so a short card may zoom out further
      than the full map allows, to keep every town in sight. */
  function fitCard() {
    var vh = el.canvas.clientHeight;
    map.setMinZoom(4);
    cardFitting = true;
    try {
      for (var i = 0; i < 3; i++) {
        var h0 = el.cardChip.offsetHeight;
        var bottom = el.cardOpen.getBoundingClientRect().top;
        if (h0) bottom = Math.min(bottom, el.cardChip.getBoundingClientRect().top);
        var top = el.banners.getBoundingClientRect().bottom;
        map.fitBounds(map._viewBounds, { paddingTopLeft: [6, Math.max(6, top + 4)], paddingBottomRight: [6, Math.max(6, vh - bottom + 4)], animate: false });
        if (el.cardChip.offsetHeight === h0) break;      // moveend re-wrote the caption: same height, done
      }
    } finally { cardFitting = false; }
  }

  /** Pixel size of a lat/lon box at a zoom. */
  function boundsSize(b, z) {
    return map.project(b.getSouthEast(), z).subtract(map.project(b.getNorthWest(), z));
  }

  /** Short landscape screens (phones on their side): the legend is a column on the left and the
      timeline starts right of it (map.css, same media query). */
  function sideLegend() { return !CARD && !!(sideQuery && sideQuery.matches); }

  /** The two-column legend (map.css .legend-2col: the keys beside a shorter scale) of portrait
      phones: always on a short one, and on a taller one when fitView finds that banners and the
      note leave Montana no room under the one-column legend (they take height as a shorter screen
      would). */
  function twoColLegend() {
    return !CARD && !!(phoneQuery && phoneQuery.matches) && (!!(compactQuery && compactQuery.matches) || legendCrowded);
  }

  /** Short screens and the two-column legend get a shorter legend bar with fewer stop labels
      (map.css has no say: the bar height is set here, with the labels). */
  function compactLegend() { return !CARD && (!!(compactQuery && compactQuery.matches) || twoColLegend()); }

  /** The legend's form now, to notice when a turn or a resize changes it. */
  function legendFormNow() { return (twoColLegend() ? "2" : "1") + (compactLegend() ? "c" : ""); }

  /** Don't let the viewer zoom out past the area the pictures cover (on big screens it is small).
      Not in the card, which can't be zoomed (fitCard sets its own). */
  function fitMinZoom() {
    if (!map || !map._imageBounds || CARD) return;
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
    /** One line layer (counties, rivers, roads, borders), classed by kind and minimum zoom. */
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
      // autoPanOnFocus off: Leaflet's own keeps a focused bubble inside the map but not clear of the
      // legend or the timeline; reveal() does (keyboard focus only, so a click doesn't pan twice)
      var m = L.marker([t.lat, t.lon], { icon: icon, keyboard: !CARD, riseOnHover: true, interactive: true, autoPanOnFocus: false }).addTo(map);
      t._marker = m;
      t._el = m.getElement();
      t._bubble = t._el.querySelector(".bubble");
      t._el.setAttribute("role", CARD ? "link" : "button");
      m.on("click", function () { activateTown(t); });
      t._el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activateTown(t); }
      });
      t._el.addEventListener("focus", function () {
        if (!CARD && !sheetState && t._el.matches(":focus-visible")) reveal(L.latLng(t.lat, t.lon), townExtent(t));
      });
      t._el.addEventListener("blur", function () { if (state.ready) renderBubbles(); });   // its name was held while playing
    });
  }

  /** How far a town's bubble and name reach from its point, in px ({l, t, r, b}), for reveal(). */
  function townExtent(t) {
    var c = map.latLngToContainerPoint([t.lat, t.lon]), mapR = el.canvas.getBoundingClientRect();
    var e = { l: 21, t: 21, r: 21, b: 21 };          // the bubble and its focus ring
    var n = t._el.querySelector(".tname"), r = n && n.getBoundingClientRect();
    if (r && r.width) {
      e.l = Math.max(e.l, c.x - (r.left - mapR.left) + 3);
      e.r = Math.max(e.r, r.right - mapR.left - c.x + 3);
      e.t = Math.max(e.t, c.y - (r.top - mapR.top) + 3);
      e.b = Math.max(e.b, r.bottom - mapR.top - c.y + 3);
    }
    return e;
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
      var label = t.name + ", " + v.words + (h ? " at " + clock(Date.parse(h.time)) + ", NWS forecast" : "") + (v.over ? ", over limit" : "") +
        (t._here ? ", your location" : "");
      // a screen reader reads a focused control's new name out: while playing, the focused town's
      // name waits until playback stops (setPlaying) or focus moves on (its blur)
      if (state.playing && document.activeElement === t._el) return;
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
    refitForBanner();
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
    var all = Object.keys(L_.modes || {});
    var full = all.filter(function (m) { return (L_.modes[m] || []).length; });
    var pick = full.length ? full : all;              // a mode with frames first; an empty layer keeps its keys
    if (pick.indexOf(state.mode) < 0) state.mode = pick.indexOf("12h") >= 0 ? "12h" : (pick[0] || "12h");
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
    state.ready = true;
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
    if (n < 2 && state.playing) setPlaying(false);
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
      state.goToken++;               // a picture of the previous layer still loading must not appear now
      app.classList.remove("is-loading");
      showPicture(null);
      renderAll();
      refitForNote();                // its "no pictures" warning can take 2 or 3 lines on a phone
      return;
    }
    go(pos, {
      done: function () {
        if (!first) return;
        if (!state.userMoved && !sheetState) fitView();     // the timeline is a line shorter once "loading" goes
        // play once, unless the viewer already chose (any play, pause, step or scrub clears autoplay)
        if (state.autoplay && !CARD && !reducedMotion() && !sheetState && n > 1) {
          if (document.hidden) state.resumeOnShow = true;   // opened in a background tab: play once it is shown
          else { setPlaying(true); schedule(HOLD_MS); }
        }
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

  /** The real "now" of this update: the newest radar frame (the build's "now"), or the build time when
      the radar is stale or failed (its newest frame is then not "now"). */
  function nowRaw() {
    var radar = data.status && data.status.radar;
    return Date.parse(radar && radar.ok === false ? data.built : data.now);
  }

  /** "Now" kept inside the track: only for placing the Now tick and label (see nowOnTrack). */
  function nowMs() {
    var t = nowRaw();
    if (!state.times.length) return t;
    return clamp(t, state.times[0], state.times[state.times.length - 1]);
  }

  /** Whether the real now is on this track (within 10 minutes of it). Only then does the track show a
      Now tick and label: a forecast-only track that starts at the next whole hour has none, and its
      first frame gets its own time label instead (a frame 15 minutes after now isn't now). */
  function nowOnTrack() {
    return !!state.times.length && Math.abs(nowRaw() - nowMs()) <= 10 * MIN;
  }

  /** Small ticks under the track, one per frame where there is room, and a taller one at Now. */
  function renderTicks() {
    el.ticks.innerHTML = "";
    var w = el.ticks.clientWidth || 300, last = -99, html = "", nowOn = nowOnTrack();
    for (var i = 0; i < state.times.length; i++) {
      var x = frac(state.times[i]) * w;
      if (x - last < 6 || (nowOn && i === state.nowPos)) continue;
      last = x;
      html += '<i style="left:' + (frac(state.times[i]) * 100).toFixed(3) + '%"></i>';
    }
    if (nowOn) html += '<i class="now" style="left:' + (frac(nowMs()) * 100).toFixed(3) + '%"></i>';
    el.ticks.innerHTML = html;
  }

  /** Time labels under the track: "Now" first (or, when now isn't on the track, the first frame's
      own time), then whole hours (or quarter or half hours on a short track) that fit without
      touching each other at the current width. A long track counts in steps of 2 hours or more,
      like the reference ("8 AM Now 12 PM 2 PM"), so the labels stay calm on a wide screen too. */
  function layoutLabels() {
    var box = el.labels, w = box.clientWidth;
    box.innerHTML = "";
    var n = state.times.length;
    if (!n || n < 2 || !w) return;
    var t0 = state.times[0], t1 = state.times[n - 1], span = t1 - t0;
    var nowOn = nowOnTrack(), nowT = nowOn ? nowMs() : t0;      // the first label: Now, or the first frame
    var steps = span > 4 * HOUR ? [2 * HOUR, 3 * HOUR, 4 * HOUR, 6 * HOUR] : [15 * MIN, 30 * MIN, HOUR, 2 * HOUR];
    var nowEl = nowOn ? makeLabel("Now", null, true) : makeLabel(null, t0, false);
    var nowBox = place(nowEl, frac(nowT) * w);
    var GAP = 8, EDGE = 6, SPACING = 46;   // px between labels; px between steps so the scale stays calm
    for (var s = 0; s < steps.length; s++) {
      if (steps[s] / span * w < SPACING && s < steps.length - 1) continue;
      var marks = [], okAll = true;
      for (var t = Math.ceil(t0 / (15 * MIN)) * 15 * MIN; t <= t1; t += 15 * MIN) {
        if (!onStep(t, steps[s])) continue;
        if (Math.abs(t - nowT) < 1) continue;
        marks.push(t);
      }
      var placed = [], els = [];
      for (var k = 0; k < marks.length; k++) {
        var lab = makeLabel(null, marks[k], false);
        var b = place(lab, frac(marks[k]) * w);
        els.push(lab);
        if (b.left < -EDGE || b.right > w + EDGE) { lab.remove(); els.pop(); continue; }
        if (b.left < nowBox.right + GAP && b.right > nowBox.left - GAP) { lab.remove(); els.pop(); continue; }   // too close to "Now": left out
        var hit = false;
        for (var q = 0; q < placed.length; q++) if (b.left < placed[q].right + GAP && b.right > placed[q].left - GAP) { hit = true; break; }
        if (hit) { okAll = false; break; }      // hour labels touching: try a wider step
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
      if (p.minute === "00") s.innerHTML = esc(p.hour) + "<small>\u00a0" + esc((p.dayPeriod || "").toLowerCase() + zoneMark(p)) + "</small>";
      else s.textContent = p.hour + ":" + p.minute + zoneMark(p);
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
      subtitle says "loading" (see holdPicture for what stays on screen meanwhile). While playing,
      the next step is scheduled from here, whatever started this frame (playback, a layer or
      1h/12h switch), so playback can't stall with the button still saying it plays. */
  function go(pos, opts) {
    var n = state.frames.length;
    if (!n) return;
    pos = clamp(pos, 0, n - 1);
    state.pos = pos;
    var f = state.frames[pos], token = ++state.goToken, c = cache[f.src];
    // a picture that failed a while ago is asked for again (one dropped request on a phone network
    // must not blank it for good); playback skips failed pictures, so only the viewer's own step
    // or scrub retries, at most once per RETRY_MS
    if (c && c.ok === false && Date.now() - c.failedAt >= RETRY_MS) { delete cache[f.src]; f._failed = false; }
    renderAll();
    load(f.src, function (ok) {
      if (token !== state.goToken) return;
      f._failed = !ok;
      app.classList.remove("is-loading");
      showPicture(ok ? f.src : null, { layer: state.layer, kind: f.kind });
      renderNote();
      refitForNote();                // a new layer or mode, or a picture found to have failed
      if (CARD) renderCardChip();
      if (opts && opts.done) opts.done(ok);
      if (!CARD) preload();          // the rest of this layer, once one of its pictures shows
      continuePlayback();
    });
    if (cache[f.src] && cache[f.src].ok === null) {
      app.classList.add("is-loading");
      holdPicture(f);
    }
  }

  /** While frame f loads, the picture on screen stays only if it is the same layer and the same kind
      (radar or model), dimmed; otherwise it goes, so a radar picture never sits under a forecast
      title or a precipitation picture under the temperature legend (evidence is never blended).
      A swap still in flight is cancelled: it would put up a picture the title no longer describes. */
  function holdPicture(f) {
    if (!overlays.length) return;
    swapToken++;
    var cur = overlays[front], nxt = overlays[1 - front];
    instantly(nxt, 0);
    if (sameKind(cur._meta, { layer: state.layer, kind: f.kind })) cur.setOpacity(0.45);
    else instantly(cur, 0);
  }

  /** Whether two pictures are the same layer and the same kind of evidence (radar or model). */
  function sameKind(a, b) { return !!(a && b && a.layer === b.layer && a.kind === b.kind); }

  /** Set an overlay's opacity at once, without the crossfade. */
  function instantly(ov, v) {
    var img = ov.getElement();
    if (!img) { ov.setOpacity(v); return; }
    img.classList.add("instant");
    ov.setOpacity(v);
    void img.offsetWidth;            // apply the change before the fade comes back
    img.classList.remove("instant");
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
      img.onerror = function () { c.ok = false; c.failedAt = Date.now(); flush(c); checkForUpdate(); };
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

  /** Crossfade the two overlays to a loaded picture (no fade with reduced motion); null hides both.
      `meta` ({layer, kind}) records what the picture is, for holdPicture. A picture of another layer
      or kind (radar after model, or the reverse) replaces the old one at once instead of fading
      through it, so the two are never seen blended. */
  function showPicture(src, meta) {
    if (!overlays.length) return;
    var tok = ++swapToken, cur = overlays[front], nxt = overlays[1 - front];
    if (!src) { instantly(cur, 0); instantly(nxt, 0); cur._meta = nxt._meta = null; return; }
    if (cur._url === src) { cur._meta = meta || null; cur.setOpacity(1); instantly(nxt, 0); return; }
    var img = nxt.getElement();
    instantly(nxt, 0);               // stop any fade on the back picture before changing it
    var cut = !sameKind(cur._meta, meta);
    var done = function () {
      if (tok !== swapToken) return;
      nxt._meta = meta || null;
      if (cut) { instantly(nxt, 1); instantly(cur, 0); }
      else { nxt.setOpacity(1); cur.setOpacity(0); }
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
    // a screen reader reads every value change of a focused slider: while playing, its value waits
    // until playback stops (setPlaying); the knob and the title above still move
    if (!(state.playing && document.activeElement === el.range)) {
      el.range.value = String(ms);
      el.range.setAttribute("aria-valuetext", (f.kind === "radar" ? "Radar, " : "Forecast, ") + dayClock(ms) + ", " +
        sourceWords(f) + nowWords(ms, f));
    }
    var pct = (frac(ms) * 100).toFixed(3) + "%";
    el.fill.style.width = pct;
    el.knob.style.left = pct;
  }

  /** What a screen reader hears about "Now" for the "Now" frame, matching the visible Now tick:
      ", now" only when that frame is within 10 minutes of it. When the radar is late its newest
      frame is the "latest radar picture", not now; the first model hour of the temperature and
      gust layers is "this hour". Other frames say nothing (a frame 10 minutes after now isn't now). */
  function nowWords(ms, f) {
    if (state.pos !== state.nowPos) return "";
    var now = nowRaw();              // the real now: the clamped one (nowMs) is only for placing the tick
    if (Math.abs(ms - now) <= 10 * MIN) return ", now";
    if (f.kind === "radar") return ", latest radar picture";
    return Math.floor(now / HOUR) * HOUR === ms ? ", this hour" : "";
  }

  /** The source in plain words: radar estimate or model forecast, never blended. */
  function sourceWords(f) {
    var sample = /^SAMPLE/.test(f.source || "");
    if (f.kind === "radar") return sample ? "sample, not NOAA radar" : "NOAA radar estimate";
    var run = f.run ? ", run " + clock(Date.parse(f.run)) : "";
    return sample ? "sample, not the HRRR model" : "HRRR model" + run;
  }

  /** The line above the timeline: a failed picture, the end of the forecast, a layer with no pictures
      at all (warnings, on a solid backing), and what hatching in view means (like the reference's
      "Forecast is not available in some areas"). Plain words; a failure never looks like clear sky. */
  function renderNote() {
    var warn = noteWarnings(state.pos).join(" "), info = "";
    var f = state.frames[state.pos];
    // same rule as the legend key (whenever hatching is in view); a warning takes the line alone,
    // so it stays short, and the key still names the hatching
    if (f && !warn) info = hatchNote();
    var html = warn ? '<span class="note-warn">' + esc(warn) + "</span>" : info ? '<span class="note-info">' + esc(info) + "</span>" : "";
    var changed = el.note._html !== html;
    if (changed) { el.note.innerHTML = html; el.note._html = html; }
    el.note.hidden = !html || CARD;
    el.note.classList.toggle("warn", !!warn);
    if (changed) tidyLabels();
  }

  /** The note's warnings at timeline position `pos` (any position when the layer has no pictures):
      no pictures at all and why, a picture that failed, no model forecast after the last radar
      picture. Shared by renderNote and noteRoom, so the room fitted is the room the note takes. */
  function noteWarnings(pos) {
    var n = state.frames.length, st = data.status || {}, warns = [];
    if (!n) {
      var why = [];
      if (state.layer === "precip" && st.radar && !st.radar.ok) why.push("radar: " + st.radar.detail);
      if (st.forecast && !st.forecast.ok) why.push("model forecast: " + st.forecast.detail);
      warns.push("No " + LAYER_WORD[state.layer].toLowerCase() + " pictures in this update" + (why.length ? " (" + why.join("; ") + ")" : "") +
        ". This is not an all-clear.");
      return warns;
    }
    var f = state.frames[pos];
    if (knownFailed(f)) warns.push("The " + clock(state.times[pos]) + " picture didn't load. This is not an all-clear.");
    if (pos === n - 1 && f.kind === "radar") {
      warns.push("No model forecast after now in this update" + (st.forecast && !st.forecast.ok ? " (" + st.forecast.detail + ")" : "") + ".");
    }
    return warns;
  }

  /** Every different warning the note can show on this timeline (what noteRoom makes room for). */
  function noteWarningSet() {
    var out = [], seen = {};
    for (var i = 0; i < Math.max(1, state.frames.length); i++) {
      var t = noteWarnings(i).join(" ");
      if (t && !seen[t]) { seen[t] = true; out.push(t); }
    }
    return out;
  }

  /** A picture known to have failed: shown and failed, or failed while it was preloaded. */
  function knownFailed(f) { return !!(f._failed || (cache[f.src] && cache[f.src].ok === false)); }

  // ------------------------------------------------------------------ legend

  /** Legend for the active layer: title, gradient bar with its stop labels, note and keys. */
  function renderLegend() {
    var L_ = layer();
    el.legendTitle.textContent = L_.title || LAYER_WORD[state.layer];
    var stops = L_.legend || [];
    el.legendScale.hidden = !stops.length;
    el.legendBar.style.background = L_.gradient || "";
    legendForm = legendFormNow();
    app.classList.toggle("legend-2col", twoColLegend());
    var barH = compactLegend() ? 64 : Math.max(96, (stops.length - 1) * 16);
    var shown = thinStops(stops, barH);
    el.legendScale.style.setProperty("--bar-h", barH + "px");
    el.legendStops.innerHTML = stops.map(function (s, i) {
      if (!shown[i]) return "";
      var pos = Number(s.pos) || 0;
      return '<li style="--pos:' + pos + '"' + (s.limit ? ' class="limit"' : "") + ">" + esc(s.label) + (s.limit ? " limit" : "") + "</li>";
    }).join("");
    var w = 0;                       // the scale's width for the two-column legend of short phones
    [].forEach.call(el.legendStops.children, function (li) { w = Math.max(w, li.offsetWidth); });
    if (w) el.legendScale.style.setProperty("--scale-w", Math.ceil(16 + w + 2) + "px");
    el.legendNote.textContent = L_.legend_note || "";
    renderKeys();
  }

  /** Which stop labels fit on a bar `barH` px tall without touching (labels are 12.5 px): the top,
      the bottom and a roofing limit always; the others where there is room. The bar keeps every
      colour either way. */
  function thinStops(stops, barH) {
    var gap = 14 / barH;
    var keep = stops.map(function (s, i) { return i === 0 || i === stops.length - 1 || !!s.limit; });
    stops.forEach(function (s, i) {
      if (keep[i]) return;
      var p = Number(s.pos) || 0;
      keep[i] = stops.every(function (o, j) { return !keep[j] || Math.abs((Number(o.pos) || 0) - p) >= gap; });
    });
    return keep;
  }

  /** Keys under the legend: alerts that have no outline (when there are any), what the town numbers
      are (the NWS forecast, not the coloured model field under them; always shown, phones too),
      then only what is on the map now:
      hatching (gaps in a picture: for the whole timeline when any frame has them; the band outside
      the pictures), the limit ring, warning outline colours and storm-report circles. Every colour
      carries its word. */
  function renderKeys() {
    if (!data) return;
    var keys = [];
    keys.push(["key-bubble", state.layer === "wind" ? "Town numbers: NWS gust forecast, mph" : "Town numbers: NWS forecast, \u00b0F"]);
    var hatch = hatchInView();
    if (hatch.key) keys.push(["key-hatch", hatch.key]);
    if (hatch.outside) keys.push(["key-hatch-out", OUTSIDE_WORDS]);
    if (data.towns.some(function (t) { return t._over && townVisible(t); })) keys.push(["key-ring", ringWords()]);
    if (state.warnings) (state.alertKinds || []).forEach(function (k) { keys.push(["key-hz key-" + k, KIND_WORD[k] + " area (NWS)"]); });
    if (state.reports && data.reports.length) {
      if (data.reports.some(function (r) { return r.kind === "hail"; })) keys.push(["key-hail", "Hail report (size)"]);
      if (data.reports.some(function (r) { return r.kind === "wind"; })) keys.push(["key-wind", "Wind report"]);
    }
    if (locState && locState.here && townVisible(locState.here)) keys.push(["key-here", "Your location"]);
    var html = keys.map(function (k) { return '<li><span class="key ' + k[0] + '" aria-hidden="true"></span>' + esc(k[1]) + "</li>"; }).join("");
    // alerts issued by county or zone have no outline to draw (AGENTS.md rule 6: null geometry never
    // means "no alert"): one row says how many, whatever the Warnings switch says, and opens the List.
    // First, so a legend that scrolls (a phone on its side) shows it without scrolling.
    var n = noOutlineCount();
    if (n) {
      html = '<li><button type="button" class="key-btn" data-open-list><span class="key key-list" aria-hidden="true"></span>' +
        esc(n + (n > 1 ? " NWS alerts have" : " NWS alert has") + " no outline (county or zone): see List") + "</button></li>" + html;
    }
    if (el.legendKeys._html !== html) {
      el.legendKeys.innerHTML = html;
      el.legendKeys._html = html;
      tidyLabels();                            // the "Map data" link under the legend may have moved
    }
  }

  /** How many active alerts have no outline (issued by county or zone). */
  function noOutlineCount() {
    return ((data && data.alerts && data.alerts.items) || []).filter(function (a) { return !a.geometry; }).length;
  }

  /** The hatching in view, of two kinds. `inside`: areas a picture has no data for (no radar coverage,
      or masked model cells; a heavier hatch drawn in the picture), worded for the frame shown so a
      model frame never says "radar". `outside`: the band outside the pictures' box, which this map
      doesn't draw (every layer and frame, a hairline, see drawOutsideMask). NOAA has data there, so
      it is never called a coverage gap; it is hatched so it never looks dry. */
  function hatchInView() {
    var h = { inside: "", outside: false, key: "" };
    if (!map || !map._imageBounds) return h;
    var f = state.frames[state.pos];
    var words = f && f.kind === "radar" ? "No radar coverage" : "No model data";
    if (f && f.nodata && !f._failed) h.inside = words;
    // the legend's key for gaps stays for the whole timeline when any of its frames has one, so the
    // legend keeps its height (and the fit its room) during playback; worded for the frame shown
    if (f && state.frames.some(function (x) { return x.nodata; })) h.key = words;
    h.outside = !map._imageBounds.contains(map.getBounds());
    return h;
  }

  /** The note line's words for the hatching in view, or "" when none is in view. */
  function hatchNote() {
    var h = hatchInView(), f = state.frames[state.pos];
    if (h.inside) return f.kind === "radar" ? (h.outside ? HATCH_NOTE.radarOut : HATCH_NOTE.radar) : (h.outside ? HATCH_NOTE.modelOut : HATCH_NOTE.model);
    return h.outside ? HATCH_NOTE.outside : "";
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
    state.autoplay = false;          // the viewer (or a sheet) chose: the first picture won't start playback
    var was = state.playing;
    state.playing = !!on && state.frames.length > 1;
    el.play.setAttribute("aria-pressed", state.playing ? "true" : "false");
    clearTimeout(state.timer);
    state.timer = null;
    if (state.playing) schedule(STEP_MS);
    else if (was && data && state.ready) { renderTimeline(); renderBubbles(); }   // the held slider value and town name
  }

  /** Next playback step after `ms`. */
  function schedule(ms) {
    clearTimeout(state.timer);
    state.timer = setTimeout(step, ms);
  }

  /** While playing and no step is waiting: the next step after the frame now on screen (called by
      go once its picture is ready). Holds on Now and on the last frame. */
  function continuePlayback() {
    if (!state.playing || state.timer) return;
    var n = state.frames.length;
    schedule(state.pos === state.nowPos || state.pos === n - 1 ? HOLD_MS : STEP_MS);
  }

  /** One playback step: the next frame (skipping pictures that failed); go() schedules the one after
      once this picture is ready; loops. */
  function step() {
    state.timer = null;
    if (!state.playing) return;
    var n = state.frames.length, next = (state.pos + 1) % n, guard = 0;
    while (knownFailed(state.frames[next]) && guard++ < n) next = (next + 1) % n;   // failed, shown or preloaded
    go(next);
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
    r.addEventListener("pointerdown", onScrubStart);
    r.addEventListener("pointermove", function (e) { if (state.dragging) scrubTo(e.clientX); });
    r.addEventListener("pointerup", onScrubEnd);
    r.addEventListener("pointercancel", onScrubEnd);
    r.addEventListener("lostpointercapture", onScrubEnd);
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

    el.legendKeys.addEventListener("click", function (e) {
      var b = e.target.closest("[data-open-list]");
      if (b) openList(b);
    });
    el.sheetClose.addEventListener("click", closeSheet);
    el.scrim.addEventListener("click", function () {
      // the second click of a double-click on a bubble or an outline lands on the scrim the first one
      // put under the pointer: it must not close the sheet that click just opened (a time guard, as
      // iPhone Safari counts every tap as a single click)
      if (Date.now() - sheetOpenedAt < 400) return;
      closeSheet();
    });
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

  /** A finger or mouse on the timeline: jump to that spot and follow the drag anywhere along the
      track (a native slider on iPhone only moves from its thumb, and this one has no visible thumb). */
  function onScrubStart(e) {
    if (el.range.disabled || (e.pointerType === "mouse" && e.button !== 0)) return;
    e.preventDefault();
    try { el.range.focus({ preventScroll: true }); } catch (err) { el.range.focus(); }
    state.dragging = true;
    setPlaying(false);
    try { el.range.setPointerCapture(e.pointerId); } catch (err) { /* capture is a nicety */ }
    scrubTo(e.clientX);
  }

  /** End of a drag on the timeline. */
  function onScrubEnd() { state.dragging = false; }

  /** Show the frame nearest to a screen x on the track. */
  function scrubTo(x) {
    var n = state.times.length;
    if (n < 2) return;
    var r = el.fill.parentNode.getBoundingClientRect();
    var t = state.times[0] + clamp((x - r.left) / r.width, 0, 1) * (state.times[n - 1] - state.times[0]);
    var k = nearest(t);
    if (k !== state.pos) go(k);
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
    // the map itself too: a click or drag on it focuses it (Leaflet's keys don't use Space)
    if (e.key === " " && (t === document.body || t === document.documentElement || t === el.canvas)) { e.preventDefault(); setPlaying(!state.playing); return; }
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && onPage && tag !== "INPUT") {
      e.preventDefault();
      stepBy(e.key === "ArrowLeft" ? -1 : 1);
    }
  }

  /** Open or close the layer menu (focus goes in on open and back to the button on close). While it
      is open the top controls are lifted over the timeline (.top.menu-open): both are stacking
      contexts of their own, so the menu's own z-index can't do it. */
  function toggleLayers(open, refocus) {
    el.layers.hidden = !open;
    el.top.classList.toggle("menu-open", !!open);
    el.layersBtn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      fitLayersMenu();
      var checked = el.layers.querySelector("input[name=layer]:checked") || el.layers.querySelector("input");
      if (checked) checked.focus();
    } else if (refocus) el.layersBtn.focus();
  }

  /** The layer menu ends above the bottom of the screen and scrolls inside when it is taller (a phone
      on its side). Measured, since its top moves with the banners. */
  function fitLayersMenu() {
    el.layers.style.maxHeight = "";
    var room = app.getBoundingClientRect().bottom - el.layers.getBoundingClientRect().top - 12;
    el.layers.style.maxHeight = Math.max(120, Math.floor(room)) + "px";
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

  /** A small banner at the top. kind: warn (announced at once, role "alert") | info. Replaces an
      earlier one with the same id. An open sheet moves to stay clear of it. */
  function banner(kind, html, id) {
    if (id && byId(id)) byId(id).remove();
    var p = document.createElement("p");
    p.className = "banner banner-" + kind;
    if (id) p.id = id;
    if (kind === "warn") p.setAttribute("role", "alert");
    p.innerHTML = html;
    el.banners.appendChild(p);
    if (sheetState) placeSheet();
    return p;
  }

  /** A banner that came or went (or keys that grew the legend) can cover towns: fit again, unless the
      viewer has moved the map or a sheet is open. */
  function refitForBanner() {
    if (state.ready && !state.userMoved && !sheetState) fitView();
  }

  /** A warning banner with a Reload button (not in the card, whose page has its own). */
  function reloadBanner(id, words) {
    var b = banner("warn", "<strong>" + esc(words) + "</strong> Reload for the latest." +
      (CARD ? "" : ' <button type="button" class="banner-btn" data-reload>Reload</button>'), id);
    var btn = b.querySelector("[data-reload]");
    if (btn) btn.addEventListener("click", function () { location.reload(); });
    refitForBanner();
    return b;
  }

  /** The first picture that fails may be gone because the site was rebuilt since this page opened
      (each model run gives the model pictures new names, and each deploy replaces the whole site).
      Ask for map.json past every cache; when it is newer than ours, say so with a Reload button.
      At most once a minute, and not again once an update is found. */
  function checkForUpdate() {
    if (CARD || !data || byId("update-banner") || Date.now() - updateChecked < MIN) return;
    updateChecked = Date.now();
    var url = app.getAttribute("data-map").split("?")[0] + "?check=" + Date.now();
    fetchJSON(url, { credentials: "same-origin", cache: "no-store" }).then(function (d) {
      if (d && d.built && data && d.built !== data.built) reloadBanner("update-banner", "This map was updated after you opened it.");
    }, function () { /* offline too: the note already says the picture didn't load */ });
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

  /** "This map is 40 minutes old" once the page is older than the rebuild cycle allows (in hours or
      days for older pages). It is announced once, when it appears (role "alert"); the age then keeps
      counting on screen without being read out again every minute. */
  function checkAge() {
    if (!builtMs) return;
    var minutes = Math.round((Date.now() - builtMs) / MIN);
    if (minutes <= STALE_MIN) return;
    var words = "This map is " + ageWords(minutes) + " old.";
    var b = byId("age-banner");
    if (b) {
      b.removeAttribute("role");
      var strong = b.querySelector("strong");
      if (strong.textContent !== words) strong.textContent = words;
      return;
    }
    reloadBanner("age-banner", words);
  }

  /** "40 minutes", "about 3 hours", "about 3 days". */
  function ageWords(minutes) {
    if (minutes < 90) return minutes + " minutes";
    var hours = Math.round(minutes / 60);
    return hours < 36 ? "about " + hours + " hours" : "about " + Math.round(hours / 24) + " days";
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
      el.locateBtn.classList.add("is-on");
      var ll = L.latLng(pos.coords.latitude, pos.coords.longitude), acc = pos.coords.accuracy || 0;
      if (locLayer) locLayer.remove();
      var dot = L.marker(ll, { pane: "loc", interactive: false, keyboard: false,
        icon: L.divIcon({ className: "loc-dot", html: "<i></i>", iconSize: [16, 16], iconAnchor: [8, 8] }) });
      locLayer = L.layerGroup([
        L.circle(ll, { radius: acc, renderer: renderers.loc, className: "loc-acc", interactive: false }), dot
      ]).addTo(map);
      locState = { ll: ll, dot: dot, here: null };
      var best = null, bestKm = Infinity;
      data.towns.forEach(function (t) {
        var km = ll.distanceTo([t.lat, t.lon]) / 1000;
        if (km < bestKm) { bestKm = km; best = t; }
      });
      var inside = map._imageBounds && map._imageBounds.contains(ll);
      if (inside) { state.userMoved = true; map.setView(ll, Math.max(map.getZoom(), 7), { animate: !reducedMotion() }); }
      var words = inside ? "Showing your location." : "You're outside the area this map covers.";
      if (best) {
        var mi = Math.round(bestKm * 0.621371);
        el.near.textContent = "Nearest town: " + best.name + " \u00b7 " + mi + " mi";
        el.near.setAttribute("data-town", best.slug);
        el.near.setAttribute("aria-label", "Nearest town: " + best.name + ", " + mi + " miles. Open its forecast.");
        el.near.hidden = false;
        words += " Nearest town: " + best.name + ", " + (mi < 1 ? "under a mile." : mi + (mi === 1 ? " mile." : " miles."));
      }
      toast(words);                  // the polite live region: a screen reader hears that it worked
      placeLocDot();
    }, function () {
      el.locateBtn.classList.remove("is-busy");
      toast("Location isn't available.");
    }, { enableHighAccuracy: false, timeout: 12000, maximumAge: 300000 });
  }

  /** The location dot, or a blue ring on the bubble it would sit on: drawn over a bubble, the dot
      would hide that town's number (the town the "Nearest town" chip names). Checked again at every
      zoom, as their distance on screen changes. */
  function placeLocDot() {
    if (!locState || !data) return;
    var p = map.latLngToLayerPoint(locState.ll), here = null, best = 15 + 8 + 2;   // bubble and dot radii, a little air
    data.towns.forEach(function (t) {
      if (t.minor && map.getZoom() < 7) return;
      var d = map.latLngToLayerPoint([t.lat, t.lon]).distanceTo(p);
      if (d < best) { best = d; here = t; }
    });
    locState.here = here;
    data.towns.forEach(function (t) { t._here = t === here; t._el.classList.toggle("is-here", t._here); });
    var dotEl = locState.dot.getElement();
    if (dotEl) dotEl.classList.toggle("is-hidden", !!here);
    if (state.ready) { renderBubbles(); renderKeys(); }
  }

  // ------------------------------------------------------------------ sheets (town, alert, report, list)

  /** Open the bottom sheet (a modal dialog). The opener gets focus back when it closes. Android's
      back button or gesture closes it (a CloseWatcher, where the browser has one), as Escape and the
      Close button do; the page's history is left alone. */
  function openSheet(kind, title, html, opener, opts) {
    opts = opts || {};
    if (!sheetState) {
      sheetState = { opener: opener || document.activeElement,
        view: { center: map.getCenter(), zoom: map.getZoom(), userMoved: state.userMoved } };   // closeSheet puts it back
      sheetOpenedAt = Date.now();
      setPlaying(false);
      // the map can't be moved while a sheet is open, so its pan limits are lifted until it closes:
      // they would undo the pan that keeps a town in sight above a tall sheet (reveal)
      if (map.options.maxBounds) { panLimits = map.options.maxBounds; map.setMaxBounds(null); }
      if (window.CloseWatcher) {
        try {
          sheetState.watcher = new CloseWatcher();
          sheetState.watcher.onclose = function () { closeSheet(); };
        } catch (e) { /* not allowed here: Escape and Close still work */ }
      }
    }
    sheetState.kind = kind;
    sheetState.ll = null;            // openTown sets it: the town to keep in sight on a resize
    sheetState.back = !!opts.back;
    toggleLayers(false);
    el.sheet.className = "glass sheet sheet-" + kind;
    el.sheetBack.hidden = !opts.back;
    el.sheetTitle.textContent = title;
    el.sheetBody.innerHTML = (data && data.sample ? '<p class="sample-tag">Sample data: invented to review the layout. It is not weather.</p>' : "") + html;
    el.sheetBody.scrollTop = 0;
    el.sheet.hidden = false;
    el.scrim.hidden = false;
    placeSheet();
    setInert(true);
    var f = opts.focus ? el.sheetBody.querySelector(opts.focus) : null;
    (f || el.sheetTitle).focus();
  }

  /** Keep an open sheet clear of the banners at the top, so a source warning ("This is not an
      all-clear") is never hidden behind it: a side panel (wide screens) starts below the banners it
      would cover, and a bottom sheet (phones) stops short of them. map.css reads --sheet-top. */
  function placeSheet() {
    var b = el.banners.getBoundingClientRect(), s = el.sheet.getBoundingClientRect();
    var clash = b.height > 0 && b.right > s.left && b.left < s.right;
    if (clash) el.sheet.style.setProperty("--sheet-top", Math.ceil(b.bottom + 8) + "px");
    else el.sheet.style.removeProperty("--sheet-top");
  }

  /** Close the sheet and put focus back where it came from. If the sheet panned the map to keep a
      town in sight, the map goes back to where it was (the viewer can't move it while a sheet is
      open). A ?town= link has done its job: the address drops it, so a reload doesn't reopen it. */
  function closeSheet() {
    if (!sheetState) return;
    var opener = sheetState.opener, v = sheetState.view, panned = sheetState.revealed, resized = sheetState.resized;
    if (sheetState.watcher) { sheetState.watcher.onclose = null; sheetState.watcher.destroy(); }
    sheetState = null;
    el.sheet.hidden = true;
    el.scrim.hidden = true;
    setInert(false);
    // the pan limits come back once the map is back where it was (Leaflet fires moveend even for a
    // pan of zero, and at once without animation)
    var limit = function () { if (panLimits && !sheetState) map.setMaxBounds(panLimits); };
    if (panned && v && Math.abs(map.getZoom() - v.zoom) < 1e-6) {
      state.userMoved = v.userMoved;
      if (resized && !v.userMoved) { fitView(); limit(); }      // turned while open: fit the new screen
      else { map.once("moveend", limit); map.panTo(v.center, { animate: !reducedMotion() }); }
    } else limit();
    if (new URLSearchParams(location.search).has("town")) saveUrl();
    if (opener && !document.contains(opener) && opener.hasAttribute && opener.hasAttribute("data-open-list")) {
      opener = el.legendKeys.querySelector("[data-open-list]");      // the legend keys were drawn again
    }
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

  /** Tab and Shift+Tab wrap around inside the modal sheet: `inert` keeps focus off the page behind
      it, but alone it lets Tab leave the page for the browser's own controls. */
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
        // the build lists every alert a town check found (build.py add_town_alerts); this is a backstop
        if (!a) return '<p class="warn">An NWS alert is active here, but this map update has no details for it. The full forecast page below lists it.</p>';
        return alertRow(a);
      }).join("") + "</div>";
    }
    html += '<p><a class="go" href="' + esc(t.url) + '">Full forecast for ' + esc(t.name) + "</a></p>";
    openSheet("town", t.name, html, opener, { back: back });
    sheetState.ll = L.latLng(t.lat, t.lon);
    reveal(sheetState.ll, townExtent(t));
  }

  /** Pan just enough that a town is in sight, clear of everything drawn over the map: the open sheet,
      the legend, the "Map data" link, the close button, the right-hand buttons, the banners, the
      timeline, the note and the location chip (like a maps app does when a place card opens).
      `ext` is how far the town reaches from its point ({l, t, r, b} px: the bubble and its name).
      Of the clear spots the nearest to where the town is now wins; with no clear spot for the name
      too, one for the bubble alone; with none at all (a sheet as tall as the screen), the map stays. */
  function reveal(ll, ext) {
    var size = map.getSize(), p = map.latLngToContainerPoint(ll), mapR = el.canvas.getBoundingClientRect();
    var boxes = [];
    [el.sheet, el.legend, el.legendWrap.querySelector(".mapdata"), el.top.querySelector(".close"), el.buttons,
      el.timeline, el.note, el.near].concat([].slice.call(el.banners.children)).forEach(function (x) {
      if (!x || x.hidden || x.offsetParent === null) return;
      var r = x.getBoundingClientRect();
      if (r.width && r.height) boxes.push({ l: r.left - mapR.left, t: r.top - mapR.top, r: r.right - mapR.left, b: r.bottom - mapR.top });
    });
    /** Whether the town, its point at x, y, would be clear of every box and inside the map. */
    function clear(e, x, y) {
      if (x - e.l < 0 || y - e.t < 0 || x + e.r > size.x || y + e.b > size.y) return false;
      for (var k = 0; k < boxes.length; k++) {
        var b = boxes[k];
        if (x + e.r > b.l && x - e.l < b.r && y + e.b > b.t && y - e.t < b.b) return false;
      }
      return true;
    }
    var exts = [ext || { l: 24, t: 24, r: 24, b: 24 }, { l: 24, t: 24, r: 24, b: 24 }];
    for (var i = 0; i < exts.length; i++) {
      var e = exts[i];
      if (clear(e, p.x, p.y)) return;
      var best = null, bestD = Infinity, STEP = 6;
      for (var y = e.t; y <= size.y - e.b; y += STEP) {
        for (var x = e.l; x <= size.x - e.r; x += STEP) {
          var d = (x - p.x) * (x - p.x) + (y - p.y) * (y - p.y);
          if (d < bestD && clear(e, x, y)) { bestD = d; best = [x, y]; }
        }
      }
      if (best) {
        state.userMoved = true;
        if (sheetState) sheetState.revealed = true;
        map.panBy([p.x - best[0], p.y - best[1]], { animate: !reducedMotion() });
        return;
      }
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
    html += "<h3>Official alerts" + (a.ok ? " (" + items.length + ")" : "") + "</h3>";     // a failed check has no count to give
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
      var rst = data.status && data.status.reports, repFailed = !!(rst && !rst.ok);
      html += "<h3>Storm reports, last 3 days" + (repFailed ? "" : " (" + data.reports.length + ")") + "</h3>";
      if (repFailed) {          // missing input is "data unavailable", never a count of zero (AGENTS.md rule 5)
        html += '<p class="warn">Storm reports didn\u2019t all load (' + esc(rst.detail) + "). Data unavailable for those days; " +
          "no report is not \u201cno hail\u201d.</p>";
      }
      if (data.reports.length) {
        html += '<div class="rows">' + data.reports.map(function (r, i) {
          var what = r.kind === "hail" ? (r.size_in != null ? r.size_in.toFixed(2) + " in hail" : "Hail") : (r.mph != null ? "Wind " + r.mph + " mph" : "Wind, speed unknown");
          return '<button type="button" class="row" data-report="' + i + '" data-key="r-' + i + '"><span class="row-main"><span class="row-title">' + esc(what) + "</span>" +
            '<span class="row-meta">' + esc(r.place) + ", " + esc(r.state) + " \u00b7 " + esc(dateClock(Date.parse(r.time))) + "</span></span></button>";
        }).join("") + "</div>";
      } else if (!repFailed) html += "<p>No reports. No report is not \u201cno hail\u201d.</p>";
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

  /** The card: latest frame, outlines and bubbles; no controls except "Open map". The Now page's
      caption names the same picture: build.py map_card() picks the frame the way setLayer and
      buildTimeline open the card (precipitation, 12h timeline, now_index). Change both together. */
  function setupCard() {
    el.cardOpen.href = "map.html" + layerQuery("?");
    el.canvas.removeAttribute("aria-describedby");   // its keys and List button aren't in the card
    renderCardChip();
  }

  /** The card's caption: which picture this is and when, or why there is none (the card has no
      note line, so a missing picture is said here), then what hatching in view means, with the
      legend's hatch swatch. Short lines, so it stays small on a phone; when its height changes the
      card is fitted again so it never covers a town. */
  function renderCardChip() {
    var f = state.frames[state.pos], h0 = el.cardChip.offsetHeight;
    var warn = !f || !!f._failed, main;
    if (!f) main = "No " + LAYER_WORD[state.layer].toLowerCase() + " picture in this update. Not an all-clear.";
    else if (f._failed) main = "The " + clock(state.times[state.pos]) + " picture didn\u2019t load. Not an all-clear.";
    else {
      // a sample card also shows the "Sample data ... not weather" banner, so a short name fits one line
      var sample = /^SAMPLE/.test(f.source || "");
      main = (f.kind === "radar" ? (sample ? "Sample radar" : "NOAA radar estimate") :
        (sample ? "Sample forecast" : "HRRR model forecast")) + " \u00b7 " + clock(state.times[state.pos]);
    }
    var h = f && !f._failed ? hatchInView() : { inside: "", outside: false };
    var hatch = h.inside || (h.outside ? OUTSIDE_WORDS : "");
    var html = '<span class="card-main">' + esc(main) + "</span>" + (hatch ? '<span class="card-hatch"><span class="key ' +
      (h.inside ? "key-hatch" : "key-hatch-out") + '" aria-hidden="true"></span>' +
      '<span class="visually-hidden">. Hatched areas: </span>' + esc(hatch) + "</span>" : "");
    // the Storm reports card: alerts without an outline aren't on it (the Now page card sits beside
    // the full alert list, so it needn't say)
    var n = state.reports ? noOutlineCount() : 0;
    if (n) html += '<span class="card-alerts"><span class="visually-hidden">. </span>' + esc(n + (n > 1 ? " NWS alerts have" : " NWS alert has") + " no outline: see the Now page") + "</span>";
    if (el.cardChip._html !== html) { el.cardChip.innerHTML = html; el.cardChip._html = html; }
    el.cardChip.classList.toggle("warn", warn);
    if (state.ready && !cardFitting && map && el.cardChip.offsetHeight !== h0) fitView();
  }

  boot();
})();
