<!--
{
  "documentType" : "article",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/migrating-from-version-5-to-version-6",
  "metadataVersion" : "0.1.0",
  "role" : "article",
  "title" : "Migrating from Version 5 to Version 6"
}
-->

# Migrating from Version 5 to Version 6

Adopt modern web platform conventions introduced in MapKit JS version 6.

## Breaking Changes

### Native EventTarget Replaces MapKitEventTarget

MapKit JS version 6 removes the custom event system in favor of standard DOM APIs. All MapKit JS classes that previously extended [`MapKitEventTarget`](/documentation/MapKitJS/MapKitEventTarget) (such as [`Map`](/documentation/MapKitJS/Map), [`Annotation`](/documentation/MapKitJS/Annotation), [`TileOverlay`](/documentation/MapKitJS/TileOverlay), and the [`mapkit`](/documentation/MapKitJS/mapkit) namespace object) now extend `EventTarget`.

**The third argument to `addEventListener` has changed.** In version 5, the third argument was a `thisObject` — an object to use as `this` when calling the listener. In version 6, it’s the standard `EventListenerOptions` object, which supports `once`, `signal`, and other standard features.

```javascript
// Version 5: thisObject as third argument.
map.addEventListener("region-change-end", this.handleRegionChange, this);

// Version 6: use arrow functions for context binding.
map.addEventListener("region-change-end", (event) => this.handleRegionChange(event));

// Version 6: use standard EventListenerOptions.
map.addEventListener("region-change-end", handleRegionChange, { once: true });
```

### Null Replaces Undefined for Absent Values

MapKit JS version 6 returns `null` instead of `undefined` for optional properties and return values. This affects getters, method return values, callback parameters, event properties, and data class properties such as [`Place`](/documentation/MapKitJS/Place).

```javascript
// Version 5
if (annotation.id !== undefined) { /* ... */ }

// Version 6 — check for null.
if (annotation.id !== null) { /* ... */ }

// Version 6 — nullish check (works for both null and undefined).
if (annotation.id != null) { /* ... */ }
```

JavaScript code using truthy/falsy checks or nullish coalescing (`??`) isn’t affected.

**TypeScript:** Getter return types change from `T | undefined` to `T | null`. Code using strict equality checks against `undefined` produces type errors.

### CORS Required for Images

MapKit JS version 6 requires CORS for all images, including tile images and annotation images. When you use [`ImageSource`](/documentation/MapKitJS/ImageSource) objects such as `HTMLCanvasElement` or `HTMLImageElement`, make sure they contain only CORS-clean pixel data.

### TileOverlay Behavioral Changes

In version 6, MapKit JS no longer turns off map rotation when tile overlays are present, and zoom no longer snaps to integer levels. Tile images also require CORS, as described in [CORS Required for Images](/documentation/MapKitJS/migrating-from-version-5-to-version-6#CORS-Required-for-Images).

## Deprecations

### Callback Parameters and Cancellation in Async Service APIs

All asynchronous service methods now return `Promise` instead of `number` (request ID). You can use async/await syntax. Callbacks still work at runtime but the framework considers them deprecated. The framework also deprecates [`cancel(promise)`](/documentation/MapKitJS/Service/cancel) method accepting a numeric request ID — use `AbortController`/`AbortSignal` instead.

```javascript
// Version 5
search.search("coffee", (error, result) => {
    if (error) { console.error(error); return; }
    console.log(result.places);
});

// Version 6
try {
    const result = await search.search("coffee");
    console.log(result.places);
} catch (error) {
    console.error(error);
}
```

```javascript
// Version 5
const id = search.search("query", callback);
search.cancel(id);

// Version 6
const controller = new AbortController();
const promise = search.search("query", { signal: controller.signal });
controller.abort();
```

When you abort a request, the Promise rejects with a `DOMException` where `name === "AbortError"`, matching the `fetch()` API behavior. A new [`RequestError`](/documentation/MapKitJS/RequestError) type represents network and HTTP errors.

**TypeScript:** The return type changes from `number` to `Promise<T>`, and `cancel()` now accepts `Promise<unknown>` instead of `number`.

### MapFeatureAnnotation.fetchPlace()

Use [`getPlace(id, options)`](/documentation/MapKitJS/PlaceLookup/getPlace) instead. It returns a Promise and supports AbortSignal cancellation.

### ImageDelegate.getImageUrl()

Use [`getImage(ratio)`](/documentation/MapKitJS/ImageDelegate/getImage) instead. It returns a Promise that resolves to an [`ImageSource`](/documentation/MapKitJS/ImageSource) or URL string.

### CoordinateRegion.toMapRect()

[`toMapRect()`](/documentation/MapKitJS/CoordinateRegion/toMapRect) is mathematically imprecise and MapKit JS deprecates it in this release. Use [`MapRect`](/documentation/MapKitJS/MapRect) directly when precision matters, particularly at low zoom levels.

- Prefer [`visibleMapRect`](/documentation/MapKitJS/Map/visibleMapRect) over [`region`](/documentation/MapKitJS/Map/region) for setting the map’s visible area.
- Pass [`MapRect`](/documentation/MapKitJS/MapRect) to [`cameraBoundary`](/documentation/MapKitJS/Map/cameraBoundary) instead of [`CoordinateRegion`](/documentation/MapKitJS/CoordinateRegion).

### TileOverlay.urlTemplate Renamed to imageForTile

This release renames the `urlTemplate` property to [`imageForTile`](/documentation/MapKitJS/TileOverlay/imageForTile). The old name continues to work as a deprecated alias.

### Enumeration Accessors Moved to Top Level

Enumeration accessors previously nested on class objects are now available directly on the [`mapkit`](/documentation/MapKitJS/mapkit) namespace with singular naming. The old accessors still work but log a deprecation warning.

|Deprecated                                                                                                  |Replacement                                                                                   |
|------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
|`mapkit.Map.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/Map/MapTypes``                              |`mapkit.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/mapkit/MapType``                  |
|`mapkit.Map.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/Map/ColorSchemes``                          |`mapkit.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/mapkit/ColorScheme``              |
|`mapkit.Map.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/Map/Distances-data.var``                    |`mapkit.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/mapkit/DistanceUnitSystem``       |
|`mapkit.Map.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/Map/LoadPriorities``                        |`mapkit.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/mapkit/MapLoadPriority``          |
|`mapkit.Annotation.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/Annotation/CollisionMode-data.var``  |`mapkit.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/mapkit/AnnotationCollisionMode``  |
|`mapkit.Annotation.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/Annotation/DisplayPriority-data.var``|`mapkit.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/mapkit/AnnotationDisplayPriority``|
|`mapkit.Directions.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/Directions/Transport``               |`mapkit.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/mapkit/TransportType``            |
|`mapkit.Search.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/Search/RegionPriority-data.var``         |`mapkit.`​``doc://com.apple.mapkitjs/documentation/MapKitJS/mapkit/RegionPriority``           |

## New Features

### Wheel Events Zoom and Pan Without Holding Shift

The map now zooms and pans with wheel events without requiring you to hold the Shift key.

### mapkit.load() Returns Promise

[`load(libraryNames)`](/documentation/MapKitJS/mapkit/load) now returns `Promise<MapKit>`:

```javascript
// Version 5
mapkit.load(["map"]);
await new Promise((resolve) => {
    mapkit.addEventListener("load", resolve);
});

// Version 6
const { Map } = await mapkit.load(["map"]);
```

The `data-callback` function now also fires when libraries fail to load, so your application can handle errors instead of waiting indefinitely.

### Object Literals Accepted as Data Types

You can now pass plain object literals wherever data type class instances were previously required. New interfaces define the expected shape: [`CoordinateData`](/documentation/MapKitJS/CoordinateData), [`CoordinateRegionData`](/documentation/MapKitJS/CoordinateRegionData), [`CoordinateSpanData`](/documentation/MapKitJS/CoordinateSpanData), [`CameraZoomRangeData`](/documentation/MapKitJS/CameraZoomRangeData), [`MapPointData`](/documentation/MapKitJS/MapPointData), [`MapRectData`](/documentation/MapKitJS/MapRectData), [`MapSizeData`](/documentation/MapKitJS/MapSizeData), and [`PaddingData`](/documentation/MapKitJS/PaddingData).

```javascript
// Version 5 — class instances required.
map.region = new mapkit.CoordinateRegion(
    new mapkit.Coordinate(37.3349, -122.0090),
    new mapkit.CoordinateSpan(0.02, 0.02),
);

// Version 6 — plain objects also accepted.
map.region = {
    center: { latitude: 37.3349, longitude: -122.0090 },
    span: { latitudeDelta: 0.02, longitudeDelta: 0.02 },
};
```

Existing code using class instances continues to work because each class implements its corresponding data interface.

### ImageSource Support for Annotations

[`ImageAnnotation`](/documentation/MapKitJS/ImageAnnotation) and [`MarkerAnnotation`](/documentation/MapKitJS/MarkerAnnotation) now accept [`ImageSource`](/documentation/MapKitJS/ImageSource) objects directly, in addition to [`ImageHashObject`](/documentation/MapKitJS/ImageHashObject) and [`ImageDelegate`](/documentation/MapKitJS/ImageDelegate). You can also pass `Promise<ImageSource>` for async image loading.

### ImageSource Support for TileOverlay

[`imageForTile`](/documentation/MapKitJS/TileOverlay/imageForTile) now accepts a callback that returns [`ImageSource`](/documentation/MapKitJS/ImageSource), `Promise<ImageSource>`, or `null` for client-side tile rendering.

### PlaceLookup.getPlace(annotation) Overload

A new overload of [`getPlace(id, options)`](/documentation/MapKitJS/PlaceLookup/getPlace) accepts a [`MapFeatureAnnotation`](/documentation/MapKitJS/MapFeatureAnnotation) directly.

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)