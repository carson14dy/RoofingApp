<!--
{
  "availability" : [
    "MapKit JS: 5.13.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/Map/colorScheme",
  "metadataVersion" : "0.1.0",
  "role" : "Instance Property",
  "symbol" : {
    "kind" : "Instance Property",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "instp/mapkit.Map/colorScheme"
  },
  "title" : "colorScheme"
}
-->

# colorScheme

The map’s color scheme when displaying standard or muted standard map types.

```
get colorScheme(): ColorScheme;
set colorScheme(colorScheme: ColorScheme);
```

## Discussion

This property accepts a value from [`ColorScheme`](/documentation/MapKitJS/ColorScheme) to determine whether the map displays with a dark or light theme when [`Standard`](/documentation/MapKitJS/MapType/Standard) or [`MutedStandard`](/documentation/MapKitJS/MapType/MutedStandard) are the configured [`mapType`](/documentation/MapKitJS/Map/mapType). The default is [`Light`](/documentation/MapKitJS/ColorScheme/Light).

The map updates the grid, user location accuracy ring, marker annotation labels, and controls to complement the Dark Mode style.

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)