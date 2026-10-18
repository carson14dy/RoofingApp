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

Every browser context counts the requests that leave this server, and that count must be zero, except for
the imagery host in the contexts that have switched to Imagery. Exits 1 with the reasons if anything fails.
The Website workflow runs it on branch pushes; locally set PW_CHROMIUM to a Chromium executable if
Playwright's own isn't installed.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


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


def check(root: Path, shots: Path | None = None) -> list[str]:
    from playwright.sync_api import sync_playwright

    problems: list[str] = []
    data = json.loads((root / "data" / "map.json").read_text(encoding="utf-8"))
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
                page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
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
                      ("check_imagery_refused", lambda: check_imagery_refused(browser, base, data)))
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
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
        main_towns = sum(1 for t in data["towns"] if not t.get("minor"))
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
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
        main_towns = sum(1 for t in data["towns"] if not t.get("minor"))
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
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
        page.wait_for_selector(".leaflet-overlay-pane svg path", timeout=15000)
        snap(page, shots, "phone-map.png")
        base_choice(page, "imagery")
        watch.tile()                                # the picture waits for a tile; a missing one is the desktop's note
        page.wait_for_timeout(400)
        if not page.evaluate(IMAGERY_ON):
            problems.append("phone imagery: switching to Imagery did not set is-imagery on #app")
        if base_query(page) != "imagery":
            problems.append(f"phone imagery: the address does not carry base=imagery ({page.url})")
        main_towns = sum(1 for t in data["towns"] if not t.get("minor"))
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check the built Montana map in Chromium (AGENTS.md rule 8)")
    ap.add_argument("root", nargs="?", default="_site", type=Path, help="the built site (default: _site)")
    ap.add_argument("--shots", type=Path, metavar="DIR",
                    help="also save pictures for the record: the desktop and phone, both base maps")
    a = ap.parse_args(argv)
    problems = check(a.root, a.shots)
    notes = [p[len(NOTE):] for p in problems if p.startswith(NOTE)]
    failures = [p for p in problems if not p.startswith(NOTE)]
    for n in notes:
        print("Note: " + n)
    if failures:
        print("Map smoke test failed:\n- " + "\n- ".join(failures))
        return 1
    print("Map smoke test passed: page, frames, basemap, bubbles, play, layers, card and the Imagery base map all work, "
          "and no request went to another site (the imagery tiles aside, after a switch to Imagery).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
