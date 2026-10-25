<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/CircleOverlay",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.CircleOverlay"
  },
  "title" : "CircleOverlay"
}
-->

# CircleOverlay

A circular overlay with a configurable radius that centers on a specific geographic coordinate.

```
class CircleOverlay extends Overlay
```

## Overview

The circle overlay provides a built-in object for creating circles. MapKit JS defines [`CircleOverlay`](/documentation/MapKitJS/CircleOverlay) by a coordinate and a radius (in meters). All [`style`](/documentation/MapKitJS/OverlayOptions/style) properties apply to circle overlays except `lineCap`, `lineJoin`, and `fillRule`. MapKit JS ignores properties that don’t apply.

[`CircleOverlay`](/documentation/MapKitJS/CircleOverlay) doesn’t implement methods of its own. For more information, see the base object, [`Overlay`](/documentation/MapKitJS/Overlay).

The following example uses circle overlays to show the relative population sizes of three cities in the San Francisco Bay Area:

```javascript
const stats = [
    { name: "San Francisco", coordinate: [37.783333, -122.416667], population: 852469 },
    { name: "Oakland", coordinate: [37.804444, -122.270833], population: 390724 },
    { name: "San Jose", coordinate: [37.333333, -121.9], population: 1000536 },
];

const style = new mapkit.Style({
    lineWidth: 2,         // 2 CSS pixels.
    strokeColor: "#999",
    fillColor: "#FFF"
});

const circles = stats.map(function(stat) {
    const coordinate = new mapkit.Coordinate(stat.coordinate[0], stat.coordinate[1]),
        radius = stat.population / 85, // The radius is in meters.
        circle = new mapkit.CircleOverlay(coordinate, radius);
    circle.data = { population: stat.population };
    circle.style = style;
    return circle;
});

map.addOverlays(circles);
```

## Topics

### Creating a circle overlay

[`constructor(
    coordinate: CoordinateData,
    radius: number,
    options?: OverlayOptions,
);`](/documentation/MapKitJS/CircleOverlay/CircleOverlayConstructor)

Creates a circle overlay with a center coordinate, radius, and style options.

[`interface OverlayOptions`](/documentation/MapKitJS/OverlayOptions)

A dictionary of options that determines an overlay’s data, and indicates whether it’s visible, in an enabled state, and in a selected state.

### Defining the circle

[`get coordinate(): CoordinateData;
set coordinate(coordinate: CoordinateData);`](/documentation/MapKitJS/CircleOverlay/coordinate)

The coordinate of the circle overlay’s center.

[`get radius(): number;
set radius(radius: number);`](/documentation/MapKitJS/CircleOverlay/radius)

The circle overlay’s radius, in meters.

## Relationships

### Inherits From

[`Overlay`](/documentation/MapKitJS/Overlay)

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)