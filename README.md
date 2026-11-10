# Apogee — Rocket Mission Simulation & Verification

> **A systems-engineering pipeline for rocket mission design, flight simulation, uncertainty analysis, recovery trade studies, and flight-readiness reporting.**

Apogee combines **RocketPy**, **Astropy**, **NumPy/SciPy**, and **Pydantic** into one reproducible workflow rather than a collection of disconnected scripts.

The pipeline evaluates a configurable rocket mission through environment checks, motor selection, Mach-dependent stability analysis, six-degree-of-freedom Monte Carlo dispersion, recovery optimization, optional flight-log comparison, and automated report generation.

**Important:** this repository is a simulation and analysis project. It is **not** a certified flight simulator, launch authorization system, or substitute for a real range-safety review. The current demonstration uses synthetic motor and flight-log data, clearly labeled below.

---

## System Architecture

```text
                         MISSION CONFIG
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 0 — ENVIRONMENT & LAUNCH WINDOW                       │
│  Astropy solar geometry + atmospheric/wind model             │
│  Output: shared environment + Go/No-Go scorecard             │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 1 — MOTOR SELECTION                                   │
│  Sweep motor library → apogee error + cost + certification   │
│  Output: ranked motor shortlist                              │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 4 — STABILITY vs MACH                                 │
│  Fin sweep → CP/CG / static-margin history through flight    │
│  Output: selected fin geometry + stability result             │
│                                                              │
│  BLOCKING CONDITION: no candidate above safety threshold     │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 2 — MONTE CARLO DISPERSION                            │
│  Full 6-DOF flights with uncertainty in:                     │
│  wind · thrust · mass · CG · rail angle                      │
│  Output: landing distribution + 95% confidence ellipse       │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 3 — RECOVERY TRADE STUDY                              │
│  Sweep main/drogue configurations                             │
│  Objectives: minimize drift + minimize impact velocity       │
│  Output: Pareto front + recommended configuration             │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 2 — CONFIRMATION RUN                                  │
│  Re-run the optimized recovery configuration through the     │
│  full Monte Carlo analysis to verify the footprint change     │
│  under uncertainty                                           │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 5 — FLIGHT-LOG COMPARISON (OPTIONAL)                  │
│  Simulated vs logged apogee / velocity / descent rate        │
│  Output: signed residuals + likely error sources              │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
                    FLIGHT READINESS REPORT
                  Markdown + JSON + 3 plots
```

The important design choice is that these stages **share typed data contracts** rather than passing unstructured dictionaries. Pydantic models in `apogee/schemas.py` define the interfaces between mission stages and make malformed hand-offs fail explicitly.

---

## What the Pipeline Models

### Environment

The launch-condition stage evaluates:

- solar elevation / civil-twilight state
- altitude-dependent wind profile
- maximum modeled ground-band wind
- configurable launch-condition limits

The current demonstration uses a deterministic power-law wind profile rather than a live forecast feed.

### Motor Selection

The pipeline discovers RASP-format `.eng` files, parses their thrust curves, builds RocketPy motor models, and evaluates candidates against a target apogee.

Candidates are ranked using mission-relevant constraints rather than simply selecting the most powerful motor.

### Stability

For each candidate fin set, the pipeline runs an actual RocketPy flight and samples static margin against Mach through the modeled boost/coast segment.

This means the reported margin can reflect:

- propellant burn and CG migration
- Mach-dependent aerodynamic behavior
- the actual simulated flight history

The implementation explicitly flags the transonic region as a **model-confidence boundary** for the semi-empirical aerodynamic treatment.

### Dispersion

The core uncertainty analysis runs independent six-degree-of-freedom flights while perturbing:

- wind speed
- wind direction
- motor thrust scale
- dry mass
- center-of-gravity position
- launch inclination
- launch heading

The resulting landing points are summarized with a **95% confidence ellipse**.

### Recovery Optimization

Recovery is treated as a multi-objective problem:

```text
        Horizontal drift  ← minimize
                  ↕
        Impact velocity   ← minimize
```

Instead of inventing one weighted score, the pipeline computes the **Pareto-optimal set** and then selects a configuration subject to the configured impact-velocity limit.

The chosen configuration is subsequently pushed back through Stage 2 for a full uncertainty-aware confirmation run.

### Flight-Log Comparison

If a flight log is configured, Stage 5 compares:

- apogee
- maximum velocity
- descent rate

and reports signed percentage error plus possible sources of discrepancy.

The current repository does **not** contain a real hardware flight.

---

## Technical Design

### Typed stage interfaces

Every pipeline stage communicates through Pydantic models in `apogee/schemas.py`.

Examples include:

```text
MissionConfig
     ↓
EnvironmentReport
     ↓
MotorSelectionResult
     ↓
StabilityResult
     ↓
DispersionAnalysisResult
     ↓
RecoveryOptimizationResult
     ↓
ValidationResult
     ↓
FlightReadinessReport
```

This keeps the pipeline inspectable and makes stage boundaries explicit.

### Single rocket-construction path

`apogee/utils/rocket_builder.py` centralizes rocket and motor construction so geometry and common assumptions are not duplicated across stages.

### Parallel Monte Carlo

Stage 2 uses `ProcessPoolExecutor` because each dispersion flight is independent.

Workers rebuild RocketPy objects from primitive inputs instead of attempting to pickle complex RocketPy objects across processes.

### Deterministic experiment setup

Stage 2 pre-samples uncertainty inputs from a seeded random generator so the experiment can be repeated with the same configuration and seed.

---

## Demo Results

The current v1.0 demonstration was run with the configured synthetic mission.

| Quantity | Recorded result |
|---|---:|
| Target apogee | **2,200 m** |
| Selected motor | **K740-Synth** |
| Apogee error | **0.12%** |
| Minimum static margin | **1.96 cal** |
| Monte Carlo runs | **120** |
| Tests | **19** |
| Landing dispersion | **919 m, 95% confidence** |

These numbers describe the **software's current synthetic demonstration**, not a real launch campaign.

The generated report contains:

- motor-selection shortlist
- stability-margin analysis
- 6-DOF dispersion statistics
- landing ellipse
- recovery trade-off
- optional V&V comparison

Run the pipeline yourself to regenerate the artifacts.

---

## Repository Structure

```text
apogee_v/
├── README.md
├── requirements.txt
├── LICENSE
│
├── apogee/
│   ├── schemas.py
│   ├── pipeline.py
│   ├── report.py
│   ├── stage0_environment.py
│   ├── stage1_motor_selector.py
│   ├── stage2_dispersion.py
│   ├── stage3_recovery.py
│   ├── stage4_stability.py
│   ├── stage5_validation.py
│   └── utils/
│       ├── motor_parser.py
│       └── rocket_builder.py
│
├── config/
│   ├── mission_config.yaml
│   └── motors/
│       ├── *.eng
│       └── motor_costs.csv
│
├── data/
│   └── sample_flight_log.csv
│
├── scripts/
│   ├── run_pipeline.py
│   ├── generate_synthetic_motors.py
│   └── generate_sample_flight_log.py
│
└── tests/
    ├── test_motor_parser.py
    ├── test_stage3_recovery.py
    └── test_stage4_stability.py
```

Generated artifacts are written to `outputs/` when the pipeline runs.

---

## Quickstart

### 1. Install

```bash
python3 -m pip install -r requirements.txt
```

### 2. Run the test suite

```bash
python3 -m pytest tests/ -v
```

Expected unit-test count for the current release:

```text
19 passed
```

### 3. Run the full pipeline

```bash
python3 scripts/run_pipeline.py
```

The default mission configuration uses **120 Monte Carlo runs**.

### 4. Run a quick smoke test

```bash
python3 scripts/run_pipeline.py --quick
```

The quick mode reduces the Monte Carlo count for iteration and debugging. It is not intended to replace the full analysis run.

### 5. Inspect generated artifacts

```text
outputs/
├── flight_readiness_report.md
├── flight_readiness_report.json
├── dispersion_ellipse.png
├── stability_margin.png
└── recovery_pareto.png
```

---

## Synthetic Data & Modeling Boundaries

This repository is deliberately explicit about what is simulated, estimated, and not yet physically validated.

### Synthetic motor library

The included `.eng` files are generated demonstration thrust curves.

They are **not certified manufacturer motor data**.

The pipeline accepts real RASP-format motor files without requiring changes to the parser.

### Synthetic flight log

`data/sample_flight_log.csv` is a clearly labeled synthetic log used to demonstrate the Stage 5 comparison pipeline.

There is no hardware launch associated with this repository.

### Weather

The current environment model uses a deterministic power-law wind-shear approximation.

The code provides a clear swap point for a real forecast/reanalysis source on a machine with an appropriate data feed.

### Aerodynamic model

The stability analysis uses semi-empirical aerodynamic methods available through RocketPy. The repository explicitly treats the transonic region as a modeling-confidence boundary.

For a flight-critical model, this should be independently cross-checked with higher-fidelity aerodynamic data such as CFD or wind-tunnel measurements.

---

## Engineering Decisions

### 1. Estimated grain geometry

The demo motor inputs provide propellant/total mass and thrust curves, but not internal grain geometry.

`rocket_builder.py` therefore estimates a single-segment BATES-style geometry so RocketPy can model propellant depletion and CG movement.

The assumption is documented rather than hidden.

### 2. Stability is evaluated across the flight

The system does not rely on one static low-speed stability calculation.

It samples static margin throughout the modeled flight, allowing CG and Mach effects to appear in the result.

### 3. Transonic results are not presented as certification-grade

The repository deliberately avoids treating the Barrowman/Prandtl–Glauert region beyond its useful range as authoritative.

The output flags the modeling boundary instead of silently presenting the numbers as fact.

### 4. Recovery uses two simulation fidelities

The recovery sweep is deliberately inexpensive so many configurations can be compared.

The selected configuration is then evaluated again through the full Monte Carlo dispersion model.

This prevents the optimizer from being judged on a different simulation basis from the final uncertainty analysis.

### 5. Motor and fin coupling is explicit

The current pipeline selects a motor first and evaluates fin candidates for that motor.

A complete motor × fin cross-product is intentionally left as a future extension because motor choice changes the Mach history and therefore can change the stability result.

---

## Verification vs. Validation

A central distinction in this project is:

> **Verification asks whether the software implements its intended model correctly. Validation asks whether the model represents the physical system accurately enough for its intended use.**

The current repository contains automated verification tests and a framework for importing flight data for validation.

It does **not** claim physical validation of a real vehicle.

That distinction is intentional.

### Decision-gate semantics

The generated report deliberately separates **engineering gate status** from **launch authorization**.

- `engineering_gates_passed` means only that the configured software checks passed.
- `launch_authorization_status` is fixed to `NOT_AUTHORIZED`. This software cannot grant range approval, certify a vehicle or motor, or replace competent human review.
- A launch time in the past, an environment-gate failure, a motor over the configured total-impulse limit, an out-of-tolerance motor apogee, insufficient stability margin, or a Monte Carlo successful-run rate below the configured minimum blocks the engineering gate.
- Both baseline and optimized-recovery Monte Carlo runs must meet `minimum_monte_carlo_success_rate_pct` (95% by default). Failed runs retain their IDs and exception summaries in the result instead of disappearing from the report. At least two runs must converge to calculate a covariance ellipse.
- Recovery optimization must find a candidate within the configured impact-velocity limit. If none exists, the least-impact-velocity candidate is shown for diagnosis only and blocks the gate.
- A physical-validation evidence gate requires a non-synthetic flight log and an operator attestation that the flight configuration matches the simulated configuration. A source string containing `synthetic` is always classified as synthetic, even when the configuration flag is false. The configuration-match flag is an operator assertion, not independent authentication.

The demo configuration intentionally marks its included log as synthetic and its configuration match as unverified. It also contains a historical launch date. It must therefore produce a **NO-GO** engineering status. This is expected: the demo is not evidence of launch readiness.

The Stage 5 comparison uses a separate nominal RocketPy flight with the selected motor, fin geometry, and recovery settings. It does not infer velocity from Mach using a fixed speed-of-sound value or compare a Monte Carlo mean against a different baseline configuration.

---

## Test Coverage

The current test suite contains **32 unit tests** covering:

### RASP motor parser

- header parsing
- thrust-point parsing
- dry-mass calculation
- burn-time calculation
- trapezoidal impulse integration
- impulse-class classification
- malformed-file handling
- motor-library discovery

### Recovery optimizer

- Pareto dominance
- non-dominated trade-offs
- sorting
- Pareto flags

### Stability selection

- fin-area calculation
- smallest-stable-fin selection
- unstable-candidate exclusion
- all-unstable fallback behavior

### Readiness and validation gates

- past launch-time rejection
- motor impulse-limit rejection
- recovery feasibility and impact-limit rejection
- baseline and confirmation Monte Carlo convergence thresholds
- synthetic and unverified flight-log rejection
- physical-log comparison tolerance

The current tests primarily exercise deterministic logic without running full RocketPy flights, keeping the suite fast.

---

## Development Lessons

A useful part of this project was discovering that the engineering work was not simply writing the physics pipeline.

Two examples:

### Recovery-footprint comparison

An earlier implementation produced an apparently nonsensical negative footprint reduction because two different simulation bases were being compared.

The fix was to compare like-for-like configurations and then confirm the final result through the full Monte Carlo run.

### RocketPy API assumption

A flight-reporting implementation initially assumed an attribute name that did not exist in the RocketPy API.

The error was caught during execution and corrected by checking the actual interface rather than guessing.

These are small examples, but they capture the intended workflow:

```text
Implement
   ↓
Run
   ↓
Observe failure
   ↓
Diagnose
   ↓
Fix
   ↓
Test
   ↓
Record
```

---

## Roadmap

### Near term

- real motor thrust-curve inputs
- real weather/reanalysis feed
- larger motor × fin trade space
- explicit minimum main-deployment constraint
- stronger end-to-end integration testing
- richer generated plots and raw result exports

### Aerodynamic fidelity

- export geometry for CFD comparison
- compare semi-empirical stability predictions against CFD around transonic conditions
- incorporate higher-fidelity aerodynamic databases where available

### Flight-data validation

- ingest real altimeter/GPS telemetry
- compare complete simulated and measured trajectories
- quantify residuals and model bias
- use measured data to calibrate uncertain model parameters

### Autonomy

The long-term direction is to expose the simulation as an environment for:

- trim and linearization
- classical guidance/control
- reinforcement-learning controllers
- disturbance rejection
- trajectory optimization
- autonomous flight experiments

That is the bridge from **mission analysis** to **aerospace autonomous-systems research**.

---

## Why this project exists

The goal is not to claim a certified rocket simulation.

The goal is to build a transparent computational engineering workflow in which:

**assumptions are visible,**

**uncertainty is modeled,**

**trade-offs are explicit,**

**results are reproducible,**

**failures are documented,**

and **validation boundaries are not hidden.**

---

## License

MIT

---

*Apogee is an educational/research software project for demonstrating aerospace systems engineering, simulation, uncertainty analysis, and verification workflows. Do not use its current outputs as a substitute for professional engineering review, certified simulation tools, range-safety analysis, or flight authorization.*
