# NWS fixtures

Real responses from `api.weather.gov`, saved byte for byte, for `tests/test_nws_fixtures.py`.
Nothing here is edited. They were captured once; do not refresh them without updating the tests and
the counts below.

## Capture

- **When (UTC):** 2026-10-17. The statewide alert request at 01:26:06; the 30-day history at
  01:28:37 to 01:28:39; the point lookups and point alert checks between 01:27:18 and 01:27:59.
- **How:** each URL was requested once. Nothing was repeated and nothing was retried. All 39
  responses returned HTTP 200.
- **Headers:** the same as `website/sources.py`: `User-Agent: MontanaHailWatch website
  (https://github.com/carson14dy/RoofingApp)` and `Accept: application/geo+json, application/json`.
  The statewide request was sent with curl; the rest with Python requests.
- **Cache-Control:** the alert responses say `max-age=5`, so each one is a snapshot from that minute,
  not a feed, and none was refreshed. The point lookups say `max-age` 50,000 to 86,400 seconds; each
  was fetched once.
- **Size:** 777,155 bytes. The history fit on one page (132 messages, 686 KB), so no page was dropped.

## Requests

| File | URL | Requested (UTC) | HTTP | Bytes | Features | Cache-Control |
|---|---|---|---|---|---|---|
| `alerts-active-mt.json` | `https://api.weather.gov/alerts/active?area=MT` | 01:26:06 | 200 | 12,586 | 3 | public, max-age=5, s-maxage=5 |
| `alerts-history-p1.json` | `https://api.weather.gov/alerts?area=MT&status=actual&start=2026-09-17T01:26:06Z` | 01:28:37 | 200 | 685,676 | 132 | public, max-age=5, s-maxage=5 |
| `alerts-history-p2.json` | the `pagination.next` link from page 1 (`&limit=500&cursor=…`) | 01:28:39 | 200 | 260 | 0 | public, max-age=5, s-maxage=5 |
| `points-<town>.json` (14) | `https://api.weather.gov/points/{lat},{lon}` for each town in `website/towns.json` | 01:27:18 to 01:27:32 | 200 | about 3.9 KB each | | public, max-age 50,858 to 80,400 |
| `points-cross-<town>.json` (4) | `https://api.weather.gov/points/{lat},{lon}` for the four cross-county points | 01:27:34 to 01:27:38 | 200 | about 3.9 KB each | | public, max-age=86400 |
| `alerts-point-<town>.json` (14) | `https://api.weather.gov/alerts/active?point={lat},{lon}` for each town | 01:27:39 to 01:27:54 | 200 | 232 to 3,929 | 0, or 1 for Kalispell | public, max-age=5, s-maxage=5 |
| `alerts-point-cross-<town>.json` (4) | `https://api.weather.gov/alerts/active?point={lat},{lon}` for the four cross-county points | 01:27:56 to 01:27:59 | 200 | 234 each | 0 | public, max-age=5, s-maxage=5 |

The `alerts/active?point=` checks are the ones `website/build.py` makes for each town. They were
captured because they are the website's own answer for a town.

## Counts

- **Statewide, now:** 3 alerts (2 High Wind Warnings, 1 Lake Wind Advisory). All 3 have null geometry.
- **30 days (2026-09-17 to 2026-10-17):** 132 messages: 23 Alert, 86 Update, 23 Cancel. 131 have null
  geometry; 1 has a polygon (a Special Weather Statement for Red Lodge Foothills, sent 2026-10-11
  20:57 MDT). Page 2 was empty, so the pagination ended there.
- **Point answers:** 18 places, 1 with an alert. Kalispell (zone MTZ003) gets the Lake Wind Advisory,
  which has null geometry.

## The four cross-county points

The county lines come from the Census county outlines in `website/static/map/basemap.json`, which are
tagged with the two counties on either side of each line. The four towns nearest a county line were
Helena (2.7 km from the Jefferson / Lewis and Clark line), Butte (6.2 km, Jefferson / Silver Bow),
Havre (13.9 km, Blaine / Hill) and Bozeman (17.1 km, Gallatin / Park). Each cross point sits 1.5 km
past that line, on the far side from its town, rounded to 4 decimals. The `/points` answers then
confirmed the county and forecast zone differ on each pair:

| Town (county, forecast zone) | Cross point (county, forecast zone) |
|---|---|
| Helena (MTC049 Lewis and Clark, MTZ319) | cross-helena (MTC043 Jefferson, MTZ322) |
| Butte (MTC093 Silver Bow, MTZ007) | cross-butte (MTC043 Jefferson, MTZ322) |
| Havre (MTC041 Hill, MTZ305) | cross-havre (MTC005 Blaine, MTZ306) |
| Bozeman (MTC031 Gallatin, MTZ326) | cross-bozeman (MTC067 Park, MTZ067) |

## What is not here

- NWS's answer for a point at a past time (`alerts?point=` with a `start` time) was not captured. The
  30-day history is therefore checked against the NWS fields and the standalone rule, never against a
  town's answer. One test replays a real history alert as Helena's answer, and says so.
- Station, forecast and SPC responses are not used by these tests.
