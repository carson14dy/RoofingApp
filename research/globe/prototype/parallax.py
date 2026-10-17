#!/usr/bin/env python3
"""Cloud-top parallax for geostationary imagery over Montana (research only).

Question: how far does a cloud top at height h appear from the ground point
directly beneath it, when the imager geolocates the pixel on the surface
(height 0), as imagery pipelines do without a cloud-top-height correction?

Model (WGS84 ellipsoid, closed-form ray/ellipsoid intersection, no network)
  S   satellite, over the equator at longitude L, geocentric radius a + H.
  P   cloud top = geodetic (lat, lon, h).
  Q   apparent position = first point where the ray S -> P meets the
      ellipsoid at height 0. Surface geolocation places the cloud top at Q.
  G   true ground point = geodetic (lat, lon, 0), directly beneath P.
  Displacement = Q - G, resolved on the local east and north axes at G
      (up = geodetic normal at G): north_km, east_km, total_km = hypot.
      Positive north is poleward. Displacement points away from the satellite:
      north-west of Montana for GOES-East, north-east for GOES-West.
  VZA view zenith angle at G: angle between the geodetic normal at G and G->S.
  Pixel  one 2 km ABI pixel is a 56 microradian square in the satellite's
      fixed-grid angles (x = atan(E/K), y = atan(N/K), K = nadir direction).
      Its four corners are intersected with the ellipsoid. The long and short
      axes are the singular values of the pixel's ground side vectors (km),
      and the area is the corner polygon's area, both in the east/north plane
      at G. Stretch = value / nadir value.

Constants and sources
  a = 6378.137 km        WGS84 semi-major axis. NIMA TR8350.2 (WGS 84), 6378137 m.
  1/f = 298.257223563    WGS84 inverse flattening. Same source. (GRS 80 gives
                         298.257222101; the change is far below 1 mm in position.)
  H = 35786.023 km       Geostationary height above the equator, from the ABI
                         perspective_point_height attribute (35786023 m) as
                         documented in the GOES-R Series Product Definition and
                         Users' Guide. Satellite radius a + H = 42164.160 km.
                         W2 to confirm the attribute value from a live file.
  2 km ABI sampling      56 microradians (GOES-R PUG, 2 km bands), so
                         56e-6 rad x 35786 km = 2.00 km at nadir. W2 to confirm
                         from the x/y scale_factor in a live file.
  Task constants         H = 35786 km and R = 6371 km. R = 6371 km is the IUGG
                         mean radius (6371.0088 km), not the WGS84 equatorial
                         radius. Used only by --model sphere, as a sensitivity
                         check. 35786 + 6371 = 42157 km, which is 7 km short of
                         the geostationary radius, so sphere mode is not a
                         second answer.
  GOES-East -75.2 deg    Nominal operational longitudes ASSUMED here.
  GOES-West -137.0 deg   To be confirmed from the live file attributes by W2.
                         (goes-aws.json already quotes a GOES-19 subpoint of
                         -75.2 deg and a GOES-18 origin of -137.0 deg from file
                         attributes; that is cross-reference, not confirmation here.)

Usage (from research/globe/prototype, no network needed)
  python3 parallax.py                 table of displacements and geometry
  python3 parallax.py --selftest      built-in checks; exit 1 on failure
  python3 parallax.py --emit-json F   the same numbers as JSON
  python3 parallax.py --model sphere  task constants on a sphere, for comparison
"""

from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np

WGS84_A_KM = 6378.137
WGS84_INV_F = 298.257223563
GEO_HEIGHT_KM = 35786.023
SPHERE_R_KM = 6371.0
SPHERE_HEIGHT_KM = 35786.0
ABI_2KM_IFOV_RAD = 56e-6

GOES_EAST_LON = -75.2   # ASSUMED nominal; W2 to confirm from file attributes
GOES_WEST_LON = -137.0  # ASSUMED nominal; W2 to confirm from file attributes
SATELLITES = {"GOES-East": GOES_EAST_LON, "GOES-West": GOES_WEST_LON}

# name: (lat, lon), as given in the research brief
SITES = {
    "Missoula": (46.872, -113.994),
    "Billings": (45.7833, -108.5007),
    "Glasgow": (48.19, -106.63),
    "Miles City": (46.4, -105.8),
}
HEIGHTS_KM = (2.0, 5.0, 8.0, 12.0, 15.0)


def _params(model: str):
    """Return (a, b, e^2, satellite geocentric radius) in km."""
    if model == "wgs84":
        a, f, h_geo = WGS84_A_KM, 1.0 / WGS84_INV_F, GEO_HEIGHT_KM
    elif model == "sphere":
        a, f, h_geo = SPHERE_R_KM, 0.0, SPHERE_HEIGHT_KM
    else:
        raise ValueError(f"unknown model: {model!r}")
    return a, a * (1.0 - f), f * (2.0 - f), a + h_geo


def satellite_ecef(sat_lon: float, model: str = "wgs84") -> np.ndarray:
    _, _, _, r_sat = _params(model)
    lon = math.radians(sat_lon)
    return np.array([r_sat * math.cos(lon), r_sat * math.sin(lon), 0.0])


def geodetic_to_ecef(lat: float, lon: float, h: float = 0.0, model: str = "wgs84") -> np.ndarray:
    a, _, e2, _ = _params(model)
    phi, lam = math.radians(lat), math.radians(lon)
    sp, cp = math.sin(phi), math.cos(phi)
    n = a / math.sqrt(1.0 - e2 * sp * sp)
    return np.array([
        (n + h) * cp * math.cos(lam),
        (n + h) * cp * math.sin(lam),
        (n * (1.0 - e2) + h) * sp,
    ])


def ecef_to_geodetic(p, model: str = "wgs84"):
    """Return (lat_deg, lon_deg, height_km). Fixed-point iteration, converges in a few steps."""
    a, _, e2, _ = _params(model)
    x, y, z = (float(v) for v in p)
    rho = math.hypot(x, y)
    lon = math.atan2(y, x)
    phi = math.atan2(z, rho * (1.0 - e2))
    h = 0.0
    for _ in range(50):
        sp = math.sin(phi)
        n = a / math.sqrt(1.0 - e2 * sp * sp)
        h = rho / math.cos(phi) - n
        nxt = math.atan2(z, rho * (1.0 - e2 * n / (n + h)))
        done = abs(nxt - phi) < 1e-15
        phi = nxt
        if done:
            break
    return math.degrees(phi), math.degrees(lon), h


def _first_surface_hit(origin: np.ndarray, direction: np.ndarray, model: str = "wgs84") -> np.ndarray:
    """First point of the ray origin + t*direction (t > 0) on the ellipsoid, from outside."""
    a, b, _, _ = _params(model)
    s, d = origin, direction
    qa = (d[0] ** 2 + d[1] ** 2) / a ** 2 + d[2] ** 2 / b ** 2
    qb = 2.0 * ((s[0] * d[0] + s[1] * d[1]) / a ** 2 + s[2] * d[2] / b ** 2)
    qc = (s[0] ** 2 + s[1] ** 2) / a ** 2 + s[2] ** 2 / b ** 2 - 1.0
    disc = qb * qb - 4.0 * qa * qc
    if disc < 0.0:
        raise ValueError("ray misses the ellipsoid")
    t = (-qb - math.sqrt(disc)) / (2.0 * qa)  # smaller root = visible (near) side
    if t <= 0.0:
        raise ValueError("ellipsoid lies behind the satellite")
    return s + t * d


def _enu(lat: float, lon: float):
    phi, lam = math.radians(lat), math.radians(lon)
    east = np.array([-math.sin(lam), math.cos(lam), 0.0])
    north = np.array([-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi)])
    up = np.array([math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi)])
    return east, north, up


def displacement(lat: float, lon: float, h_km: float, sat_lon: float, model: str = "wgs84") -> dict:
    """Apparent surface position of a cloud top at (lat, lon, h_km) seen from sat_lon."""
    s = satellite_ecef(sat_lon, model)
    p = geodetic_to_ecef(lat, lon, h_km, model)
    q = _first_surface_hit(s, p - s, model)
    g = geodetic_to_ecef(lat, lon, 0.0, model)
    east, north, _ = _enu(lat, lon)
    v = q - g
    n_km, e_km = float(v @ north), float(v @ east)
    total = math.hypot(n_km, e_km)
    q_lat, q_lon, q_h = ecef_to_geodetic(q, model)
    bearing = math.degrees(math.atan2(e_km, n_km)) % 360.0 if total > 1e-9 else float("nan")
    return {
        "north_km": n_km,
        "east_km": e_km,
        "total_km": total,
        "bearing_deg": bearing,
        "apparent_lat": q_lat,
        "apparent_lon": q_lon,
        "apparent_height_km": q_h,
    }


def view_geometry(lat: float, lon: float, sat_lon: float, model: str = "wgs84") -> dict:
    s = satellite_ecef(sat_lon, model)
    g = geodetic_to_ecef(lat, lon, 0.0, model)
    east, north, up = _enu(lat, lon)
    los = s - g
    rng = float(np.linalg.norm(los))
    u = los / rng
    vza = math.degrees(math.acos(max(-1.0, min(1.0, float(up @ u)))))
    sat_bearing = math.degrees(math.atan2(float(u @ east), float(u @ north))) % 360.0
    return {"vza_deg": vza, "sat_bearing_deg": sat_bearing, "slant_range_km": rng}


def pixel_footprint(lat: float, lon: float, sat_lon: float, model: str = "wgs84",
                    ifov: float = ABI_2KM_IFOV_RAD) -> dict:
    """Ground footprint of one pixel of angular size ifov that views (lat, lon) at h = 0."""
    s = satellite_ecef(sat_lon, model)
    g = geodetic_to_ecef(lat, lon, 0.0, model)
    k = -s / float(np.linalg.norm(s))            # nadir direction, satellite -> Earth
    n_hat = np.array([0.0, 0.0, 1.0])
    e_hat = np.cross(k, n_hat)                  # satellite-local east
    los = (g - s) / float(np.linalg.norm(g - s))
    x0 = math.atan2(float(los @ e_hat), float(los @ k))
    y0 = math.atan2(float(los @ n_hat), float(los @ k))
    half = ifov / 2.0
    corners = []
    for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half)):
        u = math.tan(x0 + dx) * e_hat + math.tan(y0 + dy) * n_hat + k
        corners.append(_first_surface_hit(s, u / float(np.linalg.norm(u)), model))
    east, north, _ = _enu(lat, lon)
    en = np.array([[float((c - g) @ east), float((c - g) @ north)] for c in corners])
    x, y = en[:, 0], en[:, 1]
    area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    # Side vectors averaged over opposite sides. Their singular values are the
    # principal extents of the pixel on the ground: long (along the tilt), short (across).
    ex = ((en[1] - en[0]) + (en[2] - en[3])) / 2.0
    ey = ((en[3] - en[0]) + (en[2] - en[1])) / 2.0
    long_km, short_km = np.linalg.svd(np.column_stack([ex, ey]), compute_uv=False)
    return {"long_axis_km": float(long_km), "short_axis_km": float(short_km), "area_km2": area}


def table(model: str = "wgs84") -> list[dict]:
    rows = []
    for site, (lat, lon) in SITES.items():
        for sat, slon in SATELLITES.items():
            for h in HEIGHTS_KM:
                d = displacement(lat, lon, h, slon, model)
                rows.append({
                    "site": site, "satellite": sat, "h_km": h,
                    "north_km": d["north_km"], "east_km": d["east_km"], "total_km": d["total_km"],
                    "apparent_lat": d["apparent_lat"], "apparent_lon": d["apparent_lon"],
                })
    return rows


def site_summary(model: str = "wgs84") -> list[dict]:
    out = []
    for site, (lat, lon) in SITES.items():
        per = {}
        for sat, slon in SATELLITES.items():
            geo = view_geometry(lat, lon, slon, model)
            nadir = pixel_footprint(0.0, slon, slon, model)
            fp = pixel_footprint(lat, lon, slon, model)
            per[sat] = {
                "vza_deg": geo["vza_deg"],
                "sat_bearing_deg": geo["sat_bearing_deg"],
                "slant_range_km": geo["slant_range_km"],
                "pixel_long_km": fp["long_axis_km"],
                "pixel_short_km": fp["short_axis_km"],
                "pixel_long_stretch": fp["long_axis_km"] / nadir["long_axis_km"],
                "pixel_short_stretch": fp["short_axis_km"] / nadir["short_axis_km"],
                "pixel_area_km2": fp["area_km2"],
                "pixel_area_ratio": fp["area_km2"] / nadir["area_km2"],
                "nadir_pixel_km": nadir["long_axis_km"],
                "sat_lon": slon,
            }
        nearer = min(per, key=lambda s: per[s]["vza_deg"])
        other = next(s for s in per if s != nearer)
        out.append({
            "site": site, "lat": lat, "lon": lon, "satellites": per,
            "nearer_satellite": nearer,
            "vza_margin_deg": abs(per[nearer]["vza_deg"] - per[other]["vza_deg"]),
            # VZA depends only on |lon - sat_lon| at fixed latitude, so the other satellite ties
            # with the nearer one when it sits the same distance on the far side of the site.
            "tie_longitude_for_other": 2.0 * lon - SATELLITES[nearer],
            "tie_satellite": other,
        })
    return out


def sensitivity(model: str = "wgs84") -> dict:
    out = {"satellite_lon_pm_0p5_deg": [], "slope_km_per_km_at_12km": [], "sphere_minus_wgs84_at_12km": []}
    for site, (lat, lon) in SITES.items():
        for sat, slon in SATELLITES.items():
            base = displacement(lat, lon, 12.0, slon, model)["total_km"]
            moved = [displacement(lat, lon, 12.0, slon + dl, model)["total_km"] - base for dl in (-0.5, 0.5)]
            out["satellite_lon_pm_0p5_deg"].append(
                {"site": site, "satellite": sat, "change_km_at_12km_for_minus_0p5": moved[0],
                 "change_km_at_12km_for_plus_0p5": moved[1]})
            slope = (displacement(lat, lon, 13.0, slon, model)["total_km"]
                     - displacement(lat, lon, 11.0, slon, model)["total_km"]) / 2.0
            out["slope_km_per_km_at_12km"].append({"site": site, "satellite": sat, "slope": slope})
            if model == "wgs84":
                sph = displacement(lat, lon, 12.0, slon, "sphere")
                wg = displacement(lat, lon, 12.0, slon, "wgs84")
                out["sphere_minus_wgs84_at_12km"].append({
                    "site": site, "satellite": sat,
                    "total_km_diff": sph["total_km"] - wg["total_km"],
                    "north_km_diff": sph["north_km"] - wg["north_km"],
                    "east_km_diff": sph["east_km"] - wg["east_km"]})
    return out


def _checks(model: str = "wgs84"):
    results = []

    def add(name, ok, detail):
        results.append((name, bool(ok), detail))

    worst = 0.0
    for lon in SATELLITES.values():
        for h in (0.0, 2.0, 5.0, 8.0, 12.0, 15.0):
            d = displacement(0.0, lon, h, lon, model)
            worst = max(worst, abs(d["north_km"]), abs(d["east_km"]))
    add("sub-satellite point gives zero displacement (both satellites, h 0-15 km)",
        worst < 1e-6, f"max offset {worst:.1e} km")

    bad = []
    for sat, lon in SATELLITES.items():
        for site, (lat, slon) in SITES.items():
            tot = [displacement(lat, slon, float(h), lon, model)["total_km"] for h in np.arange(0.0, 15.5, 1.0)]
            if not all(b > a for a, b in zip(tot, tot[1:])):
                bad.append(f"{site}/{sat}")
    add("displacement grows with cloud-top height (0-15 km, 1 km steps, all sites)",
        not bad, "strictly increasing" if not bad else "not monotonic: " + ", ".join(bad))

    bad = []
    for sat, lon in SATELLITES.items():
        for off in (30.0, -30.0):
            tot = [displacement(float(la), lon + off, 10.0, lon, model)["total_km"]
                   for la in np.arange(0.0, 61.0, 5.0)]
            if not all(b > a for a, b in zip(tot, tot[1:])):
                bad.append(f"{sat} offset {off:+.0f} deg")
    add("displacement grows with latitude 0-60 N at fixed 30 deg longitude offset, h = 10 km",
        not bad, "strictly increasing" if not bad else "not monotonic: " + ", ".join(bad))

    lat, lon = 40.0, -95.0
    g = view_geometry(lat, lon, GOES_EAST_LON, model)
    d1 = displacement(lat, lon, 1.0, GOES_EAST_LON, model)["total_km"]
    ratio = d1 / math.tan(math.radians(g["vza_deg"]))
    add("flat-Earth limit: total ~ h*tan(VZA) at h = 1 km, VZA < 60 deg (GOES-East, 40 N 95 W)",
        abs(ratio - 1.0) < 0.03 and g["vza_deg"] < 60.0,
        f"VZA {g['vza_deg']:.2f} deg, total/(h tan VZA) = {ratio:.4f}")

    a, b, _, _ = _params(model)
    s = satellite_ecef(GOES_WEST_LON, model)
    p = geodetic_to_ecef(46.872, -113.994, 15.0, model)
    q = _first_surface_hit(s, p - s, model)
    res = (q[0] ** 2 + q[1] ** 2) / a ** 2 + q[2] ** 2 / b ** 2 - 1.0
    sin_ang = float(np.linalg.norm(np.cross(q - s, p - s))) / (float(np.linalg.norm(q - s)) * float(np.linalg.norm(p - s)))
    add("apparent point lies on the ellipsoid and on the satellite ray (Missoula, 15 km, GOES-West)",
        abs(res) < 1e-9 and sin_ang < 1e-9, f"surface residual {res:.1e}, ray sine {sin_ang:.1e}")

    nadir = pixel_footprint(0.0, GOES_EAST_LON, GOES_EAST_LON, model)
    add("nadir 2 km ABI pixel is 2.00 km across (both axes within 0.5%)",
        abs(nadir["long_axis_km"] - 2.004) < 0.01 and abs(nadir["short_axis_km"] - 2.004) < 0.01,
        f"long {nadir['long_axis_km']:.4f} km, short {nadir['short_axis_km']:.4f} km")

    # Foreshortening: along the tilt the pixel stretches by (R/R0)/cos(VZA), across it by R/R0,
    # with R the slant range to the site and R0 the nadir range. Compare the numerical footprint.
    r0 = _params(model)[3] - _params(model)[0]
    worst_pix = 0.0
    for slon in SATELLITES.values():
        nad = pixel_footprint(0.0, slon, slon, model)
        for lat, lo in SITES.values():
            gv = view_geometry(lat, lo, slon, model)
            fp = pixel_footprint(lat, lo, slon, model)
            ratio = gv["slant_range_km"] / r0
            pred_long = ratio / math.cos(math.radians(gv["vza_deg"]))
            worst_pix = max(worst_pix,
                            abs(fp["long_axis_km"] / nad["long_axis_km"] / pred_long - 1.0),
                            abs(fp["short_axis_km"] / nad["short_axis_km"] / ratio - 1.0))
    add("pixel stretch matches foreshortening: (R/R0)/cos(VZA) along the tilt, R/R0 across it",
        worst_pix < 0.01, f"worst relative difference {worst_pix:.5f}")

    worst_dev = 0.0
    for name, slon in SATELLITES.items():
        for site, (lat, lo) in SITES.items():
            d = displacement(lat, lo, 12.0, slon, model)
            gv = view_geometry(lat, lo, slon, model)
            diff = abs((d["bearing_deg"] - (gv["sat_bearing_deg"] + 180.0) + 180.0) % 360.0 - 180.0)
            worst_dev = max(worst_dev, diff)
    add("displacement points away from the satellite (bearing within 5 deg of satellite bearing + 180)",
        worst_dev < 5.0, f"worst deviation {worst_dev:.2f} deg")

    east_ok = all(displacement(la, lo, 12.0, GOES_EAST_LON, model)["east_km"] < 0.0
                  and displacement(la, lo, 12.0, GOES_WEST_LON, model)["east_km"] > 0.0
                  for la, lo in SITES.values())
    north_ok = all(displacement(la, lo, 8.0, sl, model)["north_km"] > 0.0
                   for la, lo in SITES.values() for sl in SATELLITES.values())
    add("Montana displacement is north (poleward); east-west sign is away from the satellite",
        north_ok and east_ok, f"north>0 {north_ok}, GOES-East shifts west and GOES-West east: {east_ok}")

    return results


def _print_report(model: str) -> None:
    print(f"model {model}; satellites " + ", ".join(f"{n} {v:.1f}" for n, v in SATELLITES.items())
          + " (ASSUMED longitudes, W2 to confirm)")
    print("displacement = apparent surface position minus true ground point; north +, east +; km")
    print(f"{'site':<11}{'satellite':<11}{'h km':>6}{'north':>9}{'east':>9}{'total':>9}   apparent lat, lon")
    for r in table(model):
        print(f"{r['site']:<11}{r['satellite']:<11}{r['h_km']:>6.1f}{r['north_km']:>9.2f}{r['east_km']:>9.2f}"
              f"{r['total_km']:>9.2f}   {r['apparent_lat']:.4f}, {r['apparent_lon']:.4f}")
    print()
    print(f"{'site':<11}{'satellite':<11}{'VZA deg':>9}{'sat bearing':>13}"
          f"{'2 km px long':>14}{'short':>8}{'area km2':>10}{'area x':>8}")
    for row in site_summary(model):
        for sat, d in row["satellites"].items():
            print(f"{row['site']:<11}{sat:<11}{d['vza_deg']:>9.2f}{d['sat_bearing_deg']:>13.1f}"
                  f"{d['pixel_long_km']:>14.2f}{d['pixel_short_km']:>8.2f}{d['pixel_area_km2']:>10.2f}"
                  f"{d['pixel_area_ratio']:>8.2f}")
        print(f"  nearer satellite by VZA: {row['nearer_satellite']} (margin {row['vza_margin_deg']:.2f} deg); "
              f"{row['tie_satellite']} would tie at {row['tie_longitude_for_other']:.2f} deg")


def _emit(path: str, model: str) -> None:
    payload = {
        "model": model,
        "table": table(model),
        "geometry": site_summary(model),
        "sensitivity": sensitivity(model),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cloud-top parallax for GOES imagery over Montana.")
    ap.add_argument("--selftest", action="store_true", help="run built-in checks and exit")
    ap.add_argument("--model", choices=("wgs84", "sphere"), default="wgs84")
    ap.add_argument("--emit-json", metavar="PATH", help="write the numbers as JSON to PATH")
    args = ap.parse_args(argv)

    if args.selftest:
        checks = _checks(args.model)
        for name, ok, detail in checks:
            print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        passed = sum(ok for _, ok, _ in checks)
        print(f"{passed}/{len(checks)} checks passed (model {args.model})")
        return 0 if passed == len(checks) else 1

    if args.emit_json:
        _emit(args.emit_json, args.model)
        print(f"wrote {args.emit_json}")
        return 0

    _print_report(args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
