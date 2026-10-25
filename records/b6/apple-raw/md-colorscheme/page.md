<!--
{
  "availability" : [
    "MapKit JS: 5.13.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/ColorScheme",
  "metadataVersion" : "0.1.0",
  "role" : "Enumeration",
  "symbol" : {
    "kind" : "Enumeration",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "enum/mapkit.ColorScheme"
  },
  "title" : "ColorScheme"
}
-->

# ColorScheme

Constants that indicate the color scheme of the map or a place detail.

```
const ColorScheme: Readonly<{
    readonly Dark: "dark";
    readonly Light: "light";
    readonly Adaptive: "adaptive";
}>
type ColorScheme = (typeof ColorScheme)[keyof typeof ColorScheme];
```

## Overview

Color schemes apply to maps that have a [`Standard`](/documentation/MapKitJS/MapType/Standard) or [`MutedStandard`](/documentation/MapKitJS/MapType/MutedStandard) map type. Use these constants with the map’s [`colorScheme`](/documentation/MapKitJS/Map/colorScheme) property.

## Topics

### Color scheme values

[`readonly Adaptive: "adaptive";`](/documentation/MapKitJS/ColorScheme/Adaptive)

A constant indicating a color scheme that follows the current system setting.

[`readonly Light: "light";`](/documentation/MapKitJS/ColorScheme/Light)

A constant indicating a light color scheme.

[`readonly Dark: "dark";`](/documentation/MapKitJS/ColorScheme/Dark)

A constant indicating a dark color scheme.



---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)