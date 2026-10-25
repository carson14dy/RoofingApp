<!--
{
  "availability" : [

  ],
  "documentType" : "symbol",
  "framework" : "AppleMapsServerAPI",
  "identifier" : "/documentation/AppleMapsServerAPI/-v1-token",
  "metadataVersion" : "0.1.0",
  "role" : "Web Service Endpoint",
  "symbol" : {
    "kind" : "Web Service Endpoint",
    "modules" : [
      "Apple Maps Server API"
    ],
    "preciseIdentifier" : "rest:maps_web_api:get:v1-token"
  },
  "title" : "Generate a Maps token"
}
-->

# Generate a Maps token

Returns a JWT maps access token that you use to call the service API.

## Discussion

### Example

**Request:**

```
curl -si -H "Authorization: Bearer <maps_auth_token>" "https://maps-api.apple.com/v1/token"
```

**Response:**

```json
{
  "accessToken": "<maps_access_token>",
  "expiresInSeconds": 1800
}
```

---

Copyright &copy; 2026 Apple Inc. All rights reserved. | [Terms of Use](https://www.apple.com/legal/internet-services/terms/site.html) | [Privacy Policy](https://www.apple.com/privacy/privacy-policy)