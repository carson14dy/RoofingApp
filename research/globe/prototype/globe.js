/* globe.js: 3D storm view prototype (research; outside the app).
 *
 * Why this runs in the browser: CesiumJS draws the globe with WebGL, and hover and toggle events and
 * DOM updates only exist in the page. Everything else is decided in Python (serve.py): the layer list,
 * valid and retrieved times, freshness states, tile URLs, the radar image and its bounds, and every
 * alert's geometry. This file draws what the server gives it and changes nothing it was not given.
 *
 * Sections
 *   1. Data: fetch the JSON the server serves (plain fetch; no framework)
 *   2. Panel: one row per layer with source, times, state and legend (DOM text, never HTML)
 *   3. Imagery: Cesium imagery layers from the URL templates Python gives
 *   4. Alerts: outlines and zone-match markers from GeoJSON (no fill, no extrusion)
 *   5. Places: points whose names show while the pointer is over them (a browser-only mouse event)
 *   6. Failure handling: the 3D view can fail while the panel keeps working
 *   7. Status for tests: window.globeStatus, window.globeViewer and window.globeData
 *   8. 3D storms: MRMS voxels as Cesium points, with exaggeration, zoom and a dBZ legend. Browser-only:
 *      WebGL points, camera distance (point size) and the buttons. Python gives the positions and the state.
 */
(function () {
  "use strict";

  // ---- 7. Status (shared by every section) ---------------------------------------------------
  // Why in the browser: this records what the page itself did (which layers got a Cesium layer,
  // tile errors seen by the browser). The tests read it; nothing on the server depends on it.
  const status = (window.globeStatus = {
    cesium: "pending", viewer: false, tilesLoaded: false, error: null,
    drawn: {}, tileErrors: {}, alerts: {}, places: 0, layers: [], volume: null
  });
  window.globeViewer = null;
  window.globeData = null;

  // The Cesium Viewer's data sources and imagery layers, keyed by layer id (created in section 3 and 4).
  const imageryLayers = {};
  const dataSources = {};
  // Visibility the user chose in the panel. It is applied when the 3D view starts, so a click before
  // Cesium is ready is not lost.
  const chosenVisibility = {};

  // Stacking order, bottom first. Presentation only; Python decides which layers exist and their data.
  const DRAW_ORDER = ["bluemarble", "usgs_imagery", "goes_east_geocolor", "goes_east_band13", "nws_radar"];
  const STATE_TEXT = { live: "Live", stale: "Stale", unavailable: "Unavailable", off: "Off" };
  const ALERT_FALLBACK_COLOUR = "#e9f0f7";

  const $ = (id) => document.getElementById(id);

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  // ---- 1. Data ------------------------------------------------------------------------------
  // Why in the browser: the page has to ask the local server for its JSON. Nothing is computed here.
  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(url + " returned HTTP " + response.status);
    return response.json();
  }

  // ---- 2. Panel -----------------------------------------------------------------------------
  // Why in the browser: it is DOM. The text (state, times, legends) is the text Python wrote.
  // A row's toggle is enabled only when Python gave something to draw.
  function hasDrawableData(layer) {
    if (layer.tile_template || layer.image_url) return true;
    if (layer.draw_url && layer.voxel_count > 0) return true;
    return Array.isArray(layer.items) && layer.items.length > 0;
  }

  function linkTo(source) {
    const a = el("a", null, source.name);
    a.href = source.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }

  function kvList(pairs) {
    const list = el("dl", "kv");
    for (const [key, value] of pairs) {
      list.append(el("dt", null, key));
      const dd = el("dd");
      if (value instanceof Node) dd.append(value);
      else dd.textContent = value;
      list.append(dd);
    }
    return list;
  }

  function layerRow(layer) {
    const li = el("li", "layer");
    li.dataset.layer = layer.id;

    const head = el("div", "layer-head");
    const label = el("label", "layer-toggle");
    const box = el("input");
    box.type = "checkbox";
    box.id = "toggle-" + layer.id;
    box.disabled = !hasDrawableData(layer);
    box.checked = !box.disabled && Boolean(layer.default_on);
    box.addEventListener("change", () => setLayerVisible(layer.id, box.checked));
    label.append(box, el("span", "layer-name", layer.name));
    head.append(label, el("span", "state state-" + layer.state, STATE_TEXT[layer.state] || layer.state));
    li.append(head, el("p", "kind", layer.kind));
    if (layer.label) li.append(el("p", "label-chip", layer.label));
    li.append(el("p", "state-text", layer.state_text || ""));

    const sourceNode = layer.source && layer.source.url ? linkTo(layer.source) : (layer.source ? layer.source.name : "");
    li.append(kvList([
      ["Source", sourceNode],
      ["Valid", layer.valid_text || "No valid time"],
      ["Retrieved", layer.retrieved_text || "not applicable"],
      ["Limit", layer.freshness_limit_min ? layer.freshness_limit_min + " min (proposal)" : "none: not timed"]
    ]));
    if (layer.content_text) li.append(el("p", "note-line", layer.content_text));
    if (layer.tile_template) {
      const errors = el("p", "tile-errors", "Tile errors in this browser: " + (status.tileErrors[layer.id] || 0));
      errors.id = "tiles-" + layer.id;
      li.append(errors);
    }
    if (layer.counts) {
      const c = layer.counts;
      li.append(el("p", "counts", `Geometry: polygon ${c.polygon}, zone ${c.zone}, none ${c.none}`));
    }
    if (Array.isArray(layer.items) && layer.items.length) {
      const list = el("ul", "items");
      for (const item of layer.items) {
        if (layer.kind === "places") {
          list.append(el("li", null, `${item.name} (${item.lat.toFixed(4)}, ${item.lon.toFixed(4)})`));
        } else {
          list.append(el("li", null, `${item.event} · ${item.severity || "severity not given"} · ${item.text}`));
        }
      }
      li.append(list);
    }
    if (layer.draw_url) li.append(volumeControls(layer));  // 3D storms only: section 8
    li.append(el("p", "legend", layer.legend));
    if (layer.draw_url) li.append(dbzSwatches());
    return li;
  }

  function renderPanel(layers) {
    const list = $("layer-list");
    list.textContent = "";
    status.layers = layers.layers.map((layer) => layer.id);
    for (const layer of layers.layers) list.append(layerRow(layer));
    $("panel-stamp").textContent = "Layer list built " + layers.generated_text +
      (layers.offline ? ". Offline: live feeds are off." : ".");
  }

  function setLayerVisible(id, visible) {
    chosenVisibility[id] = visible;
    if (imageryLayers[id]) imageryLayers[id].show = visible;
    if (dataSources[id]) dataSources[id].show = visible;
    if (id === VOLUME_ID) setVolumeVisible(visible);
  }

  // ---- 3. Imagery ---------------------------------------------------------------------------
  // Why in the browser: Cesium fetches and draws image tiles, which needs WebGL and the page's origin.
  // The templates, times and bounds all come from Python.
  function imageryProviderFor(layer) {
    if (layer.tile_template) {
      return new Cesium.UrlTemplateImageryProvider({
        url: layer.tile_template,
        tilingScheme: new Cesium.WebMercatorTilingScheme(),
        maximumLevel: layer.max_zoom,
        credit: layer.source.name
      });
    }
    if (layer.image_url && layer.bounds) {
      const [west, south, east, north] = layer.bounds;
      return new Cesium.SingleTileImageryProvider({
        url: layer.image_url,
        rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north),
        credit: layer.source.name
      });
    }
    return null;
  }

  function countTileError(id) {
    status.tileErrors[id] = (status.tileErrors[id] || 0) + 1;
    const node = $("tiles-" + id);
    if (node) node.textContent = "Tile errors in this browser: " + status.tileErrors[id];
  }

  function addImagery(viewer, layer) {
    const provider = imageryProviderFor(layer);
    if (!provider) return null;
    // A tile error is a browser event: it is counted and shown, and it does not change the Python state.
    provider.errorEvent.addEventListener(() => countTileError(layer.id));
    const imagery = viewer.imageryLayers.addImageryProvider(provider);
    imagery.show = chosenVisibility[layer.id] !== undefined ? chosenVisibility[layer.id] : Boolean(layer.default_on);
    return imagery;
  }

  // ---- 4. Alerts ----------------------------------------------------------------------------
  // Why in the browser: polylines and points are Cesium entities. Only outlines are drawn: no fill,
  // no extrusion. Alerts with a polygon get an outline; zone matches get a marker at the zone centre.
  function drawAlerts(source, collection) {
    const counts = { features: 0, outlines: 0, markers: 0, noGeometry: 0 };
    for (const feature of collection.features || []) {
      counts.features += 1;
      const props = feature.properties || {};
      const colour = Cesium.Color.fromCssColorString((props.style && props.style.outline) || ALERT_FALLBACK_COLOUR);
      const geometry = feature.geometry;
      if (geometry && (geometry.type === "Polygon" || geometry.type === "MultiPolygon")) {
        const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
        for (const rings of polygons) {
          for (const ring of rings) {
            const flat = ring.flatMap((p) => [p[0], p[1]]);
            source.entities.add({
              polyline: {
                positions: Cesium.Cartesian3.fromDegreesArray(flat),
                width: 2,
                material: colour,
                arcType: Cesium.ArcType.GEODESIC
              }
            });
            counts.outlines += 1;
          }
        }
      }
      if (props.geometry_source !== "polygon" && props.marker) {
        source.entities.add({
          position: Cesium.Cartesian3.fromDegrees(props.marker[0], props.marker[1]),
          point: { pixelSize: 8, color: colour, outlineColor: Cesium.Color.BLACK, outlineWidth: 2 }
        });
        counts.markers += 1;
      } else if (!props.marker && !(geometry && geometry.type === "Point")) {
        counts.noGeometry += 1;
      }
    }
    return counts;
  }

  // ---- 5. Places ----------------------------------------------------------------------------
  // Why in the browser: the name shows while the pointer is over a point. Pointer movement and
  // picking exist only in the browser; the names and coordinates come from Python.
  function drawPlaces(viewer, source, collection) {
    const entities = [];
    for (const feature of collection.features || []) {
      const [lon, lat] = feature.geometry.coordinates;
      const name = feature.properties.name;
      entities.push(source.entities.add({
        name: name,
        position: Cesium.Cartesian3.fromDegrees(lon, lat),
        point: {
          pixelSize: 9,
          color: Cesium.Color.fromCssColorString("#e0a93c"),
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2
        },
        label: {
          text: name,
          show: false,
          font: "600 14px Inter, system-ui, sans-serif",
          fillColor: Cesium.Color.fromCssColorString("#e9f0f7"),
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(12, -12),
          disableDepthTestDistance: Number.POSITIVE_INFINITY
        }
      }));
    }
    let shown = null;
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((movement) => {
      const picked = viewer.scene.pick(movement.endPosition);
      const hit = picked && picked.id && entities.indexOf(picked.id) >= 0 ? picked.id : null;
      if (shown && shown !== hit) shown.label.show = false;
      if (hit) hit.label.show = true;
      shown = hit;
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    return entities.length;
  }

  // ---- 6. Failure handling ------------------------------------------------------------------
  // Why in the browser: only the page knows whether the library loaded and whether WebGL started.
  // The panel and its data are separate, so a failure here leaves the panel working.
  function showGlobeFailure(detail) {
    status.error = detail;
    $("globe-error-detail").textContent = detail;
    $("globe-error").hidden = false;
    $("globe-status").textContent = "3D view not running. The layer panel still works.";
  }

  // ---- 8. 3D storms (MRMS reflectivity voxels) ----------------------------------------------
  // Why in the browser: each voxel is one WebGL point (a Cesium PointPrimitive). The point size that follows
  // the camera distance, the exaggeration buttons, the zoom button and the toggle are browser events and
  // draw calls. Python (serve.py) decides which voxels exist, their dBZ values, each column's longitude,
  // each row's latitude and the heights for each exaggeration. This section only looks those up. It computes
  // no geometry of its own, and it never adds a point to the places layer.
  //
  // dBZ colour steps: the NWS reflectivity colours as MetPy 1.7.1 encodes them (colortable_files/
  // NWSReflectivity.tbl, checked 2026-10-17). That is a third-party encoding, not an NWS-published file.
  // dBZ is radar echo strength, not hail size.
  //   5-10 #00ECEC   10-15 #01A0F6   15-20 #0000F6   20-25 #00FF00   25-30 #00C800   30-35 #009000
  //   35-40 #FFFF00  40-45 #E7C000   45-50 #FF9000   50-55 #FF0000   55-60 #D60000   60-65 #C00000
  //   65-70 #FF00FF  70-75 #9955C9
  //   75 dBZ and above uses the 70-75 colour. The table's 15th entry (black) is not used.
  //   Below 5 dBZ nothing is drawn.
  const DBZ_STEPS = [
    { lo: 5, hex: "#00ECEC" }, { lo: 10, hex: "#01A0F6" }, { lo: 15, hex: "#0000F6" },
    { lo: 20, hex: "#00FF00" }, { lo: 25, hex: "#00C800" }, { lo: 30, hex: "#009000" },
    { lo: 35, hex: "#FFFF00" }, { lo: 40, hex: "#E7C000" }, { lo: 45, hex: "#FF9000" },
    { lo: 50, hex: "#FF0000" }, { lo: 55, hex: "#D60000" }, { lo: 60, hex: "#C00000" },
    { lo: 65, hex: "#FF00FF" }, { lo: 70, hex: "#9955C9" }
  ];
  const VOLUME_ID = "mrms_volume";
  // Point size: 6 px at the view's own distance. Cesium's NearFarScalar scales it with the camera distance:
  // 1.5 times when the camera is within half the view radius, 0.6 times beyond 20 view radii. The radius is
  // Python's (doc.view.radius_m).
  const POINT_PX = 6;
  const NEAR_SCALE = 1.5;
  const FAR_SCALE = 0.6;
  const volumeState = {
    doc: null, collection: null, factor: 1, visible: false, drawn: 0, skippedBelowFive: 0,
    buildMs: null, firstFrameMs: null, builds: 0, zoomClicks: 0
  };

  // The index into DBZ_STEPS for a dBZ value, or -1 below the lowest step. Arithmetic on Python's value.
  function dbzStepIndex(dbz) {
    if (dbz < DBZ_STEPS[0].lo) return -1;
    const width = DBZ_STEPS[1].lo - DBZ_STEPS[0].lo;
    return Math.min(Math.floor((dbz - DBZ_STEPS[0].lo) / width), DBZ_STEPS.length - 1);
  }

  // 3931 -> "3,931". Written out so the text is the same in every browser locale.
  function countText(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  // The status the tests read. Small on purpose: the voxel arrays and Cesium objects are not copied into it.
  function publishVolumeStatus() {
    status.volume = {
      layer: VOLUME_ID, drawn: volumeState.drawn, skippedBelowFive: volumeState.skippedBelowFive,
      drawnInFile: volumeState.doc && volumeState.doc.voxels ? volumeState.doc.voxels.length : 0,
      buildMs: volumeState.buildMs, firstFrameMs: volumeState.firstFrameMs, builds: volumeState.builds,
      factor: volumeState.factor, visible: volumeState.visible, zoomClicks: volumeState.zoomClicks
    };
    showDrawnCount();
  }

  // The panel's count: the points actually added to the 3D view (not the file's count).
  function showDrawnCount() {
    const node = $("volume-drawn");
    if (!node) return;
    node.textContent = volumeState.collection
      ? "Drawn in this view: " + countText(volumeState.drawn) + " voxels"
      : "Drawn in this view: none (the 3D view is not running)";
  }

  // The on-screen label: shows the exaggeration factor whenever the storms are on.
  function updateFactorChip() {
    const chip = $("volume-factor");
    if (!chip) return;
    chip.textContent = "Vertical exaggeration ×" + volumeState.factor +
      (volumeState.factor === 1 ? ": heights as measured" : ": heights stretched, not to scale");
    chip.hidden = !(volumeState.visible && volumeState.collection);
  }

  function setVolumeVisible(visible) {
    volumeState.visible = visible;
    if (volumeState.collection) volumeState.collection.show = visible;
    updateFactorChip();
    publishVolumeStatus();
  }

  function setVolumeFactor(factor) {
    volumeState.factor = factor;
    const viewer = window.globeViewer;
    if (viewer && volumeState.doc) buildVolume(viewer);  // the points move to the new heights
    updateFactorChip();
    publishVolumeStatus();
  }

  // Draws the voxels as points. Called once the 3D view exists, and again when the exaggeration changes.
  // Why in the browser: WebGL points, and the camera distance that sizes them, exist only in the page.
  function buildVolume(viewer) {
    const doc = volumeState.doc;
    if (!doc || !Array.isArray(doc.voxels) || doc.voxels.length === 0) {
      publishVolumeStatus();
      return;
    }
    const started = performance.now();
    if (volumeState.collection) viewer.scene.primitives.remove(volumeState.collection);  // also destroys it
    const heights = doc.heights_m[String(volumeState.factor)];
    const radius = doc.view.radius_m;
    const scale = new Cesium.NearFarScalar(radius * 0.5, NEAR_SCALE, radius * 20, FAR_SCALE);
    const colours = DBZ_STEPS.map((step) => Cesium.Color.fromCssColorString(step.hex).withAlpha(0.9));
    const points = new Cesium.PointPrimitiveCollection();
    let drawn = 0;
    let skipped = 0;
    for (const [i, j, k, dbz] of doc.voxels) {
      const step = dbzStepIndex(dbz);
      if (step < 0) {
        skipped += 1;
        continue;
      }
      points.add({
        position: Cesium.Cartesian3.fromDegrees(doc.lons[i], doc.lats[j], heights[k]),
        pixelSize: POINT_PX,
        color: colours[step],
        scaleByDistance: scale,
        disableDepthTestDistance: Number.POSITIVE_INFINITY
      });
      drawn += 1;
    }
    points.show = volumeState.visible;
    viewer.scene.primitives.add(points);
    volumeState.collection = points;
    volumeState.drawn = drawn;
    volumeState.skippedBelowFive = skipped;
    volumeState.builds += 1;
    volumeState.buildMs = Math.round((performance.now() - started) * 10) / 10;
    volumeState.firstFrameMs = null;
    const stopTiming = viewer.scene.postRender.addEventListener(() => {
      volumeState.firstFrameMs = Math.round((performance.now() - started) * 10) / 10;
      stopTiming();
    });
    status.drawn[VOLUME_ID] = "points";
    updateFactorChip();
    publishVolumeStatus();
  }

  // Browser event (the zoom button). Python gives the centre and radius; the camera looks 45 degrees down
  // so the heights, and the exaggeration, can be seen.
  function zoomToVolume() {
    volumeState.zoomClicks += 1;
    const viewer = window.globeViewer;
    const view = volumeState.doc && volumeState.doc.view;
    if (viewer && view) {
      const [lon, lat] = view.centre;
      const sphere = new Cesium.BoundingSphere(Cesium.Cartesian3.fromDegrees(lon, lat, 0), view.radius_m);
      viewer.camera.flyToBoundingSphere(sphere, {
        offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-45), view.radius_m * 3)
      });
    }
    publishVolumeStatus();
  }

  // The 3D storms row's controls: the drawn count, the exaggeration buttons and the zoom button.
  // Why in the browser: they are form controls and click events.
  function volumeControls(layer) {
    const wrap = el("div", "vol-controls");
    const drawn = el("p", "volume-drawn");
    drawn.id = "volume-drawn";
    wrap.append(drawn);
    const group = el("fieldset", "vexag");
    group.append(el("legend", "vexag-title", "Vertical exaggeration"));
    for (const factor of layer.exaggerations) {
      const option = el("label", "vexag-option");
      const input = el("input");
      input.type = "radio";
      input.name = "vexag";
      input.value = String(factor);
      input.checked = factor === volumeState.factor;
      input.addEventListener("change", () => {
        if (input.checked) setVolumeFactor(factor);
      });
      option.append(input, el("span", null, factor + "×"));
      group.append(option);
    }
    wrap.append(group);
    const zoom = el("button", "vol-zoom", "Zoom to the storm volume");
    zoom.type = "button";
    zoom.id = "zoom-volume";
    zoom.addEventListener("click", zoomToVolume);
    wrap.append(zoom);
    return wrap;
  }

  // The dBZ colour steps as swatches. DOM only; the layer's own legend text is a separate element.
  function dbzSwatches() {
    const wrap = el("div", "dbz-steps");
    DBZ_STEPS.forEach((step, k) => {
      const last = k === DBZ_STEPS.length - 1;
      const top = last ? step.lo + 5 : DBZ_STEPS[k + 1].lo;
      const item = el("span", "dbz-step");
      const swatch = el("span", "swatch");
      swatch.style.background = step.hex;
      item.append(swatch, el("span", null, step.lo + "–" + top + (last ? "+" : "") + " dBZ"));
      wrap.append(item);
    });
    return wrap;
  }

  // ---- Start-up: panel first (it needs only the server), then the 3D view --------------------
  function startViewer(layers, alerts, places) {
    let viewer;
    try {
      viewer = new Cesium.Viewer("cesiumContainer", {
        baseLayer: false, // no ion token: the base maps are added in section 3
        terrainProvider: new Cesium.EllipsoidTerrainProvider(), // flat ellipsoid; terrain is a later phase
        baseLayerPicker: false,
        geocoder: false,
        animation: false,
        timeline: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false
      });
    } catch (error) {
      showGlobeFailure("The 3D viewer could not start (" + error.message + "). This browser needs WebGL 2.");
      return;
    }
    window.globeViewer = viewer;
    status.viewer = true;
    viewer.imageryLayers.removeAll();

    const byId = {};
    for (const layer of layers.layers) byId[layer.id] = layer;
    for (const id of DRAW_ORDER) {
      if (!byId[id]) continue;
      const imagery = addImagery(viewer, byId[id]);
      if (imagery) {
        imageryLayers[id] = imagery;
        status.drawn[id] = "imagery";
      }
    }

    const alertSource = new Cesium.CustomDataSource("nws_alerts");
    viewer.dataSources.add(alertSource);
    dataSources.nws_alerts = alertSource;
    status.alerts = drawAlerts(alertSource, alerts);
    if (status.alerts.outlines + status.alerts.markers > 0) status.drawn.nws_alerts = "alerts";

    const placeSource = new Cesium.CustomDataSource("places");
    viewer.dataSources.add(placeSource);
    dataSources.places = placeSource;
    status.places = drawPlaces(viewer, placeSource, places);
    if (status.places > 0) status.drawn.places = "places";

    // The 3D storms points: their own collection, never the places layer.
    buildVolume(viewer);

    // Apply the panel's choices made before the viewer existed.
    for (const id of Object.keys(chosenVisibility)) setLayerVisible(id, chosenVisibility[id]);

    const box = layers.montana_box;
    viewer.camera.setView({ destination: Cesium.Rectangle.fromDegrees(box.west, box.south, box.east, box.north) });

    let lastText = "";
    viewer.scene.postRender.addEventListener(() => {
      status.tilesLoaded = viewer.scene.globe.tilesLoaded;
      const text = status.tilesLoaded ? "Tiles loaded for this view." : "Tiles still loading.";
      if (text !== lastText) {
        $("globe-status").textContent = "3D view running. " + text;
        lastText = text;
      }
    });
  }

  async function main() {
    let layers, alerts, places;
    try {
      [layers, alerts, places] = await Promise.all([
        getJson("/api/layers.json"), getJson("/api/alerts.json"), getJson("/api/places.json")
      ]);
    } catch (error) {
      $("panel-error").textContent = "Layer data could not load: " + error.message +
        ". Check that serve.py is still running.";
      $("panel-error").hidden = false;
      showGlobeFailure("There is no layer data to draw.");
      return;
    }
    window.globeData = { layers: layers, alerts: alerts, places: places };
    renderPanel(layers);
    // The voxels come from their own endpoint; if it fails, the panel and the other layers still work.
    try {
      volumeState.doc = await getJson("/api/volume.json");
      publishVolumeStatus();
    } catch (error) {
      status.volume = { error: "3D storms data could not load: " + error.message, drawn: 0 };
    }
    if (typeof Cesium === "undefined") {
      status.cesium = "failed";
      showGlobeFailure(window.cesiumLoadFailed
        ? "The CesiumJS library did not load from its CDN (blocked, offline, or it failed its integrity check)."
        : "The CesiumJS library is not available.");
      return;
    }
    status.cesium = "loaded";
    $("globe-status").textContent = "Starting the 3D view.";
    startViewer(layers, alerts, places);
  }

  main();
})();
