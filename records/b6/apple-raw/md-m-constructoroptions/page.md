<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/MapConstructorOptions",
  "metadataVersion" : "0.1.0",
  "role" : "Interface",
  "symbol" : {
    "kind" : "Interface",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "struct/mapkit.MapConstructorOptions"
  },
  "title" : "MapConstructorOptions"
}
-->

# MapConstructorOptions

An object that contains options for creating a map’s features.

```
interface MapConstructorOptions
```

## Overview

Use [`MapConstructorOptions`](/documentation/MapKitJS/MapConstructorOptions) to set the initial characteristics for your map, including the visible portion of the map, which controls are visible, the configuration of overlays and annotations, and the visibility of the user’s location.

## Topics

### Controlling the visible portion of the map

[`visibleMapRect?: MapRectData;`](/documentation/MapKitJS/MapConstructorOptions/visibleMapRect)

The visible area of the map, in map units.

[`region?: CoordinateRegionData;`](/documentation/MapKitJS/MapConstructorOptions/region)

The area the map is displaying.

[`center?: CoordinateData;`](/documentation/MapKitJS/MapConstructorOptions/center)

The map coordinate at the center of the map view.

[`rotation?: number;`](/documentation/MapKitJS/MapConstructorOptions/rotation)

The map’s rotation, in degrees.

[`tintColor?: string;`](/documentation/MapKitJS/MapConstructorOptions/tintColor)

The CSS color that MapKit JS uses for the user interface controls on the map.

### Setting the map’s appearance and controls

[`colorScheme?: ColorScheme;`](/documentation/MapKitJS/MapConstructorOptions/colorScheme)

The map’s color scheme when displaying standard or muted standard map types.

[`mapType?: MapType;`](/documentation/MapKitJS/MapConstructorOptions/mapType)

The type of data that the map view displays.

[`padding?: PaddingData;`](/documentation/MapKitJS/MapConstructorOptions/padding)

The map’s inset margins.

[`showsMapTypeControl?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/showsMapTypeControl)

A Boolean value that determines whether to display a control that lets users choose the map type.

[`isRotationEnabled?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/isRotationEnabled)

A Boolean value that determines whether the user may rotate the map using the compass control or a rotate gesture.

[`showsCompass?: FeatureVisibility;`](/documentation/MapKitJS/MapConstructorOptions/showsCompass)

A feature visibility setting that determines when the compass is visible.

[`isZoomEnabled?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/isZoomEnabled)

A Boolean value that determines whether the user may zoom in and out on the map using pinch gestures or the zoom control.

[`showsZoomControl?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/showsZoomControl)

A Boolean value that determines whether to display a control for zooming in and zooming out on a map.

[`isScrollEnabled?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/isScrollEnabled)

A Boolean value that determines whether the user may scroll the map with a pointing device or gestures on a touchscreen.

[`showsScale?: FeatureVisibility;`](/documentation/MapKitJS/MapConstructorOptions/showsScale)

A feature visibility setting that allows you to determine when to display the map’s scale.

### Configuring map annotations

[`annotationForCluster?: (
    clusterAnnotation: ClusterAnnotation,
) => Annotation | undefined;`](/documentation/MapKitJS/MapConstructorOptions/annotationForCluster)

Modifies cluster annotations.

[`annotations?: Annotation[];`](/documentation/MapKitJS/MapConstructorOptions/annotations)

An array holding all the annotations on the map.

[`selectedAnnotation?: Annotation;`](/documentation/MapKitJS/MapConstructorOptions/selectedAnnotation)

The selected annotation on the map.

### Configuring map overlays

[`overlays?: Overlay[];`](/documentation/MapKitJS/MapConstructorOptions/overlays)

An array that contains all of the map’s overlays.

[`selectedOverlay?: Overlay;`](/documentation/MapKitJS/MapConstructorOptions/selectedOverlay)

The selected overlay on the map.

[`showsPointsOfInterest?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/showsPointsOfInterest)

A Boolean value that determines whether the map displays points of interest.

[`pointOfInterestFilter?: PointOfInterestFilter;`](/documentation/MapKitJS/MapConstructorOptions/pointOfInterestFilter)

The filter that determines the points of interest that display on the map.

### Enabling user location

[`showsUserLocation?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/showsUserLocation)

A Boolean value that determines whether to show the user’s location on the map.

[`tracksUserLocation?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/tracksUserLocation)

A Boolean value that determines whether to center the map on the user’s location.

[`showsUserLocationControl?: boolean;`](/documentation/MapKitJS/MapConstructorOptions/showsUserLocationControl)

A Boolean value that determines whether the user location control is visible.

### Setting the loading priority

[`loadPriority?: MapLoadPriority;`](/documentation/MapKitJS/MapConstructorOptions/loadPriority)

A value MapKit JS uses for prioritizing the visibility of specific map features before the underlaying map tiles.

[`const MapLoadPriority: Readonly<{
    readonly LandCover: "LandCover";
    readonly PointsOfInterest: "PointsOfInterest";
    readonly None: null;
}>
type MapLoadPriority = (typeof MapLoadPriority)[keyof typeof MapLoadPriority];`](/documentation/MapKitJS/MapLoadPriority)

Constants that prioritize the visibility of specific map features during map loading.

### Instance Properties

[`annotationForMapFeature?: (
    mapFeatureAnnotation: MapFeatureAnnotation,
) => Annotation | undefined;`](/documentation/MapKitJS/MapConstructorOptions/annotationForMapFeature)

The method MapKit JS calls when the framework creates a map feature annotation.

[`cameraBoundary?: CoordinateRegionData | MapRectData | null;`](/documentation/MapKitJS/MapConstructorOptions/cameraBoundary)

The boundary of the area within which the map view’s center needs to remain.

[`cameraDistance?: number;`](/documentation/MapKitJS/MapConstructorOptions/cameraDistance)

The altitude of the camera relative to the elevation of the center of the map.

[`cameraZoomRange?: CameraZoomRangeData;`](/documentation/MapKitJS/MapConstructorOptions/cameraZoomRange)

Values that set the minimum and maximum distances of the camera from the map center.

[`distances?: DistanceUnitSystem;`](/documentation/MapKitJS/MapConstructorOptions/distances)

The system of measurement that displays on the map.

[`selectableMapFeatureSelectionAccessory?: PlaceSelectionAccessory;`](/documentation/MapKitJS/MapConstructorOptions/selectableMapFeatureSelectionAccessory)

An accessory that displays place information when someone selects a map feature.

[`selectableMapFeatures?: MapFeatureType[];`](/documentation/MapKitJS/MapConstructorOptions/selectableMapFeatures)

An array of map features that someone can select from the map.

[`tileOverlays?: TileOverlay[];`](/documentation/MapKitJS/MapConstructorOptions/tileOverlays)

An array of the map tile overlays.

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)