<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/ImageAnnotation",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.ImageAnnotation"
  },
  "title" : "ImageAnnotation"
}
-->

# ImageAnnotation

A customized annotation with image resources that you provide.

```
class ImageAnnotation extends Annotation
```

## Overview

There are times when you want to customize the look of an annotation. To do this, use an [`ImageAnnotation`](/documentation/MapKitJS/ImageAnnotation) object, which lets you specify your own image resources by providing a URL to your asset (such as a PNG or JPEG image), an [`ImageSource`](/documentation/MapKitJS/ImageSource) like an `HTMLCanvasElement` or `ImageBitmap`, or a `Promise` that resolves to an [`ImageSource`](/documentation/MapKitJS/ImageSource).

To make your image look crisp on Retina displays, provide URLs to the Retina versions of your asset, or use an [`ImageDelegate`](/documentation/MapKitJS/ImageDelegate) to dynamically return the appropriate image. You may want to define the anchor of your asset with [`anchorOffset`](/documentation/MapKitJS/Annotation/anchorOffset).

The shape of your icon might affect the placement of the callout. You can modify the position of the callout with [`calloutOffset`](/documentation/MapKitJS/Annotation/calloutOffset).

## Topics

### Creating an image annotation

[`constructor(
    location: CoordinateData | Place | SearchAutocompleteResult,
    options: ImageAnnotationConstructorOptions,
);`](/documentation/MapKitJS/ImageAnnotation/ImageAnnotationConstructor)

Creates an image annotation with an image and a coordinate.

[`interface ImageAnnotationConstructorOptions
    extends AnnotationConstructorOptions`](/documentation/MapKitJS/ImageAnnotationConstructorOptions)

An object containing options for creating an image annotation.

### Setting the image

[`get image():
    | ImageDelegate
    | ImageHashObject
    | ImageSource
    | Promise<ImageSource>;
set image(
    value:
        | ImageDelegate
        | ImageHashObject
        | ImageSource
        | Promise<ImageSource>,
);`](/documentation/MapKitJS/ImageAnnotation/image)

The image for the annotation.

[`get url():
    | ImageDelegate
    | ImageHashObject
    | ImageSource
    | Promise<ImageSource>;
set url(
    value:
        | ImageDelegate
        | ImageHashObject
        | ImageSource
        | Promise<ImageSource>,
);`](/documentation/MapKitJS/ImageAnnotation/url)

An object that contains URLs for the image assets in multiple resolutions.

## Relationships

### Inherits From

[`Annotation`](/documentation/MapKitJS/Annotation)

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)