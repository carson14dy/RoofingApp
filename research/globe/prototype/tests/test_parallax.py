"""Offline unit tests for parallax.py (standard library and numpy only, no network).

Run from research/globe/prototype:
    python -m unittest discover -s tests -v
"""

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import parallax as px  # noqa: E402


class SubSatellitePoint(unittest.TestCase):
    def test_displacement_is_zero_at_sub_satellite_point(self):
        for name, lon in px.SATELLITES.items():
            for h in (0.0, 2.0, 8.0, 15.0):
                with self.subTest(satellite=name, h=h):
                    d = px.displacement(0.0, lon, h, lon)
                    self.assertAlmostEqual(d["north_km"], 0.0, places=9)
                    self.assertAlmostEqual(d["east_km"], 0.0, places=9)
                    self.assertAlmostEqual(d["total_km"], 0.0, places=9)

    def test_displacement_is_zero_at_zero_height_anywhere(self):
        for site, (lat, lon) in px.SITES.items():
            with self.subTest(site=site):
                d = px.displacement(lat, lon, 0.0, px.GOES_EAST_LON)
                self.assertAlmostEqual(d["total_km"], 0.0, places=9)

    def test_nadir_pixel_is_two_kilometres(self):
        fp = px.pixel_footprint(0.0, px.GOES_EAST_LON, px.GOES_EAST_LON)
        self.assertAlmostEqual(fp["long_axis_km"], 2.0, delta=0.02)
        self.assertAlmostEqual(fp["short_axis_km"], 2.0, delta=0.02)


class GrowsWithHeight(unittest.TestCase):
    def test_total_displacement_increases_with_height(self):
        heights = np.arange(0.0, 15.5, 1.0)
        for name, lon in px.SATELLITES.items():
            for site, (lat, site_lon) in px.SITES.items():
                with self.subTest(satellite=name, site=site):
                    tot = [px.displacement(lat, site_lon, float(h), lon)["total_km"] for h in heights]
                    self.assertTrue(all(b > a for a, b in zip(tot, tot[1:])), tot)


class GrowsWithLatitude(unittest.TestCase):
    def test_displacement_grows_with_latitude_at_fixed_longitude_offset(self):
        for name, lon in px.SATELLITES.items():
            for offset in (30.0, -30.0):
                with self.subTest(satellite=name, offset=offset):
                    lats = np.arange(0.0, 61.0, 5.0)
                    tot = [px.displacement(float(la), lon + offset, 10.0, lon)["total_km"] for la in lats]
                    self.assertTrue(all(b > a for a, b in zip(tot, tot[1:])), tot)


class Direction(unittest.TestCase):
    def test_north_component_is_poleward_in_northern_hemisphere(self):
        for name, lon in px.SATELLITES.items():
            for lat in (30.0, 40.0, 46.0, 50.0, 60.0):
                for site_lon in (-120.0, -110.0, -100.0):
                    with self.subTest(satellite=name, lat=lat, lon=site_lon):
                        d = px.displacement(lat, site_lon, 8.0, lon)
                        self.assertGreater(d["north_km"], 0.0)

    def test_montana_east_west_sign_points_away_from_satellite(self):
        for site, (lat, lon) in px.SITES.items():
            with self.subTest(site=site):
                # GOES-East lies east of Montana, so the shift is westward; GOES-West lies west, so eastward.
                self.assertLess(px.displacement(lat, lon, 12.0, px.GOES_EAST_LON)["east_km"], 0.0)
                self.assertGreater(px.displacement(lat, lon, 12.0, px.GOES_WEST_LON)["east_km"], 0.0)

    def test_displacement_bearing_is_away_from_satellite(self):
        for name, lon in px.SATELLITES.items():
            for site, (lat, site_lon) in px.SITES.items():
                with self.subTest(satellite=name, site=site):
                    d = px.displacement(lat, site_lon, 12.0, lon)
                    sat_bearing = px.view_geometry(lat, site_lon, lon)["sat_bearing_deg"]
                    diff = (d["bearing_deg"] - (sat_bearing + 180.0) + 180.0) % 360.0 - 180.0
                    self.assertLess(abs(diff), 5.0)


class Geometry(unittest.TestCase):
    def test_apparent_point_lies_on_ellipsoid_and_on_satellite_ray(self):
        a, b, _, _ = px._params("wgs84")
        s = px.satellite_ecef(px.GOES_WEST_LON)
        p = px.geodetic_to_ecef(46.872, -113.994, 15.0)
        q = px._first_surface_hit(s, p - s)
        residual = (q[0] ** 2 + q[1] ** 2) / a ** 2 + q[2] ** 2 / b ** 2 - 1.0
        sine = np.linalg.norm(np.cross(q - s, p - s)) / (np.linalg.norm(q - s) * np.linalg.norm(p - s))
        self.assertLess(abs(residual), 1e-9)
        self.assertLess(sine, 1e-9)

    def test_flat_earth_limit_for_small_height(self):
        lat, lon = 40.0, -95.0
        g = px.view_geometry(lat, lon, px.GOES_EAST_LON)
        self.assertLess(g["vza_deg"], 60.0)
        total = px.displacement(lat, lon, 1.0, px.GOES_EAST_LON)["total_km"]
        self.assertAlmostEqual(total / math.tan(math.radians(g["vza_deg"])), 1.0, delta=0.03)

    def test_pixel_stretch_matches_foreshortening_formula(self):
        r0 = px._params("wgs84")[3] - px._params("wgs84")[0]
        for slon in px.SATELLITES.values():
            nad = px.pixel_footprint(0.0, slon, slon)
            for lat, lon in px.SITES.values():
                with self.subTest(sat_lon=slon, lat=lat, lon=lon):
                    g = px.view_geometry(lat, lon, slon)
                    fp = px.pixel_footprint(lat, lon, slon)
                    ratio = g["slant_range_km"] / r0
                    self.assertAlmostEqual(fp["long_axis_km"] / nad["long_axis_km"],
                                           ratio / math.cos(math.radians(g["vza_deg"])), delta=0.01 * ratio / math.cos(math.radians(g["vza_deg"])))
                    self.assertAlmostEqual(fp["short_axis_km"] / nad["short_axis_km"], ratio, delta=0.01 * ratio)


class ModelChoice(unittest.TestCase):
    def test_sphere_with_task_constants_is_close_to_wgs84(self):
        for site, (lat, lon) in px.SITES.items():
            for name, slon in px.SATELLITES.items():
                with self.subTest(site=site, satellite=name):
                    wg = px.displacement(lat, lon, 12.0, slon, "wgs84")["total_km"]
                    sp = px.displacement(lat, lon, 12.0, slon, "sphere")["total_km"]
                    self.assertLess(abs(sp - wg), 0.5)


if __name__ == "__main__":
    unittest.main()
