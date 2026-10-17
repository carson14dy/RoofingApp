"""Labelled sample data for building the website without a network (design review and tests).

Every value is invented and shaped like the real NWS/SPC responses, so the same parsers run.
Pages built from it carry a "Sample data" banner on every screen, the map included, and every
sample radar or forecast frame names itself "SAMPLE" in its source line.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from . import sources as src

UTC = timezone.utc

# A gusty day on the Livingston–Big Timber corridor, a cold front on the Hi-Line, quiet elsewhere.
WINDY = {"livingston": 26, "bozeman": 12, "billings": 8, "great-falls": 10}
WET = {"havre": 55, "glasgow": 40, "kalispell": 35}
COLD = {"west-yellowstone": -14, "havre": -8}


def _iso(dt):
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


class SampleFetcher:
    def __init__(self, now: datetime):
        self.now = now.astimezone(UTC)
        self.hour0 = self.now.replace(minute=0, second=0, microsecond=0)

    # -- shapes the build asks for -------------------------------------------------
    def json(self, url, params=None):
        if url.endswith("/alerts/active"):
            if params and "point" in params:
                lat, lon = (float(x) for x in params["point"].split(","))
                return self._alerts(point=(lat, lon)), None
            return self._alerts(), None
        if "/points/" in url:
            lat, lon = (float(x) for x in url.rsplit("/", 1)[1].split(","))
            slug = self._slug(lat, lon)
            base = f"{src.NWS}/gridpoints/SMP/{slug}"
            return {"properties": {"forecast": base + "/forecast", "forecastHourly": base + "/forecast/hourly",
                                   "forecastGridData": base, "observationStations": base + "/stations",
                                   "gridId": "SMP", "gridX": 1, "gridY": 1,
                                   "timeZone": "America/Denver",
                                   "relativeLocation": {"properties": {"city": slug.replace("-", " ").title(),
                                                                       "state": "MT"}}}}, None
        if "/gridpoints/" in url and url.endswith("/stations"):
            return self._stations(url.split("/")[-2]), None
        if "/stations/" in url and url.endswith("/observations/latest"):
            return self._reading(url.split("/")[-3])
        if url.endswith("/forecast/hourly"):
            return self._hourly(url.split("/")[-3]), None
        if url.endswith("/forecast"):
            return self._daily(url.split("/")[-2]), None
        if "/gridpoints/" in url:
            return self._grid(url.split("/")[-1]), None
        return None, "not part of the sample data"

    def text(self, url):
        name = url.rsplit("/", 1)[1]
        day = datetime.strptime(name[:6], "%y%m%d").date()
        if day != src.spc_day_for(self.now) - timedelta(days=1):
            return "Time,Size,Location,County,State,Lat,Lon,Comments\n" if "hail" in name else \
                "Time,Speed,Location,County,State,Lat,Lon,Comments\n", None
        if "hail" in name:
            return ("Time,Size,Location,County,State,Lat,Lon,Comments\n"
                    "2215,100,4 N Glendive,Dawson,MT,47.16,-104.71,SAMPLE REPORT (XXX)\n"
                    "2240,175,2 SE Wibaux,Wibaux,MT,46.96,-104.16,SAMPLE REPORT (XXX)\n"
                    "0105,125,6 W Sidney,Richland,MT,47.72,-104.29,SAMPLE REPORT (XXX)\n"), None
        return ("Time,Speed,Location,County,State,Lat,Lon,Comments\n"
                "2230,UNK,Glendive,Dawson,MT,47.11,-104.71,SAMPLE: TREE BRANCHES DOWN (XXX)\n"
                "2305,61,3 E Terry,Prairie,MT,46.79,-105.25,SAMPLE MEASURED GUST (XXX)\n"), None

    def binary(self, url, headers=None):
        # Sample builds draw their own labelled radar and forecast fields (website/gridded.py,
        # sample=True); a non-sample build that uses this fetcher gets no gridded data at all.
        return None, "not part of the sample data"

    # -- generated content -----------------------------------------------------------
    def _slug(self, lat, lon):
        from .build import TOWNS
        return min(TOWNS, key=lambda t: (t["lat"] - lat) ** 2 + (t["lon"] - lon) ** 2)["slug"]

    def _temp(self, slug, t):
        local_h = (t - timedelta(hours=6)).hour
        return round(48 + COLD.get(slug, 0) + 14 * math.sin((local_h - 9) / 24 * 2 * math.pi))

    def _hourly(self, slug):
        periods = []
        for i in range(48):
            t = self.hour0 + timedelta(hours=i)
            local_h = (t - timedelta(hours=6)).hour
            wind = 6 + WINDY.get(slug, 0) * max(0.0, math.sin((local_h - 6) / 14 * math.pi))
            pop = WET.get(slug, 5) if 11 <= local_h <= 20 else 5
            periods.append({"startTime": _iso(t), "endTime": _iso(t + timedelta(hours=1)),
                            "isDaytime": 6 <= local_h < 19, "temperature": self._temp(slug, t),
                            "temperatureUnit": "F", "windSpeed": f"{round(wind)} mph",
                            "windDirection": "W" if slug in WINDY else "SW",
                            "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": pop},
                            "shortForecast": "Chance Rain Showers" if pop >= 30 else (
                                "Sunny" if 6 <= local_h < 19 else "Clear")})
        return {"properties": {"updateTime": _iso(self.hour0 - timedelta(hours=2)), "periods": periods}}

    # Three invented stations per town (an airport, a hill and a pass), listed farthest first: the
    # parser sorts by distance. West Yellowstone's are across the line in Wyoming, as the real ones
    # are (D25). Lewistown's airport reading is stale, so its card quotes the next station; one of
    # Glasgow's stations has no report; Livingston's hill gust failed quality control.
    STATIONS = ((0.03, -0.02, "airport", 1050), (0.12, 0.10, "hill", 1300), (-0.2, 0.25, "pass", 1650))

    def _stations(self, slug):
        from .build import TOWNS
        i = next(n for n, t in enumerate(TOWNS) if t["slug"] == slug)
        t, state = TOWNS[i], "WY" if slug == "west-yellowstone" else "MT"
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [t["lon"] + dlon, t["lat"] + dlat]},
                  "properties": {"stationIdentifier": f"SMP{i:02d}{k}", "name": f"SAMPLE {t['name']} {kind}",
                                 "elevation": {"unitCode": "wmoUnit:m", "value": elev},
                                 "county": f"{src.NWS}/zones/county/{state}C001"}}
                 for k, (dlat, dlon, kind, elev) in enumerate(self.STATIONS)]
        return {"type": "FeatureCollection", "features": feats[::-1]}

    def _reading(self, sid):
        from .build import TOWNS
        i, k = int(sid[3:5]), int(sid[5])
        slug = TOWNS[i]["slug"]
        if slug == "glasgow" and k == 2:
            return None, "not published (HTTP 404)"
        age = (150 if slug == "lewistown" else 12, 41, 150)[k]
        when = self.now - timedelta(minutes=age)
        temp_f = self._temp(slug, when) - 3 * k
        wind_mph = 6 + 0.8 * WINDY.get(slug, 0) + 2 * k
        gust = {"unitCode": "wmoUnit:km_h-1", "value": None, "qualityControl": "Z"}
        if slug in WINDY and k == 0:
            gust = {"unitCode": "wmoUnit:km_h-1", "value": round((wind_mph + 14) / src.KMH_TO_MPH, 1),
                    "qualityControl": "V"}
        if slug == "livingston" and k == 1:
            gust = {"unitCode": "wmoUnit:km_h-1", "value": 190.0, "qualityControl": "X"}
        return {"properties": {
            "timestamp": _iso(when), "textDescription": "SAMPLE Clear" if k == 0 else "",
            "elevation": {"unitCode": "wmoUnit:m", "value": self.STATIONS[k][3]},
            "temperature": {"unitCode": "wmoUnit:degC", "value": round((temp_f - 32) * 5 / 9, 1),
                            "qualityControl": "C" if k == 2 else "V"},
            "windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": round(wind_mph / src.KMH_TO_MPH, 2),
                          "qualityControl": "S" if k == 1 else "V"},
            "windDirection": {"unitCode": "wmoUnit:degree_(angle)", "value": 260 if slug in WINDY else 200,
                              "qualityControl": "V"},
            "windGust": gust}}, None

    def _grid(self, slug):
        values = []
        for i in range(0, 48, 3):
            t = self.hour0 + timedelta(hours=i)
            local_h = (t - timedelta(hours=6)).hour
            gust_mph = 12 + 1.6 * WINDY.get(slug, 0) * max(0.0, math.sin((local_h - 6) / 14 * math.pi))
            values.append({"validTime": f"{_iso(t)}/PT3H", "value": round(gust_mph / src.KMH_TO_MPH, 1)})
        return {"properties": {"elevation": {"unitCode": "wmoUnit:m", "value": SAMPLE_GROUND_M.get(slug, 1100)},
                               "windGust": {"uom": "wmoUnit:km_h-1", "values": values}}}

    def _daily(self, slug):
        periods, start = [], (self.hour0 - timedelta(hours=self.hour0.hour)) + timedelta(hours=12)
        local_today = (self.hour0 - timedelta(hours=6)).date()
        names = ["Today", "Tonight"] + [f"{(local_today + timedelta(days=k)):%A}{suffix}"
                                        for k in range(1, 7) for suffix in ("", " Night")]
        for i, name in enumerate(names):
            t = start + timedelta(hours=12 * i)
            day = i % 2 == 0
            hi = self._temp(slug, t.replace(hour=21)) - (i // 2)
            pop = WET.get(slug, 10) if i in (0, 4, 5) else 10
            wind = 10 + WINDY.get(slug, 0) if day else 6
            periods.append({"name": name, "startTime": _iso(t), "isDaytime": day,
                            "temperature": hi if day else hi - 22, "temperatureUnit": "F",
                            "windSpeed": f"{wind - 5} to {wind} mph", "windDirection": "W",
                            "probabilityOfPrecipitation": {"value": pop},
                            "shortForecast": "Chance Rain Showers" if pop >= 30 else ("Sunny" if day else "Clear"),
                            "detailedForecast": f"SAMPLE. {'High' if day else 'Low'} near "
                                                f"{hi if day else hi - 22}. Winds {wind - 5} to {wind} mph."})
        return {"properties": {"updateTime": _iso(self.hour0 - timedelta(hours=2)), "periods": periods}}

    def _alerts(self, point=None):
        wind = {"id": "sample-high-wind", "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[-111.1, 45.35], [-109.9, 45.35], [-109.9, 46.0],
                                                                 [-111.1, 46.0], [-111.1, 45.35]]]},
                "properties": {"id": "sample-high-wind", "status": "Actual", "messageType": "Alert",
                               "event": "High Wind Warning", "severity": "Severe",
                               "senderName": "NWS Billings MT (sample)",
                               "headline": "SAMPLE — High Wind Warning issued for the Livingston area",
                               "areaDesc": "Livingston Area; Southern Sweet Grass", "sent": _iso(self.now - timedelta(hours=1)),
                               "effective": _iso(self.now - timedelta(hours=1)), "onset": _iso(self.now),
                               "expires": _iso(self.now + timedelta(hours=10)), "ends": _iso(self.now + timedelta(hours=10)),
                               "description": "SAMPLE TEXT. West winds 30 to 40 mph with gusts up to 70 mph.",
                               "instruction": "SAMPLE TEXT. Secure loose objects. Use extra caution on ladders and roofs."}}
        winter = {"id": "sample-winter", "type": "Feature", "geometry": None,
                  "properties": {"id": "sample-winter", "status": "Actual", "messageType": "Alert",
                                 "event": "Winter Weather Advisory", "severity": "Moderate",
                                 "senderName": "NWS Great Falls MT (sample)",
                                 "headline": "SAMPLE — Winter Weather Advisory for the Hi-Line",
                                 "areaDesc": "Hill; Blaine; Northern Phillips", "sent": _iso(self.now - timedelta(hours=3)),
                                 "effective": _iso(self.now - timedelta(hours=3)),
                                 "onset": _iso(self.now + timedelta(hours=14)),
                                 "expires": _iso(self.now + timedelta(hours=30)), "ends": _iso(self.now + timedelta(hours=30)),
                                 "description": "SAMPLE TEXT. Snow and blowing snow. Total accumulations 2 to 4 inches.",
                                 "instruction": "SAMPLE TEXT. Slow down and use caution while traveling."}}
        feats = [wind, winter]
        if point:
            lat, lon = point
            feats = [f for f, near in ((wind, 45.35 <= lat <= 46.0 and -111.1 <= lon <= -109.9),
                                       (winter, lat > 48.3 and -110.5 < lon < -107.5)) if near]
        return {"type": "FeatureCollection", "features": feats}


# ---------------------------------------------------------------- storm sample (labelled SAMPLE)
# Invented radar values at the 11 MRMS heights for the storm text (website/storm.py): a storm core
# over the south-central towns, no radar value at all in two towns and above 6 km in one, and weak
# echo (12 dBZ) elsewhere. The same summary code reads these as it reads the live files.

STORM_TOPS = {"billings": 8000, "bozeman": 6000, "livingston": 7000, "great-falls": 3000, "lewistown": 4000}
STORM_NO_DATA = ("west-yellowstone", "kalispell")          # no radar value at any height
STORM_NO_DATA_FROM = {"havre": 6000}                         # no radar value at 6 km and above


# Invented ground heights (metres above sea level) for the storm text's below-ground count. They differ by town,
# so the sample exercises the count; the live build uses each town's NWS grid point elevation instead.
SAMPLE_GROUND_M = {"billings": 1100, "bozeman": 1500, "butte": 1700, "glasgow": 700, "glendive": 650,
                   "great-falls": 1000, "havre": 800, "helena": 1300, "kalispell": 900, "lewistown": 1200,
                   "livingston": 1400, "miles-city": 750, "missoula": 1000, "west-yellowstone": 2100}


def storm_levels(now: datetime, towns: list[dict]) -> tuple[datetime, dict[str, list[float]]]:
    """SAMPLE: (valid time, {town slug: dBZ at each of the 11 heights, NaN = no radar value}). The valid
    time is the radar frames' own (gridded.sample_layers: the newest 2-minute step, 4 minutes back)."""
    from . import gridded, storm
    when = gridded.floor_time(now, 2) - timedelta(minutes=4)
    values = {}
    for t in towns:
        slug, row = t["slug"], []
        for h in storm.HEIGHTS_M:
            if slug in STORM_NO_DATA or h >= STORM_NO_DATA_FROM.get(slug, float("inf")):
                row.append(float("nan"))
                continue
            top = STORM_TOPS.get(slug)
            if top is None:
                row.append(12.0)
            else:
                row.append(42.0 if h <= top else (30.0 if h <= top + 2000 else 18.0))
        values[slug] = row
    return when, values
