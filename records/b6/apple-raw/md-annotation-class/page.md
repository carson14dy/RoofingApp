<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/Annotation",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.Annotation"
  },
  "title" : "Annotation"
}
-->

# Annotation

The base annotation object for creating custom annotations.

```
class Annotation extends EventTarget
```

## Overview

An annotation represents data that you want to display on the map’s surface. Associate each annotation with a [`coordinate`](/documentation/MapKitJS/Annotation/coordinate) on the map. Use the extended objects [`MarkerAnnotation`](/documentation/MapKitJS/MarkerAnnotation) and [`ImageAnnotation`](/documentation/MapKitJS/ImageAnnotation) to create annotations on the map, or [`Annotation`](/documentation/MapKitJS/Annotation) to customize a view beyond the presentation that [`ImageAnnotation`](/documentation/MapKitJS/ImageAnnotation) or [`MarkerAnnotation`](/documentation/MapKitJS/MarkerAnnotation) provide.

The examples below create a custom annotation using a person’s initials to show them on the map. The following CSS style encloses the initials in a gray circle:

```javascript
.circle-annotation {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    color: #FFF;
    background-color: #CCC;
    text-align: center;
    line-height: 32px;
}
```

The following code creates the annotation:

```javascript
const people = [
    { title: "Juan Chavez",
      coordinate: new mapkit.Coordinate(37.3349, -122.0090201),
      role: "developer",
      building: "HQ" },
    { title: "Anne Johnson",
      coordinate: new mapkit.Coordinate(37.722319, -122.434979),
      role: "manager",
      building: "HQ" }
];

const factory = function(coordinate, options) {
    const div = document.createElement("div"),
        name = options.title,           // "Juan Chavez"
        parts = name.split(' ');        // ["Chavez", "Juan"]
    div.textContent = parts[0].charAt(0) + parts[1].charAt(0);    // "JA"
    div.className = "circle-annotation";
    return div;
};

people.forEach(function(person) {
    const options = {
        title: person.title,
        data: { role: person.role, building: person.building }
    };
    const annotation = new mapkit.Annotation(person.coordinate, factory, options);
    map.addAnnotation(annotation);
});
```

## Topics

### Creating an annotation

[`constructor(
    location: CoordinateData | Place | SearchAutocompleteResult,
    factory: (
        location?: Coordinate,
        options?: AnnotationConstructorOptions,
    ) => HTMLElement,
    options?: AnnotationConstructorOptions,
);`](/documentation/MapKitJS/Annotation/AnnotationConstructor)

Creates a new annotation given its location and initialization options.

[`interface AnnotationConstructorOptions`](/documentation/MapKitJS/AnnotationConstructorOptions)

An object that contains options for creating annotation features.

### Getting the map and element

[`get map(): Map | null;
set map(_: Map | null);`](/documentation/MapKitJS/Annotation/map)

The map that the framework adds the annotation to.

[`get element(): HTMLElement;
set element(_: HTMLElement);`](/documentation/MapKitJS/Annotation/element)

The annotation’s element in the DOM.

### Getting the Place ID

[`get id(): string | null;`](/documentation/MapKitJS/Annotation/id)

The place ID that references a place or a map feature.

### Getting and setting data, titles, and the accessibility label

[`get data(): object;
set data(data: object);`](/documentation/MapKitJS/Annotation/data)

Data that you define that’s specific to an annotation.

[`get title(): string | null;
set title(value: string | null | undefined);`](/documentation/MapKitJS/Annotation/title)

The text to display in the annotation’s callout.

[`get subtitle(): string | null;
set subtitle(value: string | null | undefined);`](/documentation/MapKitJS/Annotation/subtitle)

The text to display as a subtitle on the second line of an annotation’s callout.

[`get accessibilityLabel(): string | null;
set accessibilityLabel(value: string | null);`](/documentation/MapKitJS/Annotation/accessibilityLabel)

Accessibility text for the annotation.

### Getting and setting annotation appearance

[`get coordinate(): Coordinate;
set coordinate(value: CoordinateData);`](/documentation/MapKitJS/Annotation/coordinate)

The annotation’s coordinate.

[`get anchorOffset(): DOMPoint;
set anchorOffset(value: DOMPoint);`](/documentation/MapKitJS/Annotation/anchorOffset)

An offset that changes the annotation’s default anchor point.

[`get appearanceAnimation(): string;
set appearanceAnimation(appearanceAnimation: string);`](/documentation/MapKitJS/Annotation/appearanceAnimation)

A CSS animation that runs when the annotation appears on the map.

[`get displayPriority(): number;
set displayPriority(value: number);`](/documentation/MapKitJS/Annotation/displayPriority-data.property)

A numeric hint that the map uses to prioritize how it displays annotations.

[`get padding(): Padding;
set padding(value: PaddingData);`](/documentation/MapKitJS/Annotation/padding)

Spacing to add around the annotation when showing items.

[`get size(): Size | null;
set size(value: Size);`](/documentation/MapKitJS/Annotation/size)

The desired dimensions of the annotation, in CSS pixels.

[`get visible(): boolean;
set visible(value: boolean);`](/documentation/MapKitJS/Annotation/visible)

A Boolean value that determines whether the annotation is visible or hidden.

### Getting and setting interaction behavior

[`get animates(): boolean;
set animates(value: boolean);`](/documentation/MapKitJS/Annotation/animates)

A Boolean value that determines whether the framework animates the annotation.

[`get draggable(): boolean;
set draggable(value: boolean);`](/documentation/MapKitJS/Annotation/draggable)

A Boolean value that determines whether the user can drag the annotation.

[`get selected(): boolean;
set selected(value: boolean);`](/documentation/MapKitJS/Annotation/selected)

A Boolean value that indicates whether the map shows the annotation in a selected state.

[`get enabled(): boolean;
set enabled(value: boolean);`](/documentation/MapKitJS/Annotation/enabled)

A Boolean value that determines whether the annotation responds to user interaction.

### Managing callouts

[`get callout(): AnnotationCalloutDelegate | null;
set callout(callout: AnnotationCalloutDelegate | null);`](/documentation/MapKitJS/Annotation/callout)

A delegate that enables you to customize the annotation’s callout.

[`get calloutEnabled(): boolean;
set calloutEnabled(value: boolean);`](/documentation/MapKitJS/Annotation/calloutEnabled)

A Boolean value that determines whether the map shows an annotation’s callout.

[`get calloutOffset(): DOMPoint;
set calloutOffset(value: DOMPoint);`](/documentation/MapKitJS/Annotation/calloutOffset)

An offset that changes the annotation callout’s default placement.

### Managing clustering

[`get memberAnnotations(): Annotation[] | null;`](/documentation/MapKitJS/Annotation/memberAnnotations)

An array of annotations that the framework groups together in a cluster.

[`get clusteringIdentifier(): string | null;
set clusteringIdentifier(value: string | null);`](/documentation/MapKitJS/Annotation/clusteringIdentifier)

An identifier for grouping annotations into the same cluster.

[`get collisionMode(): AnnotationCollisionMode;
set collisionMode(value: AnnotationCollisionMode);`](/documentation/MapKitJS/Annotation/collisionMode-data.property)

A mode that determines the shape of the collision frame.

### Managing selection accessories

[`get selectionAccessory(): PlaceSelectionAccessory | null;
set selectionAccessory(value: PlaceSelectionAccessory | null);`](/documentation/MapKitJS/Annotation/selectionAccessory)

An accessory that displays place information when a person selects a place.

[`get selectionAccessoryOffset(): DOMPoint | null;
set selectionAccessoryOffset(value: DOMPoint | null);`](/documentation/MapKitJS/Annotation/selectionAccessoryOffset)

An offset that changes the selection accessory’s default anchor point.

### Deprecated

[`static get CollisionMode(): typeof AnnotationCollisionMode;`](/documentation/MapKitJS/Annotation/CollisionMode-data.var)

A static property that allows you to access the annotation’s collision mode enumeration values.

[`static get DisplayPriority(): typeof AnnotationDisplayPriority;`](/documentation/MapKitJS/Annotation/DisplayPriority-data.var)

A static property that allows you to access the available display priority enumeration values.

## Relationships

### Inherited By

[`MarkerAnnotation`](/documentation/MapKitJS/MarkerAnnotation)

[`UserLocationAnnotation`](/documentation/MapKitJS/UserLocationAnnotation)

[`ImageAnnotation`](/documentation/MapKitJS/ImageAnnotation)

### Inherits From

`EventTarget`

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)