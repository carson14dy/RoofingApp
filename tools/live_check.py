"""Check the public site after the B1 go-live: map.json's hail block, the hail index, the tap-anywhere sheet at the
Benchland point (?at=47.08,-110.02) in Chromium at 390 and 1280 px, and a town page's hail table."""
import json, sys, time, urllib.request
BASE = "https://carson14dy.github.io/RoofingApp/"
def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return r.read()
problems = []
m = json.loads(get("data/map.json"))
hail = m.get("hail") or {}
print("built:", m.get("built"), "| hail block state:", hail.get("state"), "| keys:", list(hail)[:12])
if hail.get("state") != "loaded":
    problems.append(f"map.json hail state is {hail.get('state')!r}")
try:
    idx = json.loads(get("hail/index.json"))
    print("hail/index.json: as_of", idx.get("as_of"), "days", idx.get("days_present"), "of", idx.get("days_expected"), "events", idx.get("events"))
except Exception as e:
    problems.append(f"hail/index.json: {e}")
town = get("town/billings.html").decode("utf-8", "replace")
if "Hail history, five years" in town and "radar-estimated hail" in town:
    print("town page: the hail history section is present")
else:
    problems.append("town/billings.html has no hail history section")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    for w, h in ((390, 844), (1280, 800)):
        page = b.new_page(viewport={"width": w, "height": h})
        offsite = []
        page.on("request", lambda r: offsite.append(r.url) if not r.url.startswith(BASE) and not r.url.startswith("data:") else None)
        page.goto(BASE + "map.html?at=47.08,-110.02", wait_until="networkidle", timeout=90000)
        text = ""
        for _ in range(30):
            text = page.evaluate("() => { const s = document.getElementById('sheet'); return s && !s.hidden ? document.getElementById('sheet-body').innerText : ''; }") or ""
            if text and "loading" not in text.lower(): break
            time.sleep(1)
        page.screenshot(path=f"/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/live-{w}.png")
        print(f"--- sheet at {w} px ({len(text)} chars):"); print(text[:900])
        if "radar" not in text.lower(): problems.append(f"sheet at {w} px has no radar wording")
        if offsite: problems.append(f"off-site requests at {w} px: {offsite[:3]}")
        page.close()
    b.close()
print("PROBLEMS:", problems if problems else "none")
sys.exit(1 if problems else 0)
