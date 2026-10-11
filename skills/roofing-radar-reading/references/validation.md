# Validation and source status

Version 0.3.0 — 2026-10-11. This is a researched, challenged working procedure and a synthetic metadata checker. It is not a running nationwide weather service, an empirical accuracy result, or broadcast certification.

Subsequent integration work on the same date produced the separate [Kansas City NWS pilot](../../../research/live-map/README.md), with real endpoint access and browser checks. The blocked-access and unimplemented-service statements below describe this skill's earlier research phase; see the [pilot validation](../../../research/live-map/VALIDATION.md) for later results. This skill remains a reference procedure and checker.

## Work completed

Three hazard researchers covered hail/rain, wind/tornado, and other hazards. A point-weather researcher specified current/forecast/historical queries. An evaluation agent produced the evidence contract and checker. Separate science and public-reporting reviewers challenged the research; the primary agent integrated corrections and independently ran the tests. Agents can share blind spots; agreement is not independent observation or human meteorologist approval.

The revision adds source footprints, precise query identity, time/interval semantics, nearby/grid/site distinctions and how/what/where/when/why challenges. All **35 synthetic unit tests passed** in the author's run and the primary agent's run. The [retained log](contract-test-results.txt) belongs to this version. Tests include positive controls and rejection of wrong-point scope, unsupported values, stale/future data, incompatible quantities, missing policy, forecast lead errors and historical leakage.

Earlier numerical checks remain in numerical-checks.json. The wind module reports eight illustrative arithmetic assertions. None is a weather-prediction test. Proposed real-storm, geographic and publication cases remain unexecuted. The installed cloud skill is unchanged; this is a local companion. Automatic installation/discovery has not been established. No application code or live feed was implemented; original handoff files/assets were preserved.

## Official research access

Earlier v0.1/v0.2 attempts were broadly blocked. In this round several NWS documentation, training and safety pages were successfully retrieved and read with TLS verification. Each module records exact claim support and retrieval status:

- [Hail/rain](hail-rain.md): heavy-rain versus hail examples, dual-pol decision aid, rain probability and flood mechanisms. Historical case values are not universal production thresholds.
- [Wind/tornado](wind-tornado.md): warnings, EF damage estimates, API/geolocation documentation. The retrieved ASOS manual is dated 1998; its gust algorithm is not treated as a current instrument contract.
- [Other hazards](other-hazards.md): lightning, heat/cold, winter, fog, flood, hurricane, dust and air-quality guidance. Safety pages do not validate detailed algorithms. Prototype calculator status is retained.
- [Point weather](point-weather.md): approximately 2.5 km NWS forecast grids, changing point-to-grid mapping, point/county/zone alert distinctions, limited alert history and source latency. Reviewers independently checked relevant cached official text.

NSSL/MRMS requests returned service errors in this round; current MESH/QPE specifications remain unverified. Live api.weather.gov requests and NCEI archive pages returned CONNECT 403. Some additional domains were blocked and candidate paths returned 404; source registers identify unused sources. Four official-document snapshot hashes are recorded in source-evidence.json. A hash records content, not scientific accuracy. Documentation access does not prove working weather endpoints.

AccuWeather, Weather by WindBorne, Zoom Radar Weather and Tomorrow.io remain absent from this chat's callable tool catalog. No provider queries, entitlement checks or accuracy comparison occurred.

A saved configuration draft includes www.weather.gov, www.nssl.noaa.gov, api.weather.gov and www.ncei.noaa.gov, preserving package-manager presets and setup instructions. Saving did not apply/publish it or establish live API/archive connectivity. Review/save in environment settings and publication remain user-controlled actions.

## Run the reference checker

From this skill directory:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check_reading.py path/to/fixture.json
```

The CLI accepts one synthetic JSON envelope or stdin and returns JSON. Exit 0 means eligible_for_scoped_wording; exit 1 means review_required or blocked. See [reading-contract.md](reading-contract.md) and the test builders for fixture structure. Their weather values, coordinates and times are fictional.

The checker validates its narrow metadata profile: exact value/unit/interval matching, registered semantics, timestamps and supplied spatial relations. It does not compute real geometry, authenticate providers/policies, interpret images, convert units, judge free-text summaries, or prove an observation true. Production spatial assertions and product policies require validated adapters and an independently reviewed registry. A JSON label saying trusted_adapter is not authentication.

## Not yet demonstrated

No live readings for a property, held-out storm benchmark, independent-site accuracy study, calibrated point uncertainty, prospective shadow operation, licensed provider integration or qualified meteorologist/editor approval was completed. Point-query, warning-geometry, timezone, caching and click-race tests are specifications, not an implemented map service.

To measure accuracy, connect and verify the required products, obtain independent reference observations, freeze matching/acceptance criteria, run the [evaluation protocol](evaluation-protocol.md), and report error, misses, false alarms, abstentions and coverage. Exact coordinates cannot remove physical sampling limits. Exact current or predicted measurements at every roof are not supported by these remote datasets.
