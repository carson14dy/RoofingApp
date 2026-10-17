# Radar interpretation procedure

## 1. Establish what the image measures

Weather-radar reflectivity, commonly displayed as equivalent reflectivity factor in dBZ, is inferred from received power using radar calibration and scattering assumptions. It is not received power itself or a direct measurement of rainfall rate, hail diameter or roof conditions. Particle size, concentration, phase and shape affect it; a large value is not a unique hail diagnosis. Base reflectivity samples a particular elevation. Composite reflectivity may select maxima aloft, so it cannot be treated as a surface layer. A mosaic can combine different heights, times and radar geometries.

Mean Doppler radial velocity describes the reflectivity-weighted along-beam motion of sampled scatterers relative to the radar. It is commonly used to infer air motion, but particle fall speeds, nonmeteorological targets, sampling height, beam geometry and processing affect that inference. Read the actual legend and radar location; never assume that red means a particular compass direction. Near-zero radial velocity can occur with strong flow across the beam. Storm-relative velocity depends on the assumed storm-motion vector. Spectrum width is velocity spread in a sampled volume, not a measured rooftop gust or a standalone tornado diagnosis.

For screenshots, record cropped/missing legends, timestamps, site identifiers and elevations. Do not read exact numerical values from anti-aliased colors. Request original data or a complete display when those details determine the answer. A screenshot cannot establish that official warnings are absent.

## 2. Decide whether the storm is sampled adequately

The radar beam broadens and generally rises above local ground with distance. Even a low elevation scan may sample well above roof level, especially far from the site. Terrain, blockage, radar altitude and refractive conditions matter. An optional standard-refraction approximation for beam-center height above radar is:

`h = sqrt(r² + (kR)² + 2*r*kR*sin(theta)) - kR`, with slant range r, elevation angle theta (converted to radians for most code libraries), consistent distance units, Earth radius R and effective-radius factor k (often approximated as 4/3).

This is a model, not measured propagation. Add radar altitude for height above sea level; subtract local terrain elevation for height above ground. Beam center is not the entire sampling volume. Never calculate heights without the necessary metadata or use the approximation to certify coverage.

Beam broadening can smooth small circulations and mix targets within a sample. Partial blockage and overshooting can weaken or remove echoes; the region above the radar's maximum elevation angle can also be unsampled. A nominally available pixel does not guarantee adequate sampling of a particular hazard.

Check possible nonweather returns, stationary clutter, anomalous propagation, biological echoes, melting-layer bright band, attenuation, range/quality masks and mosaic seams. Missing data must not be recolored or interpreted as no precipitation. Compare neighboring radars and elevations when possible. A ring, spike or hole is a clue to investigate, not proof of an artifact.

## 3. Read evolution before extrapolation

Use actual scan times, not animation frame spacing or file receipt time. Align product, elevation and color scale. A changing scan strategy, source radar or mosaic contributor can mimic intensification. Growth in a maximum aloft does not itself prove worsening surface conditions.

Reflectivity, velocity, dual-pol fields, neighboring radars and elevation slices may have different sampling times. Preserve field-level times and evaluate motion/evolution before claiming co-location; a shared display or volume timestamp may be insufficient. Do not invent exact alignment when only screenshots are available.

Track a consistent feature through multiple scans. Distinguish individual-cell motion, line motion, outflow boundaries and new development. A bowing line can support concern about damaging wind but cannot supply a measured gust. Hook-like reflectivity can motivate a rotation cross-check but does not establish a tornado. Training cells/backbuilding can invalidate arrival estimates based solely on a single cell's centroid.

For constant-motion extrapolation, use a suitable local projected coordinate system, motion vector v and displacement d from the tracked feature at its latest valid observation time t0 to the job. Closest-approach offset is `t = dot(d,v)/dot(v,v)` for nonzero v; cross-track miss distance is `norm(d-v*t)`. The estimated clock time is t0+t, never receipt time plus t. Distinguish time since observation from time remaining now; a stale extrapolation may already be in the past. A negative t is before the observation. Zero speed, too few scans, ambiguous identity or major evolution prevents a useful ETA. A point track is not a storm footprint. Use a documented geometry/uncertainty method before predicting intersection with a job.

Do not replace this geometry with straight-line distance divided by speed unless the job is on the projected path. Do not use storm-relative or radial velocity as cell speed. Quote an arrival range only when observed track variation or an explicit validated method supports that range; otherwise state the conditional point estimate and unresolved error.

Keep displacement and motion units compatible: km with km/min yields minutes. Convert to an absolute UTC instant before local-time display, and use a timezone-aware library for date/offset transitions.

## 4. Interpret velocity with geometry and quality controls

Check radar location, elevation, range, units, Nyquist velocity and de-aliasing status where available. Velocity folding can create abrupt changes; missing/low-quality returns can distort apparent features. Examine spatial continuity and persistence before interpreting a couplet.

For a compact candidate circulation, examine azimuthal velocity differences at comparable radar range. Predominantly along-radial differences may instead indicate convergence or divergence. Projection, background flow and limited resolution complicate both patterns. Rotation need not straddle zero velocity: both sides can remain inbound or outbound in strong background flow. Geometry, continuity, quality and context must agree before interpreting rotation. Stronger rotation aloft is not proof that circulation reaches the ground. Do not derive tornado intensity or touchdown from a generic couplet.

For suspected outflow or damaging wind, cross-check line structure, velocity geometry, surface stations and official warnings. Surface observations still have location/exposure limits. No radar-only calculation certifies a roof's wind conditions.

## 5. Cross-check dual-polarization evidence

| Product | Useful interpretation | Essential limit |
|---|---|---|
| ZDR, differential reflectivity | Information related to scatterer shape/orientation; useful with reflectivity and thermal context | Calibration, beam height, mixed particles and attenuation affect interpretation; no universal hail-size lookup |
| CC / rhoHV, correlation coefficient | Similarity of horizontal/vertical returns; a decrease can indicate mixed or nonmeteorological scatterers | Low signal, melting particles, clutter and beam effects are alternatives; low CC alone is not debris |
| KDP, specific differential phase | Derived from the range rate of change of differential phase between horizontal and vertical signals, generally degrees/km; useful in appropriate liquid-water contexts | Respect product conventions, including two-way phase definitions; noisy/filtered estimates and mixtures need product-specific interpretation; it is not a hail-diameter gauge |
| Hydrometeor classification | Algorithmic categorization that can support a combined reading | Algorithm, height and quality dependent; a hail label aloft is not proof of hail at a roof |

A possible tornadic debris signature requires spatial/time agreement between an appropriate correlation-coefficient reduction, reflectivity and credible rotation, with consideration of height and artifacts. Recognition should follow established operational guidance and expert review. Absence of a debris signature does not exclude a tornado; do not delay warning response while seeking it.

A credible debris signature supports lofted debris associated with tornadic circulation in the sampled volume/time context. Debris can persist aloft or move away after low-level circulation changes; it does not establish exact present touchdown location, intensity or individual damaged buildings. Low ZDR can occur with hail but also approximately spherical particles; mixed rain/hail can yield other signatures. Neither low ZDR nor low CC alone establishes hail or debris.

For hail, examine storm structure, thermal level/height context, relevant dual-pol fields and a documented hail product together. Treat MESH as a radar-derived estimate. Preserve algorithm/version, grid footprint, quality and accumulation window. A 60-minute maximum means a maximum within that interval, not hail still falling now. Different versions/windows are not interchangeable.

## 6. Reconcile evidence at the correct scale

Time-match reports to the radar estimate and account for report location precision, elevation, storm movement and melting/fall displacement. A nearby smaller-hail report does not automatically invalidate a larger estimate elsewhere; neither proves conditions at the job. Do not average the two into a supposedly improved hail measurement.

Separate no reports, no coverage and a valid negative observation. Deduplicate reports copied across providers. Distinguish preliminary reports from finalized records. Inspection findings can support damage conclusions; radar alone supports exposure assessment with stated uncertainty.

## 7. Evidence ledger

For each claim preserve: source URL/record; upstream lineage; product/version; site/elevation/range when available; observation and receipt times; interval; units; geometry/resolution; quality and missing flags; derived method; alternatives; and confidence rationale. Keep measured, reported, estimated, forecast and simulated evidence distinct. Any source failure or warning-retrieval failure must remain visible.
