# Roofing radar and point-weather skill — 0.4.0

Start with [SKILL.md](SKILL.md). This package is a local companion for the Roofing App work with Claude; the installed cloud skill has not been replaced or automatically updated.

The Montana extension adds [terrain, elevation and statewide sampling rules](references/montana.md), with a [working regional map pilot](../../research/live-map/MONTANA.md).

The underlying procedure includes hazard-specific research, exact-coordinate query rules for current/forecast/historical modes, independent challenges, and a small reference checker for evidence metadata. It does not implement a running weather app or retrieve live readings for arbitrary map clicks.

An exact latitude/longitude can identify the question. The source still determines spatial resolution, sampling height, age, uncertainty and whether the reading is measured, reported, estimated or forecast. Nearby observations and grid values must retain their actual scope.

Read [validation status](references/validation.md) before describing the result as accurate. Fresh official documentation supports portions of this procedure; a real-event benchmark, operational provider integrations and qualified meteorological review remain outstanding.

The [reading contract](references/reading-contract.md) describes deterministic checks and their limitations. The test runner instructions and exact results are in the validation record. Synthetic contract tests are not weather-accuracy tests.

Use [five-question review](references/five-question-review.md) to challenge how, what, where, when and why for each consequential claim. Preserve unresolved disagreements and narrow unsupported wording.
