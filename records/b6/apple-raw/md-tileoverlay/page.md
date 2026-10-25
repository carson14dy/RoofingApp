<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/TileOverlay",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.TileOverlay"
  },
  "title" : "TileOverlay"
}
-->

# TileOverlay

An overlay that covers an area of the map with bitmapped tiles.

```
class TileOverlay extends EventTarget
```

## Overview

You use tile overlay objects to represent your own tile-based content and to coordinate the display of that content on a map. Your tiles can supplement the underlying map content or replace it completely. You can use a single tile overlay object to represent all of the tiles at one or more zoom levels of the map.

## Topics

### Creating a tile overlay

[`constructor(
    imageForTile: TileOverlayUrlTemplate | TileOverlayImageCallback,
    options?: TileOverlayConstructorOptions,
);`](/documentation/MapKitJS/TileOverlay/TileOverlayConstructor)

Creates a tile overlay with a URL template or image callback and style options.

[`interface TileOverlayConstructorOptions`](/documentation/MapKitJS/TileOverlayConstructorOptions)

Attributes for initializing a tile overlay, including minimum and maximum zoom, opacity, and custom data.

[`type TileOverlayUrlTemplate =
    | string
    | ((
          x: number,
          y: number,
          z: number,
          scale: number,
          data: any,
      ) => string | null);`](/documentation/MapKitJS/TileOverlayUrlTemplate)

A type that specifies the URL template for a tile overlay.

[`type TileOverlayImageCallback = (
    x: number,
    y: number,
    z: number,
    scale: number,
    data: any,
) => ImageSource | Promise<ImageSource> | null;`](/documentation/MapKitJS/TileOverlayImageCallback)

A callback function that provides tile images for a tile overlay.

### Events

[`class TileOverlayErrorEvent extends Event`](/documentation/MapKitJS/TileOverlayErrorEvent)

An event object that notifies the developer of an error that occurred while loading tiles.

### Customizing the tile overlay

[`get imageForTile(): TileOverlayUrlTemplate | TileOverlayImageCallback;
set imageForTile(
    imageForTile: TileOverlayUrlTemplate | TileOverlayImageCallback,
);`](/documentation/MapKitJS/TileOverlay/imageForTile)

A string, or callback function, that provides the requested tile.

[`get data(): Record<string, any>;
set data(data: Record<string, any>);`](/documentation/MapKitJS/TileOverlay/data)

A dictionary of custom properties to use with the URL template.

[`reload(): void;`](/documentation/MapKitJS/TileOverlay/reload)

Reloads the tile overlay for the displayed map region with the latest data values.

### Setting overlay appearance

[`get opacity(): number;
set opacity(opacity: number);`](/documentation/MapKitJS/TileOverlay/opacity)

A number that indicates a tile’s opacity.

[`get maximumZ(): number | null;
set maximumZ(maximumZ: number | null);`](/documentation/MapKitJS/TileOverlay/maximumZ)

The maximum zoom level for a tile overlay.

[`get minimumZ(): number | null;
set minimumZ(minimumZ: number | null);`](/documentation/MapKitJS/TileOverlay/minimumZ)

The minimum zoom level for a tile overlay.

### Deprecated

[`get urlTemplate(): TileOverlayUrlTemplate | TileOverlayImageCallback;
set urlTemplate(
    urlTemplate: TileOverlayUrlTemplate | TileOverlayImageCallback,
);`](/documentation/MapKitJS/TileOverlay/urlTemplate)

A string, or callback function, that provides the requested tile.

## Relationships

### Inherits From

`EventTarget`

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)