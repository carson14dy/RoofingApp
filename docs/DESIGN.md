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
| Horizontal scrolling | Chromium at 288, 320, 375, 768 and 1440 px, light and dark, every page | none; `tools/smoke_pages.py` checks it on every branch push (it found 6–24 px at 288 px on 2026-10-16, now fixed) |
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

Four top-level pages and 17 town pages, two levels deep:
```
Now (index.html) ── town/<slug>.html × 17
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
4. Town card: name and the most urgent alert chip; the latest station reading on one grey line
   ("Now 43 °F · wind 10 mph SSW · no gust reported", then "22 min ago · station KBIL, 3 mi away,
   3,570 ft": the age first so a narrow card never cuts it off, "stale" past 75 minutes, D29);
   temperature range, highest gust, highest chance of rain or snow,
   then either "6 of 12 hours flagged. First at 12:00 pm: Gusts 31 mph." or the honest alternative
   ("No hour reaches the limits above", or "Gust forecast unavailable, so gusts weren't checked").
5. Town page: official alerts at that point; "Observed now", a card per nearest station
   (temperature, wind, gusts, time and age, quality flags in words, station elevation beside the
   grid square's); the 24-hour table (time, gusts, wind, rain or snow, temperature, sky, reasons);
   the 7-day list with high and low on one row.

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

**Map.** Leaflet 1.9.4 served by the site. A white vector base map (inverted in dark mode; the opt-in
USGS imagery is in section 8) so radar and warning colours stand out. Radar is NOAA's composite saved as one picture per build with
its frame time, at 72% opacity, so everyone sees the same frame the page describes. Warning
polygons use the chip colours. Towns are white dots with labels; each label's side is set in
`towns.json` so no label covers another or a dot. A town shows from its `min_zoom` in `towns.json`
(5 when it has none; `"minor": true` means 7): Butte, Glendive, Lewistown and Livingston from zoom 7,
Anaconda from zoom 8 (label on the left, away from Butte) and Belgrade from zoom 9 (at zoom 8 its
bubble would sit 3 px from Bozeman's). Maps narrower than 546 px open one zoom out, so the six towns
that show from zoom 7 or later hide there, dot and label; every town keeps its card. Reports: hail in
violet, sized by hail size; wind in teal.

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
- No sideways scrolling at 288–1440 px (`tools/smoke_pages.py`). Up to 380 px the menu says "Reports"
  for "Storm reports" with tighter padding, so it stays on one row; an alert chip drops under the
  town name when it doesn't fit beside it; a card's three numbers become two columns under 244 px.
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
   sheets and geolocation. The one thing it fetches from off the site is the imagery, and only while Imagery is on (D32).

**Layout.** Full screen (100dvh, safe areas respected).
| Region | Contents |
|---|---|
| Top left | Close (back to Now); the legend for the active layer with its note and a "Map data" link (on a portrait phone the keys sit beside a shorter scale, "Map data" in the title row: about 135–170 px tall instead of about 270–340) |
| Top right | Layers (Precipitation, Temperature, Wind gusts; Base map: Map or Imagery; Warnings and Storm reports toggles), My location, List (every alert, including those without an outline, then every town) |
| Map | White vector basemap, or USGS imagery when the Base map switch is on (D32); the active layer's frame; warning outlines; storm reports; town bubbles |
| Bottom | Timeline: play/pause, "Radar"/"Forecast" with time and source, "1h | 12h", scrubber with a Now tick |
| Sheets | Town (NWS forecast for the selected hour, flags in words, alerts, link to the town page), alert (official text), report |

**Layers and timelines.**
| Layer | Before now | After now | Bubble value |
|---|---|---|---|
| Precipitation | MRMS radar estimate, every 10 min for the past hour | HRRR: 15-min steps for the next hour (1h) or hourly to 12 h (12h) | NWS temperature; no ring |
| Temperature | — | HRRR 2 m temperature, hourly to 12 h | NWS temperature; ring below 40 °F or above 95 °F |
| Wind gusts | — | HRRR surface gusts, hourly to 12 h | NWS gusts; ring at the 25 mph limit |
| Satellite (with `--storm-layers`) | GOES-East band 13 picture of the newest 5-minute scan: one observation, not radar and not a model | — | NWS temperature; no ring |
| Base map: Map (default) or Imagery (opt-in, D32) | Under every layer, the same before and after now: the white map, or USGS aerial imagery with roads and names, only while Imagery is on (after the switch, or on a link that starts on it) | The same | No change |

A ring's key stays for the whole timeline when any of its hours rings a town in sight, so the legend
never changes height during playback. The satellite picture (with `--storm-layers`, branch previews only
until counsel reads the publishing terms) is one observation of cloud-top brightness temperature: no time
series and no ring. It is never a height and never a hail signal, and its words and legend note say so.

**Colour.** Precipitation by rate as liquid water, using the American Meteorological Society's
rainfall-rate classes: light under 0.1 in/h, moderate 0.1–0.3 in/h, heavy 0.3–2 in/h, extreme over
2 in/h; light blue through violet and magenta to yellow, like the reference. Temperature from purple
(−20 °F) through blue, cyan, green, yellow and orange to dark red (105 °F). Gusts from clear (calm)
through blue, yellow at the 25 mph limit, orange, red and purple. No-coverage hatch in grey.
Satellite (with `--storm-layers`): infrared brightness temperature in kelvin, the coldest tops in
orange-red, then magenta, violet and blue, through greys; warm surfaces fade from 275 K, are faint at 290 K
and are transparent from 300 K, so the basemap shows through. Its legend labels carry the kelvin values.

**Basemap.** White land, Montana slightly brighter than its neighbours, thin grey state and province
lines, faint county lines and interstates from zoom 7, pale-blue lakes and rivers, grey uppercase
region names, dark town names with a white halo. Dark mode inverts to charcoal. Built once from
Natural Earth and Census lines; no tile service (the opt-in imagery below is the one
exception). Past the padded box a coarse context layer runs the
state and province lines out to 37.5–60.5° N and 122–95.2° W (east of the Pacific coast), with state
and province abbreviations and ten cities from zoom 6, so a phone's map runs edge to edge like the reference; it
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
(model) data on this map". A basemap name (country, region, water or place, with its dot) under the
"Map data" link, the note line, the toast or the nearest-town chip is hidden until they or the map
move; the hatching note itself steps aside while a town's bubble or name is under it (after a zoom,
a pan or My location, or on a screen too short for Montana), and the legend's keys still name the
hatching. Names may run off the screen's edge, as in the reference.

**Imagery base map (opt-in, D32).** The Layers menu's Base map group switches the white map for USGS aerial
imagery with roads and names (The National Map, ImageryTopo). While it is on, the vector land, water, roads, county
lines, place dots and names are hidden and the USGS tiles show in their place. The Montana outline and the state and
country borders stay on top, and every weather layer, outline, report and town bubble is drawn as before. The zoom
limit is 16 while it is on and 11 when it is off. The credit row is a legend row with the privacy sentence: "Imagery:
USDA, USGS, The National Map. Your IP address and the map area you view go to USGS." Dark mode shows the imagery as
it is. On a portrait phone the credit row makes the legend about 60 px taller (210 px at 390 px wide, against 151 px
without imagery; 271 px at 320 px, against 182 px; checked 2026-10-18). On a short landscape phone the credit row sits
below the visible legend, and the legend scrolls to it (the Imagery choice then needs a scroll of the Layers menu on
first view; accepted 2026-10-18). The card never uses it. The page address records the choice as `base=imagery`, and
nothing else stores it.

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
  same sentence is only read out (polite live region), not shown twice.
- Alerts without an outline (county or zone): one legend row, whatever the Warnings switch says,
  "2 NWS alerts have no outline (county or zone): see List", which opens the List.
- Sheets: a town sheet pans the map just enough that the town (bubble and name) is clear of the
  sheet and of every panel; closing it puts the map back. Android's back gesture closes a sheet
  (CloseWatcher). The layer menu sits over the timeline and scrolls inside on a short screen.
- Very short screens (under 301 px tall, e.g. 400% zoom): the legend folds to its title row beside
  the close button and the timeline stops short of the right-hand buttons.
- Satellite (with `--storm-layers`): one picture of the newest scan. Older than 20 minutes, the picture
  stays and the banner gives its age; no scan in the last 60 minutes, there is no picture and the
  timeline says so. Both are in words with "This is not an all-clear."
- Base map: Map (default) or Imagery (opt-in). Tiles come from USGS only while Imagery is on (after the switch,
  or on a link that starts on it), as the viewer pans. A tile error replaces the credit in the credit row with
  "Imagery didn't load from USGS. Outlines and towns are still shown.", and the credit comes back when a tile loads.
  With every tile refused, the map keeps a plain near-white background with the Montana outline, state lines and town
  bubbles on it; the base map's roads, lakes, rivers, counties and names stay hidden while Imagery is on. Outside the
  United States, tiles above zoom 8 are blank or missing: from zoom 9 the Canadian places checked (Calgary, Lethbridge
  and Regina) show a blank white tile, Toronto a near-white one, and Paris, Sydney and Tokyo get a 404, which the row
  reports as a failed tile. Switching Imagery off sets the zoom limit back to 11; the view zooms out only if it is
  above 11. On a short landscape phone (667x375, 740x360, 844x390) the credit row sits below the legend's visible part,
  so the legend is scrolled to reach it, and the Imagery choice needs a scroll of the Layers menu on first view;
  accepted 2026-10-18.
- Site updated while open: the first picture that fails to load makes the page ask for map.json
  once; if it is newer, a banner says "This map was updated after you opened it" with Reload.
- Card mode (Now and Storm reports pages): latest frame, outlines and bubbles, no controls except
  "Open map"; dragging off so the page scrolls on a phone. The words beside it are built from the
  same data (`build.py` `map_card`): the Now page's caption and frame title name the picture the
  card opens on (the radar estimate, or the model forecast and its time when there is no radar) and
  what the update is missing. The card has no legend, so the Storm reports page's key names the town
  numbers (NWS forecast temperature; the card shows precipitation, which rings no town) and the
  outlines too, and says alerts without an outline are listed on the Now page; the card's caption
  counts them on one line ("1 alert has no outline"). The card zooms in steps of 0.05 (the full map
  in quarters), so a 328 px card shows Montana at 5.2, town names clear, instead of 5.
- Fit: Montana sits below the legend on a phone, right of it on a wide or short landscape screen,
  above the note and the timeline. A portrait phone's fit never settles below zoom 5.25, the first
  zoom where every town name clears the other bubbles, unless Montana is wider than the screen there
  (a 320 px phone); a phone too short for it there puts Montana where the panels hide the fewest
  bubbles.

**Data contract.** The build writes `data/map.json` (version 1): `built`, `sample`, `tz`,
`image_bounds` (all frames share one Web-Mercator image box, 43–50.5° N, 118.5–101° W), `view`,
`now` (the newest radar frame), `layers` (per layer: `title`, `unit`, `legend` stops, `legend_note`
(in a sample build it says the pictures are invented, not NOAA radar or the HRRR model),
chronological `frames` with `time`, `kind` radar|forecast|satellite, `src`, `source`, `run` and
`lead_min` for model frames, `nodata`; a satellite frame also has `satellite` (G19 or G18; SAMPLE in a
sample build), `scan_start` and `scan_end` (ISO times in UTC), and `coldest_k` and `warmest_k` (whole
kelvin over the drawn pixels, for the words); `modes` with frame indices and
`now_index`), `status` (radar, forecast, alerts, forecasts, reports, and satellite with
`--storm-layers`), `towns` (hourly NWS values for the timeline window, `alert_ids` or null when the
check failed), `alerts` (with geometry or null; it holds every alert in a town's
`alert_ids`, since the build adds what the town checks found to the statewide list), `reports`, and `imagery` (D32:
the USGS tile address with `{z}/{y}/{x}`, `max_zoom` 16, `credit_line` and `failed_line` (the two words the
credit row shows) and `host`; the same values sit in the Map page's
`data-imagery` attribute, and the browser requests tiles from them only while Imagery is on).
Frames are PNG files in
`map/frames/`, named by layer and valid time (UTC); model frames add the run hour
(`temp-202610160000-r2026101522.png`). GitHub Pages lets browsers reuse a file for 10 minutes and
each hourly HRRR run redraws the same valid times, so a name must never stand for two pictures. The
pages load the scripts, stylesheets and basemap with `?v=` = the file's content hash (unchanged files
keep their address across rebuilds) and `data/map.json` with `?v=` = the build minute.

## 9. Hail history (2026-10-18, behind `--hail-history`)

**Frame.** Carson's decision 5 (`DECISIONS.md` D34): "Where they can find the exact date that the hail happened at that location." The sheet answers one question for one spot: on which days in the last five years did NOAA's radar estimate hail of pea size or more here, and how big was it. On a loaded sheet or loaded town table, beside every number it says what the number is (a radar estimate of the largest hail over this cell, about 0.7 miles north to south and 0.5 miles east to west, during the day) and what it is not (a measurement at the ground, an inspection, or a sign of no hail).

**Users and moments.** The owner or a crew lead on a phone at a job's spot, asking on which days radar estimated hail there and reading the sentence that says what an estimate is. A reader of a town page scanning the table for the date of a storm.

**Principles specific to the history.**
1. *An estimate is not a measurement.* The sheet and each town table say so beside the rows, not in a footnote.
2. *No estimate is not "no hail".* A day with no stored value is "no estimate" in the words. A zero is never written.
3. *The date is the SPC day.* A day runs from 12:00 UTC to 12:00 UTC the next day: 6 am to 6 am Mountain daylight time, 5 am to 5 am in winter (the SPC reporting day). Its date is read in UTC, so the viewer's time zone never moves it, and it reads "Jun 15, 2025".
4. *Python writes the words.* The build renders the town tables. The browser fills the same templates from `data/map.json` and holds no hail sentence, size unit or threshold of its own. The browser also picks the largest day, counts the classes and chooses between the lead templates; every sentence it fills is Python's (website/hail.py WORDS).
5. *One reading of size.* Inches to the hundredth, rounded down, with the millimetres exact beside them, and a class word from the size table. The class comes from the stored tenths of a millimetre, so the rounded-down inches never disagree with it.

**Where the words appear.**
| Where | What shows | Shown when |
|---|---|---|
| Map sheet: tap or click the map, or open `?at=lat,lon` | Title "Hail history at this spot"; the lead; one row per day, newest first; days per size class; what this is; missing days; the stale line when it applies; the source line; a close button (Escape closes) | `--hail-history` build |
| Map legend | "Tap or click the map for the five-year hail history at that spot" | `--hail-history` build |
| Map status line | "Hail history didn't load at {time}: {detail}. This is not an all-clear." | The store cannot be read |
| Town page, "Hail history, five years" | The lead; a table of date, size in inches and mm, class word and severe tag; what this is; missing days; the source line; the SAMPLE label in sample builds | `--hail-history` build |
| About page, "Hail history" | A short paragraph: what the store is, the radar-estimate kind, the floor, the day rule, the daily job, the source and the units, and that an estimate is not an inspection | `--hail-history` build |

**States.** The sheet and the town tables use the same words. The sheet's own loading and outside states exist only there, because a town page is built, not fetched.
| State | When | Words |
|---|---|---|
| Loading (sheet) | After a tap, while the tile's shard is fetched; the words are replaced when it arrives | "Loading the hail history for this spot" |
| Loaded | At least one day at 0.25 in or more in the window | Lead: "{n} days with a radar-estimated hail size of 0.25 in or more between {start} and {end}. Largest: {largest_in} in ({largest_mm} mm) on {largest_date}." For one day: "1 day with ...". Then the rows |
| No estimate (no events) | The spot is in Montana and its key is in the shard's `state` with no entry in `cells`: no day at 0.25 in or more in the window, including a cell with no stored value | "No day between {start} and {end} has a radar-estimated hail size of 0.25 in or more at this spot. That is not the same as no hail: radar estimates miss some hail, and {missing} days have no data." With one missing day: "and 1 day has no data." With none: "That is not the same as no hail: radar estimates miss some hail." |
| Outside (sheet) | The tile is not in `tiles` (no fetch is made), or the key is not in the shard's `state`: the point is outside Montana | "Outside Montana. The history covers Montana only." |
| Outside (sample build) | A `--sample` build, where the tile is not listed or the key is not in the shard's `state`; off the grid, the plain words of the row above show | "Not in the SAMPLE data: this sample holds only a few places, so this spot has no history here." |
| Unavailable | The store or the tile cannot be read, or the build has no store | "Hail history is unavailable: {problem}. This is not the same as no hail." The problem is in plain words, for example "the history for this spot didn't load in this update" |
| Stale | The newest day is more than 3 days older than today (UTC) | "The newest day in this history is {as_of}; newer days have not been added yet." Shown with the rows |
| Sample | A `--sample` build | "SAMPLE data" sits in the sheet body in every state (loaded, no estimate, outside, loading, unavailable), not on the title, and every town table carries it too. The SAMPLE store holds real decoded values for a few tiles and days only |
| Missing days | Any day in the window with no file | "Days with no data, not counted: {list}." |
| What this is | On a loaded sheet and in each loaded town table | "A radar estimate (NOAA MRMS MESH) of the largest hail over this cell, about 0.7 miles north to south and 0.5 miles east to west, during the day. Sizes are shown to the hundredth of an inch, rounded down, with the millimetre value exact. An estimate is not a measurement at the ground and not an inspection. A day runs from 12:00 UTC to 12:00 UTC the next day: 6 am to 6 am Mountain daylight time, 5 am to 5 am in winter (the SPC reporting day). Days not listed have no radar estimate of 0.25 in or more; that is not the same as no hail." |
| Source | On a loaded sheet and in each loaded town table | "Source: NOAA MRMS MESH 24-hour maximum, 12:00 UTC files, NOAA Open Data on AWS. History as of {as_of}. The newest day is added by a job that starts at 12:43 UTC and shows here on the next rebuild, usually within the hour." |

**Size words.** The stored value is tenths of a millimetre. The size shows to the hundredth of an inch, rounded down, with the millimetre value beside it, exact to the tenth of a millimetre.
| Stored (tenths of a mm) | Size shown (in, to the hundredth, rounded down) | Class word | Severe tag |
|---|---|---|---|
| 64 to 190 | 0.25 to 0.74 | pea to mothball | no |
| 191 to 253 | 0.75 to 0.99 | penny to nickel | no |
| 254 to 380 | 1.00 to 1.49 | quarter to half dollar | yes |
| 381 to 507 | 1.50 to 1.99 | ping-pong ball to golf ball | yes |
| 508 to 698 | 2.00 to 2.74 | hen egg to tennis ball | yes |
| 699 and up | 2.75 and up | baseball or larger | yes |

- At 4.00 in (1,016 tenths) and up, a row also carries "unusually large for a radar estimate; treat with care".
- The severe tag is 254 tenths (1.00 in, 25.4 mm) and up, the NWS severe size.
- The class follows the stored tenths of a millimetre, and the shown size is rounded down from the same value, so the two never disagree about a class. 190 tenths is 19.0 mm (0.748 in): pea to mothball, shown as 0.74 in (19.0 mm). 191 tenths is 19.1 mm (0.752 in): penny to nickel, shown as 0.75 in (19.1 mm). 253 tenths is 25.3 mm (0.996 in): penny to nickel, shown as 0.99 in (25.3 mm), not severe. The first stored value, 64 tenths (6.4 mm), shows 0.25 in (6.4 mm). One rule covers every size, so there is no caps table.
- Sizes follow the NWS hail size chart; the words name the coin or ball size the chart uses.

**Legend line.** "Tap or click the map for the five-year hail history at that spot", in the legend's note line, only in a `--hail-history` build. It is not a size key.

**Data contract.** Nothing here is in the default build. With `--hail-history`:
- `data/map.json["hail"]`: `state` (`loaded`, `sample` or `unavailable`), `as_of` (the newest SPC day), `window` (first and last SPC day), `d0` ("2020-01-01"), `missing_days`, `source`, `problem` (null, or the plain words); `grid` (`cell_deg` 0.01, `tile_cells` 10, `row0_lat` 54.995, `col0_lon` -129.995, `rows` 3500, `cols` 7000); `shard` (the template `hail/t/r{r}_c{c}.json`, with `{r}` and `{c}` the tile row and column in four digits); `tiles` (the sorted names of every shard, the same list as in `hail/index.json`); `floor_tenths` 64, `floor_in` 0.25, `tenths_per_inch` 254 (the divisor the browser uses; it rounds down to the hundredth), `large_note_tenths` 1016, `stale_days` 3, `at_zoom` 9, `tenths_per_mm` 10; `classes` (`min_tenths`, `max_tenths`, `min_in`, `max_in`, `word`, `severe`, in the table's order); `words` (every sentence template, with its placeholders in braces).
- Cell arithmetic, in exact decimal: `row = floor((54.995 - lat) * 100 + 0.5)` and `col = floor((lon + 129.995) * 100 + 0.5)`, which rounds a cell edge to the cell to the south or the east. The tile is `row // 10` and `col // 10`, and the key inside the shard is `(row % 10) * 10 + (col % 10)`. Benchland (47.08 N, 110.02 W) is row 792, column 1998, in `hail/t/r0079_c0199.json` with key 28.
- The shard, `hail/t/r{row // 10:04d}_c{col // 10:04d}.json` (format `hail-cells-v1`): `{"f": "hail-cells-v1", "r": tile row, "c": tile column, "d0": "2020-01-01", "u": "tenths of a mm", "state": [key, ...], "cells": {"<key>": [[day index, tenths], ...]}}`. `state` lists every in-tile key (0 to 99) of a Montana cell, sorted. `cells` holds only the keys with at least one stored value, each list sorted by day; every value is an integer. Every tile with at least one Montana cell has a shard, even one with no events. The day index counts days from 2020-01-01. Benchland's cell (row 792, column 1998) holds 185 tenths (18.5 mm) on 2025-06-15 (day index 1992), so key 28 of `hail/t/r0079_c0199.json` lists `[1992, 185]` under `cells`.
- The browser rule, in order (`map.js`): a tile name not in `tiles` gets the outside words and no fetch; a key not in the shard's `state` gets the outside words; a key in `state` with no entry in `cells` gets the no-estimate words; any other key gets its rows. A shard that cannot be read gets the unavailable words. The browser also picks the largest day, counts the classes and chooses between the lead templates; every sentence it fills is Python's (website/hail.py WORDS).
- The index, `hail/index.json` (format `hail-store-v1`): `built_at`, `as_of`, `window`, `d0`, `grid`, `state` ("Montana"), `cells_in_state` (450,765), `floor_tenths`, `floor_in`, `days_expected` (1,826), `days_present`, `missing_days`, `events`, `shards`, `bytes`, `tiles` (the sorted names of every shard, such as `r0079_c0199`), `source` (the product `MESH_Max_1440min_00.50`, the bucket, the 12:00 UTC file time, the SPC day rule and the units table), `copy_check` (`coverage` and `frames` for each re-derived day, `partial`, `rederived`, `days_differed`, `days_checked`, `skipped`), and `"sample": true` only in the SAMPLE store. Each `coverage` entry has `listed`, `near_duplicate_pairs`, `distinct_slots` (the two-minute slots filled; 720 for a full day) and `largest_gap_s`.
- The manifest, `hail/manifest.json` (format `hail-manifest-v1`): the `bytes` and `sha256` of every other file under `hail/`, and the index's counts. The build checks every hash after unpacking and refuses the store on any mismatch.
- Budget: all of `hail/` at most 60 MB on disk; the `tiles` list is about 4,600 names (its bytes are measured in the re-check). The SAMPLE store, `website/data/hail-fixture/`, is under 50 KB and labelled sample in its index.
