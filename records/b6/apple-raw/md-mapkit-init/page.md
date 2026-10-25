<!--
{
  "availability" : [
    "MapKit JS: 5.0.0 -"
  ],
  "documentType" : "symbol",
  "framework" : "MapKitJS",
  "identifier" : "/documentation/MapKitJS/mapkit/init",
  "metadataVersion" : "0.1.0",
  "role" : "Instance Method",
  "symbol" : {
    "kind" : "Instance Method",
    "modules" : [
      "MapKit JS"
    ],
    "preciseIdentifier" : "instm/mapkit/init"
  },
  "title" : "init(options)"
}
-->

# init(options)

Initializes MapKit JS by providing an authorization callback function and optional language.

```
init(options: MapKitInitializationOptions): void;
```

## Parameters

`options`

MapKit JS initialization options.

## Discussion

Unless you wish to explicitly control initialization timing in JavaScript, use `data-token` instead of this method. See [Loading the latest version of MapKit JS](/documentation/MapKitJS/loading-the-latest-version-of-mapkit-js) for more information.

If you’re using this method, provide the token by setting [`authorizationCallback`](/documentation/MapKitJS/MapKitInitializationOptions/authorizationCallback) on a JavaScript object as a function. The [`authorizationCallback`](/documentation/MapKitJS/MapKitInitializationOptions/authorizationCallback) function calls `done()` to return the token. [Creating a Maps token](/documentation/MapKitJS/creating-a-maps-token) shows how to create Maps tokens.

When you create a server endpoint to deliver new tokens to MapKit JS, make an asynchronous request to this endpoint in your [`authorizationCallback`](/documentation/MapKitJS/MapKitInitializationOptions/authorizationCallback) function and call `done()` with the result. The following example shows creating a callback that requests a token from a server endpoint and sets a preferred language for the map:

```javascript
mapkit.init({
    authorizationCallback: function(done) {
        fetch("/gettoken")
            .then(res => res.text())
            .then(done);
    },
    language: "es"
});
```

If you don’t set up a server endpoint, you can alternatively set [`authorizationCallback`](/documentation/MapKitJS/MapKitInitializationOptions/authorizationCallback) to a function that provides a pregenerated token string.

```javascript
mapkit.init({
    authorizationCallback: function(done) {
        done("your-token-string");
    },
    language: "es"
});
```

An instance of [`mapkit`](/documentation/MapKitJS/mapkit) emits a `configuration-change` event after MapKit JS initializes, and an `error` event when initialization fails. You can learn more about both of these events in [Handling initialization events](/documentation/MapKitJS/handling-initialization-events).

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)