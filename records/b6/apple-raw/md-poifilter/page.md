<!--
{
  "availability" : [
    "MapKit JS: 5.33.1 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/PointOfInterestFilter",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.PointOfInterestFilter"
  },
  "title" : "PointOfInterestFilter"
}
-->

# PointOfInterestFilter

A filter for determining the points of interest to include or exclude on a map or in a local search.

```
class PointOfInterestFilter
```

## Overview

You can apply a point-of-interest filter when you create a map ([`MapConstructorOptions`](/documentation/MapKitJS/MapConstructorOptions)), when you update an existing map ([`Map`](/documentation/MapKitJS/Map)), or when you fetch points of interest ([`SearchConstructorOptions`](/documentation/MapKitJS/SearchConstructorOptions)).

## Topics

### Creating filters

[`static excluding(
    categories: PointOfInterestCategory[],
): PointOfInterestFilter;`](/documentation/MapKitJS/PointOfInterestFilter/excluding)

Creates a point-of-interest filter that excludes categories from a list that you provide.

[`static including(
    categories: PointOfInterestCategory[],
): PointOfInterestFilter;`](/documentation/MapKitJS/PointOfInterestFilter/including)

Creates a point-of-interest filter that includes categories from a list that you provide.

[`static excludingAllCategories: () => PointOfInterestFilter;`](/documentation/MapKitJS/PointOfInterestFilter/excludingAllCategories)

A filter that excludes all point-of-interest categories.

[`static includingAllCategories: () => PointOfInterestFilter;`](/documentation/MapKitJS/PointOfInterestFilter/includingAllCategories)

A filter that includes all point-of-interest categories.

### Querying filter behavior

[`excludesCategory(category: PointOfInterestCategory): boolean | undefined;`](/documentation/MapKitJS/PointOfInterestFilter/excludesCategory)

Returns a Boolean value that indicates whether the filter excludes the provided point-of-interest category.

[`includesCategory(category: PointOfInterestCategory): boolean | undefined;`](/documentation/MapKitJS/PointOfInterestFilter/includesCategory)

Returns a Boolean value that indicates whether the filter includes the provided point-of-interest category.



---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)