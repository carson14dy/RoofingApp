"""Open the built map in a real browser and check that it works (AGENTS.md rule 8).

    python tools/smoke_map.py _site [--shots DIR]

Serves the built site on a local port, opens map.html in Chromium (Playwright) at desktop and phone
sizes, and checks: the page loads without script errors; the map data, basemap and first frame
load (a picture from map/frames/, not the blank placeholder the overlays start with, and no "didn't
load" note); play moves the timeline; the layer menu switches the legend title and the pictures; a
bubble is drawn for every town (basemap names are markers too, so only .town counts); the card
used on the Now page loads. Also: every row of the layer menu can be tapped on a phone held
sideways (nothing paints over it); alerts without an outline are named in the legend with a way to
the List; a picture still loading when the viewer switches to a layer with no pictures never appears
under the new layer's legend; the Now page's caption names the picture the card shows (radar or
model); a portrait phone gets the short two-column legend, which keeps one height through the whole
timeline, and the Precipitation layer rings no town. On a --storm-layers build the Satellite layer is checked
too (check_satellite), including a switch to it made while the timeline plays.

The Imagery base map (D32) is checked too (check_imagery_switch, check_imagery_direct, check_imagery_phone,
check_card_ignores_imagery and check_imagery_refused). On the desktop the Layers menu picks Imagery, and one tile
from basemap.nationalmap.gov must load (HTTP 200, image/jpeg). The vector land, lakes, rivers, roads, county
lines and names are hidden, and the borders stay. The credit row (with its privacy words) and the address
(base=imagery) show, the bubbles and the weather picture stay, and zooming reaches the imagery's maximum.
Switching back restores the white map and its maximum zoom, removes the imagery tile layer and its pictures, and
asks for no more tiles; a second round does the same. A run that gets no answer from that host says "tile did not
load" as a note and still runs every other check. check_imagery_refused refuses every request to that host (no
internet needed): the credit row must then say that imagery didn't load, the base map's shapes and names stay
hidden while the outline, borders, bubbles and weather picture still show, and the row goes back to the credit
once a tile loads (a note when no tile can come). --shots DIR saves the pictures for the record: desktop and
phone, both base maps, at 1280x800 and 390x844.

On a --hail-history build the hail history at a spot is checked too (check_hail; check_no_hail when the flag is off):
?at= and a click open the sheet with the store's own words; the gate cell (797, 1986) shows 2.01 in (51.3 mm) on Jun 15,
2025 and Benchland's own cell 0.72 in (18.5 mm); a point outside Montana gets the outside words and asks for no shard (a
sample build gets its own outside words, with SAMPLE data); a Montana cell with no value gets the no-estimate words after
one shard request; a shard that fails or is missing gets the unavailable words. The joined rows of the sheet (check_joins) must match the module row for row, inside the section each row belongs to
(joined_problems); each of the eleven sections of a sample build carries the sample label (check_sample_labels); a
station file that fails shows its unavailable sentence (check_station_unavailable); and a zone file that fails leaves
the zone's rows and sentence as the module writes them (check_zone_unavailable, D27).
On a --hail-addresses build (run with --addresses) the address dots, the streets and the building outlines (B3, D30)
are checked by check_addresses: at zoom 12 nothing of them is fetched or drawn over Billings; at 13 the arterials and
the count bubbles show and no outline is fetched; at 15 the local streets, one dot per outline and the unmatched
address dots show, with no street names; at 16 the fills and the street names show; a 390 px view at zoom 15 fetches
under 650 KB gzip; each redraw at 15 and 16 takes under 30 ms; a pan across Billings makes fewer than 20 requests.
A tap on an outline's dot opens the sheet with its address line on top (or the no-address sentence), and a tap on an
unmatched dot shows its address line and how it was placed. The attribution lines are on the first screen at 390 px.
The Find an address search is tried with "401 N 27th St Billings", "27th Billings", "Colony Rd Roundup" and "qwzx 99",
and no typed text appears in any request URL. On the --address-text off build (D35) there is no form and no search
file, and no sheet shows address text. --shots saves the pictures at 390x844 and 1280x800 on both base maps. The
hook these checks read is window.hailMapTest (map.js, test only).

Every browser context counts the requests that leave this server, and that count must be zero, except for
the imagery host in the contexts that have switched to Imagery. Exits 1 with the reasons if anything fails.
The five-season summary and the eleven sections on the hail sheet (B5 part B2) are checked too (check_summary). At 390
and 1280 px the sheet is opened on the Billings cell, Benchland's cell 792,1998 and the gate cell 797,1986, once with
?at= and once by a tap, and the table must sit inside the first screen below the address and live lines, with nothing
running sideways. Every cell of the table must read exactly the words that summary.describe_summary gives for that
cell, followed by its coverage line and nothing else (D75); the table's notes, the partial line, the held line, the
five-season sentences, the lead, the radar sentence and the table's heading must be on the sheet. The sections are
read from the page's [data-hail='sections'] slot with every row in the DOM, the rows behind 'Show all' included (D83):
the eleven in their fixed order, each with the heading and lead describe_summary gives, its notes, How this was made
and the roof groups, and the joined rows of the cell as describe_joins writes them (sections_problems, joined_problems).
The words come from the store the smoke is given (--store PATH; by default the built site's own hail/ folder, whose B4
live files under hail/live/ the store reader skips, D75). If that store cannot be read, the words are not compared and
the failure is named; the table's position and the sizes of the files a tap fetches are still checked. Every row shows
its kind word and its unit. Each file a tap fetches must be under the tile-file budget in map.json
(hail.budget.tile_events_gzip_bytes, D66), and the fetch list of every tap is printed as a note. check_every_layer
measures the phone view at zoom 15 over Billings with every layer of the menu on: the files it fetches, apart from the
picture frames (listed apart, as B3's note lists them), must be under the phone budget in map.json
(hail.budget.phone_gzip_bytes, 700,000 bytes gzip after D82(b)). --history makes a missing or unavailable summary a
failure (the branch preview passes it); without the flag that is a note. A --history run on a build without the address
layer, or without the five-season history, fails with one readable line and runs no browser check (R15, D72).

The Website workflow runs it on branch pushes; locally set PW_CHROMIUM to a Chromium executable if
Playwright's own isn't installed.
"""
from __future__ import annotations

import argparse
import copy
import functools
import gzip
import http.server
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]     # the repository (the store's reader, website/hail.py, is imported from it)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):          # one line per file would bury the result
        pass


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(QuietHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


class Counted:
    """The browser, with every context it opens counting the requests that leave this server. Leaflet and the
    fonts are served by the site (AGENTS.md rule 4), so the count must be zero in every context."""

    def __init__(self, browser, base: str):
        self._browser, self.base, self.offsite = browser, base, []

    def new_context(self, allow: tuple = (), **options):
        """allow: URL prefixes this context may request without counting. Only the imagery checks pass the
        imagery host, and only for the contexts that switch to Imagery; every other context passes none."""
        ctx = self._browser.new_context(**options)
        ctx.on("request", lambda request: self._note(request, allow))
        return ctx

    def _note(self, request, allow: tuple = ()) -> None:
        url = request.url
        if url.startswith(allow):
            return
        if not url.startswith((self.base, "data:", "blob:")):       # a data: picture makes no request at all
            self.offsite.append(url)

    def __getattr__(self, name):                                     # launch and close belong to the browser
        return getattr(self._browser, name)


def console_error(message) -> str:
    """A console error with the URL it names (Playwright's location). A failed request's file is then named, so a 404 can be
    traced to its file (F-14)."""
    url = (message.location or {}).get("url") or ""
    return f"console: {message.text}" + (f" ({url})" if url else "")


def history_problem(data: dict) -> str | None:
    """The one readable failure a --history run gets when its build cannot be checked (R15, D72): a build with no five-season
    history, or one without the address layer. The Website preview builds both flags and runs --addresses --history, so a
    --history run checks a build that has the address layer. None when the build can be checked."""
    if "hail" not in data:
        return "the build has no five-season history (no hail data in map.json): build with --hail-history"
    missing = [key for key in ("addresses", "roads", "buildings") if key not in data["hail"]]
    if missing:
        return ("the build has no address layer (" + ", ".join(missing) + " missing from map.json): --history checks the "
                "preview build, which passes --hail-addresses; build with --hail-addresses, or run without --history")
    return None


def check(root: Path, shots: Path | None = None, addresses: bool = False, store: Path | None = None,
          history: bool = False) -> list[str]:
    problems: list[str] = []
    data = json.loads((root / "data" / "map.json").read_text(encoding="utf-8"))
    blocked = history_problem(data) if history else None
    if blocked:
        return [blocked]
    from playwright.sync_api import sync_playwright

    precip_frames = len(data["layers"].get("precip", {}).get("frames", []))
    httpd, base = serve(root)
    launch = {"executable_path": os.environ["PW_CHROMIUM"]} if os.environ.get("PW_CHROMIUM") else {}
    try:
        with sync_playwright() as p:
            browser = Counted(p.chromium.launch(**launch), base)
            for label, size in (("desktop", (1280, 800)), ("phone", (390, 844))):
                ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
                page.on("console", lambda m: errors.append(console_error(m)) if m.type == "error" else None)
                page.on("requestfailed", lambda r: errors.append(f"failed request: {r.url}")
                        if r.url.startswith(base) else None)
                page.goto(base + "map.html", wait_until="load")

                if precip_frames:
                    # both overlays start as a 1x1 blank GIF (map.js BLANK), which is "complete" at once
                    if not frame_drawn(page, "precip"):
                        problems.append(f"{label}: no radar or forecast frame was drawn")
                    note = frame_note(page)
                    if "didn't load" in note or "didn\u2019t load" in note:
                        problems.append(f"{label}: the map says a picture didn't load ({note.strip()})")
                try:
                    page.wait_for_selector(".leaflet-overlay-pane svg path", timeout=15000)
                except Exception:
                    problems.append(f"{label}: the basemap outlines were not drawn")
                bubbles = page.locator(".leaflet-marker-icon.town").count()
                if bubbles < len(data["towns"]) or bubbles < 8:
                    problems.append(f"{label}: only {bubbles} town bubbles drawn")
                shown = page.evaluate("() => [...document.querySelectorAll('.leaflet-marker-icon.town')]"
                                      ".filter(e => getComputedStyle(e).display !== 'none').length")
                main = sum(1 for t in data["towns"] if t["min_zoom"] < 7)    # shown at the first view (zoom 5-6)
                if shown < main:
                    problems.append(f"{label}: {shown} town bubbles showing, {main} expected below zoom 7")

                slider = page.locator("input[type=range]")
                if slider.count() != 1:
                    problems.append(f"{label}: expected one timeline slider, found {slider.count()}")
                elif precip_frames > 1:
                    play = page.locator("button[aria-pressed]").first
                    if play.get_attribute("aria-pressed") == "true":     # autoplay: pause, then play again
                        play.click()
                    page.wait_for_timeout(300)
                    before = slider.input_value()
                    play.click()
                    page.wait_for_timeout(2500)
                    after = slider.input_value()
                    if before == after:
                        problems.append(f"{label}: pressing play did not move the timeline ({before})")
                    play.click()                                          # leave it paused

                layers = page.get_by_role("button", name="Layers")
                if layers.count():
                    layers.first.click()
                    wind = page.get_by_role("radio", name="Wind gusts")
                    if not wind.count():
                        wind = page.get_by_role("button", name="Wind gusts")
                    if wind.count():
                        wind.first.click()
                        page.wait_for_timeout(500)
                        page.keyboard.press("Escape")        # close the menu: its own "Wind gusts" doesn't count
                        want = data["layers"].get("wind", {}).get("title") or "Wind gusts"
                        title = page.locator("#legend-title").inner_text().strip()
                        if title != want:
                            problems.append(f"{label}: switching to wind gusts did not change the legend ({title})")
                        elif data["layers"].get("wind", {}).get("frames") and not frame_drawn(page, "wind"):
                            problems.append(f"{label}: switching to wind gusts drew no wind picture")
                    else:
                        problems.append(f"{label}: no Wind gusts choice in the layer menu")
                        page.keyboard.press("Escape")
                else:
                    problems.append(f"{label}: no Layers button")

                problems += [f"{label}: {e}" for e in errors]
                ctx.close()

            extras = (("check_menu_rows", lambda: check_menu_rows(browser, base)),
                      ("check_no_outline_key", lambda: check_no_outline_key(browser, base, data)),
                      ("check_phone_legend", lambda: check_phone_legend(browser, base, data)),
                      ("check_empty_layer_switch", lambda: check_empty_layer_switch(browser, base, data)),
                      ("check_card_words", lambda: check_card_words(browser, base, root)),
                      ("check_satellite", lambda: check_satellite(browser, base, data)),
                      ("check_imagery_switch", lambda: check_imagery_switch(browser, base, data, shots)),
                      ("check_imagery_direct", lambda: check_imagery_direct(browser, base, data)),
                      ("check_imagery_phone", lambda: check_imagery_phone(browser, base, data, shots)),
                      ("check_card_ignores_imagery", lambda: check_card_ignores_imagery(browser, base)),
                      ("check_imagery_refused", lambda: check_imagery_refused(browser, base, data)),
                      ("check_hail", lambda: check_hail(browser, base, root, data, shots))
                      if "hail" in data else ("check_no_hail", lambda: check_no_hail(browser, base, data)))
            if "hail" in data and data["hail"].get("joins"):
                extras += (("check_joins", lambda: check_joins(browser, base, root, data, shots)),)
            if addresses:
                extras += (("check_addresses", lambda: check_addresses(browser, base, root, data, shots)),)
            if "hail" in data:                            # B5 part B2: the summary table, the taps and the phone budget
                extras += (("check_summary", lambda: check_summary(browser, base, root, data, summary_store(store, root),
                                                                   shots, history)),
                           ("check_every_layer", lambda: check_every_layer(browser, base, data)))
            if "hail_60" in data["layers"]:               # --storm-layers: the live hail swath layers (B4)
                extras += (("check_swath", lambda: check_swath(browser, base, root, data, shots)),)
            for name, extra in extras:
                try:
                    problems += extra()
                except Exception as e:                                      # noqa: BLE001 - report, don't crash
                    problems.append(f"a check could not run ({name}): {str(e).splitlines()[0]}")

            ctx = browser.new_context(viewport={"width": 600, "height": 400})
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
            page.goto(base + "map.html?card=1&layer=precip", wait_until="load")
            page.wait_for_timeout(1500)
            if not page.get_by_role("link", name="Open map").count():
                problems.append("card: no 'Open map' link")
            problems += [f"card: {e}" for e in errors]
            ctx.close()
            outside = sorted(set(browser.offsite))
            if outside:
                problems.append(f"{len(browser.offsite)} request(s) went to other sites: " + ", ".join(outside[:5]))
            browser.close()
    finally:
        httpd.shutdown()
    return problems


def frame_drawn(page, layer: str, timeout: int = 15000) -> bool:
    """Whether a picture of this layer from map/frames/ has loaded into a map overlay."""
    try:
        page.wait_for_function(
            "layer => [...document.querySelectorAll('img.leaflet-image-layer')].some(i =>"
            " i.src.includes('/map/frames/' + layer + '-') && i.complete && i.naturalWidth > 1)",
            arg=layer, timeout=timeout)
        return True
    except Exception:                                                       # noqa: BLE001 - timed out
        return False


def frame_note(page) -> str:
    """The note under the timeline when it shows (pictures that failed, hatching, no pictures)."""
    return page.evaluate("() => { const n = document.getElementById('frame-note');"
                         " return n && !n.hidden ? n.textContent : ''; }")


ROWS_HIT = """() => [...document.querySelectorAll('#layers label')].map(l => {
  l.scrollIntoView({block: 'nearest'});
  const r = l.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  const hit = document.elementFromPoint(x, y);
  return {row: l.innerText.trim().split('\\n')[0].trim(), inside: !!(hit && document.getElementById('layers').contains(hit)),
          hit: hit ? (hit.id || hit.className || hit.tagName) : null};
})"""


# These waits are for the town bubbles to be drawn (attached). The first one in towns.json (Anaconda)
# is hidden at the first view (min_zoom 7), so waiting for a visible one would wait for the wrong town.
def check_menu_rows(browser, base) -> list[str]:
    """Phones held sideways and short windows: the layer menu sits over the timeline and every row
    (scrolled into the menu's view if need be) takes a tap at its centre."""
    problems = []
    ctx = browser.new_context(viewport={"width": 844, "height": 390}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
    for w, h in ((844, 390), (667, 375), (568, 320)):
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_timeout(200)
        page.click("#btn-layers")
        page.wait_for_timeout(150)
        for row in page.evaluate(ROWS_HIT):
            if not row["inside"]:
                problems.append(f"layer menu {w}x{h}: a tap on '{row['row']}' lands on {row['hit']}")
        page.keyboard.press("Escape")
    ctx.close()
    return problems


def check_no_outline_key(browser, base, data) -> list[str]:
    """Alerts with no outline (issued by county or zone) are named in the legend, whatever the
    Warnings switch says, and the row opens the List (AGENTS.md rule 6)."""
    n = sum(1 for a in data.get("alerts", {}).get("items", []) if not a.get("geometry"))
    if not n:
        return []
    problems = []
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
    page.wait_for_timeout(300)
    key = page.locator("#legend-keys [data-open-list]")
    if not key.count() or "no outline" not in key.inner_text() or not key.inner_text().startswith(str(n)):
        problems.append(f"legend: no key for the {n} alert(s) without an outline")
    else:
        key.click()
        page.wait_for_timeout(300)
        if page.locator("#sheet-title").inner_text() != "List":
            problems.append("legend: the no-outline key did not open the List")
    ctx.close()
    # in the one-column legend (wide screens, a phone on its side) the row sits right under the scale:
    # its text must clear the bottom stop label, which hangs half a line below the scale (a 3-line row
    # once pulled itself up into it). Only labels that overlap the text across count, so the two-column
    # legend of a portrait phone, its keys beside the scale, passes.
    for w, h in ((1280, 800), (844, 390), (390, 844)):
        ctx = browser.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(base + "map.html", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        page.wait_for_timeout(300)
        gap = page.evaluate("""() => {
          const key = document.querySelector('#legend-keys [data-open-list]');
          if (!key || !key.offsetParent) return null;
          const range = document.createRange(); range.selectNodeContents(key);
          const text = range.getBoundingClientRect();
          const above = [...document.querySelectorAll('#legend-stops li')].filter(li => li.offsetParent)
            .map(li => li.getBoundingClientRect()).filter(r => r.left < text.right && r.right > text.left);
          return above.length ? text.top - Math.max(...above.map(r => r.bottom)) : null;
        }""")
        if gap is not None and gap < 0:
            problems.append(f"legend {w}x{h}: the no-outline row's text runs {-gap:.1f} px into the bottom scale label")
        ctx.close()
    return problems


def check_phone_legend(browser, base, data) -> list[str]:
    """A portrait phone gets the two-column legend (about 135-170 px tall), no key comes or goes while
    the timeline plays (the legend keeps one height, so Montana keeps its room), and the Precipitation
    layer rings no town (rings mark the Temperature and Wind gusts layers' own limits)."""
    if not data["layers"].get("precip", {}).get("frames"):
        return []
    problems = []
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
    page.wait_for_timeout(300)
    form = page.evaluate("() => [document.getElementById('app').classList.contains('legend-2col'),"
                         " Math.round(document.getElementById('legend').getBoundingClientRect().height)]")
    if not form[0] or form[1] > 180:
        problems.append(f"phone legend: two-column={form[0]}, {form[1]} px tall (want the two-column form, at most 180 px)")
    page.focus("#range")
    page.keyboard.press("Home")
    heights, rings = set(), 0
    for _ in range(len(data["layers"]["precip"]["frames"])):
        page.wait_for_timeout(120)
        heights.add(page.evaluate("() => Math.round(document.getElementById('legend').getBoundingClientRect().height)"))
        rings += page.locator(".bubble.over").count()
        page.keyboard.press("ArrowRight")
    if len(heights) > 1:
        problems.append(f"phone legend: its height changes during the timeline ({sorted(heights)} px)")
    if rings:
        problems.append("phone legend: a town has a limit ring on the Precipitation layer")
    ctx.close()
    return problems


def check_empty_layer_switch(browser, base, data) -> list[str]:
    """A precipitation picture still loading when the viewer picks a layer with no pictures (radar
    worked, the model failed) must not appear under that layer's legend afterwards."""
    if not data["layers"].get("precip", {}).get("frames"):
        return []
    import json as _json
    empty = _json.loads(_json.dumps(data))
    empty["layers"]["temp"]["frames"] = []
    empty["layers"]["temp"]["modes"] = {"12h": []}
    held = []
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**/data/map.json*", lambda r: r.fulfill(status=200, content_type="application/json",
                                                         body=_json.dumps(empty)))
    page.route("**/map/frames/precip-*", lambda r: held.append(r))     # hold every precipitation picture
    # domcontentloaded, not load: the pictures held below would keep the load event waiting, and the check
    # waits for the is-loading class itself
    page.goto(base + "map.html", wait_until="domcontentloaded")
    problems = []
    try:
        page.wait_for_function("() => document.getElementById('app').classList.contains('is-loading')", timeout=15000)
        page.click("#btn-layers")
        page.get_by_role("radio", name="Temperature").check()
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.unroute("**/map/frames/precip-*")                         # later requests pass at once
        for r in held:
            r.continue_()
        page.wait_for_timeout(1500)
        shown = page.evaluate("() => [...document.querySelectorAll('img.leaflet-image-layer')]"
                              ".filter(i => parseFloat(getComputedStyle(i).opacity) > 0).map(i => i.getAttribute('src'))")
        if shown:
            problems.append(f"empty layer: a precipitation picture shows under the Temperature legend ({shown[0]})")
    except Exception as e:                                                  # noqa: BLE001 - report, don't crash
        problems.append(f"empty layer check could not run: {e}")
    ctx.close()
    return problems


CARD_WORDS = {"NOAA radar estimate": "The latest NOAA radar estimate",
              "HRRR model forecast": "The HRRR model forecast for {at}",
              "Sample radar": "The latest sample radar picture",
              "Sample forecast": "The sample model forecast for {at}"}


def check_card_words(browser, base, root) -> list[str]:
    """The Now page's caption (build.py map_card) names the picture the card shows (map.js), so a
    model forecast is never called the radar estimate (AGENTS.md rule 5)."""
    import html as _html
    import re
    ctx = browser.new_context(viewport={"width": 600, "height": 400}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(base + "map.html?card=1&layer=precip", wait_until="load")
    page.wait_for_selector("#card-chip .card-main", timeout=15000)
    page.wait_for_timeout(500)
    chip = " ".join(page.locator("#card-chip .card-main").inner_text().replace(" ", " ").split())
    ctx.close()
    found = re.search(r'<p class="caption">(.*?)</p>', (root / "index.html").read_text(encoding="utf-8"), re.S)
    caption = " ".join(re.sub(r"<[^>]+>", " ", _html.unescape(found.group(1))).split()) if found else ""
    kind, _, at = chip.partition(" · ")
    want = CARD_WORDS.get(kind, "").format(at=at)
    if not want and chip.startswith("No "):
        want = "Missing from this update: the radar and model pictures"
    if not want or want not in caption:
        return [f"Now page: the caption doesn't name the card's picture (card: {chip!r}; caption: {caption[:100]!r})"]
    return []


def pick_layer(page, name: str) -> None:
    """Open the layer menu, tick one layer in it and close the menu again."""
    page.click("#btn-layers")
    page.get_by_role("radio", name=name).check()
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)


ON_SCREEN = ("layer => [...document.querySelectorAll('img.leaflet-image-layer')].some(i =>"
             " i.src.includes('/map/frames/' + layer + '-') && parseFloat(getComputedStyle(i).opacity) > 0.99)")


def picture_on_screen(page, layer: str, timeout: int = 15000) -> bool:
    """Whether a picture of this layer from map/frames/ is on screen and fully opaque (not still fading in)."""
    try:
        page.wait_for_function(ON_SCREEN, arg=layer, timeout=timeout)
        return True
    except Exception:                                                       # noqa: BLE001 - timed out
        return False


def map_canvas(page) -> bytes:
    """A PNG of the map canvas alone. The controls, banners and sheets are hidden for the shot, so the legend
    and the timeline cannot account for a change."""
    box = page.locator("#map").bounding_box()
    if not box:
        raise ValueError("the map canvas has no size on screen")
    style = page.add_style_tag(content=".top, .bottom, .card-ui, .scrim, .sheet { visibility: hidden !important; }")
    page.wait_for_timeout(150)
    shot = page.screenshot(clip=box)
    style.evaluate("node => node.remove()")
    return shot


def changed_count(before: bytes, after: bytes) -> int:
    """The number of pixels that differ between two PNG screenshots of the same size (changed_share's rule)."""
    import io

    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(io.BytesIO(before)).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(io.BytesIO(after)).convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        raise ValueError(f"the two screenshots differ in size ({a.shape} and {b.shape})")
    return int(np.count_nonzero(np.max(np.abs(a - b), axis=2) > GATE_NOTE_PIXELS))


def changed_share(before: bytes, after: bytes) -> float:
    """The share of pixels that differ between two PNG screenshots of the same size: a pixel differs when any
    colour channel moved by more than 16 of 255."""
    import io

    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(io.BytesIO(before)).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(io.BytesIO(after)).convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        raise ValueError(f"the two screenshots differ in size ({a.shape} and {b.shape})")
    return float(np.mean(np.max(np.abs(a - b), axis=2) > 16))


def check_satellite(browser, base, data) -> list[str]:
    """The Satellite layer (--storm-layers builds only). The layer menu picks it, the legend says Satellite, one
    of its pictures is on screen and its swatch is painted from its legend. The picture also changes the map: the
    map canvas differs from the Precipitation layer's in more than 2% of its pixels, on a desktop and a phone."""
    if not data["layers"].get("satellite", {}).get("frames"):
        return []
    want = data["layers"]["satellite"].get("title") or "Satellite"
    problems = []
    for label, size in (("desktop", (1280, 800)), ("phone", (390, 844))):
        ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(base + "map.html", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        pick_layer(page, "Precipitation")
        if not picture_on_screen(page, "precip"):
            problems.append(f"{label}: no precipitation picture on screen to compare the satellite picture with")
        before = map_canvas(page)
        pick_layer(page, "Satellite")
        title = page.locator("#legend-title").inner_text().strip()
        if title != want:
            problems.append(f"{label}: switching to Satellite left the legend at {title!r}")
        if not picture_on_screen(page, "satellite"):
            problems.append(f"{label}: the satellite picture was not drawn")
        painted = page.evaluate("() => { const s = document.querySelector('#layers .sw-satellite');"
                                " return s ? getComputedStyle(s).backgroundImage : ''; }")
        if "gradient" not in painted:
            problems.append(f"{label}: the Satellite swatch in the layer menu is not painted from its legend")
        share = changed_share(before, map_canvas(page))
        if share <= 0.02:
            problems.append(f"{label}: switching to Satellite changed {share:.1%} of the map canvas "
                            "(more than 2% expected)")
        ctx.close()
    return problems + check_satellite_while_playing(browser, base, want)


def check_satellite_while_playing(browser, base, want: str) -> list[str]:
    """The timeline plays on Precipitation and the viewer picks Satellite while it plays. The Satellite layer has one
    frame, so the timeline's position must be brought inside it (buildTimeline clamps state.pos); without that the
    page throws. No script error may follow, on a desktop and a phone."""
    problems = []
    for label, size in (("desktop", (1280, 800)), ("phone", (390, 844))):
        ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e).splitlines()[0] if str(e) else "error"))
        page.goto(base + "map.html", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        pick_layer(page, "Precipitation")
        play = page.locator("#play")
        if play.get_attribute("aria-pressed") != "true":          # aria-pressed says the timeline is playing
            play.click()
        start = page.locator("#range").input_value()
        try:
            page.wait_for_function("v => document.getElementById('range').value !== v", arg=start, timeout=10000)
        except Exception:                                          # noqa: BLE001 - timed out
            problems.append(f"{label}: the timeline did not move while it played ({start})")
        pick_layer(page, "Satellite")
        page.wait_for_timeout(1000)
        title = page.locator("#legend-title").inner_text().strip()
        if title != want:
            problems.append(f"{label}: switching to Satellite while playing left the legend at {title!r}")
        problems += [f"{label}: page error after picking Satellite while playing: {e}" for e in errors]
        ctx.close()
    return problems


# ---------------------------------------------------------------- the Imagery base map (D32)

IMAGERY_HOST = "basemap.nationalmap.gov"    # the only host the browser asks for imagery tiles, and only after a switch
PRIVACY = "Your IP address and the map area you view go to USGS."   # the credit row's privacy words (D32)
NOTE = "note: "                             # a check line that starts with this is reported and never fails the run
TILE_WAIT = 20                              # seconds to wait for the first tile before it counts as not loaded
VECTOR = "path.bm-land, path.bm-lake, path.bm-river, path.bm-road, path.bm-county"   # the shapes Imagery hides
NAMES = ".bm-label span"                    # the white map's place and region names (HTML), hidden on Imagery
BORDERS = "path.bm-border"                  # the state and country lines and the Montana outline: they stay
IMAGERY_ON = "() => document.getElementById('app').classList.contains('is-imagery')"
CHOICE = "() => (document.querySelector('input[name=base]:checked') || {}).value || ''"
CREDIT_ROWS = "() => [...document.querySelectorAll('#legend-keys li')].map(li => li.textContent.trim())"
BUBBLES = ("() => [...document.querySelectorAll('.leaflet-marker-icon.town')]"
           ".filter(e => getComputedStyle(e).display !== 'none').length")
# a shape is painted when it is shown and has a fill or a stroke that is not transparent
PAINTED = """(sel) => [...document.querySelectorAll(sel)].filter(p => {
  const s = getComputedStyle(p);
  if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
  return (s.fill !== 'none' && parseFloat(s.fillOpacity) > 0) || (s.stroke !== 'none' && parseFloat(s.strokeOpacity) > 0);
}).length"""
# a text element is shown when it has a box on the screen (a hidden label has none)
SHOWN = """(sel) => [...document.querySelectorAll(sel)].filter(e => {
  const r = e.getBoundingClientRect(), s = getComputedStyle(e);
  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0;
}).length"""
TILE_DRAWN = ("() => [...document.querySelectorAll('img.leaflet-tile')].some(t => t.src.indexOf('https://" + IMAGERY_HOST +
              "/') === 0 && t.complete && t.naturalWidth === 256)")
TILE_LAYERS = "() => document.querySelectorAll('.leaflet-tile-pane .leaflet-layer').length"   # the imagery layer's container
HOST_PICTURES = ("() => [...document.querySelectorAll('img')].filter(i => (i.src || '').indexOf('https://" +
                 IMAGERY_HOST + "/') === 0).length")                                         # pictures from the host, drawn or not


def is_tile(response) -> bool:
    """A picture from the imagery host."""
    return response.url.startswith(f"https://{IMAGERY_HOST}/") and response.request.resource_type == "image"


class Watch:
    """What the imagery checks read from one page: its script and console errors, the requests it makes to the
    imagery host (allow lists the URL prefixes that are expected there) and the answers from that host. A console
    error from the host is a tile that failed to load, which the tile check reports, so it is not counted here."""

    def __init__(self, page, allow: tuple = ()):
        self.page, self.allow = page, allow
        self.errors: list[str] = []
        self.requests: list[str] = []
        self.answers: list = []
        page.on("pageerror", lambda e: self.errors.append(f"script error: {e}"))
        page.on("console", self._console)
        page.on("request", lambda r: self.requests.append(r.url) if r.url.startswith(allow) else None)
        page.on("response", lambda r: self.answers.append(r) if is_tile(r) else None)

    def _console(self, m) -> None:
        if m.type == "error" and not m.location.get("url", "").startswith(self.allow):
            self.errors.append(f"console: {m.text}")

    def tile(self):
        """The first answer from the imagery host, or None when none came within TILE_WAIT seconds."""
        deadline = time.monotonic() + TILE_WAIT
        while not self.answers and time.monotonic() < deadline:
            self.page.wait_for_timeout(200)
        return self.answers[0] if self.answers else None


def tile_problem(tile, label: str) -> str | None:
    """What is wrong with a tile that answered (it must be 200 image/jpeg), or None."""
    kind = tile.headers.get("content-type") or ""
    if tile.status != 200 or not kind.startswith("image/jpeg"):
        return f"{label}: the tile answered HTTP {tile.status} as {kind or 'no type'}, not 200 image/jpeg"
    return None


def base_choice(page, value: str) -> None:
    """Open the Layers menu, pick the base map ("map" or "imagery") and close the menu again."""
    page.click("#btn-layers")
    page.locator(f"input[name=base][value={value}]").check()
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)


def imagery_gone(page, seconds: float = 3) -> bool:
    """Whether the imagery tile layer and every picture from its host are off the page. Switching back to Map
    must remove them (map.js setBase), so a layer that stays, hidden or idle, is a failure. Leaflet removes it at
    once; the wait is only a margin."""
    deadline = time.monotonic() + seconds
    while True:
        if page.evaluate(TILE_LAYERS) == 0 and page.evaluate(HOST_PICTURES) == 0:
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(200)


def base_query(page) -> str:
    """The base= value in the page address ('' when there is none)."""
    return parse_qs(urlsplit(page.url).query).get("base", [""])[0]


def snap(page, shots: Path | None, name: str) -> None:
    """Save a picture of the page for the record (--shots); nothing is saved without it."""
    if shots is not None:
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / name))


def zoom_to_max(page) -> None:
    """Zoom in with the mouse wheel until the map stops at its maximum. (The keyboard's plus key drops presses
    that come quickly, so it can't be counted on to reach the limit.) The wheel clamps at the limit."""
    box = page.locator("#map").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(14):
        page.mouse.wheel(0, -500)
        page.wait_for_timeout(120)
    page.wait_for_timeout(400)


def map_zoom(page, data) -> float | None:
    """The zoom the map is at. Leaflet keeps its map object private, but a frame picture's overlay is exactly as
    wide on the screen as its bounds: 256 * 2^zoom * (east - west) / 360 pixels. None when it is not on the page."""
    (_, west), (_, east) = data["image_bounds"]
    width = page.evaluate("() => { const i = document.querySelector('img.leaflet-image-layer.frame');"
                          " return i ? parseFloat(i.style.width) || 0 : 0; }")
    if not width or east <= west:
        return None
    return math.log2(width * 360 / (256 * (east - west)))


def zoom_words(z: float | None) -> str:
    return "no reading" if z is None else f"{z:.2f}"


def imagery_problem(data) -> str | None:
    """Why the Imagery base map can't be checked (the data has no entry for it, or it names another host), else None."""
    imagery = data.get("imagery")
    if not imagery:
        return "imagery: map.json has no imagery entry, so the Imagery base map is not built"
    url = urlsplit(imagery.get("url", ""))
    if url.scheme != "https" or url.hostname != IMAGERY_HOST:
        return f"imagery: the tile address {imagery.get('url')!r} is not https on {IMAGERY_HOST}"
    return None


def check_imagery_switch(browser, base, data, shots) -> list[str]:
    """The Imagery base map on a desktop (D32). The white map asks the imagery host for nothing. The Layers menu
    picks Imagery, and one tile from the host must load (HTTP 200, image/jpeg). The vector land, lakes, rivers,
    roads, county lines and names are hidden, and the borders stay. The credit row and the address (base=imagery)
    show. The bubbles and the weather picture stay, and zooming reaches the imagery's maximum. Switching back
    restores the white map and its maximum zoom, and asks the host for nothing more."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    why = imagery_problem(data)
    if why:
        return [why]
    imagery = data["imagery"]
    allow = (f"https://{IMAGERY_HOST}/",)
    problems: list[str] = []
    if PRIVACY not in imagery["credit_line"]:
        problems.append("imagery: the credit line in map.json has no privacy words (D32)")
    ctx = browser.new_context(allow=allow, viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
    page = ctx.new_page()
    watch = Watch(page, allow)
    try:
        page.goto(base + "map.html", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        page.wait_for_selector(".leaflet-overlay-pane svg path", timeout=15000)
        if page.evaluate(IMAGERY_ON):
            problems.append("imagery: the page opens on Imagery without a switch")
        if not page.evaluate(PAINTED, "path.bm-land"):
            problems.append("imagery: the white map's land is not drawn before any switch")
        if page.locator("input[name=base][value=imagery]").count() != 1:
            return problems + ["imagery: the Layers menu has no Imagery choice (input name=base, value imagery)"]
        if data["layers"].get("precip", {}).get("frames") and not picture_on_screen(page, "precip"):
            problems.append("imagery: no weather picture is on screen before the switch")
        snap(page, shots, "desktop-map.png")

        early = list(watch.requests)                # asked of the imagery host before any switch: none may be
        base_choice(page, "imagery")
        tile = watch.tile()
        wrong = tile_problem(tile, "imagery") if tile is not None else None
        if tile is None:
            problems.append(NOTE + f"desktop imagery: tile did not load (no answer from {IMAGERY_HOST} in {TILE_WAIT} "
                            "seconds, so the internet may be off or USGS may be down); the other imagery checks still ran")
        elif wrong:
            problems.append(wrong)
        else:
            try:
                page.wait_for_function(TILE_DRAWN, timeout=15000)
            except PlaywrightTimeout:
                problems.append("imagery: the tile answered 200 image/jpeg but was not drawn on the map")
        page.wait_for_timeout(400)
        snap(page, shots, "desktop-imagery.png")

        if early:
            problems.append(f"imagery: {len(early)} imagery tile request(s) came before the switch (first: {early[0]})")
        if not page.evaluate(IMAGERY_ON):
            problems.append("imagery: switching to Imagery did not set is-imagery on #app")
        if base_query(page) != "imagery":
            problems.append(f"imagery: the address does not carry base=imagery after the switch ({page.url})")
        drawn = page.evaluate(PAINTED, VECTOR)
        if drawn:
            problems.append(f"imagery: {drawn} shape(s) of the white map are still drawn "
                            "(land, lakes, rivers, roads, counties)")
        names = page.evaluate(SHOWN, NAMES)
        if names:
            problems.append(f"imagery: {names} place name(s) of the white map are still shown")
        if not page.evaluate(PAINTED, BORDERS):
            problems.append("imagery: the state and country borders are hidden on Imagery; they should stay")
        if wrong is None and tile is not None and not credit_row_shows(page, imagery["credit_line"], seconds=5):
            problems.append("imagery: the credit row does not show the credit with its privacy words on Imagery "
                            f"(rows: {page.evaluate(CREDIT_ROWS)})")
        main_towns = sum(1 for t in data["towns"] if t["min_zoom"] < 7)    # shown at the first view (zoom 5-6)
        bubbles = page.evaluate(BUBBLES)
        if bubbles < main_towns:
            problems.append(f"imagery: {bubbles} town bubbles showing on Imagery, {main_towns} expected below zoom 7")
        if data["layers"].get("precip", {}).get("frames") and not picture_on_screen(page, "precip"):
            problems.append("imagery: the weather picture is not on screen on Imagery")

        zoom_to_max(page)
        z = map_zoom(page, data)
        if z is None or abs(z - imagery["max_zoom"]) > 0.05:
            problems.append(f"imagery: zooming in stops at {zoom_words(z)}, "
                            f"not the imagery's maximum {imagery['max_zoom']}")

        base_choice(page, "map")
        page.wait_for_timeout(400)
        mark = len(watch.requests)
        if page.evaluate(IMAGERY_ON):
            problems.append("imagery: switching back to Map left is-imagery on #app")
        if base_query(page) == "imagery":
            problems.append("imagery: the address still carries base=imagery after switching back")
        if not page.evaluate(PAINTED, "path.bm-land"):
            problems.append("imagery: switching back did not restore the white map's land")
        if any(imagery[k] in row for row in page.evaluate(CREDIT_ROWS) for k in ("credit_line", "failed_line")):
            problems.append("imagery: the credit row is still shown after switching back to Map")
        if not imagery_gone(page):
            problems.append("imagery: switching back to Map left the imagery tile layer on the page "
                            f"({page.evaluate(TILE_LAYERS)} layer(s), {page.evaluate(HOST_PICTURES)} picture(s) "
                            f"from {IMAGERY_HOST})")
        page.wait_for_timeout(1500)
        if len(watch.requests) > mark:
            problems.append(f"imagery: {len(watch.requests) - mark} imagery tile request(s) "
                            "after switching back to Map")
        base_choice(page, "imagery")                # a second round: the layer comes back, then goes again
        page.wait_for_timeout(400)
        if page.evaluate(TILE_LAYERS) != 1:
            problems.append(f"imagery: switching to Imagery the second time shows {page.evaluate(TILE_LAYERS)} "
                            "tile layer(s), not 1")
        base_choice(page, "map")
        if not imagery_gone(page):
            problems.append("imagery: the second switch back to Map left the imagery tile layer on the page "
                            f"({page.evaluate(TILE_LAYERS)} layer(s), {page.evaluate(HOST_PICTURES)} picture(s) "
                            f"from {IMAGERY_HOST})")
        zoom_to_max(page)
        z = map_zoom(page, data)
        want = data["view"]["max_zoom"]
        # the B3 layers raise the map's maximum to the highest zoom they ask for (map.js b3Zoom, b3TopZoom): the outlines'
        # emphasis zoom, and the address search's zoom (D47) on an address-only build
        hail = data.get("hail", {})
        if hail.get("buildings", {}).get("state") == "loaded":
            want = max(want, hail["buildings"]["zoom"]["emphasis"])
        if hail.get("addresses", {}).get("state") in ("loaded", "sample"):
            want = max(want, hail["addresses"]["zoom"]["choose"])
        if z is None or abs(z - want) > 0.05:
            problems.append(f"imagery: after switching back the map zooms to {zoom_words(z)}, "
                            f"not the white map's maximum {want}")
        problems += [f"desktop imagery: {e}" for e in watch.errors]
    finally:
        ctx.close()
    return problems


def check_imagery_direct(browser, base, data) -> list[str]:
    """map.html?base=imagery opens on Imagery: the class, the checked choice and the address say so, the credit row
    carries its privacy words as the page opens, and one tile comes from the imagery host (a missing tile is a note,
    as in check_imagery_switch)."""
    if imagery_problem(data):
        return []                                   # check_imagery_switch reports why
    imagery = data["imagery"]
    allow = (f"https://{IMAGERY_HOST}/",)
    problems: list[str] = []
    ctx = browser.new_context(allow=allow, viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
    page = ctx.new_page()
    watch = Watch(page, allow)
    try:
        page.goto(base + "map.html?base=imagery", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        tile = watch.tile()
        wrong = tile_problem(tile, "direct open") if tile is not None else None
        if tile is None:
            problems.append(NOTE + f"direct open: tile did not load (no answer from {IMAGERY_HOST} in {TILE_WAIT} "
                            "seconds); the other checks still ran")
        elif wrong:
            problems.append(wrong)
        elif not credit_row_shows(page, imagery["credit_line"]):
            problems.append("imagery: map.html?base=imagery does not show the credit with its privacy words as it "
                            f"opens (rows: {page.evaluate(CREDIT_ROWS)})")
        if not page.evaluate(IMAGERY_ON):
            problems.append("imagery: map.html?base=imagery does not open on Imagery (no is-imagery on #app)")
        if page.evaluate(CHOICE) != "imagery":
            problems.append("imagery: the Imagery choice is not the checked one on map.html?base=imagery")
        if base_query(page) != "imagery":
            problems.append(f"imagery: the address lost base=imagery when the page opened ({page.url})")
        problems += [f"direct open: {e}" for e in watch.errors]
    finally:
        ctx.close()
    return problems


def credit_row_shows(page, words: str, seconds: float = TILE_WAIT) -> bool:
    """Whether a row of the legend reads exactly these words within seconds. The credit row changes when a tile
    fails or loads, so the checks wait for the words they expect."""
    deadline = time.monotonic() + seconds
    while True:
        if words in page.evaluate(CREDIT_ROWS):
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(200)


def check_imagery_refused(browser, base, data) -> list[str]:
    """Every request to the imagery host is refused (as with no internet, or a USGS outage). Imagery still switches
    on, and the map shows what the About page and DESIGN.md say it shows: a plain near-white background with the
    Montana outline, the state and country lines and the town bubbles. The base map's own roads, lakes, rivers,
    counties and names stay hidden, the credit row says that imagery didn't load (the words from build.py), the
    weather picture still shows, and the page raises no script error. Then the requests are let through again: the
    row goes back to the credit, with its privacy words, once a tile loads (a note when no tile comes, as with no
    internet). The refusals are made in the browser, so the first part needs no internet."""
    if imagery_problem(data):
        return []
    imagery = data["imagery"]
    allow = (f"https://{IMAGERY_HOST}/",)
    problems: list[str] = []
    ctx = browser.new_context(allow=allow, viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
    refused: list[str] = []

    def refuse(route):
        refused.append(route.request.url)
        route.abort()

    ctx.route(f"https://{IMAGERY_HOST}/**", refuse)
    page = ctx.new_page()
    watch = Watch(page, allow)
    try:
        page.goto(base + "map.html", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        page.wait_for_selector(".leaflet-overlay-pane svg path", timeout=15000)
        base_choice(page, "imagery")
        deadline = time.monotonic() + TILE_WAIT
        while not refused and time.monotonic() < deadline:
            page.wait_for_timeout(200)
        page.wait_for_timeout(1000)
        if not refused:
            return problems + ["imagery refused: the Imagery switch asked the imagery host for no tile, "
                               "so the failure case was not tested"]
        if not page.evaluate(IMAGERY_ON):
            problems.append("imagery refused: switching to Imagery with no tiles did not set is-imagery on #app")
        if not credit_row_shows(page, imagery["failed_line"]):
            problems.append("imagery refused: the credit row does not say that imagery didn't load "
                            f"(rows: {page.evaluate(CREDIT_ROWS)})")
        if any(imagery["credit_line"] in row for row in page.evaluate(CREDIT_ROWS)):
            problems.append("imagery refused: the credit row still shows the credit while the tiles are refused")
        drawn = page.evaluate(PAINTED, VECTOR)
        if drawn:
            problems.append(f"imagery refused: {drawn} shape(s) of the base map are drawn with no tiles "
                            "(land, lakes, rivers, roads, counties)")
        names = page.evaluate(SHOWN, NAMES)
        if names:
            problems.append(f"imagery refused: {names} name(s) of the base map show with no tiles")
        if not page.evaluate(PAINTED, BORDERS):
            problems.append("imagery refused: the Montana outline and the state and country borders are not drawn "
                            "with no tiles")
        main_towns = sum(1 for t in data["towns"] if t["min_zoom"] < 7)    # shown at the first view (zoom 5-6)
        bubbles = page.evaluate(BUBBLES)
        if bubbles < main_towns:
            problems.append(f"imagery refused: {bubbles} town bubbles show with no tiles, {main_towns} expected below zoom 7")
        if data["layers"].get("precip", {}).get("frames") and not picture_on_screen(page, "precip"):
            problems.append("imagery refused: the weather picture is not on screen with no tiles")
        # the requests are let through again. Leaflet does not ask again for the tiles that failed, so the map moves
        # one zoom step: the tiles of the new zoom are asked for, and the first one that loads brings the credit back
        ctx.unroute(f"https://{IMAGERY_HOST}/**")
        box = page.locator("#map").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.wheel(0, 110)
        page.wait_for_timeout(400)
        tile = watch.tile()
        if tile is None:
            problems.append(NOTE + "imagery refused: the credit row's return to the credit was not checked: no tile came "
                            f"from {IMAGERY_HOST} in {TILE_WAIT} seconds, so the internet may be off")
        elif tile.status == 200 and (tile.headers.get("content-type") or "").startswith("image/jpeg"):
            if not credit_row_shows(page, imagery["credit_line"]):
                problems.append("imagery refused: a tile loaded, but the credit row does not show the credit with its "
                                f"privacy words (rows: {page.evaluate(CREDIT_ROWS)})")
        elif not credit_row_shows(page, imagery["failed_line"]):
            problems.append(f"imagery refused: the tile answered HTTP {tile.status}, but the credit row does not say "
                            "that imagery didn't load")
        problems += [f"imagery refused: {e}" for e in watch.errors]
    finally:
        ctx.close()
    return problems


def check_imagery_phone(browser, base, data, shots) -> list[str]:
    """A portrait phone switches to Imagery the same way: the class, the address and the bubbles. Both base maps
    are pictured for the record (--shots). The desktop check reports a tile that does not load."""
    if imagery_problem(data):
        return []
    allow = (f"https://{IMAGERY_HOST}/",)
    problems: list[str] = []
    ctx = browser.new_context(allow=allow, viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    watch = Watch(page, allow)
    try:
        page.goto(base + "map.html", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        page.wait_for_selector(".leaflet-overlay-pane svg path", timeout=15000)
        snap(page, shots, "phone-map.png")
        base_choice(page, "imagery")
        watch.tile()                                # the picture waits for a tile; a missing one is the desktop's note
        page.wait_for_timeout(400)
        if not page.evaluate(IMAGERY_ON):
            problems.append("phone imagery: switching to Imagery did not set is-imagery on #app")
        if base_query(page) != "imagery":
            problems.append(f"phone imagery: the address does not carry base=imagery ({page.url})")
        main_towns = sum(1 for t in data["towns"] if t["min_zoom"] < 7)    # shown at the first view (zoom 5-6)
        if page.evaluate(BUBBLES) < main_towns:
            problems.append("phone imagery: not every main town bubble shows on Imagery")
        snap(page, shots, "phone-imagery.png")
        problems += [f"phone imagery: {e}" for e in watch.errors]
    finally:
        ctx.close()
    return problems


def check_card_ignores_imagery(browser, base) -> list[str]:
    """The map card (?card=1, on the Now and Storm reports pages) never uses Imagery, even with base=imagery in its
    address: no is-imagery class, and no request to the imagery host (this context allows no outside request)."""
    problems: list[str] = []
    ctx = browser.new_context(viewport={"width": 600, "height": 400}, reduced_motion="reduce")
    page = ctx.new_page()
    watch = Watch(page)
    try:
        page.goto(base + "map.html?card=1&layer=precip&base=imagery", wait_until="load")
        page.wait_for_selector("#card-chip .card-main", timeout=15000)
        page.wait_for_timeout(500)
        if page.evaluate(IMAGERY_ON):
            problems.append("card: ?card=1 with base=imagery switched the card to Imagery")
        problems += [f"card: {e}" for e in watch.errors]
    finally:
        ctx.close()
    return problems


# ------------------------------------------------------- the hail history at a spot (--hail-history builds)

HAIL_BENCHLAND = (47.08, -110.02)      # a grid corner: the rule that sends an edge south or east gives cell (792, 1998)
HAIL_CELL_CENTRE = (47.075, -110.015)  # the centre of that cell, Benchland's own: 0.72 in (18.5 mm) on Jun 15, 2025
HAIL_GATE = (47.025, -110.135)         # the centre of cell (797, 1986): the cell nearest Benchland with 513 tenths that day
HAIL_OUTSIDE = {"Colorado": (40.0, -105.0), "Wyoming": (43.5, -108.0), "Idaho": (44.6, -115.0),
                "Canada": (49.5, -110.0)}      # outside Montana: no Montana cell in these tiles, so the store lists none
HAIL_SAMPLE_GAPS = {"Helena": (46.589, -112.039), "Missoula": (46.8721, -113.994)}   # in Montana, in tiles a sample lacks
HAIL_OFF_GRID = (95.0, -110.0)         # north of the grid: not even a tile name
HAIL_BENCHLAND_TILE = "r0079_c0199"    # the tile of Benchland's cell: read first when looking for a spot with no value
HAIL_SIZES = (("desktop", (1280, 800)), ("phone", (390, 844)))


def hail_store():
    """The store's reader, website/hail.py, imported from this repository."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from website import hail as hs
    return hs


def hail_at(point: tuple[float, float]) -> str:
    """A spot as the address carries it, ?at=lat,lon. %g keeps every cell centre exact to the millionth of a degree."""
    return "%g,%g" % point


def hail_shard_asks(page) -> list[str]:
    """The shard requests the page makes from now on. Attach it before the page opens, so a request at load counts."""
    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url) if "/hail/t/" in r.url else None)
    return asked


def hail_shard(root: Path, name: str) -> dict:
    """One shard of the built site: the copy of the store's hail/t/ file."""
    return json.loads((root / "hail" / "t" / f"{name}.json").read_text(encoding="utf-8"))


def key_centre(shard: dict, key: int) -> tuple[float, float]:
    """The centre of the cell with this key in the shard's tile: key = (row % 10) * 10 + col % 10."""
    return hail_store().cell_centre(shard["r"] * 10 + key // 10, shard["c"] * 10 + key % 10)


def listed_tiles(data: dict) -> list[str]:
    """The tile names the map lists, from the compact split map the hail block carries (D40: no block lists every tile
    name): {"<tile row>": [[first column, last column], ...]}, written by build.py's tile_split. Names read as the store
    writes them, r0079_c0199. A map with no split map gives the list it had before D40, when there is one."""
    split = data["hail"].get("tile_split")
    if split is None:
        return sorted(data["hail"].get("tiles", []))
    return sorted(f"r{int(row):04d}_c{col:04d}" for row, runs in split.items()
                  for first, last in runs for col in range(first, last + 1))


def no_estimate_spot(root: Path, data: dict):
    """A Montana cell with no stored value on any day: a key in its tile's state list with no entry in cells, read from
    the store's shards (Benchland's tile first). None when no listed tile has one."""
    listed = set(listed_tiles(data))
    for name in [HAIL_BENCHLAND_TILE] + sorted(listed):
        if name not in listed:
            continue
        shard = hail_shard(root, name)
        have = {int(k) for k in shard["cells"]}
        for key in shard["state"]:
            if key not in have:
                return key_centre(shard, key)
    return None


def outside_spot(root: Path, data: dict):
    """A cell inside a listed tile whose key is not in the tile's state list: outside Montana, in a tile the browser
    does fetch (the border tiles). None when the store has no such cell."""
    for name in listed_tiles(data):
        shard = hail_shard(root, name)
        inside = set(shard["state"])
        for key in range(100):
            if key not in inside:
                return key_centre(shard, key)
    return None


def hail_expected(root: Path, data: dict, lat: float, lon: float) -> dict:
    """What the store says for a point, from the store's own reader and describe() (website/hail.py). The sheet must
    show the same sentences, so the check follows the store rather than one fixed value."""
    sys.path.insert(0, str(ROOT))
    from website import hail as hs
    built = datetime.fromisoformat(data["built"].replace("Z", "+00:00"))
    index = hs.load_index(root)
    return hs.describe(index, hs.cell_events(root, lat, lon), built, sample=data["hail"]["state"] == "sample")


def map_pixel(page, data: dict, lat: float, lon: float) -> tuple[float, float]:
    """Where a point is on the screen. The frame picture's box is the image bounds, projected as Leaflet projects
    them (Web Mercator), so a point's place in that box is its place on the screen."""
    box = page.locator("img.leaflet-image-layer.frame").first.bounding_box()
    (south, west), (north, east) = data["image_bounds"]

    def merc(deg: float) -> float:
        return math.log(math.tan(math.pi / 4 + math.radians(deg) / 2))
    x = box["x"] + (lon - west) / (east - west) * box["width"]
    y = box["y"] + (merc(north) - merc(lat)) / (merc(north) - merc(south)) * box["height"]
    return x, y


def hail_open(page, root_url: str, at: str | None = None) -> None:
    """Open the map (on a spot, when the address names one) and wait until it is drawn."""
    page.goto(root_url + "map.html" + (f"?at={at}" if at else ""), wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=20000)
    page.wait_for_selector("img.leaflet-image-layer.frame", timeout=20000)
    page.wait_for_timeout(700)


def sheet_settled(page, loading: str, seconds: float = 15) -> str:
    """The hail sheet's text once it has left the loading line; '' when it does not open in time."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = page.evaluate("() => { const s = document.getElementById('sheet');"
                             " return s && !s.hidden ? document.getElementById('sheet-body').innerText : null; }")
        if text is not None and text.strip() and loading not in text:
            return text
        page.wait_for_timeout(150)
    return ""


def zoom_at_centre(page) -> None:
    """Zoom in with the wheel over the middle of the map, where a spot is after ?at= (the wheel keeps the point under
    the pointer). It stops at the map's maximum, so a pixel is a small part of a cell."""
    box = page.locator("#map").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(14):
        page.mouse.wheel(0, -500)
        page.wait_for_timeout(120)
    page.wait_for_timeout(500)


def pane_transform(page) -> str:
    """The map pane's CSS transform. Leaflet writes it when the map pans or zooms, so a change means the map moved."""
    return page.evaluate("() => document.querySelector('.leaflet-map-pane').style.transform")


def check_sheet_words(label: str, text: str, want: dict, sample: bool) -> list[str]:
    """Every sentence describe() makes for the cell is on the sheet, unchanged; no template brace is left over."""
    problems = []
    if want["lead"] not in text:
        problems.append(f"{label}: the sheet's lead is not the store's lead ({want['lead'][:90]!r})")
    for row in want["rows"]:
        if row["text"] not in text:
            problems.append(f"{label}: the sheet lacks the day {row['text']!r}")
    for key in ("what_this_is", "missing", "stale", "source"):
        if want[key] and want[key] not in text:
            problems.append(f"{label}: the sheet lacks the {key.replace('_', ' ')} line")
    for line in want["class_lines"]:
        if line not in text:
            problems.append(f"{label}: the sheet lacks the class count {line!r}")
    if "{" in text or "}" in text:
        problems.append(f"{label}: a template brace was left in the sheet")
    if sample and "SAMPLE data" not in text:
        problems.append(f"{label}: the sample sheet does not say SAMPLE data")
    if not sample and "SAMPLE" in text:
        problems.append(f"{label}: a store file's sheet says SAMPLE")
    return problems


def check_hail(browser, base: str, root: Path, data: dict, shots: Path | None) -> list[str]:
    """The hail history at a spot (--hail-history), in Chromium at 1280 and 390 px.
    - ?at=47.08,-110.02 opens the sheet on arrival with one shard request; the grid's edge rule gives cell (792, 1998),
      whose sheet shows 0.72 in (18.5 mm) on Jun 15, 2025;
    - a click on the centre of that cell opens its words and writes at= into the address; Escape and the Close button
      close the sheet and drop at=;
    - the gate (decision 15): the centre of cell (797, 1986) shows 2.01 in (51.3 mm) on Jun 15, 2025;
    - a point outside Montana (Colorado, Wyoming, Idaho, Canada) gets the outside words and asks for no shard, and a spot
      off the grid gets them too and leaves the map where it was; in a sample build the outside points get the sample's
      own outside words with SAMPLE data, and so does a Montana spot in a tile the sample does not hold (Helena, Missoula);
    - a Montana cell with no entry in its shard gets the no-estimate words after one shard request;
    - a cell inside a listed tile but outside Montana gets the outside words after one shard request, when the store
      has such a cell;
    - a shard that cannot be reached, or answers 404 for a tile the store lists, gets the unavailable words;
    - every sentence the sheet shows is the one describe() makes for the same store.
    The gate and Benchland values are checked on the sample store and on a real store alike."""
    problems: list[str] = []
    h = data["hail"]
    words = h["words"]
    if h["state"] == "unavailable":
        return [f"{NOTE}the history did not load in this build ({h['problem']}), so only the words were checked"]
    if not listed_tiles(data):
        return ["the map data has no tile split (hail.tile_split), so the browser cannot tell outside from no estimate"]
    sample = h["state"] == "sample"
    want = hail_expected(root, data, *HAIL_BENCHLAND)
    centre = hail_expected(root, data, *HAIL_CELL_CENTRE)
    gate = hail_expected(root, data, *HAIL_GATE)
    for label, size in HAIL_SIZES:
        ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
        page.on("console", lambda m: errors.append(console_error(m)) if m.type == "error"
                and "/hail/t/" not in (m.location or {}).get("url", "") else None)
        try:
            asked = hail_shard_asks(page)
            hail_open(page, base, hail_at(HAIL_BENCHLAND))
            text = sheet_settled(page, words["loading"])
            if not text:
                problems.append(f"{label}: ?at={hail_at(HAIL_BENCHLAND)} did not open the hail sheet")
            else:
                if page.inner_text("#sheet-title").strip() != words["title"]:
                    problems.append(f"{label}: the hail sheet's title is not {words['title']!r}")
                problems += check_sheet_words(label, text, want, sample)
                problems += [f"{label}: the sheet lacks {part!r} (Benchland's cell, 792, 1998)"
                             for part in ("0.72 in (18.5 mm)", "Jun 15, 2025") if part not in text]
                at = parse_qs(urlsplit(page.url).query).get("at", [""])[0]
                if at != hail_at(HAIL_BENCHLAND):
                    problems.append(f"{label}: the address says at={at!r}, not at={hail_at(HAIL_BENCHLAND)}")
                snap(page, shots, f"hail-sheet-arrival-{size[0]}.png")
            if len(asked) != 1:
                problems.append(f"{label}: ?at= for Benchland asked for {len(asked)} shard(s), not one")
            page.keyboard.press("Escape")
            if not page.locator("#sheet").is_hidden():
                problems.append(f"{label}: Escape did not close the hail sheet")
            if "at" in parse_qs(urlsplit(page.url).query):
                problems.append(f"{label}: the address still holds at= after Escape closed the hail sheet")

            hail_open(page, base, hail_at(HAIL_CELL_CENTRE))
            sheet_settled(page, words["loading"])
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)              # closing the sheet puts the map back: let that pan finish
            zoom_at_centre(page)
            x, y = map_pixel(page, data, *HAIL_CELL_CENTRE)
            page.mouse.click(x, y)
            text = sheet_settled(page, words["loading"])
            if not text:
                problems.append(f"{label}: a click on the cell's centre did not open the hail sheet")
            else:
                problems += check_sheet_words(label, text, centre, sample)
                problems += [f"{label}: the click's sheet lacks {part!r} (Benchland's cell)"
                             for part in ("0.72 in (18.5 mm)", "Jun 15, 2025") if part not in text]
                snap(page, shots, f"hail-sheet-click-{size[0]}.png")
                at = parse_qs(urlsplit(page.url).query).get("at", [""])[0]
                if not at:
                    problems.append(f"{label}: the click did not write at=lat,lon into the address")
                else:
                    lat, lon = (float(v) for v in at.split(","))
                    if abs(lat - HAIL_CELL_CENTRE[0]) > 0.005 or abs(lon - HAIL_CELL_CENTRE[1]) > 0.005:
                        problems.append(f"{label}: the click wrote at={at}, not near the cell's centre")
            if not page.locator("#sheet").is_hidden():
                page.locator("#sheet-close").click()
                if not page.locator("#sheet").is_hidden():
                    problems.append(f"{label}: the Close button did not close the hail sheet")
            if "at" in parse_qs(urlsplit(page.url).query):
                problems.append(f"{label}: the address still holds at= after the Close button closed the hail sheet")

            hail_open(page, base, hail_at(HAIL_GATE))
            text = sheet_settled(page, words["loading"])
            if not text:
                problems.append(f"{label}: the gate cell (797, 1986) did not open the hail sheet")
            else:
                problems += check_sheet_words(f"{label}, gate", text, gate, sample)
                problems += [f"{label}: the gate cell's sheet lacks {part!r}"
                             for part in ("2.01 in (51.3 mm)", "Jun 15, 2025") if part not in text]
                snap(page, shots, f"hail-sheet-gate-{size[0]}.png")
            problems += [f"{label}: {e}" for e in errors]
        finally:
            ctx.close()

    outside_words = words["sample_outside"] if sample else words["outside"]   # a sample build's own words, as describe() has them
    for name, point in HAIL_OUTSIDE.items():
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        try:
            asked = hail_shard_asks(page)
            hail_open(page, base, hail_at(point))
            text = sheet_settled(page, words["loading"])
            if outside_words not in text:
                problems.append(f"outside: ?at={hail_at(point)} ({name}) does not show the outside words ({text[:120]!r})")
            if sample and words["sample"] not in text:
                problems.append(f"outside: ?at={hail_at(point)} ({name}) does not say {words['sample']!r} in a sample build")
            if asked:
                problems.append(f"outside: ?at={hail_at(point)} ({name}) asked for a shard ({asked[0]}), though it is outside Montana")
        finally:
            ctx.close()

    if sample:      # a Montana spot in a tile the sample store does not hold: the sample's words, and no shard request
        for name, point in HAIL_SAMPLE_GAPS.items():
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            try:
                asked = hail_shard_asks(page)
                hail_open(page, base, hail_at(point))
                text = sheet_settled(page, words["loading"])
                if words["sample_outside"] not in text:
                    problems.append(f"sample gap: ?at={hail_at(point)} ({name}) does not show the sample's words ({text[:120]!r})")
                if words["sample"] not in text:
                    problems.append(f"sample gap: ?at={hail_at(point)} ({name}) does not say {words['sample']!r}")
                if asked:
                    problems.append(f"sample gap: ?at={hail_at(point)} ({name}) asked for a shard ({asked[0]}), not in the sample")
            finally:
                ctx.close()

    for label, size in HAIL_SIZES:
        ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
        page = ctx.new_page()
        try:
            asked = hail_shard_asks(page)
            hail_open(page, base)
            before = pane_transform(page)
            hail_open(page, base, hail_at(HAIL_OFF_GRID))
            text = sheet_settled(page, words["loading"])
            if words["outside"] not in text:
                problems.append(f"{label}: ?at={hail_at(HAIL_OFF_GRID)} (off the grid) does not show the outside words ({text[:120]!r})")
            if asked:
                problems.append(f"{label}: ?at={hail_at(HAIL_OFF_GRID)} (off the grid) asked for a tile: {asked[0]}")
            if pane_transform(page) != before:
                problems.append(f"{label}: ?at={hail_at(HAIL_OFF_GRID)} (off the grid) moved the map")
        finally:
            ctx.close()

    spot = no_estimate_spot(root, data)
    if spot is None:
        problems.append(f"{NOTE}no listed tile has a Montana cell without a value, so the no-estimate check did not run")
    else:
        want_none = hail_expected(root, data, *spot)
        for label, size in HAIL_SIZES:
            ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
            page = ctx.new_page()
            try:
                asked = hail_shard_asks(page)
                hail_open(page, base, hail_at(spot))
                text = sheet_settled(page, words["loading"])
                if want_none["lead"] not in text:
                    problems.append(f"{label}: the Montana cell at {hail_at(spot)} with no value lacks the no-estimate "
                                    f"sentence ({text[:120]!r})")
                if words["outside"] in text:
                    problems.append(f"{label}: the Montana cell at {hail_at(spot)} with no value says outside")
                if len(asked) != 1:
                    problems.append(f"{label}: the Montana cell at {hail_at(spot)} asked for {len(asked)} shard(s), not one")
            finally:
                ctx.close()

    spot = outside_spot(root, data)
    if spot is None:
        problems.append(f"{NOTE}no listed tile has a cell outside Montana, so the outside-after-fetch check did not run")
    else:
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        try:
            asked = hail_shard_asks(page)
            hail_open(page, base, hail_at(spot))
            text = sheet_settled(page, words["loading"])
            if outside_words not in text:
                problems.append(f"outside after one fetch: ?at={hail_at(spot)} does not show the outside words ({text[:120]!r})")
            if sample and words["sample"] not in text:
                problems.append(f"outside after one fetch: ?at={hail_at(spot)} does not say {words['sample']!r} in a sample build")
            if len(asked) != 1:
                problems.append(f"outside after one fetch: ?at={hail_at(spot)} asked for {len(asked)} shard(s), not one")
        finally:
            ctx.close()

    for how, answer in (("cannot be reached", lambda route: route.abort()),
                        ("answers 404 for a tile the store lists", lambda route: route.fulfill(status=404, body="not found"))):
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        try:
            asked = hail_shard_asks(page)
            page.route("**/hail/t/**", answer)
            hail_open(page, base, hail_at(HAIL_CELL_CENTRE))
            text = sheet_settled(page, words["loading"])
            expected = words["unavailable"].replace("{problem}", words["fetch_failed"])
            if expected not in text:
                problems.append(f"failed tile ({how}): the sheet does not say the history is unavailable ({text[:120]!r})")
            if sample and words["sample"] not in text:
                problems.append(f"failed tile ({how}): the sample sheet does not say {words['sample']!r}")
            if not asked:
                problems.append(f"failed tile ({how}): the sheet made no request for the tile it needed")
        finally:
            ctx.close()
    return problems


def check_no_hail(browser, base: str, data: dict) -> list[str]:
    """A build without the hail key (the default) has no hail sheet and no legend line, and a click on the map opens
    no sheet."""
    if "hail" in data:
        return ["the build has a hail key, so it is not checked as a build without one"]
    problems = []
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    try:
        hail_open(page, base)
        if page.locator(".legend-tap, #hail-sheet, #hail-list").count():
            problems.append("no hail: the map page has a hail line or sheet template")
        x, y = map_pixel(page, data, *HAIL_CELL_CENTRE)
        page.mouse.click(x, y)
        page.wait_for_timeout(600)
        if not page.locator("#sheet").is_hidden():
            problems.append("no hail: a click on the map opened a sheet")
    finally:
        ctx.close()
    return problems


# ---------------------------------------------------------------- joined records (B2): the six sections under the sheet

JOIN_SECTIONS = ("reports", "records", "detections", "warnings", "zones", "stations")   # the six joined parts of describe_joins (their
                                                                                          # rows reach the eleven sections by _section_of)
GATE_UTICA_TIME = "11:45 pm"        # the Utica 1.0 in report of 2025-06-15 05:45 UTC, read in Montana time: Jun 14, 2025
GATE_UTICA_DAY = "Jun 14, 2025"     # the gate cell's only report within 5 miles (4.35 mi, research LSR row 202506150545)
BENCHLAND_TIME = "2:10 pm"          # the 1.75 in report of 2025-06-15 20:10 UTC (LSR 202506152010, NCEI EVENT 1258081)
BENCHLAND_DAY = "Jun 15, 2025"
GATE_OFFICE = "TFX"                 # a warning that covered the gate cell's spot: the office code the row shows


SHEET_READ = r"""() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const body = document.getElementById('sheet-body');
  if (!body) return null;
  const textOf = el => (el ? clean(el.textContent) : null);
  const plainOf = ul => (ul ? [...ul.querySelectorAll(':scope > li')].map(li => clean(li.textContent)) : []);
  const rowsOf = ul => (ul ? [...ul.querySelectorAll(':scope > li')].map(li => {
    const label = li.querySelector(':scope > span.hist-label');
    const note = li.querySelector(':scope > small.hist-note');
    const words = [...li.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('');
    return {label: label ? clean(label.textContent).replace(/:$/, '') : '', text: clean(words),
            note: note ? clean(note.textContent) : ''};
  }) : []);
  let summary = null;
  const sum = body.querySelector('[data-hail="summary"]');
  if (sum) {
    const subs = [...sum.querySelectorAll(':scope > p.sub')];
    summary = {hidden: sum.hidden, heading: textOf(sum.querySelector(':scope > h3')),
               plain: subs.length ? textOf(subs[0]) : null,
               radar: subs.length > 1 ? textOf(subs[subs.length - 1]) : null,
               notes: plainOf(sum.querySelector(':scope > ul.sum-notes')),
               partial: textOf(sum.querySelector(':scope > p.sum-partial')),
               failed: textOf(sum.querySelector(':scope > p.warn'))};
  }
  let sections = null;
  const sec = body.querySelector('[data-hail="sections"]');
  if (sec) {
    sections = {hidden: sec.hidden, notices: [...sec.querySelectorAll(':scope > p')].map(p => clean(p.textContent)),
                text: clean(sec.textContent), items: []};
    sections.items = [...sec.querySelectorAll(':scope > section.hist-sec[data-section]')].map(s => {
      const groups = [];
      let cur = null;
      [...s.children].forEach(c => {
        if (c.matches('h4.hist-group')) { cur = {name: clean(c.textContent), lines: [], refs: [], held: []}; groups.push(cur); }
        else if (cur && c.matches('ul.hist-lines')) cur.lines = plainOf(c);
        else if (cur && c.matches('ul.hist-refs')) cur.refs = plainOf(c);
        else if (cur && c.matches('ul.hist-held')) cur.held = plainOf(c);
      });
      const more = s.querySelector(':scope > details.hist-more');
      return {id: s.dataset.section, heading: textOf(s.querySelector(':scope > h3')),
              sample: textOf(s.querySelector(':scope > p.hist-sample')),
              lead: textOf(s.querySelector(':scope > p.hist-lead')),
              rows: rowsOf(s.querySelector(':scope > ul.hist-rows')),
              more: more ? {summary: textOf(more.querySelector(':scope > summary')),
                            rows: rowsOf(more.querySelector(':scope > ul.hist-rows'))} : null,
              groups: groups, notes: plainOf(s.querySelector(':scope > ul.sum-notes')), text: clean(s.textContent)};
    });
  }
  return {summary: summary, sections: sections};
}"""


def sheet_read(page, ids: list[str]) -> dict:
    """The open sheet as the reader sees it (D83(a); B5 part B2 round 2): the table's slot ([data-hail='summary']) and the
    sections' slot ([data-hail='sections']). It waits, up to SUMMARY_WAIT_S, until the sections are the eleven of ids in their
    order. Each section keeps every row the page holds: the rows shown and the rows behind 'Show all'. The rows are read as
    text content, because a closed <details> keeps its rows in the page and innerText would leave them out."""
    deadline = time.monotonic() + SUMMARY_WAIT_S
    while True:
        got = page.evaluate(SHEET_READ) or {"summary": None, "sections": None}
        items = ((got.get("sections") or {}).get("items")) or []
        if [item["id"] for item in items] == list(ids) or time.monotonic() > deadline:
            return got
        page.wait_for_timeout(200)


def section_ids(data: dict) -> list[str]:
    """The eleven sections of the sheet in their fixed order, as map.json's summary block lists them (summary.py _sections)."""
    ids = (data["hail"].get("summary") or {}).get("sections")
    return list(ids) if isinstance(ids, list) else []


def section_rows(section: dict) -> list[dict]:
    """Every row a section holds, in order: the rows shown, then the rows behind its 'Show all' control (D83(a))."""
    return list(section.get("rows") or []) + list(((section.get("more") or {}).get("rows")) or [])


def sheet_rows(sheet: dict) -> list[dict]:
    """Every row of every section of the sheet, in order."""
    return [row for item in ((sheet.get("sections") or {}).get("items") or []) for row in section_rows(item)]


def sheet_order_problems(label: str, sheet: dict, ids: list[str]) -> list[str]:
    """The sections slot is shown and holds the sections of ids, in their fixed order (D82, D83)."""
    got = sheet.get("sections")
    if not got:
        return [f"{label}: the sheet has no sections slot ([data-hail='sections'])"]
    if got.get("hidden"):
        return [f"{label}: the sheet's sections are hidden"]
    order = [item["id"] for item in got.get("items") or []]
    if order != list(ids):
        return [f"{label}: the sheet's sections are {order}, the fixed order is {list(ids)}"]
    return []


def expected_rows_by_section(expected: dict) -> dict[str, list[dict]]:
    """The joined rows of a cell (describe_joins: the six parts in their order), each placed in the section that build.py's
    _section_of gives it, the rule the browser mirrors (summary.SECTION_RULES): {section id: [{label, text, remark}]}."""
    summary_module()                                    # puts the repository on sys.path
    from website import build as bd
    placed: dict[str, list[dict]] = {}
    for sec in expected["sections"]:
        for row in sec["rows"]:
            label, words = bd._split_kind(row["text"])
            placed.setdefault(bd._section_of(label, words), []).append(
                {"label": label, "text": words, "remark": row.get("remark") or ""})
    return placed


def joined_problems(label: str, sheet: dict, expected: dict, data: dict) -> list[str]:
    """The joined rows of one cell on the open sheet against describe_joins for the same cell (B2 gates 1, 5 and 7; D82(d),
    D83). In each section the joined rows (those whose kind label is a joined kind) are the module's, in its order, each with
    its label, its words and its remark. A section with more rows than map.json's show_first shows that many, and its 'Show
    all n rows' control (the words from map.json) holds the rest. Each line and each unavailable sentence of the cell is on
    the sheet, and a section shows the kind sentence (kind_what) of each kind label among its rows."""
    problems: list[str] = []
    got = sheet.get("sections") or {}
    items = got.get("items") or []
    if not items:
        return [f"{label}: the sheet has no sections"]
    have = {item["id"]: item for item in items}
    sm = summary_module()
    placed = expected_rows_by_section(expected)
    for sid in placed:
        if sid not in have:
            problems.append(f"{label}: the {sid} section is missing, and {len(placed[sid])} joined rows belong in it")
    for sid, item in have.items():
        want = [(w["label"], _flat(w["text"]), _flat(w["remark"])) for w in placed.get(sid, [])]
        seen = [(r["label"], _flat(r["text"]), _flat(r["note"])) for r in section_rows(item) if r["label"] in sm.ROW_LABELS]
        if seen != want:
            i = next((k for k, (g, w) in enumerate(zip(seen, want)) if g != w), min(len(seen), len(want)))
            shown = ": ".join(seen[i][:2])[:90] if i < len(seen) else "nothing"
            wanted = ": ".join(want[i][:2])[:90] if i < len(want) else "nothing"
            problems.append(f"{label}: the {sid} section's joined rows differ at row {i + 1} ({len(seen)} on the sheet, "
                            f"{len(want)} from the module): the sheet has {shown!r}, the module {wanted!r}")
    show_first = (data["hail"].get("joins") or {}).get("show_first")
    show_all = ((data["hail"].get("joins") or {}).get("words") or {}).get("show_all")
    if not isinstance(show_first, int) or isinstance(show_first, bool) or show_first < 1:
        problems.append(f"{label}: map.json has no show_first for the sections (hail.joins.show_first)")
    elif not isinstance(show_all, str):
        problems.append(f"{label}: map.json has no 'Show all' words (hail.joins.words.show_all)")
    else:
        for sid, item in have.items():
            total, shown, more = len(section_rows(item)), len(item.get("rows") or []), item.get("more")
            if shown != min(total, show_first):
                problems.append(f"{label}: the {sid} section shows {shown} rows before 'Show all', the rule is "
                                f"{min(total, show_first)} of {total}")
            if total > show_first and not more:
                problems.append(f"{label}: the {sid} section has {total} rows and no 'Show all' control")
            elif total > show_first and more.get("summary") != show_all.format(n=total):
                problems.append(f"{label}: the {sid} 'Show all' control reads {more.get('summary')!r}, the words give "
                                f"{show_all.format(n=total)!r}")
            elif total <= show_first and more:
                problems.append(f"{label}: the {sid} section has a 'Show all' control for {total} rows")
    text = _flat(" ".join([got.get("text") or ""] + list(got.get("notices") or [])))
    for sec in expected["sections"]:
        for line in sec.get("lines") or []:
            if _flat(line) not in text:
                problems.append(f"{label}: the sheet lacks the line {line[:70]!r} of the {sec['id']} part")
        if sec.get("unavailable") and _flat(sec["unavailable"]) not in text:
            problems.append(f"{label}: the sheet lacks the {sec['id']} part's unavailable sentence "
                            f"({sec['unavailable'][:70]!r})")
    what = sm.kind_what(town=False)
    for sid, item in have.items():
        notes = [_flat(n) for n in item.get("notes") or []]
        for kind in sorted({r["label"] for r in section_rows(item) if r["label"] in what}):
            if _flat(what[kind]) not in notes:
                problems.append(f"{label}: the {sid} section lacks the sentence for {kind} ({what[kind][:60]!r})")
    return problems


def table_notes_problems(where: str, want: dict, summary: dict | None) -> list[str]:
    """Each note of the table's rows (describe_summary) stands under the table on the sheet (summary.notes), once or more."""
    if not summary:
        return [f"{where}: the sheet's table notes are missing (no summary slot)"]
    shown = [_flat(n) for n in summary.get("notes") or []]
    problems: list[str] = []
    for row in want["table"]["rows"]:
        if row.get("town_only"):
            continue
        for note in row.get("notes") or []:
            if _flat(note) not in shown:
                problems.append(f"{where}: the table's notes lack {_flat(note)[:70]!r} ({row['label']})")
    return problems


def sections_problems(where: str, want: dict, sheet: dict, ids: list[str]) -> list[str]:
    """Each section of the sheet against describe_summary for the same cell (B5 part B2 round 2; D75, D83): its heading and
    its lead exactly; each of its notes (the section's own notes, and the notes of the table rows that the section shows,
    summary.SECTION_KEYS); How this was made's lines; and the roof's groups, each with its name, its lines, its references
    (kind, then text) and its held lines, in order."""
    sm = summary_module()
    have = {item["id"]: item for item in ((sheet.get("sections") or {}).get("items") or [])}
    wants = {s["id"]: s for s in want["sections"]}
    rows = {row["key"]: row for row in want["table"]["rows"]}
    problems: list[str] = []
    for sid in ids:
        item, ws = have.get(sid), wants.get(sid)
        if ws is None:
            problems.append(f"{where}: describe_summary has no {sid} section")
            continue
        if item is None:
            continue                                    # the missing section is named by sheet_order_problems
        if _flat(item["heading"]) != _flat(ws["heading"]):
            problems.append(f"{where}: the {sid} heading on the sheet is {item['heading']!r}, describe_summary's is "
                            f"{ws['heading']!r}")
        if _flat(item["lead"]) != _flat(ws["lead"]):
            problems.append(f"{where}: the {sid} lead on the sheet is {_flat(item['lead'])[:90]!r}, describe_summary's "
                            f"is {_flat(ws['lead'])[:90]!r}")
        wanted = list(ws.get("notes") or [])
        for key in sm.SECTION_KEYS.get(sid, ()):
            if key in rows:
                wanted += [n for n in rows[key].get("notes") or [] if n not in wanted]
        notes = [_flat(n) for n in item["notes"]]
        for note in wanted:
            if _flat(note) not in notes:
                problems.append(f"{where}: the {sid} section lacks its note {_flat(note)[:70]!r}")
    made = have.get("made")
    if made is not None:
        notes = [_flat(n) for n in made["notes"]]
        for line in want["how_made"]:
            if _flat(line) not in notes:
                problems.append(f"{where}: How this was made lacks the line {_flat(line)[:70]!r}")
    roof_item = have.get("roof")
    if roof_item is not None and wants.get("roof") is not None:
        roof = want["roof"]
        notes = [_flat(n) for n in roof_item["notes"]]
        for line in roof.get("how_made") or []:
            if _flat(line) not in notes:
                problems.append(f"{where}: the roof section lacks its line {_flat(line)[:70]!r}")
        names_have = [_flat(g["name"]) for g in roof_item["groups"]]
        names_want = [_flat(g["name"]) for g in roof["groups"]]
        if names_have != names_want:
            problems.append(f"{where}: the roof groups on the sheet are {names_have}, describe_summary's are {names_want}")
        for g, d in zip(roof["groups"], roof_item["groups"]):
            parts = (("lines", [_flat(x["text"]) for x in g["lines"]], [_flat(x) for x in d["lines"]]),
                     ("references", [_flat(f"{x['kind']}: {x['text']}") for x in g["references"]],
                      [_flat(x) for x in d["refs"]]),
                     ("held lines", [_flat(x["text"]) for x in g["held"]], [_flat(x) for x in d["held"]]))
            for what, wantl, havel in parts:
                if wantl != havel:
                    i = next((k for k, (a, b) in enumerate(zip(havel, wantl)) if a != b), min(len(havel), len(wantl)))
                    shown = havel[i][:70] if i < len(havel) else "nothing"
                    wanted_one = wantl[i][:70] if i < len(wantl) else "nothing"
                    problems.append(f"{where}: the roof group {g['name']!r} shows its {what} differently at line {i + 1}: "
                                    f"the sheet has {shown!r}, describe_summary {wanted_one!r}")
    return problems


def sheet_checks(where: str, want: dict | None, sheet: dict, ids: list[str], expected: dict | None,
                 data: dict) -> list[str]:
    """The sheet below the table at one spot and one size: the eleven sections in order (always); with the store's words
    (want), the table's notes, each section's heading, lead and notes, How this was made and the roof (sections_problems);
    with the cell's joined rows (expected), those rows (joined_problems)."""
    problems = sheet_order_problems(where, sheet, ids)
    if want is None:
        return problems                                 # no words to compare with: the order and the position still count
    problems += table_notes_problems(where, want, sheet.get("summary"))
    problems += sections_problems(where, want, sheet, ids)
    if expected is not None:
        problems += joined_problems(where, sheet, expected, data)
    return problems


_EVENTS: dict = {}          # the site's events table, read once (joins_expected)
_INDEX: dict = {}           # the store's index, read once (joins_expected)


def joins_expected(root: Path, data: dict, point: tuple[float, float], part: str | None = None) -> dict:
    """The six sections for a cell as the town pages write them (website/joins.py describe_joins), from the built site's
    store copy. The sheet's joined rows must be these rows, in the section each one belongs to (expected_rows_by_section)."""
    hs = hail_store()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from website import joins as jn
    if str(root) not in _INDEX:
        _INDEX[str(root)] = hs.load_index(root)
    index = _INDEX[str(root)]
    if part is not None:       # the same index with one part marked unavailable (check_part_unavailable)
        index = copy.deepcopy(index)
        index[jn.INDEX_KEY]["parts"][part] = "unavailable"
    row, col = hs.cell_for(*point)
    tile = json.loads((root / "hail" / "j" / f"{hs.tile_name(row // hs.TILE, col // hs.TILE)}.json").read_text(encoding="utf-8"))
    built = datetime.fromisoformat(data["built"].replace("Z", "+00:00"))
    if str(root) not in _EVENTS:
        _EVENTS[str(root)] = jn._read_events(root)
    return jn.describe_joins(index, tile, row, col, built, sample=False, store_dir=root,
                             events=_EVENTS[str(root)])


def _flat(text: str) -> str:
    """Whitespace folded to single spaces, as HTML shows it, so a trailing space in the module's text is not a difference."""
    return " ".join(text.split())


NO_REPORT_SECTIONS = ("reports", "records", "detections", "warnings")   # the sections that say "no" for a cell with none


def no_join_spot(root: Path, data: dict, budget: int = 4000):
    """A Montana cell (a key of its tile's state list) with no report, record, detection or warning within the module's
    radii: the first one found in the store's tiles, or None after `budget` cells. Its sections come from the module."""
    hs = hail_store()
    tested = 0
    for name in listed_tiles(data)[::23]:                     # spread over the state; the first tiles are zone-covered
        if not (root / "hail" / "j" / f"{name}.json").is_file():
            continue
        tr, tc = int(name[1:5]), int(name[7:11])
        for key in hail_shard(root, name)["state"][::33]:
            if tested >= budget:
                return None
            tested += 1
            point = hs.cell_centre(tr * 10 + key // 10, tc * 10 + key % 10)
            words = joins_expected(root, data, point)
            if not any(sec["rows"] for sec in words["sections"] if sec["id"] in NO_REPORT_SECTIONS):
                return point
    return None


def check_joins(browser, base: str, root: Path, data: dict, shots: Path | None) -> list[str]:
    """The joined rows of the sheet in Chromium at 1280 and 390 px (B2 gates 1, 5 and 7; D82(d), D83): on the gate cell (797,
    1986) the eleven sections come in their fixed order, the Utica 1.0 in report of Jun 14, 2025 at 11:45 pm is on the sheet
    and so is a TFX warning; Benchland's own cell shows its 1.75 in report at 2:10 pm on Jun 15, 2025; each section's joined
    rows, with their labels, words and remarks, are the module's (joined_problems); each of the eleven sections of a sample
    build carries the sample label (check_sample_labels); and no page scrolls sideways on the phone. The part checks
    (check_part_unavailable, check_station_unavailable, check_zone_unavailable, check_cross_day_end) follow."""
    problems: list[str] = []
    loading = data["hail"]["words"]["loading"]
    ids = section_ids(data)
    if data["hail"]["joins"].get("state") == "unavailable":      # a store without the records (the published asset before
        words = data["hail"]["joins"]["words"]                   # the joins step has run): every part says so in the module's
        for label, size in HAIL_SIZES:                           # own sentence (D20) and nothing else, and the page throws
            ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})   # nothing (the preview of 2026-10-19)
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            try:
                hail_open(page, base, hail_at(HAIL_GATE))
                sheet_settled(page, loading, 20)
                sheet = sheet_read(page, ids)
                shown = sheet.get("sections") or {}
                text = _flat(" ".join([shown.get("text") or ""] + list(shown.get("notices") or [])))
                for key in JOIN_SECTIONS:
                    sentence = words["unavailable"].format(part=words["part_" + key], one=words["one_" + key])
                    if _flat(sentence) not in text:
                        problems.append(f"{label}: the {key} part does not say its records are unavailable")
                if errors:
                    problems.append(f"{label}: script error: " + "; ".join(errors[:3]))
            finally:
                ctx.close()
        return problems
    for label, size in HAIL_SIZES:
        ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
        try:
            hail_open(page, base, hail_at(HAIL_GATE))
            sheet_settled(page, loading, 20)
            sheet = sheet_read(page, ids)
            problems += sheet_order_problems(f"{label} gate", sheet, ids)
            problems += check_sample_labels(sheet, data, f"{label} gate")
            problems += joined_problems(f"{label} gate", sheet, joins_expected(root, data, HAIL_GATE), data)
            text = _flat((sheet.get("sections") or {}).get("text") or "")
            if GATE_UTICA_DAY not in text or GATE_UTICA_TIME not in text:
                problems.append(f"{label}: the gate cell's reports lack the Utica report at {GATE_UTICA_TIME} on {GATE_UTICA_DAY}")
            if not any(r["label"] == "Warning" and GATE_OFFICE in r["text"] for r in sheet_rows(sheet)):
                problems.append(f"{label}: the gate cell's warnings lack a {GATE_OFFICE} warning")
            spot = no_join_spot(root, data)
            if spot is None:    # no tile of the real store is empty; the sample build holds one and checks these words
                pass
            else:
                hail_open(page, base, hail_at(spot))
                sheet_settled(page, loading, 20)
                empty = sheet_read(page, ids)
                problems += joined_problems(f"{label} no-join", empty, joins_expected(root, data, spot), data)
            snap(page, shots, f"joins-gate-{label}.png")
            hail_open(page, base, hail_at(HAIL_CELL_CENTRE))
            sheet_settled(page, loading, 20)
            bench = sheet_read(page, ids)
            problems += joined_problems(f"{label} Benchland", bench, joins_expected(root, data, HAIL_CELL_CENTRE), data)
            bench_text = _flat((bench.get("sections") or {}).get("text") or "")
            if "1.75" not in bench_text or BENCHLAND_TIME not in bench_text or BENCHLAND_DAY not in bench_text:
                problems.append(f"{label}: Benchland's own cell lacks the 1.75 in report at {BENCHLAND_TIME} on {BENCHLAND_DAY}")
            if label == "phone" and page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth"):
                problems.append("phone: the sheet makes the page scroll sideways")
            problems += [f"{label}: {e}" for e in errors]
        finally:
            ctx.close()
    problems += check_part_unavailable(browser, base, root, data)
    problems += check_station_unavailable(browser, base, root, data)
    problems += check_zone_unavailable(browser, base, root, data)
    problems += check_cross_day_end(browser, base, root, data)
    return problems


PART_UNAVAILABLE = "reports"     # the part the unavailable check marks as not loaded


def check_part_unavailable(browser, base: str, root: Path, data: dict) -> list[str]:
    """A part the build marks unavailable shows its own sentence and none of its rows, as describe_joins writes it; the other
    sections keep their rows (browser-1, D2). The map's data file is answered with that part marked unavailable, and the
    module's words come from the same index with the same mark (joined_problems). The store on disk is not changed."""
    problems: list[str] = []
    loading = data["hail"]["words"]["loading"]
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"script error: {e}"))

    def mark_unavailable(route):
        response = route.fetch()
        doc = response.json()
        doc["hail"]["joins"]["parts"][PART_UNAVAILABLE] = "unavailable"
        route.fulfill(status=200, content_type="application/json", body=json.dumps(doc))

    page.route("**/data/map.json*", mark_unavailable)
    try:
        hail_open(page, base, hail_at(HAIL_GATE))
        sheet_settled(page, loading, 20)
        sheet = sheet_read(page, section_ids(data))
        expected = joins_expected(root, data, HAIL_GATE, PART_UNAVAILABLE)
        sentence = next(sec["unavailable"] for sec in expected["sections"] if sec["id"] == PART_UNAVAILABLE)
        if not sentence:
            problems.append(f"the module writes no unavailable sentence for the {PART_UNAVAILABLE} part")
        problems += joined_problems("unavailable part", sheet, expected, data)
        problems += [f"unavailable part: {e}" for e in errors]
    finally:
        ctx.close()
    return problems


def check_sample_labels(sheet: dict, data: dict, label: str) -> list[str]:
    """Each of the eleven sections of a sample build says the build's sample word, and no section of a store build says it
    (browser-4, D82): the word is in each section's text, the rows behind 'Show all' included. The sheet's own tag above the
    sections is not counted."""
    joins = data["hail"]["joins"]
    word, sample = joins["words"]["sample"], joins.get("state") == "sample"
    have = {item["id"]: item for item in ((sheet.get("sections") or {}).get("items") or [])}
    problems: list[str] = []
    for sid in section_ids(data):
        if sid not in have:
            problems.append(f"{label}: the {sid} section is missing, so its sample label cannot be checked")
            continue
        text = _flat(have[sid]["text"])
        if sample and word not in text:
            problems.append(f"{label}: the {sid} section of a sample build does not say {word!r}")
        if not sample and word in text:
            problems.append(f"{label}: the {sid} section of a store build says {word!r}")
    return problems


def check_station_unavailable(browser, base: str, root: Path, data: dict) -> list[str]:
    """A station file that does not load (browser-1, D27): the first station file the sheet asks for is refused, in a browser
    context of its own. The stations part then shows its unavailable sentence and none of its rows, and the other rows keep
    what the module writes for them. The module's words come from the same index with the stations part marked unavailable
    (joins_expected), which is how describe_joins writes a part that did not load."""
    problems: list[str] = []
    if data["hail"]["joins"].get("state") == "unavailable":     # a store without the records has no station file to fail
        return problems
    loading = data["hail"]["words"]["loading"]
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
    refused: list[str] = []

    def refuse_first_station(route):
        if not refused:
            refused.append(route.request.url)
            return route.abort()
        return route.continue_()

    page.route("**/hail/s/**", refuse_first_station)
    try:
        hail_open(page, base, hail_at(HAIL_GATE))
        sheet_settled(page, loading, 20)
        sheet = sheet_read(page, section_ids(data))
        if not refused:
            problems.append("the station check refused no station file: the gate cell asked for none")
        problems += joined_problems("station file", sheet, joins_expected(root, data, HAIL_GATE, "stations"), data)
        problems += [f"station file: {e}" for e in errors]
    finally:
        ctx.close()
    return problems


HAIL_CROSS_DAY_CENTRE = (48.985, -110.955)   # the centre of cell (601, 1904): a warning that ends on the next Montana day


def gate_zone(root: Path, point: tuple[float, float]) -> str | None:
    """The forecast zone code of the cell at a point, from its tile's zone map (None when the cell has none)."""
    hs = hail_store()                       # puts the repository on sys.path before the website package is imported
    from website import joins as jn
    row, col = hs.cell_for(*point)
    tile = json.loads((root / "hail" / "j" / f"{hs.tile_name(row // hs.TILE, col // hs.TILE)}.json").read_text(encoding="utf-8"))
    return jn._zone_for_key(tile, hs.cell_key(row, col))


def zone_lost_expected(root: Path, data: dict, point: tuple[float, float], zone: str) -> dict:
    """The six sections for a point as describe_joins writes them when the zone's file did not load: the same store with
    that one file left out of a copy (the copy holds the store's j, s and z folders, and the index; the zone is removed
    from the copy's z folder). The copy is made here and removed here."""
    copied = Path(tempfile.mkdtemp(prefix="hailwatch-zone-"))
    try:
        (copied / "hail").mkdir()
        shutil.copy(root / "hail" / "index.json", copied / "hail" / "index.json")
        for part in ("j", "s", "z"):
            shutil.copytree(root / "hail" / part, copied / "hail" / part)
        (copied / "hail" / "z" / f"{zone}.json").unlink()
        return joins_expected(copied, data, point)
    finally:
        shutil.rmtree(copied, ignore_errors=True)


def check_zone_unavailable(browser, base: str, root: Path, data: dict) -> list[str]:
    """A zone file that does not load (D27): the gate cell's forecast zone file is refused in a browser context of its own.
    The zone part's sentence and its rows give way to the module's: the module's words come from describe_joins on a copy of
    the store without that zone file (zone_lost_expected, joined_problems). The fire weather zone's file is not refused."""
    problems: list[str] = []
    if data["hail"]["joins"].get("state") == "unavailable":     # a store without the records has no zone file to fail
        return problems
    zone = gate_zone(root, HAIL_GATE)
    if not zone:
        return ["the zone check: the gate cell has no forecast zone to refuse"]
    loading = data["hail"]["words"]["loading"]
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
    refused: list[str] = []

    def public_zone_file(url: str) -> bool:
        return "/hail/z/" in url and "/hail/z/fire-" not in url

    def refuse_first_zone(route):
        if not refused:
            refused.append(route.request.url)
            return route.abort()
        return route.continue_()

    page.route(public_zone_file, refuse_first_zone)
    try:
        hail_open(page, base, hail_at(HAIL_GATE))
        sheet_settled(page, loading, 20)
        sheet = sheet_read(page, section_ids(data))
        if not refused:
            problems.append("the zone check refused no zone file: the gate cell asked for none")
        problems += joined_problems("zone file", sheet, zone_lost_expected(root, data, HAIL_GATE, zone), data)
        problems += [f"zone file: {e}" for e in errors]
    finally:
        ctx.close()
    return problems


def check_cross_day_end(browser, base: str, root: Path, data: dict) -> list[str]:
    """A warning that ends on a later Montana day shows that day with its end time on the sheet, as the town table does
    (rules-6, D13). The cell's expected rows with such an end must all be on the sheet. A build that does not hold the
    cell's tile (a sample build holds three) gets a note and no check, as no_join_spot skips such tiles (F-08)."""
    hs = hail_store()
    row, col = hs.cell_for(*HAIL_CROSS_DAY_CENTRE)
    name = hs.tile_name(row // hs.TILE, col // hs.TILE)
    if not (root / "hail" / "j" / f"{name}.json").is_file():
        return [f"{NOTE}the cross-day check did not run: this build holds no record file for tile {name}"]
    loading = data["hail"]["words"]["loading"]
    expected = joins_expected(root, data, HAIL_CROSS_DAY_CENTRE)
    warn = next(sec for sec in expected["sections"] if sec["id"] == "warnings")
    cross = [r["text"] for r in warn["rows"] if re.search(r" to [A-Z][a-z]{2} \d{1,2}, \d{4} ", r["text"])]
    if not cross:
        return [f"the cross-day check found no warning ending on a later day at {HAIL_CROSS_DAY_CENTRE}"]
    problems: list[str] = []
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    try:
        hail_open(page, base, hail_at(HAIL_CROSS_DAY_CENTRE))
        sheet_settled(page, loading, 20)
        shown = {_flat(f"{r['label']}: {r['text']}") for r in sheet_rows(sheet_read(page, section_ids(data)))}
        for row in cross:
            if _flat(row) not in shown:
                problems.append(f"the sheet lacks the cross-day row {row[:90]!r}")
    finally:
        ctx.close()
    return problems


# ---------------------------------------------------------------- the address, street and outline layers (B3)

# The browser's test hook (map.js, window.hailMapTest; test only, documented there): shards(), dots() -> {buildings,
# addresses} drawn by the last redraw, labels(), counts(), lines() (road lines drawn), fetches() (URLs requested since
# reset()), draws() (redraw times in ms since reset()), reset(), view(lat, lon, zoom), pan(dx, dy), zoom(), hits(),
# state() -> {roads, bld, adr, zoom, textOn, searchOn, tap, minZoom, maxZoom, ...}.
B3_BILLINGS = (45.7857, -108.5071)       # the centre of the Billings view the checks use (401 North 27th Street)
B3_STREET = {"line": "401 North 27th Street", "city": "Billings", "zip": "59101", "at": (45.78566, -108.50717)}
B3_ROUNDUP = {"line": "500 Colony Road", "city": "Roundup", "zip": "59072", "at": (46.71750, -108.50031)}
ADDRESS_GATE_ZOOM = 15                   # the zoom at which the dots, the local streets and the budget are measured
# bytes of gzip: 650 KiB (650 * 1024). The brief says "650 KB"; the unit is for the supervisor to confirm. The budget is
# asserted on the B3 files plus the shell (the page without the precipitation frames, which predate B3). The precipitation
# layer is listed apart on the note line, which splits the whole page by part (D30, D48).
ADDRESS_FETCH_BUDGET_GZIP = 650 * 1024
# The map's line for the address list (build.py, D44). The smoke's own expectation, so a map.json without the line fails
# here (R-03, R-13); the line is checked on the rendered page, like the others.
ADDRESS_ATTRIBUTION_START = "Addresses: Montana State Library"
ADDRESS_DRAW_MS = 30                     # milliseconds per redraw at zoom 15 and 16 (D30)
PAN_FETCH_LIMIT = 20                     # fetches across a pan over Billings at zoom 15 (D30)
B3_SEARCHES = (("401 N 27th St Billings", "rows", B3_STREET["line"] + ", " + B3_STREET["city"] + " " + B3_STREET["zip"], "Billings"),
               ("27th Billings", "list", None, "Billings"),
               ("Colony Rd Roundup", "rows", B3_ROUNDUP["line"] + ", " + B3_ROUNDUP["city"] + " " + B3_ROUNDUP["zip"], "Roundup"),
               ("qwzx 99", "none", None, "Billings"))
READY = "() => !!(window.hailMapTest && window.hailMapTest.state)"
ADDRESS_LIKE = re.compile(r"\b\d{1,5} (?:[NSEW]|North|South|East|West) ?\w+ (?:Street|Road|Avenue|Drive|Lane|Court|"
                          r"Highway|Boulevard|Way|Trail|Loop|Circle|Place|Parkway|Terrace|Square)\b", re.I)


def b3_kind(url: str) -> str:
    """Which B3 file a request is for: road, outline, address, search, count, or other (not a B3 file). The browser asks
    with paths relative to the page, so the path is read with a leading slash either way."""
    path = "/" + urlsplit(url).path.lstrip("/")
    if "/hail/r/" in path:
        return "road"
    if "/hail/b/" in path:
        return "outline"
    if "/hail/a/idx/" in path:
        return "search"
    if "/hail/a/" in path:
        return "address"
    if path.endswith("/hail/counts.json"):
        return "count"
    return "other"


def response_part(url: str) -> str:
    """Which part of the page a response belongs to, for the budget's split: the B3 files (b3_kind), the precipitation
    frames (map/frames/) or the shell and data (the page, its scripts and styles, the map data and the basemap)."""
    if b3_kind(url) != "other":
        return "B3 files"
    if "/map/frames/" in "/" + urlsplit(url).path.lstrip("/"):
        return "precipitation frames"
    return "shell and data"


def b3_open(browser, base: str, width: int, height: int, allow: tuple = (), listen=None):
    """A new page on the map with the hook ready. Returns (context, page); a page with no hook fails here. allow: the
    URL prefixes this page may request without counting (the imagery host, after a switch to Imagery). listen: called
    with every response, from before the first request, so a budget counts the whole load."""
    ctx = browser.new_context(allow=allow, viewport={"width": width, "height": height})
    page = ctx.new_page()
    if listen is not None:
        page.on("response", listen)
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_function(READY, timeout=15000)
    return ctx, page


def b3_view(page, lat: float, lon: float, zoom: float, settle_ms: int = 1500) -> dict:
    """Reset the hook, move the map to a view, wait for the redraw, and return what the hook reports for it."""
    page.evaluate("([la, lo, z]) => { window.hailMapTest.reset(); window.hailMapTest.view(la, lo, z); }", [lat, lon, zoom])
    page.wait_for_timeout(settle_ms)
    return page.evaluate("""() => { const h = window.hailMapTest; const d = h.dots();
        return {fetched: h.fetches(), buildings: d.buildings, addresses: d.addresses, labels: h.labels(),
                counts: h.counts(), lines: h.lines(), draws: h.draws(), zoom: h.zoom()}; }""")


def b3_kinds(urls) -> set[str]:
    return {b3_kind(url) for url in urls} - {"other"}


def b3_records(root: Path, lat: float, lon: float) -> tuple[list, list, list]:
    """The records the site's own shard files hold for the B1 tile of a point: outlines with address lines, outlines
    with none, and unmatched address rows. Read from the built files, so the taps aim at real records."""
    from website import hail as hs
    row, col = hs.cell_for(lat, lon)
    tile = hs.tile_name(row // hs.TILE, col // hs.TILE)
    outlines, bare, rows = [], [], []
    for path in sorted((root / "hail" / "b").glob(f"{tile}*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("a", []):
            if "l" in entry:
                zs = entry.get("z") or [None] * len(entry["l"])
                common = doc.get("c") or ["", ""]
                lines = [{"line": line, "city": (z or common)[0], "zip": (z or common)[1]} for line, z in zip(entry["l"], zs)]
                outlines.append({"lat": entry["p"][1], "lon": entry["p"][0], "lines": lines})
            else:
                bare.append({"lat": entry["p"][1], "lon": entry["p"][0]})
    for path in sorted((root / "hail" / "a").glob(f"{tile}*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for row_ in doc.get("a", []):
            if row_[5] != "S" and row_[2]:
                rows.append({"lon": row_[0], "lat": row_[1], "lines": [{"line": row_[2], "city": row_[3], "zip": row_[4]}],
                             "letter": row_[5]})
    return outlines, bare, rows


def tap_centre(page, lat: float, lon: float) -> None:
    """Centre the map on a point and tap the middle of the map: the dot at that point is the nearest one (D7)."""
    page.evaluate("([la, lo]) => window.hailMapTest.view(la, lo, 17)", [lat, lon])
    page.wait_for_timeout(1300)
    box = page.locator("#map").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(1500)


def sheet_text(page) -> str:
    return page.evaluate("() => { const s = document.getElementById('sheet'); return s && !s.hidden ? s.innerText : ''; }")


def close_sheet(page) -> None:
    if page.locator("#sheet-close").count() and page.locator("#sheet:not([hidden])").count():
        page.click("#sheet-close")
    page.wait_for_timeout(300)


def check_zoom_rules(browser, base: str, data: dict) -> list[str]:
    """The zoom rules over Billings (D27, D30): nothing B3 at 12; the arterials and the count bubbles at 13 with no
    outline file fetched; the local streets, the outline dots and the unmatched address dots at 15, with no street names;
    the street names at 16; each redraw at 15 and 16 under the draw budget. A layer the build did not load is not checked."""
    problems: list[str] = []
    roads_ok = data["hail"]["roads"].get("state") == "loaded"
    outlines_ok = data["hail"]["buildings"].get("state") == "loaded"
    addr_ok = data["hail"]["addresses"].get("state") in ("loaded", "sample")
    ctx, page = b3_open(browser, base, 1280, 800)
    rows = {}
    lat, lon = B3_BILLINGS
    for zoom in (12, 13, 15, 16):
        state = b3_view(page, lat, lon, zoom)
        kinds = sorted(b3_kinds(state["fetched"]))
        if zoom in (15, 16):
            # seven more redraws of the same view (the hook's redraws: a 1 px pan and a draw each), so the budget
            # is checked on several draws, not on the one the view made
            state["draws"] = page.evaluate("() => window.hailMapTest.redraws(7)")
        ordered = sorted(state["draws"])
        rows[zoom] = {"fetched": kinds, "arterial_lines": state["lines"], "outline_dots": state["buildings"],
                      "address_dots": state["addresses"], "counts": state["counts"], "names": state["labels"],
                      "draw_ms": {"n": len(ordered), "min": round(ordered[0], 1), "median": round(ordered[len(ordered) // 2], 1),
                                  "max": round(ordered[-1], 1)} if ordered else None}
        if zoom == 12 and (kinds or state["lines"] or state["buildings"] or state["addresses"] or state["counts"]):
            problems.append(f"zoom 12 over Billings fetched {kinds} and drew B3 features; nothing B3 shows at 12 (D27)")
        if zoom == 13:
            if any("/hail/b/" in url for url in state["fetched"]):
                problems.append("zoom 13 fetched an outline shard; outlines start at zoom 15 (D27)")
            if state["buildings"] or state["addresses"]:
                problems.append("zoom 13 drew outline or address dots; they start at zoom 15 (D27)")
            if roads_ok and not state["lines"]:
                problems.append("zoom 13 drew no arterial roads over Billings")
            if outlines_ok and not state["counts"]:
                problems.append("zoom 13 drew no count bubbles over Billings")
        if zoom == 15:
            if roads_ok and not state["lines"]:
                problems.append("zoom 15 drew no local streets over Billings")
            if outlines_ok and not state["buildings"]:
                problems.append("zoom 15 drew no building outline dots over Billings")
            if addr_ok and not state["addresses"]:
                problems.append("zoom 15 drew no unmatched address dots over Billings")
            if state["labels"]:
                problems.append(f"zoom 15 drew {state['labels']} street names; names start at zoom 16 (D27)")
        if zoom == 16:
            if roads_ok and not state["labels"]:
                problems.append("zoom 16 drew no street names over Billings")
        if zoom in (15, 16) and state["draws"] and max(state["draws"]) >= ADDRESS_DRAW_MS:
            problems.append(f"a redraw at zoom {zoom} took {max(state['draws']):.1f} ms (budget {ADDRESS_DRAW_MS})")
    ctx.close()
    problems.append(f"note: zoom rules over Billings: {rows}")
    return problems


def check_budget_and_pan(browser, base: str) -> list[str]:
    """A 390 px phone view of Billings at zoom 15 fetches under the gzip budget (D30), counted on the B3 files (the note
    gives the whole page split by part), and a pan across Billings at zoom 15 makes fewer than PAN_FETCH_LIMIT requests,
    all to this site, with every redraw under the draw budget."""
    problems: list[str] = []
    lat, lon = B3_BILLINGS
    seen: list = []
    ctx, page = b3_open(browser, base, 390, 844, listen=lambda r: seen.append(r))    # every response, from the first request
    b3_view(page, lat, lon, ADDRESS_GATE_ZOOM, settle_ms=2500)
    sizes = {"shell and data": 0, "precipitation frames": 0, "B3 files": 0}
    counts = {"shell and data": 0, "precipitation frames": 0, "B3 files": 0}
    unread = 0
    for response in seen:
        part = response_part(response.url)
        try:
            size = len(gzip.compress(response.body(), 6))
        except Exception:                                                  # noqa: BLE001 - reported below
            unread += 1
            continue
        sizes[part] += size
        counts[part] += 1
    total = sum(sizes.values())
    if unread:
        problems.append(f"{unread} responses could not be read to measure them")
    b3_and_shell = sizes["B3 files"] + sizes["shell and data"]          # the budget's scope (D30, D48)
    if b3_and_shell >= ADDRESS_FETCH_BUDGET_GZIP:
        problems.append(f"the B3 files and the shell of a 390 px Billings view at zoom {ADDRESS_GATE_ZOOM} fetched "
                        f"{b3_and_shell} bytes gzip; the budget is {ADDRESS_FETCH_BUDGET_GZIP}")
    problems.append(f"note: 390 px Billings view at zoom {ADDRESS_GATE_ZOOM}: the B3 files plus the shell {b3_and_shell} bytes "
                    f"gzip against the budget of {ADDRESS_FETCH_BUDGET_GZIP} (B3 files {sizes['B3 files']} in "
                    f"{counts['B3 files']} files; shell and data {sizes['shell and data']} in {counts['shell and data']} "
                    f"files); the precipitation frames {sizes['precipitation frames']} bytes gzip in "
                    f"{counts['precipitation frames']} files, a layer that predates B3, listed apart (page total {total})")
    ctx.close()

    ctx, page = b3_open(browser, base, 1280, 800)
    b3_view(page, lat, lon, ADDRESS_GATE_ZOOM)
    page.evaluate("() => window.hailMapTest.reset()")
    for dx, dy in ((300, 0), (300, 0), (-300, 300), (-300, 0), (0, -300), (600, 0)):
        page.evaluate("([x, y]) => window.hailMapTest.pan(x, y)", [dx, dy])
        page.wait_for_timeout(1200)
    urls = page.evaluate("() => window.hailMapTest.fetches()")
    draws = page.evaluate("() => window.hailMapTest.draws()")
    if any(url.startswith(("http://", "https://")) and not url.startswith(base) for url in urls):
        problems.append("the pan asked for a B3 file from another site")
    if len(urls) >= PAN_FETCH_LIMIT:
        problems.append(f"a pan across Billings at zoom {ADDRESS_GATE_ZOOM} made {len(urls)} requests; the limit is "
                        f"{PAN_FETCH_LIMIT}")
    if draws and max(draws) >= ADDRESS_DRAW_MS:
        problems.append(f"a redraw while panning took {max(draws):.1f} ms (budget {ADDRESS_DRAW_MS})")
    problems.append(f"note: pan across Billings at zoom {ADDRESS_GATE_ZOOM}: {len(urls)} requests "
                    f"({', '.join(urlsplit(u).path.split('/hail/')[-1] for u in urls)}); redraws ms "
                    f"{[round(ms, 1) for ms in draws]}")
    ctx.close()
    return problems


def check_taps(browser, base: str, root: Path, data: dict, off: bool) -> list[str]:
    """A tap on an outline's dot opens the hail sheet with its address line on top (or, for an outline with no address,
    the no-address sentence and no address line), and the hail history under it. A tap on an unmatched address dot shows
    its address line and its placement sentence. In the off mode no address text shows, and the dots still open."""
    problems: list[str] = []
    words = data["hail"]["buildings"]["templates"]
    placed = data["hail"]["addresses"]["templates"]["placed_how"]
    outlines, bare, rows = b3_records(root, B3_BILLINGS[0], B3_BILLINGS[1])
    ctx, page = b3_open(browser, base, 1280, 800)
    # the outline taps need the outline layer: a build without it has no outline records to tap, which is not a failure
    # (as in check_zoom_rules, a layer the build did not load is not checked); its note says so
    outlines_loaded = data["hail"]["buildings"].get("state") == "loaded"
    if not outlines_loaded:
        problems.append("note: the outline taps are not checked: this build did not load the building outlines")
    if off:
        target = (outlines + bare)[:1]
        if not target and outlines_loaded:
            problems.append("off mode: no outline in the Billings tile to tap")
        for dot in target:
            tap_centre(page, dot["lat"], dot["lon"])
            text = sheet_text(page)
            if ADDRESS_LIKE.search(text):
                problems.append("off mode: a dot's sheet shows an address line")
            if "hail" not in text.lower():
                problems.append("off mode: a dot's sheet has no hail history")
            close_sheet(page)
        ctx.close()
        return problems
    if not outlines and outlines_loaded:
        problems.append("no outline with an address is in the Billings tile's shard files")
    if outlines:
        dot = outlines[0]
        tap_centre(page, dot["lat"], dot["lon"])
        text = sheet_text(page)
        first = dot["lines"][0]
        line = f"{first['line']}, {first['city']} {first['zip']}"
        if line not in "\n".join(text.split("\n")[:4]):
            problems.append(f"an outline's sheet does not show its address line {line!r} on top")
        if "hail" not in text.lower():
            problems.append("an outline's sheet has no hail history under it")
        close_sheet(page)
    if bare:
        dot = bare[0]
        tap_centre(page, dot["lat"], dot["lon"])
        text = sheet_text(page)
        if words["no_address"] not in text:
            problems.append("an outline with no address does not say so in words")
        if ADDRESS_LIKE.search(text):
            problems.append("an outline with no address shows an address line")
        close_sheet(page)
    if rows:
        dot = rows[0]
        tap_centre(page, dot["lat"], dot["lon"])
        text = sheet_text(page)
        first = dot["lines"][0]
        line = f"{first['line']}, {first['city']} {first['zip']}"
        if line not in "\n".join(text.split("\n")[:4]):
            problems.append(f"an unmatched address dot's sheet does not show its address line {line!r} on top")
        how = placed.get(dot["letter"], "")
        if how and words["placed"].format(how=how) not in text:
            problems.append("an unmatched address dot's sheet does not say how the point was placed")
        close_sheet(page)
    ctx.close()
    return problems


def check_attribution(browser, base: str, data: dict) -> list[str]:
    """The address, roads and outline lines are on the first screen at 390 px (D29, D44): in the map's key list or in the
    Leaflet attribution control. The lines map.json names are checked, and the address line is expected whenever the
    address list loaded (the smoke's own expectation, ADDRESS_ATTRIBUTION_START, not map.json's list: R-13). The line each
    source takes is reported."""
    problems: list[str] = []
    lines = list(data["hail"].get("attribution") or [])
    if data["hail"]["addresses"].get("state") in ("loaded", "sample") and \
            not any(line.startswith(ADDRESS_ATTRIBUTION_START) for line in lines):
        problems.append(f"map.json's attribution lists no address line ({ADDRESS_ATTRIBUTION_START!r} is expected)")
    if data["hail"]["addresses"].get("state") in ("loaded", "sample"):
        lines.append(ADDRESS_ATTRIBUTION_START)
    ctx, page = b3_open(browser, base, 390, 844)
    page.wait_for_timeout(800)
    where = page.evaluate("""() => { const out = {};
        const rendered = el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
        out.keys = [...document.querySelectorAll('#legend-keys .key-line')].map(li => ({text: li.innerText,
            box: li.getBoundingClientRect().toJSON(), shown: rendered(li), where: 'the key list'}));
        out.credits = [...document.querySelectorAll('#legend-note .legend-credit')].map(s => ({text: s.textContent,
            box: s.getBoundingClientRect().toJSON(), shown: rendered(s), where: 'the legend note'}));
        const a = document.querySelector('.leaflet-control-attribution');
        out.control = a ? {text: a.innerText, box: a.getBoundingClientRect().toJSON(), shown: rendered(a),
            where: 'the Leaflet attribution control'} : null;
        out.view = {w: innerWidth, h: innerHeight}; return out; }""")
    for line in lines:
        found = [item for item in where["keys"] + where["credits"] if line[:40] in item["text"]]
        in_control = where["control"] is not None and line[:40] in where["control"]["text"]
        if not found and not in_control:
            problems.append(f"the map does not carry the attribution line {line[:40]!r} (key list, legend note or attribution control)")
            continue
        holder = found[0] if found else where["control"]
        box = holder["box"]
        if not holder["shown"] or box["x"] < 0 or box["x"] + box["width"] > where["view"]["w"] or box["y"] < 0 \
                or box["y"] + box["height"] > where["view"]["h"]:
            problems.append(f"the attribution line {line[:40]!r} is not on the first screen at 390 px "
                            f"(it is in {holder['where']}, which is not shown there)")
        problems.append(f"note: attribution line {line[:40]!r} is in " + holder["where"])
    ctx.close()
    return problems


def check_search(browser, base: str, root: Path, data: dict) -> list[str]:
    """The typed-address search (D6): the four searches of the brief, the rows or the list, the chosen row's zoom and
    sheet, the no-match sentence, and no typed text in any request URL. A search whose city the build's index does not
    hold (a sample build holds four cities) is not run and is named in a note."""
    problems: list[str] = []
    templates = data["hail"]["addresses"]["templates"]
    cities = json.loads((root / "hail" / "a" / "idx" / "cities.json").read_text(encoding="utf-8"))["cities"]
    ctx, page = b3_open(browser, base, 1280, 800)
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    results = {}
    skipped = []
    for typed, want, expect, city in B3_SEARCHES:
        if city not in cities:
            skipped.append(typed)
            continue
        page.fill("#address-input", typed)
        page.press("#address-input", "Enter")
        page.wait_for_timeout(1500)
        items = page.locator("#address-results li").all_inner_texts()
        status = page.locator("#address-status").inner_text() if page.locator("#address-status").count() else ""
        results[typed] = len(items)
        if want == "rows" and not any(expect in item for item in items):
            problems.append(f"search {typed!r} did not list {expect!r} (listed {items[:3]})")
        if want == "list" and len(items) < 2:
            problems.append(f"search {typed!r} listed {len(items)} row(s); a street name alone lists several")
        if want == "none" and (items or templates["search_none"] not in status):
            problems.append(f"search {typed!r} did not give the no-match sentence")
        if want == "rows" and any(expect in item for item in items):
            page.locator("#address-results li button.find-row", has_text=expect).first.click()
            page.wait_for_timeout(1800)
            if expect.split(",")[0] not in "\n".join(sheet_text(page).split("\n")[:4]):
                problems.append(f"choosing {expect!r} did not open its sheet with the address on top")
            if page.evaluate("() => window.hailMapTest.zoom()") < 17:
                problems.append(f"choosing {expect!r} did not zoom to the address (zoom 17)")
            close_sheet(page)
        page.fill("#address-input", "")
    if skipped:
        problems.append(f"note: searches not run (their city is not in this build's index): {skipped}")
    for typed, _, _, _ in B3_SEARCHES:
        for needle in (typed, typed.replace(" ", "%20"), typed.replace(" ", "+")):
            if any(needle in url for url in urls):
                problems.append(f"the typed text {typed!r} appears in a request URL")
                break
    problems.append(f"note: search results listed: {results}")
    ctx.close()
    return problems


def check_address_text_off(browser, base: str) -> list[str]:
    """The off build (D35): no form, no search file requested, and the browser says it holds no address text."""
    problems: list[str] = []
    ctx, page = b3_open(browser, base, 1280, 800)
    if page.locator("#address-input").count():
        problems.append("off mode: the Find an address box is on the page")
    state = page.evaluate("() => window.hailMapTest.state()")
    if state["textOn"] or state["searchOn"]:
        problems.append("off mode: the browser reports address text or a search on")
    b3_view(page, B3_BILLINGS[0], B3_BILLINGS[1], 16, settle_ms=2000)
    urls = page.evaluate("() => window.hailMapTest.fetches()")
    if any(b3_kind(url) == "search" for url in urls):
        problems.append("off mode: a search file was requested")
    ctx.close()
    return problems


def check_addresses(browser, base: str, root: Path, data: dict, shots: Path | None) -> list[str]:
    """The B3 layers on a --hail-addresses build (D30, D35): the zoom rules and the draw budget, the fetch budget and the
    pan, the taps, the attribution on the first screen, the search (or, in the off mode, no search), and the screenshots
    at 390x844 and 1280x800 on the white map and on Imagery."""
    h = data.get("hail", {})
    for key in ("addresses", "roads", "buildings"):
        if key not in h:
            return [f"the build has no {key} layer: build with --hail-addresses"]
    if h["addresses"].get("state") not in ("loaded", "sample"):
        return [f"the address list is {h['addresses'].get('state')}: {h['addresses'].get('problem')}"]
    off = h["addresses"].get("text") == "off"
    problems = check_zoom_rules(browser, base, data)
    problems += check_budget_and_pan(browser, base)
    problems += check_taps(browser, base, root, data, off)
    problems += check_attribution(browser, base, data)
    problems += check_address_text_off(browser, base) if off else check_search(browser, base, root, data)
    for width, height in ((390, 844), (1280, 800)):
        for name in ("map", "imagery"):
            ctx, page = b3_open(browser, base, width, height, allow=(f"https://{IMAGERY_HOST}/",) if name == "imagery" else ())
            if name == "imagery":
                base_choice(page, "imagery")
            b3_view(page, B3_BILLINGS[0], B3_BILLINGS[1], ADDRESS_GATE_ZOOM, settle_ms=2000)
            snap(page, shots, f"b3-{'notext-' if off else ''}{name}-{width}x{height}.png")
            ctx.close()
    return problems


# ---------------------------------------------------------------- the live hail swath layers (B4; --storm-layers builds)

SWATH = (("hail_60", "Hail, last hour", "hail-60", 60), ("hail_1440", "Hail, last 24 hours", "hail-1440", 1440))
MINUTE_MS = 60_000
# a kind of cell in a note or a failure line, in words (browser-17): "a Montana cell with a value" and so on
KIND_WORDS = {"value": "with a value", "none": "without an estimate in a tile that has a live file",
              "missing": "in a tile with no live file"}
GATE_MIN_CHANGED = 16      # D17: the picture changes at least this many pixels in a box around a listed value cell
GATE_MIN_ZOOM = 10         # D17: the cell is looked at from zoom 10 or closer (the map's maximum zoom is 11)
GATE_SPOT_RADIUS = 80      # D17: the count is taken in a box this many screen pixels either side of the spot
GATE_NOTE_PIXELS = 16     # a pixel counts as changed when a colour channel moves by more than this (changed_share)
TICK_MS = 60_000          # the hail layers' state is checked this often (map.js STATE_TICK, D7): once a minute
CLOCK_TIME = re.compile(r"\d{1,2}(?::\d{2})?\s?(?:am|pm)", re.IGNORECASE)   # a clock time as the timeline shows it
SWATH_LINE = "#tl-sub .tl-src"                 # the timeline's subtitle: a hail layer's state line (map.js hailView)
SWATH_LIVE = "[data-live='swath']"             # the sheet's live line (map.js liveOpen)
SWATH_PICTURE = ("layer => [...document.querySelectorAll('img.leaflet-image-layer')].some(i =>"
                 " i.src.includes('/map/frames/' + layer + '-') && parseFloat(getComputedStyle(i).opacity) > 0.99)")
# every picture on the map shown or hidden (visibility: the script's own opacity is left alone)
IMAGES_SHOWN = ("(shown) => document.querySelectorAll('img.leaflet-image-layer').forEach(i =>"
                " { i.style.visibility = shown ? '' : 'hidden'; })")


def swath_module():
    """The swath module's words and cell arithmetic, imported from this repository (the test's own copy of the rule)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from website import swath as sw
    return sw


def swath_ms(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def clock_time(ms: int) -> datetime:
    """A time in milliseconds since the epoch as the fake clock takes it (a datetime, so the unit is not guessed)."""
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def swath_stamp(layer: dict) -> str:
    """The folder of a layer's live files, from its pattern: hail/live/<window>/<stamp>/{tile}.json (D14)."""
    return layer["live"]["pattern"].split("/")[3]


def view_state(layer: dict, now_ms: int) -> tuple[str, str]:
    """The state and the timeline's line a hail layer shows at a time, by the rule the browser follows (D7): fresh up to
    the fresh minutes, stale up to the stale minutes, then unavailable. The line has no clock time (the day clock above
    it is the one time, browser-13). Written here again, so the check does not share the script's code."""
    w = layer["words"]
    pre = w["sample_sheet"] + " " if layer["sample"] else ""      # a sample build's state line begins with its label (D10)
    age_ms = max(0, now_ms - swath_ms(layer["valid"]))
    if age_ms <= layer["fresh_min"] * MINUTE_MS:
        return "fresh", pre + w["timeline_fresh"].format(age=age_ms // MINUTE_MS)
    if age_ms <= layer["stale_min"] * MINUTE_MS:
        return "stale", pre + w["timeline_stale"].format(age=age_ms // MINUTE_MS, limit=layer["fresh_min"])
    problem = w["age_out"].format(age=math.ceil(age_ms / MINUTE_MS), limit=layer["stale_min"])
    return "unavailable", pre + w["unavailable"].format(title=layer["title"], problem=problem)


def live_cells(root: Path, layer: dict) -> list[tuple[int, int, int]]:
    """The cells the layer's live files list (row, column, tenths), in file order: the values at or above the floor."""
    folder = root / "hail" / "live" / str(layer["window"]) / swath_stamp(layer)
    out = []
    for path in sorted(folder.glob("*.json")):
        out += [tuple(cell) for cell in json.loads(path.read_text(encoding="utf-8")).get("cells", [])]
    return out


def value_cell(root: Path, layer: dict):
    """A cell with a value at or above the floor in the layer's live files (inside the picture's box by construction):
    (row, column), or None when the build has none."""
    for row, col, tenths in live_cells(root, layer):
        if tenths >= hail_store().FLOOR_TENTHS:
            return row, col
    return None


def in_montana(root: Path, row: int, col: int) -> bool:
    """Whether a grid cell is a Montana cell, by the store's shard for its tile (the state list)."""
    hs = hail_store()
    path = root / hs.shard_path(row, col)
    return path.is_file() and hs.cell_key(row, col) in json.loads(path.read_text(encoding="utf-8"))["state"]


def swath_spots(root: Path, layer: dict) -> dict:
    """Montana cells for the sheet's live line, from the layer's own files: one with a value (the file lists it), one in
    a tile whose file does not list it (no estimate), and one in a tile with no file (the 404 path, D16). Each is
    (row, col, tile name) or missing from the dict when the build has no such cell."""
    hs = hail_store()
    folder = root / "hail" / "live" / str(layer["window"]) / swath_stamp(layer)
    spots: dict = {}
    files = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))}
    for name, doc in files.items():
        for row, col, _tenths in doc.get("cells", []):
            if "value" not in spots and in_montana(root, row, col):
                spots["value"] = (row, col, name)
        r0, c0 = int(name[1:5]) * 10, int(name[7:11]) * 10     # rNNNN_cNNNN: the tile's first row and column
        listed = {(r, c) for r, c, _t in doc.get("cells", [])} | {tuple(x) for x in doc.get("nocov", [])}
        for row in range(r0, r0 + hs.TILE):
            for col in range(c0, c0 + hs.TILE):
                if "none" not in spots and (row, col) not in listed and in_montana(root, row, col):
                    spots["none"] = (row, col, name)
    for name in sorted(data_tiles(root)):
        if name in files:
            continue
        shard = json.loads((root / "hail" / "t" / f"{name}.json").read_text(encoding="utf-8"))
        if shard["state"]:
            key = shard["state"][0]
            spots.setdefault("missing", (shard["r"] * 10 + key // 10, shard["c"] * 10 + key % 10, name))
        if "missing" in spots:
            break
    return spots


def data_tiles(root: Path) -> list[str]:
    """The tile names the store holds (hail/index.json, the list the browser's tiles come from)."""
    return json.loads((root / "hail" / "index.json").read_text(encoding="utf-8"))["tiles"]


def wait_live(page, loading: str, seconds: float = 15) -> str:
    """The sheet's live line once it has left its loading words ('' when it does not in time)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = page.evaluate(f"() => {{ const n = document.querySelector(\"{SWATH_LIVE}\"); return n ? n.textContent : null; }}")
        if text and text.strip() and loading not in text:       # a sample build's loading line begins with its label
            return text.strip()
        page.wait_for_timeout(150)
    return ""


def check_swath_layers(browser, base, root: Path, data: dict, shots) -> list[str]:
    """Each hail layer on a desktop and a phone: the layer menu picks it and the legend says its title; every class has
    its word on the scale (none thinned) and its colour in the bar; the legend's kind and uncoloured sentences are in view; the
    swatch is painted from the legend; the state line is the fresh line with the age the browser works out; the picture
    is on screen. The pixel gate is check_swath_gate. The page's clock is set to two minutes after the frame, so a build
    older than its stale window is read as fresh here."""
    sw = swath_module()
    problems = []
    for key, title, prefix, window in SWATH:
        L = data["layers"][key]
        if not L["frames"]:
            continue                                  # no picture: check_swath_clock reads its words instead
        for label, size in (("desktop", (1280, 800)), ("phone", (390, 844))):
            ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, reduced_motion="reduce")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
            page.clock.install(time=clock_time(swath_ms(L["valid"]) + 2 * MINUTE_MS))
            page.goto(base + "map.html", wait_until="load")
            page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
            pick_layer(page, title)
            if page.locator("#legend-title").inner_text().strip() != L["title"]:
                problems.append(f"{label}: switching to {title} did not set the legend title")
            stops = " ".join(page.locator("#legend-stops").inner_text().split())
            if page.locator("#legend-stops li").count() != len(L["legend"]):
                problems.append(f"{label}: {title}: the legend shows {page.locator('#legend-stops li').count()} of "
                                f"{len(L['legend'])} classes (every class keeps its word)")
            for entry in L["legend"]:
                if entry["label"] not in stops:
                    problems.append(f"{label}: {title}: the legend lacks {entry['label']!r}")
            # the kind sentence and the uncoloured sentence are in view on this screen, with their words (browser-4)
            for el_id, words in (("legend-note", L["legend_note"]),
                                 ("legend-uncoloured", sw.WORDS_SWATH["uncoloured"].format(window=L["window_word"]))):
                shown = page.locator(f"#{el_id}")
                text = shown.text_content()
                if not shown.is_visible() or words not in text or "{" in text:      # a placeholder left in the text fails
                    problems.append(f"{label}: {title}: #{el_id} is not in view with its words: {text!r}")
            if "rgba(" not in page.evaluate("() => document.getElementById('legend-bar').style.background"):
                problems.append(f"{label}: {title}: the legend bar has no colours")
            painted = page.evaluate(f"() => {{ const s = document.querySelector('#layers .sw-{key}');"
                                    " return s ? getComputedStyle(s).backgroundImage : ''; }")
            if "gradient" not in painted:
                problems.append(f"{label}: {title}: the swatch in the layer menu is not painted from its legend")
            now_ms, line = page.evaluate(f"() => [Date.now(), document.querySelector('{SWATH_LINE}').textContent]")
            state, want = view_state(L, now_ms)
            if line.strip() != want:
                problems.append(f"{label}: {title}: the state line is {line.strip()!r}, not {want!r} ({state})")
            if not picture_on_screen(page, prefix):
                problems.append(f"{label}: {title}: the picture was not drawn")
            # one clock time per frame: the day clock is the time, the line under it has none (browser-13)
            src_text = page.locator("#tl-sub .tl-src").text_content()
            aria = page.locator("#range").get_attribute("aria-valuetext") or ""
            if CLOCK_TIME.search(src_text) or len(CLOCK_TIME.findall(aria)) != 1:
                problems.append(f"{label}: {title}: the timeline has a clock time in its line ({src_text!r}) or does not "
                                f"have exactly one in its value ({aria!r})")
            problems += [f"{label}: {title}: {e}" for e in errors]
            snap(page, shots, f"swath-{key}-{label}.png")
            ctx.close()
    return problems


def check_swath_clock(browser, base, root: Path, data: dict, shots) -> list[str]:
    """The states follow the viewer's clock (D7). The page's clock is moved on with the timers held (Playwright's clock):
    two minutes after the frame, the layer is fresh; past its fresh minutes it is stale (the picture stays, the line
    gives the age and ends with "This is not an all-clear."); past its stale minutes it is unavailable (no picture; the
    line says so). The minute's check moves the line by itself. With the history sheet (--hail-history) and a cell with a
    value, the sheet opens in each state: stale ends with the all-clear sentence, unavailable reads its line and asks for
    no live file."""
    problems = []
    sw = swath_module()
    hs = hail_store() if "hail" in data else None
    for key, title, prefix, window in SWATH:
        L = data["layers"][key]
        if not L["frames"]:
            continue
        valid = swath_ms(L["valid"])
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
        page.clock.install(time=clock_time(valid + 2 * MINUTE_MS))
        page.goto(base + f"map.html?layer={key}", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        page.wait_for_timeout(600)
        stages = (("fresh", 2), ("stale", L["fresh_min"] + 5), ("unavailable", L["stale_min"] + 5))
        elapsed = 2
        for want_state, minutes in stages:
            if minutes > elapsed:
                page.clock.run_for((minutes - elapsed) * MINUTE_MS)
                elapsed = minutes
            now_ms, line = page.evaluate(f"() => [Date.now(), document.querySelector('{SWATH_LINE}').textContent]")
            state, want = view_state(L, now_ms)
            if state != want_state or line.strip() != want:
                problems.append(f"{title}: at {minutes} min the line is {line.strip()!r}, not {want!r} ({want_state})")
            drawn = page.evaluate(SWATH_PICTURE, key.replace("_", "-"))
            if want_state == "unavailable" and drawn:
                problems.append(f"{title}: an unavailable layer still shows its picture")
            if want_state == "stale" and not drawn:
                problems.append(f"{title}: a stale layer lost its picture (it should stay, with its age)")
            if want_state == "stale" and not line.strip().endswith(sw.WORDS_SWATH["all_clear"]):
                problems.append(f"{title}: the stale line does not end with the all-clear sentence")
        problems += [f"{title}: clock: {e}" for e in errors]
        ctx.close()
        if hs is None:
            continue
        spots = swath_spots(root, L)
        if "value" not in spots:
            problems.append(f"{NOTE}{title}: this build has no Montana cell {KIND_WORDS['value']}, so the sheet's live line is not checked")
            continue
        row, col, tile = spots["value"]
        at = hail_at(hs.cell_centre(row, col))
        for want_state, minutes in (("stale", L["fresh_min"] + 5), ("unavailable", L["stale_min"] + 5)):
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            page = ctx.new_page()
            errors: list[str] = []
            live: list = []
            page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
            page.on("response", lambda r: live.append((r.url, r.status)) if "/hail/live/" in r.url else None)
            page.clock.set_fixed_time(clock_time(valid + minutes * MINUTE_MS))   # held still: the age is exact
            page.goto(base + f"map.html?layer={key}&at={at}", wait_until="load")
            page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
            text = wait_live(page, L["words"]["live_loading"])
            state, line = view_state(L, valid + minutes * MINUTE_MS)
            if want_state == "stale":
                want = sw.sheet_line(window, hs_tenths(root, L, row, col), datetime.fromtimestamp(valid / 1000, timezone.utc),
                                     "stale", None, sample=L["sample"])
                if text != want:
                    problems.append(f"{title}: the stale sheet's live line is {text!r}, not {want!r}")
                if len([u for u, _s in live if u.endswith(f"/{tile}.json")]) != 1:
                    problems.append(f"{title}: the stale sheet did not read its tile once ({len(live)} live requests)")
            else:
                if text != line:
                    problems.append(f"{title}: the unavailable sheet's live line is {text!r}, not {line!r}")
                # D16: the file is read and its outcome is mapped by the state (a 404 or a value gives the unavailable line)
                if len([u for u, _s in live if u.endswith(f"/{tile}.json")]) != 1:
                    problems.append(f"{title}: the unavailable sheet did not read its tile once ({len(live)} live requests)")
            problems += [f"{title}: sheet at {want_state}: {e}" for e in errors]
            ctx.close()
    return problems


def hs_tenths(root: Path, layer: dict, row: int, col: int) -> int:
    """The tenths of a millimetre the layer's live file gives for a cell (0 when it lists none)."""
    folder = root / "hail" / "live" / str(layer["window"]) / swath_stamp(layer)
    for name_path in folder.glob("*.json"):
        for r, c, t in json.loads(name_path.read_text(encoding="utf-8")).get("cells", []):
            if (r, c) == (row, col):
                return t
    return 0


def check_swath_sheet(browser, base, root: Path, data: dict, shots) -> list[str]:
    """The sheet's live line (--hail-history builds with a hail layer on; D4, D5, D16). Arrival at a point with ?at= (and
    a click on the same cell) gives the words the module gives for the cell in the state the layer is in: the value, no
    estimate, or the no-estimate words for a tile with no file, which asks for a file and gets a 404. One live file is
    read per click, and a second click on the same tile reads nothing (the file is kept for the page). No request leaves
    the site (the context counts them)."""
    if "hail" not in data:
        return []
    sw = swath_module()
    hs = hail_store()
    problems = []
    for key, title, prefix, window in SWATH:
        L = data["layers"][key]
        if not L["frames"]:
            continue
        spots = swath_spots(root, L)
        for kind, want_status in (("value", 200), ("none", 200), ("missing", 404)):
            if kind not in spots:
                problems.append(f"{NOTE}{title}: this build has no Montana cell {KIND_WORDS[kind]}, so the sheet's live line is not checked")
                continue
            row, col, tile = spots[kind]
            lat, lon = hs.cell_centre(row, col)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            page = ctx.new_page()
            errors: list[str] = []
            live: list = []
            page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
            # the browser logs a 404 it was asked for (the resource, not the script); anything else is an error
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
            page.on("response", lambda r: live.append((r.url, r.status)) if "/hail/live/" in r.url else None)
            page.clock.install(time=clock_time(swath_ms(L["valid"]) + 2 * MINUTE_MS))
            page.goto(base + f"map.html?layer={key}&at={hail_at((lat, lon))}", wait_until="load")
            page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
            text = wait_live(page, L["words"]["live_loading"])
            state, _ = view_state(L, swath_ms(L["valid"]) + 2 * MINUTE_MS)
            tenths = hs_tenths(root, L, row, col) if kind == "value" else 0
            want = sw.sheet_line(window, tenths, clock_time(swath_ms(L["valid"])), state, None, sample=L["sample"])
            if text != want:
                problems.append(f"{title}: the sheet's live line at a Montana cell {KIND_WORDS[kind]} is {text!r}, not {want!r}")
            asked = [(u, s) for u, s in live if u.endswith(f"/{tile}.json")]
            if len(asked) != 1 or asked[0][1] != want_status or len(live) != 1:
                problems.append(f"{title}: at a Montana cell {KIND_WORDS[kind]} the live file was asked {len(live)} time(s), "
                                f"{asked}; a {want_status} was expected, once")
            if kind == "value":
                snap(page, shots, f"swath-sheet-{key}-desktop.png")
                before = len(live)
                page.keyboard.press("Escape")                       # close the sheet, then click the same cell
                page.wait_for_timeout(300)
                zoom_at_centre(page)
                picture_on_screen(page, prefix)              # the picture is drawn before the map is clicked
                x, y = map_pixel(page, data, lat, lon)
                page.mouse.click(x, y)
                again = wait_live(page, L["words"]["live_loading"])
                if again != want:
                    problems.append(f"{title}: a click on the same value cell gave {again!r}")
                if len(live) != before:
                    problems.append(f"{title}: a second click on the same tile read {len(live) - before} more live file(s)")
            problems += [f"{title}: sheet at a Montana cell {KIND_WORDS[kind]}: {e}" for e in errors]
            ctx.close()
        if "value" in spots:                                        # a phone: the same line on a small screen
            row, col, tile = spots["value"]
            lat, lon = hs.cell_centre(row, col)
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
            page = ctx.new_page()
            page.goto(base + f"map.html?layer={key}&at={hail_at((lat, lon))}", wait_until="load")
            page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
            wait_live(page, L["words"]["live_loading"])
            snap(page, shots, f"swath-sheet-{key}-phone.png")
            ctx.close()
    return problems


def check_swath_list(browser, base, data: dict, shots) -> list[str]:
    """The List view carries the swath section: its heading and both layers' lines, with the SAMPLE credit on a sample
    build (the List is the build's own words, placed by storm.js)."""
    problems = []
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
    page.click("#btn-list")
    try:
        # textContent, not innerText: the sheet's headings are set in capitals by CSS, and the words are the build's
        page.wait_for_function("() => document.getElementById('sheet-body') && document.getElementById('sheet-body')"
                               ".textContent.indexOf('Hail swath (radar estimate)') >= 0", timeout=8000)
    except Exception:                                               # noqa: BLE001 - reported below
        problems.append("the List view has no hail swath section")
    text = page.evaluate("() => document.getElementById('sheet-body').textContent")
    for key, title, _prefix, _window in SWATH:
        if data["layers"][key]["frames"] and title not in text:
            problems.append(f"the List view does not name {title}")
    if data.get("sample") and "SAMPLE: invented values, not NOAA data." not in text:
        problems.append("the sample List view does not credit the sample")
    snap(page, shots, "swath-list-desktop.png")
    ctx.close()
    return problems


def changed_count_at(before: bytes, after: bytes, x: float, y: float, radius: int) -> int:
    """The changed pixels (changed_count's rule) in a box of radius screen pixels either side of a point (D17)."""
    import io

    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(io.BytesIO(before)).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(io.BytesIO(after)).convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        raise ValueError(f"the two screenshots differ in size ({a.shape} and {b.shape})")
    x0, x1 = max(0, int(x) - radius), min(a.shape[1], int(x) + radius)
    y0, y1 = max(0, int(y) - radius), min(a.shape[0], int(y) + radius)
    moved = np.max(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]), axis=2) > GATE_NOTE_PIXELS
    return int(np.count_nonzero(moved))


def on_map(page, x: float, y: float) -> bool:
    """Whether a screen point is on the map and not under a panel (the legend card, the sheet, the timeline)."""
    return bool(page.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y); return !!e && !!e.closest('#map'); }",
                              [x, y]))


def clear_spot(page, data: dict, lat: float, lon: float) -> None:
    """Drags the map until the spot is on the map and not under a panel (D17). A phone's legend card covers the middle of
    the screen, so the spot is moved down into the map below it. A spot already on the map is left where it is."""
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    sx, sy = map_pixel(page, data, lat, lon)
    if on_map(page, sx, sy):
        return
    start = (width - 50, height * 0.36)                 # the map at the right edge, clear of the panels
    target = (width / 2, height * 0.72)                 # the map below the legend card
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0] + target[0] - sx, start[1] + target[1] - sy, steps=12)
    page.mouse.up()
    page.wait_for_timeout(300)


def zoom_on_spot(page, data: dict, lat: float, lon: float) -> None:
    """Zooms in with the wheel over the spot (D17): Leaflet keeps the point under the pointer, so the spot stays where it
    is on the screen. The gate's clock is fake, so the map's wheel timers are run once the wheel has been turned."""
    x, y = map_pixel(page, data, lat, lon)
    page.mouse.move(x, y)
    for _ in range(14):
        page.mouse.wheel(0, -500)
        page.wait_for_timeout(120)
    page.clock.run_for(3000)
    page.wait_for_timeout(400)


def check_swath_gate(browser, base, root: Path, data: dict, shots) -> list[str]:
    """The picture gate for the sparse hail layers (D17, the B4 brief). The page opens at a cell that the live file lists
    with a value at or above the floor, and the sheet that the spot opens is closed. The map is dragged, if a panel covers
    the spot, and zoomed on the spot to GATE_MIN_ZOOM or closer. The picture, when it is shown, must change at least
    GATE_MIN_CHANGED pixels in a box of GATE_SPOT_RADIUS screen pixels around the spot, counted as the share test counted
    them (a colour channel moves by more than 16 of 255). The picture hidden is the control: the whole canvas may not
    change with it hidden. The count is recorded as a note for each size, with the canvas share for the record. A layer
    with no cell at or above the floor is a note: "no values in the box: pixel gate not applicable". The 2 percent rule
    is for the dense pictures (radar and satellite), not for these layers."""
    problems = []
    hs = hail_store()
    for key, title, prefix, window in SWATH:
        L = data["layers"][key]
        if not L["frames"]:
            continue
        cell = value_cell(root, L)
        if cell is None:
            problems.append(f"{NOTE}{title}: no values in the box: pixel gate not applicable")
            continue
        lat, lon = hs.cell_centre(*cell)
        for label, size in HAIL_SIZES:
            ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, reduced_motion="reduce")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
            page.clock.install(time=clock_time(swath_ms(L["valid"]) + 2 * MINUTE_MS))
            page.goto(base + f"map.html?layer={key}&at={hail_at((lat, lon))}", wait_until="load")
            page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
            page.keyboard.press("Escape")                       # the spot's sheet opens at once, and its scrim covers the map
            page.wait_for_timeout(300)
            if not picture_on_screen(page, prefix):
                problems.append(f"{label}: {title}: the picture was not on screen at its spot")
            clear_spot(page, data, lat, lon)
            zoom_on_spot(page, data, lat, lon)
            zoom = map_zoom(page, data)
            if zoom is None or zoom < GATE_MIN_ZOOM - 0.05:
                problems.append(f"{label}: {title}: the spot is at zoom {zoom_words(zoom)}, not {GATE_MIN_ZOOM} or closer")
            sx, sy = map_pixel(page, data, lat, lon)
            if not on_map(page, sx, sy):
                problems.append(f"{label}: {title}: the spot is under a panel at zoom {zoom_words(zoom)}, so it is not checked")
            page.wait_for_timeout(300)
            page.evaluate(IMAGES_SHOWN, False)
            page.wait_for_timeout(150)
            without = map_canvas(page)
            page.evaluate(IMAGES_SHOWN, True)
            page.wait_for_timeout(150)
            shown = map_canvas(page)
            page.evaluate(IMAGES_SHOWN, False)                  # the control: hidden again, nothing else may change
            page.wait_for_timeout(150)
            again = map_canvas(page)
            page.evaluate(IMAGES_SHOWN, True)
            drift = changed_count(without, again)
            if drift >= GATE_MIN_CHANGED:
                problems.append(f"{label}: {title}: the map changed {drift} pixels with the picture hidden in both captures "
                                "(the control), so the count below is not the picture's alone")
            box = page.locator("#map").bounding_box()
            changed = changed_count_at(without, shown, sx - box["x"], sy - box["y"], GATE_SPOT_RADIUS)
            if changed < GATE_MIN_CHANGED:
                problems.append(f"{label}: {title}: the picture changed {changed} pixels at the spot, "
                                f"fewer than {GATE_MIN_CHANGED}")
            problems.append(f"{NOTE}{title}: {label}: {changed} pixels changed at the spot (a box of {2 * GATE_SPOT_RADIUS} "
                            f"px; zoom {zoom_words(zoom)}; {changed_share(without, shown):.2%} of the whole canvas, "
                            "for the record)")
            problems += [f"{label}: {title}: {e}" for e in errors]
            ctx.close()
    return problems


def check_swath_tick(browser, base, data: dict) -> list[str]:
    """The state is checked every minute (browser-12, D7). The page's clock is moved by hand: one second past the fresh
    minutes, the line must read stale within a minute, and one second past the stale minutes it must read unavailable
    within a minute, with the picture gone. Each step's line is the one view_state gives at that time, or the one it gave a
    minute before: the line is written at each tick, so it can lag the clock by up to a minute."""
    problems = []
    for key, title, prefix, window in SWATH:
        L = data["layers"][key]
        if not L["frames"]:
            continue
        valid = swath_ms(L["valid"])
        fresh_ms, stale_ms = L["fresh_min"] * MINUTE_MS, L["stale_min"] * MINUTE_MS
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error"
                and "Failed to load resource" not in m.text else None)
        page.clock.install(time=clock_time(valid + fresh_ms - 1000))
        page.goto(base + f"map.html?layer={key}", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
        page.wait_for_timeout(600)
        now = fresh_ms - 1000                       # ms past the frame, as the page's clock stands now
        steps = (("stale", fresh_ms + 1000), ("unavailable", stale_ms + 1000))
        for want_state, boundary in steps:
            page.clock.run_for(boundary - now)     # one second past the boundary
            now = boundary
            page.clock.run_for(TICK_MS)            # within a minute of it, the check has run
            now += TICK_MS
            now_ms, line = page.evaluate(f"() => [Date.now(), document.querySelector('{SWATH_LINE}').textContent]")
            state, want = view_state(L, now_ms)
            # the line is written at the last tick, up to a minute before the read: that minute's line is the other answer
            _, earlier = view_state(L, now_ms - TICK_MS)
            drawn = page.evaluate(SWATH_PICTURE, key.replace("_", "-"))
            if state != want_state or line.strip() not in (want, earlier):
                problems.append(f"{title}: a minute past {boundary // MINUTE_MS} min the line is {line.strip()!r}, "
                                f"not {want!r} ({want_state})")
            if want_state == "unavailable" and drawn:
                problems.append(f"{title}: an unavailable layer still shows its picture")
            if want_state == "stale" and not drawn:
                problems.append(f"{title}: a stale layer lost its picture at the fresh minutes")
        problems += [f"{title}: tick: {e}" for e in errors]
        ctx.close()
    return problems


def check_swath_outside(browser, base, root: Path, data: dict, shots) -> list[str]:
    """Points outside Montana with a hail layer on (browser-2; the store decides, B1). A point in the picture's box gets
    the Montana sentence and no value; a point outside the box gets the picture's outside words. A point in a tile the
    store does not list reads no tile (no request); a point in a listed tile reads its shard once, and its live file once
    only when the shard puts the point in Montana (F-9, D16): a listed tile outside Montana makes one request, the shard.
    The live line follows the shard. The points: the HAIL_OUTSIDE spots, and a cell of a listed tile outside Montana (the
    border case)."""
    if "hail" not in data:
        return []
    hs = hail_store()
    problems = []
    spots = dict(HAIL_OUTSIDE)
    border = outside_spot(root, data)
    if border is not None:
        spots["a listed tile outside Montana"] = border
    for key, title, prefix, window in SWATH:
        L = data["layers"][key]
        if not L["frames"]:
            continue
        (south, west), (north, east) = L["bounds"]
        for name, (lat, lon) in spots.items():
            row, col = hs.cell_for(lat, lon)
            tile = hs.tile_name(row // hs.TILE, col // hs.TILE)
            inside_box = south <= lat <= north and west <= lon <= east
            listed = tile in set(listed_tiles(data))
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            page = ctx.new_page()
            errors: list[str] = []
            live, shards = [], []
            page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
            page.on("request", lambda r: live.append(r.url) if "/hail/live/" in r.url else
                    shards.append(r.url) if "/hail/t/" in r.url else None)
            page.clock.install(time=clock_time(swath_ms(L["valid"]) + 2 * MINUTE_MS))
            page.goto(base + f"map.html?layer={key}&at={hail_at((lat, lon))}", wait_until="load")
            page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
            text = wait_live(page, L["words"]["live_loading"])
            if not inside_box:
                want = L["words"]["outside"]
            elif listed and not in_montana(root, row, col):
                want = L["words"]["outside_montana_live"]
            else:
                want = None                          # a Montana cell: the other checks read its value
            label = L["words"]["sample_sheet"] + " " if L["sample"] else ""     # the sample label leads a sample build's line (D10)
            if want is not None and text != label + want:
                problems.append(f"{title}: the sheet's live line at {name} is {text!r}, not {label + want!r}")
            if not listed and (live or shards):
                problems.append(f"{title}: {name} is in a tile the store does not list, yet {len(live)} live and "
                                f"{len(shards)} shard request(s) were made")
            if listed and len([u for u in shards if u.endswith(f"/{tile}.json")]) != 1:
                problems.append(f"{title}: {name} did not read its shard once")
            live_reads = len([u for u in live if u.endswith(f"/{tile}.json")])
            want_live = 1 if listed and inside_box and in_montana(root, row, col) else 0
            if live_reads != want_live:
                problems.append(f"{title}: {name} read {live_reads} live file(s), not {want_live} (a point the shard puts "
                                "outside Montana reads no live file, F-9)")
            problems += [f"{title}: outside at {name}: {e}" for e in errors]
            ctx.close()
    return problems


# the centre of a town marker that lies fully on screen (the town card check clicks it)
TOWN_ON_SCREEN = ("() => { const w = innerWidth, h = innerHeight; for (const t of document.querySelectorAll('.leaflet-marker-icon.town')) {"
                  " const b = t.getBoundingClientRect(); if (b.width > 0 && b.left >= 0 && b.top >= 0 && b.right <= w && b.bottom <= h &&"
                  " getComputedStyle(t).visibility !== 'hidden') return {x: b.left + b.width / 2, y: b.top + b.height / 2}; }"
                  " return null; }")


def check_swath_town_card(browser, base, root: Path, data: dict, shots) -> list[str]:
    """A hail sheet's live line does not carry into the next sheet (rules-1). With a hail layer on, the page opens a hail
    sheet at a cell with a value, the sheet closes (Escape), a town's card opens, and a minute later the card has no live
    line. The precipitation layer at the same spot is the control: it has no live line at all."""
    if "hail" not in data:
        return []
    hs = hail_store()
    problems = []
    for key, title, prefix, window in SWATH:
        L = data["layers"][key]
        if not L["frames"]:
            continue
        cell = value_cell(root, L)
        if cell is None:
            problems.append(f"{NOTE}{title}: no cell with a value in the live files: the town card check is not checked")
            continue
        at = hail_at(hs.cell_centre(*cell))
        for layer_key in (key, "precip"):
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error"
                    and "Failed to load resource" not in m.text else None)
            page.clock.install(time=clock_time(swath_ms(L["valid"]) + 2 * MINUTE_MS))
            page.goto(base + f"map.html?layer={layer_key}&at={at}", wait_until="load")
            page.wait_for_selector(".leaflet-marker-icon.town", state="attached", timeout=15000)
            page.wait_for_selector("#sheet.sheet-hail", state="visible", timeout=15000)
            if layer_key == key and page.locator("#legend-title").inner_text().strip() != L["title"]:
                problems.append(f"{title}: the layer was not on when its sheet opened")
            page.keyboard.press("Escape")
            page.wait_for_selector("#sheet", state="hidden", timeout=5000)
            centre = None
            for _ in range(8):                                      # zoom out with the wheel until a town is on screen
                centre = page.evaluate(TOWN_ON_SCREEN)
                if centre:
                    break
                page.mouse.wheel(0, 240)
                page.wait_for_timeout(300)
            if not centre:
                problems.append(f"{NOTE}{title}: no town marker is on screen after zooming out: the town card check is not checked")
                ctx.close()
                continue
            page.mouse.click(centre["x"], centre["y"])             # a visible town marker, by its centre
            page.wait_for_selector("#sheet.sheet-town", state="visible", timeout=5000)
            page.clock.run_for(61_000)
            lines = page.locator("#sheet-body [data-live='swath']").count()
            if lines:
                problems.append(f"{title} (layer {layer_key}): the town card shows a live line from the closed hail sheet")
            problems += [f"{title}: town card: {e}" for e in errors]
            ctx.close()
    return problems


def check_swath(browser, base, root: Path, data: dict, shots) -> list[str]:
    """The live hail swath layers (--storm-layers builds): the layers, their legends and states, the view-time freshness,
    the sheet's live line (with --hail-history) and the List. Notes (a gate that does not apply, a cell that a build lacks)
    are reported and never fail the run."""
    if not all(key in data["layers"] for key, *_ in SWATH):
        return ["the map data has no hail swath layers (--storm-layers)"]
    problems = []
    problems += check_swath_layers(browser, base, root, data, shots)
    problems += check_swath_gate(browser, base, root, data, shots)
    problems += check_swath_tick(browser, base, data)
    problems += check_swath_clock(browser, base, root, data, shots)
    problems += check_swath_list(browser, base, data, shots)
    problems += check_swath_sheet(browser, base, root, data, shots)
    problems += check_swath_outside(browser, base, root, data, shots)
    problems += check_swath_town_card(browser, base, root, data, shots)
    return problems


# ---------------------------------------------------------------- the five-season summary on the sheet (B5, part B2)
# The table is the browser's words. describe_summary (website/summary.py) gives the Python words for the same cell of the
# same store. The page is read as a reader sees it: the table inside the sheet that holds the column names, with no class
# names, so the browser may build it any way. Each row is found by its label; its kind word and unit are read from the row;
# every cell is compared with the Python cell text and its coverage line.
SUMMARY_SIZES = (("phone", (390, 844)), ("desktop", (1280, 800)))   # gate B5-11: the sheet at these two sizes
SUMMARY_WAIT_S = 15                     # the table is awaited this long once the sheet's loading line has gone

SUMMARY_READ = """() => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const body = document.getElementById('sheet-body');
  const sheet = document.getElementById('sheet');
  if (!body || !sheet) return null;
  const sb = sheet.getBoundingClientRect();
  const out = {present: false, body: clean(body.innerText),
               viewport: {w: innerWidth, h: innerHeight, scrollW: document.documentElement.scrollWidth},
               sheet: {top: sb.top, bottom: sb.bottom}};
  // the table lives in the summary slot ([data-hail='summary'], B5 round 2); textContent, not innerText, names it: in the phone's
  // card layout the column header is hidden, and a hidden header still names the table
  const slot = body.querySelector('[data-hail="summary"]') || body;
  const table = [...slot.querySelectorAll('table')].find(t => {
    const text = clean(t.textContent);
    return text.includes('2021-22') && text.includes('Five seasons');
  });
  if (!table) return out;
  out.present = true;
  const box = r => ({top: r.top, bottom: r.bottom, left: r.left, right: r.right});
  let top = table;
  while (top.parentElement && top.parentElement !== body) top = top.parentElement;
  const kids = [...body.children];
  let above = null;
  for (const k of kids.slice(0, kids.indexOf(top))) {
    const b = k.getBoundingClientRect().bottom;
    above = above === null ? b : Math.max(above, b);
  }
  out.table = box(table.getBoundingClientRect());
  out.above_bottom = above;
  out.rows = [...table.querySelectorAll('tr')].map(tr => ({
    text: clean(tr.innerText),
    cells: [...tr.querySelectorAll('th, td')].map(c => clean(c.innerText)),
    rect: box(tr.getBoundingClientRect())}));
  out.first_row = out.rows.length > 1 ? out.rows[1].rect : null;   // row 0 is the column header
  return out;
}"""


def map_budget(data: dict, key: str) -> int | None:
    """A byte budget the build wrote into map.json's hail.budget block (D66, D75): tile_events_gzip_bytes for a file a tap
    fetches, phone_gzip_bytes for the phone view. None when the build did not write it, and the caller names that."""
    value = ((data.get("hail") or {}).get("budget") or {}).get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def summary_store(store: Path | None, root: Path) -> Path:
    """The store the sheet's summary words are read from: --store when it is given, else the built site's own copy (D75)."""
    return store if store is not None else root


def summary_module():
    """The summary's words and rules, website/summary.py, imported from this repository."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from website import summary as sm
    return sm


def summary_spots(data: dict) -> list[tuple[str, tuple[int, int]]]:
    """The three cells the smoke compares word for word (gate B5-11): the cell of Billings' town point (read from the map's
    own town list), Benchland's cell 792,1998 and the gate cell 797,1986. No station, count or value is pinned here: the
    expected words come from describe_summary on the store the smoke is given."""
    hs = hail_store()
    town = next(t for t in data["towns"] if t["name"] == "Billings")
    return [("Billings", hs.cell_for(town["lat"], town["lon"])), ("Benchland cell 792,1998", (792, 1998)),
            ("the gate cell 797,1986", (797, 1986))]


def map_now(data: dict) -> datetime:
    """The build's time (map.json "now", UTC): the time the build gave describe_summary, so the stale line reads the same."""
    return datetime.fromisoformat(data["now"].replace("Z", "+00:00"))


def norm(text) -> str:
    """Text as a reader sees it: each run of white space is one space, and the ends are cut."""
    return " ".join(str(text or "").split())


def gzip_size(body: bytes) -> int:
    return len(gzip.compress(body, 6))


UNIT_NOUNS = {"days": ("day",),                                   # the cells' own nouns: "1 day", "3 hail reports"
              "count": ("report", "reports", "watch", "watches", "warning", "warnings", "product", "products",
                        "record", "records")}


def unit_shown(unit: str, text: str, unit_spec: dict) -> bool:
    """The row's unit, as its abbreviation, its word or the noun its cells use, is in the row's text. The held row's unit
    slot is its reason."""
    if unit == "reason":
        return True
    tokens = {unit, unit_spec[unit]["word"], *UNIT_NOUNS.get(unit, ())}
    return any(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", text) for token in tokens if token)


def cell_words(text, coverage) -> str:
    """The words a cell of the table must read: the cell's own words, then its coverage line (if any). The browser sets the line
    in a block after the words (map.css: .sum-cover is a block), and innerText joins the two with one space."""
    return norm(text) + (" " + norm(coverage) if coverage else "")


def find_cell(cells: list[str], start: int, text, coverage) -> int | None:
    """The first cell from start whose words are exactly the Python words of the cell and its coverage line (D75(b)). A cell
    with other words before or after them is not that cell, so words added to a correct cell fail."""
    want = cell_words(text, coverage)
    for i in range(start, len(cells)):
        if want and norm(cells[i]) == want:
            return i
    return None


def summary_problems(label: str, want: dict, got: dict | None) -> list[str]:
    """The sheet's table against describe_summary for the same cell: the heading, the lead and the radar sentence; the partial
    line and the held line; every row in the Product order with its label, its kind word and its unit; every season cell and
    the five-season cell with its exact Python words and coverage line; the five-season sentence. Nothing here looks at a
    class name or a position beyond the order of the cells."""
    sm = summary_module()
    if not got or not got.get("present"):
        return [f"{label}: the sheet shows no five-season table (no table inside the sheet holds 2021-22 and Five seasons)"]
    problems: list[str] = []
    body = norm(got.get("body"))
    table = want["table"]
    # the heading's words, not its capitals: a heading the style shows in capitals reads the same words (AGENTS: sentence case
    # is the convention for the words; the style is checked by the browser's own review, not here)
    if norm(sm.WORDS_SUMMARY["table_title"]).lower() not in body.lower():
        problems.append(f"{label}: the sheet lacks the table's heading {sm.WORDS_SUMMARY['table_title']!r}")
    for what, text in (("the lead sentence", want["plain"]), ("the radar sentence", want["radar_sentence"])):
        if norm(text) not in body:
            problems.append(f"{label}: the sheet lacks {what} {norm(text)!r}")
    partial = (table.get("partial") or {}).get("text")
    if partial and norm(partial) not in body:
        problems.append(f"{label}: the sheet lacks the partial line that starts {norm(partial)[:70]!r}")
    if table.get("held") and norm(table["held"]) not in body:
        problems.append(f"{label}: the sheet lacks the held line {norm(table['held'])!r}")
    data_rows = (got.get("rows") or [])[1:]                  # row 0 is the column header
    j = 0
    for py in table["rows"]:
        if py.get("town_only") or py["key"] == "held":
            continue
        name = norm(py["label"])
        k = next((i for i in range(j, len(data_rows))
                  if data_rows[i]["cells"] and data_rows[i]["cells"][0].startswith(name)), None)
        if k is None:
            problems.append(f"{label}: the table has no row labelled {py['label']!r}, in the Product order")
            continue
        row, j = data_rows[k], k + 1
        if norm(py["kind"]) not in row["text"]:
            problems.append(f"{label}: the row {py['label']!r} does not show its kind word {py['kind']!r}")
        if not unit_shown(py["unit"], row["text"], sm.UNIT_SPEC):
            problems.append(f"{label}: the row {py['label']!r} does not show its unit "
                            f"({sm.UNIT_SPEC[py['unit']]['word']})")
        cells, pos = row["cells"], 1
        for i, text in enumerate(py["texts"]):
            found = find_cell(cells, pos, text, py["coverage"][i])
            if found is None:
                problems.append(f"{label}: {py['label']!r}, {sm.FIVE[i]}: the sheet does not show exactly "
                                f"{cell_words(text, py['coverage'][i])!r}")
            else:
                pos = found + 1
        if find_cell(cells, pos, py["five_text"], py["five_coverage"]) is None:
            problems.append(f"{label}: {py['label']!r}, Five seasons: the sheet does not show exactly "
                            f"{cell_words(py['five_text'], py['five_coverage'])!r}")
        if py.get("five_note") and norm(py["five_note"]) not in body:
            problems.append(f"{label}: {py['label']!r}: the sheet lacks the five-season line {norm(py['five_note'])[:70]!r}")
    return problems


def first_screen_problems(label: str, got: dict | None) -> list[str]:
    """The table starts inside the first screen of the sheet, below the address and live lines, its first row is in that
    screen, and nothing runs sideways at this width (gate B5-11: the table within the first screen at 390 px)."""
    if not got or not got.get("present"):
        return []
    vp, sheet, table = got["viewport"], got["sheet"], got["table"]
    limit = min(sheet["bottom"], vp["h"])
    problems: list[str] = []
    if got.get("above_bottom") is not None and got["above_bottom"] > table["top"] + 1:
        problems.append(f"{label}: a block above the table ends at {got['above_bottom']:.0f} px, below the table's top at "
                        f"{table['top']:.0f} px; the address lines and the live line come first")
    if not sheet["top"] - 1 <= table["top"] <= limit:
        problems.append(f"{label}: the table starts at {table['top']:.0f} px, outside the first screen of the sheet "
                        f"({sheet['top']:.0f} to {limit:.0f} px at {vp['w']} px wide)")
    first = got.get("first_row")
    if not first or first["top"] < sheet["top"] - 1 or first["bottom"] > limit:
        where = "missing" if not first else f"{first['top']:.0f} to {first['bottom']:.0f} px"
        problems.append(f"{label}: the table's first row is not inside the first screen ({where}; the screen ends at "
                        f"{limit:.0f} px)")
    if table["left"] < -0.5 or table["right"] > vp["w"] + 0.5 or vp["scrollW"] > vp["w"] + 0.5:
        problems.append(f"{label}: the table or the page runs sideways at {vp['w']} px (the page is {vp['scrollW']} px wide)")
    return problems


def fetch_problems(label: str, sizes: dict, limit: int) -> list[str]:
    """sizes: {path: gzip bytes}. Every file a tap fetches is under limit, the tile-file budget map.json carries (D30, D66, D75)."""
    return [f"{label}: {path} is {size} bytes gzip, at or over the {limit}-byte limit for a file a tap fetches"
            for path, size in sorted(sizes.items()) if size >= limit]


def tap_problems(label: str, responses: list, limit: int | None) -> list[str]:
    """The hail files one tap fetched, each counted once: the fetch list as a note, the unread files, the answers that are not
    200, and the size rule against limit (None when the build wrote no budget; check_summary names that once)."""
    files: dict[str, int | None] = {}
    statuses: dict[str, int] = {}
    for response in responses:
        path = urlsplit(response.url).path
        if path not in files:
            statuses[path] = response.status
            try:
                files[path] = gzip_size(response.body())
            except Exception:                                   # noqa: BLE001 - reported below
                files[path] = None
    measured = {path: size for path, size in files.items() if size is not None}
    listed = ", ".join(f"{path.split('/hail/')[-1]} {size} B"
                       + ("" if statuses[path] == 200 else f" (answered {statuses[path]})")
                       for path, size in sorted(measured.items()))
    problems = [f"{NOTE}fetch list {label}: {listed or 'no hail file'}"]
    unread = sorted(path for path, size in files.items() if size is None)
    if unread:
        problems.append(f"{label}: {len(unread)} file(s) could not be read to measure them: {', '.join(unread[:3])}")
    answered = sorted(path for path, status in statuses.items() if status != 200)
    if answered:
        problems.append(f"{label}: {', '.join(p.split('/hail/')[-1] for p in answered[:4])} did not answer 200 OK "
                        f"(a file the sheet needs is missing or failed)")
    return problems + (fetch_problems(label, measured, limit) if limit is not None else [])


def summary_read(page) -> dict:
    """The sheet's summary table as the page shows it, once the table is there (or the last reading, after SUMMARY_WAIT_S)."""
    deadline = time.monotonic() + SUMMARY_WAIT_S
    got = None
    while time.monotonic() < deadline:
        got = page.evaluate(SUMMARY_READ)
        if got and got.get("present"):
            return got
        page.wait_for_timeout(200)
    return got or {"present": False}


def table_problems(label: str, want: dict | None, got: dict | None) -> list[str]:
    """The sheet's table against the store's words when want is given (summary_problems). With no words (the store could not
    be read, and check_summary names that), only the table's presence is checked here."""
    if want is not None:
        return summary_problems(label, want, got)
    if not got or not got.get("present"):
        return [f"{label}: the sheet shows no five-season table (no table inside the sheet holds 2021-22 and Five seasons)"]
    return []


def summary_spot(browser, base: str, data: dict, label: str, cell: tuple[int, int], want: dict | None, size_name: str,
                 size: tuple[int, int], shots: Path | None, limit: int | None, expected: dict | None = None) -> list[str]:
    """One spot at one size, twice: opened with ?at= (the link a reader gets), and by a tap on the map at the spot's centre,
    from a page that has loaded and holds no sheet yet (so the tap's own files are the ones it lists). want is the store's
    words for the cell, or None when the store could not be read; expected is describe_joins for the cell, or None. The
    table's position, the sections' order and the tap's files are checked either way. limit is the tile-file budget
    (map.json), or None."""
    hs = hail_store()
    lat, lon = hs.cell_centre(*cell)
    loading = data["hail"]["words"]["loading"]
    ids = section_ids(data)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{label} {size_name}".lower()).strip("-")
    problems: list[str] = []

    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]})
    page = ctx.new_page()
    errors_first: list[str] = []                        # this context's errors only (F-15)
    page.on("pageerror", lambda e: errors_first.append(f"script error: {e}"))
    arrival: list = []
    page.on("response", lambda r: arrival.append(r) if "/hail/" in r.url else None)
    hail_open(page, base, hail_at((lat, lon)))
    where = f"{label} at {size_name}, opened with ?at="
    if not sheet_settled(page, loading):
        problems.append(f"{where}: the hail sheet did not open")
    got = summary_read(page)
    sheet = sheet_read(page, ids)
    problems += table_problems(where, want, got) + first_screen_problems(where, got)
    problems += sheet_checks(where, want, sheet, ids, expected, data)
    snap(page, shots, f"summary-{slug}-open.png")
    problems += tap_problems(where, arrival, limit)
    problems += [f"{label} at {size_name}: {e}" for e in errors_first]
    ctx.close()

    tapped: list = []
    errors_tapped: list[str] = []                       # the tapped context's errors, not the first context's again (F-15)
    ctx, page = b3_open(browser, base, size[0], size[1], listen=lambda r: tapped.append(r))
    page.on("pageerror", lambda e: errors_tapped.append(f"script error: {e}"))
    start = len(tapped)
    tap_centre(page, lat, lon)
    where = f"{label} at {size_name}, tapped at its centre"
    if not sheet_settled(page, loading):
        problems.append(f"{where}: the tap did not open the hail sheet")
    got = summary_read(page)
    sheet = sheet_read(page, ids)
    problems += table_problems(where, want, got) + first_screen_problems(where, got)
    problems += sheet_checks(where, want, sheet, ids, expected, data)
    problems += tap_problems(where, [r for r in tapped[start:] if "/hail/" in r.url], limit)
    problems += [f"{label} at {size_name}: {e}" for e in errors_tapped]
    ctx.close()
    return problems


def check_summary(browser, base: str, root: Path, data: dict, store: Path, shots: Path | None,
                  history: bool) -> list[str]:
    """The five-season summary and the eleven sections on the hail sheet (B5 part B2; brief Product and gates B5-11 and B5-12)
    at 390 and 1280 px, for the Billings cell, Benchland's cell 792,1998 and the gate cell 797,1986 (summary_spots): the words
    of every cell, row and line against describe_summary on the store given (--store, or the built site's hail/), the table's
    notes, each section's heading, lead, notes and rows, How this was made and the roof groups (sections_problems and
    joined_problems), the first-screen rule, and the tile-file budget map.json carries for every file a tap fetches. A summary
    that did not load is a failure with --history and a note without it. A store that cannot be read is a failure too (named
    once); the sheet is still opened at each spot, so the table's position and the tap's files are checked (D75)."""
    summary = (data["hail"].get("summary") or {})
    if summary.get("state") != "loaded":
        text = (f"the five-season summary is {summary.get('state', 'missing')} in this build: "
                f"{summary.get('problem') or 'no reason given'}")
        return [text] if history else [f"{NOTE}{text}; the sheet's summary words were not checked"]
    hs = hail_store()
    sm = summary_module()
    now = map_now(data)
    limit = map_budget(data, "tile_events_gzip_bytes")
    problems: list[str] = []
    if limit is None:
        problems.append("the build's map.json has no tile-file budget (hail.budget.tile_events_gzip_bytes), so the sizes of "
                        "the files a tap fetches are not checked")
    spots = summary_spots(data)
    want: dict | None = None
    expected: dict | None = None
    with tempfile.TemporaryDirectory(prefix="smoke-store-") as tmp:
        try:
            store_root = hs.load_store(store, tmp)
        except hs.HailStoreError as exc:
            problems.append(f"the store the smoke was given ({store}) cannot be read: {exc}. The sheet's words were not "
                            f"compared; the table's position and the sizes of the files a tap fetches were still checked.")
        else:
            want = {label: sm.describe_summary(store_root, row, col, now) for label, (row, col) in spots}
            expected = {label: joins_expected(store_root, data, hs.cell_centre(row, col)) for label, (row, col) in spots}
            for label, words in want.items():
                if words["state"] not in ("loaded", "partial"):
                    problems.append(f"{label}: the store's own words for this cell are {words['state']}: "
                                    f"{words.get('problem')}")
    for size_name, size in SUMMARY_SIZES:
        for label, cell in spots:
            problems += summary_spot(browser, base, data, label, cell, want[label] if want is not None else None,
                                     size_name, size, shots, limit,
                                     expected[label] if expected is not None else None)
    return problems


def check_every_layer(browser, base: str, data: dict) -> list[str]:
    """The phone view at zoom 15 over Billings with every layer of the menu on (gate B5-12, D30, D40, D42, D66): each layer is
    ticked in turn, and the files the view fetches (shell, data, B3 files, B4 live files, B5 history files) must be under the
    phone budget map.json carries (hail.budget.phone_gzip_bytes). The picture frames (map/frames/) are listed apart, as B3's
    note lists them."""
    problems: list[str] = []
    titles = [layer["title"] for layer in data["layers"].values() if layer.get("title")]
    lat, lon = B3_BILLINGS
    seen: list = []
    ctx, page = b3_open(browser, base, 390, 844, listen=lambda r: seen.append(r))   # every response, from the first request
    b3_view(page, lat, lon, ADDRESS_GATE_ZOOM, settle_ms=2500)
    missing = []
    for title in titles:
        try:
            pick_layer(page, title)
            page.wait_for_timeout(1500)
        except Exception as e:                                  # noqa: BLE001 - reported below
            missing.append(f"{title} ({str(e).splitlines()[0][:70]})")
    if missing:
        problems.append("the layer menu would not turn on every layer at 390 px: " + "; ".join(missing))
    sizes: dict[str, tuple[str, int]] = {}
    unread = 0
    for response in seen:
        if response.url in sizes:
            continue
        try:
            sizes[response.url] = (layer_part(response.url), gzip_size(response.body()))
        except Exception:                                       # noqa: BLE001 - reported below
            unread += 1
    ctx.close()
    totals: dict[str, int] = {}
    for part, size in sizes.values():
        totals[part] = totals.get(part, 0) + size
    scope = sum(size for part, size in totals.items() if part != "frames")
    if unread:
        problems.append(f"{unread} responses could not be read to measure them")
    phone = map_budget(data, "phone_gzip_bytes")                # map.json's phone budget (D66, D75)
    if phone is None:
        problems.append("the build's map.json has no phone-view budget (hail.budget.phone_gzip_bytes), so the phone view "
                        "with every layer on is not checked")
    elif scope >= phone:
        problems.append(f"the phone view at zoom {ADDRESS_GATE_ZOOM} over Billings with every layer on fetched {scope} bytes "
                        f"gzip; the budget is {phone}")
    parts = ", ".join(f"{part} {size}" for part, size in sorted(totals.items()))
    problems.append(f"note: phone view at zoom {ADDRESS_GATE_ZOOM} over Billings with {len(titles)} layers on: {scope} bytes "
                    f"gzip against the budget of {phone} ({parts}; {len(sizes)} files)")
    return problems


def layer_part(url: str) -> str:
    """Which part of a phone view a response belongs to: the picture frames (listed apart), the B3 files, the B4 live swath
    files (hail/live/), the B5 history files (the other hail/ files), or the shell and data."""
    path = "/" + urlsplit(url).path.lstrip("/")
    if "/map/frames/" in path:
        return "frames"
    if b3_kind(url) != "other":
        return "B3 files"
    if "/hail/live/" in path:
        return "B4 live files"
    if "/hail/" in path:
        return "B5 history files"
    return "shell and data"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Check the built Montana map in Chromium (AGENTS.md rule 8)")
    ap.add_argument("root", nargs="?", default="_site", type=Path, help="the built site (default: _site)")
    ap.add_argument("--shots", type=Path, metavar="DIR",
                    help="also save pictures for the record: the desktop and phone, both base maps")
    ap.add_argument("--addresses", action="store_true",
                    help="also check the address dots, streets and building outlines (a --hail-addresses build)")
    ap.add_argument("--store", type=Path, metavar="PATH",
                    help="the store the sheet's summary words are read from (a folder that holds hail/, or a "
                         "hail-store.tar.gz); default: the built site's own hail/ folder")
    ap.add_argument("--history", action="store_true",
                    help="the build passed --hail-history: its five-season summary must load and its sheet checks must "
                         "run (without the flag, a missing summary is a note)")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    problems = check(a.root, a.shots, addresses=a.addresses, store=a.store, history=a.history)
    notes = [p[len(NOTE):] for p in problems if p.startswith(NOTE)]
    failures = [p for p in problems if not p.startswith(NOTE)]
    for n in notes:
        print("Note: " + n)
    if failures:
        print("Map smoke test failed:\n- " + "\n- ".join(failures))
        return 1
    print("Map smoke test passed: page, frames, basemap, bubbles, play, layers, card and the Imagery base map all work, "
          "and on a --hail-history build the hail sheet does too (or, without the flag, no sheet is offered); "
          "on a --storm-layers build the hail swath layers, their freshness and their List do too; "
          "on a --hail-history build the five-season summary on the sheet shows the store's own words at three cells, "
          "inside the first screen, and each file a tap fetches is under the budget map.json carries; "
          "no request went to another site (the imagery tiles aside, after a switch to Imagery).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
