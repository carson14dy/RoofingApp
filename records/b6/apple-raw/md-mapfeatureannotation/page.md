<!--
{
  "availability" : [
    "MapKit JS: 5.74.1 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/MapFeatureAnnotation",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.MapFeatureAnnotation"
  },
  "title" : "MapFeatureAnnotation"
}
-->

# MapFeatureAnnotation

An object that represents a map feature that the user selects.

```
class MapFeatureAnnotation extends PlaceAnnotation
```

## Overview

MapKit JS creates a `MapFeatureAnnotation` when you set [`selectableMapFeatures`](/documentation/MapKitJS/Map/selectableMapFeatures), and when a person taps a map feature. The instance is available from the [`selectedAnnotation`](/documentation/MapKitJS/Map/selectedAnnotation) property when a person selects a map feature and MapKit JS passes it to the [`annotationForMapFeature`](/documentation/MapKitJS/Map/annotationForMapFeature) delegate method.

MapKit JS removes the annotation as soon as a person deselects the map feature.

## Topics

### Annotation properties

[`get title(): string | null;`](/documentation/MapKitJS/MapFeatureAnnotation/title)

The title of the feature.

[`get featureType(): "" | MapFeatureType;`](/documentation/MapKitJS/MapFeatureAnnotation/featureType)

A value that describes the type of place the feature represents.

[`get pointOfInterestCategory(): PointOfInterestCategory | null;`](/documentation/MapKitJS/MapFeatureAnnotation/pointOfInterestCategory)

The point-of-interest category of the feature.

[`get color(): string;`](/documentation/MapKitJS/PlaceAnnotation/color)

The color of the place.

[`get glyphImage(): MapFeatureAnnotationGlyphImage | null;`](/documentation/MapKitJS/PlaceAnnotation/glyphImage)

The glyph image for the place.

[`get selectedGlyphImage(): MapFeatureAnnotationGlyphImage | null;`](/documentation/MapKitJS/PlaceAnnotation/selectedGlyphImage)

The selected glyph image for the place.

### Deprecated

[`fetchPlace(
    callback: (error: Error | null, result: Place | null) => void,
): Promise<Place | null>;`](/documentation/MapKitJS/MapFeatureAnnotation/fetchPlace)

Fetches the place object associated with the map feature.

### Instance Properties

[`get accessibilityLabel(): string | null;`](/documentation/MapKitJS/MapFeatureAnnotation/accessibilityLabel)

The accessibility label for the annotation.

[`get collisionMode(): AnnotationCollisionMode;`](/documentation/MapKitJS/MapFeatureAnnotation/collisionMode)

A value that determines how the map handles collisions between annotations.

[`get map(): Map | null;`](/documentation/MapKitJS/MapFeatureAnnotation/map)

The map that the annotation is on.

[`get subtitle(): string | null;`](/documentation/MapKitJS/MapFeatureAnnotation/subtitle)

The subtitle of the feature.

[`get subtitleVisibility(): FeatureVisibility;`](/documentation/MapKitJS/MapFeatureAnnotation/subtitleVisibility)

A value that determines the subtitle’s visibility.

[`get titleVisibility(): FeatureVisibility;`](/documentation/MapKitJS/MapFeatureAnnotation/titleVisibility)

A value that determines the behavior of the title’s visibility.

## Relationships

### Inherits From

[`PlaceAnnotation`](/documentation/MapKitJS/PlaceAnnotation)

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)