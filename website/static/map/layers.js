/* Montana Hail Watch: the base map's own drawing (DESIGN 13.1, 13.2, 13.7; D145). map.html loads it after map.js.

   Why this is JavaScript (AGENTS.md rule 4): only the browser knows which files the current view needs, and only it can draw
   them on the map. Python builds every file (website/terrain.py for the relief and the land cover tint, website/basemap2.py for
   the vector bands, the places and the summits, and the build's data/base.json for every word, credit, zoom range and rule).
   This file reads those files and draws them:
   - the terrain: the relief (h) and the land cover tint (l) as two tile layers at native zooms 5 to 10, faded from the zoom
     data/base.json "terrain.fade" gives to the zoom the layers are gone at, under the vectors. Not added in dark mode (D115(g)),
     and not while Imagery is on. A tile the store does not hold is never requested: data/base.json lists the tiles of each zoom
     (terrain.tile_runs) and the tiles that failed (terrain.layers.*.missing); any other tile is drawn as the blank GIF.
   - the vector bands: band A (one file, from its first zoom), bands B and C (the 2 by 2 and 1 by 1 degree cells in view, from
     their zooms) and band D (one shard per tile in view, from its zoom, only for a tile that was built). One canvas in the
     "vectors" pane draws the fills (reservations, forests, parks, lakes), the lines (rivers, routes), the route shields and the
     lake and river names. A feature is drawn only from its own minimum zoom ("z"). A file that fails is asked again after the
     next move; the files held are kept least recently used first, under the cap map.json gives.
   - the places and the summits: labels from places.json (once, from its first zoom) and peaks.json (once, from band B's first
     zoom). They are DOM labels, so map.js tidyLabels places them clear of the towns; a summit shows its height in feet.
   - the credit lines of data/base.json (base.credit), once each, in the attribution line.
   - the base map line of the options sheet: the problem sentence of a part that is not loaded (or of the whole base map), the
     vector words for a file that failed in view, and the water line for a listed tile in view that was not built. Nothing is
     drawn from a guess, and a missing value is never a zero.

   Every word is Python's: a sentence comes from data/base.json, a colour is a role in map.css (--map-...), and a width, a font
   size, a fill opacity and the halo come from map.css tokens. The only requests are for this site's own files.

   Interface (map.js): window.hailMapLayers.start(ctx) once data/base.json has loaded (ctx is documented at start); and
   window.hailMapLayers.update(), which asks for a redraw on the next frame after a change the base map shows.
   window.hailMapLayersTest is a test-only hook for tools/smoke_map.py (its file list, its counts and its draw times).
*/
(function () {
  "use strict";

  var BLANK = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";   // the empty tile (as map.js BLANK)
  var DEG = Math.PI / 180;
  var FORMAT = { vector: "hail-base-vector-v1", water: "hail-base-water-v1", places: "hail-base-places-v1", peaks: "hail-base-peaks-v1" };
  // the area kinds, each with the map.css role of its colour: the fill is the role at --map-fill-alpha, the outline the role
  var FILLS = [["reservation", "--map-reservation"], ["forest", "--map-forest"], ["park", "--map-park"], ["lake", "--map-water"]];
  var ROLE = { waterLine: "--map-water-line", route: "--map-route", shield: "--map-route-shield", shieldInk: "--map-route-shield-ink",
    place: "--map-place-text", placeDot: "--map-place-dot", summit: "--map-summit", summitDot: "--map-summit-dot", halo: "--map-label-halo" };

  var S = null;            // the state, made by start()

  // ------------------------------------------------------------------ small helpers

  /** Text made safe for HTML. */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** The value of a map.css token, read from the root element. */
  function token(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function tokenNum(name) { return parseFloat(token(name)) || 0; }

  /** A number as text with at least `width` digits (a tile's row and column in its name, "r0100_c0165"). */
  function pad(n, width) { var s = String(n); while (s.length < width) s = "0" + s; return s; }

  /** Whether two boxes [west, south, east, north] share an area. */
  function overlaps(a, b) { return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]; }

  /** The world-pixel projection at a scale (Web Mercator, as the B3 canvas draws). */
  function proj(lon, lat, scale) {
    var s = Math.sin(lat * DEG);
    return [(lon + 180) / 360 * scale, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * scale];
  }

  /** The world-pixel size of the map at a zoom (a tile is 256 px). */
  function scaleAt(z) { return 256 * Math.pow(2, z); }

  // ------------------------------------------------------------------ the terrain tiles

  /** A tile layer that asks only for the tiles its set holds ("z/x/y" keys in this.options.have). Any other tile is the blank
      GIF, so no request leaves for a file the store does not have, and the console has no 404 from one. */
  var Terrain = L.TileLayer.extend({
    getTileUrl: function (coords) {
      var key = coords.z + "/" + coords.x + "/" + coords.y;
      return this.options.have[key] ? L.TileLayer.prototype.getTileUrl.call(this, coords) : BLANK;
    }
  });

  /** The "z/x/y" keys a layer holds: the runs of the tile set (terrain.tile_runs) less the tiles that failed. */
  function haveSet(runs, missing) {
    var miss = {}, have = {};
    (missing || []).forEach(function (k) { miss[k] = true; });
    Object.keys(runs || {}).forEach(function (z) {
      (runs[z] || []).forEach(function (run) {
        for (var x = run[1]; x <= run[2]; x++) {
          var key = z + "/" + x + "/" + run[0];
          if (!miss[key]) have[key] = true;
        }
      });
    });
    return have;
  }

  /** The fade of the terrain at a zoom: 1 up to terrain.fade.full_zoom, then straight down to 0 at gone_zoom. */
  function fadeAt(z) {
    var f = S.T && S.T.fade;
    if (!f || z <= f.full_zoom) return 1;
    return Math.max(0, Math.min(1, (f.gone_zoom - z) / (f.gone_zoom - f.full_zoom)));
  }

  /** The two terrain layers, made once: the tint (l) first, so the relief (h) lies over it. */
  function makeTerrain() {
    var T = S.T;
    if (!T || (T.state !== "loaded" && T.state !== "partial") || !T.layers || !T.tile_runs) return;   // the terrain is drawn only when loaded or partial
    var zooms = T.zooms || [], first = zooms[0], last = zooms[zooms.length - 1];
    var gone = T.fade ? T.fade.gone_zoom : last + 1;
    ["l", "h"].forEach(function (key) {
      var lay = T.layers[key];
      if (!lay || lay.state === "unavailable" || !lay.template) return;
      var layer = new Terrain(S.root + lay.template, {
        pane: "terrain", tileSize: T.tile_px || 256, minZoom: first, maxNativeZoom: last, maxZoom: gone - 1,
        errorTileUrl: BLANK, className: key === "h" ? "terrain-relief" : "terrain-tint", keepBuffer: 1,
        have: haveSet(T.tile_runs, lay.missing)
      });
      if (key === "h") S.relief = layer; else S.tint = layer;
    });
  }

  /** Adds the terrain layers unless the page is in dark mode or on Imagery, and removes them when it is. */
  function syncTerrain() {
    var want = !(S.dark && S.dark.matches) && !S.ctx.imagery();
    [S.tint, S.relief].forEach(function (layer) {
      if (!layer) return;
      var has = S.map.hasLayer(layer);
      if (want && !has) layer.addTo(S.map);
      else if (!want && has) S.map.removeLayer(layer);
    });
  }

  /** The opacity of each layer at the map's zoom: the relief fades with fadeAt; the tint is its own strength (--map-tint-opacity)
      at the same fade. */
  function fadeTerrain() {
    var f = fadeAt(S.map.getZoom());
    if (f === S.fade) return;                       // setOpacity restyles every loaded tile: only on a change
    S.fade = f;
    if (S.relief) S.relief.setOpacity(f);
    if (S.tint) S.tint.setOpacity(f * S.tintOpacity);
  }

  // ------------------------------------------------------------------ the files: the cache

  /** The site address of a file named by a template ({cell} or {tile}). */
  function fileUrl(template, name) { return S.root + template.replace("{cell}", name).replace("{tile}", name); }

  /** A file's features, places or summits, with each feature's box [west, south, east, north] for the view test. */
  function prepare(doc, kind) {
    if (kind === "places") return doc.places || [];
    if (kind === "peaks") return doc.peaks || [];
    var feats = doc.features || [];
    feats.forEach(function (f) {
      var w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
      (f.g || []).forEach(function (part) {
        part.forEach(function (p) {
          if (p[0] < w) w = p[0];
          if (p[0] > e) e = p[0];
          if (p[1] < s) s = p[1];
          if (p[1] > n) n = p[1];
        });
      });
      f.b = [w, s, e, n];
    });
    return feats;
  }

  /** Asks for a file once. Its entry is "loading" until it answers, then "ready" with its data and its bytes. A file that fails
      is noted with its reason and is asked again after the next move (S.gen). */
  function loadFile(url, kind, format) {
    var e = { kind: kind, state: "loading", data: null, bytes: 0 };
    S.cache.set(url, e);
    S.fetches.push(url);
    fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.text();
    }).then(function (text) {
      var doc = JSON.parse(text);
      if (!doc || doc.f !== format) throw new Error("format");
      e.data = prepare(doc, kind);
      e.bytes = text.length;
      e.state = "ready";
      S.bytes += e.bytes;
      evict();
    }).then(null, function (err) {
      if (S.cache.get(url) === e) S.cache.delete(url);
      S.failedAt[url] = S.gen;
      S.failures.push({ url: url, kind: kind, reason: err && err.message ? err.message : "load" });
    }).then(scheduleDraw, scheduleDraw);
  }

  /** The bytes of the ready files in view (the ones the last draw asked for): the cache may stay over its cap only for these
      (the test hook reports them, so the smoke can check the cap). */
  function pinnedSize() {
    var n = 0;
    S.cache.forEach(function (e, url) { if (e.state === "ready" && S.pinned[url]) n += e.bytes; });
    return n;
  }

  /** Drops the least recently used ready files until the cache is under its cap; the files in view (S.pinned) stay. */
  function evict() {
    if (S.bytes <= S.cap) return;
    var keys = [];
    S.cache.forEach(function (e, url) { keys.push(url); });
    for (var i = 0; i < keys.length && S.bytes > S.cap; i++) {
      var e = S.cache.get(keys[i]);
      if (!e || e.state !== "ready" || S.pinned[keys[i]]) continue;
      S.cache.delete(keys[i]);
      S.bytes -= e.bytes;
    }
  }

  /** The ready entry of a file (its data), or null while it loads. Asks for it when it is not held and did not fail on this move.
      A ready entry moves to the end of the cache order, so the least recently used goes first. */
  function need(url, kind, format) {
    S.pinned[url] = true;
    var e = S.cache.get(url);
    if (!e) {
      if (S.failedAt[url] === S.gen) S.failedNow = true;
      else loadFile(url, kind, format);
      return null;
    }
    if (e.state !== "ready") return null;
    S.cache.delete(url);
    S.cache.set(url, e);
    return e;
  }

  // ------------------------------------------------------------------ the view: the cells, the tiles and what is listed

  /** The box [west, south, east, north] of a cell named "n44w106" (its south-west corner, 44 N and 106 W), of a size in degrees. */
  function cellBox(name, size) {
    var m = /^([ns])(\d+)([ew])(\d+)$/.exec(name);
    if (!m) return null;
    var lat = Number(m[2]) * (m[1] === "s" ? -1 : 1), lon = Number(m[4]) * (m[3] === "w" ? -1 : 1);
    return [lon, lat, lon + size, lat + size];
  }

  /** The box of a band D tile (row r, column c) from the grid in map.json: the tile is the grid's tile cells square. */
  function tileBox(r, c) {
    var g = S.grid, step = g.cell_deg * g.tile_cells, west = g.col0_lon - g.cell_deg / 2 + c * step;
    var north = g.row0_lat + g.cell_deg / 2 - r * step;
    return [west, north - step, west + step, north];
  }

  /** The tile name the build writes ("r0100_c0165"). */
  function tileName(r, c) { return "r" + pad(r, 4) + "_c" + pad(c, 4); }

  /** Whether the store lists a tile (map.json hail.tile_split: each row's runs of columns, first and last inclusive). A tile with
      no run has no Montana cell. */
  function tileListed(r, c) {
    var runs = (S.split && S.split[String(r)]) || [];
    return runs.some(function (run) { return c >= run[0] && c <= run[1]; });
  }

  /** The band D tiles that a view touches: [{name, r, c, box}]. A view far larger than a phone's lists none. */
  function tilesIn(vb) {
    var g = S.grid, step = g.cell_deg * g.tile_cells, out = [];
    var top = g.row0_lat + g.cell_deg / 2, left = g.col0_lon - g.cell_deg / 2;
    var r0 = Math.max(0, Math.floor((top - vb[3]) / step)), r1 = Math.max(0, Math.floor((top - vb[1]) / step));
    var c0 = Math.max(0, Math.floor((vb[0] - left) / step)), c1 = Math.max(0, Math.floor((vb[2] - left) / step));
    if ((r1 - r0 + 1) * (c1 - c0 + 1) > 400) return out;
    for (var r = r0; r <= r1; r++) {
      for (var c = c0; c <= c1; c++) out.push({ name: tileName(r, c), r: r, c: c, box: tileBox(r, c) });
    }
    return out;
  }

  /** The map.css tokens the drawing uses: the colours of each role (read again on a change of colour scheme), the widths, the
      alphas, the label and shield sizes and the font. */
  function tokens() {
    S.col = {};
    FILLS.forEach(function (f) { S.col[f[1]] = token(f[1]); });
    Object.keys(ROLE).forEach(function (k) { S.col[ROLE[k]] = token(ROLE[k]); });
    S.w = { riverA: tokenNum("--map-river-w-a"), riverB: tokenNum("--map-river-w-b"), riverC: tokenNum("--map-river-w-c"),
      riverD: tokenNum("--map-river-w-d"), routeA: tokenNum("--map-route-w-a"), routeB: tokenNum("--map-route-w-b"),
      fillLine: tokenNum("--map-fill-line-w"), halo: tokenNum("--map-label-halo-w") };
    S.fillAlpha = parseFloat(token("--map-fill-alpha")) || 0;
    S.tintOpacity = parseFloat(token("--map-tint-opacity")) || 0;
    S.labelSize = tokenNum("--map-label-size");
    S.labelGap = tokenNum("--map-label-gap");
    S.shieldSize = tokenNum("--map-shield-size");
    S.shieldRadius = tokenNum("--map-shield-radius");
    S.font = token("--font");
  }

  // ------------------------------------------------------------------ the draw

  /** Schedules one draw on the next frame: several changes in one frame make one draw. */
  function scheduleDraw() {
    if (!S || S.queued) return;
    S.queued = true;
    (window.requestAnimationFrame || function (f) { setTimeout(f, 0); })(function () { S.queued = false; draw(); });
  }

  /** The base map line for the sheet: the problem of each part that is not loaded, the vector words for a file that failed in
      view, and the water line for a listed tile in view that was not built. Unique sentences, in that order. */
  function baseLine() {
    var words = S.ctx.sheet() || {}, parts = [], T = S.T, V = S.V;
    if (S.block.state === "unavailable" && S.block.problem) parts.push(S.block.problem);
    if (T && T.state !== "loaded" && T.problem) parts.push(T.problem);
    var vb = S.vBlock;                     // the block, not the drawn part: a part that is not drawn still says why
    if (vb && vb.state !== "loaded" && vb.problem) parts.push(vb.problem);
    if (S.failedNow && V && V.words && V.words.unavailable) parts.push(V.words.unavailable);
    if (S.unbuiltNow && words.water_line_unavailable) parts.push(words.water_line_unavailable);
    return parts.filter(function (p, i) { return !!p && parts.indexOf(p) === i; }).join(" ");
  }

  /** Sets the sheet's base map line (map.js shows it, with the imagery legend when Imagery is on). Passed on only on a change. */
  function setLine(text) {
    if (text === S.lineText) return;
    S.lineText = text;
    S.ctx.setLine(text);
  }

  /** The credit lines of data/base.json (base.credit), once each, in the attribution line beside the source lines. */
  function addCredits() {
    if (S.creditsAdded) return;
    S.creditsAdded = true;
    var lines = S.block.credit || [];
    S.attr = S.ctx.attribution();          // map.js's one attribution control: the B3 source lines are in it too (D44)
    lines.forEach(function (line) { S.attr.addAttribution(esc(line)); });
    S.creditCount = lines.length;
  }

  /** Reads the files of the view (asking for the missing ones), then draws the bands that are ready in it. */
  function draw() {
    if (!S) return;
    var t0 = performance.now(), map = S.map, z = map.getZoom(), size = map.getSize(), cv = S.canvas, g = S.g;
    var dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(size.x * dpr) || cv.height !== Math.round(size.y * dpr)) {
      cv.width = Math.round(size.x * dpr); cv.height = Math.round(size.y * dpr);
    }
    cv.style.width = size.x + "px"; cv.style.height = size.y + "px";
    L.DomUtil.setPosition(cv, map.containerPointToLayerPoint([0, 0]));
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, size.x, size.y);
    syncTerrain();
    fadeTerrain();
    S.failedNow = false;
    S.unbuiltNow = false;
    if (S.ctx.imagery() || !S.V) {                    // Imagery is on (the vectors are not drawn over a photo) or no vectors
      S.placeGroup.clearLayers();
      S.markers = {};
      S.counts = { places: 0, summits: 0, water: 0, shields: 0 };
      setLine(S.ctx.imagery() ? "" : baseLine());
      return;
    }
    var b = map.getBounds(), vb = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    var V = S.V, pinned = {}, cells = S.block.cells || {}, cellsDeg = V.cells_deg || {}, bands = [], drew = false;
    S.pinned = pinned;
    // band A: one file, from its first zoom; each feature is drawn from its own zoom
    if (z >= S.zA) { var a = need(S.urls.a, "vector", FORMAT.vector); if (a) bands.push({ band: "A", feats: a.data }); }
    // bands B and C: the cells in view, from their zooms
    if (z >= S.zB) (cells.B || []).forEach(function (name) {
      var box = cellBox(name, cellsDeg.B || 0);
      if (box && overlaps(box, vb)) { var e = need(fileUrl(V.tiles.b, name), "vector", FORMAT.vector); if (e) bands.push({ band: "B", feats: e.data }); }
    });
    if (z >= S.zC) (cells.C || []).forEach(function (name) {
      var box = cellBox(name, cellsDeg.C || 0);
      if (box && overlaps(box, vb)) { var e = need(fileUrl(V.tiles.c, name), "vector", FORMAT.vector); if (e) bands.push({ band: "C", feats: e.data }); }
    });
    // band D: one shard per tile in view, for a tile that was built; a listed tile that was not built is said in the line
    if (z >= S.zD && S.grid) {
      var built = {};
      (cells.D || []).forEach(function (name) { built[name] = true; });
      tilesIn(vb).forEach(function (t) {
        if (built[t.name]) { var e = need(fileUrl(V.tiles.w, t.name), "water", FORMAT.water); if (e) bands.push({ band: "D", feats: e.data }); }
        else if (tileListed(t.r, t.c)) S.unbuiltNow = true;
      });
    }
    // the places (once, from their first zoom) and the summits (from band B's first zoom): labels, drawn below
    var places = need(S.urls.places, "places", FORMAT.places);
    var peaks = z >= S.zB ? need(S.urls.peaks, "peaks", FORMAT.peaks) : null;
    // the canvas: the fills, then the lines, then the names and the shields over them
    var scale = scaleAt(z), c = map.getCenter(), wc = proj(c.lng, c.lat, scale), pc = map.latLngToContainerPoint(c);
    var ox = pc.x - wc[0], oy = pc.y - wc[1];
    g.lineJoin = "round"; g.lineCap = "round";
    drawFills(bands, vb, z, scale, ox, oy);
    var labels = drawLines(bands, vb, z, scale, ox, oy);
    drawLabels(labels, scale, ox, oy);
    setPlaces(z, vb, places, peaks);
    if (bands.length || S.relief || S.tint) { addCredits(); drew = true; }
    setLine(baseLine());
    S.app && S.app.classList.toggle("base-water", bands.some(function (bd) { return bd.band === "A"; }));
    if (drew) S.draws.push(performance.now() - t0);
    if (S.draws.length > 50) S.draws.shift();
    evict();
  }

  /** The area kinds: one path per kind, filled at the fill alpha of its role. The outlines come after every fill, last kind first,
      so the first kind in FILLS (a reservation) is outlined on top and its edge is not painted over by a forest or park beside it. */
  function drawFills(bands, vb, z, scale, ox, oy) {
    var g = S.g, outlines = [];
    FILLS.forEach(function (fill) {
      var kind = fill[0], col = S.col[fill[1]], path = new Path2D(), any = false;
      bands.forEach(function (bd) {
        bd.feats.forEach(function (f) {
          if (f.k !== kind || f.z > z || !overlaps(f.b, vb)) return;
          any = true;
          (f.g || []).forEach(function (ring) {
            ring.forEach(function (p, i) {
              var q = proj(p[0], p[1], scale);
              if (i === 0) path.moveTo(q[0] + ox, q[1] + oy); else path.lineTo(q[0] + ox, q[1] + oy);
            });
            path.closePath();
          });
        });
      });
      if (!any) return;
      g.globalAlpha = S.fillAlpha;
      g.fillStyle = col;
      g.fill(path, "evenodd");
      g.globalAlpha = 1;
      outlines.push({ col: col, path: path });
    });
    g.lineWidth = S.w.fillLine;
    for (var i = outlines.length - 1; i >= 0; i--) {
      g.strokeStyle = outlines[i].col;
      g.stroke(outlines[i].path);
    }
  }

  /** The rivers and the routes, one path per band and kind at the band's width. Returns the names to draw: each lake's name at its
      label point, each river's and each route's on its longest piece in view (one name per name and id, so a feature reaching
      into two files is named once). */
  function drawLines(bands, vb, z, scale, ox, oy) {
    var g = S.g, pieces = {}, names = [];
    var width = { river: { A: S.w.riverA, B: S.w.riverB, C: S.w.riverC, D: S.w.riverD },
                  route: { A: S.w.routeA, B: S.w.routeB, C: S.w.routeB, D: S.w.routeB } };
    bands.forEach(function (bd) {
      ["river", "route"].forEach(function (kind) {
        var col = S.col[kind === "river" ? ROLE.waterLine : ROLE.route], any = false;
        g.beginPath();
        bd.feats.forEach(function (f) {
          if (f.k !== kind || f.z > z || !overlaps(f.b, vb)) return;
          any = true;
          (f.g || []).forEach(function (path) {
            path.forEach(function (p, i) {
              var q = proj(p[0], p[1], scale);
              if (i === 0) g.moveTo(q[0] + ox, q[1] + oy); else g.lineTo(q[0] + ox, q[1] + oy);
            });
          });
          if (f.n) {
            var key = kind + "|" + f.id + "|" + f.n, best = pieces[key];
            if (!best || (f.size || 0) > (best.size || 0)) pieces[key] = { kind: kind, size: f.size, n: f.n, s: f.s, path: f.g };
          }
        });
        if (!any) return;
        g.lineWidth = width[kind][bd.band];
        g.strokeStyle = col;
        g.stroke();
      });
      bd.feats.forEach(function (f) {
        if (f.k === "lake" && f.n && f.l && f.z <= z && overlaps(f.b, vb)) names.push({ kind: "water", text: f.n, p: f.l });
      });
    });
    Object.keys(pieces).forEach(function (key) {
      var pc = pieces[key];
      if (pc.kind === "route") {
        var mid = midpoint(pc.path);                // the shield carries the route's text as the data gives it ("US-191", "MT-20")
        if (mid) names.push({ kind: "shield", text: pc.n, p: mid });
      } else {
        var at = midpoint(pc.path);
        if (at) names.push({ kind: "water", text: pc.n, p: at });
      }
    });
    return names;
  }

  /** The middle vertex of a line's longest path. */
  function midpoint(paths) {
    var p = paths[0] || [];
    return p.length ? p[p.length >> 1] : null;
  }

  /** The boxes (container px) the names keep off: the towns, with their bubbles and names (they keep their priority), and the
      place and summit labels. */
  function domBoxes(rect) {
    var out = [], nodes = S.map.getContainer().querySelectorAll(".town .bubble, .town .tname, .base-label span");
    for (var i = 0; i < nodes.length; i++) {
      var r = nodes[i].getBoundingClientRect();
      if (r.width && r.height) out.push([r.left - rect.left, r.top - rect.top, r.right - rect.left, r.bottom - rect.top]);
    }
    return out;
  }

  /** The names and the shields, each where it fits: shields first (they carry the route numbers), then the water names. A name is
      left out when its box meets a box already placed or a town or label. */
  function drawLabels(names, scale, ox, oy) {
    var g = S.g, rect = S.canvas.getBoundingClientRect(), taken = domBoxes(rect), water = 0, shields = 0;
    names.sort(function (a, b) { return (a.kind === "shield" ? 0 : 1) - (b.kind === "shield" ? 0 : 1); });
    names.forEach(function (nm) {
      var q = proj(nm.p[0], nm.p[1], scale), x = q[0] + ox, y = q[1] + oy, shield = nm.kind === "shield";
      if (x < 0 || y < 0 || x > rect.width || y > rect.height) return;
      var px = shield ? S.shieldSize : S.labelSize;
      g.font = (shield ? "700 " : "600 ") + px + "px " + S.font;
      var w = g.measureText(nm.text).width + (shield ? 8 : 2 * S.labelGap), h = px + (shield ? 6 : S.labelGap);
      var box = [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
      for (var i = 0; i < taken.length; i++) if (overlaps(box, taken[i])) return;
      taken.push(box);
      g.textAlign = "center";
      g.textBaseline = "middle";
      if (shield) {
        g.beginPath();
        roundRect(g, box[0], box[1], w, h, S.shieldRadius);
        g.fillStyle = S.col[ROLE.shield];
        g.fill();
        g.lineWidth = S.w.fillLine;
        g.strokeStyle = S.col[ROLE.route];
        g.stroke();
        g.fillStyle = S.col[ROLE.shieldInk];
        g.fillText(nm.text, x, y);
        shields++;
      } else {
        g.lineWidth = S.w.halo;
        g.strokeStyle = S.col[ROLE.halo];
        g.strokeText(nm.text, x, y);
        g.fillStyle = S.col[ROLE.waterLine];
        g.fillText(nm.text, x, y);
        water++;
      }
    });
    S.counts = S.counts || {};
    S.counts.water = water;
    S.counts.shields = shields;
  }

  /** A rounded rectangle path (a route shield). */
  function roundRect(g, x, y, w, h, r) {
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  // ------------------------------------------------------------------ the places and the summits (DOM labels)

  /** The places and the summits of the view, as DOM labels from their zoom. A label that stays in view keeps its marker; only the
      labels that come into view are made and only those that leave are removed, and map.js tidyLabels (which places them clear of
      the towns, the notes and the chip) runs only when a label was made or removed. */
  function setPlaces(z, vb, places, peaks) {
    if (places) S.placesDoc = places.data;
    if (peaks) S.peaksDoc = peaks.data;
    var inView = function (p) { return p.lon >= vb[0] && p.lon <= vb[2] && p.lat >= vb[1] && p.lat <= vb[3]; };
    var pdoc = S.placesDoc || [], sdoc = z >= S.zB ? (S.peaksDoc || []) : [], want = {}, counts = { places: 0, summits: 0 };
    pdoc.forEach(function (p, i) {
      if (p.min_zoom <= z && inView(p) && counts.places < S.labelCap) { counts.places++; want["p" + i] = function () { return placeLabel(p); }; }
    });
    sdoc.forEach(function (p, i) {
      if (p.min_zoom <= z && inView(p) && hasHeight(p) && counts.summits < S.labelCap) { counts.summits++; want["s" + i] = function () { return summitLabel(p); }; }
    });
    var changed = false;
    Object.keys(S.markers).forEach(function (k) {
      if (!want[k]) { S.placeGroup.removeLayer(S.markers[k]); delete S.markers[k]; changed = true; }
    });
    Object.keys(want).forEach(function (k) {
      if (!S.markers[k]) { S.markers[k] = want[k](); S.placeGroup.addLayer(S.markers[k]); changed = true; }
    });
    if (changed && S.ctx.tidy) S.ctx.tidy();
    S.counts = S.counts || {};
    S.counts.places = counts.places;
    S.counts.summits = counts.summits;
    S.app && S.app.classList.toggle("base-places", !!S.placesDoc);
  }

  /** A place: its dot and its name (map.css base-label, base-place). */
  function placeLabel(p) {
    return L.marker([p.lat, p.lon], {
      pane: "labels", interactive: false, keyboard: false,
      icon: L.divIcon({ className: "bm-label base-label base-place", html: "<i></i><span>" + esc(p.name) + "</span>", iconSize: [0, 0], iconAnchor: [0, 0] })
    });
  }

  /** A summit is labelled only with a height that is a number: a missing height is left out, never shown as zero (rule 3). */
  function hasHeight(p) { return typeof p.elev_ft === "number" && isFinite(p.elev_ft); }

  /** A summit: its name and its height in feet, in the sheet's words (sheet.summit_height holds the unit and one placeholder). */
  function summitLabel(p) {
    var words = S.ctx.sheet() || {}, tpl = words.summit_height || "", ph = /\{[a-z_]+\}/.exec(tpl);
    var num = new Intl.NumberFormat("en-US").format(Math.round(p.elev_ft));
    var name = ph ? p.name + " " + tpl.replace(ph[0], num) : p.name;     // no height word, no height: a bare number is never shown
    return L.marker([p.lat, p.lon], {
      pane: "labels", interactive: false, keyboard: false,
      icon: L.divIcon({ className: "bm-label base-label base-summit", html: "<i></i><span>" + esc(name) + "</span>",
        iconSize: [0, 0], iconAnchor: [0, 0] })
    });
  }

  // ------------------------------------------------------------------ start

  /** Starts the base map (map.js calls it once data/base.json has loaded). ctx:
      map (the Leaflet map, with the panes "terrain" and "vectors" that map.js makes), root (the site's address, ending in "/"),
      block (data/base.json's base block), grid (map.json hail.grid, or null), tileSplit (map.json hail.tile_split, or null), cap
      (the cache cap in bytes: map.json hail.draw.cache_bytes), sheet() (the sheet's words), setLine(text) (the sheet's base map
      line), tidy() (map.js tidyLabels), attribution() (map.js's one attribution control, bottom right: the credit lines go in it), imagery() (true while Imagery is on) and app (the page's main element: it gets the classes
      base-water and base-places while those are drawn). Nothing is fetched here; the first draw asks for the files of the view. */
  function start(ctx) {
    if (S || !ctx || !ctx.map || !ctx.block) return;
    var block = ctx.block, live = block.state !== "unavailable";      // an unavailable base map draws nothing (D145(d)); its line says why
    var T = live ? (block.terrain || null) : null, V = live ? (block.vector || null) : null;
    var vBlock = V;                        // the vector block as data/base.json gives it (its state and problem): the sheet line reads it
    if (V && (V.state === "unavailable" || !V.tiles)) V = null;
    var zooms = V && V.zooms ? V.zooms : {};
    S = {
      ctx: ctx, map: ctx.map, root: ctx.root || "", block: block, T: T, V: V, vBlock: vBlock, grid: ctx.grid || null, split: ctx.tileSplit || null,
      app: ctx.app || null, cap: ctx.cap || 0,
      zA: zooms.A ? zooms.A[0] : Infinity, zB: zooms.B ? zooms.B[0] : Infinity, zC: zooms.C ? zooms.C[0] : Infinity,
      zD: zooms.D ? zooms.D[0] : Infinity,
      urls: V ? { a: (ctx.root || "") + V.tiles.a, places: (ctx.root || "") + V.tiles.places, peaks: (ctx.root || "") + V.tiles.peaks } : {},
      cache: new Map(), bytes: 0, pinned: {}, gen: 0, failedAt: {}, failures: [], fetches: [], draws: [],
      failedNow: false, unbuiltNow: false, queued: false, lineText: null, creditsAdded: false, creditCount: 0,
      placesDoc: null, peaksDoc: null, markers: {}, counts: { places: 0, summits: 0, water: 0, shields: 0 }, labelCap: 600,
      relief: null, tint: null, fade: null, attr: null, dark: window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null
    };
    makeTerrain();
    tokens();
    S.canvas = document.createElement("canvas");
    S.canvas.className = "base-canvas";
    S.canvas.setAttribute("aria-hidden", "true");
    ctx.map.getPane("vectors").appendChild(S.canvas);
    S.g = S.canvas.getContext("2d");
    S.placeGroup = L.layerGroup().addTo(ctx.map);
    ctx.map.on("moveend", function () { S.gen++; scheduleDraw(); });
    ctx.map.on("zoomend", function () { fadeTerrain(); });
    ctx.map.on("resize", scheduleDraw);
    var again = function () { tokens(); syncTerrain(); fadeTerrain(); scheduleDraw(); };
    if (S.dark && S.dark.addEventListener) S.dark.addEventListener("change", again);
    else if (S.dark && S.dark.addListener) S.dark.addListener(again);
    window.hailMapLayersTest = {
      stats: function () {
        var loaded = {};
        S.cache.forEach(function (e, url) { if (e.state === "ready") loaded[url] = e.kind; });
        return { fetched: S.fetches.slice(), failures: S.failures.slice(), loaded: loaded, bytes: S.bytes, pinnedBytes: pinnedSize(), cap: S.cap,
          cached: S.cache.size, draws: S.draws.slice(), counts: S.counts, line: S.lineText || "", credits: S.creditCount,
          unbuilt: S.unbuiltNow, failed: S.failedNow,
          relief: !!(S.relief && S.map.hasLayer(S.relief)), tint: !!(S.tint && S.map.hasLayer(S.tint)),
          reliefOpacity: S.relief && S.map.hasLayer(S.relief) ? S.relief.options.opacity : null,
          dark: !!(S.dark && S.dark.matches), zoom: S.map.getZoom(), base: block.state,
          view: (function () { var b = S.map.getBounds(); return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]; })(),
          vector: S.vBlock ? S.vBlock.state : null, terrain: T ? T.state : null };
      },
      reset: function () { S.fetches = []; S.draws = []; S.failures = []; },
      redraw: function () { draw(); return S.draws.slice(); }
    };
    scheduleDraw();
  }

  window.hailMapLayers = { start: start, update: scheduleDraw };
})();
