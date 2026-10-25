<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/Map",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit.Map"
  },
  "title" : "Map"
}
-->

# Map

An embeddable interactive map that you add to a webpage.

```
class Map extends EventTarget
```

## Overview

A map is a self-contained view object that you embed on a webpage. It’s possible to have multiple independent maps on a single webpage, although typically webpages only need one interactive map.

## Topics

### Creating a map

[`constructor(
    parent?: string | HTMLElement | null,
    options?: MapConstructorOptions,
);`](/documentation/MapKitJS/Map/MapConstructor)

Creates a map you embed on a webpage and initializes it with the constructor options you choose.

[`interface MapConstructorOptions`](/documentation/MapKitJS/MapConstructorOptions)

An object that contains options for creating a map’s features.

### Handling map events

[Handling map events](/documentation/MapKitJS/handling-map-events)

Register an event lister for events that a map object dispatches.

### Accessing interaction properties

[`get isRotationAvailable(): boolean;
set isRotationAvailable(_: boolean);`](/documentation/MapKitJS/Map/isRotationAvailable)

A Boolean value that indicates whether map rotation is available.

[`get isRotationEnabled(): boolean;
set isRotationEnabled(value: boolean);`](/documentation/MapKitJS/Map/isRotationEnabled)

A Boolean value that determines whether the user may rotate the map using the compass control or a rotate gesture.

[`get isScrollEnabled(): boolean;
set isScrollEnabled(value: boolean);`](/documentation/MapKitJS/Map/isScrollEnabled)

A Boolean value that determines whether the user can cause the map to scroll with a pointing device or with gestures on a touchscreen.

[`get isZoomEnabled(): boolean;
set isZoomEnabled(value: boolean);`](/documentation/MapKitJS/Map/isZoomEnabled)

A Boolean value that determines whether the user may zoom in and out on the map using pinch gestures or the zoom control.

### Manipulating the visible portion of the map

[`get center(): Coordinate;
set center(center: CoordinateData);`](/documentation/MapKitJS/Map/center)

The map coordinate at the center of the map view.

[`setCenterAnimated(coordinate: CoordinateData, animated?: boolean): Map;`](/documentation/MapKitJS/Map/setCenterAnimated)

Centers the map to the provided coordinate, with optional animation.

[`get region(): CoordinateRegion;
set region(region: CoordinateRegionData);`](/documentation/MapKitJS/Map/region)

The area the map is displaying.

[`setRegionAnimated(region: CoordinateRegionData, animated?: boolean): Map;`](/documentation/MapKitJS/Map/setRegionAnimated)

Changes the map’s region to the provided region, with optional animation.

[`get rotation(): number;
set rotation(rotation: number);`](/documentation/MapKitJS/Map/rotation)

The map’s rotation, in degrees.

[`setRotationAnimated(degrees: number, animated?: boolean): Map | null;`](/documentation/MapKitJS/Map/setRotationAnimated)

Changes the map’s rotation setting to the number of specified degrees.

[`get visibleMapRect(): MapRect;
set visibleMapRect(visibleMapRect: MapRectData);`](/documentation/MapKitJS/Map/visibleMapRect)

The visible area of the map, in map units.

[`setVisibleMapRectAnimated(mapRect: MapRectData, animated?: boolean): Map;`](/documentation/MapKitJS/Map/setVisibleMapRectAnimated)

Changes the map’s visible map rectangle to the specified map rectangle.

[`get cameraBoundary(): CameraBoundaryDescription | null;
set cameraBoundary(
    cameraBoundary: null | CoordinateRegionData | MapRectData,
);`](/documentation/MapKitJS/Map/cameraBoundary)

A constraint of the location of the center of the map.

[`setCameraBoundaryAnimated(
    cameraBoundary: null | CoordinateRegionData | MapRectData,
    animated?: boolean,
): Map;`](/documentation/MapKitJS/Map/setCameraBoundaryAnimated)

Changes the map’s camera boundary with an animated transition.

[`interface CameraBoundaryDescription`](/documentation/MapKitJS/CameraBoundaryDescription)

An object literal that contains information defining an area on the map.

[`get cameraDistance(): number;
set cameraDistance(value: number);`](/documentation/MapKitJS/Map/cameraDistance)

The altitude of the camera relative to the elevation of the center of the map.

[`setCameraDistanceAnimated(distance: number, animated?: boolean): Map;`](/documentation/MapKitJS/Map/setCameraDistanceAnimated)

Changes the map’s camera distance with an animated transition.

[`get cameraZoomRange(): CameraZoomRange | undefined;
set cameraZoomRange(value: CameraZoomRangeData | undefined | null);`](/documentation/MapKitJS/Map/cameraZoomRange)

The minimum and maximum distances of the camera from the map center.

[`setCameraZoomRangeAnimated(
    cameraZoomRange: CameraZoomRangeData | null,
    animated?: boolean,
): Map;`](/documentation/MapKitJS/Map/setCameraZoomRangeAnimated)

Changes the map’s camera zoom range with an animated transition.

### Showing the map’s controls

[`get showsCompass(): FeatureVisibility;
set showsCompass(value: FeatureVisibility);`](/documentation/MapKitJS/Map/showsCompass)

A feature visibility setting that determines when the compass is visible.

[`get showsMapTypeControl(): boolean;
set showsMapTypeControl(showsMapTypeControl: boolean);`](/documentation/MapKitJS/Map/showsMapTypeControl)

A Boolean value that determines whether to display a control that lets users choose the map type.

[`get showsScale(): FeatureVisibility;
set showsScale(showsScale: FeatureVisibility);`](/documentation/MapKitJS/Map/showsScale)

A feature visibility setting that determines when the map displays the map’s scale indicator.

[`get showsUserLocationControl(): boolean;
set showsUserLocationControl(showsUserLocationControl: boolean);`](/documentation/MapKitJS/Map/showsUserLocationControl)

A Boolean value that determines whether the user location control is visible.

[`get showsZoomControl(): boolean;
set showsZoomControl(showsZoomControl: boolean);`](/documentation/MapKitJS/Map/showsZoomControl)

A Boolean value that determines whether to display a control for zooming in and zooming out on a map.

### Configuring the map’s appearance

[`get colorScheme(): ColorScheme;
set colorScheme(colorScheme: ColorScheme);`](/documentation/MapKitJS/Map/colorScheme)

The map’s color scheme when displaying standard or muted standard map types.

[`get distances(): DistanceUnitSystem;
set distances(distances: DistanceUnitSystem);`](/documentation/MapKitJS/Map/distances-data.property)

The system of measurement that displays on the map.

[`get mapType(): MapType;
set mapType(mapType: MapType);`](/documentation/MapKitJS/Map/mapType)

The type of data that the map displays.

[`get padding(): Padding;
set padding(padding: PaddingData);`](/documentation/MapKitJS/Map/padding)

The map’s inset margins.

[`get pointOfInterestFilter(): PointOfInterestFilter | null;
set pointOfInterestFilter(filter: PointOfInterestFilter | null);`](/documentation/MapKitJS/Map/pointOfInterestFilter)

The filter that determines the points of interest that display on the map.

[`get showsPointsOfInterest(): boolean;
set showsPointsOfInterest(showsPointsOfInterest: boolean);`](/documentation/MapKitJS/Map/showsPointsOfInterest)

A Boolean value that determines whether the map displays points of interest.

[`showItems(
    items: (Overlay | Annotation)[],
    options?: MapShowItemsOptions,
): (Annotation | Overlay)[];`](/documentation/MapKitJS/Map/showItems)

Adjusts the map’s visible region to bring the specified overlays and annotations into view.

[`interface MapShowItemsOptions`](/documentation/MapKitJS/MapShowItemsOptions)

Options that determine the map parameters to use when showing items.

[`get tintColor(): string;
set tintColor(value: string);`](/documentation/MapKitJS/Map/tintColor)

The CSS color that MapKit JS uses for user interface controls on the map.

### Annotating the map

[`get annotations(): Annotation[];
set annotations(annotations: Annotation[]);`](/documentation/MapKitJS/Map/annotations)

An array of all the annotations on the map.

[`get selectedAnnotation(): Annotation | null;
set selectedAnnotation(annotation: Annotation | null);`](/documentation/MapKitJS/Map/selectedAnnotation)

The selected annotation.

[`get annotationForCluster():
    | ((clusterAnnotation: ClusterAnnotation) => Annotation | undefined)
    | null;
set annotationForCluster(
    value:
        | ((clusterAnnotation: ClusterAnnotation) => Annotation | undefined)
        | null,
);`](/documentation/MapKitJS/Map/annotationForCluster)

A delegate method for modifying an annotation that represents a group of annotations that the framework combines into a cluster.

[`annotationsInMapRect(mapRect: MapRectData): Annotation[];`](/documentation/MapKitJS/Map/annotationsInMapRect)

Returns the list of annotation objects within the specified map rectangle.

[`addAnnotation(annotation: Annotation): Annotation | null;`](/documentation/MapKitJS/Map/addAnnotation)

Adds an annotation to the map.

[`addAnnotations(annotations: Annotation[]): Annotation[];`](/documentation/MapKitJS/Map/addAnnotations)

Adds an array of annotations to the map.

[`removeAnnotation(annotation: Annotation): Annotation;`](/documentation/MapKitJS/Map/removeAnnotation)

Removes an annotation from the map.

[`removeAnnotations(annotations: Annotation[]): Annotation[];`](/documentation/MapKitJS/Map/removeAnnotations)

Removes multiple annotations from the map.

### Adding and removing overlays

[`get overlays(): Overlay[];
set overlays(overlays: Overlay[]);`](/documentation/MapKitJS/Map/overlays)

An array of all of the map’s overlays.

[`get selectedOverlay(): Overlay | null;
set selectedOverlay(overlay: Overlay | null);`](/documentation/MapKitJS/Map/selectedOverlay)

The selected overlay on the map.

[`overlaysAtPoint(point: DOMPoint): Overlay[];`](/documentation/MapKitJS/Map/overlaysAtPoint)

Returns an array of overlays at a given point on the webpage.

[`addOverlay(overlay: Overlay): Overlay | null;`](/documentation/MapKitJS/Map/addOverlay)

Adds an overlay to the map.

[`addOverlays(overlays: Overlay[]): Overlay[];`](/documentation/MapKitJS/Map/addOverlays)

Adds multiple overlays to the map.

[`removeOverlay(overlay: Overlay): Overlay;`](/documentation/MapKitJS/Map/removeOverlay)

Removes an overlay from the map.

[`removeOverlays(overlays: Overlay[]): Overlay[];`](/documentation/MapKitJS/Map/removeOverlays)

Removes multiple overlays from the map.

[`topOverlayAtPoint(point: DOMPoint): Overlay | null;`](/documentation/MapKitJS/Map/topOverlayAtPoint)

Returns the topmost overlay at a given point on the webpage.

### Adding and removing geographical features

[`addItems(items: (Overlay | Annotation)[]): (Annotation | Overlay)[];`](/documentation/MapKitJS/Map/addItems)

Adds a collection of annotations, overlays, or other item collections to the map.

[`removeItems(items: (Overlay | Annotation)[]): (Annotation | Overlay)[];`](/documentation/MapKitJS/Map/removeItems)

Removes a collection of annotations, overlays, or other item collections from the map.

### Adding and removing tile overlays

[`get tileOverlays(): TileOverlay[];
set tileOverlays(tileOverlays: TileOverlay[]);`](/documentation/MapKitJS/Map/tileOverlays)

An array of all of the map’s tile overlays.

[`addTileOverlay(tileOverlay: TileOverlay): TileOverlay;`](/documentation/MapKitJS/Map/addTileOverlay)

Adds a tile overlay to the map.

[`addTileOverlays(tileOverlays: TileOverlay[]): TileOverlay[];`](/documentation/MapKitJS/Map/addTileOverlays)

Adds an array of tile overlays to the map.

[`removeTileOverlay(tileOverlay: TileOverlay): TileOverlay;`](/documentation/MapKitJS/Map/removeTileOverlay)

Removes a tile overlay from the map.

[`removeTileOverlays(tileOverlays: TileOverlay[]): TileOverlay[];`](/documentation/MapKitJS/Map/removeTileOverlays)

Removes an array of tile overlays from the map.

### Exploring at street level

[`class LookAround extends AbstractLookAround`](/documentation/MapKitJS/LookAround)

A view that allows someone to see a street level view of a place.

[`interface LookAroundOptions extends CommonLookAroundOptions`](/documentation/MapKitJS/LookAroundOptions)

Options for initializing a LookAround view.

[`class LookAroundPreview extends AbstractLookAround`](/documentation/MapKitJS/LookAroundPreview)

A class that renders a preview of a Look Around view.

[`interface LookAroundPreviewOptions extends CommonLookAroundOptions`](/documentation/MapKitJS/LookAroundPreviewOptions)

Options for initializing a LookAroundPreview object.

[`class LookAroundScene`](/documentation/MapKitJS/LookAroundScene)

Object that represents the current location of the view.

[`interface CommonLookAroundOptions`](/documentation/MapKitJS/CommonLookAroundOptions)

Options that control the behavior of Look Around views.

### Displaying the user’s location

[`get showsUserLocation(): boolean;
set showsUserLocation(value: boolean);`](/documentation/MapKitJS/Map/showsUserLocation)

A Boolean value that determines whether to show the user’s location on the map.

[`get tracksUserLocation(): boolean;
set tracksUserLocation(value: boolean);`](/documentation/MapKitJS/Map/tracksUserLocation)

A Boolean value that determines whether to center the map on the user’s location.

[`get userLocationAnnotation(): UserLocationAnnotation | null;`](/documentation/MapKitJS/Map/userLocationAnnotation)

An annotation that indicates the user’s location on the map.

### Converting map coordinates

[`convertCoordinateToPointOnPage(coordinate: CoordinateData): DOMPoint;`](/documentation/MapKitJS/Map/convertCoordinateToPointOnPage)

Converts a coordinate on the map to a point in the page’s coordinate system.

[`convertPointOnPageToCoordinate(point: DOMPoint): Coordinate;`](/documentation/MapKitJS/Map/convertPointOnPageToCoordinate)

Converts a point in page coordinates to the corresponding map coordinate.

### Destroying a map

[`destroy(): void;`](/documentation/MapKitJS/Map/destroy)

Removes the map’s element from the DOM and releases internal references to the map to free up memory.

### Accessing the element

[`get element(): HTMLDivElement | null;
set element(_: HTMLDivElement | null);`](/documentation/MapKitJS/Map/element)

The map’s DOM element.

### Selecting map features

[`get selectableMapFeatures(): MapFeatureType[];
set selectableMapFeatures(value: MapFeatureType[]);`](/documentation/MapKitJS/Map/selectableMapFeatures)

An array of map features that users can select from the map.

[`get selectableMapFeatureSelectionAccessory(): PlaceSelectionAccessory | null;
set selectableMapFeatureSelectionAccessory(
    value: PlaceSelectionAccessory | null,
);`](/documentation/MapKitJS/Map/selectableMapFeatureSelectionAccessory)

An accessory for displaying place information when a person selects a map feature.

[`get annotationForMapFeature():
    | ((
          mapFeatureAnnotation: MapFeatureAnnotation,
      ) => Annotation | undefined)
    | undefined;
set annotationForMapFeature(
    value:
        | ((
              mapFeatureAnnotation: MapFeatureAnnotation,
          ) => Annotation | undefined)
        | undefined,
);`](/documentation/MapKitJS/Map/annotationForMapFeature)

The method MapKit JS calls when the framework creates a map feature annotation.

### Prioritizing feature loading

[`get loadPriority(): MapLoadPriority;
set loadPriority(value: MapLoadPriority);`](/documentation/MapKitJS/Map/loadPriority)

A value MapKit JS uses for prioritizing the visibility of specific map features before the underlaying map tiles.

### Deprecated

[`static get ColorSchemes(): typeof ColorScheme;`](/documentation/MapKitJS/Map/ColorSchemes)

A static property that lets you access the color scheme enumeration.

[`static get Distances(): typeof DistanceUnitSystem;`](/documentation/MapKitJS/Map/Distances-data.var)

A static property that allows you to access the distance enumeration.

[`static get LoadPriorities(): typeof MapLoadPriority;`](/documentation/MapKitJS/Map/LoadPriorities)

A static property that allows you to access the load priority enumeration.

[`static get MapTypes(): typeof MapType;`](/documentation/MapKitJS/Map/MapTypes)

A static property that allows you to access the map type enumeration.

## Relationships

### Inherits From

`EventTarget`

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)