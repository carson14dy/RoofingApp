"""Check that no page of the built site is wider than the screen (AGENTS.md rule 8, DESIGN.md: 288 to
1440 px without sideways scroll).

    python tools/smoke_pages.py _site

Serves the built site on a local port and opens every page (Now, map, storm reports, about and each
town page) in Chromium (Playwright) at 288, 320, 375, 390, 768, 1280 and 1440 px, in light and dark. A page
fails when the document is wider than the window, and the outermost elements past the edge are
named. Measured with a desktop-style window of the phone's width: a mobile browser zooms out or
lets the page slide sideways instead, which is the bug this checks for. Exits 1 with the reasons if
anything fails. The Website workflow runs it on branch pushes; locally set PW_CHROMIUM to a Chromium
executable if Playwright's own isn't installed.

On a --hail-history build the five-season table of each town page is checked too, at TABLE_WIDTHS: no sideways scroll,
and one card per row (the row's label first, each cell named by its season) below CARD_BELOW px. At 390 px the page's jump
link to the five-year history (D39) must be on the first screen, and its target must be on the page.
"""
from __future__ import annotations

import functools
import http.server
import os
import sys
import threading
from pathlib import Path

WIDTHS = (288, 320, 375, 390, 768, 1280, 1440)
# The five-season table on each town page (B5, summary.py; --hail-history builds): a table from 900 px up, and one card
# per row below 900 px with the row's label first and each season named on its cell (no sideways scroll at any width).
TABLE_WIDTHS = (288, 320, 375, 390, 640, 768, 899, 900, 1280, 1440)
CARD_BELOW = 900


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):          # one line per file would bury the result
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # Leaving a page while its map pictures load closes the connection mid-file; that's expected.
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    httpd = QuietServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"

# The outermost elements whose right edge passes the window, skipping any that a scroll box or a
# clipping box contains (an absolutely positioned element counts as outside a box that isn't its
# containing block, as the browser lays it out).
PAST_THE_EDGE = """() => {
  const W = window.innerWidth;
  const contained = el => {
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      if (getComputedStyle(a).overflowX !== 'visible' && a.contains(el)) {
        let cb = el.offsetParent; // the containing block for positioned elements
        if (getComputedStyle(el).position !== 'absolute' || (cb && (a === cb || a.contains(cb)))) return true;
      }
    }
    return false;
  };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.right <= W + 0.5 || contained(el) || getComputedStyle(el).position === 'fixed') continue;
    let p = el.parentElement, outer = true;
    for (; p && p !== document.body; p = p.parentElement) if (p.getBoundingClientRect().right > W + 0.5) { outer = false; break; }
    if (outer) out.push(el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/).join('.') : '')
      + ' (' + Math.round(r.right - W) + ' px past, "' + (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 30) + '")');
  }
  return {over: document.documentElement.scrollWidth - W, past: out.slice(0, 4)};
}"""


# The five-season table of a town page, read from the page: whether the table is a table or one card per row, whether each
# row's header comes first, whether every cell names its season, and how far the page and the table box scroll sideways.
TABLE_CHECK = """() => {
  const W = window.innerWidth;
  const t = document.querySelector('table.five');
  if (!t) return {present: false};
  const rows = [...t.querySelectorAll('tbody > tr')];
  const card = getComputedStyle(t.querySelector('thead')).position === 'absolute';
  const headFirst = rows.every(r => r.firstElementChild && r.firstElementChild.tagName === 'TH'
                                    && r.firstElementChild.classList.contains('row-head'));
  const blockRows = rows.every(r => getComputedStyle(r).display === 'block');
  const labelled = [...t.querySelectorAll('tbody td')].every(td => td.hasAttribute('data-label'));
  const box = t.closest('.table-box');
  return {present: true, card, rows: rows.length, headFirst, blockRows, labelled,
          over: document.documentElement.scrollWidth - W, boxScroll: box ? box.scrollWidth - box.clientWidth : 0};
}"""


# The jump link to a town page's five-year history (D39): its target is on the page, and the link is on the first screen.
JUMP_CHECK = """() => {
  const a = document.querySelector('a[href="#history"]');
  if (!a) return null;
  const target = document.getElementById('history');
  const r = a.getBoundingClientRect();
  return {present: !!target, onFirstScreen: r.top >= 0 && r.bottom <= window.innerHeight};
}"""

TABLES_CHECKED: dict[int, int] = {}      # width -> the town pages whose five-season table was read at that width


def check_tables(root: Path, base: str, browser, problems: list[str]) -> None:
    """Every town page's five-season table at TABLE_WIDTHS: no sideways scroll, one card per row below CARD_BELOW (the row
    header first, each cell labelled with its season). A page with no table (a build without --hail-history) is skipped."""
    pages = sorted(f"town/{p.name}" for p in (root / "town").glob("*.html"))
    for width in TABLE_WIDTHS:
        ctx = browser.new_context(viewport={"width": width, "height": 800})
        page = ctx.new_page()
        for name in pages:
            page.goto(base + name, wait_until="load")
            res = page.evaluate(TABLE_CHECK)
            if not res.get("present"):
                continue
            TABLES_CHECKED[width] = TABLES_CHECKED.get(width, 0) + 1
            if res["over"] > 0:
                problems.append(f"{name} at {width} px: the page is {res['over']} px wider than the screen (the table)")
            if res["boxScroll"] > 0:
                problems.append(f"{name} at {width} px: the table scrolls sideways inside its box by {res['boxScroll']} px")
            if not res["labelled"]:
                problems.append(f"{name} at {width} px: a table cell does not name its season")
            if width < CARD_BELOW and not (res["card"] and res["blockRows"] and res["headFirst"]):
                problems.append(f"{name} at {width} px: the table does not reflow to one card per row with the label first")
            if width >= CARD_BELOW and res["card"]:
                problems.append(f"{name} at {width} px: the table is cards where it should be a table")
            if width == 390:
                # D39: the jump link to the history is on the first screen, and the history's table leads its heading
                link = page.evaluate(JUMP_CHECK)
                if link is None or not link["present"]:
                    problems.append(f"{name} at 390 px: the page has no jump link to its five-year history")
                elif not link["onFirstScreen"]:
                    problems.append(f"{name} at 390 px: the jump link to the history is below the first screen")
        ctx.close()


def check(root: Path) -> list[str]:
    from playwright.sync_api import sync_playwright

    pages = ["index.html", "map.html", "reports.html", "about.html"]
    pages += sorted(f"town/{p.name}" for p in (root / "town").glob("*.html"))
    problems: list[str] = []
    httpd, base = serve(root)
    launch = {"executable_path": os.environ["PW_CHROMIUM"]} if os.environ.get("PW_CHROMIUM") else {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch)
            for scheme in ("light", "dark"):
                for width in WIDTHS:
                    ctx = browser.new_context(viewport={"width": width, "height": 800}, color_scheme=scheme)
                    page = ctx.new_page()
                    for name in pages:
                        page.goto(base + name, wait_until="load")
                        if name == "map.html":
                            page.wait_for_timeout(1000)        # the map lays out after its data loads
                        res = page.evaluate(PAST_THE_EDGE)
                        if res["over"] > 0:
                            problems.append(f"{name} at {width} px ({scheme}) is {res['over']} px wider than the "
                                            f"screen: " + ("; ".join(res["past"]) or "no single element named"))
                    ctx.close()
            check_tables(root, base, browser, problems)
            browser.close()
    finally:
        httpd.shutdown()
    return problems


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0] if args else "_site")
    problems = check(root)
    if problems:
        print("Page width check failed:\n- " + "\n- ".join(problems))
        return 1
    print(f"Page width check passed: every page fits the screen at {', '.join(map(str, WIDTHS))} px, light and dark.")
    if TABLES_CHECKED:
        widths = ", ".join(f"{w} px: {n} pages" for w, n in sorted(TABLES_CHECKED.items()))
        print(f"Five-season table check passed on town pages (no sideways scroll; cards below {CARD_BELOW} px): {widths}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
