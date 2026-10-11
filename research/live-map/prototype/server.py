#!/usr/bin/env python3
"""Local, standard-library NWS point-evidence prototype; not a production service."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent
POLICY = {
    "id": "local-prototype-proposed-v1",
    "validated_operational_policy": False,
    "observation_max_age_seconds": 1800,
    "forecast_max_issue_age_seconds": 43200,
    "alerts_max_fetch_age_seconds": 120,
    "future_clock_tolerance_seconds": 60,
    "alerts_cache_seconds": 30,
    "note": "Illustrative freshness limits, not validated hazard-response thresholds. A fresh nearby station is not a measurement at the selected roof.",
}


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo else None
    except ValueError:
        return None


def age_state(value, now, maximum, tolerance=60):
    parsed = parse_time(value)
    if parsed is None:
        return {"age_seconds": None, "freshness": "unknown_timestamp"}
    age = (now - parsed).total_seconds()
    return {"age_seconds": round(age, 1), "freshness": "future_timestamp" if age < -tolerance else "stale" if age > maximum else "fresh"}


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def coordinates(latitude, longitude):
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise ValueError("Latitude and longitude must be finite decimal numbers.")
    try:
        lat, lon = float(latitude), float(longitude)
    except (ValueError, TypeError):
        raise ValueError("Latitude and longitude must be finite decimal numbers.") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Latitude must be in [-90,90] and longitude in [-180,180].")
    return {"latitude_deg": lat, "longitude_deg": lon, "crs": "EPSG:4326"}


def distance_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a["latitude_deg"], a["longitude_deg"], b["latitude_deg"], b["longitude_deg"]])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def geometry_point(geometry):
    try:
        if geometry.get("type") != "Point":
            return None
        lon, lat = geometry["coordinates"][:2]
        return coordinates(lat, lon)
    except (AttributeError, KeyError, ValueError, TypeError):
        return None


def mapping(value):
    return value if isinstance(value, dict) else {}


def point_key(point):
    # Stable at full Python float precision; never rounded to a weather grid.
    return f'{point["latitude_deg"]:.17g},{point["longitude_deg"]:.17g}'


def approved_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "api.weather.gov" or parts.port not in (None, 443) or parts.username or parts.password or parts.fragment:
        raise ValueError("Upstream URL is outside the approved NWS HTTPS host.")
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        approved_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def network_json(url, timeout):
    approved_url(url)
    request = Request(url, headers={"User-Agent": "RoofingApp-local-research-prototype/0.1", "Accept": "application/geo+json"})
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        content = response.read(5_000_001)
        if len(content) > 5_000_000:
            raise ValueError("NWS response exceeds the prototype size limit.")
    def invalid_number(_):
        raise ValueError("Non-finite JSON number in source response.")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            invalid_number(value)
        return number
    data = json.loads(content, parse_constant=invalid_number, parse_float=finite_float)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object from NWS.")
    return data


class SourceClient:
    def __init__(self, adapter=network_json, clock=None, timeout=8):
        self.adapter = adapter
        self.clock = clock or (lambda: datetime.now(UTC))
        self.timeout = timeout
        self.cache = {}
        self.lock = threading.Lock()
        self.url_locks = {}

    def get(self, url, ttl):
        approved_url(url)
        with self.lock:
            lock = self.url_locks.setdefault(url, threading.Lock())
        with lock:
            now = self.clock()
            with self.lock:
                cached = self.cache.get(url)
            # A transient metadata/forecast failure must not block retry for a full day.
            effective_ttl = min(ttl, 30) if cached and cached[1]["status"] != "available" else ttl
            if cached and (now - cached[0]).total_seconds() < effective_ttl:
                return {**cached[1], "cache_hit": True}
            try:
                body = self.adapter(url, self.timeout)
                if not isinstance(body, dict):
                    raise ValueError("Expected a source JSON object.")
                result = {"status": "available", "source_url": url, "fetched_at": iso(self.clock()), "data": body, "cache_hit": False}
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
                code = error.code if isinstance(error, HTTPError) else None
                result = {"status": "unavailable", "source_url": url, "fetched_at": iso(self.clock()), "error": f"NWS HTTP {code}" if code else type(error).__name__, "cache_hit": False}
                # Preserve previously fetched evidence, but never present failure as a fresh fetch.
                if cached and cached[1].get("data"):
                    result.update(data=cached[1]["data"], fetched_at=cached[1]["fetched_at"], last_success_at=cached[1]["fetched_at"], last_attempt_at=iso(self.clock()), retained_previous=True)
            with self.lock:
                self.cache[url] = (now, result)
            return result


class Archive:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "point-snapshots.sqlite3"
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, point_key TEXT NOT NULL, generated_at TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS point_time ON snapshots(point_key, generated_at)")

    def save(self, response):
        identifier = str(uuid.uuid4())
        response["snapshot_id"] = identifier
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("INSERT INTO snapshots VALUES (?,?,?,?)", (identifier, point_key(response["selected_point"]), response["generated_at"], json.dumps(response, allow_nan=False)))
        return identifier

    def history(self, point, limit=20):
        with sqlite3.connect(self.path, timeout=5) as connection:
            start = connection.execute("SELECT MIN(generated_at) FROM snapshots").fetchone()[0]
            point_start = connection.execute("SELECT MIN(generated_at) FROM snapshots WHERE point_key=?", (point_key(point),)).fetchone()[0]
            rows = connection.execute("SELECT payload FROM snapshots WHERE point_key=? ORDER BY generated_at DESC LIMIT ?", (point_key(point), max(1, min(100, limit)))).fetchall()
        return {"selected_point": point, "mode": "local_query_archive", "status": "available" if rows else "no_local_history", "archive_start": start, "point_archive_start": point_start, "snapshots": [json.loads(row[0]) for row in rows], "limitation": "Only responses previously requested from this local prototype are stored. No earlier weather archive, continuous monitoring, or retrospective weather reconstruction is provided. Stored freshness describes the original query time."}


class WeatherService:
    def __init__(self, client=None, archive=None, policy=None):
        self.client = client or SourceClient()
        self.archive = archive
        self.policy = dict(POLICY)
        if policy:
            self.policy.update(policy)
        self.last_result = None
        self.lock = threading.Lock()

    def freshness(self, value, maximum):
        return age_state(value, self.client.clock(), maximum, self.policy["future_clock_tolerance_seconds"])

    def alerts(self, point):
        url = "https://api.weather.gov/alerts/active?" + urlencode({"point": f'{point["latitude_deg"]},{point["longitude_deg"]}'})
        result = self.client.get(url, max(30, self.policy["alerts_cache_seconds"]))
        raw = result.get("data", {})
        valid_collection = isinstance(raw.get("features"), list)
        output = {key: value for key, value in result.items() if key != "data"}
        if result["status"] == "available" and not valid_collection:
            output.update(status="unavailable", error="NWS alert collection is malformed")
        output.update(selected_point=point, features=raw.get("features", []) if valid_collection else [], **self.freshness(result.get("fetched_at"), self.policy["alerts_max_fetch_age_seconds"]))
        rejected = [item for item in output["features"] if not isinstance(item, dict) or not isinstance(item.get("properties"), dict)]
        if rejected:
            output["features"] = [item for item in output["features"] if isinstance(item, dict) and isinstance(item.get("properties"), dict)]
            output.update(status="unavailable", rejected_features=rejected, error="Malformed alert records returned; current alert status is incomplete")
        output["matching_method"] = "Official NWS /alerts/active?point query; includes provider polygon/county/zone applicability. No local polygon filtering."
        output["status_meaning"] = "An empty successful response means no active alerts returned by NWS for this point at fetch time; it does not mean no weather hazards. A failed request has unknown current alert status."
        output["freshness_policy_id"] = self.policy["id"]
        output["last_verified_fetch_age_seconds"] = output["age_seconds"]
        return output

    def observations(self, station_result, point):
        if station_result["status"] != "available":
            return {"status": "unavailable", "stations": [], "error": station_result.get("error", "Station listing unavailable")}
        candidates = []
        features = station_result["data"].get("features", [])
        if not isinstance(features, list):
            return {"status": "unavailable", "stations": [], "error": "Malformed station collection"}
        for feature in features:
            if not isinstance(feature, dict):
                continue
            props = mapping(feature.get("properties"))
            station_point = geometry_point(feature.get("geometry"))
            url = props.get("@id") or feature.get("id")
            if station_point and isinstance(url, str):
                try:
                    approved_url(url)
                except ValueError:
                    continue
                candidates.append((distance_km(point, station_point), station_point, props, url))
        candidates.sort(key=lambda item: item[0])
        chosen = candidates[:3]
        with ThreadPoolExecutor(max_workers=3) as pool:
            observations = list(pool.map(lambda item: self.client.get(item[3].rstrip("/") + "/observations/latest", 120), chosen))
        records = []
        field_names = ("temperature", "dewpoint", "relativeHumidity", "windDirection", "windSpeed", "windGust", "barometricPressure", "seaLevelPressure", "visibility", "precipitationLastHour", "precipitationLast3Hours", "precipitationLast6Hours", "windChill", "heatIndex")
        for candidate, result in zip(chosen, observations):
            distance, station_point, station_props, _ = candidate
            props = mapping(result.get("data", {}).get("properties"))
            source_point = geometry_point(result.get("data", {}).get("geometry")) or station_point
            fields = {}
            for name in field_names:
                value = mapping(props.get(name))
                number = value.get("value")
                # MADIS/NWS X is an explicitly rejected datum. Other native flags
                # are preserved without pretending this service runs station QC.
                rejected = value.get("qualityControl") == "X"
                fields[name] = {"value": number if finite_number(number) and not rejected else None, "unit": value.get("unitCode"), "quality_control": value.get("qualityControl"), "quality_status": "source_rejected" if rejected else "not_independently_verified", "value_status": "unusable" if rejected else "available" if finite_number(number) else "missing"}
                if rejected:
                    fields[name]["raw_source_value"] = number if finite_number(number) else None
            record = {key: value for key, value in result.items() if key != "data"}
            record.update(station_id=station_props.get("stationIdentifier"), name=station_props.get("name"), location=source_point, distance_km=round(distance_km(point, source_point), 3), evidence_kind="nearby_station_observation", observed_at=props.get("timestamp"), text_description=props.get("textDescription"), elevation=props.get("elevation"), fields=fields, **self.freshness(props.get("timestamp"), self.policy["observation_max_age_seconds"]))
            if not props or not any(field["value_status"] == "available" for field in fields.values()):
                record["status"] = "unavailable"
                record.setdefault("error", "No usable numeric station observations returned")
            records.append(record)
        available = sum(record["status"] == "available" for record in records)
        return {"status": "available" if records and available == len(records) else "partial" if available else "unavailable", "stations": records, "selection_policy": "Up to three geographically nearest stations in the NWS returned station list; not a validated representativeness or hazard-coverage ranking.", "quality_policy": "Native NWS quality_control flags are retained. No additional station QC or roof-height correction is applied.", "freshness_policy_id": self.policy["id"]}

    def point_evidence(self, point):
        # NWS points accepts coordinates to four decimals. Preserve and disclose adapter quantization.
        submitted = coordinates(round(point["latitude_deg"], 4), round(point["longitude_deg"], 4))
        point_url = f'https://api.weather.gov/points/{submitted["latitude_deg"]:.4f},{submitted["longitude_deg"]:.4f}'
        metadata = self.client.get(point_url, 86400)
        base = {"submitted_point": submitted, "quantization_distance_m": round(distance_km(point, submitted) * 1000, 3), "source_url": point_url}
        if metadata["status"] != "available":
            return {**base, "timezone": None, "current": {"status": "unavailable", "stations": [], "error": "Point metadata unavailable"}, "forecast": {"status": "unavailable", "periods": [], "error": metadata.get("error")}}
        props = mapping(metadata["data"].get("properties"))
        base.update(timezone=props.get("timeZone"), relative_location=props.get("relativeLocation"), grid={"office": props.get("gridId"), "x": props.get("gridX"), "y": props.get("gridY")})

        def optional_source(key, ttl):
            url = props.get(key)
            if not isinstance(url, str):
                return {"status": "unavailable", "error": f"NWS point metadata has no {key} link"}
            try:
                return self.client.get(url, ttl)
            except ValueError:
                return {"status": "unavailable", "error": "NWS metadata link failed host validation"}

        with ThreadPoolExecutor(max_workers=2) as pool:
            forecast_future = pool.submit(optional_source, "forecastHourly", 300)
            station_future = pool.submit(optional_source, "observationStations", 86400)
            forecast_result, station_result = forecast_future.result(), station_future.result()
        forecast_props = mapping(forecast_result.get("data", {}).get("properties"))
        forecast = {key: value for key, value in forecast_result.items() if key != "data"}
        issued = forecast_props.get("generatedAt")
        updated = forecast_props.get("updateTime")
        freshness_time = updated or issued
        forecast.update(evidence_kind="grid_forecast", issued_at=issued, updated_at=updated, freshness_time_basis="updateTime" if updated else "generatedAt", valid_times=forecast_props.get("validTimes"), periods=forecast_props.get("periods", []), grid={**base["grid"], "geometry": forecast_result.get("data", {}).get("geometry")}, elevation=forecast_props.get("elevation"), **self.freshness(freshness_time, self.policy["forecast_max_issue_age_seconds"]))
        if not isinstance(forecast["periods"], list) or not forecast["periods"]:
            forecast.update(status="unavailable", periods=[], error=forecast.get("error", "No hourly forecast periods returned"))
        timestamp_issues = []
        for label, value in (("generatedAt", issued), ("updateTime", updated)):
            state = self.freshness(value, self.policy["forecast_max_issue_age_seconds"])
            if state["freshness"] in ("future_timestamp", "unknown_timestamp"):
                timestamp_issues.append({"field": label, "issue": state["freshness"]})
            if state["freshness"] == "future_timestamp":
                forecast["freshness"] = "future_timestamp"
        forecast["timestamp_issues"] = timestamp_issues
        rejected_periods, valid_periods = [], []
        for period in forecast["periods"]:
            item = mapping(period)
            start, end = parse_time(item.get("startTime")), parse_time(item.get("endTime"))
            if start is None or end is None or start >= end:
                rejected_periods.append(period)
            else:
                valid_periods.append(period)
        forecast.update(periods=valid_periods, rejected_periods=rejected_periods)
        if rejected_periods:
            forecast["status"] = "partial" if valid_periods and forecast["status"] == "available" else "unavailable"
            forecast["error"] = "Forecast source contains invalid or reversed period timestamps; original rejected records retained separately"
        now = self.client.clock()
        forecast["has_current_or_future_periods"] = any(parse_time(period["endTime"]) > now for period in valid_periods)
        if valid_periods and not forecast["has_current_or_future_periods"]:
            forecast["freshness"] = "expired_validity"
        forecast["freshness_policy_id"] = self.policy["id"]
        forecast["precipitation_probability_definition"] = "NWS probability of measurable precipitation (at least 0.01 inch liquid equivalent) for the source forecast interval; not percent of time raining or a hail probability."
        base.update(current=self.observations(station_result, point), forecast=forecast)
        return base

    def point(self, point):
        with ThreadPoolExecutor(max_workers=2) as pool:
            alerts_future = pool.submit(self.alerts, point)
            weather_future = pool.submit(self.point_evidence, point)
            weather, alerts = weather_future.result(), alerts_future.result()
        statuses = [weather["current"]["status"], weather["forecast"]["status"], alerts["status"]]
        response = {"schema_version": "0.1.0", "selected_point": point, "generated_at": iso(self.client.clock()), **weather, "alerts": alerts, "status": "available" if all(status == "available" for status in statuses) else "unavailable" if all(status == "unavailable" for status in statuses) else "partial", "freshness_policy": self.policy, "archive_status": "disabled", "snapshot_id": None, "limitations": ["The selected pin is precise; station observations and grid forecasts do not measure exact weather at that roof.", "No live radar, hail-size estimate, lightning detections, roof-level winds, or parcel-level weather accuracy claim is supplied by this prototype.", "Hourly forecast periods are preserved; no interpolation into invented minute-by-minute forecasts.", "Freshness is shown separately from successful retrieval. Policy limits are illustrative and require operational validation."]}
        if self.archive:
            try:
                response["archive_status"] = "saved"
                self.archive.save(response)
            except (OSError, sqlite3.Error, ValueError):
                response.update(archive_status="failed", snapshot_id=None)
        with self.lock:
            self.last_result = {"generated_at": response["generated_at"], "status": response["status"], "selected_point": point, "source_times": {"alerts_fetched_at": alerts.get("fetched_at"), "forecast_updated_at": weather["forecast"].get("updated_at"), "observations": [{"station_id": record["station_id"], "observed_at": record["observed_at"]} for record in weather["current"].get("stations", [])]}}
        return response

    def health(self):
        with self.lock:
            latest = self.last_result
        ages = None
        if latest:
            source_times = latest["source_times"]
            ages = {"alerts": self.freshness(source_times["alerts_fetched_at"], self.policy["alerts_max_fetch_age_seconds"]), "forecast": self.freshness(source_times["forecast_updated_at"], self.policy["forecast_max_issue_age_seconds"]), "stations": [{"station_id": item["station_id"], **self.freshness(item["observed_at"], self.policy["observation_max_age_seconds"])} for item in source_times["observations"]]}
        return {"service": "running", "mode": "local_research_prototype", "production_ready": False, "generated_at": iso(self.client.clock()), "sources_configured": ["NWS public API"], "commercial_plugins_configured": False, "archive_enabled": bool(self.archive), "freshness_policy": self.policy, "last_point_query": latest, "last_point_source_ages": ages, "monitoring": "On-demand queries only; no unattended background collection."}


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Do not persist requested property coordinates or future credentials in access logs.
            return

        def send_json(self, payload, status=200):
            data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                parsed = urlsplit(self.path)
                if parsed.path == "/api/health":
                    return self.send_json(service.health())
                if parsed.path in ("/api/point", "/api/alerts", "/api/history"):
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if len(query.get("lat", [])) != 1 or len(query.get("lon", [])) != 1:
                        raise ValueError("Supply exactly one lat and lon parameter.")
                    point = coordinates(query["lat"][0], query["lon"][0])
                    if parsed.path == "/api/point":
                        return self.send_json(service.point(point))
                    if parsed.path == "/api/alerts":
                        return self.send_json(service.alerts(point))
                    if not service.archive:
                        return self.send_json({"status": "archive_disabled", "selected_point": point, "snapshots": []})
                    return self.send_json(service.archive.history(point))
                files = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
                for filename, content_type in {"leaflet.js": "text/javascript", "leaflet.css": "text/css", "topojson-client.min.js": "text/javascript", "states-10m.json": "application/json", "leaflet-LICENSE": "text/plain", "topojson-LICENSE": "text/plain", "us-atlas-LICENSE": "text/plain", "us-atlas-README.md": "text/plain"}.items():
                    files["/vendor/" + filename] = ("vendor/" + filename, content_type)
                if parsed.path not in files:
                    return self.send_json({"error": "Not found"}, 404)
                filename, content_type = files[parsed.path]
                path = (ROOT / filename).resolve()
                if not path.is_relative_to(ROOT) or not path.is_file():
                    return self.send_json({"error": "Frontend file not present yet"}, 404)
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
            except ValueError as error:
                self.send_json({"error": str(error)}, 400)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send_json({"error": "Local service failure; source status is unknown."}, 500)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--archive-dir", default=str(ROOT / ".local" / "state"))
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument("--observation-max-age-seconds", type=int, default=POLICY["observation_max_age_seconds"])
    parser.add_argument("--forecast-max-issue-age-seconds", type=int, default=POLICY["forecast_max_issue_age_seconds"])
    args = parser.parse_args()
    if not 0 < args.timeout <= 30:
        parser.error("--timeout must be positive and at most 30 seconds")
    if min(args.observation_max_age_seconds, args.forecast_max_issue_age_seconds) <= 0:
        parser.error("Freshness limits must be positive; these remain proposed demonstration policies")
    service = WeatherService(SourceClient(timeout=args.timeout), Archive(args.archive_dir), {"observation_max_age_seconds": args.observation_max_age_seconds, "forecast_max_issue_age_seconds": args.forecast_max_issue_age_seconds})
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print(f"Local research prototype listening on http://{args.host}:{args.port}; no authentication or production hardening.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
