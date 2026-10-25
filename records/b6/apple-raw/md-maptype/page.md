<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/MapType",
  "metadataVersion" : "0.1.0",
  "role" : "Enumeration",
  "symbol" : {
    "kind" : "Enumeration",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "enum/mapkit.MapType"
  },
  "title" : "MapType"
}
-->

# MapType

Constants representing the type of map to display.

```
const MapType: Readonly<{
    readonly Satellite: "satellite";
    readonly Hybrid: "hybrid";
    readonly MutedStandard: "mutedStandard";
    readonly Standard: "standard";
}>
type MapType = (typeof MapType)[keyof typeof MapType];
```

## Topics

### Map type values

[`readonly Hybrid: "hybrid";`](/documentation/MapKitJS/MapType/Hybrid)

A satellite image of the area with road and road name layers on top.

[`readonly MutedStandard: "mutedStandard";`](/documentation/MapKitJS/MapType/MutedStandard)

A street map that emphasizes your data over the underlying map details.

[`readonly Satellite: "satellite";`](/documentation/MapKitJS/MapType/Satellite)

A satellite image of the area.

[`readonly Standard: "standard";`](/documentation/MapKitJS/MapType/Standard)

A street map that shows the position of all roads and some road names.



---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)