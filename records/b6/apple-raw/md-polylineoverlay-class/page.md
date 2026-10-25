<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/PolylineOverlay",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.PolylineOverlay"
  },
  "title" : "PolylineOverlay"
}
-->

# PolylineOverlay

An overlay of connected line segments that don’t form a closed shape.

```
class PolylineOverlay extends Overlay
```

## Overview

A *polyline* is a shape that consists of connected line segments that you define with a set of points. The first and last points don’t connect to each other.

The longitude of all points should be within a 360-degree range. Depending on how you specify the longitude, a line between Tokyo and Los Angeles that you create with a [`PolylineOverlay`](/documentation/MapKitJS/PolylineOverlay) may take a different route. Specifying a longitude of -118º for Los Angeles and 140º for Tokyo results in a very long line spanning 258º. Specifying a longitude of 242º (that’s, -118 + 360) for Los Angeles and 140º for Tokyo results in a shorter line spanning 98º. MapKit JS may not render the polyline correctly if the range of longitudes is larger than 360º.

All [`style`](/documentation/MapKitJS/OverlayOptions/style) properties apply to polyline overlays except `fillColor`, `fillOpacity,` and `fillRule`. MapKit JS ignores properties that don’t apply. [`PolylineOverlay`](/documentation/MapKitJS/PolylineOverlay) doesn’t implement methods of its own. For more information, see the base object, [`Overlay`](/documentation/MapKitJS/Overlay).

The following example shows a polyline object for a map.

```javascript
const points = [ [10, 1], [5, 6], [1, 1] ];
const coords = points.map(function(point) {
    return new mapkit.Coordinate(point[0], point[1]);
});

const style = new mapkit.Style({
    lineWidth: 2,
    lineJoin: "round",
    lineDash: [8, 4],
    strokeColor: "#F0F"
});

const polyline = new mapkit.PolylineOverlay(coords, { style: style });
map.addOverlay(polyline);
```

## Topics

### Creating a polyline overlay

[`constructor(points: CoordinateData[], options?: OverlayOptions);`](/documentation/MapKitJS/PolylineOverlay/PolylineOverlayConstructor)

Creates a polyline overlay with coordinate points and style options.

[`interface OverlayOptions`](/documentation/MapKitJS/OverlayOptions)

A dictionary of options that determines an overlay’s data, and indicates whether it’s visible, in an enabled state, and in a selected state.

### Defining the polyline

[`get points(): Coordinate[];
set points(points: Coordinate[]);`](/documentation/MapKitJS/PolylineOverlay/points)

An array of coordinate points that define the polyline overlay’s shape.

## Relationships

### Inherits From

[`Overlay`](/documentation/MapKitJS/Overlay)

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)