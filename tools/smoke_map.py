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
timeline, and the Precipitation layer rings no town; a zoom by double-click or the = key holds through
a layer switch, and on a map nobody moved a layer switch fits Montana as a fresh load does; no
basemap name sticks out from under a panel or the card's caption, or sits on the note's line, also
once a banner comes on a map the viewer moved; a picture that fails says so in the note and the
slider's words, and keeps no coverage-gap key; My location outside the map's area says so in the
toast and offers no chip; the Storm reports card shows no reports banner, and on a phone, with a
banner and its caption's line counting alerts without an outline, opens at the Now card's zoom with
no town under either card's caption; a town stays clear of its sheet when the phone turns; with a
town's sheet open on a phone, no basemap name sticks out from under its edge and no town shows under
a panel or that edge; a phone's first view draws the minor towns as dots whose dot and name open
their sheet, and a minor town hidden there shows once zoomed in to its dot_zoom; a town with an alert
(or a failed alert check) opens its sheet and leads its List row with the alert; with storm reports
on, a town name (or a minor town's dot name) moves off a report circle lying on it. Exits 1 with the
reasons if anything fails. The Website workflow runs it on branch pushes; locally set PW_CHROMIUM to
a Chromium executable if Playwright's own isn't installed.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):          # one line per file would bury the result
        pass


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(QuietHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def check(root: Path) -> list[str]:
    from playwright.sync_api import sync_playwright

    problems: list[str] = []
    data = json.loads((root / "data" / "map.json").read_text(encoding="utf-8"))
    precip_frames = len(data["layers"].get("precip", {}).get("frames", []))
    httpd, base = serve(root)
    launch = {"executable_path": os.environ["PW_CHROMIUM"]} if os.environ.get("PW_CHROMIUM") else {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch)
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
                          lambda: check_phone_legend(browser, base, data), lambda: check_zoom_holds(browser, base),
                          lambda: check_switch_fit(browser, base), lambda: check_names_clear(browser, base),
                          lambda: check_names_after_banner(browser, base, data),
                          lambda: check_failed_picture(browser, base, data), lambda: check_location(browser, base),
                          lambda: check_reports_card(browser, base, data), lambda: check_sheet_turn(browser, base),
                          lambda: check_sheet_names(browser, base, data),
                          lambda: check_town_alerts_first(browser, base, data),
                          lambda: check_names_off_reports(browser, base, data),
                          lambda: check_names_off_reports(browser, base, data, "Lewistown", (1024, 768)),
                          lambda: check_minor_dots(browser, base, data),
                          lambda: check_empty_layer_switch(browser, base, data),
                          lambda: check_card_words(browser, base, root)):
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


# how far apart two town bubbles are, in px: it doubles with each zoom level
APART = ("() => { const b = [...document.querySelectorAll('.leaflet-marker-icon.town:not(.minor)')].slice(0, 2)"
         ".map(e => e.getBoundingClientRect()); return Math.hypot(b[0].x - b[1].x, b[0].y - b[1].y); }")


# each town as drawn: "bubble", "dot" (map.css .town.is-dot: a small dot, no number) or "" (hidden),
# and its bubble's (or dot's) centre
FORMS = """() => Object.fromEntries([...document.querySelectorAll('.leaflet-marker-icon.town')].map(t => {
  const b = t.querySelector('.bubble').getBoundingClientRect(), shown = getComputedStyle(t).display !== 'none';
  const form = !shown ? '' : b.width < 16 && getComputedStyle(t.querySelector('.bubble')).fontSize === '0px' ? 'dot' : 'bubble';
  return [t.querySelector('.tname').textContent, [form, b.left + b.width / 2, b.top + b.height / 2]]; }))"""

# the centre of a town's dot (or bubble) or name, if a tap there reaches the town and not something over it
TAP_AT = """([name, part]) => { const t = [...document.querySelectorAll('.leaflet-marker-icon.town')]
    .find(e => e.querySelector('.tname').textContent === name);
  const r = t.querySelector(part).getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  const hit = document.elementFromPoint(x, y);
  return hit && t.contains(hit) ? [x, y] : null; }"""


def page_zoom(page, data, forms) -> float:
    """The map's zoom, from how far apart two bubble towns are drawn (Web Mercator, 256 px tiles)."""
    import math

    def world(t):                                         # px at zoom 0
        return ((t["lon"] + 180) / 360 * 256,
                (1 - math.log(math.tan(math.pi / 4 + math.radians(t["lat"]) / 2)) / math.pi) / 2 * 256)
    a, b = [t for t in data["towns"] if not t.get("minor")][:2]
    (ax, ay), (bx, by) = world(a), world(b)
    fa, fb = forms[a["name"]], forms[b["name"]]
    return math.log2(math.hypot(fa[1] - fb[1], fa[2] - fb[2]) / math.hypot(ax - bx, ay - by))


def check_minor_dots(browser, base, data) -> list[str]:
    """The map a phone opens (zoom 5.25-5.5) draws the towns its List names: each minor town as a dot
    and a name from its towns.json dot_zoom (map.js townForm), a bubble from zoom 7, and a tap on the
    dot or the name opens its sheet. A minor town below its dot_zoom (Livingston, whose dot touches
    Bozeman's bubble below zoom 6.25) shows once the map is zoomed in to it, clear to tap."""
    minor = [t for t in data["towns"] if t.get("minor")]
    if not minor:
        return []
    problems = []
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce", has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
    page.evaluate("() => document.fonts.ready.then(() => true)")
    page.wait_for_timeout(500)

    def want(t, z):
        if not t.get("minor") or z >= 7 - 1e-6:
            return "bubble"
        return "dot" if t.get("dot_zoom") is not None and z >= t["dot_zoom"] - 1e-6 else ""

    forms = page.evaluate(FORMS)
    z = page_zoom(page, data, forms)
    for t in data["towns"]:
        if forms[t["name"]][0] != want(t, z):
            problems.append(f"phone at zoom {z:.2f}: {t['name']} is drawn as {forms[t['name']][0] or 'nothing'}, "
                            f"want {want(t, z) or 'nothing'}")
    for t in minor:
        if forms[t["name"]][0] != "dot":
            continue
        for part, what in ((".bubble", "dot"), (".tname", "name")):
            xy = page.evaluate(TAP_AT, [t["name"], part])
            if not xy:
                problems.append(f"phone: {t['name']}'s {what} can't take a tap (something covers it)")
                continue
            page.touchscreen.tap(*xy)
            page.wait_for_timeout(250)
            title = page.locator("#sheet-title").inner_text() if page.locator("#sheet").is_visible() else None
            if title != t["name"]:
                problems.append(f"phone: a tap on {t['name']}'s {what} opened {title or 'nothing'}")
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
    late = [t for t in minor if t.get("dot_zoom") is not None and t["dot_zoom"] > z + 1e-6]
    if late:
        page.focus("#map")
        while z < max(t["dot_zoom"] for t in late) - 1e-6:
            page.keyboard.press("Equal")                       # +0.5 (zoomDelta)
            page.wait_for_timeout(500)
            z = page_zoom(page, data, page.evaluate(FORMS))
        forms = page.evaluate(FORMS)
        for t in late:
            if forms[t["name"]][0] != "dot":
                problems.append(f"phone at zoom {z:.2f}: {t['name']} is still not drawn (dot_zoom {t['dot_zoom']})")
            elif not page.evaluate(TAP_AT, [t["name"], ".bubble"]):
                problems.append(f"phone at zoom {z:.2f}: {t['name']}'s dot is covered (by another town's bubble?)")
    ctx.close()
    return problems


def check_zoom_holds(browser, base) -> list[str]:
    """A zoom by the viewer stays where they put it: a double-click and the = key zoom in, and a layer
    switch afterwards doesn't fit Montana again (a refit once undid every desktop zoom but the
    wheel's). The zoom is read as the distance between two town bubbles (APART)."""
    problems = []
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
    page.wait_for_timeout(500)
    spot = page.evaluate("""() => {          // a spot of bare map: no bubble, outline, report or panel on it
      const m = document.getElementById('map').getBoundingClientRect();
      for (let y = m.top + m.height * 0.3; y < m.bottom - m.height * 0.3; y += 10)
        for (let x = m.left + m.width * 0.3; x < m.right - m.width * 0.3; x += 10) {
          const e = document.elementFromPoint(x, y);
          if (e && e.closest('#map') && !e.closest('.leaflet-marker-icon') && !e.classList.contains('leaflet-interactive')) return [x, y];
        }
      return null; }""")
    if not spot:
        ctx.close()
        return ["zoom: no bare spot of the map to double-click"]
    before = page.evaluate(APART)
    page.mouse.dblclick(spot[0], spot[1])                  # +0.5 (zoomDelta)
    page.wait_for_timeout(600)
    page.focus("#map")
    page.keyboard.press("Equal")                            # +0.5
    page.wait_for_timeout(600)
    zoomed = page.evaluate(APART)
    page.click("#btn-layers")
    page.get_by_role("radio", name="Temperature").check()
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    after = page.evaluate(APART)
    if zoomed < before * 1.8:
        problems.append(f"zoom: a double-click and the = key didn't hold (towns {before:.0f} -> {zoomed:.0f} px apart, want about twice)")
    elif abs(after - zoomed) > zoomed * 0.02:
        problems.append(f"zoom: a layer switch undid the viewer's zoom (towns {zoomed:.0f} -> {after:.0f} px apart)")
    ctx.close()
    return problems


def check_switch_fit(browser, base) -> list[str]:
    """On a phone map the viewer hasn't moved, a layer switch fits Montana where a fresh load of that
    layer does: the new scale and keys change the height of the legend above Montana (a fit made
    before the new keys were drawn once left it off by half a key row)."""
    def first_bubble(query, switch_to=None):
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(base + "map.html" + query, wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
        page.wait_for_timeout(600)
        if switch_to:
            page.click("#btn-layers")
            page.get_by_role("radio", name=switch_to).check()
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
        at = page.evaluate("() => { const r = document.querySelector('.leaflet-marker-icon.town .bubble')"
                           ".getBoundingClientRect(); return [r.x, r.y]; }")
        ctx.close()
        return at
    fresh, switched = first_bubble("?layer=wind"), first_bubble("?layer=precip", "Wind gusts")
    if max(abs(fresh[0] - switched[0]), abs(fresh[1] - switched[1])) > 1.5:
        return [f"layer switch: Montana sits {switched[1] - fresh[1]:+.0f} px from where a fresh Wind gusts map puts it"]
    return []


# basemap names on screen that meet a glass panel, the card's caption or Open map, or the note's line
NAMES_CUT = """() => {
  const text = (e) => { const r = document.createRange(); r.selectNodeContents(e); return r.getBoundingClientRect(); };
  const shown = (e) => e && !e.hidden && e.offsetParent !== null;
  const boxes = ['legend', 'buttons', 'timeline', 'near-chip', 'card-chip', 'card-open'].map(id => document.getElementById(id))
    .concat([document.querySelector('#top .close')], [...document.getElementById('banners').children]).filter(shown)
    .map(e => e.getBoundingClientRect()).filter(r => r.width > 2 && r.height > 2);
  const note = document.getElementById('frame-note');
  if (shown(note)) { const r = text(note); boxes.push({left: r.left - 24, right: r.right + 24, top: r.top, bottom: r.bottom}); }
  return [...document.querySelectorAll('#map .bm-label:not(.bm-hide)')].filter(e => getComputedStyle(e).display !== 'none')
    .filter(e => { const r = text(e.querySelector('span')), left = e.querySelector('i') ? r.left - 10 : r.left;
      return r.width && boxes.some(b => left < b.right && r.right > b.left && r.top < b.bottom && r.bottom > b.top); })
    .map(e => e.textContent); }"""


def check_names_clear(browser, base) -> list[str]:
    """No basemap name sticks out from under a glass panel, the card's caption or Open map, or sits on
    the note's line (map.js tidyLabels hides them): as the map opens on a phone and on a laptop, on
    the phone with the legend's (i) note open, and in the card. On a phone the covered half of such
    a name blurs under the glass and the rest reads as a broken word."""
    problems = []
    for w, h, query, info in ((390, 844, "", False), (390, 844, "", True), (1440, 900, "", False),
                              (358, 320, "?card=1", False)):
        ctx = browser.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(base + "map.html" + query, wait_until="load")
        page.wait_for_selector("#map .bm-label", state="attached", timeout=15000)
        page.evaluate("() => document.fonts.ready.then(() => true)")
        page.wait_for_timeout(500)
        if info:
            page.click("#legend-info")
            page.wait_for_timeout(300)
        cut = page.evaluate(NAMES_CUT)
        if cut:
            problems.append(f"names at {w}x{h}{query}{' with the (i) note open' if info else ''}: "
                            f"{', '.join(cut[:4])} cut by a panel or on the note's line")
        ctx.close()
    return problems


def check_failed_picture(browser, base, data) -> list[str]:
    """A picture that doesn't load never reads as a clear sky (AGENTS.md rule 5): the note and the
    slider's words for screen readers say it didn't load, and no "no coverage" key stays for a gap
    that isn't drawn."""
    precip = data["layers"].get("precip", {})
    order = precip.get("modes", {}).get("12h", [])
    if len(order) < 3:
        return []
    name = precip["frames"][order[1]]["src"].split("/")[-1].split("?")[0]
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**/map/frames/" + name + "*", lambda r: r.abort())
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
    page.focus("#range")
    page.keyboard.press("Home")
    page.wait_for_timeout(600)
    page.keyboard.press("ArrowRight")                      # the timeline's second frame: its picture fails
    page.wait_for_timeout(1000)
    st = page.evaluate("""() => ({value: document.getElementById('range').getAttribute('aria-valuetext') || '',
      note: document.getElementById('frame-note').textContent,
      gapKey: [...document.querySelectorAll('#legend-keys li')].some(li => getComputedStyle(li).visibility !== 'hidden'
        && /^(No radar coverage|No model data)$/.test(li.textContent.trim()))})""")
    ctx.close()
    problems = []
    if "didn't load" not in st["note"] or "didn't load" not in st["value"] or "not an all-clear" not in st["value"]:
        problems.append(f"failed picture: the note or the slider's words don't say it didn't load "
                        f"(note {st['note']!r}; slider {st['value']!r})")
    if st["gapKey"]:
        problems.append("failed picture: the legend still names a coverage gap that isn't drawn")
    return problems


def check_location(browser, base) -> list[str]:
    """My location: inside the map the chip names the nearest town and the toast is only read out (it
    says the same); outside the map's area the toast says so, with the nearest town and its
    distance, and no chip offers a town hundreds of miles away."""
    problems = []
    for where, lat, lon, inside in (("Bozeman", 45.68, -111.04, True), ("Denver", 39.74, -104.99, False)):
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce", permissions=["geolocation"],
                                  geolocation={"latitude": lat, "longitude": lon, "accuracy": 500})
        page = ctx.new_page()
        page.goto(base + "map.html", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
        page.get_by_role("button", name="Show my location").click()
        page.wait_for_function("() => document.getElementById('toast').textContent.includes('Nearest town')", timeout=10000)
        st = page.evaluate("""() => { const t = document.getElementById('toast');
          return {toast: t.textContent, shown: t.classList.contains('show') && !t.classList.contains('quiet'),
                  chip: !document.getElementById('near-chip').hidden}; }""")
        ctx.close()
        if inside and (not st["chip"] or st["shown"]):
            problems.append(f"location in {where}: want the nearest-town chip and the toast only read out ({st})")
        if not inside and (st["chip"] or not st["shown"] or "outside" not in st["toast"]):
            problems.append(f"location in {where}: want the toast to say it is outside the map, and no chip ({st})")
    return problems


def failed_reports(data) -> str:
    """map.json as if the SPC report files had failed (for page.route)."""
    import json as _json
    failed = _json.loads(_json.dumps(data))
    failed["reports"] = []
    failed.setdefault("status", {})["reports"] = {"label": "SPC storm reports", "ok": False, "detail": "a test failure"}
    return _json.dumps(failed)


def check_names_after_banner(browser, base, data) -> list[str]:
    """A banner that comes after the viewer moved the map refits nothing (here Storm reports, turned on
    when the report files failed): the names it and the panels it pushes down cover are hidden then
    too (map.js banner)."""
    body = failed_reports(data)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**/data/map.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector("#map .bm-label", state="attached", timeout=15000)
    page.evaluate("() => document.fonts.ready.then(() => true)")
    page.wait_for_timeout(500)
    page.focus("#map")
    page.keyboard.press("ArrowDown")                       # the viewer moves the map
    page.wait_for_timeout(400)
    page.click("#btn-layers")
    page.check("#tg-reports")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    cut = page.evaluate(NAMES_CUT)
    banner = page.locator("#reports-banner").count()
    ctx.close()
    if not banner:
        return ["names after a banner: turning on Storm reports with failed report files showed no banner"]
    return [f"names after a banner: {', '.join(cut[:4])} cut by a panel once the reports banner came"] if cut else []


# towns (bubble or name) under the card's caption or Open map
CARD_UNDER = """() => { const p = ['card-chip', 'card-open'].map(id => document.getElementById(id).getBoundingClientRect());
  return [...document.querySelectorAll('.leaflet-marker-icon.town')].filter(t => getComputedStyle(t).display !== 'none')
    .filter(t => [...t.querySelectorAll('.bubble, .tname')].map(e => e.getBoundingClientRect()).some(r => r.width
      && p.some(b => Math.min(r.right, b.right) - Math.max(r.left, b.left) > 1 && Math.min(r.bottom, b.bottom) - Math.max(r.top, b.top) > 1)))
    .map(t => t.querySelector('.tname').textContent); }"""


def check_reports_card(browser, base, data) -> list[str]:
    """The Storm reports card has no reports banner when the report files failed (the page says so
    above and below the card). On a phone, with a banner (the build's own, or a one-line test banner
    when it shows none) and its caption's extra line ("1 alert has no outline"), it opens at the Now
    card's zoom (APART; style.css .map-card-tall gives it the room) and no town is under either card's
    caption or Open map. The banner, then that line, once zoomed it out until the town names piled up."""
    import json as _json
    import re
    from datetime import datetime
    problems = []
    failed = failed_reports(data)
    ctx = browser.new_context(viewport={"width": 358, "height": 320}, reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**/data/map.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=failed))
    page.goto(base + "map.html?card=1&overlay=reports", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
    page.wait_for_timeout(300)
    if page.locator("#reports-banner").count():
        problems.append("Storm reports card: shows the reports banner, which the page around it already says")
    ctx.close()

    body = _json.loads(_json.dumps(data))
    items = body["alerts"]["items"]
    if all(a.get("geometry") for a in items):               # the caption's extra line needs one
        items.append({"id": "smoke-no-outline", "event": "Winter Weather Advisory", "kind": "advisory", "headline": "",
                      "area": "Hill; Blaine", "severity": "Moderate", "sender": "", "sent": data["built"],
                      "onset": None, "until": None, "description": "", "instruction": "", "geometry": None})
    body = _json.dumps(body)
    # the page-age check reads <body data-built>, which can differ from map.json's "built" (an old fixture)
    stamp = re.search(r'data-built="(\d+)"', urllib.request.urlopen(base + "index.html").read().decode("utf-8"))
    built = int(stamp.group(1)) if stamp else int(datetime.fromisoformat(data["built"].replace("Z", "+00:00")).timestamp() * 1000)

    def a_banner(route):                                     # a one-line banner when the build shows none
        r = route.fetch()
        html = re.sub(r'id="banners">\s*</div>', 'id="banners"><p class="banner banner-info">A test banner.</p></div>',
                      r.text(), count=1)
        route.fulfill(response=r, body=html)

    seen = {}
    for name in ("index.html", "reports.html"):
        ctx = browser.new_context(viewport={"width": 360, "height": 740}, reduced_motion="reduce")
        ctx.add_init_script("Date.now = () => Math.round(%d + performance.now());" % built)   # no page-age banner
        page = ctx.new_page()
        page.route("**/data/map.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
        page.route(re.compile(r"/map\.html\?card=1"), a_banner)
        page.goto(base + name, wait_until="load")
        page.locator("iframe.map-card").scroll_into_view_if_needed()       # it loads lazily
        frame = None
        for _ in range(75):
            frame = next((f for f in page.frames if "card=1" in f.url), None)
            if frame and frame.locator(".leaflet-marker-icon.town").count():
                break
            page.wait_for_timeout(200)
        frame.evaluate("() => document.fonts.ready.then(() => true)")
        page.wait_for_timeout(600)
        seen[name] = {"apart": frame.evaluate(APART), "under": frame.evaluate(CARD_UNDER),
                      "banners": frame.locator("#banners > *").count(), "line": frame.locator("#card-chip .card-alerts").count()}
        ctx.close()
    now, rep = seen["index.html"], seen["reports.html"]
    if not (now["banners"] == rep["banners"] == 1):
        problems.append(f"Storm reports card: want one banner in each card, found {now['banners']} and {rep['banners']}")
    if not rep["line"]:
        problems.append("Storm reports card: the caption doesn't count the alert without an outline")
    if rep["apart"] < now["apart"] * 0.98:
        problems.append(f"Storm reports card: opens zoomed out from the Now card on a 360 px phone with a banner "
                        f"(towns {now['apart']:.0f} -> {rep['apart']:.0f} px apart)")
    for name, st in seen.items():
        if st["under"]:
            problems.append(f"{name} card: {', '.join(st['under'][:3])} under the caption or Open map on a 360 px phone")
    return problems


def check_sheet_turn(browser, base) -> list[str]:
    """A town's sheet open while the phone turns: the town (bubble and name) stays clear of the side
    sheet the turn brings (a turn once left the name under it)."""
    problems = []
    for town in ("Havre", "Glasgow"):
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        page = ctx.new_page()
        page.goto(base + "map.html", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
        page.wait_for_timeout(500)
        page.locator(".leaflet-marker-icon.town", has_text=town).first.click()
        page.wait_for_timeout(400)
        page.set_viewport_size({"width": 844, "height": 390})
        page.wait_for_timeout(800)
        under = page.evaluate("""(town) => { const s = document.getElementById('sheet').getBoundingClientRect();
          const t = [...document.querySelectorAll('.leaflet-marker-icon.town')].find(e => e.textContent.includes(town));
          return [t.querySelector('.bubble'), t.querySelector('.tname')].some(e => { const r = e.getBoundingClientRect();
            return r.left < s.right && r.right > s.left && r.top < s.bottom && r.bottom > s.top; }); }""", town)
        ctx.close()
        if under:
            problems.append(f"town sheet: after the phone turns, {town}'s bubble or name is under the sheet")
    return problems


# where a viewer taps a town's bubble: its centre, if the bubble is shown and nothing covers it there
TAP_POINT = """(name) => { const t = [...document.querySelectorAll('.leaflet-marker-icon.town')]
    .find(e => (e.querySelector('.tname') || {}).textContent === name);
  if (!t || getComputedStyle(t).display === 'none') return null;
  const r = t.querySelector('.bubble').getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  const hit = document.elementFromPoint(x, y);
  return hit && t.contains(hit) ? [x, y] : null; }"""

# basemap names on screen partly under the open sheet: they stick out from under its edge
SHEET_CUT = """() => { const s = document.getElementById('sheet').getBoundingClientRect();
  const text = (e) => { const r = document.createRange(); r.selectNodeContents(e); return r.getBoundingClientRect(); };
  return [...document.querySelectorAll('#map .bm-label:not(.bm-hide)')].filter(e => getComputedStyle(e).display !== 'none')
    .filter(e => { const r = text(e.querySelector('span'));
      if (!r.width || r.right < 0 || r.left > innerWidth || r.bottom < 0 || r.top > innerHeight) return false;
      const meets = r.left < s.right && r.right > s.left && r.top < s.bottom && r.bottom > s.top;
      return meets && !(r.left >= s.left && r.right <= s.right && r.top >= s.top && r.bottom <= s.bottom); })
    .map(e => e.textContent); }"""


# towns drawn on screen (bubble or dot, or name) partly under a panel or the open sheet's edge
SHEET_TOWNS = """() => { const R = (r) => ({l: r.left, t: r.top, r: r.right, b: r.bottom});
  const text = (e) => { const g = document.createRange(); g.selectNodeContents(e); return R(g.getBoundingClientRect()); };
  const md = document.querySelector('.mapdata');
  const panels = [document.getElementById('legend'), document.querySelector('.close'), document.getElementById('buttons'),
    ...document.getElementById('banners').children].filter(e => e && e.offsetParent !== null).map(e => R(e.getBoundingClientRect()))
    .concat(md && md.offsetParent !== null ? [text(md)] : []).filter(b => b.r - b.l > 2 && b.b - b.t > 2);
  const s = R(document.getElementById('sheet').getBoundingClientRect());
  const meet = (a, b) => a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t;
  const inside = (a, b) => a.l >= b.l && a.r <= b.r && a.t >= b.t && a.b <= b.b;
  return [...document.querySelectorAll('#map .leaflet-marker-icon.town')].filter(t => {
    const cs = getComputedStyle(t);
    if (cs.display === 'none' || cs.visibility !== 'visible') return false;
    return [R(t.querySelector('.bubble').getBoundingClientRect()), text(t.querySelector('.tname'))].some(b =>
      b.r > 0 && b.l < innerWidth && b.b > 0 && b.t < innerHeight && (panels.some(p => meet(b, p)) || (meet(b, s) && !inside(b, s))));
  }).map(t => t.querySelector('.tname').textContent); }"""


def check_sheet_names(browser, base, data) -> list[str]:
    """A town's sheet open on a phone: no basemap name is partly under it, sticking out from under its
    edge as a broken word (map.js tidyLabels counts the open sheet as a panel), and no town shows under
    a panel or the sheet's edge (reveal pans so the fewest are, tidyLabels hides the rest until the
    sheet closes). Every town whose bubble takes a tap is opened in turn, as a viewer would, and closed
    with Escape."""
    problems, opened = [], 0
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
    page.evaluate("() => document.fonts.ready.then(() => true)")
    page.wait_for_timeout(500)
    for t in data["towns"]:
        xy = page.evaluate(TAP_POINT, t["name"])
        if not xy:
            continue                                   # hidden at this zoom, or under a panel
        page.mouse.click(*xy)
        page.wait_for_timeout(250)
        if page.locator("#sheet").is_hidden() or page.locator("#sheet-title").inner_text() != t["name"]:
            problems.append(f"town sheet: a tap on {t['name']}'s bubble did not open its sheet")
        else:
            opened += 1
            cut = page.evaluate(SHEET_CUT)
            if cut:
                problems.append(f"town sheet 390x844: {', '.join(cut[:4])} {'sticks' if len(cut) == 1 else 'stick'} out "
                                f"from under the {t['name']} sheet")
            under = page.evaluate(SHEET_TOWNS)
            if under:
                problems.append(f"town sheet 390x844: with the {t['name']} sheet open, {', '.join(under[:4])} "
                                f"{'shows' if len(under) == 1 else 'show'} under a panel or the sheet's edge")
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    ctx.close()
    return problems + ([] if opened else ["town sheet: no town's bubble took a tap at 390x844"])


SHEET_BLOCKS = """() => [...document.getElementById('sheet-body').children]
  .filter(e => !e.classList.contains('sample-tag'))
  .map(e => e.tagName + ':' + e.textContent.replace(/\\s+/g, ' ').trim())"""
LIST_ROWS = """() => Object.fromEntries([...document.querySelectorAll('#sheet-body [data-town]')]
  .map(r => [r.getAttribute('data-town'), r.querySelector('.row-meta').textContent.replace(/\\s+/g, ' ').trim()]))"""


def check_town_alerts_first(browser, base, data) -> list[str]:
    """A town with an active alert, or whose alert check failed, opens its sheet on "Official alerts",
    above the forecast's numbers (below them, "Sunny" and the limit line read like an all-clear before
    the warning); a town with no alert keeps the forecast first. The limit line names the page's
    limits, and the List leads each such town's row with its alert ("1 alert · ...", "Alerts not
    checked · ..."). The alerts are put in map.json here (Billings, Glasgow, Havre), so any build
    tests it."""
    import json as _json
    problems = []
    body = _json.loads(_json.dumps(data))
    towns = {t["slug"]: t for t in body["towns"]}
    if not all(s in towns for s in ("billings", "glasgow", "havre")):
        return ["town alerts: Billings, Glasgow or Havre is missing from map.json"]
    body["alerts"]["items"].append({"id": "smoke-alert", "event": "Severe Thunderstorm Warning", "kind": "warning",
                                    "headline": "", "area": "Yellowstone", "severity": "Severe", "sender": "",
                                    "sent": data["built"], "onset": None, "until": None, "description": "",
                                    "instruction": "", "geometry": None})
    towns["billings"]["alert_ids"] = ["smoke-alert"]
    towns["glasgow"]["alert_ids"] = None
    towns["havre"]["alert_ids"] = []
    body = _json.dumps(body)
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    page.route("**/data/map.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    page.goto(base + "map.html", wait_until="load")
    page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
    page.wait_for_timeout(500)
    limits = page.evaluate("() => JSON.parse(document.getElementById('app').getAttribute('data-limits'))")
    for name, first in (("Billings", True), ("Glasgow", True), ("Havre", False)):
        xy = page.evaluate(TAP_POINT, name)
        if not xy:
            problems.append(f"town alerts: {name}'s bubble takes no tap at 390x844")
            continue
        page.mouse.click(*xy)
        page.wait_for_timeout(250)
        blocks = page.evaluate(SHEET_BLOCKS)
        text = " ".join(blocks).replace("\u00a0", " ")
        leads = bool(blocks) and blocks[0].lower() == "h3:official alerts"
        if leads != first:
            problems.append(f"town sheet {name}: " + ("the official alerts don't come first" if first else
                            "opens on the alerts though it has none") + f" ({' | '.join(blocks[:3])[:160]})")
        if first and name == "Glasgow" and "Couldn\u2019t check NWS alerts" not in text:
            problems.append("town sheet Glasgow: a failed alert check isn't said")
        if "reaches a limit" in text:
            problems.append(f"town sheet {name}: still says 'reaches a limit'")
        if "under your limits" in text and f"gusts {limits['gust_mph']} mph" not in text:
            problems.append(f"town sheet {name}: the limit line doesn't name the gust limit ({limits['gust_mph']} mph)")
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    page.locator("#btn-list").click()
    page.wait_for_timeout(250)
    rows = page.evaluate(LIST_ROWS)
    if not rows.get("billings", "").startswith("1 alert \u00b7 "):
        problems.append(f"List: Billings's row doesn't lead with its alert ({rows.get('billings')!r})")
    if not rows.get("glasgow", "").startswith("Alerts not checked \u00b7 "):
        problems.append(f"List: Glasgow's row doesn't lead with 'Alerts not checked' ({rows.get('glasgow')!r})")
    if any("reaches a limit" in v for v in rows.values()):
        problems.append("List: a row still says 'reaches a limit'")
    ctx.close()
    return problems


# a town's name and its bubble centre, and every shown town's bubble centre (px)
TOWN_SPOTS = """(name) => { const out = {};
  document.querySelectorAll('.leaflet-marker-icon.town').forEach(e => { const b = e.querySelector('.bubble').getBoundingClientRect();
    if (b.width) out[e.querySelector('.tname').textContent] = [b.left + b.width / 2, b.top + b.height / 2]; });
  const t = [...document.querySelectorAll('.leaflet-marker-icon.town')].find(e => e.querySelector('.tname').textContent === name);
  const n = t.querySelector('.tname').getBoundingClientRect();
  return {bubbles: out, name: [n.left + n.width / 2, n.top + n.height / 2], cls: t.className, margin: t.querySelector('.tname').style.cssText}; }"""
# the report circle's box, the town name's box, and what a tap at the circle's centre reaches
REPORT_VS_NAME = """(name) => { const d = [...document.querySelectorAll('path.rep')].map(p => p.getBoundingClientRect())
    .find(r => r.width && r.right > 0 && r.left < innerWidth && r.bottom > 0 && r.top < innerHeight);
  const t = [...document.querySelectorAll('.leaflet-marker-icon.town')].find(e => e.querySelector('.tname').textContent === name);
  const n = t.querySelector('.tname').getBoundingClientRect();
  if (!d) return null;
  const hit = document.elementFromPoint(d.left + d.width / 2, d.top + d.height / 2);
  return {over: n.left < d.right && n.right > d.left && n.top < d.bottom && n.bottom > d.top,
          hit: hit ? String(hit.getAttribute('class') || '') : '', name: [n.left + n.width / 2, n.top + n.height / 2],
          cls: t.className, margin: t.querySelector('.tname').style.cssText}; }"""


def check_names_off_reports(browser, base, data, name="Glasgow", size=(390, 844)) -> list[str]:
    """Storm reports on, on a phone: a report circle right on a town's name (Glasgow's, put in map.json
    here) moves the name to a clear spot beside its bubble (map.js placeNamesOffReports), so the name
    reads and the circle stays whole: a tap at its centre opens the report, a tap on the name the town.
    With the overlay off the name is back on its towns.json side. Also run for a minor town's dot name
    (Lewistown at 1024 x 768, zoom 6.25+). Not Billings on a phone: with Miles City's name on its left,
    Billings's has no clear spot at 390 x 844, so it stays (with its halo), as designed."""
    import json as _json
    problems = []
    towns = {t["name"]: t for t in data["towns"]}
    w, h = size
    if name not in towns:
        return [f"names off reports: {name} is missing from map.json"]
    far = {"kind": "hail", "time": data["built"], "day": data["built"][:10], "lat": 30.0, "lon": -125.0, "place": "far away",
           "county": "", "state": "", "comments": "", "size_in": 1.0, "mph": None}

    def with_reports(reps):
        body = _json.loads(_json.dumps(data))
        body["reports"] = reps                          # the far one keeps the legend's report key in both loads
        body.setdefault("status", {})["reports"] = {"label": "SPC storm reports", "ok": True, "detail": "test"}
        return _json.dumps(body)

    def open_page(body):
        ctx = browser.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce")
        page = ctx.new_page()
        page.route("**/data/map.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
        page.goto(base + "map.html?overlay=reports", wait_until="load")
        page.wait_for_selector(".leaflet-marker-icon.town", timeout=15000)
        page.evaluate("() => document.fonts.ready.then(() => true)")
        page.wait_for_timeout(500)
        return ctx, page

    ctx, page = open_page(with_reports([far]))
    spots = page.evaluate(TOWN_SPOTS, name)
    ctx.close()
    pre = "dot-" if "is-dot" in spots["cls"].split() else "side-"      # the dot form's name has its own side
    home = next((c for c in spots["cls"].split() if c.startswith(pre)), "")
    t, (tx, ty) = towns[name], spots["bubbles"].get(name, (None, None))
    others = [(n, xy) for n, xy in spots["bubbles"].items() if n != name and n in towns]
    if tx is None or not others:
        return [f"names off reports: {name} or another town isn't shown at {w}x{h}"]
    u_name, (ux, uy) = max(others, key=lambda o: min(abs(o[1][0] - tx), abs(o[1][1] - ty)))
    u = towns[u_name]
    nx, ny = spots["name"]
    lat = t["lat"] + (ny - ty) * (u["lat"] - t["lat"]) / (uy - ty)
    lon = t["lon"] + (nx - tx) * (u["lon"] - t["lon"]) / (ux - tx)
    ctx, page = open_page(with_reports([far, dict(far, lat=lat, lon=lon, place="on the name")]))
    got = page.evaluate(REPORT_VS_NAME, name)
    if not got:
        problems.append(f"names off reports: the report put on {name}'s name isn't on the screen")
    else:
        if got["over"]:
            problems.append(f"names off reports: {name}'s name stays on a storm report circle at {w}x{h}")
        if "rep-hit" not in got["hit"]:
            problems.append(f"names off reports: a tap on the report's centre by {name} doesn't reach it ({got['hit']!r})")
        page.mouse.click(*got["name"])
        page.wait_for_timeout(250)
        if page.locator("#sheet").is_hidden() or page.locator("#sheet-title").inner_text() != name:
            problems.append(f"names off reports: a tap on {name}'s moved name doesn't open {name}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        page.locator("#btn-layers").click()
        page.get_by_role("switch", name="Storm reports").uncheck()
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        back = page.evaluate(TOWN_SPOTS, name)
        if home not in back["cls"].split() or back["margin"]:
            problems.append(f"names off reports: with the overlay off {name}'s name isn't back on its side ({back['cls']}; {back['margin']})")
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


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0] if args else "_site")
    problems = check(root)
    if problems:
        print("Map smoke test failed:\n- " + "\n- ".join(problems))
        return 1
    print("Map smoke test passed: page, frames, basemap, bubbles, play, layers and card all work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
