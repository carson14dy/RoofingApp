<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/Overlay",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.Overlay"
  },
  "title" : "Overlay"
}
-->

# Overlay

An abstract base object that defines the methods and properties for map overlays.

```
abstract class Overlay extends EventTarget
```

## Overview

Overlays inherit from an abstract base object, [`Overlay`](/documentation/MapKitJS/Overlay), and share some common properties with [`Annotation`](/documentation/MapKitJS/Annotation) that allow you to control the visibility and interaction with the map in the same way. This object is abstract and you can’t instantiate it.

## Topics

### Registering event listeners

### Setting overlay options

[`get data(): {};
set data(data: {});`](/documentation/MapKitJS/Overlay/data)

Custom data to associate with the overlay.

[`get visible(): boolean;
set visible(visible: boolean);`](/documentation/MapKitJS/Overlay/visible)

A Boolean value that determines whether an overlay is visible.

[`get enabled(): boolean;
set enabled(value: boolean);`](/documentation/MapKitJS/Overlay/enabled)

A Boolean value that determines whether the overlay responds to user interaction.

[`get selected(): boolean;
set selected(value: boolean);`](/documentation/MapKitJS/Overlay/selected)

A Boolean value that indicates whether the user selects the overlay.

[`get style(): Style;
set style(style: Style);`](/documentation/MapKitJS/Overlay/style)

Style properties to apply to the overlay.

[`get map(): Map | null;
set map(_: Map | null);`](/documentation/MapKitJS/Overlay/map)

The map you add the overlay to.

## Relationships

### Inherited By

[`PolygonOverlay`](/documentation/MapKitJS/PolygonOverlay)

[`PolylineOverlay`](/documentation/MapKitJS/PolylineOverlay)

[`CircleOverlay`](/documentation/MapKitJS/CircleOverlay)

### Inherits From

`EventTarget`

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)