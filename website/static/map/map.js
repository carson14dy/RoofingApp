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
     store, not by this file: in a store file, a tile that hail.tile_split does not list has no Montana cell, so the
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
   - The map options sheet (DESIGN 13.6, D108): the Layers button opens it. Its chips and switches set the live layer, the
     five-year choice, the landmark kinds, Points of interest, the recent radar hail highlight, Warnings and Storm reports,
     and its Reset. This is JavaScript because a chip changes a state the page draws, and the focus trap and the inert page
     are browser work. Every word the sheet shows is Python's: each chip's data-legend and data-reason, the landmark line's
     data-template, and data/base.json (its sheet block, the picture and zone words, the held and unavailable sentences and
     the list joins). The page's first-paint words (the banners and the reports and picture lines, and the sheet's words
     before base.json answers) are the map-words script that build.py renders (MAP_WORDS, read once into PW). The address
     keeps the choices: layer, base, poi, hail_recent, history and landmarks (poi=0 and hail_recent=1 read as off and on).
   - The base map's own drawing (B6, DESIGN 13.2 and 13.7; website/static/map/layers.js, loaded after this file): the terrain
     tiles, the vector bands A to D, the places and the summits, the credit lines and the sheet's base map line. This file makes
     the two panes it draws in ("terrain" and "vectors", under the weather pictures) and starts layers.js once data/base.json has
     loaded (startBaseLayers); it hands layers.js its words and its state, and asks it to redraw when a sheet choice changes.
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

  /* The page's words, rendered by Python into <script id="map-words"> (build.py MAP_WORDS): read once here. A word with a
     {name} takes a value from the data (a layer's title, a detail) through wordFill; the script holds no sentence of its own. */
  var PW = (function () {
    try { return JSON.parse(document.getElementById("map-words").textContent) || {}; } catch (e) { return {}; }
  })();

  var el = {
    banners: byId("banners"), legendTitle: byId("legend-title"), legendScale: byId("legend-scale"),
    legendBar: byId("legend-bar"), legendStops: byId("legend-stops"), legendNote: byId("legend-note"),
    legendUncoloured: byId("legend-uncoloured"),
    legendKeys: byId("legend-keys"), layersBtn: byId("btn-layers"), locateBtn: byId("btn-locate"),
    listBtn: byId("btn-list"), options: byId("map-options"), optTitle: byId("mo-title"), optClose: byId("mo-close"),
    optReset: byId("mo-reset"), warnings: byId("tg-warnings"), reports: byId("tg-reports"), poi: byId("tg-poi"),
    hailRecent: byId("tg-hail-recent"), find: byId("find"),
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
    autoplay: true,                  // play once the first picture shows, unless the viewer chose first (setPlaying)
    history: null, landmarks: {}, poi: true, hailRecent: false   // the sheet's choices (DESIGN 13.6; readOptionParams)
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
      return r.json().then(null, function () { throw new Error("the file was incomplete or unreadable"); });
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
    wireControls();
    b3Start();                                     // --hail-addresses builds: roads, outlines and address dots (B3)
    var want = params.get("layer");
    var mode = params.get("mode");
    if (mode === "1h" || mode === "12h") state.mode = mode;
    readOptionParams();                            // poi, hail_recent, history and landmarks (DESIGN 13.6)
    el.warnings.checked = state.warnings;
    el.reports.checked = state.reports;
    setReports(state.reports, true);
    if (want === "none") setLayer(null, { first: true });   // no live layer (layer=none, set by saveUrl)
    else setLayer(want && data.layers[want] ? want : "precip", { atNow: true, first: true });
    if (params.get("base") === "imagery") setBase("imagery", { first: true });   // D32: the page address opens on imagery
    renderOptions();
    requestAnimationFrame(function () { setTimeout(loadBase, 0); });   // base.json after the first paint (DESIGN 13.6)
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
    pane("terrain", 405, false);                   // B6: the terrain tiles (layers.js), under the vectors
    pane("vectors", 408, false);                   // B6: the base map canvas (layers.js), under the weather pictures
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
      if (!el.options.hidden) placeSheet(el.options);
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
    // the towns keep their place: a base map label (layers.js: a place or a summit) clears their bubbles and names too (DESIGN 13.7)
    var towns = [].slice.call(el.canvas.querySelectorAll(".town .bubble, .town .tname")).map(function (x) {
      var t = x.getBoundingClientRect();
      return { left: t.left, right: t.right, top: t.top, bottom: t.bottom, width: t.width, height: t.height };
    }).filter(function (b) { return b.width > 2 && b.height > 2; });
    for (var i = 0; i < spans.length; i++) {
      var r = textBox(spans[i]), hide = false;                               // the glyphs, taller than the line
      var left = spans[i].previousElementSibling ? r.left - 10 : r.left;      // a place's dot, left of its name
      var others = spans[i].parentNode.classList.contains("base-label") ? boxes.concat(towns) : boxes;
      for (var k = 0; r.width && !hide && k < others.length; k++) {
        var b = others[k];
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
    if (sourceCtl) {                                      // the source lines above the band (b3Lift): towns under them count too
      var cr = sourceCtl.getContainer().getBoundingClientRect();
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
    if (sourceCtl) room += sourceCtl.getContainer().offsetHeight + 8;     // the source lines sit above the note (b3Lift)
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
    renderOptions();
    if (!quiet) saveUrl();
  }

  /** The storm reports sentence (DESIGN 13.6): Python's words, on the switch's data-legend (tg-reports). */
  function reportsNoReport() { return el.reports.getAttribute("data-legend") || ""; }

  /** When the reports overlay is on: say how many, or that the report files failed. */
  function renderReportNote() {
    var old = byId("reports-banner");
    if (old) old.remove();
    if (!state.reports || !data) return;
    var st = data.status && data.status.reports;
    if (st && !st.ok) {
      banner("warn", wordFill("reports_failed", { detail: esc(st.detail) }) + reportsNoReport(), "reports-banner");
    } else if (!data.reports.length) {
      banner("info", (PW.reports_none || "") + reportsNoReport(), "reports-banner");
    }
  }

  // ------------------------------------------------------------------ layers, modes and the timeline

  /** The active layer's data. */
  function layer() { return data.layers[state.layer] || { frames: [], modes: {}, now_index: {} }; }

  /** The title of a weather layer as data/map.json gives it (the legend's and the timeline's words). */
  function layerWord(key) { var L_ = key && data && data.layers[key]; return (L_ && L_.title) || ""; }

  /** Switch the weather layer; keep the time on the timeline when the new layer has it. */
  function setLayer(key, opts) {
    opts = opts || {};
    if (!key) { hideLive(opts); return; }
    var keep = (!opts.atNow && state.frames.length) ? state.times[state.pos] : null;
    state.layer = key;
    el.timeline.hidden = false;
    el.legend.hidden = false;
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
    renderOptions();
  }

  /** No live layer (DESIGN 13.6, setLayer(null)): the picture goes, the timeline and the legend card are hidden, and the address
      says layer=none. The town numbers stay, since they are the NWS forecast and not a layer. */
  function hideLive(opts) {
    setPlaying(false);
    state.layer = null;
    state.frames = []; state.times = []; state.pos = 0; state.nowPos = 0;
    el.timeline.hidden = true;
    el.legend.hidden = true;
    showPicture(null, null);
    hailWatch(false);
    renderOptions();
    if (!(opts && opts.first)) saveUrl();
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
        whenEl.textContent = wordFill("nothing_to_show", { layer: layerWord(state.layer).toLowerCase() });
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
      if (state.layer === "precip" && st.radar && !st.radar.ok) why.push(wordFill("radar_reason", { detail: st.radar.detail }));
      if (state.layer === "satellite" && st.satellite && !st.satellite.ok) why.push(wordFill("satellite_reason", { detail: st.satellite.detail }));
      if (st.forecast && !st.forecast.ok) why.push(wordFill("forecast_reason", { detail: st.forecast.detail }));
      warns.push(wordFill("no_layer_pictures", { layer: layerWord(state.layer).toLowerCase(),
                                                 why: why.length ? " (" + why.join("; ") + ")" : "" }));
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
    el.legendTitle.textContent = L_.title || layerWord(state.layer);
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

  // ------------------------------------------------------------------ base map: white or imagery (D32)

  /** Switch the base map. The white vector map is the default. Imagery (opt-in) is USGS aerial imagery with
      roads and names: its tile layer is made on the first switch, and the browser asks for tiles only while
      it is on (a switch, or an address that starts on it). While it is on, the vector base map's land, water,
      roads, county lines, place dots and names are hidden (is-imagery, map.css); the Montana outline and the
      state and country borders stay, and so do the weather, the warning outlines, the reports and the bubbles.
      The zoom limit goes up to the imagery's and back to the map's own (Leaflet zooms out to it when needed).
      The credit row shows the credit with its privacy words while it is on, and the failure words while tiles
      fail (setImageryFailed). The card never uses imagery. */
  function setBase(value, opts) {
    if (CARD || !data || !imageryCfg) return;
    opts = opts || {};
    var imagery = value === "imagery";
    state.base = imagery ? "imagery" : "map";
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
    renderOptions();
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

    el.layersBtn.addEventListener("click", function () { toggleOptions(el.options.hidden); });
    el.options.addEventListener("click", onOptionsClick);
    el.options.addEventListener("change", onOptionsChange);
    el.options.addEventListener("keydown", trapOptionsFocus);
    el.optClose.addEventListener("click", function () { toggleOptions(false, true); });
    el.optReset.addEventListener("click", resetOptions);
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
    document.addEventListener("pointerdown", function (e) {     // a tap outside closes the options sheet
      if (!el.options.hidden && !el.options.contains(e.target) && !el.layersBtn.contains(e.target)) toggleOptions(false);
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

  /** Page keys: Escape closes the options sheet or a sheet; Space plays; arrows step (outside text fields). */
  function onKey(e) {
    if (CARD) return;
    if (e.key === "Escape") {
      if (!el.options.hidden) { e.preventDefault(); toggleOptions(false, true); return; }
      if (sheetState) { e.preventDefault(); closeSheet(); return; }
      return;
    }
    if (sheetState || !el.options.hidden || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target, tag = (t && t.tagName) || "";
    var onPage = t === document.body || t === el.play || t === el.timeline || t === document.documentElement;
    // the map itself too: a click or drag on it focuses it (Leaflet's keys don't use Space)
    if (e.key === " " && (t === document.body || t === document.documentElement || t === el.canvas)) { e.preventDefault(); setPlaying(!state.playing); return; }
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && onPage && tag !== "INPUT") {
      e.preventDefault();
      stepBy(e.key === "ArrowLeft" ? -1 : 1);
    }
  }

  /** Open or close the map options sheet (DESIGN 13.6). It opens on its title and closes back to #btn-layers (refocus). While it
      is open the page behind it is inert (setInert); Escape and a tap outside close it. */
  function toggleOptions(open, refocus) {
    if (open && (CARD || !data)) return;
    el.options.hidden = !open;
    el.layersBtn.setAttribute("aria-expanded", open ? "true" : "false");
    setInert(!!open);
    if (open) {
      placeSheet(el.options);
      renderOptions();
      el.optTitle.focus({ preventScroll: true });
    } else if (refocus) el.layersBtn.focus();
  }

  /** Keep the chosen layer, mode and overlay in the address so a reload keeps them. */
  function saveUrl() {
    if (CARD || !window.history || !history.replaceState || !data) return;
    var q = new URLSearchParams(location.search);
    q.delete("town");
    if (!state.layer) q.set("layer", "none"); else if (state.layer !== "precip") q.set("layer", state.layer); else q.delete("layer");
    var modes = Object.keys(layer().modes || {});
    if (modes.length > 1 && state.mode !== "12h") q.set("mode", state.mode); else q.delete("mode");
    if (state.reports) q.set("overlay", "reports"); else q.delete("overlay");
    if (state.base === "imagery") q.set("base", "imagery"); else q.delete("base");
    optionParams(q);
    if (hailAt) q.set("at", hailAt); else q.delete("at");
    var s = q.toString();
    history.replaceState(null, "", location.pathname + (s ? "?" + s : "") + location.hash);
  }

  /** "&layer=temp&overlay=reports" for links to the full map (prefix "?" or "&"). */
  function layerQuery(prefix) {
    var q = [];
    if (!state.layer || state.layer !== "precip") q.push("layer=" + (state.layer || "none"));
    if (state.reports) q.push("overlay=reports");
    return q.length ? prefix + q.join("&") : "";
  }

  // ------------------------------------------------------------------ the map options sheet (DESIGN 13.6, D108, D110)

  /* The sheet's words are Python's. Each chip carries its legend (data-legend), its reason (data-reason) and, for the
     landmark line, its template (data-template); data/base.json (its "sheet" block, the picture and zone words, the held
     and unavailable sentences, the list joins) holds the rest. renderOptions turns the data's states into the five looks of
     a chip: off, on, unavailable (dashed, with its word and its reason), waiting (Points of interest is off) and held. A chip
     whose data has not loaded yet is pending: disabled, with no reason, until base.json answers. A choice here changes its
     state, its legend line and the address. What the five-year, landmark and recent layers draw is added on the map in the
     later stages (DESIGN 13.6, "Browser hooks"). */
  /** A word with its {name} values filled in: the page's words (PW) hold the words, the data holds the values. */
  function wordFill(key, values) {
    var text = PW[key] || "";
    Object.keys(values || {}).forEach(function (name) { text = text.split("{" + name + "}").join(values[name]); });
    return text;
  }

  /** The sheet's words: the page's first-paint block (PW), then data/base.json's sheet block once it has loaded. */
  function sheetWords() {
    var out = {}, base = (baseDoc && !baseDoc._error && baseDoc.sheet) || {};
    Object.keys(PW).forEach(function (k) { out[k] = PW[k]; });
    Object.keys(base).forEach(function (k) { out[k] = base[k]; });
    return out;
  }

  var baseDoc = null;                // data/base.json once it has loaded; { _error } when it could not be fetched
  var baseLineText = "";            // the base map's line (layers.js: the problems in view), shown under the imagery legend
  var optionNote = {};               // a group's reason, opened by a tap on a chip that is not available (the next change clears it)

  /** The chip or card of one group and key, from the markup (data-group, data-key). */
  function optionItem(group, key) {
    return el.options.querySelector("[data-group=\"" + group + "\"][data-key=\"" + key + "\"]");
  }

  /** The chips of one group, in the order the markup gives them. */
  function optionChips(group) {
    return [].slice.call(el.options.querySelectorAll(".mo-chip[data-group=\"" + group + "\"]"));
  }

  /** The name of the landmark kind whose code is code (base.json landmarks.kinds), or null. */
  function kindName(kinds, code) {
    return Object.keys(kinds).filter(function (n) { return kinds[n] && kinds[n].code === code; })[0] || null;
  }

  /** A chip's aria-pressed and look: "plain" (off or on), "pending", "unavailable", "waiting" or "held". reason, when it is
      given (a string, maybe empty), replaces the chip's data-reason; noteText, when it is given, replaces the words on its face. */
  function setChip(node, pressed, look, reason, noteText) {
    node.setAttribute("aria-pressed", pressed ? "true" : "false");
    // a pending chip is not disabled (it is not unavailable yet); a tap on it changes nothing (onOptionsClick)
    node.setAttribute("aria-disabled", look === "plain" || look === "pending" ? "false" : "true");
    node.classList.toggle("is-pending", look === "pending");
    node.classList.toggle("is-unavailable", look === "unavailable");
    node.classList.toggle("is-waiting", look === "waiting");
    node.classList.toggle("is-held", look === "held");
    if (reason !== undefined) {
      if (reason) node.setAttribute("data-reason", reason); else node.removeAttribute("data-reason");
    }
    var face = noteText !== undefined ? node.querySelector(".mo-note") : null;
    if (face) face.textContent = noteText || "";
  }

  /** A group's line: its text, or hidden when there is none. */
  function setGroupLine(line, text) {
    if (!line) return;
    line.textContent = text || "";
    line.hidden = !text;
  }

  /** A chip's legend: its own data-legend, or the layer's note from map.json (the satellite chip has none of its own). */
  function legendOf(chip) {
    var L_ = data && data.layers[chip.getAttribute("data-key")];
    return chip.getAttribute("data-legend") || (L_ && L_.legend_note) || "";
  }

  /** The five-year chip's picture or zone block in base.json, and its legend words. */
  function historyBlock(key, b) {
    var hist = b.history_layers || {}, pics = hist.pictures || {};
    if (key === "hail") return { block: pics.hail1, legend: ((pics.hail1 || {}).words || {}).legend || "" };
    if (key === "heat") return { block: pics.heat90, legend: ((pics.heat90 || {}).words || {}).legend || "" };
    if (key === "wind" || key === "flood") return { block: hist.zones, legend: ((hist.zones || {}).words || {}).legend || "" };
    return { block: null, legend: "" };
  }

  /** The base map cards: the chosen one is pressed. The Imagery legend shows under them while Imagery is chosen. */
  function renderBaseCards() {
    [].forEach.call(el.options.querySelectorAll(".mo-card"), function (card) {
      card.setAttribute("aria-pressed", card.getAttribute("data-key") === state.base ? "true" : "false");
    });
    var imagery = optionItem("base", "imagery");
    var legend = state.base === "imagery" && imagery ? imagery.getAttribute("data-legend") : "";
    setGroupLine(byId("mo-base-line"), [legend, baseLineText].filter(Boolean).join(" "));
  }

  /** The landmark line (DESIGN 13.6): the kinds that are on, named by their chips (data-name), in the sentence that
      data-template gives. Hidden while no kind is on or Points of interest is off. */
  function landmarkLine() {
    var line = byId("mo-land-line");
    if (!line) return;
    var names = optionChips("landmark").filter(function (c) {
      return state.landmarks[c.getAttribute("data-key")] && c.getAttribute("aria-pressed") === "true";
    }).map(function (c) { return c.getAttribute("data-name") || ""; });
    var text = "";
    if (state.poi && names.length) {
      var words = sheetWords();
      var kinds = names.length > 2 ? names.slice(0, -1).join(words.list_comma) + words.list_last + names[names.length - 1]
                                   : names.join(words.list_and);
      text = (line.getAttribute("data-template") || "").replace("{kinds}", kinds);
      text = text.charAt(0).toUpperCase() + text.slice(1);
    }
    setGroupLine(line, text);
  }

  /** Every state on the sheet, read from the data: the base cards, the live chips, the five-year chips, the landmark kinds,
      the switches and the group lines. map.json gives the layers and the states of the store's blocks; base.json (fetched
      once after the first paint) gives the picture, zone, landmark and recent words. Calls are cheap; each one sets the same
      state from the same data. */
  function renderOptions() {
    if (!el.options || !data) return;
    var failed = !!(baseDoc && baseDoc._error), pending = !baseDoc;
    var b = pending || failed ? {} : baseDoc, words = sheetWords(), note = optionNote;
    renderBaseCards();
    // Live weather: one choice at a time; the layers come from map.json, so they are always available
    optionChips("live").forEach(function (c) { setChip(c, state.layer === c.getAttribute("data-key"), "plain"); });
    var liveOn = optionChips("live").filter(function (c) { return c.getAttribute("aria-pressed") === "true"; })[0];
    setGroupLine(byId("mo-live-line"), liveOn ? legendOf(liveOn) : "");
    // Five-year history: one choice; a chip draws from its picture or zone file in base.json. A part that did not load, or
    // loaded in part, is unavailable with its own sentence (a zero may be a missing count)
    optionChips("history").forEach(function (c) {
      var key = c.getAttribute("data-key");
      if (key === "fire_smoke") { if (state.history === key) state.history = null; setChip(c, false, "unavailable"); return; }
      if (pending) { setChip(c, false, "pending", ""); return; }
      var h = historyBlock(key, b), st = h.block && h.block.state;
      if (failed || st !== "loaded") {
        if (state.history === key) state.history = null;
        var why = !failed && h.block && h.block.problem ? h.block.problem
          : !failed && st === "partial" ? words.partial_history : words.base_failed;
        setChip(c, false, "unavailable", why, words.unavailable);
        return;
      }
      setChip(c, state.history === key, "plain", "");
    });
    var histOn = optionChips("history").filter(function (c) { return c.getAttribute("aria-pressed") === "true"; })[0];
    setGroupLine(byId("mo-hist-line"), histOn ? historyBlock(histOn.getAttribute("data-key"), b).legend : "");
    // a tapped unavailable chip's reason has a line of its own, so the legend of a chip that is on stays beside it
    setGroupLine(byId("mo-hist-reason"), note.history || "");
    // Landmarks: any number at once; held kinds say so with their reason, and the chips wait while Points of interest is off
    var base = b.base || {};                 // base.json: the base map's own block (landmarks, held) sits under "base"
    var lmBlock = base.landmarks || {}, kinds = lmBlock.kinds || {}, held = (base.held || {}).kinds || {};
    optionChips("landmark").forEach(function (c) {
      var code = c.getAttribute("data-key"), name = kindName(kinds, code), kind = name ? kinds[name] : null;
      if (pending) { setChip(c, false, "pending", ""); return; }
      if (failed || !kind) {
        delete state.landmarks[code];
        setChip(c, false, "unavailable", failed ? words.base_failed : (lmBlock.problem || words.base_failed), words.unavailable);
        return;
      }
      if (kind.held || kind.state === "held") {
        delete state.landmarks[code];
        setChip(c, false, "held", (held[name] || {}).reason || kind.problem || "", words.held);
        return;
      }
      if (kind.state !== "loaded") {
        delete state.landmarks[code];
        setChip(c, false, "unavailable", kind.problem || lmBlock.problem || words.base_failed, words.unavailable);
        return;
      }
      if (!state.poi) { setChip(c, !!state.landmarks[code], "waiting", byId("mo-land-reason").getAttribute("data-waiting") || ""); return; }
      setChip(c, !!state.landmarks[code], "plain", "");
    });
    landmarkLine();
    setGroupLine(byId("mo-land-reason"), note.landmark || "");
    // Switches: Points of interest and Warnings and Storm reports have no data of their own; the recent-hail switch
    // needs the recent block, and is unavailable (with the store's words) when it is unavailable or stale
    el.poi.checked = state.poi;
    el.warnings.checked = state.warnings;
    el.reports.checked = state.reports;
    setGroupLine(byId("mo-reports-line"), state.reports ? el.reports.getAttribute("data-legend") : "");
    var rec = b.recent || null, recOff = pending || failed || !rec || rec.state === "unavailable" || !!rec.stale;
    var recReason = pending ? "" : (failed || !rec) ? words.base_failed : (rec.state === "unavailable" ? (rec.problem || words.base_failed) : (rec.stale || ""));
    if (!pending && recOff && state.hailRecent) { state.hailRecent = false; saveUrl(); }   // a link's choice waits for base.json
    el.hailRecent.disabled = recOff;
    el.hailRecent.checked = pending ? state.hailRecent : state.hailRecent && !recOff;
    setGroupLine(byId("mo-recent-line"), pending ? "" : recOff ? recReason :
      (state.hailRecent ? el.hailRecent.getAttribute("data-legend") : ""));
    if (window.hailMapLayers) window.hailMapLayers.update();     // the base map follows the sheet's choices (layers.js)
  }

  /** Live weather (DESIGN 13.6): one choice, and the chosen one turns off with a tap on it (no live layer: setLayer(null)). */
  function setLive(key) {
    optionNote = {};
    setLayer(key || null);
  }

  /** Five-year history: one choice; null turns it off. */
  function setHistory(key) {
    optionNote = {};
    state.history = key || null;
    renderOptions();
    saveUrl();
  }

  /** A landmark kind (its code: s, p, h, a, f or c): any number of kinds at once. */
  function setLandmark(code, on) {
    optionNote = {};
    if (on) state.landmarks[code] = true; else delete state.landmarks[code];
    renderOptions();
    saveUrl();
  }

  /** Points of interest: the landmark dots and names. Off, the landmark chips wait with their choices kept. */
  function setPoi(on) {
    optionNote = {};
    state.poi = !!on;
    renderOptions();
    saveUrl();
  }

  /** The recent-hail switch: the building highlight of the recent cells (drawn in a later stage). */
  function setHailRecent(on) {
    optionNote = {};
    state.hailRecent = !!on;
    renderOptions();
    saveUrl();
  }

  /** Reset (DESIGN 13.6): Map as the base map, Precipitation, no five-year choice, no landmark kind, Points of interest on,
      The recent-hail switch off, Warnings on and Storm reports off. The sheet stays open, and unavailable chips stay so. */
  function resetOptions() {
    optionNote = {};
    state.history = null;
    state.landmarks = {};
    state.hailRecent = false;
    state.poi = true;
    setBase("map");
    setLayer("precip");
    setWarnings(true);
    setReports(false);
    renderOptions();
    saveUrl();
  }

  /** The sheet's address parameters (DESIGN 13.6): poi=off, hail_recent=on, history=<chip key>, landmarks=<kind codes>. A value
      that names no chip of this page is ignored. Read on boot. */
  function readOptionParams() {
    var poi = params.get("poi"), recent = params.get("hail_recent");
    state.poi = !(poi === "off" || poi === "0");            // poi=off (or 0) turns Points of interest off
    state.hailRecent = recent === "on" || recent === "1";   // hail_recent=on (or 1) turns the recent-hail highlight on
    var h = params.get("history");
    state.history = h && optionItem("history", h) ? h : null;
    state.landmarks = {};
    (params.get("landmarks") || "").split(",").forEach(function (code) {
      if (code && optionItem("landmark", code)) state.landmarks[code] = true;
    });
  }

  /** Writes the sheet's parameters into the address (saveUrl): a default is left out. */
  function optionParams(q) {
    if (!state.poi) q.set("poi", "off"); else q.delete("poi");
    if (state.hailRecent) q.set("hail_recent", "on"); else q.delete("hail_recent");
    if (state.history) q.set("history", state.history); else q.delete("history");
    var codes = Object.keys(state.landmarks).filter(function (c) { return state.landmarks[c]; });
    if (codes.length) q.set("landmarks", codes.join(",")); else q.delete("landmarks");
  }

  /** data/base.json, fetched once after the first paint by the name data/map.json gives (base.file). Until it answers the
      chips that need it are pending; when it cannot be read they show unavailable with the sheet's own sentence. */
  function loadBase() {
    var file = data && data.base && data.base.file;
    if (!file) { baseDoc = { _error: true }; renderOptions(); return; }
    fetchJSON(file).then(function (d) { baseDoc = d; }, function () { baseDoc = { _error: true }; })
      .then(function () { renderOptions(); startBaseLayers(); });
  }

  /** The base map's drawing (layers.js, B6): started once data/base.json has answered. ctx is documented at layers.js start(). */
  function startBaseLayers() {
    if (!window.hailMapLayers || !data || !data.base || !baseDoc || baseDoc._error) return;
    var hail = data.hail || {};
    window.hailMapLayers.start({
      map: map, app: app, root: (app.getAttribute("data-map") || "").replace(/data\/map\.json.*$/, ""),
      block: baseDoc.base || {}, grid: hail.grid || null, tileSplit: hail.tile_split || null,
      cap: (hail.draw || {}).cache_bytes || 0, sheet: sheetWords, setLine: setBaseLine, tidy: tidyLabels,
      imagery: function () { return state.base === "imagery"; }, attribution: sourceControl
    });
  }

  /** The base map's line (layers.js): its words, or "" when everything in view is drawn. Shown with the imagery legend. */
  function setBaseLine(text) { baseLineText = text || ""; renderBaseCards(); }

  /** A tap in the sheet: a base card, or a chip. A chip that is not available opens its reason and changes nothing else. */
  function onOptionsClick(e) {
    var item = e.target.closest ? e.target.closest(".mo-chip, .mo-card") : null;
    if (!item || !el.options.contains(item)) return;
    var group = item.getAttribute("data-group"), key = item.getAttribute("data-key");
    if (group === "base") { setBase(key); return; }
    var on = item.getAttribute("aria-pressed") === "true";
    if (item.classList.contains("is-pending")) return;     // base.json has not answered yet: nothing to change
    if (item.getAttribute("aria-disabled") === "true") {
      optionNote = {};
      optionNote[group] = item.getAttribute("data-reason") || "";
      renderOptions();
      return;
    }
    if (group === "live") setLive(on ? null : key);
    else if (group === "history") setHistory(on ? null : key);
    else if (group === "landmark") setLandmark(key, !on);
  }

  /** A switch's change. */
  function onOptionsChange(e) {
    var t = e.target;
    if (t === el.warnings) setWarnings(t.checked);
    else if (t === el.reports) setReports(t.checked);
    else if (t === el.poi) setPoi(t.checked);
    else if (t === el.hailRecent) setHailRecent(t.checked);
  }

  /** Tab and Shift+Tab wrap around inside the open sheet, as they do in the town sheet. */
  function trapOptionsFocus(e) {
    if (e.key !== "Tab") return;
    var f = [].slice.call(el.options.querySelectorAll("button, input, [tabindex='0']")).filter(function (x) {
      return !x.disabled && x.offsetParent !== null;
    });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === el.optTitle)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
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
    if (el.sheet) el.sheet.classList.remove("sheet-wide");     // the five-season table widens the sheet; no other sheet does
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
    toggleOptions(false);
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

  /** Keep an open sheet clear of the banners at the top and of the find panel, so a source warning ("This is not an
      all-clear") is never hidden behind it and the address button stays in reach: a side panel (wide screens) starts below
      the rows it would cover, and a bottom sheet (phones) stops short of them. map.css reads --sheet-top. */
  function placeSheet(node) {
    node = node || el.sheet;
    node.style.removeProperty("--sheet-top");               // measured where the sheet sits by default
    var b = el.banners.getBoundingClientRect(), s = node.getBoundingClientRect();
    var f = el.find ? el.find.getBoundingClientRect() : null;
    var clash = b.height > 0 && b.right > s.left && b.left < s.right;
    var findClash = !!f && f.height > 0 && f.right > s.left && f.left < s.right;
    if (!clash && !findClash) return;
    var top = Math.max(clash ? b.bottom : 0, findClash ? f.bottom : 0);
    node.style.setProperty("--sheet-top", Math.ceil(top + 8) + "px");
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
      } else if (!repFailed) html += "<p>" + (PW.no_reports || "") + esc(reportsNoReport()) + "</p>";
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

  /** The tile's name as the build writes it: "r0079_c0199" for the tile that holds the cell. */
  function hailTileName(h, cell) {
    var t = h.grid.tile_cells;
    return "r" + pad4(Math.floor(cell.row / t)) + "_c" + pad4(Math.floor(cell.col / t));
  }

  /** Whether the store holds the tile at all. The build's compact split map (hail.tile_split, D40) gives each tile row's runs of
      tile columns, [first, last]; a tile with no run is not in the store, so it has no Montana cell. The tile is named as the
      build writes it ("r0079_c0199", hailTileName). */
  function hailListed(h, name) {
    var runs = own(h.tile_split, String(parseInt(name.slice(1, 5), 10))) || [], col = parseInt(name.slice(7, 11), 10);
    return runs.some(function (run) { return col >= run[0] && col <= run[1]; });
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
      the unit's scale (summary.units.in.scale, hundredths of an inch, D83(b)), over the build's tenths per inch, floored, shown
      with the unit's decimals. Rounding down never crosses a class edge, because every edge in tenths lies at or above its
      inch value, so a shown size keeps its class. A build without the unit fails with its placeholder (D16). */
  function hailInches(h, t) { var U = own(own(h.summary, "units"), "in"); if (!U || typeof U.scale !== "number" || typeof U.decimals !== "number") return missingKey("summary.units.in.scale"); return (Math.floor(t * U.scale / h.tenths_per_inch) / U.scale).toFixed(U.decimals); }
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
      show(slot("stale"), payload.stale);
      // B5 R11: the table and the sections fill their own slots when they load; the B1 lead, days, what, missing and source
      // lines are the Hail section's notes and rows (histModel), so the sheet shows each once (D79)
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
      hailShow(h, "loaded", text, null);                // the sample tag and the stale line at once; the table and the sections follow
      var tableP = sumTable(h, cell).then(function (res) { return res; }, function () { return null; });   // B5: the five-season table
      var joinsP = joinSections(h, cell);               // never rejects: a part that fails says so in its own section
      tableP.then(function (res) { if (current()) sumRender(el.sheetBody.querySelector('[data-hail="summary"]'), res); });
      Promise.all([tableP, joinsP]).then(function (both) {   // B5 R11: the eleven sections under the table, in the fixed order
        if (!current()) return;
        var slot = el.sheetBody.querySelector('[data-hail="sections"]');
        try { histRender(slot, histModel(h, cell, both[0], both[1], text)); }
        catch (e) {                                       // the sections that could not be built say so; the table and the rest stand (D16)
          if (window.console) console.error("summary sections", e);
          histRender(slot, { notices: [fill(h.words.unavailable, { problem: sumWord(h.summary, "table_problem") })], sections: [] });
        }
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
      town page for one cell say the same words. The build writes the record files (hail/j per tile, hail/j/e per tile for
      the events they refer to, hail/z per zone and per fire weather zone, hail/k per county, hail/s per station), the
      templates (hail.joins.words), the shard templates, the radii and the earth radius, the counts the lines say, the lags
      and each part's state. The browser does these steps and no others: the tile's file and its events file (one fetch
      each, kept for the page); the forecast zone's, the zone before the switch's, the fire weather zone's, the county's and
      each station file the tile names; the distance from the cell's centre in miles; the filters (reports and records
      within the report radius, detections within the detection radius, the warnings whose cover bit is set for the cell's
      key, the zone and county products and the station days in the window); the station picks at the cell's centre (the
      rule of joins.station_picks: the two nearest within the station radius, nearest first); the newest-first order; the
      Montana-time text (Intl, the zone named by data.tz); and the fill of the templates. A part the build marks
      unavailable, or whose file does not load, shows its own unavailable sentence and nothing else; a partial part keeps
      its lead and rows. It writes no sentence, unit, radius or threshold of its own: tests/test_site.py runs this block
      under node and compares it with describe_joins. */
  var JOIN_PARTS = ["reports", "records", "detections", "warnings", "zones", "stations"];
  var joinFmts = null;                        // the Montana-time formatters, made on first use
  // the fields of a row of the events table (hail/j/e/<tile>.json: the rows joins.py reads, the same shapes): a report's
  // type word is at 11; a record's mph, kt and cause are at 11, 12 and 13
  var JROW = { day: 0, hhmm: 1, lat: 2, lon: 3, code: 4, mag: 5, unit: 6, qual: 7, source: 8, city: 9, remark: 10, type: 11,
    mph: 11, kt: 12, cause: 13 };
  var JDET = { day: 0, hhmm: 1, lat: 2, lon: 3, size: 4 };
  var JDAY = { day: 0, mph: 1, kt: 2, flag: 3 };
  // the stop words of a zone event (joins.ZONE_STOP_WORDS): the suffix key and the "at" key of each stop state
  var JZONE_STOP = { cancelled: ["zones_cancelled", "zones_cancelled_at"], upgraded: ["zones_upgraded", "zones_upgraded_at"] };

  /** A key of a map.json object when the object holds it as its own; undefined otherwise. */
  function own(obj, key) { return obj && Object.prototype.hasOwnProperty.call(obj, key) ? obj[key] : undefined; }
  function has(v) { return v !== null && v !== undefined; }
  /** The placeholder for a words key the build does not write yet: it names the key, so the gap shows on the page. */
  function missingKey(key) { return "[missing words key: " + key + "]"; }
  /** Python's round() to a whole number: half to even (joins._warning_text rounds the wind tag so). */
  function roundEven(x) {
    var f = Math.floor(x), twice = 2 * (x - f);
    if (twice > 1) return f + 1;
    if (twice < 1) return f;
    return f % 2 === 0 ? f : f + 1;
  }
  /** Digits with a comma every three places, as Python's {n:,} writes them. */
  function thousands(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

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

  /** The clock text of an instant in Montana time, from the build's time template (hour, minute, am or pm, zone). */
  function joinClock(J, ms) {
    var p = {};
    joinFormats().clock.formatToParts(new Date(ms)).forEach(function (x) { p[x.type] = x.value; });
    return fill(J.words.time, { hour: p.hour, minute: p.minute, ampm: p.dayPeriod === "AM" ? J.words.am : J.words.pm,
      zone: p.timeZoneName });
  }

  /** The end of a span (joins.fmt_end): "end not recorded" when there is none; the clock alone on the begin's day, else
      with its date. Without a begin (null), the date is always written. */
  function joinEnd(J, ms, begin) {
    if (ms === null) return J.words.zones_end_unset;
    if (begin !== null && joinDay(ms) === joinDay(begin)) return joinClock(J, ms);
    return joinDay(ms) + " " + joinClock(J, ms);
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

  /** The station picks at a point (joins.station_picks, D36): the two nearest candidates within the station radius, nearest
      first, ties by id. The candidates are the tile's station_candidates when the file has them, else its stations list.
      The miles are shown to one decimal place. */
  function joinPicks(J, tile, lat, lon) {
    var cands = has(tile.station_candidates) ? tile.station_candidates : (tile.stations || []);
    var list = cands.map(function (s) { return { s: s, miles: joinMiles(J, lat, lon, s.lat, s.lon) }; });
    list.sort(function (a, b) {
      if (a.miles !== b.miles) return a.miles - b.miles;
      return a.s.id < b.s.id ? -1 : a.s.id > b.s.id ? 1 : 0;
    });
    var out = [];
    for (var i = 0; i < list.length && out.length < 2; i++) {
      if (list[i].miles > J.radius_miles.station) break;
      out.push({ id: list[i].s.id, name: list[i].s.name, lat: list[i].s.lat, lon: list[i].s.lon,
        miles: Number(list[i].miles.toFixed(1)) });
    }
    return out;
  }

  /** The magnitude of a row (joins._magnitude): knots with their miles per hour beside them, or the magnitude in its
      unit; no number reads the build's "no size given" words. */
  function joinMagnitude(J, text, unit, mph, kt) {
    var W = J.words;
    if (unit === "kt" && has(kt)) return fill(W.magnitude_kt_mph, { value: kt, mph: mph });
    if (unit === "kt" && text) return fill(W.magnitude_kt, { value: text });
    if (unit === J.hail_unit && text) return fill(W.magnitude_in, { value: Number(text).toFixed(2) });
    if (unit === "mph" && text) return fill(W.magnitude_mph, { value: text });
    return W.magnitude_none;
  }

  /** The qualifier part of a row (" (word)"), or "" when the code has no word (joins._qualifier). */
  function joinQualifier(J, code) {
    var word = has(code) ? (own(J.qualifiers, code) || own(J.ncei_qualifiers, code) || "") : "";
    return word ? fill(J.words.qualifier_part, { qualifier: word }) : "";
  }

  /** The NCEI cause as written, its whitespace collapsed (joins._record_text); "" when there is none. */
  function joinCause(v) {
    if (!v) return "";
    return String(v).split(/\s+/).filter(function (s) { return s.length > 0; }).join(" ");
  }

  /** The text of a report row (joins._report_text): the type word the row carries (or the store's type word for its code),
      the magnitude when the code has a unit, the qualifier, the source, the distance and the bearing (none for a spot at the
      centre). A code with no unit shows its type word and qualifier only (D9, D19). */
  function joinReportText(J, r, ms, miles, bearing) {
    var W = J.words, code = r[JROW.code], typed = J.unit_codes.indexOf(code) < 0, here = bearing === null;
    var base = { date: joinDay(ms), time: joinClock(J, ms),
      type: r[JROW.type] || own(J.types, code) || String(code).toLowerCase(),
      qualifier: joinQualifier(J, r[JROW.qual]), source: r[JROW.source], miles: miles.toFixed(1) };
    if (!typed) base.magnitude = joinMagnitude(J, r[JROW.mag], r[JROW.unit], null, null);
    if (!here) base.bearing = bearing;
    var key = here ? (typed ? "reports_row_here_typed" : "reports_row_here") : (typed ? "reports_row_typed" : "reports_row");
    return fill(W[key], base);
  }

  /** The text of a record row (joins._record_text): the label of a record, the magnitude when its type carries a unit, the
      qualifier, the NCEI cause, the source, the distance and the bearing. */
  function joinRecordText(J, r, ms, miles, bearing) {
    var W = J.words, code = r[JROW.code], typed = J.unit_codes.indexOf(code) < 0, here = bearing === null;
    var cause = joinCause(r[JROW.cause]);
    var base = { date: joinDay(ms), time: joinClock(J, ms), type: code, qualifier: joinQualifier(J, r[JROW.qual]),
      source: r[JROW.source], miles: miles.toFixed(1), cause: cause ? fill(W.records_cause, { cause: cause }) : "" };
    if (!typed) base.magnitude = joinMagnitude(J, r[JROW.mag], r[JROW.unit], r[JROW.mph], r[JROW.kt]);
    if (!here) base.bearing = bearing;
    var key = here ? (typed ? "records_row_here_typed_b5" : "records_row_here_b5") :
      (typed ? "records_row_typed_b5" : "records_row_b5");
    return fill(W[key], base);
  }

  /** The text of a zone-coded record row (joins._zone_record_text): the same words for the whole zone. */
  function joinZoneRecordText(J, r, ms, zone) {
    var W = J.words, code = r[JROW.code], typed = J.unit_codes.indexOf(code) < 0;
    var base = { date: joinDay(ms), time: joinClock(J, ms), type: code, qualifier: joinQualifier(J, r[JROW.qual]),
      source: r[JROW.source], zone: zone, cause: "" };
    if (!typed) base.magnitude = joinMagnitude(J, r[JROW.mag], r[JROW.unit], r[JROW.mph], r[JROW.kt]);
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

  /** The zone code whose cell keys include a key, in the tile's map of field ("zones", "zones_before", "fire" or
      "counties": {code: [keys]}); undefined when none does (joins._zone_for_key). */
  function joinZoneOf(j, field, key) {
    var zones = j[field] || {}, codes = Object.keys(zones);
    for (var i = 0; i < codes.length; i++) { if (zones[codes[i]].indexOf(key) >= 0) return codes[i]; }
    return undefined;
  }

  /** The heading of a section: the zone's name and code for the zone products (zones_heading, or the no-zone heading), else
      the section's own heading. */
  function joinHeading(W, k, zoneName, zone) {
    if (k !== "zones") return W[k + "_heading"];
    return zone ? fill(W.zones_heading, { zone_name: zoneName, zone: zone }) : W.zones_heading_no_zone;
  }

  /** The events of one tile (hail/j/e/<tile>.json, format J.events_tiles_format): a file in any other format is a failed
      load, and the sections it feeds say so. */
  function joinEvents(J, url) {
    return hailTile(url).then(function (doc) {
      if (doc.f !== J.events_tiles_format) throw hailFailure("format", url);
      return doc;
    });
  }

  /** A zone, county or station file as the sheet reads it (joins._read_part_file, D27): the row lists are arrays, and the
      format tag is the one the build writes (when the block carries it). A file in that shape is a failed load. */
  function joinFile(fmt) {
    return function (url) {
      return hailTile(url).then(function (doc) {
        if (["events", "records", "days"].some(function (k) { return doc[k] !== undefined && !Array.isArray(doc[k]); })) {
          throw hailFailure("format", url);
        }
        if (fmt && doc.f !== fmt) throw hailFailure("format", url);
        return doc;
      });
    };
  }

  /** The files one cell needs: the tile's events file and its record file (one fetch each), then the forecast zone's, the zone
      before the switch's, the fire weather zone's, the county's and each station file the picks name. Resolves with
      {j, events, zoneCode, zone, zoneBeforeCode, zoneBefore, fireCode, fire, countyCode, county, picks, sdocs}; a part that
      fails holds its error (.error). The tile's own failure is the whole result's error. Never rejects. */
  function joinLoad(h, cell) {
    var J = h.joins, key = hailKey(h, cell), name = hailTileName(h, cell), spot = hailCentre(h.grid, cell);
    var part = function (load, url) {
      return load(url).then(function (doc) { return { doc: doc }; }, function (e) { return { error: e }; });
    };
    var fmts = J.formats || {};
    return part(function (url) { return joinEvents(J, url); }, fill(J.events_tiles, { tile: name })).then(function (ev) {
      return part(hailTile, fill(J.shards.j, { tile: name })).then(function (got) {
        if (got.error) return { error: got.error };
        var j = got.doc, zoneCode = joinZoneOf(j, "zones", key), zbCode = joinZoneOf(j, "zones_before", key);
        var fireCode = joinZoneOf(j, "fire", key), countyCode = joinZoneOf(j, "counties", key);
        var picks = joinPicks(J, j, spot.lat, spot.lon);
        var zoneOf = function (code) { return part(joinFile(fmts.zone), fill(J.shards.z, { zone: code })); };
        var needZone = parts("zones") !== "unavailable" || parts("records") !== "unavailable";
        return Promise.all([
          zoneCode && needZone ? zoneOf(zoneCode) : null,
          zbCode && zbCode !== zoneCode && needZone ? zoneOf(zbCode) : null,
          fireCode && parts("zones") !== "unavailable" ? part(joinFile(fmts.zone), fill(J.shards.fire, { zone: fireCode })) : null,
          countyCode && parts("zones") !== "unavailable" ? part(joinFile(fmts.county), fill(h.county.tile, { county: countyCode })) : null,
          parts("stations") !== "unavailable" ? Promise.all(picks.map(function (st) {
            return part(joinFile(fmts.station), fill(J.shards.s, { station: st.id }));
          })) : []
        ]).then(function (all) {
          return { j: j, events: ev.doc || null, eventsError: ev.error || null, zoneCode: zoneCode, zone: all[0],
            zoneBeforeCode: zbCode, zoneBefore: all[1], fireCode: fireCode, fire: all[2], countyCode: countyCode,
            county: all[3], picks: picks, sdocs: all[4] };
        });
      });
    });
    /** The part's state (the build's parts block; loaded when it says nothing else). */
    function parts(k) { return J.parts[k] === "unavailable" ? "unavailable" : J.parts[k] === "partial" ? "partial" : "loaded"; }
  }

  /** The six sections for one cell (never rejects): {reports, records, detections, warnings, zones, stations, times}; each
      section {id, heading, what, lead, fire_lead, rows, lines, unavailable}, and a row {text, remark}. A section that did not
      load says so in its unavailable sentence and shows nothing else, except a partial part, which keeps its lead and rows. */
  function joinSections(h, cell) {
    if (!h.joins || !h.joins.words) return Promise.resolve(null);
    var J = h.joins, W = J.words, key = hailKey(h, cell), spot = hailCentre(h.grid, cell);
    var lag = J.lags || {}, counts = J.counts || {};
    var parts = function (k) { return J.parts[k] === "unavailable" ? "unavailable" : J.parts[k] === "partial" ? "partial" : "loaded"; };
    var shell = function (k, heading) {
      return { id: k, heading: heading, what: [W[k + "_what"], W["source_" + k]].filter(Boolean).join(" "), lead: "",
        fire_lead: "", rows: [], lines: [], lineParts: [], unavailable: null };
    };
    // a line and the part it comes from (describe_joins' lines; the part decides the section the line is a note of, D82(d)):
    // the county and the fire zone lines are the zones section's lines, but they feed their own parts
    var addLine = function (sec, text, part) { sec.lines.push(text); sec.lineParts.push(part || sec.id); };
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
    var newestNcei = lag.ncei ? hailDate(lag.ncei) : (W.records_newest_unknown || missingKey("records_newest_unknown"));
    var joinFill = function (got) {
      var out = {};
      JOIN_PARTS.forEach(function (k) { out[k] = shell(k, joinHeading(W, k, null, null)); });
      var j = got.j, zoneCode = got.zoneCode, fireCode = got.fireCode, countyCode = got.countyCode;
      // the zone file error (D27): the zone's own file, then the zone before the switch's, which overrides it as in joins.py
      var zoneErr = null;
      if (got.zone && got.zone.error) zoneErr = got.zone.error;
      if (got.zoneBefore && got.zoneBefore.error) zoneErr = got.zoneBefore.error;
      var zdoc = got.zone && !got.zone.error ? got.zone.doc : {};
      var bdoc = got.zoneBefore && !got.zoneBefore.error ? got.zoneBefore.doc : {};
      var fdoc = got.fire && !got.fire.error ? got.fire.doc : {};
      var kdoc = got.county && !got.county.error ? got.county.doc : {};
      var fireErr = got.fire && got.fire.error ? got.fire.error : null, countyErr = got.county && got.county.error ? got.county.error : null;
      var iemSwitch = Date.parse(J.iem_switch || "");
      var iemZones = J.iem_outline_zones || [];
      if (zoneCode) out.zones.heading = joinHeading(W, "zones", J.zone_names[zoneCode] || zoneCode, zoneCode);
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

      // official records: the NCEI point rows within the report radius, then the zone's rows, then the rows of the zone that
      // held the cell before the switch (describe_joins "records", D44, D48)
      if (parts("records") === "unavailable" || !got.events) out.records.unavailable = joinUnavailable(J, "records");
      else {
        var rec = [];
        (j.records || []).forEach(function (ref) {
          var r = got.events.records[ref], miles = joinMiles(J, spot.lat, spot.lon, r[JROW.lat], r[JROW.lon]);
          if (miles <= J.radius_miles.report) rec.push({ ms: joinInstant(h, r[JROW.day], r[JROW.hhmm]), miles: miles, r: r, zone: null });
        });
        (zdoc.records || []).forEach(function (r) {
          rec.push({ ms: joinInstant(h, r[JROW.day], r[JROW.hhmm]), miles: null, r: r, zone: zoneCode });
        });
        if (got.zoneBeforeCode !== undefined && got.zoneBeforeCode !== zoneCode) {
          (bdoc.records || []).forEach(function (r) {
            var when = joinInstant(h, r[JROW.day], r[JROW.hhmm]);
            if (when < iemSwitch) rec.push({ ms: when, miles: null, r: r, zone: got.zoneBeforeCode });
          });
        }
        rec.sort(function (a, b) { return b.ms - a.ms; });
        out.records.lead = fill(W[rec.length === 1 ? "records_lead_one" : rec.length ? "records_lead_many" : "records_lead_none"],
          Object.assign({ n: rec.length, newest: newestNcei }, ftn));
        out.records.rows = rec.map(function (x) {
          if (x.zone !== null) {
            var zt = joinZoneRecordText(J, x.r, x.ms, x.zone);
            if (iemZones.indexOf(x.zone) >= 0 && x.ms < iemSwitch) zt += W.zones_simplified_suffix;
            return { text: zt, remark: "" };
          }
          var bearing = x.miles < J.here_miles ? null : joinCompass(J, spot.lat, spot.lon, x.r[JROW.lat], x.r[JROW.lon]);
          return { text: joinRecordText(J, x.r, x.ms, x.miles, bearing), remark: "" };
        });
        var floodCodes = J.flood_record_codes || [];
        var floodN = rec.filter(function (x) { return x.zone === null && floodCodes.indexOf(x.r[JROW.code]) >= 0; }).length;   // D48
        if (floodN) addLine(out.records, fill(W[floodN === 1 ? "flood_records_line_one" : "flood_records_line_many"], { n: floodN }));
        if (counts.ncei_zone_rows_unmatched) addLine(out.records, fill(W[counts.ncei_zone_rows_unmatched === 1 ? "records_unplaced_one" : "records_unplaced_many"],
          { n: counts.ncei_zone_rows_unmatched }));
        if (parts("records") === "partial") out.records.unavailable = joinUnavailable(J, "records", J.partial.records);
        if (zoneErr) out.records.unavailable = joinUnavailable(J, "records", [zoneCode], joinReason(W, zoneErr));   // D27
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
        addLine(out.detections, lag.swdi ? fill(W.detections_lag, { newest: hailDate(lag.swdi) }) : W.detections_lag_none);
        if (parts("detections") === "partial") out.detections.unavailable = joinUnavailable(J, "detections", J.partial.detections);
      }

      // warnings: the warnings whose cover has this cell's key, newest first (describe_joins "warnings")
      if (parts("warnings") === "unavailable" || !got.events) out.warnings.unavailable = joinUnavailable(J, "warnings");
      else {
        var wrn = [];
        (j.warnings || []).forEach(function (pair) {
          if (!joinCovers(pair[1], key)) return;
          var item = got.events.warnings[pair[0]];
          wrn.push({ b: Date.parse(item.b), e: item.e ? Date.parse(item.e) : null, w: item });
        });
        wrn.sort(function (a, b) { return b.b - a.b; });
        var noOutline = counts.warnings_no_outline || 0;
        out.warnings.lead = !wrn.length && noOutline ? W.warnings_lead_unknown
          : fill(W[wrn.length === 1 ? "warnings_lead_one" : wrn.length ? "warnings_lead_many" : "warnings_lead_none"],
            Object.assign({ n: wrn.length }, ftn));
        out.warnings.rows = wrn.map(function (x) { return { text: joinWarningText(J, x), remark: "" }; });
        addLine(out.warnings, lag.warnings ? fill(W.warnings_lag, { newest: hailDate(lag.warnings) }) : W.warnings_lag_none);
        if (noOutline) addLine(out.warnings, fill(W[noOutline === 1 ? "warnings_no_outline_one" : "warnings_no_outline_many"],
          { n: noOutline }));
        if (parts("warnings") === "partial") out.warnings.unavailable = joinUnavailable(J, "warnings", J.partial.warnings);
      }

      // zone products: the forecast zone's products (the zone before the switch's, for a removed zone or MTZ060, D44), the fire
      // weather zone's red flag warnings (D7, D17) and the county's products, windowed and ordered by their begin, or by their
      // end when the begin is not recorded (joins._zone_when)
      if (parts("zones") === "unavailable") out.zones.unavailable = joinUnavailable(J, "zones");
      else {
        var publicItems = [], redItems = [], countyItems = [], beforeItems = [];
        var fireName = J.fire_zone_names[fireCode] !== undefined ? J.fire_zone_names[fireCode] : fireCode;
        if (fireCode !== undefined && got.fire && !got.fire.error) fireName = fdoc.name || fireName;
        var spanOf = function (e) {
          var begin = e.b ? Date.parse(e.b) : null, endAt = e.e ? Date.parse(e.e) : null;
          return { begin: begin, end: endAt, when: begin !== null ? begin : endAt, st: e.st, ev: e };
        };
        (zdoc.events || []).forEach(function (e) {
          var s = spanOf(e);
          if (s.when === null || !within(s.when)) return;
          if (iemZones.indexOf(zoneCode) >= 0 && s.when < iemSwitch) beforeItems.push(withZone(s, zoneCode));
          else publicItems.push(s);
        });
        if (got.zoneBeforeCode !== undefined && got.zoneBeforeCode !== zoneCode) {
          (bdoc.events || []).forEach(function (e) {
            var s = spanOf(e);
            if (s.when !== null && within(s.when) && s.when < iemSwitch) beforeItems.push(withZone(s, got.zoneBeforeCode));
          });
        }
        (fdoc.events || []).forEach(function (e) { var s = spanOf(e); if (s.when !== null && within(s.when)) redItems.push(s); });
        (kdoc.events || []).forEach(function (e) { var s = spanOf(e); if (s.when !== null && within(s.when)) countyItems.push(s); });
        var zoneName = J.zone_names[zoneCode] !== undefined ? J.zone_names[zoneCode] : zoneCode;
        var leadN = publicItems.length + beforeItems.filter(function (x) { return x.code === zoneCode; }).length;   // D17, D44
        out.zones.lead = zoneCode === undefined ? W.zones_no_zone
          : fill(W[leadN === 1 ? "zones_lead_one" : leadN ? "zones_lead_many" : "zones_lead_none"],
            { n: leadN, zone_name: zoneName, zone: zoneCode, start: ftn.start, end: ftn.end });
        var grouped = {}, order = [];
        var addTo = function (map, name, item) { if (!map[name]) { map[name] = []; order.push(name); } map[name].push(item); };
        var nameOf = function (ev) { return own(J.products, ev.k + "." + ev.s) || (ev.k + "." + ev.s); };
        publicItems.forEach(function (x) { addTo(grouped, nameOf(x.ev), x); });
        redItems.forEach(function (x) {
          addTo(grouped, fill(W.fire_product, { product: nameOf(x.ev), zone_name: fireName, zone: fireCode }), x);
        });
        var groupKeys = Object.keys(grouped);
        var minWhen = function (list) { return list.reduce(function (m, x) { return x.when < m ? x.when : m; }, Infinity); };
        groupKeys.sort(function (a, b) { return minWhen(grouped[b]) - minWhen(grouped[a]); });
        groupKeys.forEach(function (name) {
          var texts = grouped[name].slice().sort(function (a, b) { return a.when - b.when; }).map(function (x) { return joinZoneSpan(J, x); });
          out.zones.rows.push({ text: fill(W.zones_row, { product: name, events: texts.join("; ") }), remark: "" });
        });
        // the cell's zone before the switch: its products, grouped by product and zone (D44)
        var beforeGroups = {}, beforeOrder = [], beforeCodes = {};
        beforeItems.forEach(function (x) {
          var name = nameOf(x.ev), gkey = JSON.stringify([name, x.code]);
          if (!beforeGroups[gkey]) { beforeGroups[gkey] = { name: name, code: x.code, items: [] }; beforeOrder.push(gkey); }
          beforeGroups[gkey].items.push(x);
          beforeCodes[x.code] = (beforeCodes[x.code] || 0) + 1;
        });
        beforeOrder.sort(function (a, b) { return minWhen(beforeGroups[b].items) - minWhen(beforeGroups[a].items); });
        beforeOrder.forEach(function (gkey) {
          var g = beforeGroups[gkey];
          var texts = g.items.slice().sort(function (a, b) { return a.when - b.when; }).map(function (x) { return joinZoneSpan(J, x); });
          out.zones.rows.push({ text: fill(W.zones_row_simplified, { product: g.name, zone_name: J.zone_names[g.code] !== undefined ? J.zone_names[g.code] : g.code,
            zone: g.code, note: W.zones_simplified, events: texts.join("; ") }), remark: "" });
        });
        Object.keys(beforeCodes).sort().forEach(function (bcode) {
          var n = beforeCodes[bcode];
          addLine(out.zones, fill(W[n === 1 ? "zones_before_line_one" : "zones_before_line_many"],
            { n: n, zone_name: J.zone_names[bcode] !== undefined ? J.zone_names[bcode] : bcode, zone: bcode }), "zones");
        });
        if (counts.zone_products_unplaced) addLine(out.zones, fill(W[counts.zone_products_unplaced === 1 ? "zones_unplaced_one" : "zones_unplaced_many"],
          { n: thousands(counts.zone_products_unplaced) }), "zones");
        if (countyCode !== undefined) {
          var countyName = own(h.county && h.county.short_names, countyCode);      // without the word County (the build's short_names)
          if (countyName === undefined) countyName = missingKey("county.short_names");
          if ((h.county && h.county.state) !== "loaded" || countyErr) addLine(out.zones, W.county_unavailable, "county");
          else {
            var ckw = { start: ftn.start, end: ftn.end, county_name: countyName, county: countyCode };
            addLine(out.zones, countyItems.length === 0 ? fill(W.county_lead_none, ckw)
              : fill(W[countyItems.length === 1 ? "county_lead_one" : "county_lead_many"], Object.assign({ n: countyItems.length }, ckw)), "county");
            var cgroups = {}, corder = [];
            countyItems.forEach(function (x) { addTo(cgroups, nameOf(x.ev), x); });
            Object.keys(cgroups).sort(function (a, b) { return minWhen(cgroups[b]) - minWhen(cgroups[a]); }).forEach(function (name) {
              var texts = cgroups[name].slice().sort(function (a, b) { return a.when - b.when; }).map(function (x) { return joinZoneSpan(J, x); });
              out.zones.rows.push({ text: fill(W.county_row, { product: name, county_name: countyName, events: texts.join("; ") }), remark: "" });
            });
          }
        }
        if (J.fire_state !== "loaded" || fireErr) addLine(out.zones, W.zones_fire_unavailable, "fire");
        else if (fireCode === undefined) addLine(out.zones, W.zones_fire_none, "fire");
        else out.zones.fire_lead = fill(W[redItems.length === 1 ? "fire_lead_one" : redItems.length ? "fire_lead_many" : "fire_lead_none"],
          { n: redItems.length, zone_name: fireName, zone: fireCode, start: ftn.start, end: ftn.end });
        if (parts("zones") === "partial") out.zones.unavailable = joinUnavailable(J, "zones", J.partial.zones);
        // the county line is written once, where the county part is read (D71: describe_joins writes it once too)
        if (zoneErr) {                                                  // D27: no lead, rows or lines from a zone file that did not load
          out.zones.lead = null; out.zones.fire_lead = null; out.zones.rows = []; out.zones.lines = []; out.zones.lineParts = [];
          out.zones.unavailable = joinUnavailable(J, "zones");
        }
      }

      // station gusts: the station days in the window, newest first, and the days each station's file dropped (describe_joins)
      var stationLost = got.sdocs.some(function (x) { return x && x.error; });     // a station file that did not load (D27)
      if (parts("stations") === "unavailable") out.stations.unavailable = joinUnavailable(J, "stations");
      else if (!got.picks.length) out.stations.lead = fill(W.stations_none_near, { miles: Math.floor(J.radius_miles.station) });
      else if (stationLost) out.stations.unavailable = joinUnavailable(J, "stations");
      else {
        var days = [], dropped = 0;
        got.picks.forEach(function (st, i) {
          var sdoc = got.sdocs[i] && !got.sdocs[i].error ? got.sdocs[i].doc : {};
          (sdoc.days || []).forEach(function (row) {
            var iso = hailIso(h, row[JDAY.day]);
            if (iso < J.window[0] || iso > J.window[1]) return;
            days.push({ iso: iso, mph: row[JDAY.mph], kt: row[JDAY.kt], flag: row.length > JDAY.flag ? row[JDAY.flag] : 0, st: st });
          });
          dropped += sdoc.dropped || 0;
        });
        days.sort(function (a, b) { return a.iso < b.iso ? 1 : a.iso > b.iso ? -1 : b.mph - a.mph; });
        out.stations.lead = fill(W[days.length === 1 ? "stations_lead_one" : days.length ? "stations_lead_many" : "stations_lead_none"],
          Object.assign({ n: days.length, kt_min: J.station_kt, mph_min: J.station_mph }, ftn));
        out.stations.rows = days.map(function (x) {
          return { text: fill(W.stations_row, { date: hailDate(x.iso), kt: Math.floor(x.kt), mph: Math.floor(x.mph),
            station: x.st.name, miles: Number(x.st.miles).toFixed(1) }) + (x.flag ? W.flag_suffix : ""), remark: "" };
        });
        if (days.some(function (x) { return x.flag; })) addLine(out.stations, W.flag_check_line);
        if (dropped) addLine(out.stations, fill(W[dropped === 1 ? "stations_dropped_one" : "stations_dropped"],
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

  /** A zone event's span with the zone code it belongs to (the zone before the switch's products keep their own code). */
  function withZone(span, code) { var out = {}; Object.keys(span).forEach(function (k) { out[k] = span[k]; }); out.code = code; return out; }

  /** One zone event's span in words (joins._zone_event_text, D6, D16, D26, D31): "{date} {begin} to {end}", "end not recorded"
      when there is none, "start not recorded; end {end}" when there is no begin, and ", cancelled" or ", upgraded" when a
      stop ended it. A stop at or before the begin reads "cancelled at {time}" or "upgraded at {time}" in place of the span. */
  function joinZoneSpan(J, x) {
    var W = J.words, keys = own(JZONE_STOP, x.st);
    if (keys && x.begin !== null && x.end !== null && x.end <= x.begin) return fill(W[keys[1]], { time: joinEnd(J, x.end, null) });
    var text;
    if (x.begin === null && x.end === null) text = W.zones_event_no_span;
    else if (x.begin === null) text = fill(W.zones_event_no_start, { end: joinEnd(J, x.end, null) });
    else text = fill(W.zones_event, { date: joinDay(x.begin), begin: joinClock(J, x.begin), end: joinEnd(J, x.end, x.begin) });
    return text + (keys ? W[keys[0]] : "");
  }

  /** One warning row (joins._warning_text, B5 D41): the significance label, the Montana date and span, the product's own
      kind word, the office and the tags the archive gives. */
  function joinWarningText(J, x) {
    var W = J.words, tg = x.w.tags || {}, tags = [];
    if (has(tg.hail_in)) tags.push(fill(W.tag_hail, { value: Number(tg.hail_in).toFixed(2) }));
    if (has(tg.wind_mph)) tags.push(fill(W.tag_wind, { value: String(roundEven(tg.wind_mph)) }));
    if (tg.tornado) tags.push(fill(W.tag_tornado, { value: String(tg.tornado).toLowerCase() }));
    if (tg.damage) tags.push(fill(W.tag_damage, { value: String(tg.damage).toLowerCase() }));
    var code = x.w.k + "." + x.w.s;
    var ends = joinDay(x.e) === joinDay(x.b) ? "" : joinDay(x.e) + " ";     // the end's date only on a later Montana day
    var span = x.e === null ? fill(W.warnings_span, { begin: joinClock(J, x.b), end: W.zones_end_unset })
      : fill(W.warnings_span, { begin: joinClock(J, x.b), end: ends + joinClock(J, x.e), });
    return fill(W.warnings_row_b5, {
      label: own(J.significance, x.w.s) || missingKey("significance"),
      date: joinDay(x.b), span: span,
      product: own(J.kind_words, code) || own(J.products, code) || code, office: x.w.o,
      tags: tags.length ? tags.join(", ") : W.warnings_tags_none });
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
    if (!f) main = wordFill("no_layer_picture", { layer: layerWord(state.layer).toLowerCase() });
    else if (f._failed) main = "The " + clock(state.times[state.pos]) + " picture didn\u2019t load. This is not an all-clear.";
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

  // ------------------------------------------------------------------ five seasons at a spot (B5, the sheet's table and sections)

  /** The five-season table and the sections the sheet shows at a cell, computed here from the per-tile files, with the
      rules of website/summary.py describe_summary and the words of map.json "summary" (the browser holds no word, unit or
      threshold of its own). Each function names the Python function it mirrors. The table's cells are {value, date, text,
      valid, missing, flag, unknown, coverage}: value an integer (or null), date yyyymmdd (or null), text the words, valid
      the days with a value, missing the days missing (never counted as zero), coverage the line the page shows under it. */

  var SUM_SEASONS = [];                      // the five season labels, set from h.summary.seasons on first use

  /** A UTC day number (days since 1970) of an ISO date, and the ISO date of a day number. */
  function sumDayNum(iso) { return Date.parse(iso) / HAIL_DAY_MS; }
  function sumIsoOf(n) { return new Date(n * HAIL_DAY_MS).toISOString().slice(0, 10); }

  /** The season label of an ISO date, "2021-22": the season that began on summary.rule.season's first day (S.rule.season, the
      build's own rule, D87(d)); stations.season_of is the same rule. The rule is the summary's, passed in, so a build without it
      throws here and the part that needs the season shows its D20 sentence (D16). */
  function sumSeasonOf(S, iso) {
    var R = own(own(S, "rule"), "season");
    if (!R || typeof R.start_month !== "number" || typeof R.start_day !== "number") throw new Error("summary.rule.season");
    var y = Number(iso.slice(0, 4)), m = Number(iso.slice(5, 7)), d = Number(iso.slice(8, 10));
    var began = m > R.start_month || (m === R.start_month && d >= R.start_day);
    var sy = began ? y : y - 1;
    return sy + "-" + String(sy + 1).slice(2);
  }

  /** The first and last day numbers of a season label (summary.season_bounds: the rule's first and last days, S.rule.season). */
  function sumBounds(S, label) {
    var R = own(own(S, "rule"), "season");
    if (!R || typeof R.start_month !== "number" || typeof R.end_month !== "number") throw new Error("summary.rule.season");
    var y = Number(label.slice(0, 4)), two = function (n) { return ("0" + n).slice(-2); };
    return { start: sumDayNum(y + "-" + two(R.start_month) + "-" + two(R.start_day)),
      end: sumDayNum((y + 1) + "-" + two(R.end_month) + "-" + two(R.end_day)) };
  }

  /** The Montana calendar day of an instant, as an ISO date (joins._local(utc).date()). */
  function sumMontanaIso(ms) {
    if (!sumIsoFmt) {
      sumIsoFmt = new Intl.DateTimeFormat("en-US", { timeZone: data.tz, year: "numeric", month: "2-digit", day: "2-digit" });
    }
    var p = {};
    sumIsoFmt.formatToParts(new Date(ms)).forEach(function (x) { p[x.type] = x.value; });
    return p.year + "-" + p.month + "-" + p.day;
  }
  var sumIsoFmt = null;

  /** "Jul 24, 2022" for an ISO date (hail.fmt_date). */
  function sumFmtDate(iso) { return hailDate(iso); }

  /** The words of the summary, with the check that a key the page needs is present (a missing key shows its placeholder). */
  function sumWord(S, key) {
    var v = own(S.words, key);
    return v === undefined || v === null ? missingKey(key) : v;
  }


  /** A words key of the stations block (stations.words), or its placeholder when the build does not write it. */
  function stWord(h, key) { var v = own(h.stations.words, key); return v === undefined ? missingKey(key) : v; }

  /** summary._join_names: "A", "A and B", "A, B and C" (the list words of the summary, never a literal here). */
  function sumJoinNames(S, names) {
    var list = names.filter(function (n) { return n; });
    if (list.length <= 1) return list.join("");
    return fill(sumWord(S, "list_last"), { head: list.slice(0, -1).join(", "), last: list[list.length - 1] });
  }

  /** The type word of a report key (summary.REPORT_TYPES, the build's report_types); a missing key shows its placeholder. */
  function sumReportType(S, key) {
    var type = own(S.report_types, key);
    return type === undefined ? missingKey("report_types") : type;
  }

  /** summary._no_report for a report key: the key's type word, in the period's words. */
  function sumNoReport(S, key, when) {
    return fill(sumWord(S, "no_report"), { type: sumReportType(S, key), when: when });
  }

  /** The noun of a count of a key: the singular for one, else the plural (summary.NOUNS, the build's nouns). */
  function sumNoun(S, key, n) {
    var pair = own(S.nouns, key);
    return pair === undefined ? missingKey("nouns") : pair[n === 1 ? 0 : 1];
  }

  /** The decimal places a unit shows (summary.UNIT_SPEC, the build's units). A build without them fails the part that needs them. */
  function sumDecimals(S, unit) {
    var spec = own(S.units, unit);
    if (spec === undefined || typeof spec.decimals !== "number") throw new Error("summary.units." + unit + ".decimals");
    return spec.decimals;
  }
  /** The store's integers per whole unit (summary.units.in.scale: hundredths of an inch; summary.units.F.scale: tenths of a degree F),
      from map.json (D83(b)). A build without them fails the part that needs them (D16). */
  function sumScale(S, unit) {
    var spec = own(S.units, unit);
    if (spec === undefined || typeof spec.scale !== "number") throw new Error("summary.units." + unit + ".scale");
    return spec.scale;
  }
  /** The decimals of a station's inches (stations.fmt_in: one decimal, summary.units.in.station_decimals in map.json). */
  function sumStationDecimals(S) {
    var spec = own(S.units, "in");
    if (spec === undefined || typeof spec.station_decimals !== "number") throw new Error("summary.units.in.station_decimals");
    return spec.station_decimals;
  }
  /** The season rule in the store's own integers (D83(b)): summary.rule.season_min (0.95) times the percent scale of summary.rule.percent,
      as a whole number (95 of 100). Throws when either is not written, so the part that needs the rule fails with its D20 sentence (D16). */
  function sumSeasonRule(S) {
    var P = sumPercent(S);
    if (!P) throw new Error("summary.rule.percent");
    if (!S.rule || typeof S.rule.season_min !== "number") throw new Error("summary.rule.season_min");
    return { scale: P.scale, share: Math.round(S.rule.season_min * P.scale) };
  }

  /** summary._clear: the line with the all-clear sentence at its end, added once when the line lacks it (D41). */
  function sumClear(S, text) {
    var allClear = sumWord(S, "all_clear"), t = String(text).replace(/\s+$/, "");
    if (t.slice(-allClear.length) === allClear) return t;
    return (t.charAt(t.length - 1) === "." ? t : t + ".") + " " + allClear;
  }

  /** summary._flag_clause: a zone statement without its all-clear sentence and its full stop (D98(b)). The statement is the word
      the build gives (sumZoneFlag); a coverage line joins its clauses and adds the sentence once, at its end (D29, D41). */
  function sumFlagClause(S, flag) {
    return histWithoutClear(S, flag).replace(/\s+$/, "").replace(/\.+$/, "").replace(/\s+$/, "");
  }

  /** summary._joined_flags: the distinct zone statements of the cells, in season order, as clauses; null when there are none. */
  function sumJoinedFlags(S, cells) {
    var seen = [];
    cells.forEach(function (c) {
      if (!c.flag) return;
      var clause = sumFlagClause(S, c.flag);
      if (seen.indexOf(clause) < 0) seen.push(clause);
    });
    return seen.length ? seen.join("; ") : null;
  }

  /** summary._cover: the coverage line, the days missing (when there are any) and a zone's statement (its clauses; the line ends
      with the all-clear sentence once, D41). null when there is neither. */
  function sumCover(S, missing, flag) {
    if (flag) {
      var parts = (missing ? [sumMissingText(S, missing)] : []).concat([sumFlagClause(S, flag)]);
      return sumClear(S, parts.join("; ") + ".");
    }
    return missing ? sumMissingText(S, missing) : null;
  }

  /** summary._missing_text: "1 day missing", "1,108 days missing" (the count with its thousands separator, as _thousands writes it). */
  function sumMissingText(S, n) {
    return n === 1 ? sumWord(S, "coverage_one") : fill(sumWord(S, "coverage"), { n: thousands(n) });
  }

  /** summary._cell: one season's figure. */
  function sumCell(S, o) {
    var missing = o.missing || 0, flag = o.flag || null;
    return { value: o.value === undefined ? null : o.value, date: o.date === undefined ? null : o.date,
      text: o.text === undefined ? null : o.text, valid: o.valid || 0, missing: missing, station: o.station || null,
      flag: flag, unknown: !!o.unknown, coverage: sumCover(S, missing, flag) };
  }

  /** summary._unavailable_cell: a season with no figure and the cell's words (never a zero). */
  function sumUnavailableCell(S, text) { return sumCell(S, { text: text || sumWord(S, "cell_unavailable") }); }

  /** summary._count_text: "1 hail report", "3 hail reports", "2 days", "1,020 days"; a zero report or record count reads as its
      no-report or no-record sentence for the period (D41). */
  function sumCountText(S, key, n, when) {
    if (when === undefined) when = sumWord(S, "these_five");      // summary._count_text's default period
    if (key === "days") return fill(sumWord(S, n === 1 ? "day_one" : "days"), { n: thousands(n) });
    var reportKey = ["hail_max", "hail_n", "wind_n", "freezing_rain_n", "flood_report_n"].indexOf(key) >= 0;
    if (n === 0 && reportKey) {
      if (S.report_types === undefined || S.report_types[key] === undefined) return missingKey("report_types");
      return fill(sumWord(S, "no_report"), { type: S.report_types[key], when: when });
    }
    if (n === 0 && key === "flood_record_n") {
      if (S.record_types === undefined || S.record_types[key] === undefined) return missingKey("record_types");
      return fill(sumWord(S, "no_record"), { type: S.record_types[key], when: when });
    }
    if (S.nouns === undefined || S.nouns[key] === undefined) return missingKey("nouns");
    return thousands(n) + " " + sumNoun(S, key, n);
  }

  /** A store integer as its figure with the unit's decimals (summary._in_text and climate._tenths_f_text): the scale and the decimals
      are map.json's summary.units (D83(b)), so "in" 205 reads "2.05" and "F" -3 reads "-0.3". */
  function sumFixed(S, unit, value) {
    var scale = sumScale(S, unit), dec = sumDecimals(S, unit), a = Math.abs(value);
    var whole = String(Math.floor(a / scale)), frac = String(a % scale);
    while (frac.length < dec) frac = "0" + frac;
    return (value < 0 ? "-" : "") + whole + (dec > 0 ? "." + frac : "");
  }
  /** summary._fmt_in_on: hundredths of an inch with its date when it has one: "1.25 in on Jun 15, 2025". */
  function sumInText(S, hund) { return sumFixed(S, "in", hund); }
  function sumInOn(S, hund, iso) {
    if (iso) return fill(sumWord(S, "in_on"), { inches: sumInText(S, hund), date: sumFmtDate(iso) });
    return fill(sumWord(S, "in_plain"), { inches: sumInText(S, hund) });
  }

  /** summary._five: the five-season figure from the five season cells. "sum": every season must have a valid day and a value,
      else the five-season sentence (a total never leaves a season out). "max" or "min": the extreme of the seasons that have
      one, with its own season text; the earliest season wins a tie. none when no season has one. */
  function sumFive(S, cells, combine, fmt, none) {
    var missing = cells.reduce(function (s, c) { return s + c.missing; }, 0);
    var coverage = sumCover(S, missing, sumJoinedFlags(S, cells));
    var unknown = [];
    cells.forEach(function (c, k) { if (c.unknown) unknown.push(SUM_SEASONS[k]); });
    if (unknown.length) return { value: null, date: null, text: sumWord(S, "cell_unavailable"), coverage: coverage, note: sumFiveUnavailable(S, unknown) };
    if (combine === "sum") {
      var bad = [];
      cells.forEach(function (c, k) { if (c.valid <= 0 || c.value === null) bad.push(SUM_SEASONS[k]); });
      if (bad.length) return { value: null, date: null, text: sumWord(S, "cell_unavailable"), coverage: coverage, note: sumFiveUnavailable(S, bad) };
      var total = cells.reduce(function (s, c) { return s + c.value; }, 0);
      return { value: total, date: null, text: fmt ? fmt(total) : String(total), coverage: coverage, note: null };
    }
    var present = cells.filter(function (c) { return c.value !== null; });
    if (!present.length) return { value: null, date: null, text: none, coverage: coverage, note: null };
    var best = present.reduce(function (m, c) { return combine === "max" ? Math.max(m, c.value) : Math.min(m, c.value); }, present[0].value);
    // the season that holds the best value: a dated season before an undated one, then the earliest date (summary's min key)
    var candidates = present.filter(function (c) { return c.value === best; }), pick = candidates[0];
    candidates.forEach(function (c) { if (sumEarlier(c, pick)) pick = c; });
    return { value: best, date: pick.date, text: pick.text, coverage: coverage, note: null };
  }

  /** The order summary._five's min key gives two season cells: a dated cell first, then the earlier date. */
  function sumEarlier(a, b) {
    var ua = a.date === null ? 1 : 0, ub = b.date === null ? 1 : 0;
    if (ua !== ub) return ua < ub;
    return (a.date || 0) < (b.date || 0);
  }

  /** summary._five_unavailable_text: the five-season sentence for the seasons that have no usable value. */
  function sumFiveUnavailable(S, bad) {
    if (bad.length === SUM_SEASONS.length) return sumWord(S, "five_unavailable_all");
    return fill(sumWord(S, "five_unavailable"), { season: bad.join(", "), verb: bad.length === 1 ? "has" : "have" });
  }

  /** summary._row: a table row with its five season cells, its five-season figure and its notes. */
  function sumRow(S, spec, cells, five, notes) {
    var out = { key: spec.key, label: spec.label, kind: spec.kind, unit: spec.unit, scale: spec.scale,
      decimals: spec.decimals, source: spec.source, town_only: !!spec.town_only,
      values: cells.map(function (c) { return c.value; }), dates: cells.map(function (c) { return c.date; }),
      texts: cells.map(function (c) { return c.text; }), coverage: cells.map(function (c) { return c.coverage; }),
      stations: cells.map(function (c) { return c.station; }), five: five.value, five_date: five.date,
      five_text: five.text, five_coverage: five.coverage, five_note: five.note || null,
      notes: notes.filter(function (n) { return n; }), five_missing: cells.reduce(function (s, c) { return s + c.missing; }, 0) };
    if (five.note) out.notes.push(five.note);
    return out;
  }

  /** summary._unavailable_row: a row whose part did not load (D16): no figure in any season and the part's sentence as its note. */
  function sumUnavailableRow(S, spec, sentence) {
    var cells = SUM_SEASONS.map(function () { return sumUnavailableCell(S); });
    var five = { value: null, date: null, text: sumWord(S, "cell_unavailable"), coverage: null, note: null };
    return sumRow(S, spec, cells, five, [sentence]);
  }

  /** The spec of a table row (summary.ROWS, as map.json "summary" rows carry it). */
  function sumSpec(S, key) {
    for (var i = 0; i < S.rows.length; i++) { if (S.rows[i].key === key) return S.rows[i]; }
    return null;
  }

  /** A spot's frame: the cell's centre, its key and tile, the store's window, its as-of day and its missing days. */
  function sumSpot(h, cell) {
    var c = hailCentre(h.grid, cell);
    var missing = {};
    (h.missing_days || []).forEach(function (d) { missing[d] = true; });
    return { row: cell.row, col: cell.col, lat: c.lat, lon: c.lon, key: hailKey(h, cell), tile: hailTileName(h, cell),
      first: h.window[0], last: h.window[1], asOf: h.as_of, missing: missing };
  }

  /** summary._Spot.in_window and season_cover: the days of a season, the days of it in the window and the valid days. The
      store's missing days are subtracted only when withMissing (the radar rows ask for them; the report rows do not). */
  function sumInWindow(sp, iso) { return iso >= sp.first && iso <= sp.last; }
  function sumCoverOf(S, sp, label, withMissing) {
    var b = sumBounds(S, label), lo = Math.max(b.start, sumDayNum(sp.first)), hi = Math.min(b.end, sumDayNum(sp.last));
    var total = b.end - b.start + 1, store = hi >= lo ? hi - lo + 1 : 0, miss = 0;
    if (withMissing) {
      Object.keys(sp.missing).forEach(function (d) {
        if (sumSeasonOf(S, d) === label && sumInWindow(sp, d)) miss += 1;
      });
    }
    return { total: total, store: store, valid: store - miss };
  }

  /** summary._radar_rows (B1): the largest radar estimate of each season with its date, and the days of 1 inch or more; the
      radar rows read the cell's days from hail/t (the B1 shard) and count each day once (D35). The class note sits under the
      one-inch row. */
  function sumRadarRows(h, sp, S, days) {
    var bySeason = {};
    SUM_SEASONS.forEach(function (lab) { bySeason[lab] = {}; });
    days.forEach(function (x) {
      var label = sumSeasonOf(S, x.iso);
      if (bySeason[label] !== undefined && sumInWindow(sp, x.iso)) {
        bySeason[label][x.iso] = Math.max(bySeason[label][x.iso] === undefined ? 0 : bySeason[label][x.iso], x.t);
      }
    });
    var floor = h.floor_tenths, one = S.rule.one_inch_tenths;
    var rule = sumSeasonRule(S);                    // D37: a season is full at 95 percent of its days (the rule's own integers)
    var maxCells = [], oneCells = [], seasonNotes = [], shortMax = [], shortOne = [];
    SUM_SEASONS.forEach(function (label) {
      var cov = sumCoverOf(S, sp, label, true), missing = cov.total - cov.valid;
      if (cov.valid <= 0) {
        maxCells.push(sumUnavailableCell(S));
        oneCells.push(sumUnavailableCell(S));
        seasonNotes.push(fill(sumWord(S, "season_unavailable"), { season: label, source: sumWord(S, "source_radar_history") }));
        shortMax.push(label); shortOne.push(label);
        return;
      }
      var vals = bySeason[label], isos = Object.keys(vals);
      var full = cov.valid * rule.scale >= cov.total * rule.share;          // a zero or "No radar estimate" shows only when full
      var short = fill(sumWord(S, "radar_season_short"), { season: label, k: thousands(cov.valid), d: thousands(cov.total) });
      var big = isos.filter(function (iso) { return vals[iso] >= floor; });
      if (big.length) {
        var bestIso = big[0];                       // the largest value; on a tie the earliest day (summary's max key)
        big.forEach(function (iso) {
          if (vals[iso] > vals[bestIso] || (vals[iso] === vals[bestIso] && iso < bestIso)) bestIso = iso;
        });
        var hund = Math.floor(sumScale(S, "in") * vals[bestIso] / h.tenths_per_inch);
        maxCells.push(sumCell(S, { value: hund, text: sumInOn(S, hund, bestIso), date: Number(bestIso.replace(/-/g, "")),
          valid: cov.valid, missing: missing }));
      } else if (full) {
        maxCells.push(sumCell(S, { value: null, text: sumWord(S, "none_radar"), valid: cov.valid, missing: missing }));
      } else {                                      // a partial season with no figure says Data unavailable and its days (D37, D82(c))
        maxCells.push(sumCell(S, { value: null, text: short, valid: cov.valid, missing: missing }));
        shortMax.push(label);
      }
      var nOne = isos.filter(function (iso) { return vals[iso] >= one; }).length;
      if (nOne || full) oneCells.push(sumCell(S, { value: nOne, text: sumCountText(S, "days", nOne), valid: cov.valid, missing: missing }));
      else { oneCells.push(sumCell(S, { value: null, text: short, valid: cov.valid, missing: missing })); shortOne.push(label); }
    });
    // summary._radar_rows: the five-season largest is Data unavailable (with the seasons named) when a season below 95 percent has no figure
    var fiveMax = sumFive(S, maxCells, "max", null, shortMax.length ? sumWord(S, "cell_unavailable") : sumWord(S, "none_radar"));
    if (fiveMax.value === null && shortMax.length) fiveMax.note = sumFiveUnavailable(S, shortMax);
    var fiveOne = sumFive(S, oneCells, "sum", function (v) { return sumCountText(S, "days", v); }, "");
    var classNote = sumClassNote(h, S, bySeason);
    var notes = seasonNotes.concat([fill(sumWord(S, "window_radar"), { first: sumFmtDate(sp.first), last: sumFmtDate(sp.last),
      as_of: sumFmtDate(sp.asOf), season: SUM_SEASONS[0] })]);
    return {
      radar_max: sumRow(S, sumSpec(S, "radar_max"), maxCells, fiveMax, notes),
      radar_1in: sumRow(S, sumSpec(S, "radar_1in"), oneCells, fiveOne, classNote ? [classNote] : [])
    };
  }

  /** summary._class_note: the radar days by size class over the five seasons (the store's classes), or null when no day
      has an estimate of 0.25 in or more. */
  function sumClassNote(h, S, bySeason) {
    var counts = {};
    SUM_SEASONS.forEach(function (label) {
      Object.keys(bySeason[label]).forEach(function (iso) {
        var t = bySeason[label][iso];
        if (t >= h.floor_tenths) { var c = hailClass(h, t); counts[c.word] = (counts[c.word] || 0) + 1; }
      });
    });
    var items = [];
    h.classes.forEach(function (cls) {
      var n = counts[cls.word] || 0;
      if (!n) return;
      var dec = sumDecimals(S, "in"), span = cls.max_in === null ? fill(sumWord(S, "class_open"), { min: cls.min_in.toFixed(dec) })
        : fill(sumWord(S, "class_range"), { min: cls.min_in.toFixed(dec), max: cls.max_in.toFixed(dec) });
      items.push(fill(sumWord(S, "class_item"), { count: sumCountText(S, "days", n), word: cls.word, span: span }));
    });
    return items.length ? fill(sumWord(S, "class_counts"), { items: items.join("; ") }) : null;
  }

  /** The montana-time event rows of one tile's joins (summary._Spot.lsr_within, records_within): the reports within the
      report radius of the cell's centre, with the Montana day, the code, the type word, the magnitude and unit, the
      distance in miles (rounded to two places) and the source. */
  function sumReports(h, sp, events, j) {
    var J = h.joins, out = [];
    (j.reports || []).forEach(function (ref) {
      var r = events.reports[ref], miles = joinMiles(J, sp.lat, sp.lon, r[JROW.lat], r[JROW.lon]);
      if (miles > J.radius_miles.report) return;
      out.push({ day: sumMontanaIso(joinInstant(h, r[JROW.day], r[JROW.hhmm])), code: r[JROW.code], mag: r[JROW.mag],
        unit: r[JROW.unit], kind: r[JROW.type] !== undefined ? r[JROW.type] : r[JROW.code], miles: Number(miles.toFixed(2)),
        src: r[JROW.source] });
    });
    return out;
  }
  function sumRecords(h, sp, events, j) {
    var J = h.joins, out = [];
    (j.records || []).forEach(function (ref) {
      var r = events.records[ref], miles = joinMiles(J, sp.lat, sp.lon, r[JROW.lat], r[JROW.lon]);
      if (miles <= J.radius_miles.report) out.push({ day: sumMontanaIso(joinInstant(h, r[JROW.day], r[JROW.hhmm])), code: r[JROW.code] });
    });
    return out;
  }

  /** summary._lsr_cells: the per-season cells of the report rows (hail largest and count, wind, freezing rain, flood). */
  function sumReportCells(h, sp, S, lsr) {
    var picks = {
      hail_n: function (r) { return r.code === "H"; },
      wind_n: function (r) { return S.rule.wind_codes.indexOf(r.code) >= 0; },
      freezing_rain_n: function (r) { return r.kind === "freezing rain"; },
      flood_report_n: function (r) { return r.kind === "flood" || r.kind === "flash flood"; }
    };
    var out = { hail_max: [], hail_n: [], wind_n: [], freezing_rain_n: [], flood_report_n: [] };
    SUM_SEASONS.forEach(function (label) {
      var cov = sumCoverOf(S, sp, label, false), missing = cov.total - cov.valid;
      Object.keys(picks).forEach(function (key) {
        if (cov.valid <= 0) { out[key].push(sumUnavailableCell(S, fill(sumWord(S, "season_unavailable"), { season: label, source: sumWord(S, "source_report_archive") }))); return; }
        var n = lsr.filter(function (r) { return picks[key](r) && sumSeasonOf(S, r.day) === label && sumInWindow(sp, r.day); }).length;
        out[key].push(sumCell(S, { value: n, text: sumCountText(S, key, n, label), valid: cov.valid, missing: missing }));
      });
      if (cov.valid <= 0) { out.hail_max.push(sumUnavailableCell(S, fill(sumWord(S, "season_unavailable"), { season: label, source: sumWord(S, "source_report_archive") }))); return; }
      var best = null;
      lsr.forEach(function (r) {
        if (r.code !== "H" || r.unit !== h.joins.hail_unit || sumSeasonOf(S, r.day) !== label || !sumInWindow(sp, r.day)) return;
        var hund = sumHundredths(S, r.mag);
        if (hund === null) return;
        if (best === null || hund > best.hund || (hund === best.hund && r.day < best.day)) best = { hund: hund, day: r.day };
      });
      if (best === null) out.hail_max.push(sumCell(S, { value: null, text: sumNoReport(S, "hail_max", label), valid: cov.valid, missing: missing }));
      else out.hail_max.push(sumCell(S, { value: best.hund, text: sumInOn(S, best.hund, best.day), date: Number(best.day.replace(/-/g, "")), valid: cov.valid, missing: missing }));
    });
    return out;
  }

  /** summary._hundredths_from_decimal: an LSR magnitude as written ("1.25") to hundredths of an inch, rounding half up; null when
      it is not a number. */
  function sumHundredths(S, text) {
    var scale = sumScale(S, "in"), dec = sumDecimals(S, "in");
    var m = /^\s*(\d+)(?:\.(\d+))?\s*$/.exec(String(text === null || text === undefined ? "" : text));
    if (!m) return null;
    var frac = m[2] || "", digits = frac.slice(0, dec);
    while (digits.length < dec) digits += "0";
    var hund = Number(m[1]) * scale + Number(digits);
    if (frac.length > dec && Number(frac.charAt(dec)) >= 5) hund += 1;      // half up at the unit's last place (Decimal, ROUND_HALF_UP)
    return hund;
  }

  /** summary._reports_rows: the report rows (hail largest and count, wind, freezing rain, flood), with the automated count
      of the hail and wind rows and its note. */
  function sumReportRows(h, sp, S, state, reason, periods, events, j) {
    var keys = ["hail_max", "hail_n", "wind_n", "freezing_rain_n", "flood_report_n"];
    var J = h.joins;
    if (state === "unavailable" || !events) {
      var sentence = sumClear(S, joinUnavailable(J, "reports", null, null));
      return keys.reduce(function (o, k) { o[k] = sumUnavailableRow(S, sumSpec(S, k), sentence); return o; }, {});
    }
    var lsr = sumReports(h, sp, events, j);
    var note = state === "partial" ? sumClear(S, joinUnavailable(J, "reports", periods, reason)) : null;
    var cells = sumReportCells(h, sp, S, lsr);
    var out = {};
    var fiveMax = sumFive(S, cells.hail_max, "max", null, sumNoReport(S, "hail_max", sumWord(S, "these_five")));
    out.hail_max = sumRow(S, sumSpec(S, "hail_max"), cells.hail_max, fiveMax, note ? [note] : []);
    var inFive = function (r) { return SUM_SEASONS.indexOf(sumSeasonOf(S, r.day)) >= 0 && sumInWindow(sp, r.day); };
    var picks = {
      hail_n: function (r) { return r.code === "H"; },
      wind_n: function (r) { return S.rule.wind_codes.indexOf(r.code) >= 0; }
    };
    [["hail_n", NOUNS_PLURAL(S, "hail_n")], ["wind_n", NOUNS_PLURAL(S, "wind_n")]].forEach(function (pair) {
      var key = pair[0], autoList = S.auto_sources || [];
      var automated = S.auto_sources === undefined ? 0 : lsr.filter(function (r) { return picks[key](r) && inFive(r) && autoList.indexOf(r.src) >= 0; }).length;
      var extra = note ? [note] : [];
      if (S.auto_sources === undefined) extra.push(missingKey("auto_sources"));
      if (automated) extra.push(sumAutomated(S, automated, pair[1]));
      var five = sumFive(S, cells[key], "sum", function (v) { return sumCountText(S, key, v); }, "");
      out[key] = sumRow(S, sumSpec(S, key), cells[key], five, extra);
      out[key].automated = automated;
    });
    ["freezing_rain_n", "flood_report_n"].forEach(function (key) {
      var five = sumFive(S, cells[key], "sum", function (v) { return sumCountText(S, key, v); }, "");
      out[key] = sumRow(S, sumSpec(S, key), cells[key], five, note ? [note] : []);
    });
    return out;
  }
  function NOUNS_PLURAL(S, key) { return S.nouns === undefined || S.nouns[key] === undefined ? missingKey("nouns") : S.nouns[key][1]; }

  /** summary._automated_sentence. */
  function sumAutomated(S, n, kind) {
    return n === 1 ? fill(sumWord(S, "automated_one"), { kind: kind }) : fill(sumWord(S, "automated_note"), { n: n, kind: kind });
  }

  /** summary._records_row (D48): the NCEI flood and flash flood records within 5 miles, a row of its own. */
  function sumRecordsRow(h, sp, S, state, reason, periods, events, j) {
    var J = h.joins, spec = sumSpec(S, "flood_record_n");
    if (state === "unavailable" || !events || !j) {
      var why = !events ? J.words.reason_events : !j ? J.words.reason_no_answer : reason;
      return sumUnavailableRow(S, spec, sumClear(S, joinUnavailable(J, "records", null, why)));
    }
    var note = state === "partial" ? sumClear(S, joinUnavailable(J, "records", periods, reason)) : null;
    var days = sumRecords(h, sp, events, j).filter(function (r) { return J.flood_record_codes.indexOf(r.code) >= 0; }).map(function (r) { return r.day; });
    var cells = SUM_SEASONS.map(function (label) {
      var cov = sumCoverOf(S, sp, label, false);
      if (cov.valid <= 0) return sumUnavailableCell(S, fill(sumWord(S, "season_unavailable"), { season: label, source: sumWord(S, "source_record_archive") }));
      var n = days.filter(function (d) { return sumSeasonOf(S, d) === label && sumInWindow(sp, d); }).length;
      return sumCell(S, { value: n, text: sumCountText(S, "flood_record_n", n, label), valid: cov.valid, missing: cov.total - cov.valid });
    });
    var five = sumFive(S, cells, "sum", function (v) { return sumCountText(S, "flood_record_n", v); }, "");
    return sumRow(S, spec, cells, five, note ? [note] : []);
  }

  /** The files the table reads at a cell: the radar tile (hail/t), the joins record tile (hail/j) and its events (hail/j/e);
      then the zone, county and climate files the cell names; then the tile list (hail/tl, D36), the station files it names
      for snowfall and deepest snow, and the gust file of the joined records' station. Each part holds its error or null; a
      part that fails is said so by its rows. Never rejects. */
  function sumLoad(h, cell) {
    var J = h.joins, name = hailTileName(h, cell), sp = sumSpot(h, cell);
    var part = function (url, load) { return (load || hailTile)(url).then(function (doc) { return { doc: doc }; }, function (e) { return { error: e }; }); };
    return Promise.all([
      part(hailShardUrl(h, cell)),
      part(fill(J.shards.j, { tile: name })),
      part(fill(J.events_tiles, { tile: name }), function (url) { return joinEvents(J, url); })
    ]).then(function (all) {
      var jdoc = all[1].doc || null, key = sp.key;
      var zc = jdoc ? joinZoneOf(jdoc, "zones", key) : undefined;
      var cc = jdoc ? joinZoneOf(jdoc, "counties", key) : undefined;
      var clim = sumClimateCellRecord(h, sp);
      var zoneP = zc !== undefined ? part(fill(J.shards.z, { zone: zc }), joinFile(J.formats && J.formats.zone)) : Promise.resolve({});
      var countyP = cc !== undefined && h.county ? part(fill(h.county.tile, { county: cc }), joinFile(J.formats && J.formats.county)) : Promise.resolve({});
      var climP = clim.status === "pending" ? part(fill(h.climate.tile, { tile: clim.tile }), hailTile) : Promise.resolve({});
      var tlPath = own(h.summary, "tile_list");          // the build's path and format of the tile lists (D36, D62)
      var tlP = tlPath === undefined ? Promise.resolve({}) : part(fill(tlPath, { tile: name }));
      var picks = jdoc ? joinPicks(J, jdoc, sp.lat, sp.lon) : [];
      var gustP = picks.length ? part(fill(J.shards.s, { station: picks[0].id })) : Promise.resolve({});
      return Promise.all([zoneP, countyP, climP, tlP, gustP]).then(function (more) {
        var tl = more[3].doc && more[3].doc.f === own(h.summary, "tile_list_format") ? more[3].doc : null;
        var ids = {};
        ["SNOW", "SNWD"].forEach(function (el) {
          var block = tl ? own(tl.elements, el) : undefined;
          var got = block && tl.margin_miles !== undefined ? sumTilePicks(J, block, sp.lat, sp.lon, h.stations.radius_miles) : null;
          if (got) got.picks.forEach(function (p) { ids[p.id] = true; });
        });
        var sdKeys = Object.keys(ids);
        return Promise.all(sdKeys.map(function (id) { return part(fill(h.stations.tile, { station: id })); })).then(function (sdAll) {
          var sd = {};
          sdKeys.forEach(function (id, k) { sd[id] = sdAll[k].doc || null; });
          return { t: all[0], j: all[1], events: all[2], zoneDoc: more[0].doc || null, countyDoc: more[1].doc || null,
            clim: clim, climDoc: more[2].doc || null, tileDoc: tl, sd: sd, gustDoc: more[4].doc || null };
        });
      });
    });
  }

  /** The table's context: the words and rules of h.summary (with the exports the page needs from the build), the spot, the
      store's days, the tile's records, the tile list and the station files. */
  function sumContext(h, cell, loaded) {
    var S = Object.assign({}, h.summary);
    S.nouns = own(h.summary, "nouns");                 // undefined when the build does not write the key: a placeholder shows
    S.report_types = own(h.summary, "report_types");
    S.record_types = own(h.summary, "record_types");
    S.auto_sources = own(h.summary, "auto_sources");
    S.element_names = own(h.summary, "element_names");
    S.family_nouns = own(h.summary, "family_nouns");
    SUM_SEASONS = h.summary.seasons;
    S.canada = own(h.stations, "canada_reason");                 // the Canada reason of an unread station (stations.CANADA_REASON)
    S.unplaced_products = own(h.summary, "unplaced_products");   // product code to family (summary.UNPLACED_FAMILIES)
    S.unplaced = sumUnplacedIndex(h, S);                         // family|season to the unplaced count; null when the rows are not written
    var sp = sumSpot(h, cell);
    var J = h.joins, parts = function (k) { return J.parts[k] === "unavailable" ? "unavailable" : J.parts[k] === "partial" ? "partial" : "loaded"; };
    var reasons = function (k) { return (J.reasons && J.reasons[k]) || J.words.reason_no_answer; };
    var periods = function (k) { return (J.partial && J.partial[k]) || []; };
    var tdoc = loaded.t.error ? null : loaded.t.doc;
    var days = [];
    if (tdoc) {
      var rows = (tdoc.cells && tdoc.cells[String(sp.key)]) || [];
      rows.forEach(function (pair) { days.push({ iso: hailIso(h, pair[0]), t: pair[1] }); });
    }
    var jdoc = loaded.j.error ? null : loaded.j.doc;
    var events = loaded.events.error ? null : loaded.events.doc;
    var climRec = loaded.clim.status !== "pending" ? { status: loaded.clim.status } : null;
    if (!climRec) {
      var cdoc = loaded.climDoc, key = loaded.clim.key;
      if (!cdoc || !cdoc.cells) climRec = { status: "outside" };
      else if (cdoc.state && cdoc.state.indexOf(key) < 0) climRec = { status: "outside" };
      else if (!cdoc.cells[String(key)]) climRec = { status: "no_land" };
      else climRec = { status: "ok", record: cdoc.cells[String(key)] };
    }
    return { S: S, sp: sp, h: h, days: days, tileOk: !!tdoc, jdoc: jdoc, events: events, parts: parts, reasons: reasons,
      periods: periods, zoneDoc: loaded.zoneDoc, countyDoc: loaded.countyDoc, climRec: climRec, tileDoc: loaded.tileDoc,
      sd: loaded.sd, gustDoc: loaded.gustDoc };
  }

  /** The table's rows, by key, in the row order of map.json summary.row_order (the town-only rows are not on the sheet). Each part is
      built on its own: a part that throws (a key the build does not write, a file of the wrong shape) gives its rows the D20 sentence
      and the console the error, and the rest of the table stands (D16). */
  function sumRows(ctx) {
    var h = ctx.h, S = ctx.S, sp = ctx.sp, out = {};
    var part = function (name, keys, build) {
      var got;
      try { got = build(); }
      catch (e) {
        if (window.console) console.error("summary part", name, e);
        got = {};
        var sentence = sumClear(S, fill(h.words.unavailable, { problem: sumWord(S, "table_problem") }));
        keys.forEach(function (k) { got[k] = sumUnavailableRow(S, sumSpec(S, k), sentence); });
      }
      Object.keys(got).forEach(function (k) { out[k] = got[k]; });
    };
    part("radar", ["radar_max", "radar_1in"], function () {
      var radar = ctx.tileOk ? sumRadarRows(h, sp, S, ctx.days) : null;
      if (radar) return radar;
      var rs = sumClear(S, fill(h.words.unavailable, { problem: sumWord(S, "radar_problem") }));
      return { radar_max: sumUnavailableRow(S, sumSpec(S, "radar_max"), rs), radar_1in: sumUnavailableRow(S, sumSpec(S, "radar_1in"), rs) };
    });
    part("reports", ["hail_max", "hail_n", "wind_n", "freezing_rain_n", "flood_report_n"], function () {
      return sumReportRows(h, sp, S, ctx.parts("reports"), ctx.reasons("reports"), ctx.periods("reports"), ctx.events, ctx.jdoc);
    });
    part("gust", ["gust_days", "gust_max"], function () {
      var got = sumGustRows(ctx);
      // summary.py: when the stations part loaded for some station-years only (D20 partial), the sentence that names the
      // station-years that did not load is the last note of both gust rows (the wind section then carries it once)
      if (ctx.jdoc && ctx.parts("stations") === "partial") {
        var missed = sumClear(S, joinUnavailable(h.joins, "stations", ctx.periods("stations"), ctx.reasons("stations")));
        ["gust_days", "gust_max"].forEach(function (k) { if (got[k] && got[k].notes) got[k].notes.push(missed); });
      }
      return got;
    });
    part("records", ["flood_record_n"], function () {
      return { flood_record_n: sumRecordsRow(h, sp, S, ctx.parts("records"), ctx.reasons("records"), ctx.periods("records"), ctx.events, ctx.jdoc) };
    });
    part("warnings", ["flood_warn"], function () { return { flood_warn: sumWarningRow(ctx) }; });
    part("county", ["county_watch"], function () { return { county_watch: sumCountyRow(ctx) }; });
    part("zones", ["hw_zone", "ice_warn"], function () { return sumZoneRows(ctx); });
    part("climate", ["tmax", "tmin", "hot90", "frost32", "freeze_thaw", "precip", "precip_max"], function () { return sumClimateRows(ctx, ctx.climRec); });
    part("stations", ["snow", "snow_depth"], function () {
      return { snow: sumStationRow(ctx, "snow", "SNOW", "sum"), snow_depth: sumStationRow(ctx, "snow_depth", "SNWD", "max") };
    });
    part("held", ["held"], function () { return { held: sumHeldRow(S) }; });
    return out;
  }

  /** The table of a cell: the rows, the partial line and the context, as {rows, partial, ctx}. The partial line is built on its own: a
      failure there gives its D20 sentence and leaves the rows (D16). */
  function sumTable(h, cell) {
    return sumLoad(h, cell).then(function (loaded) {
      var ctx = sumContext(h, cell, loaded), partial;
      try { partial = sumPartialRow(ctx); }
      catch (e) {
        if (window.console) console.error("summary part", "partial", e);
        partial = { label: h.summary.partial, text: sumClear(ctx.S, fill(h.words.unavailable, { problem: sumWord(ctx.S, "table_problem") })) };
      }
      return { rows: sumRows(ctx), partial: partial, ctx: ctx };
    });
  }
  /** climate.climate_cell_for: the 1/48-degree grid cell (i, j) that holds a point, in exact whole millionths of a degree
      (the half-open rule: latitude (south edge, north edge], longitude [west edge, east edge)); null off the grid. */
  function sumClimateCell(h, lat, lon) {
    var g = h.climate.grid, U = g.units_per_degree;
    var latM = Math.round(lat * HAIL_MICRO) * U, lonM = Math.round(lon * HAIL_MICRO) * U;   // millionths times 48
    var i = Math.ceil((latM - g.lat_edge_units * HAIL_MICRO) / (2 * HAIL_MICRO));
    var j = Math.floor((lonM + g.lon_edge_units * HAIL_MICRO) / (2 * HAIL_MICRO));
    return i >= 0 && i < g.rows && j >= 0 && j < g.cols ? { i: i, j: j } : null;
  }

  /** climate.climate_tile: the B1 tile and in-tile key of the B1 cell that holds a climate cell's centre. */
  function sumClimateTile(h, i, j) {
    var g = h.climate.grid, U = g.units_per_degree;
    var lat = (g.lat_centre_units[0] + g.lat_centre_units[1] * i) / U;
    var lon = (g.lon_centre_units[0] + g.lon_centre_units[1] * j) / U;
    var cell = hailCell(h.grid, hailPoint(lat, lon));
    return cell ? { tile: hailTileName(h, cell), key: hailKey(h, cell) } : null;
  }

  /** summary._Spot.climate_cell: ("ok", the cell's record {s: six season records}), ("no_land", null), ("outside", null), or
      ("unavailable", the reason). */
  function sumClimateCellRecord(h, sp) {
    var cb = h.climate;
    if (!cb || cb.state === "unavailable") return { status: "unavailable", problem: (cb && cb.problem) || null };
    var cell = sumClimateCell(h, sp.lat, sp.lon);
    if (!cell) return { status: "outside" };
    var t = sumClimateTile(h, cell.i, cell.j);
    if (!t) return { status: "outside" };
    return { status: "pending", tile: t.tile, key: t.key };
  }

  /** climate.py's 13 fields of a season record, read as summary._clim_cells reads them. */
  function sumClimRecordRow(r) {
    var days = r[0], missing = r[1];
    return { valid: days - missing, missing: missing,
      tmax: { value: r[5], date: r[6] }, tmin: { value: r[7], date: r[8] }, hot90: r[9], freeze_thaw: r[11], below32: r[12],
      rain: r[2], rain_max: { value: r[3], date: r[4] } };
  }

  /** summary._clim_cells: one season's grid figures from its record (highest and lowest temperature with dates, the day
      counts, the precipitation and the largest one-day precipitation with its date). */
  function sumClimCells(S, label, r) {
    var days = r[0], missing = r[1], valid = days - missing;
    var keys = ["tmax", "tmin", "hot90", "frost32", "freeze_thaw", "precip", "precip_max"];
    if (valid <= 0) {
      return keys.reduce(function (o, k) { o[k] = sumUnavailableCell(S, fill(sumWord(S, "season_unavailable"), { season: label, source: "grid" })); return o; }, {});
    }
    var o = {};
    o.tmax = sumCell(S, { value: r[5], text: r[5] !== null ? sumFmtF(S, r[5], r[6]) : null, date: r[6], valid: valid, missing: missing });
    o.tmin = sumCell(S, { value: r[7], text: r[7] !== null ? sumFmtF(S, r[7], r[8]) : null, date: r[8], valid: valid, missing: missing });
    [["hot90", 9], ["frost32", 12], ["freeze_thaw", 11]].forEach(function (pair) {
      var v = r[pair[1]];
      o[pair[0]] = sumCell(S, { value: v, text: v !== null ? sumCountText(S, "days", v) : null, valid: valid, missing: missing });
    });
    o.precip = sumCell(S, { value: r[2], text: r[2] !== null ? fill(sumWord(S, "in_plain"), { inches: sumInText(S, r[2]) }) : null, valid: valid, missing: missing });
    o.precip_max = sumCell(S, { value: r[3], text: r[3] !== null ? sumInOn(S, r[3], sumIsoFromYmd(r[4])) : null, date: r[4], valid: valid, missing: missing });
    return o;
  }

  /** "2021-07-30" from a yyyymmdd number (null for null). */
  function sumIsoFromYmd(v) {
    if (v === null || v === undefined) return null;
    var s = String(v);
    return s.slice(0, 4) + "-" + s.slice(4, 6) + "-" + s.slice(6, 8);
  }

  /** summary._fmt_f_on: a temperature in tenths of a degree F with its date: "102.9 F on Jul 20, 2021". The text of the
      tenths follows climate._tenths_f_text (a sign, the whole degrees, a full stop, the tenth). */
  function sumTenthsF(S, t) { return sumFixed(S, "F", t); }
  function sumFmtF(S, t, date) {
    var text = sumTenthsF(S, t);
    return date ? fill(sumWord(S, "f_on"), { f: text, date: sumFmtDate(sumIsoFromYmd(date)) }) : fill(sumWord(S, "f_plain"), { f: text });
  }

  /** summary._climate_part: the grid rows (highest and lowest temperature with dates, the day counts, precipitation and the
      largest one-day precipitation). Five seasons: each season's cells, then the five-season figure from them.
      An unavailable grid names each row's own part (D41): the precipitation rows say rain, the others temperature
      (summary.TEMP_KEYS). */
  function sumClimateRows(ctx, rec) {
    var h = ctx.h, S = ctx.S, sp = ctx.sp, keys = ["tmax", "tmin", "hot90", "frost32", "freeze_thaw", "precip", "precip_max"];
    var rainKeys = ["precip", "precip_max"];
    var out = {};
    if (rec.status === "unavailable") {
      keys.forEach(function (k) {
        var rain = rainKeys.indexOf(k) >= 0;
        var words = { part: sumWord(S, rain ? "rain_part" : "temperature_part"),
          part_lower: sumWord(S, rain ? "rain_part_lower" : "temperature_part_lower") };
        out[k] = sumUnavailableRow(S, sumSpec(S, k), sumClear(S, fill(h.climate.templates.unavailable, words)));
      });
      return out;
    }
    if (rec.status !== "ok") {
      var sentence = sumClear(S, rec.status === "no_land" ? h.climate.templates.no_land : h.climate.templates.not_in_store);
      keys.forEach(function (k) { out[k] = sumUnavailableRow(S, sumSpec(S, k), sentence); });
      return out;
    }
    var per = {};
    keys.forEach(function (k) { per[k] = []; });
    SUM_SEASONS.forEach(function (label, k) {
      var cells = sumClimCells(S, label, rec.record.s[k]);
      keys.forEach(function (key) { per[key].push(cells[key]); });
    });
    var gridNotes = [h.climate.templates.cell_sentence];
    if (h.climate.through) gridNotes.push(fill(sumWord(S, "window_grid"), { through: sumFmtDate(h.climate.through) }));
    var combine = { tmax: "max", tmin: "min", precip_max: "max" };
    var fmtSum = {
      hot90: function (v) { return sumCountText(S, "days", v); }, frost32: function (v) { return sumCountText(S, "days", v); },
      freeze_thaw: function (v) { return sumCountText(S, "days", v); },
      precip: function (v) { return fill(sumWord(S, "in_plain"), { inches: sumInText(S, v) }); }
    };
    keys.forEach(function (key) {
      var five = sumFive(S, per[key], combine[key] || "sum", fmtSum[key] || null, sumWord(S, "cell_unavailable"));
      var notes = key === "tmax" || key === "precip" ? gridNotes.slice() : [];
      out[key] = sumRow(S, sumSpec(S, key), per[key], five, notes);
    });
    return out;
  }

  /** summary._warning_rows (the flood and flash flood warnings, polygon covers of the cell, D11). */
  function sumWarningRow(ctx, reportsOk) {
    var h = ctx.h, S = ctx.S, sp = ctx.sp, J = h.joins, spec = sumSpec(S, "flood_warn");
    var state = ctx.parts("warnings"), reason = ctx.reasons("warnings"), periods = ctx.periods("warnings");
    if (state === "unavailable" || !ctx.events || !ctx.jdoc) return sumUnavailableRow(S, spec, sumClear(S, joinUnavailable(J, "warnings", null, reason)));
    var note = state === "partial" ? sumClear(S, joinUnavailable(J, "warnings", periods, reason)) : null;
    var days = [];
    (ctx.jdoc.warnings || []).forEach(function (pair) {
      if (!joinCovers(pair[1], sp.key)) return;
      var item = ctx.events.warnings[pair[0]];
      if (["FF", "FL", "FA"].indexOf(item.k) >= 0 && item.s === "W") days.push(sumMontanaIso(Date.parse(item.b)));
    });
    var cells = sumCountCells(ctx, days, "flood_warn");
    var five = sumFive(S, cells, "sum", function (v) { return sumCountText(S, "flood_warn", v); }, "");
    return sumRow(S, spec, cells, five, note ? [note] : []);
  }

  /** summary._count_cells: one count per season from the days of its items (Montana time), with the window coverage. */
  function sumCountCells(ctx, days, key) {
    var S = ctx.S, sp = ctx.sp;
    return SUM_SEASONS.map(function (label) {
      var cov = sumCoverOf(S, sp, label, false);
      if (cov.valid <= 0) return sumUnavailableCell(S, fill(sumWord(S, "season_unavailable"), { season: label, source: sumWord(S, "source_record_archive") }));
      var n = days.filter(function (d) { return sumSeasonOf(S, d) === label && sumInWindow(sp, d); }).length;
      return sumCell(S, { value: n, text: sumCountText(S, key, n, label), valid: cov.valid, missing: cov.total - cov.valid });
    });
  }

  /** summary._county_rows: the county-only flood and flash flood watches for the cell's county (k/ file, loaded with the table). */
  function sumCountyRow(ctx) {
    var h = ctx.h, S = ctx.S, sp = ctx.sp, spec = sumSpec(S, "county_watch");
    var unavailable = sumUnavailableRow(S, spec, h.joins.words.county_unavailable);
    var code = ctx.jdoc ? joinZoneOf(ctx.jdoc, "counties", sp.key) : undefined;
    if (!h.county || h.county.state !== "loaded" || !ctx.jdoc || code === undefined || !ctx.countyDoc) return unavailable;
    var days = (ctx.countyDoc.events || []).filter(function (ev) { return ev.k === "FA" || ev.k === "FF"; })
      .filter(function (ev) { return ev.s === "A" && ev.b; }).map(function (ev) { return sumMontanaIso(Date.parse(ev.b)); });
    var cells = sumCountCells(ctx, days, "county_watch");
    var five = sumFive(S, cells, "sum", function (v) { return sumCountText(S, "county_watch", v); }, "");
    var county = own(h.county.short_names, code);       // the county's name without the word County, as the build writes it
    if (county === undefined) county = missingKey("county.short_names");
    var word = sdGet(S, "words.county_word");         // summary._county_rows: the name ends with the word County (added when it does not)
    var named = String(county).slice(-(" " + word).length) === " " + word ? county : county + " " + word;
    return sumRow(S, spec, cells, five, [fill(sumWord(S, "county_note"), { county: named })]);
  }

  /** summary._zone_rows: high wind watches and warnings, and winter storm and ice storm warnings, for the cell's forecast
      zone (the zone's products, the whole zone). The unplaced products of a family mark their seasons (B5 D27). */
  function sumZoneRows(ctx) {
    var h = ctx.h, S = ctx.S, sp = ctx.sp, J = h.joins, out = {};
    var state = ctx.parts("zones"), reason = ctx.reasons("zones"), periods = ctx.periods("zones");
    var zoneCode = ctx.jdoc ? joinZoneOf(ctx.jdoc, "zones", sp.key) : undefined;
    if (state === "unavailable" || !ctx.jdoc) {
      var sentence = sumClear(S, joinUnavailable(J, "zones", null, reason));
      return { hw_zone: sumUnavailableRow(S, sumSpec(S, "hw_zone"), sentence), ice_warn: sumUnavailableRow(S, sumSpec(S, "ice_warn"), sentence) };
    }
    if (S.unplaced === null) {                                   // the build does not write the unplaced rows: the rows cannot say
      var noRows = sumClear(S, missingKey("zone_unplaced_rows"));
      return { hw_zone: sumUnavailableRow(S, sumSpec(S, "hw_zone"), noRows), ice_warn: sumUnavailableRow(S, sumSpec(S, "ice_warn"), noRows) };
    }
    var partialNote = state === "partial" ? sumClear(S, joinUnavailable(J, "zones", periods, reason)) : null;
    var zdoc = ctx.zoneDoc;
    [["hw_zone", ["HW"], ["W", "A"], "high_wind"], ["ice_warn", ["WS", "IS"], ["W"], "winter_storm"]].forEach(function (t) {
      var key = t[0], kinds = t[1], sigs = t[2], family = t[3];
      if (zoneCode === undefined || !zdoc) { out[key] = sumUnavailableRow(S, sumSpec(S, key), sumClear(S, joinUnavailable(J, "zones", null, null))); return; }
      var days = (zdoc.events || []).filter(function (ev) { return kinds.indexOf(ev.k) >= 0 && sigs.indexOf(ev.s) >= 0 && ev.b; })
        .map(function (ev) { return sumMontanaIso(Date.parse(ev.b)); });
      var cells = sumZoneCells(ctx, days, key, family);
      var five = sumFive(S, cells, "sum", function (v) { return sumCountText(S, key, v); }, "");
      if (five.value === null && cells.some(function (c) { return c.value !== null; })) five = sumPartialFive(S, cells, key) || five;
      var notes = [partialNote, sumUnplacedNote(ctx, [family])].filter(function (n) { return n; });
      out[key] = sumRow(S, sumSpec(S, key), cells, five, notes);
    });
    return out;
  }

  /** summary._zone_cells: a zone's season cells (the counts in the window), with the unplaced statement of the family on the
      seasons it falls in: a zero there is Data unavailable, a count keeps its value with the statement (B5 D27, D44). */
  function sumZoneCells(ctx, days, key, family) {
    var S = ctx.S;
    return sumCountCells(ctx, days, key).map(function (cell, k) {
      var flagged = sumZoneFlag(ctx, family, SUM_SEASONS[k]);
      if (cell.value === 0 && flagged) return sumCell(S, { text: sumWord(S, "zero_unknown"), valid: 0, missing: cell.missing, flag: flagged });
      if (flagged) return sumCell(S, { value: cell.value, text: cell.text, valid: cell.valid, missing: cell.missing, flag: flagged });
      return cell;
    });
  }

  /** summary._unplaced_index (B5 D27): (family|season) to {n, first, last} for the zone products the joins could not place, counted
      for Montana. The rows are the joins block's zone_unplaced_rows ([product, zone code, issue day, edition, reason]); a product's
      family is the build's unplaced_products map. null when the build does not write them (the zone rows then say so). */
  function sumUnplacedIndex(h, S) {
    var rows = own(h.joins, "zone_unplaced_rows"), fams = S.unplaced_products;
    if (!Array.isArray(rows) || !fams) return null;
    var out = {};
    rows.forEach(function (row) {
      var fam = own(fams, row[0]), day = String(row[2]);
      if (fam === undefined || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return;
      var label = sumSeasonOf(S, day);
      if (SUM_SEASONS.indexOf(label) < 0) return;
      var k = fam + "|" + label, rec = out[k] || (out[k] = { n: 0, first: day, last: day });
      rec.n += 1;
      if (day < rec.first) rec.first = day;
      if (day > rec.last) rec.last = day;
    });
    return out;
  }

  /** The unplaced record of a family in a season (undefined when there is none). */
  function sumUnplaced(ctx, family, label) {
    return ctx.S.unplaced ? own(ctx.S.unplaced, family + "|" + label) : undefined;
  }

  /** summary._zone_flag: Montana's unplaced products of a family in a season, as the cell's statement; null when none. */
  function sumZoneFlag(ctx, family, label) {
    if (!family) return null;
    var rec = sumUnplaced(ctx, family, label);
    if (!rec) return null;
    var S = ctx.S, noun = own(S.family_nouns, family) || missingKey("family_nouns");
    var products = fill(sumWord(S, rec.n === 1 ? "product_one" : "product_many"), { noun: noun });
    var when = rec.first === rec.last ? sumFmtDate(rec.first)
      : fill(sumWord(S, "when_span"), { first: sumFmtDate(rec.first), last: sumFmtDate(rec.last) });
    return fill(sumWord(S, "zone_flag"), { n: thousands(rec.n), noun: products, when: when });
  }

  /** summary._unplaced_note: the zone row's statement of the families' products that could not be placed, by season. */
  function sumUnplacedNote(ctx, families) {
    var S = ctx.S, parts = [];
    families.forEach(function (fam) {
      SUM_SEASONS.forEach(function (label) {
        var rec = sumUnplaced(ctx, fam, label);
        if (!rec) return;
        var noun = own(S.family_nouns, fam) || missingKey("family_nouns");
        parts.push(fill(sumWord(S, "unplaced_part"), { n: thousands(rec.n), season: label,
          products: fill(sumWord(S, rec.n === 1 ? "product_one" : "product_many"), { noun: noun }) }));
      });
    });
    if (!parts.length) return null;
    var listed = parts.length === 1 ? parts[0]
      : fill(sumWord(S, "list_last"), { head: parts.slice(0, -1).join(", "), last: parts[parts.length - 1] });
    return fill(sumWord(S, "zone_unplaced_note"), { parts: listed });
  }

  /** summary._partial_five: the five-season total of a count when some seasons are unknown: the total of the seasons shown,
      with the seasons it leaves out named. */
  function sumPartialFive(S, cells, key) {
    var shown = cells.filter(function (c) { return c.value !== null; }).map(function (c) { return c.value; });
    if (!shown.length) return null;
    var skipped = SUM_SEASONS.filter(function (lab, k) { return cells[k].value === null; });
    var total = shown.reduce(function (s, v) { return s + v; }, 0);
    var missing = cells.reduce(function (s, c) { return s + c.missing; }, 0);
    return { value: total, date: null, text: fill(sumWord(S, "five_partial"), { count: sumCountText(S, key, total), seasons: skipped.join(", ") }),
      coverage: sumCover(S, missing, sumJoinedFlags(S, cells)), note: null };
  }

  /** summary._held_row: the held items the table carries as one row (D14, D41). */
  function sumHeldRow(S) {
    var cells = SUM_SEASONS.map(function () { return sumUnavailableCell(S); });
    var five = { value: null, date: null, text: sumWord(S, "cell_unavailable"), coverage: null, note: null };
    var held = S.indicators.words.held;
    return sumRow(S, sumSpec(S, "held"), cells, five, [held.lightning, held.uv_and_sun, held.roof_surface_temperature, held.ponding]);
  }

  /** stations.tile_list_picks (D36, D63, D69, D72), mirrored line for line from website/stations.py: a block without its centre or
      margin cannot answer, and neither can a point farther from the centre than the margin (null: the sheet then prints the D32
      sentence, never a "none" sentence); the passing entries within the radius of the point, nearest first (ties by id); a capped
      list with fewer than two entries within the radius cannot answer (null); the first two are the picks; an unread candidate is
      named when it comes before the second pick (or, with fewer than two picks, lies within the radius), or when it has no
      position; the rejected candidates nearer than the second pick (or every one within the radius, with fewer than two picks)
      are named, the others counted; miles are rounded half to even, as Python's round(x, 1) rounds them. */
  function sumTilePicks(J, block, lat, lon, radius) {
    var centre = block ? block.centre : undefined, margin = block ? block.margin_miles : undefined;
    if (!has(centre) || !has(margin)) return null;
    if (joinMiles(J, lat, lon, centre[0], centre[1]) > margin) return null;
    var rows = [];
    (block.passing || []).forEach(function (entry) {
      var miles = joinMiles(J, lat, lon, entry.lat, entry.lon);
      if (miles <= radius) rows.push({ miles: miles, entry: entry });
    });
    rows.sort(function (a, b) {
      if (a.miles !== b.miles) return a.miles - b.miles;
      return a.entry.id < b.entry.id ? -1 : a.entry.id > b.entry.id ? 1 : 0;
    });
    if (block.capped && rows.length < 2) return null;
    var picks = rows.slice(0, 2), unread = [];
    (block.unread || []).forEach(function (entry) {
      var miles = null, named;
      if (entry.lat === null || entry.lat === undefined) named = true;
      else {
        miles = joinMiles(J, lat, lon, entry.lat, entry.lon);
        if (picks.length === 2) named = miles < picks[1].miles || (miles === picks[1].miles && entry.id < picks[1].entry.id);
        else named = miles <= radius;
      }
      if (named) unread.push({ id: entry.id, name: entry.name || entry.id, miles: miles === null ? null : sumRoundEven(miles, 1), reason: entry.reason });
    });
    var out = picks.map(function (p) {
      return { id: p.entry.id, name: p.entry.name || p.entry.id, miles: sumRoundEven(p.miles, 1) };
    });
    var state = out.length === 2 ? "two" : out.length === 1 ? "one" : unread.length ? "unavailable" : "none";
    // the rejected candidates the point names (stations.rejected_rule, D69): nearer than the second pick; with fewer than two picks,
    // every one within the radius. The others are counted.
    var within = [];
    (block.rejected || []).forEach(function (entry) {
      var m = joinMiles(J, lat, lon, entry.lat, entry.lon);
      if (m <= radius) within.push({ miles: m, entry: entry });
    });
    within.sort(function (a, b) {
      if (a.miles !== b.miles) return a.miles - b.miles;
      return a.entry.id < b.entry.id ? -1 : a.entry.id > b.entry.id ? 1 : 0;
    });
    var named = within, more = 0;
    if (picks.length === 2) {
      named = within.filter(function (r) { return r.miles < picks[1].miles || (r.miles === picks[1].miles && r.entry.id < picks[1].entry.id); });
      more = within.length - named.length;
    }
    var rejected = named.map(function (r) {
      return { id: r.entry.id, name: r.entry.name || r.entry.id, miles: sumRoundEven(r.miles, 1), ok: r.entry.ok, of: r.entry.of,
        share: r.entry.share, current: r.entry.current, newest: r.entry.newest };
    });
    return { state: state, picks: out, unread: unread, candidates: rows.length, incomplete: unread.length > 0,
      rejected: rejected, rejected_more: more };
  }

  /** summary._Spot.chosen_from_tile_list: the picks of one element from the tile's list (D36, D61). null when the list does not
      hold the element, predates the radius rule (no margin_miles), or cannot answer. */
  function sumChosenFromTiles(ctx, element) {
    var doc = ctx.tileDoc;
    var block = doc && doc.elements ? own(doc.elements, element) : undefined;
    if (!block || doc.margin_miles === undefined) return null;
    var got = sumTilePicks(ctx.h.joins, block, ctx.sp.lat, ctx.sp.lon, ctx.h.stations.radius_miles);
    if (got === null) return null;
    return { state: got.state, chosen: got.picks, unread: got.unread, incomplete: got.incomplete, candidates: got.candidates,
      rejected: got.rejected, rejected_more: got.rejected_more };
  }

  /** summary._Spot.chosen: (state, the chosen stations nearest first, the rule's result), from the tile list only. The browser
      has no station block, so a list that cannot answer gives state "cannot"; the sheet says so (see sumStationRow). */
  function sumChosen(ctx, element) {
    var got = sumChosenFromTiles(ctx, element);
    if (got === null) return { state: "cannot", chosen: [], res: null };
    return { state: got.state, chosen: got.chosen.map(function (c) {
        var sd = ctx.sd[c.id];
        return { id: c.id, name: c.name, net: sd && sd.net ? sd.net : null, miles: c.miles };
      }), res: got };
  }

  /** The station file's season period for a label (summary._Spot.station_season reads periods.season[label]). */
  function sumSeasonPeriod(sdoc, label) {
    var seasons = sdoc && sdoc.periods && sdoc.periods.season;
    return seasons ? own(seasons, label) : undefined;
  }

  function sumStationNone(ctx, element, state, res) {
    var S = ctx.S, name = sumElementName(S, element);
    var unread = res && res.unread ? res.unread : [];
    if (state === "none" && !unread.length && ctx.h.stations.state === "loaded") {
      return { kind: "none", text: fill(sumWord(S, "station_none"), { element: name }) };
    }
    return { kind: "failed", text: sumStationFailed(S, unread, name, "{season}") };
  }

  /** The element's plain name (stations.element_name), from the build's words (a need: map.json summary "element_names"). */
  function sumElementName(S, element) { return own(S.element_names, element) || missingKey("element_names"); }

  /** summary._station_text: a station value's words (snowfall, snow depth, highs and lows, with the station's name). */
  function sumStationText(S, element, value, date, name) {
    if (element === "SNOW") return fill(sumWord(S, "snow_at"), { inches: sumInFmt(S, value), station: name });
    if (element === "SNWD") return fill(sumWord(S, "snow_depth_at"), { inches: sumInFmt(S, value), date: sumFmtDate(sumIsoFromYmd(date)), station: name });
    return fill(sumWord(S, "temp_at"), { f: sumTenthsF(S, value), date: sumFmtDate(sumIsoFromYmd(date)), station: name });
  }


  /** The verb of the candidates that were not read (D32, D62): a file that did not load, a Canadian station (its reason is the
      build's Canada reason), or both. word(key) gives the words of the block the line belongs to: the summary's words for its
      station sentences, the stations' words for the rule's lines (stations._unread_status), which word them differently. */
  function sumUnreadVerb(S, unread, word) {
    if (!unread.length) return word("station_status_failed");
    if (S.canada === undefined) return missingKey("canada_reason");
    var flags = unread.map(function (u) { return u.reason === S.canada; });
    if (flags.every(function (f) { return !f; })) return word("station_status_failed");
    if (flags.every(function (f) { return f; })) return word(flags.length === 1 ? "station_status_not_read" : "station_status_not_read_many");
    return word("station_status_both");
  }

  /** summary._unread_status: the verb of a summary station sentence (D32, D62). */
  function sumUnreadStatus(S, unread) {
    return sumUnreadVerb(S, unread, function (key) { return sumWord(S, key); });
  }

  /** stations._unread_text's names: the nearest UNREAD_NAMES_SHOWN unread stations by name, then the count of the others. */
  function sumUnreadNames(S, unread) {
    var names = unread.map(function (u) { return u.name || u.id; }), shown = S.rule.unread_names_shown;
    if (typeof shown !== "number") throw new Error("summary.rule.unread_names_shown");
    var more = names.length - shown;
    if (more <= 0) return sumJoinNames(S, names);
    return fill(sumWord(S, "unread_more"), { names: names.slice(0, shown).join(", "), n: more,
      stations: sumWord(S, more === 1 ? "station_one" : "station_many") });
  }

  /** The reasons of the unread candidates, sorted and joined in brackets ("" when there are none). */
  function sumUnreadReason(S, unread) {
    var reasons = [];
    unread.forEach(function (u) { if (u.reason && reasons.indexOf(u.reason) < 0) reasons.push(u.reason); });
    reasons.sort();
    return reasons.length ? fill(sumWord(S, "reason_part"), { reasons: reasons.join("; ") }) : "";
  }

  /** summary._Spot.station_none's failed sentence (D32): the unread candidates by name, or the stations within the radius when none
      is named; their status and reasons. The season keeps its placeholder for the cell. */
  function sumStationFailed(S, unread, name, season) {
    var names = unread.length ? sumJoinNames(S, unread.map(function (u) { return u.name || u.id; }))
      : fill(sumWord(S, "stations_within"), { miles: S.rule.radius_miles });
    return fill(sumWord(S, "station_failed"), { season: season, names: names, status: sumUnreadStatus(S, unread),
      reason: sumUnreadReason(S, unread), element: name });
  }

  /** stations.station_words for a chosen result (D41, D62): the unread candidates' line (unread_element when the rule cannot
      answer, else unread_partial), or the one-station line. Nothing for two stations with no candidate unread. */
  function sumStationLines(ctx, element, state, res) {
    var S = ctx.S, name = sumElementName(S, element), unread = res && res.unread ? res.unread : [];
    if (unread.length) {
      return [fill(stWord(ctx.h, state === "unavailable" ? "unread_element" : "unread_partial"), { element: name,
        stations: sumUnreadNames(S, unread), status: sumUnreadVerb(S, unread, function (key) { return stWord(ctx.h, key); }),
        reason: sumUnreadReason(S, unread) })];
    }
    if (state === "one") return [sumClear(S, fill(stWord(ctx.h, "two_of_one"), { element: name, station: res.chosen[0].name }))];
    return [];
  }


  /** summary.rule.percent (D82, written by map.json): the percent scale, the decimals a percent shows and the step under the rule.
      Undefined when the build does not write it, so the sentence that needs it shows its placeholder. */
  function sumPercent(S) {
    var P = S.rule ? own(S.rule, "percent") : undefined;
    return P && has(P.scale) && has(P.decimals) && has(P.step) ? P : undefined;
  }
  /** Python's round(x, places) for a float, half to even (D82). toFixed rounds an exact tie up, so an exact tie takes the even
      digit instead; toFixed(100) prints the exact digits of the double, which is where a tie is looked for. */
  function sumRoundEven(x, places) {
    places = Number(places);
    var up = x.toFixed(places), exact = x.toFixed(100), dot = exact.indexOf(".");
    if (!/^50*$/.test(exact.slice(dot + 1 + places)) || Number(up.charAt(up.length - 1)) % 2 === 0) return Number(up);
    return Number(exact.slice(0, places ? dot + 1 + places : dot));
  }
  /** summary._share_text (D5): a station's share of the days as a percent with one decimal; a share under the rule never reads as the
      rule's own figure (79.96 percent shows 79.9, not 80.0). The scale, the decimals and the step are map.json's (D82). */
  function sumSharePct(S, share) {
    var P = sumPercent(S);
    if (!P) return missingKey("summary.rule.percent");
    var pct = sumRoundEven(share * P.scale, P.decimals), need = sumRoundEven(S.rule.cover_min * P.scale, P.decimals);
    if (share < S.rule.cover_min && pct >= need) pct = sumRoundEven(need - P.step, P.decimals);
    return pct.toFixed(P.decimals);
  }

  /** summary._rejected_notes (D69, F6): the candidates the rule does not use that lie nearer than the second pick, each with its
      reason (its share of the days, or the date of its newest value); the farther ones are counted in one clause. */
  function sumRejectedNotes(ctx, res, element) {
    var S = ctx.S, out = [], name = sumElementName(S, element), place = sumWord(S, "place_spot"), P = sumPercent(S);
    (res.rejected || []).forEach(function (r) {
      var miles = r.miles.toFixed(1);
      if (r.share < S.rule.cover_min) {
        out.push(fill(sumWord(S, "station_rejected"), { station: r.name, miles: miles, place: place, pct: sumSharePct(S, r.share),
          element: name, need: P ? sumRoundEven(S.rule.cover_min * P.scale, 0) : missingKey("summary.rule.percent") }));
      } else {
        var newest = r.newest ? sumFmtDate(sumIsoFromYmd(r.newest)) : sumWord(S, "newest_unknown");
        out.push(fill(sumWord(S, "station_rejected_current"), { station: r.name, miles: miles, place: place, element: name,
          newest: newest, days: S.rule.fresh_days, as_of: sumFmtDate(ctx.sp.asOf) }));
      }
    });
    var more = res.rejected_more || 0;
    if (more) out.push(fill(sumWord(S, more === 1 ? "station_rejected_more_one" : "station_rejected_more"), { n: more }));
    return out;
  }

  /** stations.fmt_in: inches from hundredths, rounded half away from zero to the station decimals ("50.3" for 5029: one decimal).
      The scale and the station decimals are map.json's (summary.units.in, D83(b)); the rounding step is one unit of the last place. */
  function sumInFmt(S, h) {
    var dec = sumStationDecimals(S), base = Math.pow(10, dec), step = sumScale(S, "in") / base;
    var v = Math.abs(h), q = Math.floor((v + step / 2) / step);
    var frac = String(q % base);
    while (frac.length < dec) frac = "0" + frac;
    return (h < 0 ? "-" : "") + Math.floor(q / base) + (dec > 0 ? "." + frac : "");
  }

  /** The record conversions of summary.STATION_CONV: (value, date) of a station's season record for an element. The constants are
      the build's (summary.conv: mm_scale for snowfall, c_to_f for the tenths of a degree C to F rule), never written here. */
  function sumConv(h, element, rec) {
    var C = own(h.summary, "conv");
    if (C === undefined) throw new Error("summary.conv");
    var T = h.tenths_per_inch, half = Math.floor(T / 2);                 // T: the store's tenths of a millimetre per inch
    var toF = function (c10) { return Math.floor((C.c_to_f.mul * c10 + C.c_to_f.offset + C.c_to_f.round) / C.c_to_f.div); };
    if (element === "SNOW") return { value: rec.sum !== undefined ? Math.floor((rec.sum * C.mm_scale + half) / T) : null, date: null };
    if (element === "SNWD") return { value: rec.max !== undefined ? Math.floor((rec.max * C.mm_scale + half) / T) : null, date: rec.max_d === undefined ? null : rec.max_d };
    if (element === "TMAX") return { value: rec.max !== undefined ? toF(rec.max) : null, date: rec.max_d === undefined ? null : rec.max_d };
    return { value: rec.min !== undefined ? toF(rec.min) : null, date: rec.min_d === undefined ? null : rec.min_d };
  }

  /** summary._Spot.station_season: one season's figure: the first chosen station (nearest first) whose season has at least
      95 percent of its days with the element; the nearer stations that fell short are named on the cell (passed over). */
  function sumStationSeason(ctx, element, label, chosen, none) {
    var S = ctx.S, total = sumCoverOf(S, ctx.sp, label, false).total;
    if (!chosen.length) return sumNoneCell(S, label, none, total);
    var short = [], failed = [];
    for (var k = 0; k < chosen.length; k++) {
      var st = chosen[k], sdoc = ctx.sd[st.id];
      var period = sdoc ? sumSeasonPeriod(sdoc, label) : undefined;
      if (!period) { failed.push({ station: st.name, miles: st.miles, sid: st.id }); continue; }
      var n = Number(period.n), rec = own(period, element) || {}, ok = Number(rec.ok || 0), rule = sumSeasonRule(S);
      if (n > 0 && ok * rule.scale >= n * rule.share) {
        var conv = sumConv(ctx.h, element, rec);
        if (conv.value !== null) {
          var cell = sumCell(S, { value: conv.value, date: conv.date, valid: ok, missing: n - ok, station: st.name });
          cell.station = st.name; cell.miles = st.miles; cell.sid = st.id;
          cell.passedOver = short.slice(); cell.failed = failed.slice(); cell.season = label;
          return cell;
        }
      }
      short.push({ station: st.name, n: n, ok: ok, miles: st.miles, sid: st.id });
    }
    if (!short.length) {
      if (failed.length) {
        var names = sumJoinNames(S, failed.map(function (f) { return f.station; }));   // summary._station_season's failed line
        return sumCell(S, { text: fill(sumWord(S, "station_failed"), { season: label, names: names,
          status: sumWord(S, "station_status_failed"), reason: "", element: sumElementName(S, element) }), valid: 0, missing: 0 });
      }
      return sumNoneCell(S, label, none, total);
    }
    var first = short[0];
    var text = fill(sumWord(S, "station_short"), { season: label, station: first.station, k: first.ok, d: first.n, element: sumElementName(S, element) });
    var c2 = sumCell(S, { value: null, text: text, valid: 0, missing: first.n - first.ok, station: first.station });
    c2.miles = first.miles; c2.sid = first.sid;
    return c2;
  }

  /** summary._none_cell: the cell of a season no chosen station gives a figure for. */
  function sumNoneCell(S, label, none, total) {
    if (none.kind === "failed") return sumCell(S, { text: none.text.replace("{season}", label), valid: 0, missing: 0 });
    return sumCell(S, { text: none.text, valid: 0, missing: total });
  }

  function sumStationRow(ctx, key, element, combine) {
    var S = ctx.S, spec = sumSpec(S, key);
    var ch = sumChosen(ctx, element);
    if (ch.state === "cannot") {
      return sumUnavailableRow(S, spec, sumClear(S, fill(sumWord(S, "unavailable_part"), { part: sumWord(S, "station_part"), part_lower: sumWord(S, "station_part_lower") })));
    }
    var none = sumStationNone(ctx, element, ch.state, ch.res);
    var cells = [];
    SUM_SEASONS.forEach(function (label) {
      var cell = sumStationSeason(ctx, element, label, ch.chosen, none);
      if (cell.value !== null) cell.text = sumStationText(S, element, cell.value, cell.date, cell.station);
      cells.push(cell);
    });
    var plain = combine === "sum" ? function (v) { return fill(sumWord(S, "in_plain"), { inches: sumInFmt(S, v) }); } : null;
    var noneFive = none.kind === "failed" ? none.text.replace("{season}", sumWord(S, "five_seasons")) : none.text;
    var five = sumFive(S, cells, combine, plain, noneFive);
    var names = [];
    cells.forEach(function (c) { if (c.station && names.indexOf(c.station) < 0) names.push(c.station); });
    if (combine === "sum" && five.value !== null) {
      if (names.length > 1) five = { value: null, date: null, text: sumWord(S, "five_snow_split"), coverage: five.coverage, note: null };
      else if (names.length) five.text = fill(sumWord(S, "five_station_one"), { total: five.text, station: names[0] });
    }
    var notes = [];
    if (ch.chosen.length) {
      notes.push(sumWord(S, "station_rule_spot"));
      ch.chosen.forEach(function (st) {
        notes.push(fill(sumWord(S, "station_named"), { station: st.name, miles: st.miles.toFixed(1) }));
        if (st.net === "SNOTEL") notes.push(fill(sumWord(S, "snotel_station"), { station: st.name }));
      });
      sumStationLines(ctx, element, ch.state, ch.res).forEach(function (w) { notes.push(w); });
    } else {
      notes.push(none.kind === "failed" ? none.text.replace("{season}", sumWord(S, "five_seasons")) : none.text);
    }
    sumRejectedNotes(ctx, ch.res, element).forEach(function (w) { notes.push(w); });   // the candidates the rule does not use (D69)
    cells.forEach(function (cell, k) {
      (cell.passedOver || []).forEach(function (po) {
        var P = sumPercent(S), pct = P ? sumRoundEven(po.n ? po.ok * P.scale / po.n : 0, P.decimals).toFixed(P.decimals)
          : missingKey("summary.rule.percent");
        notes.push(fill(sumWord(S, "passed_over"), { station: po.station, pct: pct, season: SUM_SEASONS[k], ok: po.ok, n: po.n, chosen: cell.station }));
      });
      (cell.failed || []).forEach(function (fl) {
        notes.push(fill(sumWord(S, "record_failed_passed"), { station: fl.station, season: SUM_SEASONS[k], chosen: cell.station, element: sumElementName(S, element) }));
      });
    });
    notes.push(sumWord(S, "window_station"));
    return sumRow(S, spec, cells, five, notes);
  }

  /** summary._gust_rows: the days at 50 kt or more and the strongest gust, at the nearer of the cell's station picks (the rule of
      joins.station_picks, the joined records' own station). A season shows its figures only when 95 percent of its days have a
      value (D5, O8, D37); a record without those counts shows Data unavailable; a failed record is named (D32). */
  function sumGustRows(ctx) {
    var h = ctx.h, S = ctx.S, sp = ctx.sp, J = h.joins;
    var picks = ctx.jdoc ? joinPicks(J, ctx.jdoc, sp.lat, sp.lon) : null;
    if (!picks) return { gust_days: sumUnavailableRow(S, sumSpec(S, "gust_days"), sumClear(S, joinUnavailable(J, "stations", null, null))),
      gust_max: sumUnavailableRow(S, sumSpec(S, "gust_max"), sumClear(S, joinUnavailable(J, "stations", null, null))) };
    if (!picks.length) {
      var totals = SUM_SEASONS.map(function (label) { return sumCoverOf(S, sp, label, false).total; });
      var cells = totals.map(function (t) { return sumCell(S, { text: sumWord(S, "gust_none"), valid: 0, missing: t }); });
      var five = { value: null, date: null, text: sumWord(S, "gust_none"), coverage: sumCover(S, totals.reduce(function (a, b) { return a + b; }, 0), null), note: null };
      return { gust_days: sumRow(S, sumSpec(S, "gust_days"), cells, five, [sumWord(S, "gust_none")]),
        gust_max: sumRow(S, sumSpec(S, "gust_max"), cells, five, [sumWord(S, "gust_none")]) };
    }
    var st = picks[0], name = st.name, miles = st.miles, milesText = Number(miles).toFixed(1);
    var note = fill(sumWord(S, "gust_station"), { station: name, miles: miles.toFixed(1) });
    var gdoc = ctx.gustDoc;
    if (!gdoc) {
      var failed = fill(sumWord(S, "gust_failed"), { names: name, reason: "" });
      var fcells = SUM_SEASONS.map(function () { return sumCell(S, { text: failed, valid: 0, missing: 0, station: name }); });
      var ffive = { value: null, date: null, text: sumWord(S, "cell_unavailable"), coverage: null, note: failed };
      return { gust_days: sumRow(S, sumSpec(S, "gust_days"), fcells, ffive, [note, failed]),
        gust_max: sumRow(S, sumSpec(S, "gust_max"), fcells, ffive, [note, failed]) };
    }
    var seasons = gdoc.periods && gdoc.periods.season;
    if (!seasons || typeof seasons !== "object") {
      var interim = fill(sumWord(S, "gust_interim"), { station: name });
      var ucells = SUM_SEASONS.map(function () { return sumCell(S, { text: sumWord(S, "cell_unavailable"), unknown: true, station: name }); });
      var fd = sumFive(S, ucells, "sum", null, "");
      var fm = sumFive(S, ucells, "max", null, sumWord(S, "none_gust"));
      return { gust_days: sumRow(S, sumSpec(S, "gust_days"), ucells, fd, [note, interim, sumWord(S, "gust_coverage_note")]),
        gust_max: sumRow(S, sumSpec(S, "gust_max"), ucells, fm, [note, interim, sumWord(S, "gust_floor_note")]) };
    }
    var cellsDays = [], cellsMax = [];
    SUM_SEASONS.forEach(function (label) {
      var per = own(seasons, label) || {}, nDays = Number(per.n || 0), ok = Number(per.ok || 0);
      if (nDays <= 0) {
        var t = fill(sumWord(S, "season_unavailable"), { season: label, source: fill(sumWord(S, "gust_record_at"), { station: name }) });
        cellsDays.push(sumCell(S, { text: t, unknown: true, station: name })); cellsMax.push(sumCell(S, { text: t, unknown: true, station: name }));
        return;
      }
      var missing = Math.max(0, nDays - ok), rule = sumSeasonRule(S);
      if (ok * rule.scale < nDays * rule.share) {
        var s = fill(sumWord(S, "gust_season_short"), { season: label, station: name, k: ok, d: nDays });
        cellsDays.push(sumCell(S, { text: s, valid: ok, missing: missing, unknown: true, station: name }));
        cellsMax.push(sumCell(S, { text: s, valid: ok, missing: missing, unknown: true, station: name }));
        return;
      }
      var members = [];
      (gdoc.days || []).forEach(function (item) {
        var iso = hailIso(h, item[0]);
        if (sumSeasonOf(S, iso) === label) members.push({ iso: iso, mph: Number(item[1]), kt: Number(item[2]), flag: item.length > 3 ? Number(item[3]) : 0 });
      });
      var n = members.length;
      var dtext = fill(sumWord(S, n === 1 ? "station_days_one" : "station_days"), { n: thousands(n), station: name });
      cellsDays.push(sumCell(S, { value: n, text: dtext, valid: ok, missing: missing, station: name }));
      if (members.length) {
        var best = members[0];
        members.forEach(function (m) { if (m.kt > best.kt || (m.kt === best.kt && m.iso < best.iso)) best = m; });
        var wording = sumWord(S, best.flag ? "gust_flagged" : "gust");
        cellsMax.push(sumCell(S, { value: best.kt, text: fill(wording, { kt: best.kt, mph: best.mph, date: sumFmtDate(best.iso), station: name }),
          date: Number(best.iso.replace(/-/g, "")), valid: ok, missing: missing, station: name }));
      } else {
        cellsMax.push(sumCell(S, { value: null, text: fill(sumWord(S, "none_gust_at"), { station: name }), valid: ok, missing: missing, station: name }));
      }
    });
    var fiveDays = sumFive(S, cellsDays, "sum", function (v) { return fill(sumWord(S, v === 1 ? "station_days_one" : "station_days"), { n: thousands(v), station: name }); }, "");
    var fiveMax = sumFive(S, cellsMax, "max", null, sumWord(S, "none_gust"));
    return { gust_days: sumRow(S, sumSpec(S, "gust_days"), cellsDays, fiveDays, [note, sumWord(S, "gust_coverage_note")]),
      gust_max: sumRow(S, sumSpec(S, "gust_max"), cellsMax, fiveMax, [note, sumWord(S, "gust_floor_note")]) };
  }

  /** summary._partial_grid: the grid's values for the days of the partial season so far, labelled preliminary, never a record;
      a season whose highest, lowest or rain total is not known says so instead (D20, D33). */
  function sumPartialGrid(ctx, rec, through) {
    var S = ctx.S, h = ctx.h, label = h.summary.partial;
    var days = Number(rec[0]), missing = Number(rec[1]), valid = days - missing;
    if (valid <= 0) return fill(h.climate.templates.season_unavailable, { label: label });
    var tmax = rec[5] !== null ? sumTenthsF(S, rec[5]) : null, tmin = rec[7] !== null ? sumTenthsF(S, rec[7]) : null;
    var rain = rec[2] !== null ? sumInText(S, rec[2]) : null, rmax = rec[3] !== null ? sumInText(S, rec[3]) : null;
    if (tmax === null || tmin === null || rain === null || rmax === null) return fill(sumWord(S, "partial_grid_unavailable"), { season: label });
    var hot = rec[9], frost = rec[12];
    var text = fill(sumWord(S, "partial_grid"), {
      season: label, n_days: valid, through: sumFmtDate(through), high: tmax, high_date: sumFmtDate(sumIsoFromYmd(rec[6])),
      low: tmin, low_date: sumFmtDate(sumIsoFromYmd(rec[8])), hot: hot, hot_days: sumWord(S, hot === 1 ? "day_noun" : "days_noun"),
      frost: frost, frost_days: sumWord(S, frost === 1 ? "day_noun" : "days_noun"), total: rain,
      rain_max: rmax, rain_max_date: sumFmtDate(sumIsoFromYmd(rec[4])) });
    if (missing) text += " " + fill(sumWord(S, "partial_missing"), { n: thousands(missing) }) + ".";
    return text;
  }

  /** summary._partial: the one line below the table for the partial season (D20, D33): the grid's preliminary values, and the
      report and radar counts so far. */
  function sumPartialLine(ctx, lsr, radarDays) {
    var S = ctx.S, sp = ctx.sp, h = ctx.h, label = h.summary.partial;
    var storeDays = sumCoverOf(S, sp, label, false).store;
    var rec = ctx.climRec && ctx.climRec.status === "ok" ? ctx.climRec.record.s[5] : null;
    var gridDays = rec ? Number(rec[0]) : 0, through = h.climate.through;
    if (storeDays <= 0 && gridDays <= 0) return fill(sumWord(S, "partial_none"), { season: label });
    var parts = [];
    if (rec && gridDays > 0 && through) parts.push(sumPartialGrid(ctx, rec, through));
    if (lsr !== null && radarDays !== null) {
      var count = function (pick) { return lsr.filter(function (r) { return pick(r) && sumSeasonOf(S, r.day) === label && sumInWindow(sp, r.day); }).length; };
      var hailN = count(function (r) { return r.code === "H"; });
      var windN = count(function (r) { return S.rule.wind_codes.indexOf(r.code) >= 0; });
      var windAuto = S.auto_sources === undefined ? 0 : count(function (r) { return S.rule.wind_codes.indexOf(r.code) >= 0 && S.auto_sources.indexOf(r.src) >= 0; });
      var floodN = count(function (r) { return r.kind === "flood" || r.kind === "flash flood"; });
      var one = radarDays.filter(function (x) { return sumSeasonOf(S, x.iso) === label && x.t >= S.rule.one_inch_tenths; }).length;
      var auto = windN && S.auto_sources === undefined ? missingKey("auto_sources") : windN && windAuto ? fill(sumWord(S, "auto_partial"), { n: windAuto }) : "";
      var items = [];
      [["hail_n", hailN, ""], ["wind_n", windN, auto], ["flood_report_n", floodN, ""]].forEach(function (t) {
        var key = t[0], n = t[1], extra = t[2];
        if (n) items.push(n + " " + sumNoun(S, key, n) + extra);
        else items.push(fill(sumWord(S, "partial_no_report"), { word: sumReportType(S, key) }));
      });
      parts.push(fill(sumWord(S, "partial_counts"), { season: label, items: items.join("; "), r1: one,
        r1_word: sumWord(S, one === 1 ? "day_noun" : "days_noun") }));
    }
    return parts.length ? parts.join(" ") : fill(sumWord(S, "partial_none"), { season: label });
  }

  /** The table's partial line (summary.describe_summary's partial): the line, with the all-clear sentence (D41). */
  function sumPartialRow(ctx) {
    var J = ctx.h.joins, reasonsState = ctx.parts("reports");
    var lsr = null, radarDays = ctx.tileOk ? ctx.days : null;
    if (ctx.events && reasonsState !== "unavailable" && ctx.jdoc) lsr = sumReports(ctx.h, ctx.sp, ctx.events, ctx.jdoc);
    var text = sumPartialLine(ctx, lsr, radarDays);
    if (reasonsState === "unavailable" || (lsr === null && !ctx.events)) {
      var why = reasonsState === "unavailable" ? ctx.reasons("reports") : J.words.reason_events;
      text = (text ? text + " " : "") + sumClear(ctx.S, joinUnavailable(J, "reports", null, why));
    }
    return { label: ctx.h.summary.partial, text: sumClear(ctx.S, text || fill(sumWord(ctx.S, "partial_none"), { season: ctx.h.summary.partial })) };
  }

  /** The sheet's five-season table (summary.describe_summary's table): one row per table row in map.json's row order, the five
      seasons and the five-season figure, each cell with its words and its coverage line; then the partial line and the radar
      sentence (D20, D33, D41). Built with DOM calls, so every word on it is the build's. A failure shows the B1 unavailable
      words with the reason, never an empty table. */
  function sumRender(slot, res) {
    if (!slot) return;
    slot.textContent = "";
    var sheetEl = slot.closest ? slot.closest(".sheet") : null;
    if (sheetEl) sheetEl.classList.toggle("sheet-wide", !!res);   // the table needs the room: a wider sheet at desktop width (B5-11)
    if (!res) {
      var failed = document.createElement("p");
      failed.className = "warn";
      var hd = hailData(), problem = hd ? own(hd.summary.words, "table_problem") : undefined;
      failed.textContent = hd ? fill(hd.words.unavailable, { problem: problem === undefined ? missingKey("table_problem") : problem }) : "";
      slot.appendChild(failed);
      slot.hidden = false;
      return;
    }
    var S = res.ctx.S, cols = S.columns, rows = S.row_order;
    var h3 = document.createElement("h3");
    h3.textContent = S.words.table_title;
    slot.appendChild(h3);
    var plain = document.createElement("p");
    plain.className = "sub";
    plain.textContent = S.words.plain;
    slot.appendChild(plain);
    var table = document.createElement("table");
    table.className = "sum-table";
    var hr = table.createTHead().insertRow();
    hr.appendChild(document.createElement("th"));
    cols.forEach(function (c) {
      var th = document.createElement("th");
      th.scope = "col";
      th.textContent = c;
      hr.appendChild(th);
    });
    var tbody = table.createTBody();
    rows.forEach(function (key) {
      var row = res.rows[key];
      if (!row) return;                                      // the town-only rows are not on the sheet
      var tr = tbody.insertRow();
      var th = document.createElement("th");
      th.scope = "row";
      var label = document.createElement("span");
      label.className = "sum-label";
      label.textContent = row.label;
      th.appendChild(label);
      var kind = document.createElement("small");
      kind.className = "sum-kind";
      kind.textContent = row.kind;
      th.appendChild(kind);
      if (row.unit !== "reason") {                         // the unit's word beside the kind word, as the page's row heads show it
        var unitWord = document.createElement("small");
        unitWord.className = "sum-kind";
        var unitSpec = own(S.units, row.unit);
        unitWord.textContent = unitSpec === undefined ? missingKey("units") : unitSpec.word;
        th.appendChild(unitWord);
      }
      tr.appendChild(th);
      cols.forEach(function (c, k) {
        var td = tr.insertCell();
        td.setAttribute("data-label", c);
        var fiveCell = k === cols.length - 1;
        td.textContent = fiveCell ? row.five_text : row.texts[k];
        var cov = fiveCell ? row.five_coverage : row.coverage[k];
        if (cov) {
          var sm = document.createElement("small");
          sm.className = "sum-cover";
          sm.textContent = cov;
          td.appendChild(sm);
        }
      });
    });
    slot.appendChild(table);
    var notes = [];                                        // every row's notes, once each, under the table (R4): the D20 reasons,
    rows.forEach(function (key) {                          // the rule lines and the explanations, as the page's footnotes
      var row = res.rows[key];
      if (row) row.notes.forEach(function (n) { if (notes.indexOf(n) < 0) notes.push(n); });
    });
    if (notes.length) {
      var list = document.createElement("ul");
      list.className = "sum-notes";
      notes.forEach(function (n) {
        var li = document.createElement("li");
        li.textContent = n;
        list.appendChild(li);
      });
      slot.appendChild(list);
    }
    if (res.partial) {
      var part = document.createElement("p");
      part.className = "sum-partial";
      part.textContent = res.partial.text;
      slot.appendChild(part);
    }
    var rs = document.createElement("p");
    rs.className = "sub";
    rs.textContent = S.words.radar_sentence;
    slot.appendChild(rs);
    slot.hidden = false;
  }

  // ------------------------------------------------------------------ the sections under the table (B5 R11, D79(c))

  /** The eleven sections of the sheet under the table, in the order of map.json summary.sections: each with its heading, its
      lead sentence and its kind word, its rows (each starting with its kind label) and its notes; the roof section carries its
      groups of lines and references. Ported from website/build.py's history_view (the rows, the notes and the what-sentences),
      website/summary.py's _sections (the leads and the kinds), _extra and _roof (the roof counts and lines): the same per-tile
      records as the table feed them, so the sheet's text is the module's for the same cell. Every word, kind, label, unit and
      rule comes from map.json: summary.words, summary.indicators, summary.how_made and summary.section_data (read below,
      each with its placeholder when the build does not write it). A part that fails shows its D20 sentence in its own section
      and the rest of the sheet stands (D16). */

  /** summary.section_data at a dotted path, or the placeholder that names the key the build does not write. */
  function sdGet(S, path) {
    var cur = own(S, "section_data"), parts = path.split(".");
    for (var i = 0; i < parts.length && cur !== undefined && cur !== null; i++) cur = own(cur, parts[i]);
    return cur === undefined || cur === null ? missingKey("summary.section_data." + path) : cur;
  }
  /** The list at a section_data path (an empty list when the build does not write it: its placeholder is said once). */
  function sdList(S, path) { var v = sdGet(S, path); return Array.isArray(v) ? v : []; }
  /** A words key of summary.indicators.words, or its placeholder. */
  function indWord(S, key) {
    var v = own(S.indicators && S.indicators.words, key);
    return v === undefined || v === null ? missingKey("summary.indicators.words." + key) : v;
  }
  /** summary._tidy: a clause with one full stop at its end. */
  function histTidy(text) { var t = String(text).replace(/\s+$/, ""); return /[.?!]$/.test(t) ? t : t + "."; }
  /** summary._without_clear: the line with its all-clear sentence taken out, so the lead composes it and adds the sentence once. */
  function histWithoutClear(S, text) {
    var allClear = sumWord(S, "all_clear");
    return String(text).split(" " + allClear).join("").split(allClear).join("").trim();
  }
  /** summary._clear_words for the notices: the line with the all-clear sentence at its end (sumClear). */
  function histClear(S, text) { return sumClear(S, text); }

  /** build.py's _split_kind: a joined row's kind label and its words ("Report: ..." gives "Report" and the rest). The labels are
      map.json's section_data.row_labels; a row with none of them keeps its whole text and no label. */
  function histSplitKind(S, text) {
    var labels = sdList(S, "row_labels");
    for (var i = 0; i < labels.length; i++) {
      var prefix = labels[i] + ": ";
      if (text.indexOf(prefix) === 0) return [labels[i], text.slice(prefix.length)];
    }
    return ["", text];
  }

  /** build.py's _section_of: the section a joined row belongs to, from its kind label and its type or product words. The label
      rules come first (a station is wind, a detection is hail), then the words are read from the row (a product's name, a zone
      or county product before its comma, a report's or record's type after its time). The first rule that matches the words
      decides. The patterns are map.json's section_data.rules. null when the build does not write the rules. */
  function histSectionOf(S, label, body) {
    var R = sdGet(S, "rules");
    if (typeof R !== "object" || R === null || !Array.isArray(R.rules)) return null;
    var byLabel = own(R.by_label, label);
    if (byLabel !== undefined) return byLabel;
    var words;
    if (R.product_labels.indexOf(label) >= 0) {
      var m = new RegExp(R.product_patterns[0]).exec(body) || new RegExp(R.product_patterns[1]).exec(body);
      words = m ? m[1] : body;
    } else if (R.zone_labels.indexOf(label) >= 0) {
      words = body.split(new RegExp(R.zone_split))[0];
    } else {
      var t = new RegExp(R.time_pattern, "i").exec(body);
      words = (t ? t[1] : body).split(new RegExp(R.split))[0];
    }
    for (var i = 0; i < R.rules.length; i++) {
      if (new RegExp(R.rules[i][1], "i").test(words)) return R.rules[i][0];
    }
    return R.default;
  }

  /** build.py's _joined_coverage: the coverage lines of one season's figures as one phrase: the same line once, or each row's
      line named by its word when they differ. */
  function histJoinedCoverage(pairs) {
    var texts = [];
    pairs.forEach(function (p) { if (texts.indexOf(p[1]) < 0) texts.push(p[1]); });
    if (texts.length === 1) return texts[0];
    return pairs.map(function (p) { return p[0] + ": " + p[1]; }).join("; ");
  }

  /** build.py's _per_season: one row per season from the table's own cell words for these keys (the highest and lowest, a count,
      a depth), with the coverage line of any missing days; a cell that did not load is left out (the table says so). */
  function histSeasonRows(res, S, kind, keys, names) {
    var out = [], unavail = sumWord(S, "cell_unavailable");
    SUM_SEASONS.forEach(function (season, k) {
      var parts = [], cov = [];
      keys.forEach(function (key, i) {
        var row = res.rows[key];
        if (!row) return;
        var text = row.texts[k] || unavail;
        if (text.indexOf(unavail) === 0) return;
        parts.push(names[i] + " " + text);
        if (row.coverage[k]) cov.push([names[i], row.coverage[k]]);
      });
      if (parts.length) out.push({ label: kind, text: season + ": " + parts.join("; ") + (cov.length ? " (" + histJoinedCoverage(cov) + ")" : "") });
    });
    return out;
  }

  /** build.py's _window_lines: how the periods are counted (the radar and report windows, the grid's newest day, the station window). */
  function histWindowLines(S, h) {
    var lines = [];
    if (h.window && h.as_of) {
      var first = hailDate(h.window[0]), last = hailDate(h.window[1]), asOf = hailDate(h.as_of);
      lines.push(fill(sumWord(S, "window_radar"), { first: first, last: last, as_of: asOf, season: SUM_SEASONS[0] }));
      lines.push(fill(sumWord(S, "window_reports"), { first: first, last: last }));
    }
    if (h.climate && h.climate.through) lines.push(fill(sumWord(S, "window_grid"), { through: hailDate(h.climate.through) }));
    lines.push(sumWord(S, "window_station"));
    return lines;
  }

  /** summary._polygon_cells: the season cells of a polygon count (the warnings whose cover holds the cell, D11). */
  function histPolygonCells(ctx, kinds, sig, noun) {
    var days = [];
    (ctx.jdoc.warnings || []).forEach(function (pair) {
      if (!joinCovers(pair[1], ctx.sp.key)) return;
      var item = ctx.events.warnings[pair[0]];
      if (item && kinds.indexOf(item.k) >= 0 && item.s === sig) days.push(sumMontanaIso(Date.parse(item.b)));
    });
    return sumCountCells(ctx, days, noun);
  }

  /** summary._extra: the roof counts the table does not carry, as season cells (the zone counts with their unplaced statements).
      A count whose part did not load is that part's own sentence (D16): never a count of nothing. Each entry is the list of
      season cells, or a string (the sentence the line shows instead). The codes and kinds are map.json's section_data.roof.extra. */
  function histExtra(ctx, lsr) {
    var S = ctx.S, h = ctx.h, sp = ctx.sp, J = h.joins, out = {}, X = sdGet(S, "roof.extra") || {};
    var jdoc = ctx.jdoc, events = ctx.events;
    var blocked = function (part) {
      var state = ctx.parts(part);
      if (state === "unavailable") return sumClear(S, joinUnavailable(J, part, null, ctx.reasons(part)));
      if (!jdoc) return sumClear(S, joinUnavailable(J, part, null, J.words.reason_no_answer));
      if ((part === "reports" || part === "records" || part === "warnings") && !events) return sumClear(S, joinUnavailable(J, part, null, J.words.reason_events));
      return null;
    };
    var put = function (key, part, make) { var msg = blocked(part); out[key] = msg ? msg : make(); };
    var spec = function (key) { return own(X, key) || {}; };
    put("hail_signatures", "detections", function () {
      var days = [];
      (jdoc.detections || []).forEach(function (d) {
        if (joinMiles(J, sp.lat, sp.lon, d[JDET.lat], d[JDET.lon]) > J.radius_miles.detection) return;
        var iso = joinSpcIso(J, joinInstant(h, d[JDET.day], d[JDET.hhmm]));
        if (days.indexOf(iso) < 0) days.push(iso);            // a day counts once, however many rows it has
      });
      return sumCountCells(ctx, days, "days");
    });
    put("hail_warnings", "warnings", function () { return histPolygonCells(ctx, spec("hail_warnings").polygon || [], spec("hail_warnings").sig, spec("hail_warnings").noun); });
    put("tornado_warnings", "warnings", function () { return histPolygonCells(ctx, spec("tornado_warnings").polygon || [], spec("tornado_warnings").sig, spec("tornado_warnings").noun); });
    put("records_tornado", "records", function () {
      var codes = spec("records_tornado").records || [], recordsWithin = sumRecords(h, sp, events, jdoc);
      return sumCountCells(ctx, recordsWithin.filter(function (r) { return codes.indexOf(r.code) >= 0; }).map(function (r) { return r.day; }), spec("records_tornado").noun);
    });
    var reportCount = function (key) {
      var kinds = spec(key).reports || [];
      return sumCountCells(ctx, (lsr || []).filter(function (r) { return kinds.indexOf(r.kind) >= 0; }).map(function (r) { return r.day; }), spec(key).noun);
    };
    put("tornado_reports", "reports", function () { return reportCount("tornado_reports"); });
    put("rain_reports", "reports", function () { return reportCount("rain_reports"); });
    put("extreme_heat", "reports", function () { return reportCount("extreme_heat"); });
    var zoneCells = function (key) {
      var msg = blocked("zones");
      if (msg) return msg;
      if (!ctx.zoneDoc) return sumClear(S, joinUnavailable(J, "zones", null, J.words.reason_no_answer));
      var kinds = spec(key).zone || [], sigs = spec(key).sig || [];
      var days = (ctx.zoneDoc.events || []).filter(function (ev) { return kinds.indexOf(ev.k) >= 0 && sigs.indexOf(ev.s) >= 0 && ev.b; })
        .map(function (ev) { return sumMontanaIso(Date.parse(ev.b)); });
      return sumZoneCells(ctx, days, spec(key).noun || key, spec(key).family || null);
    };
    ["heat_advisory", "excessive_heat", "ice_storm", "winter_storm"].forEach(function (key) { out[key] = zoneCells(key); });
    return out;
  }

  /** summary._station_runs: the stations named by the seasons they gave: "Billings WTP 2021-22 to 2024-25, Billings Logan 2025-26". */
  function histStationRuns(S, cells) {
    var runs = [];
    cells.forEach(function (cell, k) {
      var name = cell.station;
      if (!name) return;
      var last = runs[runs.length - 1];
      if (last && last[0] === name && last[2] === k - 1) last[2] = k;
      else runs.push([name, k, k]);
    });
    return runs.map(function (r) {
      var span = r[1] === r[2] ? SUM_SEASONS[r[1]] : SUM_SEASONS[r[1]] + " " + sdGet(S, "words.span_to") + " " + SUM_SEASONS[r[2]];
      return r[0] + " " + span;
    }).join(", ");
  }

  /** summary._dl_cells: days with 1 inch or more of snow on the ground and a low below 32 F, per season, from the station that
      passes the snow-depth rule for that season (D5). Returns the season cells; a string when the stations did not load; or
      the station words ({kind, text}) when no station gives a figure. The pair count is the station file's DL pair (D40). */
  function histDlCells(ctx) {
    var S = ctx.S;
    var ch = sumChosen(ctx, "SNWD");
    if (ch.state === "cannot") return sumUnavailablePart(S);
    var none = sumStationNone(ctx, "SNWD", ch.state, ch.res);
    if (!ch.chosen.length) return none;
    return SUM_SEASONS.map(function (label) {
      var cell = sumStationSeason(ctx, "SNWD", label, ch.chosen, none);
      if (cell.value === null || cell.value === undefined || cell.sid === undefined) {
        return sumCell(S, { text: cell.text || sumWord(S, "cell_unavailable"), valid: 0, missing: cell.missing });
      }
      var sdoc = ctx.sd[cell.sid], seasons = sdoc && sdoc.periods ? sdoc.periods.season : undefined;
      var period = seasons ? own(seasons, label) : undefined, pair = period ? own(period, "DL") : undefined;
      if (!pair) return sumUnavailableCell(S);
      var n = Number(pair.n);
      var text = fill(sumWord(S, n === 1 ? "station_days_one" : "station_days"), { n: thousands(n), station: cell.station });
      return sumCell(S, { value: n, text: text, valid: cell.valid, missing: cell.missing, station: cell.station });
    });
  }

  /** summary._unavailable_part for the station part: the D20 sentence for the stations (with the all-clear sentence). */
  function sumUnavailablePart(S) {
    return sumClear(S, fill(sumWord(S, "unavailable_part"), { part: sumWord(S, "station_part"), part_lower: sumWord(S, "station_part_lower") }));
  }

  /** The roof line specs (map.json summary.section_data.roof.lines: label, kind, noun), with the variables of a label filled in. */
  function rlSpec(S, id, vars) {
    var s = sdGet(S, "roof.lines." + id);
    if (typeof s !== "object" || s === null) return { label: s, kind: missingKey("summary.section_data.roof.lines." + id + ".kind"), noun: null };
    return { label: fill(s.label, vars || {}), kind: s.kind, noun: s.noun || null };
  }

  /** summary._line: one roof line with its label, its kind word and its five-season figure (null when none); a line with no figure
      says Data unavailable beside its label, with the reason and the all-clear sentence (summary.indicator_unavailable). */
  function histLine(S, id, value, text, why, coverage, vars) {
    var spec = rlSpec(S, id, vars), none = value === null || value === undefined;
    if (none || text === null || text === undefined) {
      text = sumClear(S, fill(indWord(S, "indicator_unavailable"), { kind: spec.kind, label: spec.label, why: why || sumWord(S, "cell_unavailable") }));
    } else if (String(text).indexOf(sdGet(S, "partial_marker")) >= 0) {
      text = sumClear(S, text);                  // a total of some seasons only is partial, and its line says so (D41)
    }
    return { id: id, label: spec.label, kind: spec.kind, value: none ? null : Number(value), text: text, coverage: coverage || null };
  }

  /** summary._gust_why: why the gust line has no figure: the station's own Data unavailable sentence, else the five-season note. */
  function histGustWhy(S, row) {
    if (!row) return null;
    var unav = sumWord(S, "cell_unavailable"), hit = (row.notes || []).filter(function (n) { return n.indexOf(unav) === 0; })[0];
    return hit !== undefined ? hit : row.five_note;
  }

  /** summary._roof: the roof section's lines under the five headings (each with its kind word and its five-season count or
      measurement, from the same records as the table), the reference lines (quotes from the public sources the roof record
      names, one per stressor) and the held lines (D14). Returns {groups, how_made} with each group's lines, references and held. */
  function histRoof(ctx, res, extra) {
    var S = ctx.S, rows = res.rows, L = own(S.indicators.words, "lines") || {};
    var covered = sumWord(S, "covered"), allClear = sumWord(S, "all_clear"), unav = sumWord(S, "cell_unavailable");
    var lineT = function (k) { return own(L, k) === undefined ? missingKey("summary.indicators.words.lines." + k) : L[k]; };
    var these = sumWord(S, "these_five"), tailRoof = sdGet(S, "words.tail_five_roof");
    var partial = sdGet(S, "partial_marker");
    var rv = function (key) { var r = rows[key]; return r ? { n: r.five, t: r.five_text, c: r.five_coverage } : { n: null, t: null, c: null }; };
    var rowWhy = function (row) {
      if (!row) return null;
      var hit = (row.notes || []).filter(function (n) { return n.indexOf(allClear) >= 0; })[0];
      return hit !== undefined ? hit : row.five_note;
    };
    var ext = function (key) {
      var cells = extra[key];
      if (typeof cells === "string") return { value: null, note: cells, coverage: null };
      return Array.isArray(cells) ? histExtraFive(S, key, cells) : null;
    };
    var isReport = function (noun) { return own(S.report_types, noun) !== undefined; };
    var kindOf = function (id) { return rlSpec(S, id).kind; };
    var noReportLine = function (kind, noun) { return kind + ": " + sumNoReport(S, noun, these); };
    var reportNear = function (key, n, tail) {               // summary's "N noun within 5 miles" + tail, with its count words
      return fill(sdGet(S, "words.report_near"), { count: sumCountText(S, key, n), tail: tail || "" });
    };
    var fromCells = function (id, key, noun, tpl, more) {
      var f = ext(key), kind = kindOf(id);
      if (f === null) return histLine(S, id, null, null, unav, null, more);
      if (f.value === null || f.value === undefined) return histLine(S, id, null, null, f.note, f.coverage, more);
      var text;
      if (f.text && String(f.text).indexOf(partial) >= 0) text = histTidy(kind + ": " + f.text);
      else if (isReport(noun) && f.value === 0) text = noReportLine(kind, noun);
      else text = fill(tpl, Object.assign({ count: sumCountText(S, noun, f.value) }, more || {}));
      return histLine(S, id, f.value, text, null, f.coverage, more);
    };
    var counted = function (id, key, noun, tpl, more) {
      var r = rv(key), kind = kindOf(id), n = r.n, text = null;
      if (n !== null && isReport(noun) && n === 0) text = noReportLine(kind, noun);
      else if (n !== null) text = fill(tpl, Object.assign({ count: sumCountText(S, noun, n) }, more || {}));
      if (n !== null && r.t && String(r.t).indexOf(partial) >= 0) text = histTidy(kind + ": " + r.t);
      return histLine(S, id, n, text, r.t, r.c, more);
    };
    var lines = {};
    var n1 = rv("radar_1in");
    lines.hail_size_days = histLine(S, "hail_size_days", n1.n, n1.n !== null
      ? fill(lineT("hail_size_days"), { count: sumCountText(S, "days", n1.n), largest: rv("radar_max").t }) : null,
      rowWhy(rows.radar_1in) || n1.t, n1.c);
    lines.hail_reports = counted("hail_reports", "hail_n", "hail_n", lineT("hail_reports"));
    if (lines.hail_reports.value) {                       // a count above zero names the largest hail reported (a zero reads so)
      lines.hail_reports.text = fill(lineT("hail_reports"), { count: sumCountText(S, "hail_n", lines.hail_reports.value), largest: rv("hail_max").t });
    }
    lines.hail_signatures = fromCells("hail_signatures", "hail_signatures", rlSpec(S, "hail_signatures").noun, lineT("hail_signatures"));
    lines.hail_warnings = fromCells("hail_warnings", "hail_warnings", rlSpec(S, "hail_warnings").noun, lineT("hail_warnings"), { covered: covered });
    var gust = ctx.gust, ng = rv("gust_days");
    lines.wind_gust_days = histLine(S, "wind_gust_days", ng.n, ng.n !== null
      ? fill(lineT("wind_gust_days"), { count: sumCountText(S, "days", ng.n), station: gust ? gust.name : sdGet(S, "words.nearest_station"),
          miles: gust ? Number(gust.miles).toFixed(1) : sdGet(S, "words.no_miles") }) : null,
      histGustWhy(S, rows.gust_days) || ng.t, ng.c);
    var wAuto = Number((rows.wind_n || {}).automated || 0);
    var autoText = wAuto === 1 ? sumWord(S, "auto_roof_one") : wAuto > 1 ? fill(sumWord(S, "auto_roof_many"), { n: wAuto }) : "";
    lines.wind_reports = counted("wind_reports", "wind_n", "wind_n", lineT("wind_reports"), { auto: autoText });
    lines.wind_zone_warnings = counted("wind_zone_warnings", "hw_zone", "hw_zone", lineT("wind_zone_warnings"));
    var tf = [ext("tornado_reports"), ext("records_tornado"), ext("tornado_warnings")];
    if (tf.every(function (f) { return f && f.value !== null && f.value !== undefined; })) {
      var report = histReportClause(S, "tornado", tf[0].value, reportNear("tornado", tf[0].value, tailRoof));
      lines.tornado_funnel = histLine(S, "tornado_funnel", tf[0].value, fill(lineT("tornado_funnel"), {
        report: report, count_nc: sumCountText(S, "tornado_nc", tf[1].value), count_w: sumCountText(S, "tor_warn", tf[2].value), covered: covered }));
    } else {
      var tw = tf.filter(function (f) { return f && f.note; })[0];
      lines.tornado_funnel = histLine(S, "tornado_funnel", null, null, tw ? tw.note : null);
    }
    lines.freeze_thaw_days = counted("freeze_thaw_days", "freeze_thaw", "freeze", lineT("freeze_thaw_days"));
    lines.days_low_below_32 = counted("days_low_below_32", "frost32", "days", lineT("days_low_below_32"));
    lines.days_high_90 = counted("days_high_90", "hot90", "days", lineT("days_high_90"));
    var tx = rows.tmax, tn = rows.tmin;
    if (tx && tn && tx.five !== null && tn.five !== null) {
      lines.temperature_extremes = histLine(S, "temperature_extremes", tx.five, fill(lineT("temperature_extremes"), { hi: tx.five_text, lo: tn.five_text }));
    } else {
      lines.temperature_extremes = histLine(S, "temperature_extremes", null, null,
        rowWhy(tx) || rowWhy(tn) || (tx ? tx.five_text : null) || (tn ? tn.five_text : null));
    }
    var ns = rv("snow"), snowStation = (rows.snow ? rows.snow.stations || [] : []).filter(function (s) { return !!s; })[0];
    lines.snowfall_season = histLine(S, "snowfall_season", ns.n, ns.n !== null && snowStation
      ? fill(lineT("snowfall_season"), { total: fill(sumWord(S, "in_plain"), { inches: sumInFmt(S, ns.n) }), station: snowStation }) : null,
      rowWhy(rows.snow) || ns.t, ns.c);
    var nd = rv("snow_depth");
    lines.snow_depth = histLine(S, "snow_depth", nd.n, nd.n !== null ? fill(lineT("snow_depth"), { largest: nd.t }) : null,
      rowWhy(rows.snow_depth) || nd.t, nd.c);
    // the ice-dam line: the kind word leads it in every state, the unavailable ones too (D41, D57)
    var dlSpec = rlSpec(S, "ice_dam_weather_days");
    var iceLine = function (why, coverage) {
      return { id: "ice_dam_weather_days", label: dlSpec.label, kind: dlSpec.kind, value: null, coverage: coverage || null,
        text: sumClear(S, fill(lineT("ice_dam_unavailable"), { label: dlSpec.label, why: why || unav })) };
    };
    var dl = histDlCells(ctx);
    if (typeof dl === "string") {
      lines.ice_dam_weather_days = iceLine(dl);
    } else if (!Array.isArray(dl)) {                      // no station gives a figure (D32): its words, for the five seasons
      lines.ice_dam_weather_days = iceLine(dl.kind === "failed" ? fill(dl.text, { season: sumWord(S, "five_seasons") }) : dl.text);
    } else {
      var five = sumFive(S, dl, "sum", null, "");
      var names = [];
      dl.forEach(function (c) { if (c.station && names.indexOf(c.station) < 0) names.push(c.station); });
      if (five.value !== null && names.length !== 1) {    // more than one station would mix sources (D41, F5)
        var note = names.length ? fill(sumWord(S, "ice_five_split"), { runs: histStationRuns(S, dl) }) : sumUnavailablePart(S);
        five = { value: null, date: null, text: null, coverage: five.coverage, note: note };
      }
      lines.ice_dam_weather_days = five.value !== null
        ? histLine(S, "ice_dam_weather_days", five.value, fill(lineT("ice_dam_weather_days"), { count: sumCountText(S, "days", five.value), station: names[0] }), five.note, five.coverage)
        : iceLine(five.note, five.coverage);
    }
    lines.freezing_rain_reports = counted("freezing_rain_reports", "freezing_rain_n", "freezing_rain_n", lineT("freezing_rain_reports"));
    lines.ice_storm_warnings = fromCells("ice_storm_warnings", "ice_storm", "ice_storm", lineT("ice_storm_warnings"));
    lines.winter_storm_warnings = fromCells("winter_storm_warnings", "winter_storm", "winter_storm", lineT("winter_storm_warnings"));
    var pr = rv("precip");
    lines.precipitation_year = histLine(S, "precipitation_year", pr.n, pr.n !== null ? fill(lineT("precipitation_year"), { total: pr.t }) : null,
      rowWhy(rows.precip) || pr.t, pr.c);
    var pm = rv("precip_max");
    lines.largest_one_day_rain = histLine(S, "largest_one_day_rain", pm.n, pm.n !== null ? fill(lineT("largest_one_day_rain"), { largest: pm.t }) : null,
      rowWhy(rows.precip_max) || pm.t, pm.c);
    lines.rain_reports = fromCells("rain_reports", "rain_reports", "rain_n", lineT("rain_reports"));
    var nfl = rv("flood_report_n"), nfw = rv("flood_warn");
    lines.flood_reports_warnings = histLine(S, "flood_reports_warnings", nfl.n, nfl.n !== null && nfw.n !== null
      ? fill(lineT("flood_reports_warnings"), { report: histReportClause(S, "flood_report_n", nfl.n, reportNear("flood_report_n", nfl.n, tailRoof)),
          count_w: sumCountText(S, "flood_warn", nfw.n), covered: covered }) : null, nfl.t || nfw.t, nfl.c);
    var hk = [ext("heat_advisory"), ext("excessive_heat"), ext("extreme_heat")];
    if (hk.every(function (f) { return f && f.value !== null && f.value !== undefined; })) {
      var xReport = histReportClause(S, "xheat", hk[2].value, reportNear("xheat", hk[2].value, tailRoof));
      var heatText = String(hk[0].text || "").indexOf(partial) >= 0
        ? fill(lineT("heat_reports_warnings_partial"), { count_h: hk[0].text, count_e: sumCountText(S, "excessive_heat", hk[1].value), report: xReport })
        : fill(lineT("heat_reports_warnings"), { count_h: sumCountText(S, "heat_advisory", hk[0].value), count_e: sumCountText(S, "excessive_heat", hk[1].value), report: xReport });
      lines.heat_reports_warnings = histLine(S, "heat_reports_warnings", hk[0].value, heatText, null, hk[0].coverage);
    } else {
      var hw = hk.filter(function (f) { return f && f.note; })[0];
      lines.heat_reports_warnings = histLine(S, "heat_reports_warnings", null, null, hw ? hw.note : null);
    }
    // the groups: the lines under their headings, the reference lines and the held lines (map.json indicators)
    var refLine = sdGet(S, "roof.reference_line"), heldWords = own(S.indicators.words, "held") || {};
    var heldNames = sdGet(S, "roof.held_names"), refKind = sdGet(S, "kind.reference"), unavKind = sdGet(S, "kind.unavailable");
    var groups = (S.indicators.groups || []).map(function (g) {
      var gkey = g[0], refs = own(S.indicators.words.refs, gkey) || [], held = own(S.indicators.held_groups, gkey) || [];
      return {
        key: gkey, name: g[1],
        lines: (own(S.indicators.indicator_groups, gkey) || []).map(function (id) { return lines[id]; }).filter(function (x) { return !!x; }),
        references: refs.map(function (rid) {
          var r = own(S.indicators.references, rid);
          return r ? { id: rid, kind: refKind, text: fill(refLine, { source: r.source, quote: r.quote }) } : null;
        }).filter(function (x) { return !!x; }),
        held: held.map(function (hid) { return { id: hid, kind: unavKind, label: own(heldNames, hid), text: has(own(heldWords, hid)) ? heldWords[hid] : missingKey("summary.indicators.words.held." + hid) }; })
      };
    });
    return { groups: groups, how_made: own(S.indicators.words, "how_made_roof") || [] };
  }

  /** summary._report_clause: "Report: ..." (the kind word of reports) with the count words, or, for a zero count of a report
      type, the no-report sentence without its full stop (the line adds its own). */
  function histReportClause(S, key, n, nonzero) {
    var kindReport = sdGet(S, "kind.report");
    if (own(S.report_types, key) !== undefined && n === 0) return kindReport + ": " + sumNoReport(S, key, sumWord(S, "these_five")).slice(0, -1);
    return kindReport + ": " + nonzero;
  }

  /** summary._extra_five: the five-season figure of a roof count from its season cells: the total, or, for a zone count with some
      seasons unknown (the keys map.json lists in section_data.roof.partial_keys), the total of the seasons shown. */
  function histExtraFive(S, key, cells) {
    var five = sumFive(S, cells, "sum", null, "");
    if (five.value === null && sdList(S, "roof.partial_keys").indexOf(key) >= 0 && cells.some(function (c) { return c.value !== null; })) {
      five = sumPartialFive(S, cells, key) || five;
    }
    return five;
  }

  /** The leads of the sections (summary._sections): each lead is its words of summary.words filled with the five-season figures
      of the table rows and the roof counts, then the rule of finish(): the days missing among its rows once, and the all-clear
      sentence when a part did not load or only some seasons are shown (D41). */
  function histLeads(ctx, res, extra) {
    var S = ctx.S, rows = res.rows, unavailable = sumWord(S, "cell_unavailable"), allClear = sumWord(S, "all_clear");
    var partial = sdGet(S, "partial_marker"), kindReport = sdGet(S, "kind.report"), kindRecord = sdGet(S, "kind.record");
    var has = function (key) { return own(rows, key) !== undefined; };
    var fiveText = function (key) { var r = rows[key]; return !r || r.five === null || r.five === undefined ? unavailable : r.five_text; };
    var countText = function (noun, key) {
      var r = rows[key];
      if (!r || r.five === null || r.five === undefined) return unavailable;
      if (String(r.five_text || "").indexOf(partial) >= 0) return r.five_text;
      return sumCountText(S, noun, r.five);
    };
    var extraCells = function (key) { return Array.isArray(extra[key]) ? extra[key] : null; };
    var extraCount = function (noun, key) {
      var cells = extraCells(key);
      if (!cells) return unavailable;
      var f = histExtraFive(S, key, cells);
      if (f.value === null || f.value === undefined) return unavailable;
      if (String(f.text || "").indexOf(partial) >= 0) return f.text;
      return sumCountText(S, noun, f.value);
    };
    var nOf = function (key) {
      if (has(key)) return rows[key].five;
      var cells = extraCells(key);
      return cells ? histExtraFive(S, key, cells).value : null;
    };
    var autoClause = function (key) {
      var n = Number((rows[key] || {}).automated || 0);
      return n ? fill(sumWord(S, "auto_lead"), { n: n }) : "";
    };
    var reportPhrase = function (key, noun, autoKey, tail) {
      var n = nOf(key);
      if (n === null || n === undefined) return kindReport + ": " + unavailable;
      var nonzero = fill(sdGet(S, "words.report_near"), { count: sumCountText(S, noun, n), tail: tail || "" }) + (autoKey ? autoClause(autoKey) : "");
      return histReportClause(S, noun, n, nonzero);
    };
    var recordPhrase = function (key, noun) {
      var n = nOf(key);
      if (n === null || n === undefined) return kindRecord + ": " + unavailable;
      if (n === 0) return kindRecord + ": " + sumCountText(S, noun, 0).slice(0, -1);
      return kindRecord + ": " + fill(sdGet(S, "words.report_near"), { count: sumCountText(S, noun, n), tail: sdGet(S, "words.tail_five_roof") });
    };
    var finish = function (text, keys) {
      var partialLine = text.indexOf(allClear) >= 0 || text.indexOf(unavailable) >= 0 || text.indexOf(partial) >= 0;
      var body = histTidy(histWithoutClear(S, text).split(".;").join(";"));
      var missing = 0;
      keys.forEach(function (k) {
        if (has(k)) missing = Math.max(missing, Number(rows[k].five_missing || 0));
        else if (Array.isArray(extra[k])) missing = Math.max(missing, extra[k].reduce(function (s, c) { return s + c.missing; }, 0));
      });
      if (missing) body = body + " " + fill(sumWord(S, "lead_missing"), { n: thousands(missing) });
      return partialLine ? sumClear(S, body) : body;
    };
    var snowRow = rows.snow || {}, snowNames = [];
    (snowRow.stations || []).forEach(function (s) { if (s && snowNames.indexOf(s) < 0) snowNames.push(s); });
    var snowText;
    if (snowRow.five !== null && snowRow.five !== undefined && snowNames.length === 1) {
      snowText = fill(sumWord(S, "lead_snow"), { snow: fill(sumWord(S, "in_plain"), { inches: sumInFmt(S, snowRow.five) }),
        station: snowNames[0], depth: fiveText("snow_depth") });
    } else if (snowNames.length > 1) {
      snowText = fill(sumWord(S, "lead_snow_split"), { depth: fiveText("snow_depth") });
    } else {
      snowText = fill(sumWord(S, "lead_snow_none"), { depth: fiveText("snow_depth") });
    }
    var gustRow = rows.gust_days;
    var stationName = ctx.gust ? ctx.gust.name : sdGet(S, "words.nearest_station");
    var windText = !gustRow || gustRow.five === null || gustRow.five === undefined
      ? fill(sumWord(S, "lead_wind_unavailable"), { station: stationName, report: reportPhrase("wind_n", "wind_n", "wind_n") })
      : fill(sumWord(S, "lead_wind"), { gust: countText("days", "gust_days"), station: stationName, report: reportPhrase("wind_n", "wind_n", "wind_n") });
    var tailComma = sdGet(S, "words.tail_five_comma");
    var leads = {
      // summary._sections: the hail lead says Data unavailable for the days with hail when the five-season count is missing (D82(c))
      hail: finish(own(rows, "radar_1in") && rows.radar_1in.five !== null && rows.radar_1in.five !== undefined
        ? fill(sumWord(S, "lead_hail"), { radar: countText("days", "radar_1in"), report: reportPhrase("hail_n", "hail_n", null, tailComma) })
        : fill(sumWord(S, "lead_hail_unavailable"), { report: reportPhrase("hail_n", "hail_n", null, tailComma) }), ["radar_1in", "hail_n"]),
      wind: finish(windText, ["gust_days", "wind_n"]),
      storms: finish(fill(sumWord(S, "lead_storms"), { hw: countText("hw_zone", "hw_zone"), sv: extraCount("sv", "hail_warnings"), covered: sumWord(S, "covered") }), ["hw_zone", "hail_warnings"]),
      temperature: finish(fill(sumWord(S, "lead_temperature"), { tmax: fiveText("tmax"), tmin: fiveText("tmin") }), ["tmax", "tmin"]),
      rain: finish(fill(sumWord(S, "lead_rain"), { precip: fiveText("precip"), pmax: fiveText("precip_max") }), ["precip", "precip_max"]),
      snow: finish(snowText, ["snow", "snow_depth"]),
      flooding: finish(fill(sumWord(S, "lead_flood"), { report: reportPhrase("flood_report_n", "flood_report_n"),
        record: recordPhrase("flood_record_n", "flood_record_n"), flood_w: countText("flood_warn", "flood_warn"), covered: sumWord(S, "covered") }),
        ["flood_report_n", "flood_record_n", "flood_warn"]),
      ice: finish(fill(sumWord(S, "lead_ice"), { report: reportPhrase("freezing_rain_n", "freezing_rain_n"), ice: countText("ice_warn", "ice_warn") }),
        ["freezing_rain_n", "ice_warn"]),
      heat: finish(fill(sumWord(S, "lead_heat"), { hot: countText("days", "hot90"), report: reportPhrase("extreme_heat", "xheat") }),
        ["hot90", "extreme_heat"]),
      roof: sumWord(S, "lead_roof"),
      made: sumWord(S, "lead_made")
    };
    return leads;
  }

  /** build.py's history_view, for a cell: the rows of each section (the table's per-season rows, the radar days, the joined records
      each under its kind label), the notes (the kinds' sentences, the table's notes for its rows, the section's own), the roof
      groups and the made section's sources. The B1 radar lead, its missing-days line and its source line are the hail section's
      notes; the parts that did not load are notices above the sections (D16). res is the table (sumTable), joins the joined
      sections (joinSections), text the B1 words of the cell (hailText). Never throws: a part that fails is said in its place. */
  function histModel(h, cell, res, joins, text) {
    var S = res ? res.ctx.S : Object.assign({}, h.summary), ctx = res ? res.ctx : null, rows = res ? res.rows : {};
    var notices = [], ids = Array.isArray(S.sections) ? S.sections : [];
    if (!ids.length) notices.push(missingKey("summary.sections"));
    // the rows a section shows before its "show all" come from the build (hail.joins.show_first, D82); a build without them shows every row
    var showFirst = h.joins ? own(h.joins, "show_first") : undefined;
    if (!has(showFirst)) { if (h.joins) notices.push(missingKey("hail.joins.show_first")); showFirst = Infinity; }
    // a sample build labels every section with its sample word, as the sheet's tag above the sections does (D10, D82)
    var sample = h.joins && h.joins.state === "sample" ? joinsWord(h, "sample") : "";
    var lsr = [], extra = {}, roofOut = null, leads = null;
    if (ctx) {
      try {
        var picks = ctx.jdoc ? joinPicks(h.joins, ctx.jdoc, ctx.sp.lat, ctx.sp.lon) : [];
        ctx.gust = picks.length ? { name: picks[0].name, miles: picks[0].miles } : null;
        if (ctx.events && ctx.jdoc && ctx.parts("reports") !== "unavailable") lsr = sumReports(h, ctx.sp, ctx.events, ctx.jdoc);
      } catch (e) { if (window.console) console.error("summary sections, reports", e); }
      try { extra = histExtra(ctx, lsr); } catch (e) { if (window.console) console.error("summary sections, roof counts", e); extra = {}; }
      try { roofOut = histRoof(ctx, res, extra); } catch (e) { if (window.console) console.error("summary sections, roof", e); roofOut = null; }
      try { leads = histLeads(ctx, res, extra); } catch (e) { if (window.console) console.error("summary sections, leads", e); leads = null; }
    }
    var unavailable = sumClear(S, sumWord(S, "cell_unavailable"));
    var bucket = {};
    ids.forEach(function (sid) { bucket[sid] = []; });
    if (res) {
      sdList(S, "season_rows").forEach(function (item) {
        if (own(bucket, item.section) === undefined) return;
        histSeasonRows(res, S, item.kind, item.keys, item.names).forEach(function (r) { bucket[item.section].push({ label: r.label, text: r.text, note: "" }); });
      });
    }
    if (text && Array.isArray(text.rows) && own(bucket, "hail") !== undefined) {
      text.rows.forEach(function (t) { bucket.hail.push({ label: sdGet(S, "kind.radar"), text: t, note: "" }); });
    }
    var rulesMissing = false;
    if (joins) {
      JOIN_PARTS.forEach(function (k) {
        var part = joins[k];
        if (!part) return;
        if (part.unavailable) notices.push(histClear(S, part.unavailable));
        (part.rows || []).forEach(function (row) {
          var split = histSplitKind(S, row.text), sid = histSectionOf(S, split[0], split[1]);
          if (sid === null) { rulesMissing = true; return; }
          if (own(bucket, sid) !== undefined) bucket[sid].push({ label: split[0], text: split[1], note: row.remark || "" });
        });
      });
    }
    if (rulesMissing) notices.push(missingKey("summary.section_data.rules"));
    // D82(d): every line of a joined part (describe_joins' lines: the freshness lines, the NCEI flood cause line, the zone-switch
    // line, the county caveat, the implausible count) is a note of the section its part feeds (summary.section_data.part_sections,
    // the map summary.PART_SECTIONS). The order is history_sections': the parts in order, each part's lines in order. As Python
    // does, a line whose part the map does not name is left out, and an empty line is skipped.
    var lineNotes = {}, partSections = sdGet(S, "part_sections");
    if (joins) {
      if (typeof partSections !== "object" || partSections === null) { if (notices.indexOf(partSections) < 0) notices.push(partSections); }
      else JOIN_PARTS.forEach(function (k) {
        var part = joins[k];
        if (!part || !Array.isArray(part.lines)) return;
        part.lines.forEach(function (text, i) {
          var name = Array.isArray(part.lineParts) && part.lineParts[i] ? part.lineParts[i] : k;
          var sid = own(partSections, name);
          if (!text || typeof sid !== "string" || own(bucket, sid) === undefined) return;
          (lineNotes[sid] = lineNotes[sid] || []).push(text);
        });
      });
    }
    var notes = {}, keysBy = sdGet(S, "section_keys"), extraBy = sdGet(S, "extra_notes");
    ids.forEach(function (sid) {
      notes[sid] = [];
      (own(keysBy, sid) || []).forEach(function (key) {
        var row = own(rows, key);
        if (row) row.notes.forEach(function (n) { if (notes[sid].indexOf(n) < 0) notes[sid].push(n); });
      });
      (own(extraBy, sid) || []).forEach(function (wordKey) { notes[sid].push(sumWord(S, wordKey)); });
    });
    var times = joinsWord(h, "times_note");
    var howMade = Array.isArray(S.how_made) ? S.how_made : [missingKey("summary.how_made")];
    if (own(notes, "made") !== undefined) notes.made = howMade.concat(res ? histWindowLines(S, h) : [], [times]);
    var what = sdGet(S, "kind_what");
    // the B1 radar lead and its day counts by size class (the hail section's own words, after the kinds' sentences)
    var radarHead = [];
    if (text && text.lead) radarHead.push(text.lead);
    if (text && text.countsTitle && Array.isArray(text.counts) && text.counts.length) {
      radarHead.push(text.countsTitle);
      text.counts.forEach(function (c) { radarHead.push(c); });
    }
    ids.forEach(function (sid) {
      var kinds = [];
      bucket[sid].forEach(function (r) { if (kinds.indexOf(r.label) < 0) kinds.push(r.label); });
      var first = [];
      kinds.forEach(function (k) { var w = own(what, k); if (w !== undefined) first.push(w); });
      notes[sid] = first.concat(sid === "hail" ? radarHead : [], notes[sid], own(lineNotes, sid) || []);
    });
    if (text && own(notes, "hail") !== undefined) {         // the B1 missing days and its source close the hail section's notes
      if (text.missing) notes.hail.push(text.missing);
      if (text.source) notes.hail.push(text.source);
    }
    var kinds = sdGet(S, "kinds"), titles = S.words ? S.words.section_titles : undefined;
    var model = { notices: notices, showFirst: showFirst, sections: [] };
    ids.forEach(function (sid) {
      var lead = leads ? own(leads, sid) : undefined;
      if (lead === undefined) lead = unavailable;
      var sec = { id: sid, heading: own(titles, sid) === undefined ? missingKey("summary.words.section_titles." + sid) : titles[sid],
        sample: sample, lead: lead, kind: own(kinds, sid) === undefined ? missingKey("summary.section_data.kinds." + sid) : kinds[sid],
        rows: bucket[sid], notes: notes[sid], showAll: fill(joinsWord(h, "show_all"), { n: bucket[sid].length }), groups: null };
      if (sid === "roof") {
        sec.groups = roofOut ? roofOut.groups : null;
        sec.notes = roofOut ? roofOut.how_made : [];
        if (!roofOut) sec.lead = sumClear(S, fill(sumWord(S, "unavailable_part"), { part: sdGet(S, "words.roof_part"), part_lower: sdGet(S, "words.roof_part_lower") }));
      }
      model.sections.push(sec);
    });
    return model;
  }

  /** A words key of the joined records (h.joins.words), or its placeholder. */
  function joinsWord(h, key) {
    var v = h.joins && h.joins.words ? own(h.joins.words, key) : undefined;
    return v === undefined || v === null ? missingKey("hail.joins.words." + key) : v;
  }

  /** One list of rows: each row shows its kind label, then its words, then its note (the remark of a report) on a line of its own. */
  function histRowList(rows) {
    var ul = document.createElement("ul");
    ul.className = "hist-rows";
    rows.forEach(function (r) {
      var li = document.createElement("li");
      if (r.label) {
        var label = document.createElement("span");
        label.className = "hist-label";
        label.textContent = r.label + ": ";
        li.appendChild(label);
      }
      li.appendChild(document.createTextNode(r.text));
      if (r.note) {
        var note = document.createElement("small");
        note.className = "hist-note";
        note.textContent = r.note;
        li.appendChild(note);
      }
      ul.appendChild(li);
    });
    return ul;
  }

  /** The roof section's groups: each group's heading, its lines (the text of each line carries its kind word), its reference lines
      (the kind word, then the source's quote) and its held lines (their own Data unavailable words). */
  function histGroups(root, groups) {
    groups.forEach(function (g) {
      var h4 = document.createElement("h4");
      h4.className = "hist-group";
      h4.textContent = g.name;
      root.appendChild(h4);
      var add = function (cls, items, label) {
        if (!items.length) return;
        var ul = document.createElement("ul");
        ul.className = cls;
        items.forEach(function (x) {
          var li = document.createElement("li");
          li.textContent = (label ? label(x) : "") + x.text;
          ul.appendChild(li);
        });
        root.appendChild(ul);
      };
      add("hist-lines", g.lines, null);
      add("hist-refs", g.references, function (r) { return r.kind + ": "; });
      add("hist-held", g.held, null);
    });
  }

  /** The sections under the table, in the order of map.json summary.sections (the sheet's own list). */
  function histRender(slot, model) {
    if (!slot) return;
    slot.textContent = "";
    model.notices.forEach(function (text) {
      var p = document.createElement("p");
      p.className = "warn hist-notice";
      p.textContent = text;
      slot.appendChild(p);
    });
    model.sections.forEach(function (sec) {
      var root = document.createElement("section");
      root.className = "hist-sec";
      root.setAttribute("data-section", sec.id);
      var h3 = document.createElement("h3");
      h3.textContent = sec.heading;
      root.appendChild(h3);
      if (sec.sample) {                              // a sample build labels each section (D10, D82)
        var tag = document.createElement("p");
        tag.className = "sample-tag hist-sample";
        tag.textContent = sec.sample;
        root.appendChild(tag);
      }
      var lead = document.createElement("p");
      lead.className = "hist-lead";
      lead.textContent = sec.lead;
      root.appendChild(lead);
      if (sec.rows.length) {
        root.appendChild(histRowList(sec.rows.slice(0, model.showFirst)));
        if (sec.rows.length > model.showFirst) {
          var more = document.createElement("details");
          more.className = "hist-more";
          var summary = document.createElement("summary");
          summary.textContent = sec.showAll;
          more.appendChild(summary);
          more.appendChild(histRowList(sec.rows.slice(model.showFirst)));
          root.appendChild(more);
        }
      }
      if (sec.groups) histGroups(root, sec.groups);
      if (sec.notes && sec.notes.length) {
        var list = document.createElement("ul");
        list.className = "sum-notes";
        sec.notes.forEach(function (n) {
          var li = document.createElement("li");
          li.textContent = n;
          list.appendChild(li);
        });
        root.appendChild(list);
      }
      slot.appendChild(root);
    });
    slot.hidden = false;
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
  var sourceCtl = null;                      // the map's one attribution control (sourceControl): the B3 source lines and the base map's credit lines
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

  /** The map's one attribution control, bottom right. The source lines of the B3 layers (data/map.json "hail".attribution, D29) and
      the base map's credit lines (layers.js) go in it, so the page has one block of source lines, on the first screen at phone
      width too (D44; map.css caps the block at 40vh there). Made once, when the first lines come. Leaflet's prefix is left out.
      The line is lifted above the bottom band (b3Lift). The band changes height with its contents (a source line, a layer, a turn,
      the toast) and the screen, so it is measured again when it changes, and so is the line's own height. */
  function sourceControl() {
    if (!map) return null;
    if (sourceCtl) return sourceCtl;
    sourceCtl = L.control.attribution({ prefix: false, position: "bottomright" }).addTo(map);
    if (window.ResizeObserver) {
      var band = new ResizeObserver(b3Lift);
      band.observe(el.bottom);
      band.observe(el.canvas);
      new ResizeObserver(refitForBanner).observe(sourceCtl.getContainer());   // more text, more lines: the room the fit keeps (noteRoom)
    } else window.addEventListener("resize", b3Lift);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(b3Lift);   // the band is measured in its own fonts
    b3Lift();
    return sourceCtl;
  }

  /** The B3 source lines go in the map's one attribution control (sourceControl), once, when data/map.json names them. */
  function b3Credits() {
    if (!B3 || !map || B3.credits || !(B3.h.attribution || []).length) return;
    B3.credits = true;
    var ctl = sourceControl();
    B3.h.attribution.forEach(function (line) { ctl.addAttribution(esc(line)); });
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
    if (!sourceCtl) return;
    var h = b3LiftPx();
    sourceCtl.getContainer().style.setProperty("--credit-lift", (h ? Math.ceil(h + 8) : 0) + "px");
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
