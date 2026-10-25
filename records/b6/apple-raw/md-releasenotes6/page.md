<!--
{
  "documentType" : "article",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/mapkit-js-6",
  "metadataVersion" : "0.1.0",
  "role" : "article",
  "title" : "MapKit JS 6"
}
-->

# MapKit JS 6

Use the most up-to-date version of MapKit JS on your website.

## Discussion

This document includes release notes for updates to MapKit JS 6. You can learn more about MapKit JS version numbers and how to automatically link to the latest available version in [Loading the latest version of MapKit JS](/documentation/MapKitJS/loading-the-latest-version-of-mapkit-js).

### 6.0

MapKit JS 6.0 adopts modern web platform conventions. For detailed guidance on updating your code, see [Migrating from Version 5 to Version 6](/documentation/MapKitJS/migrating-from-version-5-to-version-6).

#### New features

- The map now zooms and pans with wheel events without requiring someone to hold the Shift key.
- [`load(libraryNames)`](/documentation/MapKitJS/mapkit/load) now returns `Promise<MapKit>`, and the `data-callback` function now also fires when libraries fail to load.
- You can now pass plain object literals in place of data type class instances. New interfaces define the expected shape: [`CoordinateData`](/documentation/MapKitJS/CoordinateData), [`CoordinateRegionData`](/documentation/MapKitJS/CoordinateRegionData), [`CoordinateSpanData`](/documentation/MapKitJS/CoordinateSpanData), [`CameraZoomRangeData`](/documentation/MapKitJS/CameraZoomRangeData), [`MapPointData`](/documentation/MapKitJS/MapPointData), [`MapRectData`](/documentation/MapKitJS/MapRectData), [`MapSizeData`](/documentation/MapKitJS/MapSizeData), and [`PaddingData`](/documentation/MapKitJS/PaddingData).
- [`ImageAnnotation`](/documentation/MapKitJS/ImageAnnotation) and [`MarkerAnnotation`](/documentation/MapKitJS/MarkerAnnotation) now accept [`ImageSource`](/documentation/MapKitJS/ImageSource) objects directly, in addition to [`ImageHashObject`](/documentation/MapKitJS/ImageHashObject) and [`ImageDelegate`](/documentation/MapKitJS/ImageDelegate). You can also pass `Promise<ImageSource>` for async image loading.
- The [`TileOverlay`](/documentation/MapKitJS/TileOverlay) [`imageForTile`](/documentation/MapKitJS/TileOverlay/imageForTile) callback now accepts [`ImageSource`](/documentation/MapKitJS/ImageSource), `Promise<ImageSource>`, or `null` for client-side tile rendering.
- A new overload of [`getPlace(id, options)`](/documentation/MapKitJS/PlaceLookup/getPlace) accepts a [`MapFeatureAnnotation`](/documentation/MapKitJS/MapFeatureAnnotation) directly.

#### Updates

- All MapKit JS classes that previously extended [`MapKitEventTarget`](/documentation/MapKitJS/MapKitEventTarget) now extend the native `EventTarget` interface. The third argument to `addEventListener` is now the standard `EventListenerOptions` object instead of a `thisObject`.
- Optional properties and return values now return `null` instead of `undefined` for absent values.
- Images, including tile images and annotation images, now require CORS. [`ImageSource`](/documentation/MapKitJS/ImageSource) objects must contain only CORS-clean pixel data.
- [`TileOverlay`](/documentation/MapKitJS/TileOverlay) no longer turns off map rotation or snaps zoom to integer levels.

#### Deprecated features

The framework has deprecated the following:

- Callback parameters and numeric request IDs in asynchronous service APIs. Use `Promise`-based return values with async/await, and `AbortController`/`AbortSignal` for cancellation.
- [`fetchPlace(callback)`](/documentation/MapKitJS/MapFeatureAnnotation/fetchPlace) , use [`getPlace(id, options)`](/documentation/MapKitJS/PlaceLookup/getPlace) instead.
- [`getImageUrl(ratio, callback)`](/documentation/MapKitJS/ImageDelegate/getImageUrl), use [`getImage(ratio)`](/documentation/MapKitJS/ImageDelegate/getImage) instead.
- [`toMapRect()`](/documentation/MapKitJS/CoordinateRegion/toMapRect) because it’s mathematically imprecise. Use [`MapRect`](/documentation/MapKitJS/MapRect) directly.
- This release renames the `urlTemplate` property on [`TileOverlay`](/documentation/MapKitJS/TileOverlay) to [`imageForTile`](/documentation/MapKitJS/TileOverlay/imageForTile).
- Enumeration accessors like `mapkit.Map.MapTypes` now live at the top level of the [`mapkit`](/documentation/MapKitJS/mapkit) namespace with singular names like [`MapType`](/documentation/MapKitJS/MapType).

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)