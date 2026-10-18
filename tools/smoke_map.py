"""Open the built map in a real browser and check that it works (AGENTS.md rule 8).

    python tools/smoke_map.py _site

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
too (check_satellite), including a switch to it made while the timeline plays. Every browser context counts
the requests that leave this server, and that count must be
zero. Exits 1 with the reasons if anything fails. The Website workflow runs it on branch pushes; locally set
PW_CHROMIUM to a Chromium executable if Playwright's own isn't installed.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import sys
import threading
from pathlib import Path


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

    def new_context(self, **options):
        ctx = self._browser.new_context(**options)
        ctx.on("request", self._note)
        return ctx

    def _note(self, request) -> None:
        url = request.url
        if not url.startswith((self.base, "data:", "blob:")):       # a data: picture makes no request at all
            self.offsite.append(url)

    def __getattr__(self, name):                                     # launch and close belong to the browser
        return getattr(self._browser, name)


def check(root: Path) -> list[str]:
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
                main = sum(1 for t in data["towns"] if not t.get("minor"))
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

            for extra in (lambda: check_menu_rows(browser, base), lambda: check_no_outline_key(browser, base, data),
                          lambda: check_phone_legend(browser, base, data),
                          lambda: check_empty_layer_switch(browser, base, data),
                          lambda: check_card_words(browser, base, root),
                          lambda: check_satellite(browser, base, data)):
                try:
                    problems += extra()
                except Exception as e:                                      # noqa: BLE001 - report, don't crash
                    problems.append(f"a check could not run: {str(e).splitlines()[0]}")

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


def check_menu_rows(browser, base) -> list[str]:
    """Phones held sideways and short windows: the layer menu sits over the timeline and every row
    (scrolled into the menu's view if need be) takes a tap at its centre."""
    problems = []
    ctx = browser.new_context(viewport={"width": 844, "height": 390}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
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
    page.goto(base + "map.html", wait_until="load")
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


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0] if args else "_site")
    problems = check(root)
    if problems:
        print("Map smoke test failed:\n- " + "\n- ".join(problems))
        return 1
    print("Map smoke test passed: page, frames, basemap, bubbles, play, layers and card all work, "
          "and no request went to another site.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
