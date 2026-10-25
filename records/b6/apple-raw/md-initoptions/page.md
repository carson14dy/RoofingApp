<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/MapKitInitializationOptions",
  "metadataVersion" : "0.1.0",
  "role" : "Interface",
  "symbol" : {
    "kind" : "Interface",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "struct/mapkit.MapKitInitializationOptions"
  },
  "title" : "MapKitInitializationOptions"
}
-->

# MapKitInitializationOptions

Initialization options for MapKit JS.

```
interface MapKitInitializationOptions
```

## Topics

### Callback and language

[`language?: string | null;`](/documentation/MapKitJS/MapKitInitializationOptions/language)

An ID that indicates the preferred language to use when displaying map labels, controls, directions, and other text.

[`authorizationCallback?: (this: null, done: (token: string) => void) => void;`](/documentation/MapKitJS/MapKitInitializationOptions/authorizationCallback)

A callback function that obtains a token.

### Loading libraries

[`libraries?: string[];`](/documentation/MapKitJS/MapKitInitializationOptions/libraries)

An array of libraries to load at initialization.



---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)