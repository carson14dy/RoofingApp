# Design — Montana Hail Watch

Design spec for Montana Hail Watch, the app crews open from a desktop icon.
Written 2026-10-11 with the design-playbook method (frame → explore → make → validate → ship).
This is the spec engineering builds from; the mockups are on the design canvas (link in the PR).
Decisions that bind the app live in `DECISIONS.md`; this file says what the screens are and why.

Scope: the real app (`payload/`) with Montana as its territory,
absorbing what ChatGPT's Montana pilot branch showed (nearby station readings with their age and
elevation, a statewide view, terrain wording). It is not a window around the pilot prototype
(D23, D25). The desktop icon already exists: GitHub Actions builds the Windows and macOS apps
from `main` (README, "Get the installers").

## 1. Frame (`/ux-strategy:frame-problem`)

**Problem (design-brief).** Every morning and during every storm the office has to answer three
questions for work spread across a state 550 miles wide: which jobs can work today under the
company's rules, is any official warning touching a job or territory, and where did yesterday's
storm leave roofs worth inspecting. Today's home screen puts the map first and six equal-weight
sections in a side column; the decisions are there but nothing ranks them, nearby conditions are
missing, and when a feed or the map library fails the map area goes blank. In Montana the nearest
station can be 20–30 miles away and 1,000 ft lower, stations report hourly, and radar overshoots
much of the state at low levels (D25), so the screen must show distance, age and elevation beside
every number.

**Users (persona, from the handoff and the owner).**
- Primary: the dispatcher/owner on a desktop, 6:30–8:00 am and whenever a warning fires. Needs a
  decision list, not a map to hunt across.
- Secondary: a crew lead on a laptop or phone at the job, acknowledging the day's outlook.
- Tertiary: a sales rep working inspection candidates after a storm.

**Constraints.** Python, Flask, Jinja and Folium only (D1); the dark storm look (`base.html`
tokens); evidence honesty (rules 5 and 6: never a green "safe", missing data is "Data
unavailable"); no AI text; Montana now, contiguous US next (D24); desktop first, works at 1024 px
and stacks on a phone; must stay readable over a bad connection in a truck.

**Success criteria (metrics-definition).**
| Metric | Method | Target |
|---|---|---|
| First-click success on "which job needs a review today?" | 5–8 crew/office users, first-click test on the mockup | ≥ 80% |
| Time to first decision from launch | same sessions, stopwatch | ≤ 10 s |
| All-clear misreads of the three status pills | comprehension question per pill | 0 of 5 |
| Outlook acknowledgements per job-day | app log (already recorded) | rises during the pilot |
| Missed applicable alerts | the 240 scenarios | 0 (unchanged) |

**Principles (design-principles), ranked for conflicts.**
1. **Evidence over reassurance.** Never a green "safe". Missing means unavailable, with the time
   of the last try. Counter-example: a quiet map with no feed status.
2. **Decisions before the map.** The home screen answers "what do I do" before "what is out
   there". The map stays, but it answers the second question.
3. **Distance, age and height beside every reading.** A number without "2.9 mi · 17 min old ·
   station 3,570 ft" is not a Montana number.
4. **Plain words, one screen deep.** Sentence case, no jargon, the reason in words next to every
   status; nothing important behind a second click.
5. **Last known beats blank.** Offline or stale, the screen keeps the last known state, labels
   its age, and never clears a warning.

## 2. Information architecture (`information-architecture`, `navigation-patterns`)

Global navigation stays a top bar with six destinations (under the seven-item limit): Today,
Storm History, Inspections, Crew Outlook, Places, Data sources. "Live Storms" is renamed
**Today** because that is what it answers; the map lives inside it. Utility: the version/update
chip, right-aligned. Local navigation: tabs only inside Storm History (day) and Crew Outlook
(job). Depth: nothing deeper than Today → job outlook → review. Labels are the words crews use
(jobs, warnings, inspections), validated with the first-click test above.

## 3. Explore (`/prototyping-testing:explore-options`)

**The decision this settles.** What the home screen's unit of interaction is: a job, a place on
the map, or a weather event. Criteria fixed before the concepts were drawn
(`concept-selection`):

| # | Criterion | Kind |
|---|---|---|
| T1 | No state of the screen can read as an all-clear | threshold |
| T2 | "Which jobs need review today" answered in 0 clicks from launch | threshold |
| T3 | Buildable in Flask/Jinja/Folium without new JavaScript | threshold |
| T4 | Degrades to last-known + age when a feed or the map fails | threshold |
| X1 | Fewest decisions before the first action (Hick) | trade-off |
| X2 | Keeps the storm picture useful during an active warning | trade-off |
| X3 | Holds at 50 jobs across Montana | trade-off |

**The spread (`parallel-concepts`), different in what the user does, same fidelity, same look:**
- **A · Dispatch board.** Entry: a ranked list of today's jobs with status, reason and next
  check. The system ranks; the user confirms per row. Map on the right, pins mirror the rows.
- **B · Map first (the incumbent).** Entry: a statewide map; the user hunts pins and reads a
  card per pin. The user ranks.
- **C · Storm desk.** Entry: a timeline of weather events (warnings issued, reports, forecast
  changes) newest first; each event lists the jobs it touches. The user triages events.

**Pressure test (heuristic-evaluation, on each concept's own terms).** A: risk that the map
becomes decorative during a storm; the list must grow its warnings block when warnings exist.
B: at 50 jobs the Billings cluster is unreadable at statewide zoom; status needs a click per pin.
C: many events, few decisions; the dispatcher re-derives job status from events every morning.

**Decision.** A wins. It meets every threshold; B fails T2 and X3 at Montana scale; C loses X1.
What A costs: the map drops from 70% to about 42% of the width, and the storm picture is less
prominent on quiet days. Mitigation: the warnings block expands and the map pane widens when
any convective warning touches work (state-driven, no script).
Rejected, and what brings each back: **B** was testing whether the map alone could carry the
decision; it lost on T2 and X3; it comes back for a field-only tablet user with a handful of
jobs. **C** was testing event-first triage; it lost on X1; it comes back when the unit of work is
a territory with many crews (contiguous-US scale), where events outnumber jobs.

## 4. Make: the Today screen (`/ui-design:design-screen`)

**Structure (layout-grid).** 12 columns, 24 px gutters, 24 px margins at 1440; the decisions pane
takes columns 1–7, the map pane 8–12. At 1024 the same split with the map at 360 px minimum.
Below 900 the panes stack: decisions first, map at 50vh, header navigation wraps under the
brand with the version chip in the same row (fixes the 1024 wrap seen today).

**Hierarchy (visual-hierarchy), in reading order.**
1. The date line: "Saturday, Oct 11 · 7:40 am MDT" with the feed status line beneath it, one
   chip per feed with a word and an age: Alerts live 14 s · Radar 4 min · Forecast 6:01 am ·
   Reports 10 min. This is the trust line; it never collapses.
2. **Warnings touching your work.** Only alerts matched to a job, property or territory; the
   full Montana list stays one click away. Each card: event, area, until-time, "Official · NWS",
   and the job it touches. Empty state: "No official warnings touch your work. Checked 7:40 am."
   Unavailable state: "Warnings could not be refreshed since 7:21 am. Last known warnings stay
   listed." The two states are never shown together (state machine below).
3. **Today's jobs.** One row per job: name and town, status pill, the reason in words, the
   nearby station line, next check time, a ghost "Open" button. One filled primary button for
   the whole block: "Review N jobs" (N = jobs needing review). That is the screen's single
   primary action.
4. **Tomorrow.** Same row style, conflicts only.
5. **Inspection candidates.** One line with counts and "Open list". No four-tile scoreboard.
6. **Storm matches, last 24 h.** Newest first, collapsed to three with "more".
Map pane: the Folium map with job pins coloured by status (plus shape and label, never colour
alone), warning polygons hatched, layer chips with each layer's time. Map empty states below.

**The nearby station line (D25).** `KBIL · 1.8 mi · 11 mph NW · no gust reported · 17 min old ·
station 3,570 ft`. Age past 75 min renders the whole line in the stale style with "stale" in
words. Job elevation shows "job elevation unknown" until the job records one. A `Z` or `S` flag
shows beside the value, never hides it; `X` is withheld and says so.

**Typography (typography-scale).** Display: Barlow Condensed 700 at 28 / 22 / 16 px, uppercase,
0.05 em tracking, line-height 1.2. Body: Inter 400/600 at 15 px (up from 14), small 13, caption
12 (up from 11.5 and 10.5), line-height 1.5. Mono: IBM Plex Mono 500 at 13 for coordinates and
station codes. Two weights on screen at once. Measure in the decisions pane ≤ 70 characters.

**Colour (color-system, dark-mode-design).** The app is dark only; crews use it in trucks at
dawn. Three tiers, each referencing the one below; the hexes are today's values so nothing
visually resets:
```
raw      --storm-900 #0c1622  --storm-800 #101f30  --storm-700 #16273a  --storm-600 #16364f
         --granite-700 #1c2c3f  --line-600 #2a3e54  --sky-100 #e9f0f7  --sky-400 #8ea6bf
         --wheat-500 #e0a93c  --wheat-400 #efb84e  --wheat-600 #b9872c
         --green-300 #7bd88f  --red-300 #ff8b8b  --violet-300 #c77dff  --blue-300 #a9c7e8
semantic --color-bg: var(--storm-900)   --color-surface-1: var(--storm-800)
         --color-surface-2: var(--storm-700)   --color-surface-3: var(--granite-700)
         --color-border: var(--line-600)   --color-text: var(--sky-100)
         --color-text-muted: var(--sky-400)   --color-primary: var(--wheat-500)
         --color-review: var(--wheat-500)   --color-unavailable: var(--red-300)
         --color-meets: var(--blue-300)   --color-demo: var(--violet-300)
         --color-official: var(--red-300)   --color-live: var(--green-300)
component --pill-review-fg: var(--color-review)   --btn-primary-bg: var(--color-primary)
         --card-bg: var(--color-surface-3)   --feed-chip-live: var(--color-live) …
```
Contrast, measured: text #e9f0f7 on #1c2c3f 13.9:1; muted #8ea6bf on #1c2c3f 5.6:1; wheat
#e0a93c on #0c1622 8.4:1; red #ff8b8b on #1c2c3f 7.1:1; "meets" blue #a9c7e8 on #1c2c3f 8.9:1.
All pass AA; muted text is the floor and stays at 12 px or larger. Status is never colour alone:
every pill carries its words, every pin a shape.

**Spacing (spacing-system).** 8 px base: 4, 8, 16, 24, 32, 48. Inside a row 8, between rows 8,
between blocks 24, pane padding 24. Compact density (field laptops) shifts one step down.

**Motion.** Fades of 200 ms only; the app already disables all motion under
`prefers-reduced-motion`. No loading spinners: server-rendered pages arrive whole; the feed
chips carry the age instead.

**States (state-machine).** Three machines, each with every state drawn:
- Feed (per feed): live → stale (past its limit: radar 15 min, alerts 10 min, SPC 60 min,
  forecast 12 h) → unavailable (request failed; last data kept with its time) · off (self-test)
  · demo (only under the demo event). Impossible: "no warnings" together with "unavailable".
- Job day: meets · review · unavailable (D16). No fourth "safe" state exists.
- Map: ready · tiles missing (outline and pins drawn, note "Base map tiles unavailable") ·
  library missing (Leaflet failed to load: show the pins list and "Map could not load; readings
  above are unaffected") · loading (first paint only). Today the library-missing state is a blank
  black pane; bundling Leaflet with the payload removes it for offline launches.

**Copy (ux-writing).** Status: "Forecast meets configured conditions", "Weather review needed",
"Data unavailable". Reasons start with the fact: "High Wind Warning until 6 pm; forecast gusts
48 mph exceed your 25 mph limit." Errors say what happened and what to do: "Hourly forecast
didn't load (last try 7:38 am). This is not an all-clear; try again or check NWS." Empty warnings:
"No official warnings touch your work. Checked 7:40 am." Buttons start with a verb: "Review 2
jobs", "Open", "Retry feeds".

**Accessibility.** Focus ring 2 px wheat (exists); the warnings block is an `aria-live="polite"`
region; pills are text; pointer targets ≥ 32 px, touch ≥ 44 px when stacked; headings are real
`h2`s in reading order; the map pane has an accessible name and a text equivalent (the rows).

## 5. Validate: self-critique of the design (`/visual-critique:critique-screen`)

Run on the hi-fi mockup, seven dimensions.
| Dimension | Rating | Observation → problem → fix |
|---|---|---|
| Hierarchy | pass | Entry point is the warnings block, then the jobs list; one filled button. Fix none. |
| Brand | minor issue | Mood and tokens match the existing look; voice is plain. Problem: the app's tokens are single-tier raw names, so the mockup's semantic names do not yet exist in `base.html`. Fix: add the semantic tier (section 4) before the templates change. |
| Composition | minor issue | 7/5 split balances a dense left pane with a quiet map. Problem: on quiet days the right 42% is mostly empty state. Fix: the map pane's layer chips and station pins give it content; the storm-mode widening covers busy days. |
| Typography | pass | Four sizes, two weights, 15 px body, measure under 70. |
| Colour | pass | All pairs ≥ 5.6:1; status carries words; red reserved for official and unavailable. |
| Affordance | minor issue | Rows use a ghost "Open"; the filled "Review N jobs" is singular. Problem: ghost buttons on `--color-surface-3` have a 1 px border at 3.2:1, near the floor. Fix: border uses `--sky-400` at full opacity (5.6:1). |
| Information density | minor issue | Six blocks on one screen. Problem: at 50 jobs the list is long. Fix: rows collapse to name, pill and reason past 12 jobs, with "show all"; tomorrow and matches collapse first. |

Fix list: **P1** none. **P2** semantic token tier in `base.html`; ghost-button border colour;
bundle Leaflet so the map never goes blank offline. **P3** row collapsing past 12 jobs; compact
density setting. Strongest dimension: hierarchy. Weakest: density at scale, which the
contiguous-US step (D24) will press on.

## 6. Ship: handoff (`/design-ops:handoff`)

Implementation notes, in build order, all Python/Jinja:
1. `base.html`: add the semantic and component token tiers under the raw ones (section 4); type
   sizes 15/13/12; header wraps navigation under the brand below 1100 px with the chip inline.
2. `live.html` → the Today screen: decisions pane left (the current `aside` content, reordered
   and restyled as rows), map right; rename the nav item to "Today"; warnings block shows matched
   alerts only with the statewide list behind "All Montana alerts (N)"; feed status line at the
   top; one filled "Review N jobs" button; candidates as one line; matches collapsed to three.
3. Rows get the station line once roadmap item 5 ships (`station_observation` evidence, D25
   rules); until then the row shows "Nearby station: not connected" in the muted style.
4. Map states: Folium map with a Jinja fallback block rendered when the map could not be built;
   bundle Leaflet, its CSS and marker images in `payload/static/` and point Folium at them.
5. Tests: template renders for each feed and job state; the 1024 header; browser screenshots of
   the live, offline and storm-mode states (rule 8).
Assets: none new; the app icon stays `assets/icon.*`. Version: design v1, 2026-10-11, this
file; mockups on the canvas.

**QA checklist (design-qa-checklist).** Tokens not hexes in templates; 15/13/12 px sizes; 8 px
spacing steps; every feed state visible in a screenshot; no state shows "no warnings" with a
failed feed; status pills readable in greyscale; focus visible on rows and chips; 1440, 1024 and
390 px layouts; keyboard order top to bottom; reduced motion honoured; real Montana data in the
browser check, not fixtures only.

## 7. Rationale (`design-rationale`)

**Decision.** Rebuild the home screen as a dispatch board (jobs ranked, map second), add the
nearby-station line with distance, age and elevation, and formalise the feed, job and map
states. Keep the dark storm look and the Python stack.
**Context.** Montana statewide scope (D24); terrain and sparse stations (D25); crews in trucks
at dawn; the owner's rules against reassurance and AI text.
**Options.** A dispatch board, B map first (today's screen), C storm desk (section 3).
**Evidence.** The real screens in their offline state (blank map, equal-weight sections, 1024
header wrap); ChatGPT's 16-point sweep (35 of 48 station records older than 30 min; null gusts
at nine of ten airports; stations across state lines); the handoff's home-screen order; the
playbook's density and hierarchy rules.
**Reasoning.** The morning question is a list question; a map answers "where", not "what do I
do". Montana's size makes pin-hunting fail at scale. Station readings are the one thing crews
asked the pilot for that the app lacks, and they are only honest with distance, age and height.
**Trade-offs.** Less map on quiet days; a longer first screen at many jobs; one more feed to keep
honest. The map-first concept is retrievable for a field tablet.
**Validation.** The first-click and comprehension tests in section 1 on the mockup before the
templates change; the browser screenshots of all states before merge; acknowledgement rate
during the pilot.
