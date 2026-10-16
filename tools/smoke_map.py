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
no town under either card's caption; a town stays clear of its sheet when the phone turns. Exits 1
with the reasons if anything fails. The Website workflow runs it on branch pushes; locally set
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
    built = int(datetime.fromisoformat(data["built"].replace("Z", "+00:00")).timestamp() * 1000)

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
