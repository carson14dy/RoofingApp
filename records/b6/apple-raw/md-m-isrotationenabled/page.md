<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/Map/isRotationEnabled",
  "metadataVersion" : "0.1.0",
  "role" : "Instance Property",
  "symbol" : {
    "kind" : "Instance Property",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "instp/mapkit.Map/isRotationEnabled"
  },
  "title" : "isRotationEnabled"
}
-->

# isRotationEnabled

A Boolean value that determines whether the user may rotate the map using the compass control or a rotate gesture.

```
get isRotationEnabled(): boolean;
set isRotationEnabled(value: boolean);
```

## Discussion

When `isRotationEnabled` is `false`, you can still rotate the map programmatically by using [`rotation`](/documentation/MapKitJS/Map/rotation) or [`setRotationAnimated(degrees, animated)`](/documentation/MapKitJS/Map/setRotationAnimated).

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)