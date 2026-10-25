<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/MarkerAnnotation",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.MarkerAnnotation"
  },
  "title" : "MarkerAnnotation"
}
-->

# MarkerAnnotation

An annotation that displays a balloon-shaped marker at the designated location.

```
class MarkerAnnotation extends Annotation
```

## Overview

A *marker* is a balloon-shaped annotation that contains a glyph or text. On the map, the marker appears when its coordinate is in view.

The following example shows a customized marker that specifies a color for the balloon background and the glyph, and provides custom glyph images. Color properties accept either a color name, here “brown” and “green”, or the equivalent hexadecimal color value such as “`#A52A2A`” and “`#008000`”, respectively. Or, you can use a specific color that matches your app’s specific design. For more information on standardized colors, see the CSS working group’s list of [common color names and values](https://drafts.csswg.org/css-color/#named-colors).

```javascript
const portland = new mapkit.Coordinate(45.514956, -122.679187);  // Portland City Hall, Portland, OR
const customMarker = new MarkerAnnotation(portland, {
    color: "green",
    glyphColor: "brown",
    glyphImage: { 1: "glyphImage.png" },
    selectedGlyphImage: { 1: "detailedIcon.png", 2: "detailedIcon_2x.png", 3: "detailedIcon_3x.png" }
});
```

The following example shows a marker annotation with a custom callout implemented by the callout delegate. In this example, the annotation is a dot when selected because [`selectedGlyphImage`](/documentation/MapKitJS/MarkerAnnotation/selectedGlyphImage) isn’t used.

```javascript
const calloutDelegate = {
    calloutRightAccessoryForAnnotation: function() {
        const accessoryViewRight = document.createElement("a");
        accessoryViewRight.className = "right-accessory-view";
        accessoryViewRight.href = "https://www.nps.gov/stli/index.htm";
        accessoryViewRight.target = "_blank";
        accessoryViewRight.appendChild(document.createTextNode("ⓘ"));

        return accessoryViewRight;
    }
};

const annotation = new mapkit.MarkerAnnotation(new mapkit.Coordinate(40.6892, -74.0445), {
    title: "Title",
    subtitle: "Subtitle",
    callout: calloutDelegate
});
```

---

## Topics

### Creating a marker annotation

[`constructor(
    location: CoordinateData | Place | SearchAutocompleteResult,
    options?: MarkerAnnotationConstructorOptions,
);`](/documentation/MapKitJS/MarkerAnnotation/MarkerAnnotationConstructor)

Creates a marker annotation at the coordinate location with provided options.

[`interface MarkerAnnotationConstructorOptions
    extends AnnotationConstructorOptions`](/documentation/MapKitJS/MarkerAnnotationConstructorOptions)

An object containing the options that create a marker annotation.

### Setting visibility

[`get subtitleVisibility(): FeatureVisibility;
set subtitleVisibility(value: FeatureVisibility);`](/documentation/MapKitJS/MarkerAnnotation/subtitleVisibility)

A value that determines the behavior of the subtitle’s visibility.

[`get titleVisibility(): FeatureVisibility;
set titleVisibility(value: FeatureVisibility);`](/documentation/MapKitJS/MarkerAnnotation/titleVisibility)

A value that determines the behavior of the title’s visibility.

### Setting appearance

[`get color(): string;
set color(value: string);`](/documentation/MapKitJS/MarkerAnnotation/color)

The background color of the balloon.

[`get glyphColor(): string;
set glyphColor(value: string);`](/documentation/MapKitJS/MarkerAnnotation/glyphColor)

The fill color of the glyph.

### Setting the glyph image and text

[`get glyphText(): string | null;
set glyphText(value: string | null);`](/documentation/MapKitJS/MarkerAnnotation/glyphText)

The text to display in the marker balloon.

[`get glyphImage():
    | ImageSource
    | ImageHashObject
    | ImageDelegate
    | Promise<ImageSource>
    | null;
set glyphImage(
    value:
        | ImageSource
        | ImageHashObject
        | ImageDelegate
        | Promise<ImageSource>
        | null,
);`](/documentation/MapKitJS/MarkerAnnotation/glyphImage)

The image to display in the marker balloon.

[`get selectedGlyphImage():
    | ImageSource
    | ImageHashObject
    | ImageDelegate
    | Promise<ImageSource>
    | null;
set selectedGlyphImage(
    value:
        | ImageSource
        | ImageHashObject
        | ImageDelegate
        | Promise<ImageSource>
        | null,
);`](/documentation/MapKitJS/MarkerAnnotation/selectedGlyphImage)

The image to display in the marker balloon when the user selects the marker.

### Instance Properties

[`get size(): Size;
set size(_: Size);`](/documentation/MapKitJS/MarkerAnnotation/size)

The dimensions of the annotation, in CSS pixels.

## Relationships

### Inherits From

[`Annotation`](/documentation/MapKitJS/Annotation)

### Inherited By

[`ClusterAnnotation`](/documentation/MapKitJS/ClusterAnnotation)

[`PlaceAnnotation`](/documentation/MapKitJS/PlaceAnnotation)

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)