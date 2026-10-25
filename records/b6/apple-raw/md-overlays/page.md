<!--
{
  "documentType" : "article",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/overlays",
  "metadataVersion" : "0.1.0",
  "role" : "collectionGroup",
  "title" : "Overlays"
}
-->

# Overlays

Create overlays to highlight geographic regions or paths.

## Discussion

You can enhance your maps by adding *overlays,* shapes that appear on top of the map. There are three overlay shapes:

- Circle ([`CircleOverlay`](/documentation/MapKitJS/CircleOverlay))
- Polyline ([`PolylineOverlay`](/documentation/MapKitJS/PolylineOverlay))
- Polygon ([`PolygonOverlay`](/documentation/MapKitJS/PolygonOverlay))

These three objects can satisfy a wide variety of purposes, such as outlining routes, highlighting map areas, enabling users to make selections, and more.

To display an overlay, you provide geometry data that determines the overlay’s shape, and a style that determines its visual representation. For example, a circle’s center and radius define its geometry. The coordinates of a polygon’s vertices define its shape. The style specifies how to draw the overlay, including its fill color, outline color, and opacity.

Overlays are dynamic. The system automatically redraws them when their underlying geometry or style data changes. For instance, a circle’s radius can grow, or a polygon’s fill color can update dynamically. This makes overlays a powerful visualization tool. For example, circle overlays can show the spread of an infectious disease over a span of time.

Overlays belong to their own layer that lies above map tiles and below annotations. The order that you add overlays to a map is significant. When multiple overlays overlap, overlays that you add later are higher in the z-order (that is, closer to the foreground).

## Topics

### Overlays

[Adding interactivity to overlays](/documentation/MapKitJS/adding-interactivity-to-overlays)

Configure and respond to overlays to make them interactive.

[`abstract class Overlay extends EventTarget`](/documentation/MapKitJS/Overlay)

An abstract base object that defines the methods and properties for map overlays.

[`class Style`](/documentation/MapKitJS/Style)

A set of observable style properties for overlays, including the color and opacity of strokes and fills, and line styles.

[`class CircleOverlay extends Overlay`](/documentation/MapKitJS/CircleOverlay)

A circular overlay with a configurable radius that centers on a specific geographic coordinate.

[`class PolylineOverlay extends Overlay`](/documentation/MapKitJS/PolylineOverlay)

An overlay of connected line segments that don’t form a closed shape.

[`class PolygonOverlay extends Overlay`](/documentation/MapKitJS/PolygonOverlay)

An overlay consisting of one or more points that forms a closed shape.

[`interface OverlayOptions`](/documentation/MapKitJS/OverlayOptions)

A dictionary of options that determines an overlay’s data, and indicates whether it’s visible, in an enabled state, and in a selected state.

[`class TileOverlay extends EventTarget`](/documentation/MapKitJS/TileOverlay)

An overlay that covers an area of the map with bitmapped tiles.

[`type TileOverlayUrlTemplate =
    | string
    | ((
          x: number,
          y: number,
          z: number,
          scale: number,
          data: any,
      ) => string | null);`](/documentation/MapKitJS/TileOverlayUrlTemplate)

A type that specifies the URL template for a tile overlay.



---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)