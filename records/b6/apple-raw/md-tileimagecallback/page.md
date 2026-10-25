<!--
{
  "availability" : [
    "MapKit JS: 6.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/TileOverlayImageCallback",
  "metadataVersion" : "0.1.0",
  "role" : "Type",
  "symbol" : {
    "kind" : "Type",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "type/mapkit.TileOverlayImageCallback"
  },
  "title" : "TileOverlayImageCallback"
}
-->

# TileOverlayImageCallback

A callback function that provides tile images for a tile overlay.

```
type TileOverlayImageCallback = (
    x: number,
    y: number,
    z: number,
    scale: number,
    data: any,
) => ImageSource | Promise<ImageSource> | null;
```

## Discussion

When MapKit JS needs to display a tile, it invokes the callback with the parameters `x`, `y`, `z`, `scale`, and `data`. Return one of the following:

- An [`ImageSource`](/documentation/MapKitJS/ImageSource) such as an `HTMLCanvasElement` or `OffscreenCanvas` for synchronous tile rendering.
- A `Promise` that resolves to an [`ImageSource`](/documentation/MapKitJS/ImageSource) for asynchronous tile loading.
- `null` to indicate there is no tile for the requested coordinates.

The following example creates a [`TileOverlay`](/documentation/MapKitJS/TileOverlay) with a callback that draws each tile on a canvas:

```javascript
const overlay = new mapkit.TileOverlay((x, y, z, scale) => {
    const size = 256 * scale;
    const canvas = new OffscreenCanvas(size, size);
    const ctx = canvas.getContext("2d");
    // Draw tile content based on x, y, z coordinates.
    return canvas;
});
```

To load tiles asynchronously, return a `Promise`:

```javascript
const overlay = new mapkit.TileOverlay((x, y, z, scale) => {
    return fetch(`https://myserver/tile/${z}/${x}/${y}`)
        .then((response) => response.blob())
        .then((blob) => createImageBitmap(blob));
});
```

See [`ImageSource`](/documentation/MapKitJS/ImageSource) for cross-origin requirements.

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)