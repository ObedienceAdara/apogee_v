# Apogee — A Full-Stack Rocket Mission Certification Platform

**Apogee** is an end-to-end rocket flight simulation and certification pipeline
built on [RocketPy](https://github.com/RocketPy-Team/RocketPy) and
[Astropy](https://www.astropy.org/). It doesn't just simulate a single flight —
it runs a six-stage mission design and verification workflow, the same shape
of workflow a real high-power rocketry team or launch-vehicle company runs
before signing off on a flight, and outputs a single **Flight Readiness
Report (FRR)**: the actual document format required for range-safety review
at events like IREC / Spaceport America Cup, and the kind of artifact a
review board at an aerospace company (e.g. an industrial placement like
Proforce Air Systems) would expect to see.

This is a systems-engineering project, not five disconnected scripts. Motor
choice affects stability, stability constrains the airframe, dispersion
depends on both, and recovery optimization feeds back into a confirmation
dispersion run. Those dependencies are wired together in `apogee/pipeline.py`
as real feedback loops, not just five function calls in a row.

---

## What it actually does

```
Stage 0 — Environment & Launch Window          (Astropy + RocketPy)
        |  sun elevation, twilight check, altitude wind profile, go/no-go
        v
Stage 1 — Motor Selection Optimizer            (RocketPy)
        |  sweeps a motor library, ranks by apogee-error + cost, checks cert level
        v
Stage 4 — Stability Margin Sweep vs Mach        (RocketPy)
        |  flies each fin candidate, tracks CP/CG margin through the transonic band
        |  feeds back: if nothing is stable, that's a blocking issue, not a crash
        v
Stage 2 — Six-DOF Monte Carlo Dispersion        (RocketPy, parallelized)
        |  N randomized flights -> 95% confidence landing ellipse
        v
Stage 3 — Recovery System Optimizer             (RocketPy)
        |  Pareto front: drift vs. impact velocity trade-off
        v
Stage 2 (again) — confirms the optimized recovery config actually
        |          shrinks the dispersion footprint under real wind uncertainty
        v
Stage 5 — Real Flight Validation (V&V)          (optional, if a flight log exists)
        |  sim-vs-actual residuals + likely-cause diagnosis
        v
Flight Readiness Report  (Markdown + JSON + 3 plots)
```

Every stage hands off to the next through a typed Pydantic model
(`apogee/schemas.py`) — Stage 1's output schema **is** Stage 2's input
schema, enforced at runtime. If a stage produces something malformed, it
fails loudly at that boundary instead of silently corrupting a Monte Carlo
run three stages downstream.

---

## Repository structure

```
apogee/
├── README.md                        <- you are here
├── requirements.txt
├── config/
│   ├── mission_config.yaml          <- the ONE file you edit for a new mission
│   └── motors/                      <- .eng thrust-curve library (synthetic demo set)
│       ├── H128-Synth.eng ... K740-Synth.eng
│       └── motor_costs.csv
├── data/
│   └── sample_flight_log.csv        <- synthetic demo "real flight" log (see below)
├── apogee/                          <- the actual package
│   ├── schemas.py                   <- Pydantic data contracts between every stage
│   ├── stage0_environment.py        <- Astropy sun geometry + RocketPy Environment
│   ├── stage1_motor_selector.py     <- motor library sweep + ranking
│   ├── stage2_dispersion.py         <- parallelized 6-DOF Monte Carlo
│   ├── stage3_recovery.py           <- recovery Pareto-front optimizer
│   ├── stage4_stability.py          <- fin sweep + Mach-dependent static margin
│   ├── stage5_validation.py         <- sim-vs-real V&V comparison
│   ├── pipeline.py                  <- orchestrator (the feedback loops live here)
│   ├── report.py                    <- renders the Markdown FRR + plots
│   └── utils/
│       ├── motor_parser.py          <- standalone RASP .eng file parser
│       └── rocket_builder.py        <- single source of truth for rocket/motor geometry
├── scripts/
│   ├── run_pipeline.py              <- CLI entry point
│   ├── generate_synthetic_motors.py <- builds the demo motor library
│   └── generate_sample_flight_log.py<- builds the demo Stage-5 "real" flight log
├── tests/
│   ├── test_motor_parser.py
│   ├── test_stage3_recovery.py
│   └── test_stage4_stability.py
└── outputs/                         <- pipeline writes the FRR + plots here
```

---

## Quickstart

```bash
python3 -m pip install -r requirements.txt

# (only needed once — both demo data sets are already committed, but this
#  is how you'd regenerate them)
python3 scripts/generate_synthetic_motors.py
python3 scripts/generate_sample_flight_log.py

# full run (uses n_dispersion_runs from mission_config.yaml — default 120)
python3 scripts/run_pipeline.py

# fast smoke test (20 Monte Carlo runs per stage, ~30-60s)
python3 scripts/run_pipeline.py --quick

# run the test suite
python3 -m pytest tests/ -v
```

Output lands in `outputs/`:
- `flight_readiness_report.md` — the human-readable FRR
- `flight_readiness_report.json` — the full machine-readable result (every
  Pydantic model in the pipeline, serialized)
- `dispersion_ellipse.png`, `stability_margin.png`, `recovery_pareto.png`

---

## Why the motor library and flight log are synthetic

RocketPy needs real `.eng` thrust-curve files to simulate a motor, and a real
"actual flight" record to validate against — but real manufacturer `.eng`
files are distributed via [thrustcurve.org](https://www.thrustcurve.org)
(not vendorable into a repo), and this deliverable has no associated
hardware launch (it's a software project, not a build log).

So both are generated, clearly labeled, and easy to replace:

- **Real motors:** download `.eng` files for your actual motors from
  thrustcurve.org and drop them into `config/motors/` — the parser in
  `apogee/utils/motor_parser.py` doesn't care where the file came from, only
  that it's valid RASP format. Nothing else in the pipeline changes.
- **Real flight data:** replace `data/sample_flight_log.csv` with your own
  altimeter/GPS logger export (any logger works — just match the 4 columns:
  `source,apogee_m,max_velocity_m_s,descent_rate_m_s,flight_time_s`).
  `apogee/stage5_validation.py` doesn't care whether the data is real.
- **Real weather:** `stage0_environment.py` currently builds a synthetic
  power-law wind-shear profile (documented in the module docstring) because
  this sandbox has no outbound internet access to a forecast feed. On a
  machine with internet access, swap `build_environment()`'s
  `set_atmospheric_model(type="custom_atmosphere", ...)` call for
  `type="Forecast"` or `type="Reanalysis"` — RocketPy supports both natively
  against GFS/NOAA data; see the RocketPy docs for the exact source string.

---

## Engineering decisions worth knowing about

**Grain geometry is estimated, not given.** The synthetic motor library only
specifies total impulse, burn time, propellant mass and total mass (exactly
what a real manufacturer's public spec sheet gives you) — not internal grain
geometry, which even real `.eng` files don't include. `rocket_builder.py`
back-solves a single-segment BATES-style grain from the known propellant
mass and a typical APCP density (1750 kg/m³) so RocketPy can model mass
depletion / CG shift during burn. This is a standard estimation technique
when exact grain design isn't available — it's called out explicitly in the
module docstring rather than silently baked in.

**The transonic "dip" isn't forced.** Stage 4 doesn't assume a margin dip
exists in the transonic band — it measures whatever the model actually
produces and reports it honestly. In this demo configuration, static margin
actually *increases* through the compressible regime (from ~1.96 cal to
~2.47 cal) as fin/nose lift-curve slopes diverge with Mach, then **plateaus**
right around M0.8 — which is the semi-empirical Barrowman/Prandtl-Glauert
correction hitting the edge of where it's formally valid, not a real
aerodynamic phenomenon. The stability module flags this explicitly:
above ~M0.8-1.2, RocketPy's (and OpenRocket's) predictions should be treated
as indicative only, and a real flight-critical margin decision near Mach 1
needs CFD or wind-tunnel cross-validation. If you have access to ANSYS
Fluent or similar, exporting the flagged geometry and running 1-2 transonic
cases is the natural next step — and a legitimate comparison study in its
own right (semi-empirical vs. CFD).

**Recovery optimization uses two different fidelities on purpose.** Stage 3
evaluates ~24 recovery configurations with single nominal (no wind
perturbation) flights, because a full Monte Carlo per candidate would be too
slow for an interactive trade study. The *recommended* configuration is
then re-run through the full Stage 2 Monte Carlo to confirm the footprint
actually shrinks once wind uncertainty is back in the picture — that
confirmation number (not Stage 3's internal estimate) is what the FRR
reports as the real footprint change. Comparing Stage 3's nominal-basis
"footprint_reduction_pct" against Stage 2's uncertainty-basis ellipse
directly would be an apples-to-oranges bug — an earlier version of this
pipeline actually made that mistake (a nonsensical -66% "reduction"); the
fix is why `run_stage3` compares every candidate, including the baseline,
on the exact same simulation basis.

**Low main-deployment altitudes will look attractive — sanity-check them.**
The Stage 3 sweep may recommend a low main-deployment altitude (e.g. 150m
AGL) because less time under the slow, wind-exposed main chute means less
drift. That's real physics. But a real mission should also enforce a hard
minimum deployment floor for canopy inflation time and a backup-deployment
timeline margin — this pipeline doesn't currently encode that as a
constraint, only as a note here. Add a `min_main_deploy_altitude_m` floor to
`MAIN_DEPLOY_ALTITUDES_M` in `stage3_recovery.py` before trusting a
recommendation on a real vehicle.

**Single motor/fin combination per run, by design.** The pipeline picks one
motor (Stage 1) and then sweeps fins for *that* motor (Stage 4), rather than
a full motor x fin cross-product. A different motor changes the Mach history
the rocket flies through, which can change the stability answer — so this is
a simplification made for pipeline runtime, not a claim that motor and fin
choice are independent. Widen `FIN_CANDIDATES` in `pipeline.py` and re-run
per motor shortlist entry if you want the full cross-product.

---

## Performance notes

- Stage 2's Monte Carlo is parallelized with `ProcessPoolExecutor`
  (`apogee/stage2_dispersion.py`) — each worker rebuilds its own
  `Environment`/`Motor`/`Rocket` from primitive parameters rather than
  pickling RocketPy objects across the process boundary, which is what
  makes the parallelization actually work cleanly.
- On this development machine (single core), one full 6-DOF flight with
  parachutes to landing takes ~0.7-1s, so 120 runs takes ~1.5-2 minutes.
  On a multi-core machine, `--workers N` will scale close to linearly —
  widen `n_dispersion_runs` in `mission_config.yaml` to 300-500 for a
  statistically tighter dispersion ellipse once you have the cores for it.
- `--quick` overrides `n_dispersion_runs` to 20 for both Monte Carlo stages,
  meant for iterating on config/geometry changes, not for a real FRR.

---

## Extending this

- **CFD cross-check:** export the Stage 4 flagged transonic geometry and
  run it through ANSYS Fluent (or OpenFOAM) at 2-3 Mach points; compare
  against RocketPy's Barrowman-based CP prediction. This is the single
  highest-value extension for anyone with a CFD background.
- **Real weather feed:** see "Real weather" above.
- **PDF export:** the FRR is Markdown by design (easy to version-control,
  diff, and paste into other tools) — pipe `outputs/flight_readiness_report.md`
  through `pandoc -o report.pdf` for a formatted PDF if a physical document
  is needed for a review board.
- **Multi-motor x multi-fin cross-product:** see "Single motor/fin
  combination" above.
- **Unified telemetry ingestion:** if you fly a real rocket, wire a real
  logger's raw output directly into `stage5_validation.load_flight_log()`
  instead of hand-editing the CSV.

---

## Testing

```bash
python3 -m pytest tests/ -v
```

19 unit tests cover the `.eng` parser (header parsing, trapezoidal impulse
integration, impulse-class classification, malformed-file handling), the
Stage 3 Pareto-front computation (domination logic, sort order, edge cases),
and the Stage 4 fin-selection rule (smallest-stable-wins, all-unstable
fallback). These are fast (no RocketPy flights) and run in under 5 seconds.
`test_motor_parser.py::test_real_synthetic_motor_library_parses` is a light
integration check against the actual generated `config/motors/` library and
skips gracefully if that directory hasn't been generated yet.

---

*Built for demonstrating a real aerospace mission-design workflow — not a
substitute for a certified flight simulator or a real safety review. Every
synthetic dataset in this repo is labeled as such; replace it with real data
before making a real flight decision from this tool's output.*
