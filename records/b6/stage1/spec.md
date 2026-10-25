# Map options sheet: spec (B6 design mock)

Status: a design mock for owner review. Nothing in `website/` has changed. The product change is listed under "How the sheet replaces the layer menu".

## Files

- `map-options.html`: the mock. Open it in a browser. `?demo` shows one example of each state.
- `style.css`, `map.css`: byte-identical copies of the site's files (checked with `cmp`). Do not edit them. `style.css` matches the site's copy; `map.css` matches the B6 worktree's copy of the site file. `fonts/`: the site's Atkinson fonts and `fonts.css`.
- `block-view-light.png`: our block-view capture, the background (copied unchanged). In dark mode it is inverted as a stand-in for the dark basemap. It is not a dark capture.
- Renders: `mock-390x844-light.png`, `mock-390x844-dark.png`, `mock-390x844-light-bottom.png` and `mock-390x844-dark-bottom.png` (the scrolled bottom), `mock-1280x800-light.png`, `mock-1280x800-dark.png`, `states-390x844-light.png` (demo).
- Side by side, reference left and ours right: `side-by-side-390x844-light.png`, `side-by-side-390x844-dark.png`. The reference copy is `reference-sheet.jpg`.
- Checks: `measurements.json`, with `shots` (390 by 844 and 1280 by 800, light and dark, top and bottom, and the demo), `layouts` (320 by 568, 667 by 375 in light and dark, and 1280 by 800), `edges` (outline and knob pixels), `flows` (the click-through states), `page_checks` and console. `contrast.json` holds every text and control state in light and dark.
- Scripts: `render.py`, `compose.py`, `contrast.py`, `tokens.py` (run with the project venv Python).

## What the sheet shows, top to bottom

1. Header: layers icon, "Map options", close button (44 px).
2. Base map: two labelled cards, Map (chosen) and Imagery.
3. Live weather, one at a time: Precipitation, Temperature, Wind gusts, Hail, last hour, Hail, last 24 hours.
4. Five-year history, one at a time, with the line "Past records from the last five years. Not a forecast or a damage estimate.": Hail, Heat, Wind, Flood, then Fire and Smoke marked "Coming".
5. Landmarks, any number at once, with the line "From public-domain data. Businesses are not in it, so none are shown.": Schools, Parks, Hospitals, Airports, Churches. One legend line under them names the kinds that are on.
6. Switches, each with a 14 px description: Points of interest ("Landmark dots and names, for the kinds chosen below"), Highlight recent hail ("Radar estimate of 1 in or more, last 30 days"), Warnings ("NWS outlines"), Storm reports ("Storm Prediction Center (SPC), last 3 days").
7. Reset, with the line "Back to Map and Precipitation, with Points of interest and Warnings on. Everything else off."

The sheet is a bottom sheet on a phone and a 380 px panel from 640 px wide. Its body scrolls inside the sheet.

## Look

- A solid panel: `--color-surface`, a 1 px `--color-line` edge and the `--radius` corner (12 px). No backdrop blur, no shadow and no glass variables.
- The sheet does not use the glass look of `map.css`. It does not carry the `glass` class, and it does not use the `--glass*` tokens or the blue tokens (`--loc`, `--focus`). It keeps `map.css`'s `.sheet` layout (position, height, scrolling, the entry animation) and overrides its surface and its colours. The two layer buttons at the top right keep the map's glass look, because they are the map's own controls, not part of the sheet.
- Colours come only from the roles in `style.css`: `--color-surface`, `--color-surface-muted`, `--color-line`, `--color-text`, `--color-text-muted`, `--color-focus` and `--color-on-chip`, with `--radius`, `--radius-sm`, `--text-xs` and `--text-sm` for corners and sizes. The page writes no hex value. Every computed colour inside the sheet, in both themes, was checked against those roles.
- Headings are sentence case and never uppercase. The four group headings use one token, `--color-text-muted`, at 13 px (`--text-xs`).
- Legend lines and switch descriptions are 14 px (`--text-sm`). Everything else keeps its size.

## Chip states

| State | Look | Words | Tap does | Attributes |
|---|---|---|---|---|
| Off | Outline, 1 px `--color-text-muted` | The label | Turns on and opens its legend line. In a one-at-a-time group, the chip that was on turns off. | `aria-pressed="false"` |
| On | Filled with `--color-text`, label in `--color-on-chip`, with a tick | The label | Turns off and closes its legend line. A landmark kind turns off and the landmark line is rebuilt. | `aria-pressed="true"` |
| Unavailable | Dashed outline, muted | The label and "Coming" (Fire, Smoke) or "Data unavailable" (a store that did not load) | Opens its reason line. The state does not change. | `aria-disabled="true"`, `data-reason` |
| Waiting | Dashed, muted. The choice is kept and its tick shows | The label | Opens the reason line, "Turn on Points of interest to show these." Nothing else changes. | `aria-disabled="true"` |

Live weather and five-year history are one at a time, because the map draws one weather picture and one value per building. Tap the chip that is on to turn it off; no live picture then shows, and the timeline hides. Base map is always one of its two choices. Landmark kinds are independent toggles.

## Base map

Two cards, each a small outlined card with its label: Map and Imagery. The chosen card has a 2 px `--color-focus` edge (a 1 px border and a 1 px inset ring), a tick and a bold label. The other card has a 1 px `--color-text-muted` outline. Keyboard focus is a 3 px `--color-focus` ring around the card. The Imagery value and its link parameter are `imagery`. There are no pictograms, round discs or globe and folded-map icons.

## Icons

Each data kind has its own icon, or none. Hail, last hour uses a cluster of stones; Hail, last 24 hours a clock; the five-year Hail a calendar, so no two hail chips share an icon. Live Wind gusts uses wind lines and the five-year Wind a gauge, so the two wind chips differ. Precipitation, Temperature, Heat, Flood, Fire and Smoke each keep their own icon, and each landmark kind has one. These are proposals for the owner to check.

## Legend line each chip opens

The line appears under its group's heading when a chip is on (or when its reason is tapped). One line per group. The words sit in `data-legend`, `data-reason` and `data-template`; the build writes them, and `map.js` only places them. Each acronym is spelled out at its first use in the sheet's copy, read in document order: MRMS and MESH (Hail, last hour), HRRR (Precipitation), NWS (Temperature) and SPC (Storm reports). Later uses are short.

- Base map, Imagery (existing sentence): "Aerial imagery with roads and names from USGS. Your IP address and the map area you view go to USGS while it is on."
- Precipitation (existing in `gridded.py`, with HRRR spelled out): "Rate as liquid water. Radar estimate up to now, High-Resolution Rapid Refresh (HRRR) model forecast after."
- Temperature (proposed): "HRRR model temperature, in °F. Town numbers are the National Weather Service (NWS) forecast."
- Wind gusts (existing in `gridded.py`): "HRRR model. Roofing limit 25 mph."
- Hail, last hour (existing `swath.py` note, with the window word, and the uncoloured sentence at the end): "Radar estimate of the largest hail in the last hour, in inches, from NOAA's Multi-Radar Multi-Sensor (MRMS) maximum estimated size of hail (MESH). An estimate, not observed hail and not an inspection. Uncoloured means no radar estimate of 0.25 in or more, or no value, and that is not “no hail”."
- Hail, last 24 hours: the same, with "in the last 24 hours" and "from MRMS (MESH)", and the same uncoloured sentence at the end.
- Hail (five-year, proposed from the `hail.py` words): "Largest radar estimate over five years for each cell, 0.25 in and up. Every building in a cell shares its value. A value of -- means no estimate of 0.25 in or more was stored; that is not the same as no hail."
- Heat (proposed, from the five-year rows in `DESIGN.md` section 12): "Grid estimate: days with a high of 90 °F or more in the last five years. A grid value is an estimate for a cell about 4.6 km across. A value of -- means no grid value was stored. That is not zero or an all-clear."
- Wind (five-year, proposed): "Station reading: days with a gust of 50 kt (58 mph) or more at the nearest station, in the last five years. Not a measurement at this building. A value of -- means no station reading was stored. That is not zero or an all-clear."
- Flood (proposed): "Reports, records and NWS warnings for floods and flash floods in the last five years, near this place. Not a measure of water at any building. A missing value shows as Data unavailable. That is not zero or an all-clear."
- Fire and Smoke, unavailable (proposed): "Coming later: fire is not in the map yet." and "Coming later: smoke is not in the map yet."
- Data unavailable, example (demo only, proposed): "Data unavailable: flood records did not load in this update. This is not an all-clear."
- Landmarks (proposed, one line for every kind that is on, from `data-template`): "{kinds} from public-domain data, shown as dots with their names." With one kind: "Schools from public-domain data, shown as dots with their names." With two or more: "Schools and parks from public-domain data, shown as dots with their names." The line is rebuilt on every change. It is hidden when no kind is on and while Points of interest is off.
- Points of interest off, after a tap on a waiting chip (proposed): "Turn on Points of interest to show these." The reason shows only on that tap.
- Highlight recent hail, on (proposed): "Buildings in cells where radar estimated 1 in or more in the last 30 days are highlighted. Buildings in other cells are not; that is not the same as no hail. Radar estimate, not a measurement at the ground."
- Storm reports, on (existing in `map.js`): "No report is not “no hail”."

## Switches

- Points of interest: on by default, as in the reference. It gates the landmark chips and their dots. Off, the chips wait with their choices kept, and a tap on a waiting chip shows the reason. Its description reads "Landmark dots and names, for the kinds chosen below" (see open decision 11).
- Highlight recent hail: off by default. It shows the building highlight for cells whose radar estimate reached 1 in in the last 30 days. If the hail store is stale (newest day more than 3 days old) or unavailable, the switch shows unavailable with the store's words. The mock does not show that state.
- Warnings: on by default. Storm reports: off by default.
- On: a `--color-focus` track with a `--color-surface` knob. Off: a `--color-surface` track with a 1 px `--color-text-muted` inside outline and a `--color-text-muted` knob. Both states are 3:1 or more against the sheet in light and dark (see Colour and contrast).

## Reset

Restores: Map as the base map; Precipitation on (the only live choice); no five-year history choice on; no landmark on; Points of interest on; Highlight recent hail off; Warnings on; Storm reports off. Reset leaves the sheet open and leaves unavailable chips unavailable. It also clears the address parameters the sheet adds (`poi`, `hail_recent`, `history`, `landmarks`) and keeps `base=imagery`, so old links still work.

## How the sheet replaces the layer menu in `map.js`

Current functions are named as in `website/static/map/map.js`.

- `toggleLayers(open, refocus)` becomes `toggleOptions(open, refocus)`. It shows or hides the sheet and the scrim, sets `aria-expanded` on `#btn-layers`, lifts `.top` (`menu-open`), focuses the close button on open and returns focus to `#btn-layers` on close.
- `fitLayersMenu()` is removed. Height and scrolling are CSS (`.sheet` max-height and `.sheet-body` overflow), and the top comes from `placeSheet` (`--sheet-top`).
- `setLayer(key, opts)` keeps its timeline and legend work. Its radio loop becomes `setLive(key)`, which sets `aria-pressed` on the `live` chips. `setLayer(null)` is new: it hides the timeline and the legend card and drops `layer` from the address.
- `setBase(imagery, opts)` keeps its logic. The radios stay `input[name=base]`, with values `map` and `imagery`. Only the label changes, to "Imagery".
- `setWarnings(on)` and `setReports(on, quiet)` keep their logic and ids (`#tg-warnings`, `#tg-reports`).
- The `change` handler on `el.layers` becomes a `click` handler on `#map-options` for `.mo-chip`, and a `change` handler for the switches.
- New: `setHistory(key)` (one at a time; `null` for none), `setLandmark(key, on)`, `setPoi(on)` (gates the landmark chips and their layers, then calls `landmarkLine()`), `landmarkLine()` (one line naming the kinds on, built from the chips' `data-name` and the line's `data-template`; hidden while Points of interest is off or no kind is on), `setHailRecent(on)`, `renderOptions()` (aria state and legend lines from the chips' `data-*`) and `resetOptions()` (the defaults above).
- `saveUrl()` adds `poi=off` (only when off), `hail_recent=on`, `history=<key>` and `landmarks=<key,key>`.
- `el` changes: `layers` becomes `byId("map-options")`. `warnings`, `reports` and `layersBtn` keep their ids. New: `poi`, `hailRecent`, `hailLegend`, `reportsLegend` and the chip and legend elements.
- The sheet's panel rules move into `map.css`: the solid surface (`background: var(--color-surface)`, the 1 px `--color-line` edge, `--radius`, no blur) and the 640 px panel. The glass rules stay for the map's own buttons. This mock does not change the site's `map.css`.

Hooks the Python template writes in `map.html`:

- `#map-options`: `section.sheet`, `role="dialog"`, `aria-modal="true"`, `aria-labelledby="mo-title"`, `hidden` until opened. The sheet has no `glass` class. `#btn-layers` gets `aria-controls="map-options"`.
- Chips: `button.mo-chip` with `data-group` (`live`, `history` or `landmark`), `data-key` (`precip`, `temp`, `wind`, `hail_60`, `hail_1440`; `hail`, `heat`, `wind`, `flood`, `fire`, `smoke`; `schools`, `parks`, `hospitals`, `airports`, `churches`) and `aria-pressed` (on or off). Live and history chips have `data-legend`. Landmark chips have `data-name`, the kind's name in lower case, which the line joins. Unavailable or waiting chips have `aria-disabled="true"` and `data-reason`. Python also writes the chip's word ("Coming", or the store's words).
- Base radios: `input[name=base]` with `value="map"` or `value="imagery"` and `data-legend` (the Imagery sentence; empty for Map).
- Legend lines: `p.mo-legend[data-legend-for]` for `base`, `live`, `history` and `landmark`, with `aria-live="polite"` and `hidden` unless filled. The landmark line also has `data-template`, with `{kinds}` where the kind names go.
- Switches: `#tg-poi`, `#tg-hail-recent`, `#tg-warnings`, `#tg-reports` (`role="switch"`), with `#legend-hail-recent` and `#legend-reports`.
- The mock's own `data-demo-reason` and inline script are for the mock only.

## Layout, touch and text

- Measured in `measurements.json`: at 390 by 844 and 1280 by 800 (light and dark), and at 320 by 568 and 667 by 375: no horizontal overflow, 26 controls per render, each at least 44 by 44 px. At 320 by 568, 667 by 375 and 1280 by 800 the Reset button is reachable and the close button is in view after scrolling to the bottom.
- The sheet body scrolls: at 390 by 844 the body is 602 px tall and scrolls over 1,205 px; at 1280 by 800 it is 614 px and scrolls over 1,135 px; at 320 by 568 it is 387 px and scrolls over 1,361 px; at 667 by 375 it is 189 px and scrolls over 1,135 px.
- Smallest text is 13 px (`--text-xs`): group headings, sub-lines, the Reset note and the "Coming" and "Data unavailable" words. Legend lines and switch descriptions are 14 px (`--text-sm`). Chip, card and switch labels are 15 px, as before.
- Keyboard and screen reader: chips are buttons with `aria-pressed` or `aria-disabled`, named by their group heading. Base map uses radios inside labelled cards. Switches are native checkboxes with `role="switch"`. Escape closes the sheet, and focus returns to the layers button.

## Colour and contrast

- The page writes no hex value. Every colour is a `var()` role from `style.css`. The computed colours inside the sheet were checked against those roles in both themes, and the only ones that are not plain roles are inset shadows whose colour is a role.
- The sheet is a solid panel, so each state is measured against the colour it sits on. `contrast.json` lists 58 pairs: 17 text and 12 non-text states in each theme.
- Text: lowest 6.76:1 in light and 7.87:1 in dark (the group headings), against 4.5:1.
- Non-text (chip and card outlines, the focus ring, the switch track and knob, the legend bar, the close icon): lowest 6.76:1 in light and 7.87:1 in dark, against 3:1.
- Outlines and knobs were also sampled on the pixels of a 2x render (`measurements.json`, `edges`): the switch Highlight recent hail outline when off 6.97:1 in light and 7.87:1 in dark; its knob 6.76:1 and 7.87:1; Points of interest on, track 7.03:1 and 8.54:1 against the surface, knob 7.03:1 and 8.54:1 against the track; the chosen Map card's 2 px focus edge 7.03:1 and 8.54:1; the Imagery card's 1 px outline 6.76:1 and 7.87:1.
- A pixel check that samples the track interior reads 1:1 for an outlined switch that is off, because its interior is the surface colour. The outline is measured directly instead, as above.

## Open decisions for the owner

1. One at a time for live weather and five-year history, many for landmarks. The brief said "chips"; this is the choice that the map can draw.
2. "Imagery" is now the base map's name, the site's Imagery option. The GOES cloud picture still says "Satellite" (`--storm-layers`), so the two names no longer clash. The owner's live list leaves the cloud picture out.
3. "Five-year history" is the group name, as the owner asked. The sub-line says these are past records, not a forecast or a damage estimate. `DESIGN.md` section 12 calls the same records "five seasons".
4. Cell size: the brief says 1 km. The store's cell is 0.01 degree, about 0.7 miles north to south and 0.5 miles east to west (`DESIGN.md` section 9). The copy uses the site's words.
5. "Building", not "house": `DESIGN.md` section 10 bans "house" in templates. The brief's word appears nowhere in the copy.
6. Heat, Wind and Flood have no bubble value yet. Section 12 counts days (heat, wind) and reports and warnings (flood). Each needs a unit and a number rule before the map can show it. The copy says what each counts, and what a missing value shows.
7. Points of interest on by default, as in the reference; landmark kinds off by default. Confirm.
8. Highlight recent hail depends on the hail store's last 30 days. Its stale and unavailable states must be built.
9. Landmark datasets: "public-domain data" is the owner's phrase. The sources need a live check and a `CONTRACTS` entry (AGENTS.md rule 7) before building.
10. The "Coming later" lines are proposals. The mock's example of "Data unavailable" is demo only.
11. The Points of interest description says "for the kinds chosen below", but in this layout the landmark kinds sit above that switch, as they do in the reference. Either the switch moves up to head the kinds, or the words become "above". The owner's words are used as written, and the layout is unchanged.
12. The icons are proposals: a clock for Hail, last 24 hours, a calendar for the five-year Hail and a gauge for the five-year Wind. The owner should check that they read as intended.
13. USGS stays short in the Imagery sentence, because the owner's list named MESH, MRMS, HRRR, SPC and NWS and not USGS. Say if USGS should be spelled out too.

## Not checked

- No change to `map.js` or `map.html`; the product behaviour above is a proposal. The product's `map.css` would need the new sheet rules; this mock does not change the site's `map.css`.
- No live build, no screen reader pass, no touch test on a device.
- `map.css`'s first comment names a third-party product. The copy is unchanged on purpose, so the file matches the site.
