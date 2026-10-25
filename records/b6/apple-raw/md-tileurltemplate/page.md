<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/TileOverlayUrlTemplate",
  "metadataVersion" : "0.1.0",
  "role" : "Type",
  "symbol" : {
    "kind" : "Type",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "type/mapkit.TileOverlayUrlTemplate"
  },
  "title" : "TileOverlayUrlTemplate"
}
-->

# TileOverlayUrlTemplate

A type that specifies the URL template for a tile overlay.

```
type TileOverlayUrlTemplate =
    | string
    | ((
          x: number,
          y: number,
          z: number,
          scale: number,
          data: any,
      ) => string | null);
```

## Discussion

You may set the URL template as either a template string or a function.

The template string must be in the format: `https://myserver/tile?x={x}&y={y}&z={z}&scale={scale}`. MapKit JS replaces the `x`, `y`, `z`, and `scale` values depending on the displayed map region and screen resolution, then loads an image from that URL. You can also add custom values to the template string. For example, a template string could look like: `https://{subdomain}.customtileserver.com/{z}/{x}/{y}?lang={lang}`. In this case, you must define `TileOverlay.data.subdomain` and `TileOverlay.data.lang` for the placeholders to populate. Also, note that not all parameters are necessary in a template string. The `scale` parameter is absent in this example.

You can provide a callback function instead of the template string. When MapKit JS needs to request new tiles, it invokes the [`imageForTile`](/documentation/MapKitJS/TileOverlay/imageForTile) callback with the parameters `x`, `y`, `z`, `scale`, and `data`. The callback function must return a URL for the provided parameters. Return `null` if there is no tile for the requested coordinates.

To provide tile images directly instead of URLs, use a [`TileOverlayImageCallback`](/documentation/MapKitJS/TileOverlayImageCallback).

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)