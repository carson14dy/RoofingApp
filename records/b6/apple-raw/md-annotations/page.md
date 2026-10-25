<!--
{
  "documentType" : "article",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/annotations",
  "metadataVersion" : "0.1.0",
  "role" : "collectionGroup",
  "title" : "Annotations"
}
-->

# Annotations

Create annotations to add indicators and additional details for specific locations on a map.

## Discussion

Annotations work differently in MapKit JS and native MapKit. In native MapKit, there are annotation objects and annotation views. You decide which annotation view to use for a particular annotation by implementing <doc://com.apple.documentation/documentation/MapKit/MKMapViewDelegate/mapView(_:viewFor:)-8humz> in the map’s delegate. In MapKit JS, there’s only the annotation, which is both model and view. You can still customize the look of annotations, but MapKit JS requires that you create annotation views explicitly rather than through a delegate.

MapKit JS shows single-point annotations on a map. The framework accomplishes this by creating a [`Annotation`](/documentation/MapKitJS/Annotation) object and adding it to a map. The framework provides three built-in objects for your convenience:

- [`Annotation`](/documentation/MapKitJS/Annotation), which allows you to position a live DOM element on the map.
- [`ImageAnnotation`](/documentation/MapKitJS/ImageAnnotation), which allows you to customize the annotation with your own imagery.
- [`MarkerAnnotation`](/documentation/MapKitJS/MarkerAnnotation), which places a defined *Apple look-and-feel* balloon marker on the map with a `title`, `subtitle`, and custom glyph text/image.
- [`PlaceAnnotation`](/documentation/MapKitJS/PlaceAnnotation), which places an annotation for a particular place on a map.
- [`MapFeatureAnnotation`](/documentation/MapKitJS/MapFeatureAnnotation), which places an image for a particular feature on a map.

A callout is a standard or custom element that can give more information about an annotation. A standard callout displays the annotation’s title and subtitle, if you provide them. A callout appears when the user selects an annotation interactively (by clicking or tapping), or programmatically when you set the annotation’s [`selected`](/documentation/MapKitJS/Annotation/selected) property to `true`. A callout goes away when the user deselects an annotation interactively either by tapping or clicking the map or by selecting another item on the map, or when you deselect it programmatically.

**Annotation events**

|Event       |Interface                                                              |Summary                                                                                                                                                                                                                                                                                           |
|------------|-----------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|`select`    |`Event`                                                                |MapKit JS sets the annotation’s selected property to `true`.                                                                                                                                                                                                                                      |
|`deselect`  |`Event`                                                                |MapKit JS sets the annotation’s selected property to `false`.                                                                                                                                                                                                                                     |
|`drag-start`|`Event`                                                                |The user initiates a drag for an annotation. A long press or click without movement isn’t a drag.                                                                                                                                                                                                 |
|`dragging`  |``doc://com.apple.mapkitjs/documentation/MapKitJS/AnnotationDragEvent``|The user is dragging an annotation. This event has an extra coordinate property for the coordinate of the annotation at the time the event occurs. Note: This is different from the annotation’s own coordinate property because that property doesn’t update until the user drops the annotation.|
|`drag-end`  |`Event`                                                                |The user ends a drag for an annotation.                                                                                                                                                                                                                                                           |

## Topics

### Annotations

[Clustering annotations](/documentation/MapKitJS/clustering-annotations)

Combine multiple annotations into a single clustered annotation.

[`class Annotation extends EventTarget`](/documentation/MapKitJS/Annotation)

The base annotation object for creating custom annotations.

[`class ImageAnnotation extends Annotation`](/documentation/MapKitJS/ImageAnnotation)

A customized annotation with image resources that you provide.

[`class MarkerAnnotation extends Annotation`](/documentation/MapKitJS/MarkerAnnotation)

An annotation that displays a balloon-shaped marker at the designated location.

[`class PlaceAnnotation extends MarkerAnnotation`](/documentation/MapKitJS/PlaceAnnotation)

An annotation for a place.

[`class MapFeatureAnnotation extends PlaceAnnotation`](/documentation/MapKitJS/MapFeatureAnnotation)

An object that represents a map feature that the user selects.

[`class UserLocationAnnotation extends Annotation`](/documentation/MapKitJS/UserLocationAnnotation)

An annotation that represents someone’s location.

### Customize annotations

[`interface AnnotationCalloutDelegate`](/documentation/MapKitJS/AnnotationCalloutDelegate)

Methods for customizing the behavior and appearance of an annotation callout.

[`const AnnotationCollisionMode: Readonly<{
    readonly Rectangle: "rectangle";
    readonly Circle: "circle";
    readonly None: "none";
}>
type AnnotationCollisionMode =
    (typeof AnnotationCollisionMode)[keyof typeof AnnotationCollisionMode];`](/documentation/MapKitJS/AnnotationCollisionMode)

Constants that indicate the collision mode for an annotation.

[`const AnnotationDisplayPriority: Readonly<{
    readonly Low: 250;
    readonly High: 750;
    readonly Required: 1000;
}>
type AnnotationDisplayPriority =
    (typeof AnnotationDisplayPriority)[keyof typeof AnnotationDisplayPriority];`](/documentation/MapKitJS/AnnotationDisplayPriority)

Constants that indicate the priority for displaying annotations on the map.

[`interface Size`](/documentation/MapKitJS/Size)

A structure that represents a size.

### Events

[`class AnnotationDragEvent extends Event`](/documentation/MapKitJS/AnnotationDragEvent)

An event that occurs when someone drags an annotation.



---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)