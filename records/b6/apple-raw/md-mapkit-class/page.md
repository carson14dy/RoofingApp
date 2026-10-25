<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/mapkit",
  "metadataVersion" : "0.1.0",
  "role" : "Class",
  "symbol" : {
    "kind" : "Class",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "cl/mapkit"
  },
  "title" : "mapkit"
}
-->

# mapkit

The JavaScript API for embedding Apple Maps on your website.

```
class MapKit extends EventTarget
```

## Overview

The [`mapkit`](/documentation/MapKitJS/mapkit) object is the main namespace for the MapKit JS framework. Similar to <doc://com.apple.documentation/documentation/MapKit> for apps, you can use MapKit JS to display interactive maps with customized annotations and overlays, and provide directions and search services. Your app can supply step-by-step navigation, and help a user find a location by autocompleting a search query.

MapKit JS lets you customize the look of your map. You can choose style details for overlays and annotations, display a standard street map or one that uses satellite imagery, and adjust the visibility of map controls. Additionally, you can customize a map’s behavior by providing event handlers that cause the map to scroll or respond when users select items. You can also enable or disable panning, zooming, and rotation.

## Topics

### Initialization

[Handling initialization events](/documentation/MapKitJS/handling-initialization-events)

Respond to events that trigger when MapKit JS initializes.

[`init(options: MapKitInitializationOptions): void;`](/documentation/MapKitJS/mapkit/init)

Initializes MapKit JS by providing an authorization callback function and optional language.

[`interface MapKitInitializationOptions`](/documentation/MapKitJS/MapKitInitializationOptions)

Initialization options for MapKit JS.

[`get Libraries(): string[] | undefined;`](/documentation/MapKitJS/mapkit/Libraries)

The list of available libraries.

[`get loadedLibraries(): string[] | undefined;`](/documentation/MapKitJS/mapkit/loadedLibraries)

A string that describes the list of loaded libraries.

[`load?(libraryNames: string | string[]): Promise<MapKit>;`](/documentation/MapKitJS/mapkit/load)

Tells MapKit JS which libraries to load.

### Maps

[`class Map extends EventTarget`](/documentation/MapKitJS/Map)

An embeddable interactive map that you add to a webpage.

[`get maps(): Map[];`](/documentation/MapKitJS/mapkit/maps)

An array that automatically adds and removes maps as the framework creates and destroys them.

### Annotations and overlays

[Annotations](/documentation/MapKitJS/annotations)

Create annotations to add indicators and additional details for specific locations on a map.

[Overlays](/documentation/MapKitJS/overlays)

Create overlays to highlight geographic regions or paths.

### Geocoder

[`class Geocoder extends Service`](/documentation/MapKitJS/Geocoder)

A geocoder that converts human-readable addresses to geographic coordinates, and vice versa.

### Search

[`class AddressFilter`](/documentation/MapKitJS/AddressFilter)

An object that filters which address options to include or exclude in search results.

[`class Search extends Service`](/documentation/MapKitJS/Search)

An object that retrieves map-based search results for a user-entered query.

### Points of interest

[`get filterExcludingAllCategories(): PointOfInterestFilter;`](/documentation/MapKitJS/mapkit/filterExcludingAllCategories)

A value that excludes all point-of-interest categories.

[`get filterIncludingAllCategories(): PointOfInterestFilter;`](/documentation/MapKitJS/mapkit/filterIncludingAllCategories)

A value that includes all point-of-interest categories.

[`class PointOfInterestFilter`](/documentation/MapKitJS/PointOfInterestFilter)

A filter for determining the points of interest to include or exclude on a map or in a local search.

[`class PointsOfInterestSearch extends Service`](/documentation/MapKitJS/PointsOfInterestSearch)

An object that fetches points of interest within a specified region.

[`class MapFeatureAnnotation extends PlaceAnnotation`](/documentation/MapKitJS/MapFeatureAnnotation)

An object that represents a map feature that the user selects.

[`class MapFeatureAnnotationGlyphImage implements ImageDelegate`](/documentation/MapKitJS/MapFeatureAnnotationGlyphImage)

An object that describes map feature annotation images.

### Directions

[`class Directions extends Service`](/documentation/MapKitJS/Directions)

An object that provides directions and estimated travel time based on the options you provide.

### Enumerations

[`const AddressCategory: Readonly<{
    readonly Country: "Country";
    readonly AdministrativeArea: "AdministrativeArea";
    readonly SubAdministrativeArea: "SubAdministrativeArea";
    readonly Locality: "Locality";
    readonly SubLocality: "SubLocality";
    readonly PostalCode: "PostalCode";
}>
type AddressCategory =
    (typeof AddressCategory)[keyof typeof AddressCategory];`](/documentation/MapKitJS/AddressCategory)

The categories of address components that users can search for with an address filter.

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

[`const ColorScheme: Readonly<{
    readonly Dark: "dark";
    readonly Light: "light";
    readonly Adaptive: "adaptive";
}>
type ColorScheme = (typeof ColorScheme)[keyof typeof ColorScheme];`](/documentation/MapKitJS/ColorScheme)

Constants that indicate the color scheme of the map or a place detail.

[`const DistanceUnitSystem: Readonly<{
    readonly Adaptive: "adaptive";
    readonly Metric: "metric";
    readonly Imperial: "imperial";
}>
type DistanceUnitSystem =
    (typeof DistanceUnitSystem)[keyof typeof DistanceUnitSystem];`](/documentation/MapKitJS/DistanceUnitSystem)

Constants that indicate the system of measurement that displays on the map.

[`const FeatureVisibility: Readonly<{
    readonly Adaptive: "adaptive";
    readonly Hidden: "hidden";
    readonly Visible: "visible";
}>
type FeatureVisibility =
    (typeof FeatureVisibility)[keyof typeof FeatureVisibility];`](/documentation/MapKitJS/FeatureVisibility)

Constants indicating the visibility of different adaptive map features.

[`const MapFeatureType: Readonly<{
    readonly PointOfInterest: "PointOfInterest";
    readonly Territory: "Territory";
    readonly PhysicalFeature: "PhysicalFeature";
}>
type MapFeatureType =
    (typeof MapFeatureType)[keyof typeof MapFeatureType];`](/documentation/MapKitJS/MapFeatureType)

Values that describe the feature type of a point of interest.

[`const MapLoadPriority: Readonly<{
    readonly LandCover: "LandCover";
    readonly PointsOfInterest: "PointsOfInterest";
    readonly None: null;
}>
type MapLoadPriority = (typeof MapLoadPriority)[keyof typeof MapLoadPriority];`](/documentation/MapKitJS/MapLoadPriority)

Constants that prioritize the visibility of specific map features during map loading.

[`const MapType: Readonly<{
    readonly Satellite: "satellite";
    readonly Hybrid: "hybrid";
    readonly MutedStandard: "mutedStandard";
    readonly Standard: "standard";
}>
type MapType = (typeof MapType)[keyof typeof MapType];`](/documentation/MapKitJS/MapType)

Constants representing the type of map to display.

[`const PointOfInterestCategory: Readonly<{
    readonly Airport: "Airport";
    readonly AmusementPark: "AmusementPark";
    readonly AnimalService: "AnimalService";
    readonly Aquarium: "Aquarium";
    readonly ATM: "ATM";
    readonly AutomotiveRepair: "AutomotiveRepair";
    readonly Bakery: "Bakery";
    readonly Bank: "Bank";
    readonly Baseball: "Baseball";
    readonly Basketball: "Basketball";
    readonly Beach: "Beach";
    readonly Beauty: "Beauty";
    readonly Bowling: "Bowling";
    readonly Brewery: "Brewery";
    readonly Cafe: "Cafe";
    readonly Campground: "Campground";
    readonly CarRental: "CarRental";
    readonly Castle: "Castle";
    readonly ConventionCenter: "ConventionCenter";
    readonly Distillery: "Distillery";
    readonly EVCharger: "EVCharger";
    readonly Fairground: "Fairground";
    readonly FireStation: "FireStation";
    readonly Fishing: "Fishing";
    readonly FitnessCenter: "FitnessCenter";
    readonly FoodMarket: "FoodMarket";
    readonly Fortress: "Fortress";
    readonly GasStation: "GasStation";
    readonly GoKart: "GoKart";
    readonly Golf: "Golf";
    readonly Hiking: "Hiking";
    readonly Hospital: "Hospital";
    readonly Hotel: "Hotel";
    readonly Kayaking: "Kayaking";
    readonly Landmark: "Landmark";
    readonly Laundry: "Laundry";
    readonly Library: "Library";
    readonly Mailbox: "Mailbox";
    readonly Marina: "Marina";
    readonly MiniGolf: "MiniGolf";
    readonly MovieTheater: "MovieTheater";
    readonly Museum: "Museum";
    readonly MusicVenue: "MusicVenue";
    readonly NationalMonument: "NationalMonument";
    readonly NationalPark: "NationalPark";
    readonly Nightlife: "Nightlife";
    readonly Park: "Park";
    readonly Parking: "Parking";
    readonly Pharmacy: "Pharmacy";
    readonly Planetarium: "Planetarium";
    readonly Police: "Police";
    readonly PostOffice: "PostOffice";
    readonly PublicTransport: "PublicTransport";
    readonly Restaurant: "Restaurant";
    readonly Restroom: "Restroom";
    readonly RockClimbing: "RockClimbing";
    readonly RVPark: "RVPark";
    readonly School: "School";
    readonly SkatePark: "SkatePark";
    readonly Skating: "Skating";
    readonly Skiing: "Skiing";
    readonly Soccer: "Soccer";
    readonly Spa: "Spa";
    readonly Stadium: "Stadium";
    readonly Store: "Store";
    readonly Surfing: "Surfing";
    readonly Swimming: "Swimming";
    readonly Tennis: "Tennis";
    readonly Theater: "Theater";
    readonly University: "University";
    readonly Volleyball: "Volleyball";
    readonly Winery: "Winery";
    readonly Zoo: "Zoo";
}>
type PointOfInterestCategory =
    (typeof PointOfInterestCategory)[keyof typeof PointOfInterestCategory];`](/documentation/MapKitJS/PointOfInterestCategory)

Point-of-interest categories.

[`const RegionPriority: Readonly<{
    readonly Default: "default";
    readonly Required: "required";
}>
type RegionPriority = (typeof RegionPriority)[keyof typeof RegionPriority];`](/documentation/MapKitJS/RegionPriority)

A value that indicates the importance of the configured region.

[`const TransportType: Readonly<{
    readonly Automobile: "AUTOMOBILE";
    readonly Walking: "WALKING";
    readonly Cycling: "CYCLING";
}>
type TransportType = (typeof TransportType)[keyof typeof TransportType];`](/documentation/MapKitJS/TransportType)

The modes of transportation.

### Map view customization

[`class Padding implements PaddingData`](/documentation/MapKitJS/Padding)

The values that define content padding within the map view frame.

[`interface PaddingData`](/documentation/MapKitJS/PaddingData)

A plain object representation of edge inset values.

### Geographical features

[`importGeoJSON(
    data: string | GeoJSONTypes.GeoJSON,
    callback?: GeoJSONDelegate | GeoJSONImporterCallback,
):
    | ItemCollection<
          GeoJSONTypes.GeoJSON<
              GeoJSONTypes.Geometry,
              GeoJSONTypes.GeoJsonProperties
          >
      >
    | undefined;`](/documentation/MapKitJS/mapkit/importGeoJSON)

Converts imported GeoJSON data to MapKit JS compatible items.

[`interface GeoJSONDelegate`](/documentation/MapKitJS/GeoJSONDelegate)

A delegate object that controls a GeoJSON import to override default behavior and provide custom style.

[`type Item = Annotation | Overlay | ItemCollection;`](/documentation/MapKitJS/Item)

A type alias that represents all objects that the framework sets in an item collection.

[`class ItemCollection<D = any>`](/documentation/MapKitJS/ItemCollection)

A tree structure containing annotations, overlays, and nested item collection objects.

[`type GeoJSONImporterCallback = (
    ...args:
        | [GeoJSONImportError, GeoJSONTypes.GeoJSON | undefined]
        | [null, ItemCollection]
) => void;`](/documentation/MapKitJS/GeoJSONImporterCallback)

A callback function that MapKit JS invokes when importing a GeoJSON object.

[`class GeoJSONImportError extends Error`](/documentation/MapKitJS/GeoJSONImportError)

An error object that indicates an error occurred while importing a GeoJSON object.

[Displaying Indoor Maps with MapKit JS](/documentation/MapKitJS/displaying-indoor-maps-with-mapkit-js)

Use the Indoor Mapping Data Format (IMDF) to show an indoor map with custom overlays and points of interest in your browser.

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

[`abstract class AbstractLookAround extends EventTarget`](/documentation/MapKitJS/AbstractLookAround)

An abstract class that provides a common interface for Look Around views.

[`get lookAroundViews(): AbstractLookAround[];`](/documentation/MapKitJS/mapkit/lookAroundViews)

A list of all the Look Around objects that are currently active on a page.

### Places

[`class Place`](/documentation/MapKitJS/Place)

A place object that returns from a geocoder lookup, a reverse lookup, or a fetch request for points of interest.

[`class PlaceLookup extends Service`](/documentation/MapKitJS/PlaceLookup)

An object that provides the ability to look up place information for a specified Place ID.

[`get placeDetails(): PlaceDetail[];`](/documentation/MapKitJS/mapkit/placeDetails)

A list of all place detail objects that are currently active on a page.

[`interface PlaceSelectionAccessoryOptions`](/documentation/MapKitJS/PlaceSelectionAccessoryOptions)

The options for selection accessories.

[`class PlaceAnnotation extends MarkerAnnotation`](/documentation/MapKitJS/PlaceAnnotation)

An annotation for a place.

[`class PlaceDetail`](/documentation/MapKitJS/PlaceDetail)

An interactive view that displays information about a place.

[`class PlaceSelectionAccessory`](/documentation/MapKitJS/PlaceSelectionAccessory)

The accessory that conveys information about a place associated with an annotation.

### Map coordinates

[`class Coordinate implements CoordinateData`](/documentation/MapKitJS/Coordinate)

An object representing the latitude and longitude for a point on the Earth’s surface.

[`interface CoordinateData`](/documentation/MapKitJS/CoordinateData)

A plain object representation of a coordinate.

[`class CoordinateRegion implements CoordinateRegionData`](/documentation/MapKitJS/CoordinateRegion)

A rectangular area on a map that a center coordinate and a span define, in degrees of latitude and longitude.

[`interface CoordinateRegionData`](/documentation/MapKitJS/CoordinateRegionData)

A plain object representation of a coordinate region.

[`class CoordinateSpan implements CoordinateSpanData`](/documentation/MapKitJS/CoordinateSpan)

The width and height of a map region.

[`interface CoordinateSpanData`](/documentation/MapKitJS/CoordinateSpanData)

A plain object representation of a coordinate span.

[`class BoundingRegion`](/documentation/MapKitJS/BoundingRegion)

A rectangular area on a map, which coordinates of the rectangle’s northeast and southwest corners define.

### Map units

[`class MapPoint implements MapPointData`](/documentation/MapKitJS/MapPoint)

A location, in map units, of a point on the Earth’s surface projected onto a 2D map.

[`interface MapPointData`](/documentation/MapKitJS/MapPointData)

A plain object representation of a map point in map units.

[`class MapRect implements MapRectData`](/documentation/MapKitJS/MapRect)

A rectangular region, in map units, of a two-dimensional map projection.

[`interface MapRectData`](/documentation/MapKitJS/MapRectData)

A plain object representation of a rectangular region, in map units, of a two-dimensional map projection.

[`class MapSize implements MapSizeData`](/documentation/MapKitJS/MapSize)

A pair of values, in map units, that define the width and height of a rectangular area of a map projection.

[`interface MapSizeData`](/documentation/MapKitJS/MapSizeData)

A plain object representation of dimensions in map units.

[`class CameraZoomRange implements CameraZoomRangeData`](/documentation/MapKitJS/CameraZoomRange)

A minimum and maximum camera distance, in meters, from the center of the map.

[`interface CameraZoomRangeData`](/documentation/MapKitJS/CameraZoomRangeData)

A plain object representation of a camera zoom range.

### Version and language

[`get language(): string;
set language(language: string);`](/documentation/MapKitJS/mapkit/language)

A language ID indicating the selected language.

[`get build(): string;`](/documentation/MapKitJS/mapkit/build)

The build string.

[`get version(): string;`](/documentation/MapKitJS/mapkit/version)

The version of MapKit JS.

### Response objects

### Setting images

[`type ImageHashObject = Record<string, string | undefined> & {};`](/documentation/MapKitJS/ImageHashObject)

An object that defines a set of images URLs for different scales.

[`interface ImageDelegate`](/documentation/MapKitJS/ImageDelegate)

An object you use to provide images for annotations.

[`type ImageSource =
    | HTMLImageElement
    | HTMLCanvasElement
    | ImageBitmap
    | OffscreenCanvas;`](/documentation/MapKitJS/ImageSource)

A union type that represents image sources that the framework can use for annotations and tile overlays.

### Service

[`abstract class Service`](/documentation/MapKitJS/Service)

An abstract class that provides common interfaces for service objects.

[`class RequestError extends Error`](/documentation/MapKitJS/RequestError)

The error that a service method’s returned promise rejects with when a request fails.

### Deprecated

[`class MapKitEvent`](/documentation/MapKitJS/MapKitEvent)

A generic MapKit JS event object.

[`type MapKitEventListener<T extends MapKitEvent = MapKitEvent> =
    | ((event: T) => void)
    | {
          handleEvent(event: T): void;
      };`](/documentation/MapKitJS/MapKitEventListener)

A type alias that represents a function or an object that receives a MapKit event.

[`class MapKitEventTarget`](/documentation/MapKitJS/MapKitEventTarget)

An abstract class that defines the interface for objects that can dispatch events.

### Namespace properties

[`get AddressCategory(): typeof AddressCategory;`](/documentation/MapKitJS/mapkit/AddressCategory)

An accessor for the address category enumeration.

[`get AddressFilter(): typeof AddressFilter;`](/documentation/MapKitJS/mapkit/AddressFilter)

The getter to use to access the address filter class.

[`get Annotation(): typeof Annotation;`](/documentation/MapKitJS/mapkit/Annotation)

The getter to use to for access the annotation class.

[`get AnnotationCollisionMode(): typeof AnnotationCollisionMode;`](/documentation/MapKitJS/mapkit/AnnotationCollisionMode)

An accessor for the annotation collision mode enumeration.

[`get AnnotationDisplayPriority(): typeof AnnotationDisplayPriority;`](/documentation/MapKitJS/mapkit/AnnotationDisplayPriority)

An accessor for the annotation display priority enumeration.

[`get BoundingRegion(): typeof BoundingRegion;`](/documentation/MapKitJS/mapkit/BoundingRegion)

The getter to use to access the the bounding region class.

[`get CameraZoomRange(): typeof CameraZoomRange;`](/documentation/MapKitJS/mapkit/CameraZoomRange)

The getter to use to access the camera zoom range class.

[`get CircleOverlay(): typeof CircleOverlay;`](/documentation/MapKitJS/mapkit/CircleOverlay)

The getter to use to access the circle overlay class.

[`get ColorScheme(): typeof ColorScheme;`](/documentation/MapKitJS/mapkit/ColorScheme)

An accessor for the color scheme enumeration.

[`get Coordinate(): typeof Coordinate;`](/documentation/MapKitJS/mapkit/Coordinate)

The getter to use to access the coordinate class.

[`get CoordinateRegion(): typeof CoordinateRegion;`](/documentation/MapKitJS/mapkit/CoordinateRegion)

The getter to use to access the coordinate region class.

[`get CoordinateSpan(): typeof CoordinateSpan;`](/documentation/MapKitJS/mapkit/CoordinateSpan)

The getter to use to access the coordinate span class.

[`get Directions(): typeof Directions;`](/documentation/MapKitJS/mapkit/Directions)

The getter to use to access the directions class.

[`get DistanceUnitSystem(): typeof DistanceUnitSystem;`](/documentation/MapKitJS/mapkit/DistanceUnitSystem)

An accessor for the distance unit system enumeration.

[`get FeatureVisibility(): typeof FeatureVisibility;`](/documentation/MapKitJS/mapkit/FeatureVisibility)

An accessor for the feature visibility enumeration.

[`get Geocoder(): typeof Geocoder;`](/documentation/MapKitJS/mapkit/Geocoder)

The getter to use to access the geocoder class.

[`get ImageAnnotation(): typeof ImageAnnotation;`](/documentation/MapKitJS/mapkit/ImageAnnotation)

The getter to use to access the image annotation class.

[`get LineGradient(): typeof LineGradient;`](/documentation/MapKitJS/mapkit/LineGradient)

The getter to use to access the line gradient class.

[`get LookAround(): typeof LookAround;`](/documentation/MapKitJS/mapkit/LookAround)

The getter to use to access the look around class.

[`get LookAroundPreview(): typeof LookAroundPreview;`](/documentation/MapKitJS/mapkit/LookAroundPreview)

The getter to use to access the look around preview class.

[`get LookAroundScene(): typeof LookAroundScene;`](/documentation/MapKitJS/mapkit/LookAroundScene)

The getter to use to access the look around scene class.

[`get Map(): typeof Map;`](/documentation/MapKitJS/mapkit/Map)

The getter to use to access the map view class.

[`get MapFeatureAnnotation(): typeof MapFeatureAnnotation;`](/documentation/MapKitJS/mapkit/MapFeatureAnnotation)

The getter to use to access the map feature annotation class.

[`get MapFeatureType(): typeof MapFeatureType;`](/documentation/MapKitJS/mapkit/MapFeatureType)

An accessor for the map feature type enumeration.

[`get MapLoadPriority(): typeof MapLoadPriority;`](/documentation/MapKitJS/mapkit/MapLoadPriority)

An accessor for the map load priority enumeration.

[`get MapPoint(): typeof MapPoint;`](/documentation/MapKitJS/mapkit/MapPoint)

The getter to use to access the map point class.

[`get MapRect(): typeof MapRect;`](/documentation/MapKitJS/mapkit/MapRect)

The getter to use to access the map rect class.

[`get MapSize(): typeof MapSize;`](/documentation/MapKitJS/mapkit/MapSize)

The getter to use to access the map size class.

[`get MapType(): typeof MapType;`](/documentation/MapKitJS/mapkit/MapType)

An accessor for the map type enumeration.

[`get MarkerAnnotation(): typeof MarkerAnnotation;`](/documentation/MapKitJS/mapkit/MarkerAnnotation)

The getter to use to access the marker annotation class.

[`get Padding(): typeof Padding;`](/documentation/MapKitJS/mapkit/Padding)

The getter to use to access the padding class.

[`get Place(): typeof Place;`](/documentation/MapKitJS/mapkit/Place)

The getter to use to access the place class.

[`get PlaceAnnotation(): typeof PlaceAnnotation;`](/documentation/MapKitJS/mapkit/PlaceAnnotation)

The getter to use to access the place annotation class.

[`get PlaceDetail(): typeof PlaceDetail;`](/documentation/MapKitJS/mapkit/PlaceDetail)

The getter to use to access the place detail class.

[`get PlaceLookup(): typeof PlaceLookup;`](/documentation/MapKitJS/mapkit/PlaceLookup)

The getter to use to access the place lookup class.

[`get PlaceSelectionAccessory(): typeof PlaceSelectionAccessory;`](/documentation/MapKitJS/mapkit/PlaceSelectionAccessory)

The getter to use to access the place selection accessory class.

[`get PointOfInterestCategory(): typeof PointOfInterestCategory;`](/documentation/MapKitJS/mapkit/PointOfInterestCategory)

An accessor for the point-of-interest category enumeration.

[`get PointOfInterestFilter(): typeof PointOfInterestFilter;`](/documentation/MapKitJS/mapkit/PointOfInterestFilter)

The getter to use to access the point-of-interest filter class.

[`get PointsOfInterestSearch(): typeof PointsOfInterestSearch;`](/documentation/MapKitJS/mapkit/PointsOfInterestSearch)

The getter to use to access the points of interest search class.

[`get PolygonOverlay(): typeof PolygonOverlay;`](/documentation/MapKitJS/mapkit/PolygonOverlay)

The getter to use to access the polygon overlay class.

[`get PolylineOverlay(): typeof PolylineOverlay;`](/documentation/MapKitJS/mapkit/PolylineOverlay)

The getter to use to access the polyline overlay class.

[`get RegionPriority(): typeof RegionPriority;`](/documentation/MapKitJS/mapkit/RegionPriority)

An accessor for the region priority enumeration.

[`get Search(): typeof Search;`](/documentation/MapKitJS/mapkit/Search)

The getter to use to access the search class.

[`get SearchAutocompleteResult(): typeof SearchAutocompleteResult;`](/documentation/MapKitJS/mapkit/SearchAutocompleteResult)

The getter to use to access the search autocomplete result class.

[`get Style(): typeof Style;`](/documentation/MapKitJS/mapkit/Style)

The getter to use to access the style class.

[`get TileOverlay(): typeof TileOverlay;`](/documentation/MapKitJS/mapkit/TileOverlay)

The getter to use to access the tile overlay class.

[`get TransportType(): typeof TransportType;`](/documentation/MapKitJS/mapkit/TransportType)

An accessor for the transport type enumeration.

## Relationships

### Inherits From

`EventTarget`

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)