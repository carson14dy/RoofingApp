<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/Map/rotation",
  "metadataVersion" : "0.1.0",
  "role" : "Instance Property",
  "symbol" : {
    "kind" : "Instance Property",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "instp/mapkit.Map/rotation"
  },
  "title" : "rotation"
}
-->

# rotation

The map’s rotation, in degrees.

```
get rotation(): number;
set rotation(rotation: number);
```

## Discussion

This value represents the map’s [`rotation`](/documentation/MapKitJS/Map/rotation) in degrees, where the value 0 means that the top edge of the map view corresponds to true north. The value 90 means the top of the map is pointing due west. The value 180 means the top of the map points due south, and so on.

Setting the rotation property always rotates the map around its [`center`](/documentation/MapKitJS/Map/center).

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)