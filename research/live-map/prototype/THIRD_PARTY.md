# Bundled map dependencies

- Leaflet 1.9.4: `vendor/leaflet.js`, `vendor/leaflet.css`; license in `vendor/leaflet-LICENSE`.
- TopoJSON client 3.1.0: `vendor/topojson-client.min.js`; license in `vendor/topojson-LICENSE`.
- us-atlas 3.0.1: `vendor/states-10m.json`; license and provenance in `vendor/us-atlas-LICENSE` and `vendor/us-atlas-README.md`. These are simplified U.S. Census-derived geographic outlines, not parcel boundaries or a street basemap.

Fixed packages were obtained through the npm registry using normal integrity verification and scripts disabled. The package versions and shipped-file hashes are retained in the handoff manifest.

The optional OpenStreetMap layer requests standard interactive tiles directly from the user's browser and retains visible attribution. It is off by default. Tile service access and current usage-policy review were blocked in this environment; do not promote this to a production tile dependency without reviewing the current policy, usage and hosting requirements.

NWS source data attribution is retained in the UI and JSON. Commercial radar/data rights have not been obtained or inferred from the user's chat plugin access.
