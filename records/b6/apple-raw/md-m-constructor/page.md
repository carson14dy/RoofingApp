<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/Map/MapConstructor",
  "metadataVersion" : "0.1.0",
  "role" : "Constructor",
  "symbol" : {
    "kind" : "Constructor",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "instctr/mapkit.Map/MapConstructor"
  },
  "title" : "new Map(parent, options)"
}
-->

# new Map(parent, options)

Creates a map you embed on a webpage and initializes it with the constructor options you choose.

```
constructor(
    parent?: string | HTMLElement | null,
    options?: MapConstructorOptions,
);
```

## Parameters

`parent`

A DOM element, or the ID of a DOM element, to use as your map’s container.

`options`

Options that [`MapConstructorOptions`](/documentation/MapKitJS/MapConstructorOptions) defines for initializing the properties of your map.

## Return Value

A [`Map`](/documentation/MapKitJS/Map) instance.

## Discussion

The map’s constructor takes an optional `parent` argument and an optional `options` argument. If you specify the `parent` argument, MapKit JS inserts the map element into the DOM as a descendant of `parent` that it styles to fill the size of its enclosing element. A map defaults to showing the entire world.

The following example demonstrates how to add a map to a `DIV` element using HTML:

```other
<body>
	<div id="mapContainer"></div>
</body>
```

The following example demonstrates how to add a map to a `DIV` element using JavaScript:

```javascript
const map = new mapkit.Map('mapContainer', { center: new mapkit.Coordinate(37.334883, -122.008977) });
```

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)