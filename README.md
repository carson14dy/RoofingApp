# RoofingApp
Roofing Weather and Maps Contact app

## Montana and Kansas City weather pilot

Start with the [live-map pilot](research/live-map/README.md) for setup, the
[Montana implementation and validation](research/live-map/MONTANA.md) for executed checks, and the
[radar-reading skill](skills/roofing-radar-reading/README.md) for research and
evidence rules developed through multiple-agent review.

The map defaults to Montana with 13 town samples and retains Kansas City through
the territory selector. The local prototype displays real NWS observations, forecasts and independent
official alerts for selected coordinates. It records saved query snapshots and
shows source times, station distances, quality flags and missing data.

This is an integration handoff for work with Claude. Commercial weather plugins,
live radar, historical backfill and a production deployment remain unconnected;
no independent meteorological accuracy benchmark has been completed.
