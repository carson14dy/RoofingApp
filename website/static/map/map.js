/* Montana Hail Watch: the interactive map (map.html).

   Why this is JavaScript (AGENTS.md rule 4): only the browser can run a playback timer, follow a
   finger along the timeline, open menus and sheets, and ask for the viewer's location. Python builds
   everything else at each build (website/build.py, website/gridded.py, tools/build_basemap.py):
   every radar and model picture, every number, the legends, the basemap and data/map.json. This file
   only places those finished pieces with Leaflet 1.9.4 (served from static/leaflet) and plays them.

   - Vanilla JavaScript: no framework, no build step, no request to anything but this site's files, except
     the USGS imagery tiles, which load only while Imagery is on (D32; the address comes from build.py in
     data-imagery).
   - Evidence honesty: before "Now" a frame is NOAA's radar estimate, after it the HRRR model; the
     timeline title and subtitle always say which. Town numbers are the NWS hourly forecast. Missing
     data is said in words and never drawn as a clear sky.
   - The satellite picture (--storm-layers builds only) is an infrared observation of cloud tops:
     never a height and never a hail signal.
   - The live hail swath layers, "Hail, last hour" and "Hail, last 24 hours" (--storm-layers builds only; see "live hail
     swath" below): one picture each of NOAA's radar estimate of the largest hail, with the legend and its words from
     data/map.json. Two duties are the browser's alone (AGENTS.md rule 4): (1) the freshness of a layer is worked out
     when it is switched on and again every minute while it is on (D7), from the frame's valid time and the fresh and
     stale minutes in map.json, and it fills the {age} templates; the build's own state line is used only for a layer
     with no picture; an unavailable layer shows no picture; (2) the sheet's live line (--hail-history builds, a hail
     layer on) reads the clicked cell's tile file at the frame's valid time, once for the page (a click on a tile already
     read reads nothing), and only for a point the store puts in Montana (the shard answers first; a point outside Montana
     reads the shard alone; F-9), and a 404 is "no estimate" only while the layer is fresh or stale (D16). No threshold, unit,
     window length or sentence of these layers is written here.
   - The hail history (--hail-history builds only; see "hail history at a spot" below): a click or tap on the map
     that no bubble, alert or report takes opens the five-year radar-estimated hail history for the 0.01-degree
     cell under it. The browser finds the cell from data/map.json (hail.grid). Outside Montana is decided by the
     store, not by this file: in a store file, a tile that hail.tiles does not list has no Montana cell, so the
     build's outside words show with no fetch; a cell whose key is not in its shard's state list gets them after one
     fetch. A --sample build holds only a few tiles, so there a tile it does not hold, or a key outside the state list,
     gets the sample's own outside words (hail.words.sample_outside) instead.
     Otherwise the browser fetches that one tile's shard (hail.shard) once and fills in the words the build wrote
     (hail.words): a Montana cell with no entry in its shard gets the no-estimate words, and a cell with entries
     gets its days. ?at=lat,lon opens a spot on arrival. Closing the sheet drops ?at= from the address, so a
     reload does not reopen it. Off the grid, or when the history didn't load, it shows the build's words with no
     fetch. No threshold, unit or sentence is written in this file: data/map.json and website/hail.py hold them.
   - The joined records under the radar estimate (--hail-history builds only; see "joined records at a spot" below): six
     sections, one per kind of record (reports, official records, radar detections, warnings, zone products and station
     gusts), each with its kind word. After the cell's shard the browser fetches the tile's record file (hail/j), and only
     when that file names them the cell's forecast zone and fire weather zone (hail/z, the fire files as fire-<zone>) and the
     station files the tile names (hail/s). It measures
     distances in miles on the earth radius the build wrote, keeps the records inside the radii the build wrote, reads the
     warning cover bit for the cell's key, formats the UTC times in the zone named by data.tz (Intl), and fills the build's
     templates (hail.joins.words, website/joins.py). A part that does not load shows its own unavailable sentence. No
     sentence, unit, radius or threshold is written in this file (tests/test_site.py reads it for them).
   - The roads, building outlines and address dots (--hail-addresses builds only; see "roads, building outlines and
     address dots" below): one canvas in the hail pane draws the roads by class, the outlines (a light fill from zoom 16,
     the heavier line from 17), one dot per outline and one per unmatched address (from 15), a count bubble per tile (13
     and 14, from hail/counts.json) and the street names (from 16, on the longest piece of each name per tile). Every
     width, zoom, count and rule comes from data/map.json (the "hail" blocks roads, buildings and addresses, and
     hail.draw for the cache cap and the label rules); the colours, the hairlines and the name sizes come from map.css. The
     shard files of the tiles in view are fetched once each from this site, kept under a size cap (hail.draw.cache_bytes,
     least recently used first; a failed file is asked again after the next move). A tap on a dot opens the hail sheet for
     its point with its address lines on top, and the source lines of the layers sit in the attribution line at the bottom right, above the timeline. The search
     form (#address-form) finds an address from the city index and one letter file; what is typed never leaves the
     browser. window.hailMapTest is a test-only hook for tools/smoke_map.py.
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
  var STATE_TICK = MIN;              // a hail layer's state (fresh, stale, unavailable) is checked every minute (D7)
  var BLANK = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
  var FALLBACK_VIEW = { bounds: [[44.35, -116.06], [49.01, -104.03]], min_zoom: 5, max_zoom: 11 };
  var KIND_WORD = { warning: "Warning", watch: "Watch", advisory: "Advisory", statement: "Statement" };
  var LAYER_WORD = { precip: "Precipitation", temp: "Temperature", wind: "Wind gusts", satellite: "Satellite" };   // satellite: --storm-layers builds only
  var LABEL_ZOOM = 5.25;             // from this zoom every town name clears the other bubbles (tools/build_basemap.py)
  // words for the hatching in view (hatchKind): [legend key or card caption, note line]. A gap in the
  // frame shown, the band outside the pictures' box, or both ("on this map" is true of both; only the
  // card and the note say both). A legend key fits one line of a 140 px column, a note noteRoom's line.
  var HATCH = {
    radar: ["No radar coverage", "Hatched areas have no radar coverage."],
    model: ["No model data", "Hatched areas have no model data."],
    radarOut: ["No radar data on this map", "Hatched areas have no radar data on this map."],
    modelOut: ["No model data on this map", "Hatched areas have no model data on this map."],
    // satellite: no value for a cell (fill, out of range, or a quality flag other than 0); never clear sky
    satellite: ["No satellite data", "Hatched areas have no satellite data."],
    satelliteOut: ["No satellite data on this map", "Hatched areas have no satellite data on this map."],
    outside: ["Outside map area", "Hatched areas are outside this map's area."]
  };

  var app = document.getElementById("app");
  var params = new URLSearchParams(location.search);
  var CARD = params.get("card") === "1";
  var motionQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  // keep these in step with the media queries of the same layouts in map.css
  // (not under 301 px tall or 521 px wide: those fold the legend instead, map.css "very short or narrow")
  var sideQuery = window.matchMedia ? window.matchMedia("(min-height: 301px) and (max-height: 500px) and (min-width: 521px) and (orientation: landscape)") : null;
  var compactQuery = window.matchMedia ? window.matchMedia("(max-height: 500px)") : null;
  var phoneQuery = window.matchMedia ? window.matchMedia("(max-width: 520px) and (orientation: portrait)") : null;
  var builtMs = Number(document.body.getAttribute("data-built")) || 0;
  var limits = readJSON(app.getAttribute("data-limits")) || {};
  var imageryCfg = readJSON(app.getAttribute("data-imagery")) || null;   // the imagery source from build.py (D32)

  var el = {
    banners: byId("banners"), legendTitle: byId("legend-title"), legendScale: byId("legend-scale"),
    legendBar: byId("legend-bar"), legendStops: byId("legend-stops"), legendNote: byId("legend-note"),
    legendUncoloured: byId("legend-uncoloured"),
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
    layer: "precip", base: "map", mode: "12h", frames: [], times: [], pos: 0, nowPos: 0,
    playing: false, timer: null, resumeOnShow: false, dragging: false,
    warnings: true, reports: params.get("overlay") === "reports", goToken: 0, userMoved: false,
    ready: false,                    // true once the first timeline is built
    autoplay: true                   // play once the first picture shows, unless the viewer chose first (setPlaying)
  };
  var overlays = [], front = 0, swapToken = 0;   // two image overlays, crossfaded
  var imageryLayer = null;                       // the imagery tile layer (D32): made on the first switch to Imagery
  var imageryFailed = false;                     // true while the tiles fail (tileerror), until one loads (tileload)
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
  var noteFit = { sig: null, room: 0, legendH: 0 };   // the note warnings, note room and legend height the last fit allowed for
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
          if (bm && !bm._error) {
            drawBasemap(bm);
            tidyLabels();
            // a jump at the same zoom (a view reset) places the markers after moveend: check again then
            map.on("viewreset", function () { tidyLabels(); if (state.ready) renderNote(); });
          } else banner("warn", "<strong>The map outlines didn't load</strong> (" + esc((bm && bm._error) || "it didn't load") + "). The weather and towns still show.");
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
    b3Start();                                     // --hail-addresses builds: roads, outlines and address dots (B3)
    var want = params.get("layer");
    var mode = params.get("mode");
    if (mode === "1h" || mode === "12h") state.mode = mode;
    el.warnings.checked = state.warnings;
    el.reports.checked = state.reports;
    setReports(state.reports, true);
    setLayer(want && data.layers[want] ? want : "precip", { atNow: true, first: true });
    if (params.get("base") === "imagery") setBase(true, { first: true });   // D32: the page address opens on imagery
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
    var at = hailParam();                              // ?at=lat,lon: the hail history at that spot
    if (at && hailData()) {
      state.userMoved = true;
      if (hailCell(hailData().grid, at))          // a spot off the grid leaves the map where it is
        map.setView([at.lat, at.lon], Math.max(map.getZoom(), hailData().at_zoom), { animate: false });
      openHail(at.lat, at.lon, null);
    }
  }

  /** The Leaflet map: no tiles (Python drew the basemap), one pane per kind of thing. */
  function createMap(view, imageBounds) {
    var interactive = !CARD;
    map = L.map(el.canvas, {
      // the card can't be zoomed, so finer steps let it fill its width: a 328 px card shows Montana at
      // 5.2 (town names clear) instead of 5 (fitCard)
      zoomControl: false, attributionControl: false, zoomSnap: CARD ? 0.05 : 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 110,
      minZoom: view.min_zoom || 5, maxZoom: Math.max(view.max_zoom || 11, b3TopZoom()), keyboard: interactive, dragging: interactive,
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
      A portrait phone never fits below LABEL_ZOOM unless Montana is wider than the screen there:
      lower, town names run into the other bubbles. Where Montana doesn't fit between the controls
      (at that zoom on a phone, at the minimum zoom on a short landscape screen) it goes where it
      hides the least of the town bubbles (placeCrowded). */
  function fitView() {
    if (!map || !map._viewBounds) return;
    noteFit.legendH = el.legendWrap.offsetHeight;
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
      tl = [6, legend.bottom + 4];
      br = [6, bottomPad];
      var z = boundsZoom(vb, sum(tl[1]));
      if (z < LABEL_ZOOM && phoneQuery && phoneQuery.matches && boundsSize(vb, LABEL_ZOOM).x <= vw - 12) z = LABEL_ZOOM;
      if (boundsSize(vb, z).y > vh - tl[1] - br[1] + 1) placeCrowded(vb, z, tl, br, vw, vh, tlTop);
    }
    map.fitBounds(vb, { paddingTopLeft: tl, paddingBottomRight: br, animate: false });
    fitMinZoom();
  }

  /** A basemap name (a country, region, water or place name, with its dot) under the "Map data" link,
      the note line, the toast or the nearest-town chip is hidden until they or the map move: two texts
      on top of each other read as neither. The legend and the other glass panels hide what is under
      them anyway, and names may run off the edge as in the reference. Runs after every move and
      resize, and whenever the note, the legend, the toast or the chip changes. */
  function tidyLabels() {
    if (!map || CARD) return;
    var boxes = [], link = el.legendWrap.querySelector(".mapdata");
    if (link && link.offsetParent !== null) boxes.push(textBox(link));   // its text, not its 44 px tap area
    [el.note, el.toast, el.near].forEach(function (x) { if (!x.hidden) boxes.push(x.getBoundingClientRect()); });
    boxes = boxes.filter(function (b) { return b.width > 2 && b.height > 2; });   // not the toast's empty live region
    var spans = el.canvas.querySelectorAll(".bm-label span");
    for (var i = 0; i < spans.length; i++) {
      var r = textBox(spans[i]), hide = false;                               // the glyphs, taller than the line
      var left = spans[i].previousElementSibling ? r.left - 10 : r.left;      // a place's dot, left of its name
      for (var k = 0; r.width && !hide && k < boxes.length; k++) {
        var b = boxes[k];
        hide = left < b.right + 2 && r.right > b.left - 2 && r.top < b.bottom + 2 && r.bottom > b.top - 2;
      }
      spans[i].parentNode.classList.toggle("bm-hide", hide);
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
    // the towns that show at the first view (min_zoom below 7; townMinZoom): the others appear when zoomed in
    (data ? data.towns : []).forEach(function (t) {
      if (townMinZoom(t) < 7) pts.push(map.project([t.lat, t.lon], z).subtract(nw));
    });
    var boxes = [];
    [el.legend, el.legendWrap.querySelector(".mapdata"), el.top.querySelector(".close"), el.buttons, el.timeline]
      .concat([].slice.call(el.banners.children)).forEach(function (e) {
        var r = e && e.getBoundingClientRect();
        if (r && r.width && r.height) boxes.push(r);
      });
    var nb = noteBox(tlTop);
    if (nb) boxes.push(nb);
    if (B3 && B3.credit) {                                      // the source lines above the band (b3Lift): towns under them count too
      var cr = B3.credit.getContainer().getBoundingClientRect();
      if (cr.width && cr.height) boxes.push(cr);
    }
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
    if (B3 && B3.credit) room += B3.credit.getContainer().offsetHeight + 8;     // the source lines sit above the note (b3Lift)
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
      // the satellite's hatch words count only in a build with the layer, so a default build's box stays as it was
      Object.keys(HATCH).filter(function (k) { return k.indexOf("satellite") !== 0 || !!(data.layers && data.layers.satellite); })
        .forEach(function (k) { var s = noteSize(HATCH[k][1], false); if (!big || s.width > big.width) big = s; });
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

  /** The two-column legend (map.css .legend-2col: the keys beside a shorter scale) of every portrait
      phone: about 160 px tall instead of about 270, so Montana sits higher and bigger below it. */
  function twoColLegend() { return !CARD && !!(phoneQuery && phoneQuery.matches); }

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
      if (p.site) return;          // the site towns are drawn as bubbles instead
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

  /** The zoom a town shows from: min_zoom in data/map.json (towns.json; build.py writes it), else 7 for
      the older "minor" towns and 5 for the rest. */
  function townMinZoom(t) {
    return t.min_zoom != null ? t.min_zoom : t.minor ? 7 : 5;
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
        // hidden below its min_zoom: zoomCls adds mzN, which map.css shows from zoom N, as for the basemap's names
        className: "town side-" + side + zoomCls(townMinZoom(t)),
        html: '<span class="bubble" aria-hidden="true">\u2014</span><span class="tname" aria-hidden="true">' + esc(t.name) + "</span>",
        iconSize: [30, 30], iconAnchor: [15, 15]
      });
      // autoPanOnFocus off: Leaflet's own keeps a focused bubble inside the map but not clear of the
      // legend or the timeline; reveal() does (keyboard focus only, so a click doesn't pan twice)
      var m = L.marker([t.lat, t.lon], { icon: icon, keyboard: !CARD, riseOnHover: true, interactive: true, autoPanOnFocus: false }).addTo(map);
      t._marker = m;
      t._el = m.getElement();
      t._bubble = t._el.querySelector(".bubble");
      t._name = t._el.querySelector(".tname");
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
    var r = t._name.getBoundingClientRect();
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

  /** What a bubble says for an hour: temperature (precip/temp layers) or gusts (wind layer). The ring
      (`over`) marks the layer's own limit: gusts at the gust limit, temperatures outside the cold and
      hot limits; the Precipitation layer has none (its picture is the rain, not the temperature). */
  function bubbleValue(h) {
    if (!h) return { text: "\u2014", over: false, words: "no NWS forecast for this hour" };
    if (state.layer === "wind") {
      if (h.gust_mph == null) return { text: "\u2014", over: false, words: "gusts not in the NWS forecast" };
      var g = h.gust_mph;
      return { text: String(g), over: limits.gust_mph != null && g >= limits.gust_mph, words: "gusts " + g + " mph" };
    }
    if (h.temp_f == null) return { text: "\u2014", over: false, words: "temperature not in the NWS forecast" };
    var v = h.temp_f;
    var over = state.layer === "temp" && ((limits.cold_f != null && v < limits.cold_f) || (limits.hot_f != null && v > limits.hot_f));
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
    hailWatch(!!swathLayer());          // a hail layer's state is worked out again every minute while it is on (D7)
    if (swathLayer()) hailTick();
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
    // the old layer's position must sit inside the new frames before anything draws them: a one-frame layer
    // (the satellite picture) switched to while playing stops playback below, and that draws frame state.pos
    state.pos = clamp(state.pos, 0, Math.max(0, state.frames.length - 1));
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
      showPicture(ok && hailShowable() ? f.src : null, { layer: state.layer, kind: f.kind });   // no picture once unavailable (D7)
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
    var n = state.frames.length, swath = swathLayer();
    if (!n) {
      if (swath) {                   // a hail layer with no picture: its title, and its words in the note (noteWarnings)
        el.title.textContent = swath.title;
        whenEl.textContent = swath.words.no_picture;
      } else {
        el.title.textContent = state.layer === "precip" ? "No radar or forecast" :
          state.layer === "satellite" ? "No satellite picture" : "No forecast";
        whenEl.textContent = "Nothing to show for " + LAYER_WORD[state.layer].toLowerCase();
      }
      srcEl.textContent = "";
      el.range.setAttribute("aria-valuetext", swath ? swath.words.no_picture : "No pictures in this update");
      el.fill.style.width = "0";
      el.knob.style.left = "0";
      return;
    }
    var f = state.frames[state.pos], ms = state.times[state.pos], hail = f.kind === "hail_swath";
    el.title.textContent = f.kind === "radar" ? "Radar" : f.kind === "satellite" ? "Satellite" : hail ? swath.title : "Forecast";
    whenEl.textContent = dayClock(ms);
    srcEl.textContent = sourceWords(f);
    // a screen reader reads every value change of a focused slider: while playing, its value waits
    // until playback stops (setPlaying); the knob and the title above still move
    if (!(state.playing && document.activeElement === el.range)) {
      el.range.value = String(ms);
      el.range.setAttribute("aria-valuetext", (f.kind === "radar" ? "Radar, " : f.kind === "satellite" ? "Satellite, " :
        hail ? swath.title + ", " : "Forecast, ") + dayClock(ms) + ", " + sourceWords(f) + nowWords(ms, f));
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
    if (state.pos !== state.nowPos || f.kind === "hail_swath") return "";   // a hail picture's age is its own line (hailView)
    var now = nowRaw();              // the real now: the clamped one (nowMs) is only for placing the tick
    if (Math.abs(ms - now) <= 10 * MIN) return ", now";
    if (f.kind === "radar") return ", latest radar picture";
    if (f.kind === "satellite") return ", latest satellite picture";     // one scan: never "this hour"
    return Math.floor(now / HOUR) * HOUR === ms ? ", this hour" : "";
  }

  /** The source in plain words: radar estimate or model forecast, never blended. */
  function sourceWords(f) {
    var sample = /^SAMPLE/.test(f.source || "");
    if (f.kind === "hail_swath") return hailView().line;   // the state line, worked out now (D7)
    if (f.kind === "satellite") return f.source;      // the build's own words (a sample build says SAMPLE)
    if (f.kind === "radar") return sample ? "sample, not NOAA radar" : "NOAA radar estimate";
    var run = f.run ? ", run " + clock(Date.parse(f.run)) : "";
    return sample ? "sample, not the HRRR model" : "HRRR model" + run;
  }

  /** The line above the timeline: a failed picture, the end of the forecast, a layer with no pictures
      at all (warnings, on a solid backing), and what hatching in view means (like the reference's
      "Forecast is not available in some areas"). Plain words; a failure never looks like clear sky.
      The hatching note never prints over a town's bubble or name (after a zoom, a pan or My location,
      or on a screen too short for Montana): it steps aside, and the legend's keys still name the
      hatching. */
  function renderNote() {
    var warn = noteWarnings(state.pos).join(" "), info = "";
    var f = state.frames[state.pos], k = f && !warn ? hatchKind() : "";
    // same rule as the legend keys (whenever hatching is in view); a warning takes the line alone,
    // so it stays short, and the keys still name the hatching
    if (k) info = hatchWords(k)[1];
    var html = warn ? '<span class="note-warn">' + esc(warn) + "</span>" : info ? '<span class="note-info">' + esc(info) + "</span>" : "";
    var before = el.note._html + el.note.hidden;
    if (el.note._html !== html) { el.note.innerHTML = html; el.note._html = html; }
    el.note.hidden = !html || CARD;
    el.note.classList.toggle("warn", !!warn);
    if (info && !el.note.hidden && overTown(textBox(el.note))) el.note.hidden = true;
    if (before !== html + el.note.hidden) tidyLabels();
    b3Lift();                        // the note's height is part of the band the source lines sit above (--hail-addresses builds)
  }

  /** The box of an element's text on screen (without its padding or tap area). */
  function textBox(e) {
    var rg = document.createRange();
    rg.selectNodeContents(e);
    return rg.getBoundingClientRect();
  }

  /** Whether a box on screen covers part of a town's bubble or name. */
  function overTown(b) {
    return data.towns.some(function (t) {
      return [t._bubble, t._name].some(function (e) {
        var r = e.getBoundingClientRect();
        return r.width > 0 && r.left < b.right && r.right > b.left && r.top < b.bottom && r.bottom > b.top;
      });
    });
  }

  /** The note's warnings at timeline position `pos` (any position when the layer has no pictures):
      no pictures at all and why, a picture that failed, no model forecast after the last radar
      picture. Shared by renderNote and noteRoom, so the room fitted is the room the note takes. */
  function noteWarnings(pos) {
    var n = state.frames.length, st = data.status || {}, warns = [];
    if (!n && swathLayer()) return [swathPre(swathLayer()) + swathLayer().state_line];   // the build's words for a hail layer with no picture
    if (!n) {
      var why = [];
      if (state.layer === "precip" && st.radar && !st.radar.ok) why.push("radar: " + st.radar.detail);
      if (state.layer === "satellite" && st.satellite && !st.satellite.ok) why.push("satellite: " + st.satellite.detail);
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
    // a hail layer's classes are colours with words (B4): every stop keeps its label, and the bar is tall enough for them
    var swath = !!swathLayer();
    var barH = swath ? Math.max(compactLegend() ? 64 : 96, (stops.length - 1) * 16) :
      compactLegend() ? 64 : Math.max(96, (stops.length - 1) * 16);
    var shown = swath ? stops.map(function () { return true; }) : thinStops(stops, barH);
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
    b3Credits();                     // --hail-addresses builds: the source lines of the layers (D29)
    if (el.legendUncoloured) el.legendUncoloured.textContent = L_.legend_uncoloured || "";   // a hail layer's own line (build.py); --storm-layers only
    el.legend.classList.toggle("swath-words", swath);               // the kind and uncoloured lines stay in view (map.css)
    renderKeys();
    tidyLabels();                    // another scale can move the "Map data" link, or resize the legend
    if (el.legendWrap.offsetHeight !== noteFit.legendH) refitForBanner();
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
      then only what is on the map now: hatching (a gap in the frame shown; the band outside the
      pictures), the limit ring (for the whole timeline when any of its hours rings a town in sight),
      warning outline colours and storm-report circles. Every colour carries its word. Nothing comes
      or goes during playback, so the legend keeps its height (and the fit its room). */
  function renderKeys() {
    if (!data) return;
    var keys = [];
    keys.push(["key-bubble", state.layer === "wind" ? "Town numbers: NWS gust forecast, mph" : "Town numbers: NWS forecast, \u00b0F"]);
    var hatch = hatchInView();
    if (hatch.gap) keys.push(["key-hatch", hatchWords(hatch.gap)[0]]);
    if (hatch.outside) keys.push(["key-hatch-out", HATCH.outside[0]]);
    if (ringsOnTimeline()) keys.push(["key-ring", ringWords()]);
    if (state.warnings) (state.alertKinds || []).forEach(function (k) { keys.push(["key-hz key-" + k, KIND_WORD[k] + " area (NWS)"]); });
    if (state.reports && data.reports.length) {
      if (data.reports.some(function (r) { return r.kind === "hail"; })) keys.push(["key-hail", "Hail report (size)"]);
      if (data.reports.some(function (r) { return r.kind === "wind"; })) keys.push(["key-wind", "Wind report"]);
    }
    if (locState && locState.here && townVisible(locState.here)) keys.push(["key-here", "Your location"]);
    if (state.base === "imagery" && imageryCfg) keys.push(["key-credit", imageryFailed ? imageryCfg.failed_line : imageryCfg.credit_line]);   // D32: no colour, so its text lines up with the keys
    var html = keys.map(function (k) { return '<li><span class="key ' + k[0] + '" aria-hidden="true"></span>' + esc(k[1]) + "</li>"; }).join("");
    // a frame without the gaps other frames of this timeline have keeps the gap row's room: hidden
    // and last, so it reads as padding
    if (hatch.spare) html += '<li class="key-spare"><span class="key key-hatch"></span>' + esc(hatchWords(hatch.spare)[0]) + "</li>";
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
      if (el.legendWrap.offsetHeight !== noteFit.legendH) refitForBanner();   // a taller or shorter legend
    }
  }

  /** How many active alerts have no outline (issued by county or zone). */
  function noOutlineCount() {
    return ((data && data.alerts && data.alerts.items) || []).filter(function (a) { return !a.geometry; }).length;
  }

  /** The hatching in view, of two kinds. `gap`: "radar" or "model" when the frame shown has areas with
      no data (no radar coverage, or masked model cells; a heavier hatch drawn in the picture), named
      for the frame shown so a model frame never says "radar"; when it has none, `spare` names a gap
      elsewhere on this timeline (renderKeys keeps that row's room). `outside`: the band outside the
      pictures' box, which this map doesn't draw (every layer and frame, a hairline, see
      drawOutsideMask). NOAA has data there, so it is never called a coverage gap; it is hatched so
      it never looks dry. */
  function hatchInView() {
    var h = { gap: "", spare: "", outside: false };
    if (!map || !map._imageBounds) return h;
    var f = state.frames[state.pos], kind = function (x) {
      return x.kind === "radar" || x.kind === "satellite" || x.kind === "hail_swath" ? x.kind : "model";
    };
    if (f && f.nodata && !f._failed) h.gap = kind(f);
    else state.frames.some(function (x) { if (x.nodata) h.spare = kind(x); return x.nodata; });
    h.outside = !map._imageBounds.contains(map.getBounds());
    return h;
  }

  /** HATCH's key for the hatching in view: a gap ("radar", "model", "satellite", "hail_swath"), with "Out" added when
      the band outside the pictures is in view too, "outside" for the band alone, "" for none. */
  function hatchKind() {
    var h = hatchInView();
    return h.gap ? h.gap + (h.outside ? "Out" : "") : h.outside ? "outside" : "";
  }

  /** [legend key, note line] for a hatch kind. A hail layer's words are the build's (map.json "words", the site words
      in website/build.py), so the hail kinds have none here. */
  function hatchWords(k) {
    var lay = swathLayer();
    if (k === "hail_swath" && lay) return [lay.words.hatch_key, lay.words.hatch_note];
    if (k === "hail_swathOut" && lay) return [lay.words.hatch_key_out, lay.words.hatch_note_out];
    return HATCH[k] || ["", ""];
  }

  /** Whether a town's bubble is on screen (a town appears from its min_zoom: 7 for the minor towns). */
  function townVisible(t) {
    if (map.getZoom() < townMinZoom(t)) return false;      // not shown yet at this zoom (drawTowns)
    return map.getBounds().contains([t.lat, t.lon]);
  }

  /** Whether any town in sight has the limit ring at any hour of this timeline. */
  function ringsOnTimeline() {
    var times = state.times.length ? state.times : [valueTime()];
    return data.towns.some(function (t) {
      return townVisible(t) && times.some(function (ms) { return bubbleValue(townHour(t, ms)).over; });
    });
  }

  /** What the orange ring means for the layer on screen. */
  function ringWords() {
    if (state.layer === "wind") return "Gusts " + limits.gust_mph + "\u00a0mph or more";
    return "Below " + limits.cold_f + "\u00a0\u00b0F or above " + limits.hot_f + "\u00a0\u00b0F";
  }

  /** The layer menu's swatches use each layer's own legend colours (built by Python). */
  function paintSwatches() {
    // every layer in data/map.json (the satellite layer is there only in --storm-layers builds)
    Object.keys(data.layers).forEach(function (k) {
      var sw = el.layers.querySelector(".sw-" + k);
      var L_ = data.layers[k];
      if (sw && L_ && L_.gradient) sw.style.background = L_.gradient;
    });
  }

  // ------------------------------------------------------------------ base map: white or imagery (D32)

  /** Switch the base map. The white vector map is the default. Imagery (opt-in) is USGS aerial imagery with
      roads and names: its tile layer is made on the first switch, and the browser asks for tiles only while
      it is on (a switch, or an address that starts on it). While it is on, the vector base map's land, water,
      roads, county lines, place dots and names are hidden (is-imagery, map.css); the Montana outline and the
      state and country borders stay, and so do the weather, the warning outlines, the reports and the bubbles.
      The zoom limit goes up to the imagery's and back to the map's own (Leaflet zooms out to it when needed).
      The credit row shows the credit with its privacy words while it is on, and the failure words while tiles
      fail (setImageryFailed). The card never uses imagery. */
  function setBase(imagery, opts) {
    if (CARD || !data || !imageryCfg) return;
    opts = opts || {};
    state.base = imagery ? "imagery" : "map";
    var radios = el.layers.querySelectorAll("input[name=base]");
    for (var i = 0; i < radios.length; i++) radios[i].checked = radios[i].value === state.base;
    app.classList.toggle("is-imagery", imagery);
    if (imagery) {
      if (!imageryLayer) {
        imageryLayer = L.tileLayer(imageryCfg.url, { maxZoom: imageryCfg.max_zoom, maxNativeZoom: imageryCfg.max_zoom,
          tileSize: 256, crossOrigin: "anonymous", pane: "tilePane" });
        imageryLayer.on("tileerror", function () { setImageryFailed(true); });   // the credit row says so
        imageryLayer.on("tileload", function () { setImageryFailed(false); });   // and goes back to the credit
      }
      imageryFailed = false;         // a switch on starts with the credit; a tile that fails is said again
      imageryLayer.addTo(map);
      map.setMaxZoom(imageryCfg.max_zoom);
    } else {
      if (imageryLayer) map.removeLayer(imageryLayer);
      map.setMaxZoom(Math.max((data.view && data.view.max_zoom) || 11, b3TopZoom()));
    }
    renderKeys();                    // the credit row comes and goes with the switch
    if (!opts.first) saveUrl();
  }

  /** The credit row while Imagery is on: the failure words (imagery.failed_line from build.py) while tiles fail
      (Leaflet's tileerror), and the credit with its privacy words (imagery.credit_line) again when one loads
      (tileload). The words are not written here, so build.py is the one place they change. */
  function setImageryFailed(failed) {
    if (imageryFailed === failed) return;
    imageryFailed = failed;
    if (state.base === "imagery") renderKeys();
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
      else if (e.target.name === "base") setBase(e.target.value === "imagery");
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
    el.scrim.addEventListener("click", function (e) {
      // the second click of a double-click on a bubble or an outline lands on the scrim the first one
      // put under the pointer: it must not close the sheet that click just opened (a time guard, as
      // iPhone Safari counts every tap as a single click)
      if (Date.now() - sheetOpenedAt < 400) return;
      closeSheet();
      // the scrim takes every tap while a sheet is open, so a tap on another dot (B3) is handed to the dots' tap here, and its
      // sheet opens in place of the one that closed. The tap's own point is the drag reference, not the last press on the canvas.
      if (B3) { B3.down = { x: e.clientX, y: e.clientY }; b3Tap(e); }
    });
    el.sheetBack.addEventListener("click", backToList);
    el.sheetBody.addEventListener("click", onSheetClick);
    el.sheet.addEventListener("keydown", trapFocus);
    if (hailData()) map.on("click", onHailClick);      // --hail-history builds: the history at a spot

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
    if (state.base === "imagery") q.set("base", "imagery"); else q.delete("base");
    if (hailAt) q.set("at", hailAt); else q.delete("at");
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

  /** A short message above the timeline that fades after a few seconds. `quiet`: only the polite live
      region reads it out (map.css hides it), as the screen already shows the same. */
  function toast(text, quiet) {
    el.toast.textContent = text;
    el.toast.classList.add("show");
    el.toast.classList.toggle("quiet", !!quiet);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.toast.classList.remove("show"); el.toast.textContent = ""; bottomMoved(); }, 4500);
    bottomMoved();
  }

  /** The toast or the chip came or went, so the note line above them moved: check it, and the
      basemap names under all three, again. */
  function bottomMoved() {
    if (data && state.ready) renderNote();
    tidyLabels();
    b3Lift();                        // --hail-addresses builds: the source lines stay over the timeline
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
      var words = inside ? "Showing your location." : "You're outside the area this map covers.";
      if (best) {
        var miles = bestKm * 0.621371, mi = Math.round(miles);
        var far = miles < 1 ? "under a mile" : mi + (mi === 1 ? " mile" : " miles");
        el.near.textContent = "Nearest town: " + best.name + " \u00b7 " + (miles < 1 ? "under 1 mi" : mi + " mi");
        el.near.setAttribute("data-town", best.slug);
        el.near.setAttribute("aria-label", "Nearest town: " + best.name + ", " + far + ". Open its forecast.");
        el.near.hidden = false;
        words += " Nearest town: " + best.name + ", " + far + ".";
      }
      // the polite live region: a screen reader hears that it worked; inside the map the chip says
      // the same on screen, so there the sentence is only read out, not shown twice
      toast(words, inside && !el.near.hidden);
      placeLocDot();
      if (inside) {
        state.userMoved = true;
        // once there, the town the dot sits on (bubble and name), or else the dot, is moved clear of
        // the legend and the panels
        map.once("moveend", function () {
          setTimeout(function () {   // after a jump, Leaflet places the bubbles just after moveend
            var t = locState && locState.here;
            if (t) reveal(L.latLng(t.lat, t.lon), townExtent(t)); else reveal(ll);
          });
        });
        map.setView(ll, Math.max(map.getZoom(), 7), { animate: !reducedMotion() });
      }
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
      if (map.getZoom() < townMinZoom(t)) return;          // not on the map yet at this zoom (townMinZoom)
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
    el.sheetBody.innerHTML = (data && data.sample && !opts.noSampleTag ? '<p class="sample-tag">Sample data: invented to review the layout. It is not weather.</p>' : "") + html;
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
      open). A ?town= link or an ?at= spot has done its job: the address drops it, so a reload doesn't reopen it. */
  function closeSheet() {
    if (!sheetState) return;
    var wasHail = sheetState.kind === "hail";
    var opener = sheetState.opener, v = sheetState.view, panned = sheetState.revealed, resized = sheetState.resized;
    if (sheetState.watcher) { sheetState.watcher.onclose = null; sheetState.watcher.destroy(); }
    sheetState = null;
    liveFor = null;
    liveNode = null;
    if (wasHail) { hailAt = null; saveUrl(); }      // an ?at= spot is dropped with its sheet
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
    if (hailData() && byId("hail-list")) html += byId("hail-list").innerHTML;   // the hail note (map.html template)
    var st = data.status || {};
    var bad = ["radar", "forecast", "alerts", "forecasts", "reports", "satellite", "hail_swath", "hail_history"].filter(
      function (k) { return st[k] && !st[k].ok; });
    if (bad.length) {
      html += "<h3>Sources with problems</h3><ul>" + bad.map(function (k) {
        return "<li>" + esc(st[k].label) + ": " + esc(st[k].detail) + ".</li>";
      }).join("") + "</ul>";
    }
    openSheet("list", "List", html, opener, {});
  }

  // ------------------------------------------------------------------ hail history at a spot (--hail-history builds)

  /** The hail history at a point. data/map.json "hail" holds the grid, the list of tiles the store holds (tiles), the
      size classes, the stale setting (stale_days) and every sentence (hail.words, the templates website/hail.py fills
      for the town pages). The browser does these steps and no others: the click or tap and the point it names; the
      grid, tile and key arithmetic (the cell, the tile's file name and the key inside the tile); one fetch of that
      tile's shard; the outside and no-estimate rules (a tile the list does not hold, a key the shard's state list does
      not hold, and a Montana cell with no entry in its shard, which is not the same as no hail); the day arithmetic
      (the day index counts from d0, in UTC); the choice of the cell's words; the stale line; and the fill of the
      templates. The choice mirrors website/hail.py describe(): the days inside the window at or above the floor, the
      largest value on each day (a tie goes to the later day), newest first; the lead form; the day rows with their
      severe and note tags; the class counts; the missing-day list. The stale line is the one difference: it tests the
      as_of day against the viewer's UTC day, where describe() uses the build's (map.json "built"). No unit test runs
      the browser's selection; the unit tests read this file for literals and run the size rule. tools/smoke_map.py
      check_sheet_words checks the sheet against describe() at the Benchland arrival, at Benchland's centre and at the
      gate cell, in Chromium. No threshold, size unit or sentence is written here: they come from data/map.json, which
      website/hail.py writes. */
  var HAIL_MICRO = 1e6;                       // points are read to whole millionths of a degree, as the grid is
  var HAIL_DAY_MS = 24 * 60 * 60 * 1000;      // one day, in milliseconds (the store counts whole days)
  var HAIL_EXT = { l: 12, t: 12, r: 12, b: 12 };   // the clear space the sheet's point needs around it (reveal)
  var hailTopNode = null;                     // the address block a dot's sheet shows on top (B3), for the sheet's current state
  var hailTopEnd = null;                      // the last node of that block once the sheet's body holds it (hailShow): the live line goes after it
  var hailAt = null;                          // "lat,lon" of the spot the sheet shows; the address carries it as at=
  var hailTiles = {};                         // shard URL -> promise of its JSON (a failed load is asked again)
  var hailTileSet = null;                     // the tiles the store holds (hail.tiles), as a set; made on first use
  var hailSeq = 0;                            // the newest click or arrival: an answer to an older one is dropped
  var dtfUtcDay = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });

  /** The hail block of data/map.json, or null when this build has none (the default) or the page is a card. */
  function hailData() { return CARD || !data || !data.hail ? null : data.hail; }

  /** A point as the grid reads it: whole millionths of a degree. The address and the cell use the same values. */
  function hailPoint(lat, lon) {
    return { lat: Math.round(lat * HAIL_MICRO) / HAIL_MICRO, lon: Math.round(lon * HAIL_MICRO) / HAIL_MICRO };
  }

  /** The cell (row, col) that holds a point, or null outside the grid. Row 0 is the north edge and column 0 the
      west edge. A point on an edge goes to the cell south or east of it (round half up), as website/hail.py does;
      the sums are whole millionths, so float rounding never decides the cell. */
  function hailCell(g, p) {
    var per = Math.round(1 / g.cell_deg);     // cells per degree
    var row = Math.floor((Math.round(g.row0_lat * HAIL_MICRO) - Math.round(p.lat * HAIL_MICRO)) * per / HAIL_MICRO + 0.5);
    var col = Math.floor((Math.round(p.lon * HAIL_MICRO) - Math.round(g.col0_lon * HAIL_MICRO)) * per / HAIL_MICRO + 0.5);
    return row >= 0 && row < g.rows && col >= 0 && col < g.cols ? { row: row, col: col } : null;
  }

  /** The tile's file for a cell: {r} and {c} in the template are the tile's row and column, four digits each. */
  function hailShardUrl(h, cell) {
    var t = h.grid.tile_cells;
    return h.shard.replace("{r}", pad4(Math.floor(cell.row / t))).replace("{c}", pad4(Math.floor(cell.col / t)));
  }

  function pad4(n) { return ("0000" + n).slice(-4); }

  /** The cell's key inside its tile's file: its row and column within the tile. */
  function hailKey(h, cell) { var t = h.grid.tile_cells; return (cell.row % t) * t + (cell.col % t); }

  /** The tile's name as the build lists it (hail.tiles): "r0079_c0199" for the tile that holds the cell. */
  function hailTileName(h, cell) {
    var t = h.grid.tile_cells;
    return "r" + pad4(Math.floor(cell.row / t)) + "_c" + pad4(Math.floor(cell.col / t));
  }

  /** Whether the store holds the tile at all: the build lists every tile with a Montana cell, and no other. */
  function hailListed(h, name) {
    if (!hailTileSet) hailTileSet = new Set(h.tiles);
    return hailTileSet.has(name);
  }

  /** Whether a cell's key is in its shard's state list: the Montana cells of the tile, in key order. */
  function hailInState(doc, key) { return doc.state.indexOf(key) >= 0; }

  /** One fetch per tile for the life of the page: the tile's JSON. Any failure rejects, a missing file included: the
      build lists only the tiles it wrote, so a 404 means a broken store, which is not the same as no hail. A file that is
      not JSON, or is JSON but not an object, is a failed load too, in the format (D27). Each error gives its reason (see
      hailFailure). The next click asks again. */
  function hailTile(url) {
    if (!hailTiles[url]) {
      hailTiles[url] = fetch(url, { credentials: "same-origin" }).then(function (r) {
        if (!r.ok) throw hailFailure("no_answer", url);
        return r.json().then(function (doc) {
          if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw hailFailure("format", url);
          return doc;
        }, function () { throw hailFailure("format", url); });
      }, function () { throw hailFailure("no_answer", url); });
      hailTiles[url].then(null, function () { delete hailTiles[url]; });
    }
    return hailTiles[url];
  }

  /** The error of a file that did not load. Its reason is "no_answer" (the file is missing or the request failed) or
      "format" (the file is not JSON, or not in the shape the sheet reads it as): the two reasons joins.py's readers give. */
  function hailFailure(reason, url) { var e = new Error(url); e.reason = reason; return e; }

  /** The ISO date (UTC) of a day index: the store counts whole days from its d0. */
  function hailIso(h, d) { return new Date(Date.parse(h.d0) + d * HAIL_DAY_MS).toISOString().slice(0, 10); }

  /** "Jun 15, 2025" for an ISO date, read in UTC so the SPC day's date never moves with the viewer's time zone. */
  function hailDate(iso) {                  // an empty or unreadable date (a store with no records) gives an empty string, never a throw
    var ms = Date.parse(iso || "");
    return isNaN(ms) ? "" : dtfUtcDay.format(new Date(ms));
  }

  /** The size in inches, shown to the hundredth and rounded down (see D34 in docs/DECISIONS.md): the exact tenths times
      100, over the build's tenths per inch, floored, with two decimal places. Rounding down never crosses a class
      edge, because every edge in tenths lies at or above its inch value, so a shown size keeps its class. */
  function hailInches(h, t) { return (Math.floor(t * 100 / h.tenths_per_inch) / 100).toFixed(2); }
  /** Millimetres to one decimal place, from tenths of a millimetre (the divisor comes from the data): 513 gives 51.3. */
  function hailMm(h, t) { return Math.floor(t / h.tenths_per_mm) + "." + (t % h.tenths_per_mm); }

  /** The size class of a stored value: the class whose range holds it (the top class has no maximum). */
  function hailClass(h, t) {
    for (var i = 0; i < h.classes.length; i++) {
      var c = h.classes[i];
      if (t >= c.min_tenths && (c.max_tenths === null || t <= c.max_tenths)) return c;
    }
    return null;
  }

  /** A template with its {names} replaced from vals. A name without a value stays as it is. */
  function fill(tpl, vals) {
    return String(tpl).replace(/\{(\w+)\}/g, function (m, k) {
      return Object.prototype.hasOwnProperty.call(vals, k) ? String(vals[k]) : m;
    });
  }

  /** The cell's days, newest first: the largest stored value on each day of the window (website/hail.py describe). */
  function hailDays(h, doc, key) {
    var list = (doc && doc.cells && doc.cells[String(key)]) || [], best = {};
    list.forEach(function (pair) {
      var iso = hailIso(h, pair[0]), t = pair[1];
      if (iso < h.window[0] || iso > h.window[1] || t < h.floor_tenths) return;
      if (best[iso] === undefined || t > best[iso]) best[iso] = t;
    });
    return Object.keys(best).sort().reverse().map(function (iso) { return { iso: iso, t: best[iso] }; });
  }

  /** Every sentence of the sheet for a cell, filled from the build's templates. The choice of words follows describe()
      in website/hail.py, except the stale line: that tests as_of against the viewer's UTC day, where describe() tests it
      against the build's UTC day (map.json "built"), so a page held past a build can differ. */
  function hailText(h, cell, doc) {
    var w = h.words, days = hailDays(h, doc, hailKey(h, cell)), n = days.length;
    var common = { start: hailDate(h.window[0]), end: hailDate(h.window[1]) };
    var missing = h.missing_days.filter(function (d) { return d >= h.window[0] && d <= h.window[1]; });
    var out = { sample: h.state === "sample" ? w.sample : "", lead: "", rows: [], counts: [], countsTitle: "",
      what: w.what_this_is, missing: "", stale: "", source: "" };
    days.forEach(function (day) {
      var c = hailClass(h, day.t), tags = [];
      if (c.severe) tags.push(w.severe_tag);
      if (day.t >= h.large_note_tenths) tags.push(w.large_note);
      var text = fill(w.row, { date: hailDate(day.iso), "in": hailInches(h, day.t), mm: hailMm(h, day.t), "class": c.word });
      out.rows.push(tags.length ? text + ", " + tags.join(", ") : text);
    });
    if (n) {
      var big = days[0];                       // the largest value; on a tie, the later day (as describe() picks it)
      days.forEach(function (day) { if (day.t > big.t || (day.t === big.t && day.iso > big.iso)) big = day; });
      out.lead = fill(n === 1 ? w.lead_one : w.lead_many, Object.assign({}, common, {
        n: n, largest_in: hailInches(h, big.t), largest_mm: hailMm(h, big.t), largest_date: hailDate(big.iso) }));
    } else if (!missing.length) out.lead = fill(w.lead_none_plain, common);
    else if (missing.length === 1) out.lead = fill(w.lead_none_one, common);
    else out.lead = fill(w.lead_none, Object.assign({}, common, { missing: missing.length }));
    h.classes.forEach(function (c) {
      var count = days.filter(function (d) { return hailClass(h, d.t).word === c.word; }).length;
      if (count) out.counts.push(fill(count === 1 ? w.class_count_one : w.class_count_many, { days: count, word: c.word }));
    });
    if (out.counts.length) out.countsTitle = w.class_counts_title;
    if (missing.length) out.missing = fill(w.missing, { list: missing.map(hailDate).join(", ") });
    var today = new Date().toISOString().slice(0, 10);    // the viewer's clock, in UTC (describe() uses the build's day)
    if ((Date.parse(today) - Date.parse(h.as_of)) / HAIL_DAY_MS > h.stale_days) out.stale = fill(w.stale, { as_of: hailDate(h.as_of) });
    out.source = fill(w.source, { as_of: hailDate(h.as_of) });
    return out;
  }

  /** The sheet's body: a loaded cell from the template in map.html (<template id="hail-sheet">), or one line of
      words for the other states (loading, outside, unavailable). The sheet's own title is set by openSheet. */
  function hailShow(h, kind, payload, joins) {
    var frag;
    if (kind === "loaded") {
      frag = document.getElementById("hail-sheet").content.cloneNode(true);
      var slot = function (name) { return frag.querySelector('[data-hail="' + name + '"]'); };
      var show = function (node, text) { node.hidden = !text; node.textContent = text || ""; };
      var list = function (node, items) {
        node.hidden = !items.length;
        items.forEach(function (text) { var li = document.createElement("li"); li.textContent = text; node.appendChild(li); });
      };
      show(slot("sample"), payload.sample);
      show(slot("lead"), payload.lead);
      show(slot("counts-title"), payload.countsTitle);
      list(slot("counts"), payload.counts);
      list(slot("days"), payload.rows);
      show(slot("what"), payload.what);
      show(slot("stale"), payload.stale);
      show(slot("missing"), payload.missing);
      show(slot("source"), payload.source);
      if (joins) joinRender(slot("joins"), joins);
    } else {
      frag = document.createDocumentFragment();
      if (h.state === "sample") {          // a sample build labels every state of the sheet, as the town tables do
        var tag = document.createElement("p");
        tag.className = "sample-tag";
        tag.textContent = h.words.sample;
        frag.appendChild(tag);
      }
      var p = document.createElement("p");
      p.className = kind === "unavailable" ? "warn" : "sub";
      p.textContent = payload;
      frag.appendChild(p);
    }
    var block = hailTopNode ? hailTopNode.cloneNode(true) : null;      // a dot's address block (B3): a fragment of nodes
    hailTopEnd = block && block.nodeType === 11 ? block.lastChild : block;   // its last node: the live line goes after it
    if (block) frag.insertBefore(block, frag.firstChild);   // a dot's address block comes first (B3)
    el.sheetBody.innerHTML = "";
    el.sheetBody.appendChild(frag);
    liveAttach();                                                       // the live line goes after the address block, if any (liveOpen)
    if (sheetState && sheetState.ll) reveal(sheetState.ll, HAIL_EXT);   // a longer sheet may cover the spot now
  }

  /** The hail history at a point. The sheet opens at once with the loading line, and the cell's words replace it when
      its tile answers; a click that a newer one has overtaken is dropped. A point off the grid gets the outside words
      with no fetch. In a store file, a point in a tile the store does not list gets them with no fetch, and a point
      whose key the shard's state list lacks gets them after the one fetch; a --sample build gives those two cases the
      sample's own outside words, as describe() does. A build whose history didn't load gets its words with no fetch.
      The address carries the spot as at=lat,lon. */
  function openHail(lat, lon, opener, extra) {
    var h = hailData();
    if (!h) return;
    var p = hailPoint(lat, lon), cell = hailCell(h.grid, p), seq = ++hailSeq;
    var outside = h.state === "sample" ? h.words.sample_outside : h.words.outside;   // a sample build's own words
    var dot = !!(extra && extra.dot);                 // a dot (B3): D23's words off the grid, and its address block on top
    if (dot) outside = b3GridWords();
    hailTopNode = (extra && extra.top) || null;
    hailAt = p.lat + "," + p.lon;
    saveUrl();
    openSheet("hail", h.words.title, "", opener, { noSampleTag: true });   // the sample label comes from the words
    sheetState.ll = cell ? L.latLng(p.lat, p.lon) : null;      // off the grid there is no spot to keep in sight
    if (cell) reveal(sheetState.ll, HAIL_EXT);
    // The live line is set up before the dot return below, on purpose (B4's order, kept where B3 would put the return
    // first): liveOpen() resets the last click's live line, so a dot off the grid must not return first and keep it.
    liveOpen(p, cell, seq);                                             // the live line, when a hail layer is on
    if (!cell && dot) return hailShow(h, "outside", b3GridWords());     // a dot off the hail grid (B3)
    if (!cell) return hailShow(h, "outside", h.words.outside);          // off the grid: outside Montana for certain
    if (h.state === "unavailable") return hailShow(h, "unavailable", fill(h.words.unavailable, { problem: h.problem }));
    if (!hailListed(h, hailTileName(h, cell))) return hailShow(h, "outside", outside);   // no fetch
    hailShow(h, "loading", h.words.loading);
    var current = function () { return seq === hailSeq && sheetState && sheetState.kind === "hail"; };
    var failed = function () { liveMontana("unknown"); hailShow(h, "unavailable", fill(h.words.unavailable, { problem: h.words.fetch_failed })); };
    hailTile(hailShardUrl(h, cell)).then(function (doc) {
      if (!current()) return;
      if (!doc || !Array.isArray(doc.state)) return failed();          // a listed tile that is not in the format
      if (!hailInState(doc, hailKey(h, cell))) {          // in the tile, not in Montana: the live line says so too
        liveMontana(false);
        return hailShow(h, "outside", outside);
      }
      liveMontana(true);
      var text;
      try { text = hailText(h, cell, doc); } catch (e) { return failed(); }
      hailShow(h, "loaded", text, null);                // the radar days at once; the joins follow in their own sections
      joinSections(h, cell).then(function (joins) {     // never rejects: a part that fails says so in its own section
        if (!current() || !joins) return;               // no joins block: the radar days stand alone
        joinRender(el.sheetBody.querySelector('[data-hail="joins"]'), joins);
        if (sheetState && sheetState.ll) reveal(sheetState.ll, HAIL_EXT);   // a longer sheet may cover the spot now
      });
    }, function () { if (current()) failed(); });
  }

  /** A click or tap on the map that no bubble, alert or report took. Leaflet also passes a click on a layer's element
      to the map (a bubble's handler doesn't stop it), so the element the click landed on decides. */
  function onHailClick(e) {
    var target = e.originalEvent && e.originalEvent.target;
    if (target && target.closest && target.closest(".leaflet-interactive, .leaflet-marker-icon")) return;
    openHail(e.latlng.lat, e.latlng.lng, el.canvas);
  }

  /** The spot in the address (?at=lat,lon), as a point, or null. */
  function hailParam() {
    var m = /^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/.exec(params.get("at") || "");
    if (!m) return null;
    var p = hailPoint(Number(m[1]), Number(m[2]));
    return isFinite(p.lat) && isFinite(p.lon) ? p : null;
  }

  // ------------------------------------------------------------------ live hail swath (--storm-layers builds, B4)

  /** The two hail swath layers (data/map.json layers with "kind": "hail_swath"): one picture each on the map's image box,
      with its legend, title and words from the layer block. Their freshness is worked out here, at view time (D7):
      hailView reads the frame's valid time against the viewer's clock and the fresh and stale minutes the build wrote, and
      fills the build's templates; hailWatch runs it again every minute while a hail layer is on, and the picture goes once
      the layer is unavailable. The sheet's live line (liveOpen, liveMontana, liveLoad) reads the clicked cell's tile file once
      per click, and only after the shard has put the point in Montana (F-9). The file's
      URL holds the frame's valid time, so each is read once for the page. A 404 is no file: no cell of the tile reaches the
      floor. It gives the no-estimate words while the layer is fresh or stale (D16). A file's own lists give a cell's value
      (the sizes and the class word come from the hail block) or its no-coverage words. Any other failure gives the build's
      could-not-be-loaded words. A point outside the picture's box gets the build's outside words, with no fetch. Every
      sentence, size, class and threshold is the build's; this code fills them in. */
  var swathTimer = null;             // the check, every minute, of a hail layer's state, while one is on
  var liveNode = null;               // the sheet's live line: a paragraph kept first in the sheet's body (liveAttach)
  var liveFor = null;                // the live line of the sheet: {layer, point, cell, seq, inside, got}
  var liveTiles = {};                // live file URL -> promise of its JSON, or of null for "no file"; kept for the page
  var NO_FILE = 404;                 // the status of a tile with no live file (D4)

  /** The hail swath layer on the map now, or null. */
  function swathLayer() { var lay = layer(); return lay.kind === "hail_swath" ? lay : null; }

  /** The state of a hail layer at this moment (D7): "fresh", "stale" or "unavailable", its line (the build's templates,
      with the age worked out now), the age in whole minutes and, when unavailable, the problem. The age is the viewer's
      clock less the frame's valid time; a clock behind the file's time reads as age zero. A layer with no picture is
      unavailable with the build's own line. */
  /** The sample label a sample build's state lines begin with (D10): the build's own words; "" on a real build. */
  function swathPre(lay) { return lay && lay.sample ? lay.words.sample_sheet + " " : ""; }

  function hailView(lay) {
    lay = lay || swathLayer();
    var pre = swathPre(lay);
    if (!lay || !lay.frames || !lay.frames.length) return { state: "unavailable", line: lay ? pre + lay.state_line : "", age: null, problem: null };
    var w = lay.words, ms = Math.max(0, Date.now() - Date.parse(lay.valid)), age = Math.floor(ms / MIN);
    // the timeline's line has no clock time of its own: the day clock above it is the one time (browser-13)
    if (ms <= lay.fresh_min * MIN) return { state: "fresh", line: pre + fill(w.timeline_fresh, { age: age }), age: age, problem: null };
    // {limit} is the fresh minutes here: "more than {limit} minutes old" (the module writes the same, swath.py _drawn)
    if (ms <= lay.stale_min * MIN) return { state: "stale", line: pre + fill(w.timeline_stale, { age: age, limit: lay.fresh_min }), age: age, problem: null };
    var problem = fill(w.age_out, { age: Math.ceil(ms / MIN), limit: lay.stale_min });
    return { state: "unavailable", line: pre + fill(w.unavailable, { title: lay.title, problem: problem }), age: age, problem: problem };
  }

  /** Whether the picture may show: a hail layer's picture is not drawn once the layer is unavailable (D7). */
  function hailShowable() { var lay = swathLayer(); return !lay || hailView(lay).state !== "unavailable"; }

  /** The check each minute (D7): on while a hail layer is on, off with any other layer. */
  function hailWatch(on) {
    if (on && !swathTimer) swathTimer = setInterval(hailTick, STATE_TICK);
    if (!on && swathTimer) { clearInterval(swathTimer); swathTimer = null; }
  }

  /** One check: the timeline's line, the picture (gone once unavailable) and the sheet's live line, from what is known
      already. No request is made here. */
  function hailTick() {
    if (!swathLayer()) return hailWatch(false);
    if (state.frames.length) renderTimeline();
    if (!hailShowable()) showPicture(null);
    liveRender();
  }

  /** The words of the sheet's live line for a clicked point, for the state the layer is in now (D5, D9, D16). */
  function liveText(f) {
    var lay = f.layer, v = hailView(lay), w = lay.words, pre = swathPre(lay);   // a sample build's line begins with its label (D10)
    if (!f.inside) return pre + w.outside;              // the picture's box does not reach the point: nothing is drawn there
    // Montana decides (B1): a point the store puts outside Montana shows no value, and "unknown" (the store or the
    // shard did not load) shows no value either; neither says "no hail"
    if (f.montana === false) return v.state === "unavailable" ? v.line : pre + w.outside_montana_live;
    if (f.montana === "unknown") return v.state === "unavailable" ? v.line : pre + w.live_failed;
    if (f.montana === "pending" || !f.got) return v.state === "unavailable" ? v.line : pre + w.live_loading;   // still being read (D16)
    if (f.got.failed) return pre + w.live_failed;       // a fetch error other than 404 (D16), in any state
    if (v.state === "unavailable") return v.line;       // an unavailable layer's words, and no value from it (D16); labelled in hailView
    var H = hailData(), doc = f.got.doc, row = f.cell.row, col = f.cell.col, hit = doc ? liveFind(doc.cells, row, col) : null, line;
    if (doc && liveFind(doc.nocov, row, col)) line = w.no_coverage;
    else if (hit) {
      var cls = hailClass(H, hit[2]);
      line = fill(w.live_line, { window: lay.window_word, "in": hailInches(H, hit[2]), mm: hailMm(H, hit[2]),
        "class": cls ? cls.word : "", valid: lay.valid_text });
      if (hit[2] >= H.large_note_tenths) line += " " + w.large_note;
    } else line = fill(w.no_estimate, { window: lay.window_word, valid: lay.valid_text });   // no file, or no entry: no estimate
    if (v.state === "stale") line += " " + w.all_clear;
    return pre + line;
  }

  /** The entry [row, column, ...] of one cell in a live file's list (its cells or its nocov), or null. */
  function liveFind(list, row, col) {
    for (var i = 0; list && i < list.length; i++) if (list[i][0] === row && list[i][1] === col) return list[i];
    return null;
  }

  /** Writes the live line from what is known now (the minute's check calls it again, with no request). */
  function liveRender() {
    if (!liveFor || !liveNode) return;
    liveNode.textContent = liveText(liveFor);
    liveAttach();
  }

  /** The live line sits right after a dot's address block (B3: hailTopEnd), or first when the sheet has none. The
      sheet's own lines are written over the body at each change (hailShow), and the line goes back in its place. */
  function liveAttach() {
    if (!liveNode || !sheetState || sheetState.kind !== "hail") return;
    var end = hailTopEnd && hailTopEnd.parentNode === el.sheetBody ? hailTopEnd : null;
    if (liveNode.parentNode === el.sheetBody && liveNode.previousSibling === end) return;   // already in place
    el.sheetBody.insertBefore(liveNode, end ? end.nextSibling : el.sheetBody.firstChild);
  }

  /** The shard's answer on whether the point is in Montana (openHail): the live line follows it at once. Only a point the
      shard puts in Montana reads its live file (liveLoad), so a point outside Montana reads the shard alone (D16, F-9). */
  function liveMontana(value) {
    if (!liveFor || !liveCurrent(liveFor.seq)) return;
    liveFor.montana = value;
    if (value === true) liveLoad(liveFor);
    liveRender();
  }

  /** Reads a point's live file once (liveFile) when its shard has put the point in Montana (liveMontana calls it): only
      inside the picture's box, in a tile the store lists, with a folder. A 404 is no file (D16); any other failure is the
      could-not-be-loaded words. */
  function liveLoad(f) {
    var H = hailData(), lay = f.layer;
    if (f.got || !f.inside || !f.cell || !H || !lay.live || !lay.live.pattern) return;
    liveFile(lay.live.pattern.replace("{tile}", hailTileName(H, f.cell))).then(function (doc) {
      if (!liveCurrent(f.seq)) return;
      f.got = { doc: doc };
      liveRender();
    }, function () {
      if (!liveCurrent(f.seq)) return;
      f.got = { failed: true };
      liveRender();
    });
  }

  /** Whether an answer belongs to the sheet that is open now: a newer click, or a closed sheet, overtakes it. */
  function liveCurrent(seq) { return seq === hailSeq && !!sheetState && sheetState.kind === "hail"; }

  /** One live file, read once for the page: its URL holds the frame's valid time, so a stamp is read once. A 404 gives
      null (no file for the tile). Any other failure rejects, and the next click asks again. */
  function liveFile(url) {
    if (!liveTiles[url]) {
      liveTiles[url] = fetch(url, { credentials: "same-origin" }).then(function (r) {
        if (r.status === NO_FILE) return null;
        if (!r.ok) throw new Error(url);
        return r.json().then(function (doc) {
          if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new Error(url);
          return doc;
        }, function () { throw new Error(url); });
      }, function () { throw new Error(url); });
      liveTiles[url].then(null, function () { delete liveTiles[url]; });
    }
    return liveTiles[url];
  }

  /** The sheet's live line for a clicked point (openHail calls it for every point). With a hail layer on, the point's
      tile is read once (liveFile), after the shard says the point is in Montana (liveMontana); with none, there is no line and
      no request. The cell (null off the grid) and whether the
      picture's box holds the point decide the words. */
  function liveOpen(p, cell, seq) {
    var lay = swathLayer(), H = hailData();
    liveFor = null;
    liveNode = null;
    if (!lay || !H) return;
    liveNode = document.createElement("p");
    liveNode.className = "sub";
    liveNode.setAttribute("data-live", "swath");
    var b = lay.bounds;                                 // [[south, west], [north, east]]: the picture's box
    var inside = !!cell && p.lat >= b[0][0] && p.lat <= b[1][0] && p.lon >= b[0][1] && p.lon <= b[1][1];
    // Montana, as the store says (openHail reads the tile's shard): a tile the store does not list has no Montana cell,
    // so the answer is known now and no file is read; a listed tile waits for its shard ("pending"); "unknown" when the
    // store did not load, which is no answer either way
    var montana = !cell ? false : H.state === "unavailable" ? "unknown" : hailListed(H, hailTileName(H, cell)) ? "pending" : false;
    liveFor = { layer: lay, point: p, cell: cell, seq: seq, inside: inside, montana: montana, got: null };
    liveRender();   // no request here: a listed tile waits for its shard, and liveMontana(true) reads the file (liveLoad, F-9)
  }

  // ------------------------------------------------------------------ joined records at a spot (--hail-history builds, B2)

  /** The six joined sections under the radar estimate, in JOIN_PARTS order. They follow the rules and the templates of
      website/joins.py describe_joins (the town pages write the same sentences from the same records), so a sheet and a
      town page for one cell say the same words. The build writes the record files (hail/j per tile, hail/z per zone and
      per fire weather zone, hail/s per station), the templates (hail.joins.words), the shard templates, the radii and the
      earth radius, the counts the lines say, the lags and each part's state. The browser does these steps and no others: the
      tile's file (one fetch, kept for the page); the forecast zone's file, the fire weather zone's file and each station
      file the tile names; the distance from the cell's centre in miles; the filters (reports and records within the report
      radius, detections within the detection radius, the warnings whose cover bit is set for the cell's key, the zone
      products and the station days in the window); the newest-first order; the Montana-time text (Intl, the zone named by
      data.tz); and the fill of the templates. A part the build marks unavailable, or whose file does not load, shows its own
      unavailable sentence and nothing else; a partial part keeps its lead and rows. It writes no sentence, unit, radius or
      threshold of its own: tests/test_site.py runs this block under node and compares it with describe_joins. */
  var JOIN_PARTS = ["reports", "records", "detections", "warnings", "zones", "stations"];
  var joinFmts = null;                        // the Montana-time formatters, made on first use
  // the fields of a joined row, as joins.py writes them: a report or a record, a detection and a station day
  var JROW = { day: 0, hhmm: 1, lat: 2, lon: 3, code: 4, mag: 5, unit: 6, qual: 7, source: 8, city: 9, remark: 10,
    mph: 11, kt: 12 };
  var JDET = { day: 0, hhmm: 1, lat: 2, lon: 3, size: 4 };
  var JDAY = { day: 0, mph: 1, kt: 2 };

  /** The formatters for a Montana calendar date and for a clock time with its zone. */
  function joinFormats() {
    if (!joinFmts) {
      joinFmts = {
        day: new Intl.DateTimeFormat("en-US", { timeZone: data.tz, month: "short", day: "numeric", year: "numeric" }),
        clock: new Intl.DateTimeFormat("en-US", { timeZone: data.tz, hour: "numeric", minute: "2-digit", hour12: true,
                                                  timeZoneName: "short" })
      };
    }
    return joinFmts;
  }

  /** "Jun 14, 2025": the Montana calendar date of an instant (ms), as describe_joins writes a local date. */
  function joinDay(ms) { return joinFormats().day.format(new Date(ms)); }

  /** The qualifier part of a record row (" (word)"), or "" when the code has no word: the module's _qualifier lookup. */
  function joinQualifier(J, code) {
    var word = code ? (J.qualifiers[code] || J.ncei_qualifiers[code] || "") : "";
    return word ? fill(J.words.qualifier_part, { qualifier: word }) : "";
  }

  /** The clock text of an instant in Montana time, from the build's time template (hour, minute, am or pm, zone). */
  function joinClock(J, ms) {
    var p = {};
    joinFormats().clock.formatToParts(new Date(ms)).forEach(function (x) { p[x.type] = x.value; });
    return fill(J.words.time, { hour: p.hour, minute: p.minute, ampm: p.dayPeriod === "AM" ? J.words.am : J.words.pm,
      zone: p.timeZoneName });
  }

  /** The UTC instant of a record: its UTC day index (counted from the store's d0) and its UTC time as hhmm. */
  function joinInstant(h, day, hhmm) {
    return Date.parse(h.d0) + day * HAIL_DAY_MS + (Math.floor(hhmm / 100) * 60 + hhmm % 100) * MIN;
  }

  /** The great-circle distance in miles between two points, on the earth radius and mile length the build wrote. */
  function joinMiles(J, lat1, lon1, lat2, lon2) {
    var r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLon = (lon2 - lon1) * r;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * J.earth_radius_km * Math.asin(Math.min(1, Math.sqrt(a))) / J.km_per_mile;
  }

  /** The compass word from one point to another: the bearing clockwise from north, in the build's words (joins.compass). */
  function joinCompass(J, lat1, lon1, lat2, lon2) {
    var r = Math.PI / 180, dl = (lon2 - lon1) * r;
    var y = Math.sin(dl) * Math.cos(lat2 * r);
    var x = Math.cos(lat1 * r) * Math.sin(lat2 * r) - Math.sin(lat1 * r) * Math.cos(lat2 * r) * Math.cos(dl);
    var turn = 2 * Math.PI, n = J.compass.length, step = turn / n;
    return J.compass[Math.floor((((Math.atan2(y, x) + turn) % turn) + step / 2) % turn / step) % n];
  }

  /** Whether a warning covers a cell: the build's cover is one bit per cell key, key 0 the lowest bit of the 25 hex digits. */
  function joinCovers(hex, key) {
    var text = String(hex), n = Math.floor(key / 4);          // four keys to a hex digit
    return ((parseInt(text.charAt(text.length - 1 - n), 16) >> (key % 4)) & 1) === 1;
  }

  /** The SPC report day of an instant: the UTC date of the instant less the report day's start hour (joins.spc_day). */
  function joinSpcIso(J, ms) { return new Date(ms - J.spc_hours * HOUR).toISOString().slice(0, 10); }

  /** The centre of a cell, in degrees, from the grid in map.json (the same arithmetic as hailCell, read back). */
  function hailCentre(g, cell) {
    var per = Math.round(1 / g.cell_deg);     // cells per degree
    return { lat: g.row0_lat - cell.row / per, lon: g.col0_lon + cell.col / per };
  }

  /** The magnitude of a row (joins._magnitude): a speed in knots with its miles per hour beside it, or a magnitude in its
      unit (the build's words); "" is missing and shows the build's "no size given" words. */
  function joinMagnitude(J, r) {
    var W = J.words, text = r[JROW.mag], unit = r[JROW.unit];
    if (r[JROW.kt] !== null && r[JROW.kt] !== undefined) return fill(W.magnitude_kt_mph, { value: r[JROW.kt], mph: r[JROW.mph] });
    if (text === null || text === undefined || text === "") return W.magnitude_none;
    if (unit === J.hail_unit) return fill(W.magnitude_in, { value: Number(text).toFixed(2) });
    return fill(W[J.unit_words[unit]] || W.magnitude_unitless, { value: text });
  }

  /** The text of a report row (joins._report_text): the label, the Montana date and time, the type word, the magnitude when
      the code has a unit (J.unit_codes), the qualifier, the source, the distance and the bearing (none for a spot at the
      centre). A code with no unit shows its type word and qualifier only (D19). */
  function joinReportText(J, r, ms, miles, bearing) {
    var W = J.words, code = r[JROW.code], typed = J.unit_codes.indexOf(code) < 0, here = bearing === null;
    var base = { date: joinDay(ms), time: joinClock(J, ms), type: J.types[code] || String(code || "").toLowerCase(),
      qualifier: joinQualifier(J, r[JROW.qual]), source: r[JROW.source] || "", miles: miles.toFixed(1) };
    if (!typed) base.magnitude = joinMagnitude(J, r);
    if (!here) base.bearing = bearing;
    var key = here ? (typed ? "reports_row_here_typed" : "reports_row_here") : (typed ? "reports_row_typed" : "reports_row");
    return fill(W[key], base);
  }

  /** The text of a record row (joins._record_text): the label of a record, the magnitude when its type carries a unit
      (J.unit_codes, D19), the qualifier, the source, the distance and the bearing. */
  function joinRecordText(J, r, ms, miles, bearing) {
    var W = J.words, typed = J.unit_codes.indexOf(r[JROW.code]) < 0, here = bearing === null;
    var base = { date: joinDay(ms), time: joinClock(J, ms), type: r[JROW.code], qualifier: joinQualifier(J, r[JROW.qual]),
      source: r[JROW.source] || "", miles: miles.toFixed(1) };
    if (!typed) base.magnitude = joinMagnitude(J, r);
    if (!here) base.bearing = bearing;
    var key = here ? (typed ? "records_row_here_typed" : "records_row_here") : (typed ? "records_row_typed" : "records_row");
    return fill(W[key], base);
  }

  /** The text of a zone record row (joins._zone_record_text): the same words with the zone's code in place of the place. */
  function joinZoneRecordText(J, r, ms, zone) {
    var W = J.words, typed = J.unit_codes.indexOf(r[JROW.code]) < 0;
    var base = { date: joinDay(ms), time: joinClock(J, ms), type: r[JROW.code], qualifier: joinQualifier(J, r[JROW.qual]),
      source: r[JROW.source] || "", zone: zone };
    if (!typed) base.magnitude = joinMagnitude(J, r);
    return fill(W[typed ? "records_zone_row_typed" : "records_zone_row"], base);
  }

  /** The unavailable sentence of a part (joins._unavailable_text, D20): the build's sentence with the part's name and its
      singular. A part with some periods that did not load gets the partial sentence, with its periods and reason. */
  function joinUnavailable(J, part, periods, reason) {
    var W = J.words;
    if (periods && periods.length) return fill(W.partial, { feed: W["feed_" + part], periods: periods.join(", "),
      reason: reason || (J.reasons && J.reasons[part]) || W.reason_no_answer });
    return fill(W.unavailable, { part: W["part_" + part], one: W["one_" + part] });
  }

  /** The words for the reason a file did not load (D27): the file did not answer, or it was in an unexpected format. */
  function joinReason(W, err) { return err && err.reason === "format" ? W.reason_format : W.reason_no_answer; }

  /** The zone code whose cell keys include a key, in the tile's map of field ("zones" for the forecast zones, "fire" for the
      fire weather zones: {code: [keys]}); null when none does. */
  function joinZoneOf(j, field, key) {
    var zones = j[field] || {}, codes = Object.keys(zones);
    for (var i = 0; i < codes.length; i++) { if (zones[codes[i]].indexOf(key) >= 0) return codes[i]; }
    return null;
  }

  /** The heading of a section: the zone's name and code for the zone products (zones_heading, or the no-zone heading), else
      the section's own heading. */
  function joinHeading(W, k, zoneName, zone) {
    if (k !== "zones") return W[k + "_heading"];
    return zone ? fill(W.zones_heading, { zone_name: zoneName, zone: zone }) : W.zones_heading_no_zone;
  }

  /** The events table (hail/j/events.json), read as the format it is written in (joins._read_events): a file in any other
      format is a failed load, and the three sections it feeds say so. */
  function joinEvents(J, url) {
    return hailTile(url).then(function (doc) {
      if (doc.f !== J.events_format) throw hailFailure("format", url);
      return doc;
    });
  }

  /** A zone, fire weather zone or station file as the sheet reads it (joins._read_part_file, D27): where it has them, its row
      lists are arrays. A file that is not in that shape is a failed load, in the format. */
  function joinFile(url) {
    return hailTile(url).then(function (doc) {
      if (["events", "records", "days"].some(function (k) { return doc[k] !== undefined && !Array.isArray(doc[k]); })) {
        throw hailFailure("format", url);
      }
      return doc;
    });
  }

  /** The record files one cell needs: the events table (hail/j/events.json, one fetch for the page, which holds every
      report, record and warning row once), the cell's tile (one fetch), then the forecast zone, the fire weather zone and each
      station file the tile names. Resolves with {j, events, eventsError, zoneCode, zone, fireCode, fire, stations, sdocs}; a
      part that fails holds its error. The tile's own failure is the whole result's error. Never rejects. */
  function joinLoad(h, cell) {
    var J = h.joins, key = hailKey(h, cell), name = hailTileName(h, cell);
    var part = function (load, url) {
      return load(url).then(function (doc) { return { doc: doc }; }, function (e) { return { error: e }; });
    };
    return part(function (url) { return joinEvents(J, url); }, J.events).then(function (ev) {
      return part(hailTile, J.shards.j.replace("{tile}", name)).then(function (got) {
        if (got.error) return { error: got.error };
        var j = got.doc, zoneCode = joinZoneOf(j, "zones", key), fireCode = joinZoneOf(j, "fire", key), list = j.stations || [];
        return Promise.all([
          zoneCode ? part(joinFile, J.shards.z.replace("{zone}", zoneCode)) : null,
          fireCode ? part(joinFile, J.shards.fire.replace("{zone}", fireCode)) : null,
          Promise.all(list.map(function (st) { return part(joinFile, J.shards.s.replace("{station}", st.id)); }))
        ]).then(function (all) {
          return { j: j, events: ev.doc || null, eventsError: ev.error || null, zoneCode: zoneCode, zone: all[0],
            fireCode: fireCode, fire: all[1], stations: list, sdocs: all[2] };
        });
      });
    });
  }

  /** The six sections for one cell (never rejects): {reports, records, detections, warnings, zones, stations, times}; each
      section {id, heading, what, lead, rows, lines, unavailable}, and a row {text, remark}. A section that did not load says
      so in its unavailable sentence and shows nothing else, except a partial part, which keeps its lead and rows. */
  function joinSections(h, cell) {
    if (!h.joins || !h.joins.words) return Promise.resolve(null);
    var J = h.joins, W = J.words, key = hailKey(h, cell), spot = hailCentre(h.grid, cell);
    var lag = J.lags || {}, counts = J.counts || {};
    var parts = function (k) { return J.parts[k] === "unavailable" ? "unavailable" : J.parts[k] === "partial" ? "partial" : "loaded"; };
    var shell = function (k, heading) {
      return { id: k, heading: heading, what: [W[k + "_what"], W["source_" + k]].filter(Boolean).join(" "), lead: "",
        fire_lead: "", rows: [], lines: [], unavailable: null };
    };
    var finish = function (out) {
      JOIN_PARTS.forEach(function (k) {
        out[k].showFirst = J.show_first;
        out[k].showAll = fill(W.show_all, { n: out[k].rows.length });
        out[k].sample = J.state === "sample" ? W.sample : "";      // a sample build labels each section, as the B1 tag does
      });
      out.times = W.times_note;
      return out;
    };
    var allUnavailable = function () {               // every part says why and shows nothing else (the town pages do the same)
      var out = {};
      JOIN_PARTS.forEach(function (k) { out[k] = shell(k, joinHeading(W, k, null, null)); out[k].unavailable = joinUnavailable(J, k); });
      return finish(out);
    };
    if (J.state === "unavailable") return Promise.resolve(allUnavailable());   // no records in the store: no fetch; the words say why
    var ftn = { start: hailDate(J.window[0]), end: hailDate(J.window[1]) };   // read only once the store is known to hold records
    var joinFill = function (got) {
      var out = {};
      JOIN_PARTS.forEach(function (k) { out[k] = shell(k, joinHeading(W, k, null, null)); });
      var j = got.j, zoneErr = got.zoneCode && got.zone && got.zone.error ? got.zone.error : null, zoneLost = !!zoneErr;
      var zdoc = got.zone && !got.zone.error ? got.zone.doc : null;
      var fdoc = got.fire && !got.fire.error ? got.fire.doc : null, fireLost = !!(got.fireCode && got.fire && got.fire.error);
      if (got.zoneCode) out.zones.heading = joinHeading(W, "zones", J.zone_names[got.zoneCode] || got.zoneCode, got.zoneCode);
      var within = function (b) {                        // a time that does not parse is not in the window
        if (isNaN(b)) return false;
        var iso = new Date(b).toISOString().slice(0, 10);
        return iso >= J.window[0] && iso <= J.window[1];
      };

      // reports: the point rows within the report radius of the centre, newest first (describe_joins "reports")
      if (parts("reports") === "unavailable" || !got.events) out.reports.unavailable = joinUnavailable(J, "reports");
      else {
        var rep = [];
        (j.reports || []).forEach(function (ref) {
          var r = got.events.reports[ref], miles = joinMiles(J, spot.lat, spot.lon, r[JROW.lat], r[JROW.lon]);
          if (miles <= J.radius_miles.report) rep.push({ ms: joinInstant(h, r[JROW.day], r[JROW.hhmm]), miles: miles, r: r });
        });
        rep.sort(function (a, b) { return b.ms - a.ms; });
        out.reports.lead = fill(W[rep.length === 1 ? "reports_lead_one" : rep.length ? "reports_lead_many" : "reports_lead_none"],
          Object.assign({ n: rep.length }, ftn));
        out.reports.rows = rep.map(function (x) {
          var bearing = x.miles < J.here_miles ? null : joinCompass(J, spot.lat, spot.lon, x.r[JROW.lat], x.r[JROW.lon]);
          return { text: joinReportText(J, x.r, x.ms, x.miles, bearing),
            remark: x.r[JROW.remark] ? fill(W.remark_line, { remark: x.r[JROW.remark] }) : "" };
        });
        if (parts("reports") === "partial") out.reports.unavailable = joinUnavailable(J, "reports", J.partial.reports);
      }

      // official records: the NCEI point rows within the report radius, then the zone's rows (describe_joins "records")
      if (parts("records") === "unavailable" || !got.events) out.records.unavailable = joinUnavailable(J, "records");
      else {
        var rec = [];
        (j.records || []).forEach(function (ref) {
          var r = got.events.records[ref], miles = joinMiles(J, spot.lat, spot.lon, r[JROW.lat], r[JROW.lon]);
          if (miles <= J.radius_miles.report) rec.push({ ms: joinInstant(h, r[JROW.day], r[JROW.hhmm]), miles: miles, r: r, zone: null });
        });
        ((zdoc && zdoc.records) || []).forEach(function (r) {
          rec.push({ ms: joinInstant(h, r[JROW.day], r[JROW.hhmm]), miles: null, r: r, zone: got.zoneCode });
        });
        rec.sort(function (a, b) { return b.ms - a.ms; });
        var newest = lag.ncei ? hailDate(lag.ncei) : W.unknown_date;
        out.records.lead = fill(W[rec.length === 1 ? "records_lead_one" : rec.length ? "records_lead_many" : "records_lead_none"],
          Object.assign({ n: rec.length, newest: newest }, ftn));
        out.records.rows = rec.map(function (x) {
          if (x.zone !== null) return { text: joinZoneRecordText(J, x.r, x.ms, x.zone), remark: "" };
          var bearing = x.miles < J.here_miles ? null : joinCompass(J, spot.lat, spot.lon, x.r[JROW.lat], x.r[JROW.lon]);
          return { text: joinRecordText(J, x.r, x.ms, x.miles, bearing), remark: "" };
        });
        if (counts.ncei_zone_rows_unmatched) out.records.lines.push(fill(W[counts.ncei_zone_rows_unmatched === 1 ? "records_unplaced_one" : "records_unplaced_many"],
          { n: counts.ncei_zone_rows_unmatched }));
        if (parts("records") === "partial") out.records.unavailable = joinUnavailable(J, "records", J.partial.records);
        if (zoneLost) out.records.unavailable = joinUnavailable(J, "records", [got.zoneCode], joinReason(W, zoneErr));   // D27
      }

      // radar detections: the hail detections within the detection radius, grouped by SPC day (describe_joins "detections")
      if (parts("detections") === "unavailable") out.detections.unavailable = joinUnavailable(J, "detections");
      else {
        var byDay = {}, detN = 0;
        (j.detections || []).forEach(function (d) {
          if (joinMiles(J, spot.lat, spot.lon, d[JDET.lat], d[JDET.lon]) > J.radius_miles.detection) return;
          var iso = joinSpcIso(J, joinInstant(h, d[JDET.day], d[JDET.hhmm]));
          (byDay[iso] || (byDay[iso] = [])).push(d[JDET.size]);
          detN += 1;
        });
        out.detections.lead = fill(W[detN === 1 ? "detections_lead_one" : detN ? "detections_lead_many" : "detections_lead_none"],
          Object.assign({ n: detN }, ftn));
        out.detections.rows = Object.keys(byDay).sort().reverse().map(function (iso) {
          var sizes = byDay[iso], largest = Math.max.apply(null, sizes), inches = (largest / J.hundredths_per_inch).toFixed(2);
          return { text: fill(W[sizes.length === 1 ? "detections_row_one" : "detections_row_many"],
            { date: hailDate(iso), n: sizes.length, "in": inches }), remark: "" };
        });
        out.detections.lines = [lag.swdi ? fill(W.detections_lag, { newest: hailDate(lag.swdi) }) : W.detections_lag_none];
        if (parts("detections") === "partial") out.detections.unavailable = joinUnavailable(J, "detections", J.partial.detections);
      }

      // warnings: the warnings whose cover has this cell's key, newest first (describe_joins "warnings")
      if (parts("warnings") === "unavailable" || !got.events) out.warnings.unavailable = joinUnavailable(J, "warnings");
      else {
        var wrn = [];
        (j.warnings || []).forEach(function (pair) {
          if (!joinCovers(pair[1], key)) return;
          var item = got.events.warnings[pair[0]];
          wrn.push({ b: Date.parse(item.b), e: Date.parse(item.e), w: item });
        });
        wrn.sort(function (a, b) { return b.b - a.b; });
        var noOutline = counts.warnings_no_outline || 0;
        out.warnings.lead = !wrn.length && noOutline ? W.warnings_lead_unknown
          : fill(W[wrn.length === 1 ? "warnings_lead_one" : wrn.length ? "warnings_lead_many" : "warnings_lead_none"],
            Object.assign({ n: wrn.length }, ftn));
        out.warnings.rows = wrn.map(function (x) {
          var t = x.w.tags || {}, tags = [];
          if (t.hail_in !== null && t.hail_in !== undefined) tags.push(fill(W.tag_hail, { value: Number(t.hail_in).toFixed(2) }));
          if (t.wind_mph !== null && t.wind_mph !== undefined) tags.push(fill(W.tag_wind, { value: String(Math.round(t.wind_mph)) }));
          if (t.tornado) tags.push(fill(W.tag_tornado, { value: String(t.tornado).toLowerCase() }));
          if (t.damage) tags.push(fill(W.tag_damage, { value: String(t.damage).toLowerCase() }));
          var ends = joinDay(x.e) === joinDay(x.b) ? "" : joinDay(x.e) + " ";      // the end's date only on a later Montana day
          return { text: fill(W.warnings_row, { date: joinDay(x.b), begin: joinClock(J, x.b), end: ends + joinClock(J, x.e),
            kind: J.kinds[x.w.k] || x.w.k, office: x.w.o, tags: tags.length ? tags.join(", ") : W.warnings_tags_none }), remark: "" };
        });
        out.warnings.lines = [lag.warnings ? fill(W.warnings_lag, { newest: hailDate(lag.warnings) }) : W.warnings_lag_none];
        if (noOutline) out.warnings.lines.push(fill(W[noOutline === 1 ? "warnings_no_outline_one" : "warnings_no_outline_many"],
          { n: noOutline }));
        if (parts("warnings") === "partial") out.warnings.unavailable = joinUnavailable(J, "warnings", J.partial.warnings);
      }

      // zone products: the forecast zone's products and the fire weather zone's red flag warnings (D7, D17), windowed and
      // ordered by their begin, or by their end when the begin is not recorded (joins._zone_when)
      if (parts("zones") === "unavailable" || zoneLost) out.zones.unavailable = joinUnavailable(J, "zones");
      else {
        var groups = {}, zoneN = 0, fireN = 0, fireName = null;
        var add = function (e, fireLabel) {                  // fireLabel: the fire weather zone's name, or null for a forecast zone
          var begin = e.b ? Date.parse(e.b) : null, endAt = e.e ? Date.parse(e.e) : null;
          var when = begin !== null ? begin : endAt;          // the time an event is windowed and ordered by (joins._zone_when)
          if (when === null || !within(when)) return false;
          var name = J.products[e.k + "." + e.s] || (e.k + "." + e.s);
          if (fireLabel !== null) name = fill(W.fire_product, { product: name, zone_name: fireLabel, zone: got.fireCode });
          (groups[name] || (groups[name] = [])).push({ b: begin, e: endAt, when: when, stop: joinStop(e) });
          return true;
        };
        ((zdoc && zdoc.events) || []).forEach(function (e) { if (add(e, null)) zoneN += 1; });
        if (fdoc) {
          fireName = fdoc.name || J.fire_zone_names[got.fireCode] || got.fireCode;
          (fdoc.events || []).forEach(function (e) { if (add(e, fireName)) fireN += 1; });
        }
        var zoneName = J.zone_names[got.zoneCode] || got.zoneCode;
        out.zones.lead = !got.zoneCode ? W.zones_no_zone
          : fill(W[zoneN === 1 ? "zones_lead_one" : zoneN ? "zones_lead_many" : "zones_lead_none"],
            { n: zoneN, zone_name: zoneName, zone: got.zoneCode, start: ftn.start, end: ftn.end });
        Object.keys(groups).sort(function (a, b) { return minOf(groups[b]) - minOf(groups[a]); }).forEach(function (name) {
          var texts = groups[name].sort(function (a, b) { return a.when - b.when; }).map(function (ev) { return joinZoneSpan(J, ev); });
          out.zones.rows.push({ text: fill(W.zones_row, { product: name, events: texts.join("; ") }), remark: "" });
        });
        if (counts.zone_products_unplaced) out.zones.lines.push(fill(W[counts.zone_products_unplaced === 1 ? "zones_unplaced_one" : "zones_unplaced_many"],
          { n: counts.zone_products_unplaced }));
        if (J.fire_state !== "loaded" || fireLost) out.zones.lines.push(W.zones_fire_unavailable);
        else if (!got.fireCode) out.zones.lines.push(W.zones_fire_none);
        else out.zones.fire_lead = fill(W[fireN === 1 ? "fire_lead_one" : fireN ? "fire_lead_many" : "fire_lead_none"],
          { n: fireN, zone_name: fireName, zone: got.fireCode, start: ftn.start, end: ftn.end });
        if (parts("zones") === "partial") out.zones.unavailable = joinUnavailable(J, "zones", J.partial.zones);
      }

      // station gusts: the station days in the window, newest first, and the days each station's file dropped (describe_joins)
      var stationLost = got.sdocs.some(function (x) { return x && x.error; });     // a station file that did not load (D27)
      if (parts("stations") === "unavailable" || stationLost) out.stations.unavailable = joinUnavailable(J, "stations");
      else if (!got.stations.length) out.stations.lead = fill(W.stations_none_near, { miles: Math.floor(J.radius_miles.station) });
      else {
        var days = [], dropped = 0;
        got.stations.forEach(function (st, i) {
          var sdoc = got.sdocs[i] && !got.sdocs[i].error ? got.sdocs[i].doc : null;
          ((sdoc && sdoc.days) || []).forEach(function (row) {
            var iso = hailIso(h, row[JDAY.day]);
            if (iso < J.window[0] || iso > J.window[1]) return;
            days.push({ iso: iso, mph: row[JDAY.mph], kt: row[JDAY.kt], st: st });
          });
          dropped += (sdoc && sdoc.dropped) || 0;
        });
        days.sort(function (a, b) { return a.iso < b.iso ? 1 : a.iso > b.iso ? -1 : b.mph - a.mph; });
        out.stations.lead = fill(W[days.length === 1 ? "stations_lead_one" : days.length ? "stations_lead_many" : "stations_lead_none"],
          Object.assign({ n: days.length, kt_min: J.station_kt, mph_min: J.station_mph }, ftn));
        out.stations.rows = days.map(function (x) {
          return { text: fill(W.stations_row, { date: hailDate(x.iso), kt: Math.floor(x.kt), mph: Math.floor(x.mph),
            station: x.st.name, miles: Number(x.st.miles).toFixed(1) }), remark: "" };
        });
        if (dropped) out.stations.lines.push(fill(W[dropped === 1 ? "stations_dropped_one" : "stations_dropped"],
          { n: dropped, kt: J.implausible_kt }));
      }
      if (parts("stations") === "partial" && !stationLost) out.stations.unavailable = joinUnavailable(J, "stations", J.partial.stations);
      return finish(out);
    };
    return joinLoad(h, cell).then(function (got) {
      if (got.error) return allUnavailable();                        // the tile did not load: all six say so
      try { return joinFill(got); } catch (e) { return allUnavailable(); }    // a file in a shape the sheet cannot read
    }, allUnavailable);
  }

  /** The earliest instant of a zone group's events, by their windowing time (the begin, or the end when there is none). */
  function minOf(list) { return list.reduce(function (m, x) { return x.when < m ? x.when : m; }, Infinity); }

  /** The stop that ended a zone event (joins.ZONE_STOP_STATE, D31): "cancelled" or "upgraded", the status the build gives the
      event's "st"; null when no stop ended it. Its words are zones_<stop> and zones_<stop>_at in WORDS_JOINS. */
  function joinStop(e) { return e.st === "cancelled" || e.st === "upgraded" ? e.st : null; }

  /** One zone event's span in words (joins._zone_event_text, D6, D16, D26, D31): "{date} {begin} to {end}", "end not recorded"
      when there is no end, "start not recorded; end {end}" when there is no begin. An end at or before the begin of a stop
      reads "{stop} at {time}" in place of the span (zones_<stop>_at); a stop's word follows the span (zones_<stop>). */
  function joinZoneSpan(J, ev) {
    var W = J.words, text, stop = ev.stop ? "zones_" + ev.stop : null;
    if (stop && ev.b !== null && ev.e !== null && ev.e <= ev.b) return fill(W[stop + "_at"], { time: joinSpanEnd(J, ev.e, null) });
    if (ev.b === null && ev.e === null) text = W.zones_event_no_span;
    else if (ev.b === null) text = fill(W.zones_event_no_start, { end: joinSpanEnd(J, ev.e, null) });
    else text = fill(W.zones_event, { date: joinDay(ev.b), begin: joinClock(J, ev.b),
      end: ev.e === null ? W.zones_end_unset : joinSpanEnd(J, ev.e, ev.b) });
    return text + (stop ? W[stop] : "");
  }

  /** The end of a span in Montana time (joins.fmt_end): the clock alone on the begin's day, the date and clock on a later
      day, and the date and clock when there is no begin. */
  function joinSpanEnd(J, e, b) {
    if (b === null || joinDay(e) !== joinDay(b)) return joinDay(e) + " " + joinClock(J, e);
    return joinClock(J, e);
  }

  /** The rows of one section as a list: the text, and the remark (when there is one) on a line of its own. */
  function joinList(list, rows) {
    list.hidden = !rows.length;
    rows.forEach(function (row) {
      var li = document.createElement("li");
      li.textContent = row.text;
      if (row.remark) { var small = document.createElement("small"); small.textContent = row.remark; li.appendChild(small); }
      list.appendChild(li);
    });
  }

  /** The six sections, in order, cloned from the template in map.html (#hail-join-sec) into the sheet's slot. A section that
      did not load shows its unavailable sentence; a partial part also shows its lead and rows. The rows past the build's first
      count go in the details element, which the reader opens. The zone's note (the Montana time line) follows the sections. */
  function joinRender(slotEl, sections) {
    if (!slotEl) return;
    JOIN_PARTS.forEach(function (key) {
      var sec = sections[key], frag = document.getElementById("hail-join-sec").content.cloneNode(true);
      var root = frag.querySelector(".joins-sec"), at = function (name) { return root.querySelector('[data-join="' + name + '"]'); };
      root.dataset.section = key;
      root.hidden = false;
      at("heading").textContent = sec.heading || "";
      at("sample").textContent = sec.sample || "";
      at("sample").hidden = !sec.sample;
      if (sec.unavailable) { at("unavailable").textContent = sec.unavailable; at("unavailable").hidden = false; }
      at("lead").textContent = sec.lead || "";
      at("lead").hidden = !sec.lead;
      at("fire-lead").textContent = sec.fire_lead || "";
      at("fire-lead").hidden = !sec.fire_lead;
      joinList(at("rows"), sec.rows.slice(0, sec.showFirst));
      if (sec.rows.length > sec.showFirst) {
        at("more").hidden = false;
        at("more-summary").textContent = sec.showAll;
        joinList(at("more-rows"), sec.rows.slice(sec.showFirst));
      }
      at("what").textContent = sec.what || "";
      if (sec.lines && sec.lines.length) { at("note").textContent = sec.lines.join(" "); at("note").hidden = false; }
      slotEl.appendChild(root);
    });
    if (sections.times) {
      var note = document.createElement("p");
      note.className = "muted";
      note.textContent = sections.times;
      slotEl.appendChild(note);
    }
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
        f.kind === "satellite" ? (sample ? "Sample satellite picture" : "NOAA satellite picture") :
        (sample ? "Sample forecast" : "HRRR model forecast")) + " \u00b7 " + clock(state.times[state.pos]);
    }
    // words true of all the hatching in view: a gap in the frame, the band outside the pictures, or both
    var k = f && !f._failed ? hatchKind() : "";
    var html = '<span class="card-main">' + esc(main) + "</span>" + (k ? '<span class="card-hatch"><span class="key ' +
      (k === "outside" ? "key-hatch-out" : "key-hatch") + '" aria-hidden="true"></span>' +
      '<span class="visually-hidden">. Hatched areas: </span>' + esc(hatchWords(k)[0]) + "</span>" : "");
    // the Storm reports card: alerts without an outline aren't on it (the Now page card sits beside
    // the full alert list, so it needn't say). One line on a phone; the page's key says where they are
    var n = state.reports ? noOutlineCount() : 0;
    if (n) html += '<span class="card-alerts"><span class="visually-hidden">. </span>' + esc(n + (n > 1 ? " alerts have" : " alert has") + " no outline") + "</span>";
    if (el.cardChip._html !== html) { el.cardChip.innerHTML = html; el.cardChip._html = html; }
    el.cardChip.classList.toggle("warn", warn);
    if (state.ready && !cardFitting && map && el.cardChip.offsetHeight !== h0) fitView();
  }

  // B3 layers: begin
  // ------------------------------------------------------------------ roads, building outlines and address dots (B3, --hail-addresses builds)

  /** The B3 layers on the Map page (data/map.json "hail": roads, buildings and addresses, plus "draw" and "attribution".
      The sentences this script fills are in hail.buildings.templates and hail.addresses.templates; the form and the legend
      lines are printed by map.html from the page's b3 context, built by build.py b3_words). Python writes every word, number and
      rule. The browser does these steps and no others:
        - the shard names a view needs: each 0.1-degree tile the view touches (the grid's arithmetic, from map.json), its
          split leaves named from the split map, and the leaves' bounds from their quadtree digits (0 NW, 1 NE, 2 SW, 3 SE);
        - one fetch per shard file, kept in memory with a size cap (data.hail.draw.cache_bytes): the least recently used
          shard goes first, and a shard in view never does. A failed fetch is logged (window.hailMapTest) and the map
          draws without it, so nothing throws;
        - one canvas in the "hail" pane, drawn in this order: the roads by class (the width and the zoom of each class come
          from map.json), the building outlines (a light fill and a hairline from buildings.zoom.fills, a heavier line from
          buildings.zoom.emphasis), the dots (one per outline at its dot point, and one per unmatched address, from
          buildings.zoom.dots), the count bubbles (from buildings.zoom.counts to the dots, from hail/counts.json), and the
          street names last (from roads.zoom.names_from). A name is drawn once per tile on the longest piece with that name;
          the piece must be longer than the name plus the fit allowance, the names keep clear of each other (a grid of
          data.hail.draw.labels.grid_px) and of the dots unless labels.avoid_dots is false, their angles are quantised, and
          at most labels.per_view are drawn;
        - the tap: the nearest dot within the tap radius opens the hail sheet for that dot's point, with its address lines
          above the cell's history (the template #address-sec in map.html). A tap that no dot takes goes on to the map as
          before. The sheet of a dot off the hail grid, or in a tile with no hail file, gets the grid sentence (D23);
        - the search (#address-form, #address-input, #address-results, #address-status): what is typed is read here and
          never leaves the browser. The typed words are lower-cased, punctuation and "#" go, abbreviations are spelled out
          (addresses.search_words), a trailing state is dropped, the town is the longest trailing run that the city index
          (hail/a/idx/cities.json) names (else the site town nearest the map's centre), a leading number is the address
          number, and the core name is the first word that is not a direction or a street type. The key file is the
          core name's first character, or its first two when the city's index has only that key (addresses.file_key). One
          letter file is fetched; the rows whose street holds every typed word are listed, the exact number first, then the
          nearest numbers, up to addresses.limits.result_cap. Choosing a row zooms to its point (buildings.zoom.emphasis)
          and opens its sheet. Text the index cannot give shows its module's unavailable sentence, never "no match".
      The colours and the stroke widths of the pictures' own parts (the hairlines, the dot ring, the name's halo and size, the
      count bubble's padding) come from map.css custom properties (--hail-...), read once and again when the colour scheme
      changes. Nothing else is written here: no sentence, unit, radius, zoom, cap or colour (tests/test_site.py reads this
      file for them). The numbers that are not data are a drawing speed and not a rule (B3_BATCH, the paths per fill or
      stroke call), the layer order of the map's panes (B3_PANE, as at the pane list in boot) and the 50-entry log of draw
      times kept for window.hailMapTest.
      window.hailMapTest is a test-only hook: tools/smoke_map.py reads the shard counts, the dots, the labels, the fetch log,
      the failures and the draw times from it. Nothing else reads it. */
  var B3 = null;                              // the layers' state, made by b3Start when data.hail holds one of their blocks
  var B3_FORMAT = { roads: "hail-roads-v1", buildings: "hail-buildings-v1", addresses: "hail-addresses-v1",
    letter: "hail-address-idx-v1", cities: "hail-address-cities-v1", counts: "hail-building-counts-v1" };
  var B3_PANE = 420;                          // the layers' pane: above the weather pictures (410), below the warning fills (430)
  var B3_BATCH = 200;                         // paths per fill or stroke call (a drawing speed, not a display rule)
  var B3_TAU = 2 * Math.PI;
  var B3_DEG = Math.PI / 180;
  var B3_NUMBER = /^\d+[a-z]?$|^\d+\/\d+$/;       // an address number as typed: 401, 401A or 1/2 (27th is a street word)

  /** The zoom rules of the four blocks in one place, read from data/map.json (roads.zoom, roads.classes, buildings.zoom and
      addresses.zoom). The dots of the addresses are the dots when there are no outlines, and the zoom a chosen search row
      goes to is the addresses' own (D47), so an address-only build (no streets, no outlines) keeps both rules. */
  function b3Zoom(h) {
    var r = (h.roads && h.roads.zoom) || {}, b = (h.buildings && h.buildings.zoom) || {}, a = (h.addresses && h.addresses.zoom) || {};
    var classes = (h.roads && h.roads.classes) || {};
    var from = Infinity;
    Object.keys(classes).forEach(function (k) { from = Math.min(from, classes[k].min_zoom); });
    var counts = [].concat(b.counts || []);
    var z = { roads: from, arterials: r.arterials_from, local: r.local_from, names: r.names_from,
      counts: counts.length ? counts[0] : Infinity, dots: b.dots || a.dots, fills: b.fills, emphasis: b.emphasis, choose: a.choose };
    z.top = Math.max(z.emphasis || 0, z.names || 0, z.local || 0, z.dots || 0, z.choose || 0);   // the highest zoom any layer asks for
    return z;
  }

  /** The top zoom the B3 layers need (0 without them): the map's maximum zoom is raised to it (createMap, setBase). */
  function b3TopZoom() {
    var h = hailData();
    return h && (h.roads || h.buildings || h.addresses) ? b3Zoom(h).top : 0;
  }

  /** The B3 state: the blocks that loaded (a block that did not load draws nothing, and its legend line says so), the grid,
      the tile sets, the cache, the pane and the canvas. Nothing is fetched here. */
  function b3Start() {
    var h = hailData();
    if (!h || !h.grid || !(h.roads || h.buildings || h.addresses)) return;
    var live = function (block) { return !!block && (block.state === "loaded" || block.state === "sample"); };
    var set = function (list) { var s = {}; (list || []).forEach(function (t) { s[t] = true; }); return s; };
    var mode = (h.addresses && h.addresses.text) || (h.buildings && h.buildings.text) || "on";
    B3 = {
      h: h, grid: h.grid, draw: h.draw || {}, zoom: b3Zoom(h),
      root: (app.getAttribute("data-map") || "").replace(/data\/map\.json.*$/, ""),
      roads: live(h.roads) ? h.roads : null, bld: live(h.buildings) ? h.buildings : null, adr: live(h.addresses) ? h.addresses : null,
      textOn: mode !== "off",                 // --address-text off (D35): no address text, no search
      tiles: { roads: set(h.roads && h.roads.tiles), bld: set(h.buildings && h.buildings.tiles), adr: set(h.addresses && h.addresses.tiles) },
      cache: new Map(), bytes: 0, cap: Number(((h.draw || {}).cache_bytes)) || 0, tick: 0, pinned: {},
      fetches: [], failures: [], failed: {}, gen: 0, ms: [], stats: {}, hits: [], queued: false, down: null, cityNames: null,
      dpr: window.devicePixelRatio || 1, col: {}, sz: {}, nameFont: "", countFont: ""
    };
    B3.bw = (B3.bld && B3.bld.templates) || {};
    B3.aw = (B3.adr && B3.adr.templates) || B3.bw;
    var tap = (B3.bld && B3.bld.tap_radius_px) || (B3.adr && B3.adr.limits && B3.adr.limits.tap_radius_px) || 0;
    B3.tap = tap;
    pane("hail", B3_PANE, false);
    B3.canvas = document.createElement("canvas");
    B3.canvas.className = "hail-canvas";
    B3.canvas.setAttribute("aria-hidden", "true");
    map.getPane("hail").appendChild(B3.canvas);
    B3.ctx = B3.canvas.getContext("2d");
    b3Tokens();
    ["moveend", "zoomend"].forEach(function (ev) { map.on(ev, function () { if (B3) B3.gen++; }); });   // a move asks again for a file that failed (B3.failed)
    ["moveend", "zoomend", "resize", "viewreset"].forEach(function (ev) { map.on(ev, b3Queue); });
    if (window.matchMedia) {
      var scheme = window.matchMedia("(prefers-color-scheme: dark)");
      var again = function () { b3Tokens(); b3Queue(); };
      if (scheme.addEventListener) scheme.addEventListener("change", again); else if (scheme.addListener) scheme.addListener(again);
    }
    el.canvas.addEventListener("pointerdown", function (e) { if (B3) B3.down = { x: e.clientX, y: e.clientY }; }, true);
    el.canvas.addEventListener("click", b3Tap, true);
    b3WireSearch();
    b3WireFind();
    window.hailMapTest = {                    // test-only (tools/smoke_map.py)
      shards: function () { var n = {}; B3.cache.forEach(function (e) { if (e.state === "ready") n[e.kind] = (n[e.kind] || 0) + 1; }); return n; },
      dots: function () { return { buildings: B3.stats.buildings || 0, addresses: B3.stats.addresses || 0 }; },
      labels: function () { return B3.stats.labels || 0; },
      counts: function () { return B3.stats.counts || 0; },
      lines: function () { return B3.stats.lines || 0; },
      fetches: function () { return B3.fetches.slice(); },
      failures: function () { return B3.failures.slice(); },
      draws: function () { return B3.ms.slice(); },
      bytes: function () { return B3.bytes; },
      cached: function () { return B3.cache.size; },
      reset: function () { B3.fetches = []; B3.failures = []; B3.ms = []; },
      view: function (lat, lon, zoom) { state.userMoved = true; map.setView([lat, lon], zoom, { animate: false }); return map.getZoom(); },
      pan: function (dx, dy) { map.panBy([dx, dy], { animate: false }); },
      redraws: function (n) { var out = []; for (var i = 0; i < n; i++) { map.panBy([i % 2 ? -1 : 1, 0], { animate: false }); b3Draw(); out.push(B3.ms[B3.ms.length - 1]); } return out; },
      zoom: function () { return map.getZoom(); },
      hits: function () { return B3.hits.map(function (h) { return [Math.round(h.x), Math.round(h.y), h.kind, h.kind === "b" ? (h.ref.l || []).length : 1]; }); },
      state: function () { return { roads: !!B3.roads, bld: !!B3.bld, adr: !!B3.adr, zoom: B3.zoom, tiles: Object.keys(B3.tiles.roads).length,
        bldTiles: Object.keys(B3.tiles.bld).length, adrTiles: Object.keys(B3.tiles.adr).length, root: B3.root, z: map.getZoom(), cap: B3.cap,
        textOn: B3.textOn, searchOn: !!B3.searchOn, tap: B3.tap, minZoom: map.getMinZoom(), maxZoom: map.getMaxZoom() }; }
    };
    b3Queue();
  }

  /** Colours and sizes from map.css (the --hail-... properties and the page's font), read once, and again on a colour scheme change. */
  function b3Tokens() {
    if (!B3) return;
    var cs = getComputedStyle(document.documentElement), get = function (n) { return cs.getPropertyValue(n).trim(); };
    var px = function (n) { return parseFloat(get(n)) || 0; };
    B3.col = { road: get("--hail-road"), major: get("--hail-road-major"), bldg: get("--hail-bldg"), bldgLine: get("--hail-bldg-line"),
      dot: get("--hail-dot"), dotAddress: get("--hail-dot-address") || get("--hail-dot"), dotRing: get("--hail-dot-ring"),
      name: get("--hail-name"), halo: get("--hail-name-halo"),
      countBg: get("--bubble"), countInk: get("--bubble-text") };
    B3.sz = { hair: px("--hail-hairline"), emph: px("--hail-emphasis"), ring: px("--hail-dot-ring-w"), halo: px("--hail-halo"),
      nameSize: px("--hail-name-size"), countSize: px("--hail-count-size"), countPad: px("--hail-count-pad") };
    B3.nameFont = get("--hail-name-weight") + " " + B3.sz.nameSize + "px " + get("--font");
    B3.countFont = get("--hail-count-weight") + " " + B3.sz.countSize + "px " + get("--font");
  }

  /** The source lines of the layers built (data/map.json "hail".attribution, D29) go in the map's attribution line, bottom
      right, so they are on the first screen at phone width too. Leaflet's prefix is left out; a line is escaped like the rest.
      The line is lifted above the bottom band (b3Lift). The band changes height with its contents (a source line, a layer,
      a turn, the toast) and the screen, so it is measured again when it changes, and so is the line's own height. */
  function b3Credits() {
    if (!B3 || !map || B3.credits || !(B3.h.attribution || []).length) return;
    B3.credits = true;
    var ctl = L.control.attribution({ prefix: false, position: "bottomright" }).addTo(map);
    B3.h.attribution.forEach(function (line) { ctl.addAttribution(esc(line)); });
    B3.credit = ctl;
    if (window.ResizeObserver) {
      var band = new ResizeObserver(b3Lift);
      band.observe(el.bottom);
      band.observe(el.canvas);
      new ResizeObserver(refitForBanner).observe(ctl.getContainer());   // more text, more lines: the room the fit keeps (noteRoom)
    } else window.addEventListener("resize", b3Lift);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(b3Lift);   // the band is measured in its own fonts
    b3Lift();
  }

  /** The height of the bottom band in px, from its top to the bottom of the map: the note, the toast, the chip and the timeline.
      Zero when the band is not drawn (print). The source lines sit above it and the count bubbles keep clear of it (b3DrawCounts). */
  function b3LiftPx() {
    if (!el.bottom || !el.bottom.getClientRects().length) return 0;
    return Math.max(0, el.canvas.getBoundingClientRect().bottom - el.bottom.getBoundingClientRect().top);
  }

  /** The source lines sit just above the bottom band, with the band's own 8 px gap (b3LiftPx, measured). */
  function b3Lift() {
    if (!B3 || !B3.credit) return;
    var h = b3LiftPx();
    B3.credit.getContainer().style.setProperty("--credit-lift", (h ? Math.ceil(h + 8) : 0) + "px");
  }

  /** Ask for a redraw on the next frame (several events in one frame make one draw). */
  function b3Queue() {
    if (!B3 || B3.queued) return;
    B3.queued = true;
    var later = window.requestAnimationFrame || function (f) { setTimeout(f, 0); };
    later(function () { if (B3) { B3.queued = false; b3Draw(); } });
  }

  // ---- tiles, leaves and bounds (the grid's arithmetic: map.json grid, the same rules as hailCell and hailTileName)

  /** The bounds [west, south, east, north] of a 0.1-degree tile (row r, column c) from the grid in map.json. */
  function b3TileBox(g, r, c) {
    var cell = g.cell_deg, td = cell * g.tile_cells;
    var north = g.row0_lat + cell / 2 - r * td, west = g.col0_lon - cell / 2 + c * td;
    return [west, north - td, west + td, north];
  }

  /** The tile's file name, "r0079_c0199" (the name hail.tile_name writes). */
  function b3TileName(r, c) { return "r" + pad4(r) + "_c" + pad4(c); }

  /** One quadtree step: the quarter of a box named by one digit (0 NW, 1 NE, 2 SW, 3 SE; the midlines are the box's own). */
  function b3Quarter(b, d) {
    var mx = (b[0] + b[2]) / 2, my = (b[1] + b[3]) / 2;
    if (d === "0") return [b[0], my, mx, b[3]];
    if (d === "1") return [mx, my, b[2], b[3]];
    if (d === "2") return [b[0], b[1], mx, my];
    return [mx, b[1], b[2], my];
  }

  /** The bounds of a split leaf from its name: the tile's box, then one quarter per digit after the tile's own eleven characters. */
  function b3NameBox(g, name) {
    var box = b3TileBox(g, Number(name.slice(1, 5)), Number(name.slice(7, 11)));
    for (var i = 11; i < name.length; i++) box = b3Quarter(box, name.charAt(i));
    return box;
  }

  /** The tiles a view touches, as {r, c, name} (the rows and columns are the grid's tile indexes). */
  function b3TilesIn(g, vb) {
    var td = g.cell_deg * g.tile_cells, top = g.row0_lat + g.cell_deg / 2, left = g.col0_lon - g.cell_deg / 2;
    var r0 = Math.max(0, Math.floor((top - vb[3]) / td)), r1 = Math.floor((top - vb[1]) / td);
    var c0 = Math.max(0, Math.floor((vb[0] - left) / td)), c1 = Math.floor((vb[2] - left) / td);
    var out = [];
    for (var r = r0; r <= r1; r++) for (var c = c0; c <= c1; c++) out.push({ r: r, c: c, name: b3TileName(r, c) });
    return out;
  }

  /** The shard leaves of one tile for a block: [{name, box}]. A tile with no split is one shard, named as the tile. The
      buildings' split map gives [name, box] pairs; the roads' and the addresses' give names, and their boxes come from the names. */
  function b3Leaves(block, t, boxed) {
    var list = block.split && block.split[t.name];
    if (!list) return [{ name: t.name, box: b3TileBox(B3.grid, t.r, t.c) }];
    return list.map(function (x) { return boxed ? { name: x[0], box: x[1] } : { name: x, box: b3NameBox(B3.grid, x) }; });
  }

  /** Whether two boxes [w, s, e, n] (degrees) overlap. */
  function b3Overlaps(a, b) { return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]; }

  // ---- projection: Leaflet's Web Mercator in world pixels (256 px tiles, 2^zoom of them), with one offset per draw

  /** The world pixels [x, y] of a point at a scale (256 times 2^zoom), written into out. */
  function b3Proj(lat, lon, scale, out) {
    var s = Math.sin(lat * B3_DEG);
    out[0] = (lon + 180) / 360 * scale;
    out[1] = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * scale;
    return out;
  }

  /** A line's vertices in world pixels at this zoom, and its length; cached on the row until the zoom changes. */
  function b3Row(row, scale, zk) {
    if (row.zk !== zk) {
      var n = row.xy.length / 2, out = new Float64Array(n * 2), tmp = [0, 0], len = 0;
      for (var i = 0; i < n; i++) {
        b3Proj(row.xy[2 * i + 1], row.xy[2 * i], scale, tmp);
        out[2 * i] = tmp[0]; out[2 * i + 1] = tmp[1];
        if (i) len += Math.hypot(out[2 * i] - out[2 * i - 2], out[2 * i + 1] - out[2 * i - 1]);
      }
      row.wz = out; row.len = len; row.zk = zk;
    }
    return row.wz;
  }

  /** A building's rings in world pixels at this zoom, cached on the item until the zoom changes. */
  function b3Item(item, scale, zk) {
    if (item.zk !== zk) {
      var tmp = [0, 0];
      item.wz = item.rings.map(function (ring) {
        var n = ring.length / 2, out = new Float64Array(n * 2);
        for (var i = 0; i < n; i++) { b3Proj(ring[2 * i + 1], ring[2 * i], scale, tmp); out[2 * i] = tmp[0]; out[2 * i + 1] = tmp[1]; }
        return out;
      });
      item.zk = zk;
    }
    return item.wz;
  }

  // ---- shard files: one fetch per file, the cache with its size cap, and the shape each kind is read as

  /** The file's data in the shape the drawing reads it. A file that is not in its format is a failed load (the message says so). */
  function b3Shape(kind, doc) {
    if (!doc || doc.f !== B3_FORMAT[kind]) throw new Error("format");
    if (kind === "roads") return b3ShapeRoads(doc);
    if (kind === "buildings") return b3ShapeBuildings(doc);
    if (kind === "counts") return { tiles: doc.tiles || {} };
    if (kind === "cities") return { cities: doc.cities || {} };
    if (!Array.isArray(doc.a)) throw new Error("rows");
    return { rows: doc.a };                    // addresses (the unmatched dots) and letter files: the rows as the file writes them
  }

  /** A roads shard: the lines as typed arrays, their boxes and their classes (byClass), with the name table. */
  function b3ShapeRoads(doc) {
    var rows = doc.r || [], out = [], byClass = {};
    for (var i = 0; i < rows.length; i++) {
      var pts = rows[i][2], xy = new Float64Array(pts.length * 2), bb = [Infinity, Infinity, -Infinity, -Infinity];
      for (var j = 0; j < pts.length; j++) {
        xy[2 * j] = pts[j][0]; xy[2 * j + 1] = pts[j][1];
        bb[0] = Math.min(bb[0], pts[j][0]); bb[1] = Math.min(bb[1], pts[j][1]);
        bb[2] = Math.max(bb[2], pts[j][0]); bb[3] = Math.max(bb[3], pts[j][1]);
      }
      var row = { c: rows[i][0], n: rows[i][1], xy: xy, bb: bb, zk: null, wz: null, len: 0 };
      out.push(row);
      (byClass[row.c] = byClass[row.c] || []).push(row);
    }
    return { rows: out, byClass: byClass, names: doc.names || [], chains: b3Chains(out) };
  }

  /** The pieces of a shard's names: rows of one name that share an end point are one piece (the shard cuts a street at each
      crossing, so a block is one row). Union-find over the end points; a row with no name is in no piece. */
  function b3Chains(rows) {
    var par = rows.map(function (r, i) { return i; }), seen = {};
    var find = function (i) { while (par[i] !== i) { par[i] = par[par[i]]; i = par[i]; } return i; };
    rows.forEach(function (row, i) {
      if (row.n < 0) return;
      [0, row.xy.length / 2 - 1].forEach(function (j) {
        var k = row.n + "|" + row.xy[2 * j].toFixed(5) + "|" + row.xy[2 * j + 1].toFixed(5);
        if (seen[k] !== undefined) par[find(i)] = find(seen[k]); else seen[k] = i;
      });
    });
    var pieces = {};
    rows.forEach(function (row, i) {
      if (row.n < 0) return;
      var root = find(i), piece = pieces[root] || (pieces[root] = { n: row.n, rows: [], bb: [Infinity, Infinity, -Infinity, -Infinity], zk: null, len: 0 });
      piece.rows.push(row);
      piece.bb = [Math.min(piece.bb[0], row.bb[0]), Math.min(piece.bb[1], row.bb[1]), Math.max(piece.bb[2], row.bb[2]), Math.max(piece.bb[3], row.bb[3])];
    });
    return Object.keys(pieces).map(function (k) { return pieces[k]; });
  }

  /** A buildings shard: one item per outline (its dot point, its rings in typed arrays, its box, its address lines and the
      shard's common city and zip). */
  function b3ShapeBuildings(doc) {
    var out = [];
    (doc.a || []).forEach(function (e) {
      var bb = [Infinity, Infinity, -Infinity, -Infinity];
      var rings = (e.g || []).map(function (ring) {
        var xy = new Float64Array(ring.length * 2);
        ring.forEach(function (p, j) {
          xy[2 * j] = p[0]; xy[2 * j + 1] = p[1];
          bb[0] = Math.min(bb[0], p[0]); bb[1] = Math.min(bb[1], p[1]);
          bb[2] = Math.max(bb[2], p[0]); bb[3] = Math.max(bb[3], p[1]);
        });
        return xy;
      });
      out.push({ p: e.p, rings: rings, bb: bb, l: e.l || [], z: e.z || null, c: doc.c || null, zk: null, wz: null });
    });
    return { items: out };
  }

  /** Fetch one file once: a promise of its shape. The cache keeps the entry (loading or ready); a failed file leaves the cache,
      so the next draw asks again, and its failure is logged. A draw that asked for it redraws when it arrives. */
  function b3Load(kind, url, keep, redraw) {
    var B = B3, e = B.cache.get(url);
    if (e) {
      if (e.state === "ready") { B.cache.delete(url); B.cache.set(url, e); }   // least recently used goes first
      return e.promise;
    }
    e = { kind: kind, state: "loading", data: null, bytes: 0, keep: !!keep, promise: null };
    B.cache.set(url, e);
    B.fetches.push(url);
    e.promise = fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.text();
    }).then(function (text) {
      var shaped = b3Shape(kind, JSON.parse(text));     // a file that is not JSON, or not in its format, fails here
      e.data = shaped;
      e.bytes = text.length;
      e.state = "ready";
      B.bytes += e.bytes;
      b3Evict();
      return shaped;
    }).then(null, function (err) {
      if (B.cache.get(url) === e) B.cache.delete(url);
      B.failed[url] = B.gen;
      B.failures.push({ url: url, kind: kind, reason: err && err.message ? err.message : "load" });
      throw err;
    });
    e.promise.then(function () { if (redraw) b3Queue(); }, function () {});   // a failure is logged above, and never thrown
    return e.promise;
  }

  /** Drop the least recently used files until the cache is under its cap. Files in view (B3.pinned), files still loading and
      the files the search keeps are never dropped. */
  function b3Evict() {
    var B = B3, keys = [];
    if (B.bytes <= B.cap) return;
    B.cache.forEach(function (e, url) { keys.push(url); });
    for (var i = 0; i < keys.length && B.bytes > B.cap; i++) {
      var e = B.cache.get(keys[i]);
      if (!e || e.state !== "ready" || e.keep || B.pinned[keys[i]]) continue;
      B.cache.delete(keys[i]);
      B.bytes -= e.bytes;
    }
  }

  // ---- the draw

  /** Draw the layers for the view: which files it needs, the fetches it starts, then the pictures from what is loaded. */
  function b3Draw() {
    var B = B3;
    if (!B || !map) return;
    var t0 = performance.now(), size = map.getSize(), z = map.getZoom(), Z = B.zoom, cv = B.canvas, ctx = B.ctx, dpr = B.dpr;
    var w = Math.round(size.x * dpr), hgt = Math.round(size.y * dpr);
    if (cv.width !== w || cv.height !== hgt) { cv.width = w; cv.height = hgt; }
    cv.style.width = size.x + "px"; cv.style.height = size.y + "px";
    L.DomUtil.setPosition(cv, map.containerPointToLayerPoint([0, 0]));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.x, size.y);
    B.hits = []; B.stats = { buildings: 0, addresses: 0, labels: 0, counts: 0, lines: 0 };
    var bounds = map.getBounds(), vb = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];
    var wantRoads = !!B.roads && z >= Z.roads, wantDots = !!B.bld && z >= Z.dots, wantAddr = !!B.adr && z >= Z.dots;
    var wantCounts = !!B.bld && z >= Z.counts && z < Z.dots;
    var tiles = (wantRoads || wantDots || wantAddr || wantCounts) ? b3TilesIn(B.grid, vb) : [];
    // An outline is drawn from the leaf that holds its dot point, but its vertices can reach past that leaf by the file's
    // overhang (buildings.overhang_deg, about 200 m). The outlines are drawn from the fills zoom, so from there the building
    // leaves are chosen from the view grown by the overhang: a sliver at the view's edge, or at a tile or split edge, is fetched
    // too. The dots of zooms 15 and 16 lie inside their leaves, so below the fills zoom the view stays as it is (no extra file).
    var grow = wantDots && z >= Z.fills && B.bld ? (B.bld.overhang_deg || 0) : 0;
    var bvb = grow ? [vb[0] - grow, vb[1] - grow, vb[2] + grow, vb[3] + grow] : vb;
    var btiles = grow ? b3TilesIn(B.grid, bvb) : tiles;
    var pinned = {}, roadEnts = [], bldEnts = [], adrEnts = [], countsDoc = null;
    var want = function (kind, block, t, boxed, out, view) {
      b3Leaves(block, t, boxed).forEach(function (leaf) {
        if (!b3Overlaps(leaf.box, view)) return;
        var url = B.root + block.shard.replace("{name}", leaf.name);
        pinned[url] = true;
        var e = B.cache.get(url);
        if (!e) { if (B.failed[url] !== B.gen) b3Load(kind, url, false, true); }
        else if (e.state === "ready") { b3Load(kind, url, false, false); out.push({ e: e, tile: t.name, box: leaf.box }); }
      });
    };
    tiles.forEach(function (t) {
      if (wantRoads && B.tiles.roads[t.name]) want("roads", B.roads, t, false, roadEnts, vb);
      if (wantAddr && B.tiles.adr[t.name]) want("addresses", B.adr, t, false, adrEnts, vb);
    });
    btiles.forEach(function (t) {
      if (wantDots && B.tiles.bld[t.name]) want("buildings", B.bld, t, true, bldEnts, bvb);
    });
    if (wantCounts && B.bld.counts_file) {
      var curl = B.root + B.bld.counts_file;
      pinned[curl] = true;
      var ce = B.cache.get(curl);
      if (!ce) b3Load("counts", curl, true, true); else if (ce.state === "ready") countsDoc = ce.data;
    }
    B.pinned = pinned;
    var scale = 256 * Math.pow(2, z), tmp = [0, 0];
    var c = map.getCenter(), wc = b3Proj(c.lat, c.lng, scale, [0, 0]), pc = map.latLngToContainerPoint(c);
    var ox = pc.x - wc[0], oy = pc.y - wc[1];                       // world pixels to container pixels, for this draw
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    if (wantRoads) b3DrawRoads(roadEnts, vb, z, scale, ox, oy);
    if (wantDots && z >= Z.fills) b3DrawBuildings(bldEnts, vb, z, scale, ox, oy);
    var rad = b3Radius(z);
    if ((wantDots || wantAddr) && rad > 0) b3DrawDots(z, bldEnts, adrEnts, vb, ox, oy, rad, scale, size, tmp);
    if (wantCounts && countsDoc) b3DrawCounts(tiles, countsDoc, ox, oy, scale, size);
    if (wantRoads && z >= Z.names && B.draw.labels) B.stats.labels = b3DrawNames(roadEnts, vb, z, scale, ox, oy, size);
    var ms = performance.now() - t0;
    B.ms.push(ms);
    if (B.ms.length > 50) B.ms.shift();
    b3Evict();
  }

  /** The roads by class, least prominent first, so the arterials draw on top. A class is drawn from its own zoom (map.json). */
  function b3DrawRoads(ents, vb, z, scale, ox, oy) {
    var B = B3, ctx = B.ctx, rd = B.roads, order = rd.class_order.split("").reverse();
    order.forEach(function (letter) {
      var cl = rd.classes[letter];
      if (!cl || z < cl.min_zoom) return;
      ctx.strokeStyle = cl.min_zoom <= B.zoom.arterials ? B.col.major : B.col.road;
      ctx.lineWidth = cl.width;
      ctx.beginPath();
      var k = 0;
      ents.forEach(function (ent) {
        (ent.e.data.byClass[letter] || []).forEach(function (row) {
          if (!b3Overlaps(row.bb, vb)) return;
          var wz = b3Row(row, scale, z), n = wz.length / 2;
          ctx.moveTo(wz[0] + ox, wz[1] + oy);
          for (var i = 1; i < n; i++) ctx.lineTo(wz[2 * i] + ox, wz[2 * i + 1] + oy);
          B.stats.lines++;
          if (++k % B3_BATCH === 0) { ctx.stroke(); ctx.beginPath(); }
        });
      });
      ctx.stroke();
    });
  }

  /** The outlines: a light fill and a hairline from the fills zoom, and the heavier line from the emphasis zoom. */
  function b3DrawBuildings(ents, vb, z, scale, ox, oy) {
    var B = B3, ctx = B.ctx, Z = B.zoom;
    if (z < Z.fills) return;
    var pass = function (fill, width) {
      ctx.lineWidth = width;
      ctx.beginPath();
      var k = 0;
      ents.forEach(function (ent) {
        ent.e.data.items.forEach(function (it) {
          if (!b3Overlaps(it.bb, vb)) return;
          b3Item(it, scale, z).forEach(function (wz) {
            var n = wz.length / 2;
            ctx.moveTo(wz[0] + ox, wz[1] + oy);
            for (var i = 1; i < n; i++) ctx.lineTo(wz[2 * i] + ox, wz[2 * i + 1] + oy);
            ctx.closePath();
          });
          if (++k % B3_BATCH === 0) { if (fill) ctx.fill("evenodd"); ctx.stroke(); ctx.beginPath(); }
        });
      });
      if (fill) ctx.fill("evenodd");
      ctx.stroke();
    };
    ctx.fillStyle = B.col.bldg;
    ctx.strokeStyle = B.col.bldgLine;
    pass(true, B.sz.hair);
    if (z >= Z.emphasis) pass(false, B.sz.emph);
  }

  /** The dot radius at a zoom: the buildings block's rule (dot_radius_px), or the addresses block's when there are no outlines. */
  function b3Radius(z) {
    var d = (B3.bld && B3.bld.dot_radius_px) || (B3.adr && B3.adr.dot_radius_px);
    if (!d) return 0;
    return Math.min(d.max, d.at_zoom + d.per_zoom * (z - d.zoom));
  }

  /** The dots: one per outline at its dot point, and one per unmatched address. Each drawn dot is kept for the tap (B3.hits).
      The two kinds take their own colours (--hail-dot for an outline, --hail-dot-address for an address). A shard inside the
      view is drawn from its own path (b3DotPath, built once per zoom and radius: the arcs were most of a draw's time); an edge
      shard is drawn from the dots in view. The dots in view are found one by one, for the taps and for the names that keep off them. */
  function b3DrawDots(z, bldEnts, adrEnts, vb, ox, oy, r, scale, size, tmp) {
    var B = B3, ctx = B.ctx, m = r + 1;
    B.dotR = r;
    if (z < B3.zoom.dots) return;
    ctx.strokeStyle = B.col.dotRing;
    ctx.lineWidth = B.sz.ring;
    // every shard of a kind goes into one path (one fill and one stroke a kind, not one for each shard)
    var shard = function (kind, ent, rows, ll, all) {
      var c = b3DotCache(ent, kind, rows, ll, z, r, scale);
      // a shard inside the view has every one of its dots in view: its cached path is added, moved to its corner. An edge
      // shard adds the dots in view only (a whole edge path would fill the dots that lie off the screen)
      var b = ent.box, whole = b[0] >= vb[0] && b[2] <= vb[2] && b[1] >= vb[1] && b[3] <= vb[3];
      if (whole) all.addPath(b3DotPath(c, r), new DOMMatrix([1, 0, 0, 1, c.origin[0] + ox, c.origin[1] + oy]));
      for (var i = 0; i < rows.length; i++) {
        var p = ll(rows[i]), lon = p[0], lat = p[1];
        if (lon < vb[0] || lon > vb[2] || lat < vb[1] || lat > vb[3]) continue;
        var x = c.xy[2 * i] + ox, y = c.xy[2 * i + 1] + oy;
        if (x < -m || y < -m || x > size.x + m || y > size.y + m) continue;
        B.hits.push({ x: x, y: y, kind: kind, lon: lon, lat: lat, ref: rows[i] });
        B.stats[kind === "b" ? "buildings" : "addresses"]++;
        if (!whole) { all.moveTo(x + r, y); all.arc(x, y, r, 0, B3_TAU); }
      }
    };
    [["b", bldEnts, function (ent) { return ent.e.data.items; }, function (it) { return it.p; }, B.col.dot],
      ["a", adrEnts, function (ent) { return ent.e.data.rows; }, function (row) { return row; }, B.col.dotAddress]].forEach(function (k) {
      var all = new Path2D();
      k[1].forEach(function (ent) { shard(k[0], ent, k[2](ent), k[3], all); });
      ctx.fillStyle = k[4];
      ctx.fill(all);
      ctx.stroke(all);
    });
  }

  /** A shard's dots of one kind at a zoom and radius: the world pixels of each dot (xy) and the world pixels of the north-west
      corner of the shard's box (origin). Built once per zoom and radius, kept on the shard's data. The corner keeps the
      canvas's numbers small (a world pixel at zoom 15 is about 8 million). b3DotPath adds the discs when a shard is wholly in view. */
  function b3DotCache(ent, kind, rows, ll, z, r, scale) {
    var d = ent.e.data, key = z + "|" + r;
    d.dots = d.dots || {};
    var c = d.dots[kind];
    if (c && c.key === key) return c;
    var o = b3Proj(ent.box[3], ent.box[0], scale, [0, 0]), tmp = [0, 0], xy = new Float64Array(rows.length * 2);
    for (var i = 0; i < rows.length; i++) {
      var p = ll(rows[i]);
      b3Proj(p[1], p[0], scale, tmp);
      xy[2 * i] = tmp[0]; xy[2 * i + 1] = tmp[1];
    }
    c = d.dots[kind] = { key: key, origin: o, xy: xy, path: null };
    return c;
  }

  /** The discs of a shard's dots as one Path2D, in pixels from the shard's corner (b3DotCache's origin), built on first use. */
  function b3DotPath(c, r) {
    if (c.path) return c.path;
    var path = new Path2D(), xy = c.xy, o = c.origin;
    for (var i = 0; i < xy.length; i += 2) {
      var lx = xy[i] - o[0], ly = xy[i + 1] - o[1];
      path.moveTo(lx + r, ly);
      path.arc(lx, ly, r, 0, B3_TAU);
    }
    c.path = path;
    return path;
  }

  /** One rounded bubble per tile: the count of outlines in it ("1,240 buildings"; the words come from buildings.templates).
      The bubble is centred in the part of its tile that shows: the tile's corners are clipped to the map below the banners and
      the search card and above the bottom band (b3LiftPx), so a bubble is never drawn under a panel, under the band or off the
      screen. A tile with no visible part gets none. */
  function b3DrawCounts(tiles, doc, ox, oy, scale, size) {
    var B = B3, ctx = B.ctx, pad = B.sz.countPad, p0 = [0, 0], p1 = [0, 0];
    var mapTop = el.canvas.getBoundingClientRect().top, top = 0, find = document.getElementById("find");
    [el.banners, find].forEach(function (e) {
      if (e && e.getClientRects().length) top = Math.max(top, e.getBoundingClientRect().bottom - mapTop);
    });
    var bottom = size.y - b3LiftPx();
    ctx.font = B.countFont;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    tiles.forEach(function (t) {
      var n = doc.tiles[t.name];
      if (!n) return;
      var box = b3TileBox(B.grid, t.r, t.c);
      b3Proj(box[3], box[0], scale, p0);                                    // the north-west corner of the tile, in world pixels
      b3Proj(box[1], box[2], scale, p1);                                    // its south-east corner
      var x0 = Math.max(0, Math.min(p0[0], p1[0]) + ox), x1 = Math.min(size.x, Math.max(p0[0], p1[0]) + ox);
      var y0 = Math.max(top, Math.min(p0[1], p1[1]) + oy), y1 = Math.min(bottom, Math.max(p0[1], p1[1]) + oy);
      if (x1 <= x0 || y1 <= y0) return;
      var x = (x0 + x1) / 2, y = (y0 + y1) / 2;
      var text = n === 1 ? B.bw.count_one : B3.bw.count_bubble.replace("{n}", n.toLocaleString("en-US"));
      var w = ctx.measureText(text).width + 2 * pad, h = B.sz.countSize + 2 * pad;
      ctx.fillStyle = B.col.countBg;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x - w / 2, y - h / 2, w, h, h / 2); else ctx.rect(x - w / 2, y - h / 2, w, h);
      ctx.fill();
      ctx.fillStyle = B.col.countInk;
      ctx.fillText(text, x, y);
      B.stats.counts++;
    });
  }

  /** The point at a fraction of a line's length, in container pixels, and the direction of the segment it falls on. */
  function b3AlongRow(wz, total, f, ox, oy) {
    var n = wz.length / 2, target = total * f, acc = 0;
    for (var i = 1; i < n; i++) {
      var dx = wz[2 * i] - wz[2 * i - 2], dy = wz[2 * i + 1] - wz[2 * i - 1], seg = Math.hypot(dx, dy);
      if (acc + seg >= target || i === n - 1) {
        var t = seg ? Math.min(1, Math.max(0, (target - acc) / seg)) : 0;
        return { x: wz[2 * i - 2] + dx * t + ox, y: wz[2 * i - 1] + dy * t + oy, dx: dx, dy: dy };
      }
      acc += seg;
    }
    return { x: wz[0] + ox, y: wz[1] + oy, dx: 1, dy: 0 };
  }

  /** The street names: one per name per tile, on its longest piece in view (a piece is a run of rows of one name, B3Chains).
      The piece must be longer than the name plus the fit allowance. Candidates are sorted with the arterials first, then the
      longest. A name tries the rows of its piece in view, the longest first, and keeps clear of the names already placed and
      of the dots (a grid of labels.grid_px); at most labels.per_view are drawn. Angles are quantised to labels.angle_deg and
      never upside down. Returns the count drawn. */
  function b3DrawNames(ents, vb, z, scale, ox, oy, size) {
    var B = B3, ctx = B.ctx, L_ = B.draw.labels, rd = B.roads, best = {};
    var cap = L_.per_view, fit = L_.fit_px, cell = L_.grid_px, step = L_.angle_deg * B3_DEG;
    ctx.font = B.nameFont;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ents.forEach(function (ent) {
      var names = ent.e.data.names;
      ent.e.data.chains.forEach(function (piece) {
        if (!names[piece.n] || !b3Overlaps(piece.bb, vb)) return;
        if (piece.zk !== z) {                  // the piece's length at this zoom (its rows' lengths)
          piece.len = 0;
          piece.rows.forEach(function (row) { b3Row(row, scale, z); piece.len += row.len; });
          piece.zk = z;
        }
        var key = ent.tile + "|" + names[piece.n];         // one name per tile: a split road's leaves index their names differently
        if (best[key] && piece.len <= best[key].len) return;   // a longer piece of this name is chosen already
        var inView = piece.rows.filter(function (row) { return b3Overlaps(row.bb, vb); });
        if (!inView.length) return;
        inView.sort(function (a, b) { return b.len - a.len; });
        best[key] = { len: piece.len, rows: inView, text: names[piece.n] };
      });
    });
    var list = Object.keys(best).map(function (k) { return best[k]; });
    list.forEach(function (x) {
      var c = x.rows[0].c;
      x.major = rd.classes[c] ? rd.classes[c].min_zoom <= B.zoom.arterials : false;
    });
    list.sort(function (a, b) { return (b.major - a.major) || (b.len - a.len); });
    var occ = {}, dr = B.dotR || 0;
    // a grid cell's key is a number (cx * 4096 + cy: the cells in view are a few dozen apart, so the keys stay unique)
    var cells = function (x0, y0, x1, y1, fn) {
      for (var cx = Math.floor(x0 / cell); cx <= Math.floor(x1 / cell); cx++) {
        for (var cy = Math.floor(y0 / cell); cy <= Math.floor(y1 / cell); cy++) fn(cx * 4096 + cy);
      }
    };
    var clashes = function (x0, y0, x1, y1) {
      var found = false;
      cells(x0, y0, x1, y1, function (k) {
        (occ[k] || []).forEach(function (b) { if (b[0] < x1 && b[2] > x0 && b[1] < y1 && b[3] > y0) found = true; });
      });
      return found;
    };
    var put = function (x0, y0, x1, y1) {
      cells(x0, y0, x1, y1, function (k) { (occ[k] = occ[k] || []).push([x0, y0, x1, y1]); });
    };
    if (L_.avoid_dots !== false) B.hits.forEach(function (h) { put(h.x - dr, h.y - dr, h.x + dr, h.y + dr); });   // a name keeps off the dots: on unless labels.avoid_dots is false
    var placed = 0, ANCHORS = 8;                      // rows of the piece to try, the longest first
    if (B.widthFont !== B.nameFont) { B.widthFont = B.nameFont; B.widths = new Map(); }   // a name's width, measured once per font
    var widthOf = function (text) {
      var v = B.widths.get(text);
      if (v === undefined) { v = ctx.measureText(text).width; B.widths.set(text, v); }
      return v;
    };
    for (var i = 0; i < list.length && placed < cap; i++) {
      var cand = list[i], w = widthOf(cand.text);
      if (cand.len < w + fit) continue;
      for (var k = 0; k < Math.min(ANCHORS, cand.rows.length); k++) {
        var row = cand.rows[k];
        var at = b3AlongRow(row.wz, row.len, 0.5, ox, oy);
        var ang = Math.atan2(at.dy, at.dx);
        ang = Math.round(ang / step) * step;
        if (ang > Math.PI / 2) ang -= Math.PI; else if (ang <= -Math.PI / 2) ang += Math.PI;
        var cs = Math.abs(Math.cos(ang)), sn = Math.abs(Math.sin(ang)), hh = B.sz.nameSize;
        var bw = w * cs + hh * sn, bh = w * sn + hh * cs;
        var x0 = at.x - bw / 2, y0 = at.y - bh / 2, x1 = at.x + bw / 2, y1 = at.y + bh / 2;
        if (x1 < 0 || y1 < 0 || x0 > size.x || y0 > size.y) continue;
        if (clashes(x0, y0, x1, y1)) continue;
        put(x0, y0, x1, y1);
        placed++;
        ctx.save();
        ctx.translate(at.x, at.y);
        ctx.rotate(ang);
        ctx.lineWidth = B.sz.halo;
        ctx.strokeStyle = B.col.halo;
        ctx.strokeText(cand.text, 0, 0);
        ctx.fillStyle = B.col.name;
        ctx.fillText(cand.text, 0, 0);
        ctx.restore();
        break;
      }
    }
    return placed;
  }

  // ---- the tap

  /** The dot nearest a point in the canvas (its box moves with the map, so a tap in a pan still finds the dots), within the
      tap radius (B3.tap), or null. */
  function b3Nearest(x, y) {
    var B = B3, best = null, bestD = B.tap * B.tap;
    B.hits.forEach(function (h) {
      var d = (h.x - x) * (h.x - x) + (h.y - y) * (h.y - y);
      if (d <= bestD && (!best || d < bestD)) { best = h; bestD = d; }
    });
    return best;
  }

  /** A click on the map. A dot within the tap radius takes it: the hail sheet for the dot's point (a town, a drag or a sheet
      that is open does not). Any other click goes on to the map as before. */
  function b3Tap(e) {
    var B = B3;
    if (!B || CARD || sheetState || !B.hits.length) return;
    if (e.target && e.target.closest && e.target.closest(".leaflet-marker-icon")) return;   // a town bubble or a place name
    if (B.down && Math.hypot(e.clientX - B.down.x, e.clientY - B.down.y) > map.options.tapTolerance) return;   // a drag
    var rect = B.canvas.getBoundingClientRect(), hit = b3Nearest(e.clientX - rect.left, e.clientY - rect.top);   // the canvas moves with the map pane
    if (!hit) return;
    e.stopPropagation();
    e.preventDefault();
    var list = hit.kind === "a" ? B.hits.filter(function (h) { return h.kind === "a" && h.lon === hit.lon && h.lat === hit.lat; })
      .map(function (h) { return { line: h.ref[2], city: h.ref[3], zip: h.ref[4], cls: h.ref[5] }; }) : [hit.ref];
    b3OpenDot({ kind: hit.kind, lon: hit.lon, lat: hit.lat, lines: hit.kind === "b" ? hit.ref : null, rows: list }, el.canvas);
  }

  /** The grid sentence for a dot outside the hail grid or in a tile with no file (D23): from the addresses words, else the buildings'. */
  function b3GridWords() {
    var b3 = B3 || {};
    return (b3.aw && b3.aw.outside_grid) || (b3.bw && b3.bw.outside_grid) || hailData().words.outside;
  }

  /** The sheet for a dot or a search row: the hail sheet at its point, with the address block on top. */
  function b3OpenDot(hit, opener) {
    var top = b3Top(hit);
    openHail(hit.lat, hit.lon, opener, { dot: true, top: top });
  }

  /** The address block at the top of the sheet, cloned from #address-sec: an outline's lines (or its no-address sentence),
      or an address point's line with the sentence of how it was placed when it is not a Structure point (D32). Nothing in
      the off mode (D35). */
  function b3Top(hit) {
    var B = B3, tpl = document.getElementById("address-sec");
    if (!B.textOn || !tpl) return null;
    var frag = tpl.content.cloneNode(true), sec = frag.querySelector('[data-addr="section"]');
    var lines = sec.querySelector('[data-addr="lines"]'), note = sec.querySelector('[data-addr="note"]'), units = sec.querySelector('[data-addr="units"]');
    var show = function (node, text) { node.textContent = text; node.hidden = !text; };
    var addLine = function (words, line, pair) {
      var li = document.createElement("li");
      var city = pair ? pair[0] : "", zip = pair ? pair[1] : "";
      li.textContent = !city ? line : zip ? fill(words.address_line, { line: line, city: city, zip: zip })
        : fill(words.address_line_no_zip, { line: line, city: city });
      lines.appendChild(li);
    };
    if (hit.kind === "b") {
      var it = hit.lines, ls = it.l || [];
      if (!ls.length) show(note, B.bld && B.bld.addresses === "unavailable" ? B.bw.addresses_unavailable : B.bw.no_address);
      else {
        ls.forEach(function (line, i) { addLine(B.bw, line, it.z && it.z[i] ? it.z[i] : it.c); });
        show(units, ls.length > 1 ? fill(B.bw.units, { n: ls.length }) : "");
      }
    } else {
      var rows = hit.rows;
      if (rows.length > 1) show(units, fill(B.aw.same_point, { n: rows.length }));
      rows.forEach(function (row) { addLine(B.aw, row.line, [row.city, row.zip]); });
      var off = rows.filter(function (row) { return row.cls && row.cls !== "S"; })[0];
      if (off) show(note, fill(B.aw.placed, { how: (B.aw.placed_how || {})[off.cls] || "" }));
    }
    sec.insertBefore(units, lines);      // the count ("Units on file", "{n} addresses at this point") comes before the lines (DESIGN section 10)
    sec.hidden = false;
    return frag;
  }

  // ---- the search

  /** Lower-case words of a text, punctuation and "#" dropped ("St." is "st", "1/2" stays). */
  function b3Words(text) {
    return String(text || "").toLowerCase().replace(/#/g, " ").replace(/[^a-z0-9\/ ]+/g, " ").split(" ").filter(Boolean);
  }

  /** The folder of a city (addresses.slug): lower-case ASCII words joined with dashes. */
  function b3Slug(name) {
    var s = String(name).normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return s || "city";
  }

  /** The file name of a letter key (addresses.file_key): letters and digits as they are, any other character as _ and four hex digits. */
  function b3FileKey(key) {
    return String(key).replace(/[^A-Za-z0-9]/g, function (ch) { return "_" + ("000" + ch.charCodeAt(0).toString(16)).slice(-4); });
  }

  /** The address line of a result or a shard row, in the words of the module: "{line}, {city} {zip}". */
  function b3LineText(words, item) {
    return item.zip ? fill(words.address_line, { line: item.line, city: item.city, zip: item.zip })
      : fill(words.address_line_no_zip, { line: item.line, city: item.city });
  }

  /** The site town nearest the map's centre (the town a search falls back to when the typed text names no city). */
  function b3NearestTown() {
    if (!data || !data.towns || !data.towns.length) return null;
    var c = map.getCenter(), best = null, bestD = Infinity;
    data.towns.forEach(function (t) {
      var d = (t.lat - c.lat) * (t.lat - c.lat) + (t.lon - c.lng) * (t.lon - c.lng);
      if (d < bestD) { best = t; bestD = d; }
    });
    return best;
  }

  /** The search, parsed (D6): the town, the leading address number, the spelled-out words of the street, the core name and the
      key file. Null when the text has no words. The town is the longest run at the end that the city index names; with
      none, the site town nearest the map's centre, when the index names it. */
  function b3Parse(text, cityNames) {
    var words = B3.adr.search_words || {}, tokens = b3Words(text);
    if (!tokens.length) return null;
    if (tokens.length > 1 && (tokens[tokens.length - 1] === "mt" || tokens[tokens.length - 1] === "montana")) tokens.pop();
    var city = null, cut = tokens.length;
    for (var k = 0; k < tokens.length && !city; k++) {
      var named = cityNames.get(tokens.slice(k).join(" "));
      if (named) { city = named; cut = k; }
    }
    if (!city) {
      var town = b3NearestTown(), fallback = town ? cityNames.get(b3Words(town.name).join(" ")) : null;
      if (fallback) city = fallback;
    }
    if (!city) return null;
    var rest = tokens.slice(0, cut), number = "";
    if (rest.length && B3_NUMBER.test(rest[0])) number = rest.shift();
    var toks = [];
    rest.forEach(function (t) { (words[t] ? String(words[t]).split(" ") : [t]).forEach(function (x) { toks.push(x); }); });
    var kinds = {};
    Object.keys(words).forEach(function (k) { String(words[k]).split(" ").forEach(function (x) { kinds[x] = true; }); });
    var core = toks.filter(function (t) { return !kinds[t]; })[0] || toks[0] || "";
    return { city: city, number: number, toks: toks, core: core };
  }

  /** Read the city index once (a promise of the map from a normalised city name to its display name, and the index itself). */
  function b3Cities() {
    var url = B3.root + B3.adr.cities;
    return b3Load("cities", url, true, false).then(function (doc) {
      if (!B3.cityNames) {
        B3.cityNames = new Map();
        Object.keys(doc.cities).forEach(function (name) { B3.cityNames.set(b3Words(name).join(" "), name); });
      }
      return doc.cities;
    });
  }

  /** Wire the form: a submit searches, and the typed text never leaves this page. */
  function b3WireSearch() {
    var form = document.getElementById("address-form"), input = document.getElementById("address-input");
    if (!B3.adr || !B3.textOn || !form || !input || !B3.adr.cities || !B3.adr.letter) return;
    B3.searchOn = true;
    form.addEventListener("submit", function (e) { e.preventDefault(); b3Search(input.value); });
  }

  /** The phone's Find an address button (#btn-find, drawn only on a phone: map.css) opens and closes the find panel. It is wired
      whether or not the search is on: a list that did not load shows its sentence in the panel. */
  function b3WireFind() {
    var btn = document.getElementById("btn-find");
    if (btn) btn.addEventListener("click", function () { b3FindOpen(!el.top.classList.contains("find-shown")); });
  }

  /** The find panel on a phone, open or closed (#top carries .find-shown while it is open, and the legend card steps aside for
      it: map.css). Closing it closes the results too, so the legend comes back with the panel. The fit is asked again, as it is
      when a banner comes or goes. Opening it puts the cursor in the field. */
  function b3FindOpen(open) {
    var btn = document.getElementById("btn-find"), input = document.getElementById("address-input"), list = document.getElementById("address-results");
    el.top.classList.toggle("find-shown", !!open);
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (!open && list) b3ResultsOpen(list, false);
    refitForBanner();
    if (open && input) input.focus();
  }

  /** Show a search message (the module's words), or hide the line when there is none. */
  function b3Status(text) {
    var st = document.getElementById("address-status");
    if (!st) return;
    st.textContent = text || "";
    st.hidden = !text;
  }

  /** The results list shows or hides. While it shows, #top carries .results-open: on a phone the legend card steps aside for
      it (map.css), and the fit is asked again, as it is when a banner comes or goes (unless the viewer has moved the map). */
  function b3ResultsOpen(list, on) {
    list.hidden = !on;
    if (el.top.classList.contains("results-open") === !!on) return;
    el.top.classList.toggle("results-open", !!on);
    refitForBanner();
  }

  /** One search: the city index, one letter file, the list of rows (up to the cap) and the words for each outcome. */
  function b3Search(text) {
    var B = B3, list = document.getElementById("address-results"), W = B.aw;
    if (!list) return;
    b3Status("");
    list.innerHTML = "";
    b3ResultsOpen(list, false);
    if (!b3Words(text).length) return b3Status(W.search_hint);
    b3Cities().then(function (cities) {
      var parts = b3Parse(text, B.cityNames);
      if (!parts) return b3Status(W.search_none);
      var entry = cities[parts.city] || {}, keys = entry.keys || {};
      var c1 = parts.core.charAt(0).toUpperCase(), c2 = parts.core.length > 1 ? parts.core.slice(0, 2).toUpperCase() : c1 + " ";
      var key = keys[c1] !== undefined ? c1 : keys[c2] !== undefined ? c2 : null;
      if (!key) return b3Status(W.search_none);
      var url = B.root + B.adr.letter.replace("{dir}", entry.dir || b3Slug(parts.city)).replace("{key}", b3FileKey(key));
      return b3Load("letter", url, false, false).then(function (doc) {
        var want = parts.toks, num = parts.number.toLowerCase(), n0 = parseInt(num, 10);
        var rows = doc.rows.filter(function (r) {
          var street = String(r[1]).toLowerCase().replace(/[^a-z0-9\/ ]+/g, " ").split(" ").filter(Boolean).join(" ");
          return want.every(function (t) { return street.indexOf(t) >= 0; });
        });
        if (num) {
          var near = function (r) { var v = parseInt(r[0], 10); return isNaN(v) ? Infinity : Math.abs(v - n0); };
          rows.sort(function (a, b) {
            var ea = String(a[0]).toLowerCase() === num ? 0 : 1, eb = String(b[0]).toLowerCase() === num ? 0 : 1;
            return (ea - eb) || (near(a) - near(b));
          });
        }
        if (!rows.length) return b3Status(W.search_none);
        var cap = (B.adr.limits || {}).result_cap, shown = rows.slice(0, cap);
        shown.forEach(function (r) {
          var li = document.createElement("li"), btn = document.createElement("button");
          var item = { line: [r[0], r[1], r[2]].filter(Boolean).join(" "), city: parts.city, zip: r[5], cls: r[6], lon: r[3], lat: r[4] };
          btn.type = "button";
          btn.className = "find-row";
          btn.textContent = b3LineText(W, item);
          btn.addEventListener("click", function () { b3Choose(item, btn); });
          li.appendChild(btn);
          list.appendChild(li);
        });
        b3ResultsOpen(list, true);
        if (rows.length > shown.length) b3Status(W.search_capped);
      }, function () { b3Status(B.adr.templates.unavailable); });
    }, function () { b3Status(B.adr.templates.unavailable); });
  }

  /** A chosen result: zoom to its point and open its sheet (with its address line on top). */
  function b3Choose(item, opener) {
    state.userMoved = true;
    map.setView([item.lat, item.lon], B3.zoom.choose || B3.zoom.emphasis, { animate: false });   // the search's zoom (D47)
    b3OpenDot({ kind: "a", lon: item.lon, lat: item.lat, lines: null, rows: [item] }, opener);
  }
  // B3 layers: end

  boot();
})();
