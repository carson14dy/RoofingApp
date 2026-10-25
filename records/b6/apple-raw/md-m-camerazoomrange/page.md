<!--
{
  "availability" : [
    "MapKit JS: 5.23.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/Map/cameraZoomRange",
  "metadataVersion" : "0.1.0",
  "role" : "Instance Property",
  "symbol" : {
    "kind" : "Instance Property",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "instp/mapkit.Map/cameraZoomRange"
  },
  "title" : "cameraZoomRange"
}
-->

# cameraZoomRange

The minimum and maximum distances of the camera from the map center.

```
get cameraZoomRange(): CameraZoomRange | undefined;
set cameraZoomRange(value: CameraZoomRangeData | undefined | null);
```

## Discussion

Get or set this property with a [`CameraZoomRange`](/documentation/MapKitJS/CameraZoomRange) instance, which is an object containing [`minCameraDistance`](/documentation/MapKitJS/CameraZoomRange/minCameraDistance) and [`maxCameraDistance`](/documentation/MapKitJS/CameraZoomRange/maxCameraDistance) properties.

## Topics

### Defining a Zoom Range

[`class CameraZoomRange implements CameraZoomRangeData`](/documentation/MapKitJS/CameraZoomRange)

A minimum and maximum camera distance, in meters, from the center of the map.



---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)