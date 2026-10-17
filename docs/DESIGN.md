# Design — Montana Hail Watch website

Design spec for the Montana Hail Watch website (D27), written 2026-10-14 with the design-playbook
method (frame → explore → make → validate → ship). It replaces the desktop app's design of
2026-10-11, which is parked with the app (`payload/`, `desktop/`). Decisions that bind the site
live in `DECISIONS.md`; this file says what the pages are and why. The code is `website/`; the
look is the tokens at the top of `website/static/style.css` (the map page's own glass look is in
`website/static/map/map.css`, section 8).

## 1. Frame

**Problem.** Carson, 2026-10-14: "It's too complicated and the design is ugly. Instead of an app
let's make a website first." The app asked crews to install software, set up jobs and territories,
and read six equal-weight sections on a dark screen before answering anything. The site answers
three questions with nothing to install or set up:
1. Is there an official warning in Montana right now, and where?
2. What will wind, gusts, rain or snow and temperature do in the next 12–24 hours in the towns we
   work?
3. Where was hail or damaging wind reported in the last three days?

**Users.**
- The owner or dispatcher on a desktop, 6:30–8:00 am and whenever a warning is issued.
- A crew lead on a phone in a truck or on a roof: sunlight, one hand, weak signal.
- A sales rep after a storm, looking for where hail was reported.

**Constraints.** Python builds every page (Jinja + Folium); no server, no framework, no accounts;
hand-written JavaScript only for what the browser alone can do (rule 4). Evidence honesty (rules 5
and 6): never a green "safe", missing data is a dash and a sentence, a failed check is never "no
alerts". No AI text. Montana now, contiguous US later (D24). Works from 320 px phones to 1440 px
desktops, in sunlight, and over a slow connection.

**Success criteria.**
| Metric | Method | Target |
|---|---|---|
| First-click success on "is there a warning near Bozeman?" | 5 crew/office users on a phone | ≥ 80% |
| Time to find the next-hours gusts for a named town on a phone | same sessions, stopwatch | ≤ 10 s |
| All-clear misreads (failed alert check, missing gusts, empty report day) | one comprehension question each | 0 of 5 |
| Text contrast, light and dark | computed for every token pair | ≥ 4.5:1 (lowest measured 5.86:1) |
| Horizontal scrolling | Chromium at 288–1440 px | none (measured) |
| Map labels covering each other or a town | `tests/test_site.py` + browser measurement | none |

**Principles, ranked for conflicts.**
1. **Evidence over reassurance.** No state of any page reads as an all-clear. A failed source says
   so, with the time and what to do.
2. **Three questions, three places.** Warnings, the next hours by town, storm reports. Nothing else
   competes for the first screen.
3. **Readable in a truck.** Light paper and dark ink for sunlight, large numbers, words beside every
   colour. Dark mode follows the phone's setting for night use.
4. **Say how old it is.** Every page shows when it was built and whether each source loaded; an old
   page says so in words.
5. **Nothing to set up.** No logins, settings or saved places. The URL is the product.

## 2. Information architecture

Four top-level pages and 14 town pages, two levels deep:
```
Now (index.html) ── town/<slug>.html × 14
Map (map.html, full screen; also a card on Now and Storm reports)
Storm reports (reports.html)
About (about.html)
```
Navigation is a top bar with four items; the map page has its own close button back to Now. Town
pages are reached from the town cards, from the town bubbles on the map and from the "Other towns"
row on every town page; each town page links back to its place on the map. Labels are the words crews
use: warnings, gusts, rain or snow, storm reports. Towns: ChatGPT's 13 pilot towns plus
Livingston, for the gap-wind corridor (D25).

## 3. Explore

**The decision this settles.** What the first screen is and what it looks like.

| # | Criterion | Kind |
|---|---|---|
| T1 | No state can read as an all-clear | threshold |
| T2 | Official warnings visible with no click, on a phone too | threshold |
| T3 | Static pages built by Python; JavaScript only for browser-only needs | threshold |
| T4 | Works at 320 px wide without sideways scrolling | threshold |
| X1 | Fewest elements before the first answer | trade-off |
| X2 | Storm picture stays useful during an active warning | trade-off |
| X3 | Legible in direct sunlight | trade-off |

**The spread.**
- **A · Field sheet.** Light paper look. Warnings list and map side by side on desktop, warnings
  first on a phone, then one card per town with the next 12 hours. Town pages hold the detail.
- **B · Storm desk.** The app's dark storm look carried over, a full-width radar map first, alerts
  and towns below it.
- **C · Town picker.** A list of towns first; pick one to see its warnings and forecast.

**Pressure test.** B: on a phone the full-width map pushes warnings below the fold (fails T2), and
dark grey on navy washes out in sunlight (loses X3); it is also the look Carson called ugly.
C: warnings are one tap away and the statewide picture disappears (fails T2, loses X2).
A: risk that the map is small on desktop during a storm; the map can be zoomed and links to the
live loop at weather.gov.

**Decision.** A. It meets every threshold. Rejected, and what brings each back: **B** returns as
a night or wall-display mode if crews ask for one; the dark mode of A already covers night use.
**C** returns when the site has saved jobs: a crew's own list beats a town list once it exists.

## 4. Make: the pages

**Layout.** Content width 72 rem with 16–24 px side margins. Now page: lead, then a 5 / 7 column
split at 960 px and wider (warnings left, map right), stacked below; then the town cards in an
auto-fill grid with a 17 rem minimum. Town page: a single column of alerts, the 24-hour table and
the 7-day list. Reports page: map and legend, then one table per reporting day.

**Hierarchy, in reading order.**
1. Header: mark, "Montana Hail Watch", Now · Storm reports · About.
2. Freshness line: "Updated Wed 9:02 am MDT · rebuilt every 10 minutes · 3 min ago", then which
   sources loaded and any problem in red words.
3. Now: warnings and advisories with a count (the six most urgent shown, the rest one tap away), the
   radar and warning-area map with its frame time, then "Next 12 hours by town".
4. Town card: name and the most urgent alert chip, temperature range, highest gust, highest chance
   of rain or snow, then either "6 of 12 hours flagged. First at 12:00 pm: Gusts 31 mph." or the
   honest alternative ("No hour reaches the limits above", or "Gust forecast unavailable, so gusts
   weren't checked").
5. Town page: official alerts at that point, the 24-hour table (time, gusts, wind, rain or snow,
   temperature, sky, reasons), the 7-day list with high and low on one row.

**Typography.** Atkinson Hyperlegible Next for text and Atkinson Hyperlegible Mono for numbers and
times, designed by the Braille Institute for low-vision legibility and served by the site
itself (no font service). Sizes 13 / 14 / 17 / 20 / 25 / 31 px; body 17 px; weights 400, 600
and 700. The mono zero has a slash by design, so 0 and O never mix in a time or speed.

**Colour.** Three tiers in `style.css`: raw scale (paper, ink, red, orange, amber, slate, night,
mist), semantic roles (`--color-warning`, `--color-flag`, …), component tokens (cards, chips).
Hazard colours follow the NWS order and every chip carries its word: warning red, watch orange,
advisory amber, statement slate. Flags (values over a limit) use orange text plus bold, never
colour alone. Contrast, computed:

| Pair | Light | Dark |
|---|---|---|
| Text on page / card | 15.9 / 17.2 | 14.9 / 13.2 |
| Muted text on card | 6.8 | 7.9 |
| Muted text on a warning card | 5.9 | 7.8 |
| Link on page | 6.5 | 9.6 |
| Flag text on card | 6.3 | 9.2 |
| Warning / watch / advisory / statement chip | 6.6 / 6.3 / 6.9 / 7.5 | 9.1 / 10.4 / 11.9 / 8.9 |

**Spacing.** 8 px base: 4, 8, 12, 16, 24, 32, 48, 64. Cards 16 px padding; sections 48 px apart.

**Map.** Leaflet 1.9.4 served by the site. USGS topo base in greyscale (inverted in dark mode) so
radar and warning colours stand out. Radar is NOAA's composite saved as one picture per build with
its frame time, at 72% opacity, so everyone sees the same frame the page describes. Warning
polygons use the chip colours. Towns are white dots with labels; each label's side is set in
`towns.json` so no label covers another or a dot. Maps narrower than 546 px open one zoom out, so
the four "minor" towns (Butte, Glendive, Lewistown, Livingston) hide there, dot and label; every
town keeps its card. Reports: hail in violet, sized by hail size; wind in teal.

**States.**
- Source: loaded · problem (with the reason) · stale (radar frame older than 15 minutes).
- Statewide alerts: verified list · verified-and-empty ("No active … That is not an all-clear") ·
  refresh failed with the last verified list and its time · couldn't check and nothing verified
  ("This is not an all-clear"). A failed refresh never empties the list.
- Town alerts: list · none at this point · "Alerts not checked" chip on the card.
- Forecast values: number · dash with "not available" for screen readers. A missing value never
  raises a flag and never passes one.
- Radar: shown with its frame time · not shown, with the reason.
- Page age: fresh · over 25 minutes old (the freshness line turns into a warning).

**Copy.** Plain words, sentence case, the fact first. Errors: "Couldn't load NWS alerts at
9:02 am. Below is the last list we verified, from 8:50 am. Alerts may have been issued or ended
since. Check NWS Billings, …". Empty: "No hail or wind reports in or near Montana for this day."
Footer: "Weather information only. It does not confirm roof damage and it is not a decision to
work or to stop work: check the sky and the site."

**Accessibility.** Skip link; one `h1` per page and headings in order; table captions and column
headers; "(over limit)" read out after each flagged value; chips are text; 44 px touch targets;
visible focus ring; maps have titles and the same facts are in the lists beside them; reduced
motion honoured; print hides the maps.

## 5. Validate: self-critique

Run on the sample build in Chromium at 1440 px (light and dark) and 390 px, after the fixes listed
under Ship.

| Dimension | Rating | Observation → problem → fix |
|---|---|---|
| Hierarchy | pass | Warnings, then map, then towns, on both widths; one idea per card. |
| Brand | pass | Light field-sheet look, a simple mountain-and-hailstone mark, plain voice. The tab icon is the header mark; the phone home-screen icon is the app's icon at 180 px. |
| Composition | minor issue | On quiet desktop days the warnings column is short beside a tall map. Fix (P3): when there are no warnings, let the town cards start beside the map. |
| Typography | pass | Six sizes, three weights, 17 px body, tabular numbers in tables. |
| Colour | pass | Every pair at least 5.86:1; colour always paired with words or weight. |
| Affordance | minor issue | Town cards are whole-card links; on touch there is no hover cue. Fix (P3): add a "Forecast ›" line to each card. |
| Information density | minor issue | The phone Now page is long (14 cards). Fix (P2): a compact one-line-per-town list on phones, with the same flags. |

Fix list: **P1** none. **P2** compact town list on phones. **P3** quiet-day layout, card
affordance. Strongest dimension: colour and contrast. Weakest: density on phones.

## 6. Ship

Built in `website/` (sources, build, sample data, templates, static files) and published by
`.github/workflows/website.yml` (D27). Fixes made during the browser checks before this spec was
final:
- Folium's popups needed jQuery, which the site doesn't load. They were replaced with a two-line
  Leaflet popup.
- The map style lost to Leaflet's own stylesheet. The selectors were made more specific.
- Leaflet's layer-control icon was missing. Its images are now served by the site.
- Labels covered each other and Livingston's dot. Label sides are now set per town, with the
  phone rule for minor towns.
- On phones the hourly table hid gusts off-screen. Gusts now come first, and the sky and reasons
  columns drop below 560 px.
- Missing values showed as "—%". They now show a dash with a sentence.
- The 7-day forecast was one row per 12-hour period. It is now one row per day with the high and
  low together.
- Numbers and their units no longer split across lines.

**QA checklist.**
- Tokens only, no hex values in components.
- Every state above visible in a test or screenshot.
- No page shows "no alerts" after a failed check.
- Chips readable in greyscale.
- Focus visible.
- No sideways scrolling at 288–1440 px.
- Labels collision-free at every width the maps open at.
- Live data checked in the branch build before merge (rule 7).

## 7. Rationale

**Decision.** Replace the desktop app, for now, with a static website: three pages and a page per
town, a light "field sheet" look with automatic dark mode, rebuilt from public NWS, SPC and NOAA
data every 10 minutes.

**Context.** Carson found the app too complicated and ugly. Crews need answers on phones without
installing anything. The data are public. The rules against reassurance and AI text still hold.

**Options.** A field sheet, B storm desk, C town picker (section 3).

**Evidence.** The app's own screens (dense, dark, six sections). The phone screenshots of each
concept's first screen. Dark text on a light ground reads better in bright light. The measured contrast
and layout checks above.

**Reasoning.** The three questions are list questions, and a list in high contrast is readable in
a truck. The map answers "where", so it sits beside the warnings, not above them. A static site
has no server to keep running, costs nothing on a public repository, and shows everyone the same
checked snapshot.

**Trade-offs.**
- No per-job rules or alerts to phones yet.
- A page can be up to about 10–20 minutes behind NWS. Every page links to weather.gov and says how
  old it is.
- Radar is a still frame, with a link to the live loop.
- GitHub may delay scheduled builds. It pauses them after 60 days without activity.

**Validation.**
- Run the comprehension and timing tests in section 1 with crews after launch.
- Check the first live builds' content in the workflow summary.
- Carson reviews the site on a phone and a desktop.

## 8. The interactive map (2026-10-15)

**Frame.** Carson sent a screen recording of Apple Weather's full-screen precipitation map: "Lets turn
this into a working interactable map of montana that looks like this." The recording shows a white,
minimal map; a soft blue-violet-pink-yellow precipitation overlay; a glass legend (Extreme, Heavy,
Moderate, Light); round glass buttons for layers, location and a list; temperature bubbles on the
towns; and a bottom glass timeline with play/pause, "1h | 12h" and a scrubber that runs from the
past into the forecast. The job is the same experience for Montana, built from public data and the
site's honesty rules.

**Users and moments.** A crew lead checking whether the line of showers west of Bozeman reaches the
job before noon (Precipitation, 12h, play); the owner deciding whether afternoon gusts stop roof work
in the Livingston corridor (Wind gusts layer, the 25 mph ring on the bubbles); anyone after a storm
(Storm reports overlay).

**Principles specific to the map.**
1. *Radar is not forecast.* Before "Now" every frame is NOAA's radar estimate; after "Now" it is the
   HRRR computer model. The timeline title switches between "Radar" and "Forecast", the subtitle
   names the source, and the legend says so. The numbers on the towns are the NWS forecast, labelled
   as such in the town sheet.
2. *Missing is not dry.* Areas without radar coverage are hatched and named in the legend. A failed
   download puts a sentence on the map, never an empty-looking clear sky.
3. *It must work with a thumb.* 44 px targets, the timeline is a real range input (drag or arrow
   keys), sheets close with Escape or a button, no hover-only information.
4. *Python builds the data; the browser only plays it.* Frames, legends and every number are made
   by the build. `map.js` handles what only a browser can: the playback timer, scrubbing, menus,
   sheets and geolocation.

**Layout.** Full screen (100dvh, safe areas respected).
| Region | Contents |
|---|---|
| Top left | Close (back to Now); the legend for the active layer with its note and a "Map data" link (on a portrait phone the keys sit beside a shorter scale, "Map data" in the title row: about 135–165 px tall, up to 210 on a 320 px phone, instead of about 210–340) |
| Top right | Layers (Precipitation, Temperature, Wind gusts; Warnings and Storm reports toggles), My location, List (every alert, including those without an outline, then every town) |
| Map | White vector basemap; the active layer's frame; warning outlines; storm reports; town bubbles |
| Bottom | Timeline: play/pause, "Radar"/"Forecast" with time and source, "1h | 12h", scrubber with a Now tick |
| Sheets | Town (NWS forecast for the selected hour, flags in words, alerts, link to the town page), alert (official text), report |

**Layers and timelines.**
| Layer | Before now | After now | Bubble value |
|---|---|---|---|
| Precipitation | MRMS radar estimate, every 10 min for the past hour | HRRR: 15-min steps for the next hour (1h) or hourly to 12 h (12h) | NWS temperature; no ring |
| Temperature | — | HRRR 2 m temperature, hourly to 12 h | NWS temperature; ring below 40 °F or above 95 °F |
| Wind gusts | — | HRRR surface gusts, hourly to 12 h | NWS gusts; ring at 25 mph or more (the limit) |

A ring's key stays for the whole timeline when any of its hours rings a town in sight, so the legend
never changes height during playback.

**Colour.** Precipitation by rate as liquid water, using the American Meteorological Society's
rainfall-rate classes: light under 0.1 in/h, moderate 0.1–0.3 in/h, heavy 0.3–2 in/h, extreme over
2 in/h; light blue through violet and magenta to yellow, like the reference. Temperature from purple
(−20 °F) through blue, cyan, green, yellow and orange to dark red (105 °F). Gusts from clear (calm)
through blue, yellow at the 25 mph limit, orange, red and purple. No-coverage hatch in grey.

**Basemap.** White land, Montana slightly brighter than its neighbours, thin grey state and province
lines, faint county lines and interstates from zoom 7, pale-blue lakes and rivers, grey uppercase
region names, dark town names with a white halo. Dark mode inverts to charcoal. Built once from
Natural Earth and Census lines; no tile service. Past the padded box a coarse context layer runs the
state and province lines out to 37.5–60.5° N and 122–95.2° W (east of the Pacific coast), with state
and province abbreviations and ten cities from zoom 5 (Winnipeg 6), so a phone's map runs edge to edge like the reference; it
draws no land, water or roads, and the hatch still marks it outside the map's area.
Past the basemap's padded box the page is the neighbours' land colour (#fafafa, dark #1b1e22), not
a third grey: the hatch outside the pictures' box (43–50.5° N) is a hairline, 1 px every 6 px
(`--hatch-out`; about the same weight in dark mode), like the reference's faint "not available"
hatch on white. Its words are "Outside map area" (legend key and card) and "Hatched areas are
outside this map's area." (note): NOAA has data there, the map just doesn't draw it, so it is never
called a coverage gap. Gaps inside a picture keep the heavier hatch and their own key, "No radar
coverage" or "No model data", shown on the frames that have them; on the timeline's other frames the
row keeps its room, hidden and last, so the legend keeps its height during playback. With both in
view the note says "Hatched areas have no radar (model) data on this map." and the card "No radar
(model) data on this map". A basemap name (country, region, water or place, with its dot) under or
touching the legend, Close, the right-hand buttons, the timeline, a banner, the card's caption or
Open map, an open sheet, the "Map data" text, the note line (or beside it on its line), the toast or the
nearest-town chip is hidden until they or the map move: half a name at a glass panel's edge reads as
a broken word, and a name on the note's line reads as part of the note; the hatching note itself
steps aside while a town's bubble or name is under it (after a zoom, a pan or My location, or on a
screen too short for Montana), and the legend's keys still name the hatching (on the folded layout
of very short or narrow screens, behind the (i) button, like the source). Names may run off the
screen's edge, as in the reference.

**States.**
- Frame: loading (the previous frame stays until the next has loaded) · shown · missing (a gap in the
  timeline, never a blank map).
- Source: radar ok / stale (newest frame older than 30 minutes) / failed; forecast ok / failed. Each
  failure is a banner in words with "This is not an all-clear."
- Page: fresh · older than 25 minutes (banner asks to reload) · sample (banner on every view).
- Location: off · locating · shown with accuracy ring and nearest town (announced politely) ·
  unavailable (toast). On a town's bubble the dot gives way to a blue ring on that bubble, so the
  town's number stays readable. That town (bubble and name), or else the dot, is moved clear of the
  legend and the panels. The chip says the distance ("under 1 mi" below a mile); inside the map the
  same sentence is only read out (polite live region), not shown twice. Outside the map's area the
  toast says so, with the nearest town and its distance; no chip shows.
- Alerts without an outline (county or zone): one legend row, whatever the Warnings switch says,
  "2 NWS alerts have no outline (county or zone): see List", which opens the List.
- Sheets: a town sheet pans the map just enough that the town (bubble and name) is clear of the
  sheet and of every panel; closing it puts the map back. Android's back gesture closes a sheet
  (CloseWatcher). The layer menu sits over the timeline and scrolls inside on a short screen.
- Very short screens (under 301 px tall, e.g. 400% zoom): the legend folds to its title row beside
  the close button and the timeline stops short of the right-hand buttons.
- Site updated while open: the first picture that fails to load makes the page ask for map.json
  once; if it is newer, a banner says "This map was updated after you opened it" with Reload.
- Card mode (Now and Storm reports pages): latest frame, outlines and bubbles, no controls except
  "Open map"; dragging off so the page scrolls on a phone. The words beside it are built from the
  same data (`build.py` `map_card`): the Now page's caption and frame title name the picture the
  card opens on (the radar estimate, or the model forecast and its time when there is no radar) and
  what the update is missing. The card has no legend, so the Storm reports page's key names the town
  numbers (NWS forecast temperature; the card shows precipitation, which rings no town) and the
  outlines too, and says alerts without an outline are listed on the Now page; the card's caption
  counts them on one line ("1 alert has no outline"). Where the Now card is 320 px tall (a phone or a
  short screen) that card is 344 (`style.css` `.map-card-tall`), so the line and a banner leave it at
  the Now card's zoom. The Storm reports card shows no reports banner: the page says above it when
  report files didn't load, and below it which days are incomplete ("Data unavailable for this day",
  no count) and which had no reports. The card zooms in steps of 0.05 (the full map in quarters), so
  a 328 px card shows Montana at 5.2, town names clear, instead of 5.
- Fit: Montana sits below the legend on a phone, right of it on a wide or short landscape screen,
  above the note and the timeline. A portrait phone's fit never settles below zoom 5.25, the first
  zoom where every town name clears the other bubbles, unless Montana is wider than the screen there
  (a 320 px phone); a phone too short for it there puts Montana where the panels hide the fewest
  bubbles. The fit is redone when the screen turns or resizes, a banner comes or goes, or another
  layer, 1h/12h timeline or overlay changes the legend's height (and once more when the fitted view
  itself brings a key into the legend), until the viewer moves the map in any way (drag, pinch,
  wheel, double-click or double-tap, Shift+drag, keys); from then on the map stays where they put it.
  Opening the (i) note doesn't move the map.

**Data contract.** The build writes `data/map.json` (version 1): `built`, `sample`, `tz`,
`image_bounds` (all frames share one Web-Mercator image box, 43–50.5° N, 118.5–101° W), `view`,
`now` (the newest radar frame), `layers` (per layer: `title`, `unit`, `legend` stops, `legend_note`
(in a sample build it says the pictures are invented, not NOAA radar or the HRRR model),
chronological `frames` with `time`, `kind` radar|forecast, `src`, `source`, `run` and `lead_min` for
model frames, `nodata`; `modes` with frame indices and `now_index`), `status` (radar, forecast,
alerts, forecasts, reports), `towns` (hourly NWS values for the timeline window, `alert_ids` or null
when the check failed), `alerts` (with geometry or null; it holds every alert in a town's
`alert_ids`, since the build adds what the town checks found to the statewide list), `reports`. Frames are PNG files in
`map/frames/`, named by layer and valid time (UTC); model frames add the run hour
(`temp-202610160000-r2026101522.png`). GitHub Pages lets browsers reuse a file for 10 minutes and
each hourly HRRR run redraws the same valid times, so a name must never stand for two pictures. The
pages load the scripts, stylesheets and basemap with `?v=` = the file's content hash (unchanged files
keep their address across rebuilds) and `data/map.json` with `?v=` = the build minute.

**Validate: self-critique.** Run in headless Chromium at 320–1440 px, light and dark, beside Carson's
recording, on three builds: sample; live (real MRMS radar and HRRR; NWS and SPC are blocked in this
container); and production-like (real radar and model with sample NWS answers, so the bubbles have
numbers and there are no failure banners). Done after the seven-lens verification, the owner's-eye and
skeptic reviews of its result, the phone pass that followed them, and that pass's own review (four
independent checkers, a synthesizer, parallel fixers and a recheck; D28), all on 2026-10-16. Numbers
marked "not re-measured" predate the phone pass; the rest come from its review or its final code.

| Dimension | Rating | Observation → problem → fix |
|---|---|---|
| Hierarchy | pass | The picture and the town numbers come first; the legend sits top left, the buttons top right and the timeline at the bottom, as in the reference. Failure banners sit above everything, so a failed source is read first. The one-column phone legend was 290–338 px tall (up to 40% of a 390 × 844 screen) and pushed Montana into the bottom third. Every portrait phone now gets the two-column legend, 134–165 px tall from 360 px wide (166–209 px on a 320 px phone), and Montana sits midway between the legend and the note (150 and 154 px gaps at 390 × 844). |
| Look against the reference: phone | minor issue | Glass panels, round buttons, the timeline and playback match the reference. An outer basemap layer draws state and province lines around Montana, with names from zoom 5, so the screen around the weather is a map, not blank paper: at 390 × 844 (production-like build, Precipitation) the bands above and below Montana show NV, Calgary, Salt Lake City, Saskatoon, Cheyenne and Casper (four of them on the other layers, whose legend is taller); on phones 667 px tall or shorter the panels cover most of those bands and few or no names show. Bubbles on Precipitation are plain, as in the reference: the cold and hot ring shows only on Temperature and the 25 mph ring only on Wind gusts, so a cold morning no longer rings every town (the cold flag stays in the town sheet, the List and the Now page), and a ring key stays for the whole timeline, so the legend keeps one height through playback. Problems: the pictures cover 43–50.5° N, so on a 390 × 844 phone the weather is a band about 300 px tall with straight top and bottom edges, where the reference's radar fills the screen. The legend is a wide two-column card with 4–5 key rows (more with storm reports on), where the reference shows a slim scale and four words: it is the busiest thing on a phone screen. The rows stay, because they say which numbers are NWS and which alerts have no outline. No large my-location bubble. Fix: owner's call on the picture area; P1 check on a real iPhone (glass blur, notch and home-bar insets). |
| Look against the reference: desktop | pass | At 1440 × 900 Montana fills the screen at zoom 7 with counties, rivers, lakes and places; small legend, round buttons, glass timeline and layer menu as in the reference; hour labels every 2 hours. The owner's-eye review: "on a desktop the map looks a lot like Apple's." Names that stuck out from the legend's and the timeline's edges ("e Pend Oreille", Thermopolis) are now hidden. Differences by spec: "Radar"/"Forecast" titles, lowercase am/pm, the source named under the time. |
| Honesty | pass | Every picture is named radar or model: the timeline title switches at Now, the subtitle and the slider's words name the source, and the Now page's caption is built from the same data (a checker stepped every frame of every timeline in four builds at three sizes, 678 frames, with no wrong word). Gaps are hatched and named for the frame shown; the band outside the pictures reads "Outside map area", never a coverage gap, since NOAA has data there. A failed picture or source says "This is not an all-clear."; a failed picture also drops its gap key, and the slider's words say it didn't load. Alerts without an outline get the first legend row, which opens the List. Sample builds say "invented" on every view. A Storm reports day whose files didn't load says "Data unavailable for this day", not "No hail or wind reports". Frame colours at the 14 towns match the raw HRRR (median 0.3 °F). Open, not defects: rain and snow share one scale and MRMS reads low in snow ("rate as liquid water" in the legend, behind the (i) on phones; ROADMAP 7); a picture from before the first NWS hour shows that hour's NWS number, labelled with its hour, a rule nobody has confirmed; the Precipitation legend's (i) note says "Radar estimate up to now" even when no radar loaded (the banner says it failed). |
| Legibility | minor issue | A basemap name under or touching a glass panel (legend, Close, buttons, timeline, banners, the card's caption and Open map), the "Map data" text, the toast or the chip, or on the note's line, is hidden until they or the map move. Before, the production-like build had 68 names cut at a panel's edge and 4 on the note's line across 22 sizes; now none at the opening view of 11 sizes, 3 layers and 2 builds. The hatching note steps aside while a town is under it. A portrait phone opens at zoom 5.25 (5.5 from 412 px wide), where every town name clears the other bubbles; a 320 px phone opens at 5, where a name may sit up to 4 px into a bubble (the label test's allowance). The cards fit Montana in 0.05 zoom steps, and on a phone the Storm reports card is 344 px tall, so with a banner and its extra caption line it opens at the Now card's zoom. The note (9.2:1 or more) and "Map data" (10:1 or more) are in the main ink; the hour labels moved to the timeline's darker grey and measure 4.7:1 over rain (were 3.9:1). An open sheet counts as a panel too: before, 10–13 of the 14 town sheets cut a name at their edge; now none at 390 × 844, 375 × 667 or 1440 × 900 (smoke-tested). Problem: the legend's keys and its (i) note are 11.5 px and its stop labels 12.5 px, in a grey that measured 4.5–4.6:1 at worst over the pictures: legal, but smaller and fainter than anything else on the site (13 px minimum, 5.86:1 lowest). Fix (P3): the darker grey (`--ink-sub`) for the legend's text. |
| Interaction | minor issue | The timeline is a range input (drag, arrow keys, Space); targets are 44 px, Close included on a phone on its side (the folded layout's 1h/12h buttons are 40 px wide, set on purpose); sheets close with Escape, their button, the scrim or Android's back gesture. Ten interaction findings were fixed in the verification, among them the layer menu under the timeline, autoplay after Pause and a double click closing a sheet. The phone pass caused one regression, which its review found and the fixers removed: a zoom by double-click, double-tap, the = key or Shift+drag snapped back to the Montana fit (on a desktop only the wheel zoomed). Every zoom now holds through a layer switch and the Storm reports toggle, and the smoke test checks double-click and =. My location shows your town clear of the panels and says so once; outside the map's area the toast names the nearest town and no chip shows. A phone turned with a town sheet open keeps the town's name clear of the side sheet. Problems: with motion on (most phones), a tapped town's bubble ends 5–8 px under the top of its own sheet at 390 × 844, because the sheet is measured while it still slides in (0 px with reduced motion). On an iPhone or a desktop, Back with a sheet open leaves the map and the chosen time (a choice: no history entries). Touch was only emulated. Fix (P3): open the sheet with a fade only (`map.css` `sheet-in`); a history entry per open sheet if crews hit this in the feedback week. |
| Accessibility | minor issue | axe-core, re-run on the final sample build: no violations on the map page (full map, layer menu, List, town sheet, card; light and dark; 390 × 844 and 1440 × 900). Main landmark, forced colours, reduced motion (arrow-key pans jump), focus never hidden under a panel, results announced in a polite live region, every control usable at 320 × 256 (400% zoom); on that folded layout the hatching is named only behind the (i) button, like the source. Problems: the radar and model pictures have no text version (the List has every NWS alert and town forecast as text, and the map's description claims no more); no real screen reader (VoiceOver, TalkBack) was used; the Now page, which holds the card, still has axe's meta-refresh and region findings. Fix (P2): per-town radar and model values as text (ROADMAP 8). Fix (P3): the Now page's findings. |
| Performance | minor issue | On a slow-phone profile (1.6 Mbit/s, 150 ms, 4× CPU): 13 requests and about 240 KB compressed before the first picture, shown at about 2.7 s (not re-measured: since then towns and pictures no longer wait for the basemap, and `map.js` and the basemap have grown about 11 KB compressed, to 37 and 109 KB). A repeat visit after a rebuild loads 11.6 KB besides the pictures (was 161 KB; not re-measured). Playing 12 h of precipitation takes 22 picture downloads: 33 KB on a dry day, about 650 KB in the sample's heavy rain. Temperature and wind gusts add about 1.1 and 1.4 MB (13 pictures of 73–110 KB each on 2026-10-16), so a visit that opens all three layers is about 2.8 MB. The basemap grew from 377 KB to 385 KB with the outer layer. A map left open across a deploy can lose its model pictures; it then offers a reload. Problem: each build downloads about 40 MB (39.7 MB on 2026-10-16, mostly HRRR temperature and gusts) and redraws all 48 pictures (2.5 MB): about 5.7 GB a day, most of it a repeat, since the model changes hourly and six of the seven radar pictures were drawn 10 minutes earlier. Free on a public repository, but slow and wasteful. Fix (P2): reuse pictures by HRRR run and radar time (ROADMAP 6). |
| Code size | major issue | `map.js` is 2,184 lines, about 37 KB compressed: about as long as all the Python in `website/` (2,107 lines). Plain JavaScript, documented, no framework or build step, and inside rule 4; most of it keeps Montana and every town clear of the panels on every screen size, plus the failure states and accessibility. The verification's fixes added about 320 lines (1,791 → 2,112), the phone pass and its review 72 more. Problem: that is not "minimal JavaScript" by any plain reading. The JavaScript review found about 330 lines that could move to the build: Montana-time labels written into `map.json`, the legend rendered by Jinja, the note's room reserved in CSS; each move adds `map.json` keys that tie the build to the page's wording. Fix: owner's call (ROADMAP 9). |

Fix list: **P1** none in the code. Two checks before relying on the map: a real iPhone (Safari) and
Android phone (glass blur, notch and home-bar insets, the location prompt, playback on mobile data),
and the first live build's map with real NWS alerts, town forecasts and storm reports, which no person
has yet seen on it. **P2** reuse pictures between builds (ROADMAP 6); snow told apart from rain
(ROADMAP 7); per-town radar and model values as text (ROADMAP 8). **P3**
a tapped town a few pixels under its sheet; darker legend text; a history entry per open sheet; the
Precipitation note when radar failed; confirm the rule for pictures before the first NWS hour; the Now
page's axe findings. **Owner's call** the
JavaScript size (keep, or move about 330 lines to the build); a taller picture area (41–51° N would
cover most of a phone's free map with pictures about a third bigger, inside HRRR's 51.1° N edge at the
map's west side; a phone's view reaches 57° N, past the HRRR grid, so the pictures can't fill it).
Strongest dimension: honesty. Weakest: code size against the minimal-JavaScript preference (a size
problem, not a quality one); of what users see, the phone's weather band and its busy legend.
