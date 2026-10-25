<!--
{
  "availability" : [
    "MapKit JS: 6.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/ImageSource",
  "metadataVersion" : "0.1.0",
  "role" : "Type",
  "symbol" : {
    "kind" : "Type",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "type/mapkit.ImageSource"
  },
  "title" : "ImageSource"
}
-->

# ImageSource

A union type that represents image sources that the framework can use for annotations and tile overlays.

```
type ImageSource =
    | HTMLImageElement
    | HTMLCanvasElement
    | ImageBitmap
    | OffscreenCanvas;
```

## Discussion

An [`ImageSource`](/documentation/MapKitJS/ImageSource) is an `HTMLImageElement`, `HTMLCanvasElement`, `ImageBitmap`, or `OffscreenCanvas`. You can set an [`ImageSource`](/documentation/MapKitJS/ImageSource) directly on the [`ImageAnnotation`](/documentation/MapKitJS/ImageAnnotation) [`image`](/documentation/MapKitJS/ImageAnnotation/image) property or the [`MarkerAnnotation`](/documentation/MapKitJS/MarkerAnnotation) [`glyphImage`](/documentation/MapKitJS/MarkerAnnotation/glyphImage) property to display a preloaded or dynamically generated image. You can also wrap an [`ImageSource`](/documentation/MapKitJS/ImageSource) in a `Promise` to load the image asynchronously.

## Utilizing Cross-origin Images

To enable cross-origin image sources for MapKit JS, instruct the browser to load them in CORS mode. The `HTMLImageElement` provides a `crossOrigin` property that you need to set to either `"anonymous"` (without cookies) or `"use-credentials"` (with a cookie) to opt-in to CORS request mode.

When compositing a `HTMLCanvasElement` or `ImageBitmap`, composite these objects  from CORS-enabled cross-origin, or same-origin images.

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)