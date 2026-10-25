<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/PolygonOverlay",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.PolygonOverlay"
  },
  "title" : "PolygonOverlay"
}
-->

# PolygonOverlay

An overlay consisting of one or more points that forms a closed shape.

```
class PolygonOverlay extends Overlay
```

## Overview

A *polygon* is a shape that consists of points connected end-to-end. Unlike polylines, polygons are closed shapes with an inside and an outside. The first and last points connect to each other to form a closed shape.

The [`PolygonOverlay`](/documentation/MapKitJS/PolygonOverlay) initializer doesn’t limit you to whole polygons. You can combine multiple polygons to form noncontiguous shapes or shapes with regions cut out. For example, to show the boundaries of South Africa, an overlay carves out Lesotho, an enclave within South Africa. To do this, you use points to describe Lesotho as a polygon that MapKit JS subtracts from the outer polygon.

You can choose whether a point falls inside or outside the [`PolygonOverlay`](/documentation/MapKitJS/PolygonOverlay) by setting `style.fillRule` to `nonzero` or `evenodd`.

The longitude of all points in a polygon overlay needs to be within a 360-degree range. Depending on how you specify the longitude of the points, drawing a triangle between Tokyo, Los Angeles, and Sydney using a polygon overlay may take a different route. Specifying a longitude of -118º for Los Angeles, 140º for Tokyo, and 151º for Sydney results in a very wide triangle spanning 258º. Specifying a longitude of 242º (that is, -118 + 360) for Los Angeles, 140º for Tokyo, and 151º for Sydney results in a narrower triangle spanning 98º. MapKit JS may not render the polyline correctly if the range of longitudes is larger than 360º.

All [`style`](/documentation/MapKitJS/OverlayOptions/style) properties apply to polygon overlays except `lineCap`, which MapKit JS ignores. [`PolygonOverlay`](/documentation/MapKitJS/PolygonOverlay) doesn’t implement methods of its own. For more information, see the base object, [`Overlay`](/documentation/MapKitJS/Overlay). The following example uses a rectangle overlay to show the boundary lines for the state of Colorado:

```javascript
const points = [ [41, -109.05], [41, -102.05], [37, -102.05], [37, -109.05] ];

// Map the raw coordinate points to MapKit JS Coordinate objects:
points = points.map(function(point) {
    return new mapkit.Coordinate(point[0], point[1]);
});
const style = new mapkit.Style({
    strokeColor: "#F00",
    strokeOpacity: .2,
    lineWidth: 2,
    lineJoin: "round",
    lineDash: [2, 2, 6, 2, 6, 2]
});

const rectangle = new mapkit.PolygonOverlay(points, { style: style });
map.addOverlay(rectangle);
```

## Topics

### Creating a polygon overlay

[`constructor(
    points: CoordinateData[][] | CoordinateData[],
    options?: OverlayOptions,
);`](/documentation/MapKitJS/PolygonOverlay/PolygonOverlayConstructor)

Creates a polygon overlay with an array of points and style options.

[`interface OverlayOptions`](/documentation/MapKitJS/OverlayOptions)

A dictionary of options that determines an overlay’s data, and indicates whether it’s visible, in an enabled state, and in a selected state.

### Defining the polygon

[`get points(): Coordinate[][];
set points(points: Coordinate[][]);`](/documentation/MapKitJS/PolygonOverlay/points)

One or more arrays of coordinates that define the polygon overlay shape.

## Relationships

### Inherits From

[`Overlay`](/documentation/MapKitJS/Overlay)

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)