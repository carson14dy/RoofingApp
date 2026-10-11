"""Behavior checks with fake sources. No meteorological accuracy claims or network use."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import URLError
from urllib.request import urlopen

SPEC = importlib.util.spec_from_file_location("live_point_server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
NOW = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)


class Fixtures:
    def __init__(self):
        self.now = NOW
        self.calls = []
        self.fail = set()
        self.observed_at = "2026-10-11T16:30:00Z"
        self.forecast_issued_at = "2026-10-11T16:40:00Z"
        self.forecast_updated_at = "2026-10-11T15:00:00Z"
        self.alert_features = []
        self.bad_station_qc = False

    def clock(self):
        return self.now

    def fetch(self, url, timeout):
        self.calls.append(url)
        if any(fragment in url for fragment in self.fail):
            raise URLError("fixture source failed")
        if "/alerts/active?" in url:
            return {"features": self.alert_features}
        if "/points/" in url:
            return {"properties": {"timeZone": "America/Chicago", "gridId": "EAX", "gridX": 42, "gridY": 31, "forecastHourly": "https://api.weather.gov/gridpoints/EAX/42,31/forecast/hourly", "observationStations": "https://api.weather.gov/gridpoints/EAX/42,31/stations"}}
        if url.endswith("/forecast/hourly"):
            return {"geometry": {"type": "Polygon", "coordinates": [[[-94.6, 39.0], [-94.5, 39.0], [-94.5, 39.1], [-94.6, 39.0]]]}, "properties": {"generatedAt": self.forecast_issued_at, "updateTime": self.forecast_updated_at, "validTimes": "2026-10-11T17:00:00Z/P1D", "periods": [{"number": 1, "startTime": "2026-10-11T12:00:00-05:00", "endTime": "2026-10-11T13:00:00-05:00", "temperature": 24, "temperatureUnit": "C", "probabilityOfPrecipitation": {"value": 10, "unitCode": "wmoUnit:percent"}, "windSpeed": "10 mph"}]}}
        if url.endswith("/stations"):
            # The intentionally unsorted list makes geographic ordering observable.
            return {"features": [{"id": "https://api.weather.gov/stations/" + name, "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"stationIdentifier": name, "name": name}} for name, lat, lon in [("FAR", 41, -94), ("NEAR", 39.1, -94.578), ("MID", 39.2, -94.6), ("FOURTH", 42, -95)]]}
        if "/observations/latest" in url:
            return {"properties": {"timestamp": self.observed_at, "temperature": {"value": 0, "unitCode": "wmoUnit:degC", "qualityControl": "X" if self.bad_station_qc else "V"}, "windSpeed": {"value": None, "unitCode": "wmoUnit:km_h-1"}, "precipitationLastHour": {"value": 0, "unitCode": "wmoUnit:mm"}, "windGust": {"value": None, "unitCode": "wmoUnit:km_h-1"}}}
        raise AssertionError("Unexpected fixture URL: " + url)

    def service(self, archive=None):
        return server.WeatherService(server.SourceClient(self.fetch, self.clock), archive)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = Fixtures()
        self.service = self.fixtures.service()
        self.point = server.coordinates(39.099712345, -94.578612345)

    def test_reject_invalid_coordinates_and_booleans(self):
        for lat, lon in [("nan", 1), (1, "inf"), (91, 0), (0, -181), (True, 0), (0, False), (None, 3)]:
            with self.subTest(lat=lat, lon=lon), self.assertRaises(ValueError):
                server.coordinates(lat, lon)

    def test_preserve_point_disclose_quantization_and_sort_stations(self):
        result = self.service.point(self.point)
        self.assertEqual(result["selected_point"], self.point)
        self.assertEqual(result["submitted_point"]["latitude_deg"], 39.0997)
        self.assertGreater(result["quantization_distance_m"], 0)
        self.assertEqual([station["station_id"] for station in result["current"]["stations"]], ["NEAR", "MID", "FAR"])
        self.assertEqual(len([url for url in self.fixtures.calls if "observations/latest" in url]), 3)
        self.assertIn("39.099712345", result["alerts"]["source_url"])

    def test_missing_is_distinct_from_zero_and_units_are_native(self):
        fields = self.service.point(self.point)["current"]["stations"][0]["fields"]
        self.assertEqual(fields["temperature"]["value"], 0)
        self.assertEqual(fields["temperature"]["unit"], "wmoUnit:degC")
        self.assertIsNone(fields["windSpeed"]["value"])
        self.assertEqual(fields["windSpeed"]["value_status"], "missing")
        self.assertEqual(fields["precipitationLastHour"]["value"], 0)

    def test_source_rejected_qc_is_retained_but_not_shown_as_usable_number(self):
        self.fixtures.bad_station_qc = True
        field = self.service.point(self.point)["current"]["stations"][0]["fields"]["temperature"]
        self.assertEqual(field["quality_control"], "X")
        self.assertEqual(field["quality_status"], "source_rejected")
        self.assertEqual(field["value_status"], "unusable")
        self.assertIsNone(field["value"])
        self.assertEqual(field["raw_source_value"], 0)

    def test_forecast_valid_periods_issue_and_update_are_preserved(self):
        forecast = self.service.point(self.point)["forecast"]
        self.assertEqual(forecast["updated_at"], self.fixtures.forecast_updated_at)
        self.assertEqual(forecast["issued_at"], self.fixtures.forecast_issued_at)
        self.assertEqual(forecast["age_seconds"], 7200)
        self.assertEqual(forecast["periods"][0]["startTime"], "2026-10-11T12:00:00-05:00")
        self.assertEqual(forecast["periods"][0]["windSpeed"], "10 mph")
        self.assertEqual(forecast["grid"]["geometry"]["type"], "Polygon")

    def test_future_forecast_generation_cannot_hide_behind_old_update(self):
        self.fixtures.forecast_issued_at = "2026-10-11T18:00:00Z"
        forecast = self.service.point(self.point)["forecast"]
        self.assertEqual(forecast["freshness"], "future_timestamp")
        self.assertIn({"field": "generatedAt", "issue": "future_timestamp"}, forecast["timestamp_issues"])

    def test_expired_forecast_periods_remain_evidence_but_are_not_current(self):
        self.fixtures.now += timedelta(days=2)
        forecast = self.service.point(self.point)["forecast"]
        self.assertEqual(len(forecast["periods"]), 1)
        self.assertFalse(forecast["has_current_or_future_periods"])
        self.assertEqual(forecast["freshness"], "expired_validity")

    def test_stale_observation_and_future_timestamp_are_not_fresh(self):
        for timestamp, expected in [("2026-10-10T16:30:00Z", "stale"), ("2026-10-11T18:00:00Z", "future_timestamp"), (None, "unknown_timestamp")]:
            with self.subTest(timestamp=timestamp):
                fixture = Fixtures()
                fixture.observed_at = timestamp
                result = fixture.service().point(self.point)
                self.assertEqual(result["current"]["stations"][0]["freshness"], expected)

    def test_points_failure_does_not_suppress_official_alerts(self):
        self.fixtures.fail.add("/points/")
        self.fixtures.alert_features = [{"id": "warning", "geometry": None, "properties": {"event": "Tornado Warning", "affectedZones": ["https://api.weather.gov/zones/county/MOC095"]}}]
        result = self.service.point(self.point)
        self.assertEqual(result["current"]["status"], "unavailable")
        self.assertEqual(result["alerts"]["status"], "available")
        self.assertIsNone(result["alerts"]["features"][0]["geometry"])
        self.assertEqual(result["status"], "partial")

    def test_empty_alert_success_and_alert_failure_are_distinct(self):
        self.assertEqual(self.service.alerts(self.point)["status"], "available")
        self.fixtures.fail.add("/alerts/")
        self.fixtures.now += timedelta(seconds=31)
        result = self.service.alerts(self.point)
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(result["retained_previous"])
        self.assertEqual(result["fetched_at"], server.iso(NOW))
        self.assertEqual(result["last_attempt_at"], server.iso(self.fixtures.now))

    def test_alert_requests_respect_minimum_cache_and_recompute_age(self):
        self.service.alerts(self.point)
        self.fixtures.now += timedelta(seconds=15)
        again = self.service.alerts(self.point)
        self.assertTrue(again["cache_hit"])
        self.assertEqual(again["age_seconds"], 15)
        self.assertEqual(len(self.fixtures.calls), 1)
        self.fixtures.now += timedelta(seconds=16)
        self.service.alerts(self.point)
        self.assertEqual(len(self.fixtures.calls), 2)

    def test_failed_metadata_can_retry_after_short_backoff(self):
        self.fixtures.fail.add("/points/")
        self.assertEqual(self.service.point(self.point)["forecast"]["status"], "unavailable")
        self.fixtures.fail.clear()
        self.fixtures.now += timedelta(seconds=31)
        self.assertEqual(self.service.point(self.point)["forecast"]["status"], "available")

    def test_malformed_alert_collection_is_unknown_not_all_clear(self):
        self.fixtures.alert_features = None
        result = self.service.alerts(self.point)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["features"], [])

    def test_offhost_and_credentialed_urls_are_rejected(self):
        for url in ["https://evil.test/x", "http://api.weather.gov/x", "https://api.weather.gov.evil.test/x", "https://secret@api.weather.gov/x", "https://api.weather.gov:8000/x", "https://api.weather.gov/x#fragment"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                server.approved_url(url)

    def test_distance_handles_antimeridian_and_distinguishes_degrees(self):
        distance = server.distance_km(server.coordinates(0, 179.9), server.coordinates(0, -179.9))
        self.assertAlmostEqual(distance, 22.239, places=2)
        self.assertEqual(server.distance_km(self.point, self.point), 0)

    def test_history_is_local_exact_point_and_has_no_earlier_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = server.Archive(directory)
            empty = archive.history(self.point)
            self.assertEqual(empty["status"], "no_local_history")
            self.assertIsNone(empty["archive_start"])
            service = self.fixtures.service(archive)
            result = service.point(self.point)
            history = archive.history(self.point)
            self.assertEqual(history["mode"], "local_query_archive")
            self.assertEqual(history["snapshots"][0]["snapshot_id"], result["snapshot_id"])
            self.assertEqual(history["archive_start"], server.iso(NOW))
            nearby = server.coordinates(39.099712346, -94.578612345)
            self.assertEqual(archive.history(nearby)["status"], "no_local_history")

    def test_health_is_not_live_or_accuracy_certificate(self):
        health = self.service.health()
        self.assertFalse(health["production_ready"])
        self.assertFalse(health["freshness_policy"]["validated_operational_policy"])
        self.assertIsNone(health["last_point_query"])
        self.assertFalse(health["commercial_plugins_configured"])

    def test_static_vendor_is_served_and_repository_files_are_not(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.service))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            with urlopen(base + "/vendor/leaflet.js") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("javascript", response.headers["Content-Type"])
            for path in ("/server.py", "/vendor/../server.py", "/vendor/%2e%2e/server.py"):
                with self.subTest(path=path), self.assertRaises(server.HTTPError) as error:
                    urlopen(base + path)
                self.assertEqual(error.exception.code, 404)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
