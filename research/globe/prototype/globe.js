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
 */
(function () {
  "use strict";

  // ---- 7. Status (shared by every section) ---------------------------------------------------
  // Why in the browser: this records what the page itself did (which layers got a Cesium layer,
  // tile errors seen by the browser). The tests read it; nothing on the server depends on it.
  const status = (window.globeStatus = {
    cesium: "pending", viewer: false, tilesLoaded: false, error: null,
    drawn: {}, tileErrors: {}, alerts: {}, places: 0, layers: []
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
    li.append(el("p", "legend", layer.legend));
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
