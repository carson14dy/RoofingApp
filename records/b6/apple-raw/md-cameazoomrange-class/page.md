<!--
{
  "availability" : [
    "MapKit JS: 5.23.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/CameraZoomRange",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.CameraZoomRange"
  },
  "title" : "CameraZoomRange"
}
-->

# CameraZoomRange

A minimum and maximum camera distance, in meters, from the center of the map.

```
class CameraZoomRange implements CameraZoomRangeData
```

## Topics

### Defining a zoom range

[`constructor();`](/documentation/MapKitJS/CameraZoomRange/CameraZoomRangeConstructor)

Constructs an instance of a camera zoom range object with no minimum or maximum camera distance.

[`constructor(rangeParams: Partial<CameraZoomRangeData>);`](/documentation/MapKitJS/CameraZoomRange/CameraZoomRangeConstructor1)

Creates an instance of a camera zoom range object with an object literal.

[`constructor(min: number, max: number);`](/documentation/MapKitJS/CameraZoomRange/CameraZoomRangeConstructor2)

Creates an instance of a camera zoom range object with the specified numeric arguments that specify minimum and maximum camera distances.

### Setting minimum and maximum distances

[`get minCameraDistance(): number;`](/documentation/MapKitJS/CameraZoomRange/minCameraDistance)

The minimum allowed distance of the camera from the center of the map in meters.

[`get maxCameraDistance(): number;`](/documentation/MapKitJS/CameraZoomRange/maxCameraDistance)

The maximum allowed distance of the camera from the center of the map in meters.

### Instance Methods

[`copy(): CameraZoomRange;`](/documentation/MapKitJS/CameraZoomRange/copy)

Returns a copy of the camera zoom region.

## Relationships

### Conforms To

[`CameraZoomRangeData`](/documentation/MapKitJS/CameraZoomRangeData)

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)