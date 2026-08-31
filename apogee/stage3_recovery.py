"""
apogee.stage3_recovery
=========================

Sweeps drogue/main chute sizing and main deployment altitude, and finds
the trade-off between two competing objectives that can't both be
minimized at once:

  - Horizontal drift (landing footprint size) — smaller is better for
    recovery logistics and for staying inside the launch site boundary
  - Impact velocity under the main chute — smaller is safer for the
    airframe and any recovered payload/avionics, but a bigger main chute
    (which lowers impact velocity) also means more time drifting in the
    wind, which increases drift

Rather than collapsing this into one arbitrary weighted score, this
module computes the actual Pareto front (the set of candidates where no
other candidate is simultaneously better on both objectives) and reports
it explicitly — this is standard multi-objective trade-study practice,
and it's the honest way to present "there is no single best answer, only
trade-offs" to a flight-readiness reviewer.

Each candidate here is evaluated with a single nominal (unperturbed)
flight for speed; the pipeline re-runs the full Stage 2 Monte Carlo
dispersion with the *recommended* recovery configuration afterward to
confirm the footprint actually shrinks under real-world uncertainty —
that re-run is the feedback loop described in the mission architecture.
"""

from __future__ import annotations

import math

from rocketpy import Environment, Flight, SolidMotor

from apogee.schemas import AirframeSpec, FinGeometry, RecoveryCandidate, RecoveryOptimizationResult

# Sweep grid — deliberately modest so the trade study runs in seconds on
# a single core; widen this on a multi-core machine for finer resolution.
MAIN_DEPLOY_ALTITUDES_M = [150.0, 200.0, 250.0, 300.0, 400.0, 500.0]
MAIN_CD_S_OPTIONS = [4.0, 5.5, 6.5, 8.0]
DROGUE_CD_S = 1.1


def _fly_recovery_candidate(airframe: AirframeSpec, motor: SolidMotor, env: Environment,
                             fin: FinGeometry, rail_length_m: float,
                             main_deploy_altitude_m: float, main_cd_s: float) -> tuple[float, float]:
    from apogee.utils.rocket_builder import build_rocket

    rocket = build_rocket(
        airframe, motor, fin=fin, add_parachutes=True,
        drogue_cd_s=DROGUE_CD_S, main_cd_s=main_cd_s,
        main_deploy_altitude_m=main_deploy_altitude_m,
    )
    flight = Flight(
        rocket=rocket, environment=env, rail_length=rail_length_m,
        inclination=84, heading=90, terminate_on_apogee=False, max_time=400, verbose=False,
    )
    drift = math.hypot(flight.x_impact, flight.y_impact)
    impact_velocity = abs(flight.speed(flight.t_final))
    return drift, impact_velocity


def _compute_pareto_front(candidates: list[RecoveryCandidate]) -> list[RecoveryCandidate]:
    """A candidate is Pareto-optimal if no other candidate is at least as
    good on both objectives and strictly better on at least one."""
    front = []
    for c in candidates:
        dominated = any(
            (other.predicted_drift_m <= c.predicted_drift_m and
             other.predicted_impact_velocity_m_s <= c.predicted_impact_velocity_m_s and
             (other.predicted_drift_m < c.predicted_drift_m or
              other.predicted_impact_velocity_m_s < c.predicted_impact_velocity_m_s))
            for other in candidates if other is not c
        )
        if not dominated:
            c.is_pareto_optimal = True
            front.append(c)
    front.sort(key=lambda c: c.predicted_drift_m)
    return front


def run_stage3(airframe: AirframeSpec, motor: SolidMotor, env: Environment, fin: FinGeometry,
               rail_length_m: float, max_safe_impact_velocity_m_s: float = 7.0,
               baseline_main_deploy_altitude_m: float = 250.0,
               baseline_main_cd_s: float = 6.5) -> RecoveryOptimizationResult:
    candidates: list[RecoveryCandidate] = []
    for altitude in MAIN_DEPLOY_ALTITUDES_M:
        for cd_s in MAIN_CD_S_OPTIONS:
            drift, impact_v = _fly_recovery_candidate(
                airframe, motor, env, fin, rail_length_m, altitude, cd_s
            )
            candidates.append(RecoveryCandidate(
                drogue_cd_s=DROGUE_CD_S,
                main_cd_s=cd_s,
                main_deploy_altitude_m=altitude,
                predicted_drift_m=round(drift, 1),
                predicted_impact_velocity_m_s=round(impact_v, 2),
            ))

    pareto_front = _compute_pareto_front(candidates)

    safe_candidates = [c for c in candidates if c.predicted_impact_velocity_m_s <= max_safe_impact_velocity_m_s]
    pool = safe_candidates if safe_candidates else candidates
    recommended = min(pool, key=lambda c: c.predicted_drift_m)

    # Footprint reduction is measured against the SAME nominal (unperturbed)
    # simulation basis as every other candidate — i.e. the pre-optimization
    # baseline recovery config, flown exactly like every other candidate in
    # this sweep. This keeps the comparison apples-to-apples. The real,
    # wind-uncertainty-aware footprint change is confirmed separately by the
    # Stage 2 Monte Carlo re-run in the pipeline (see the FRR Stage 2 section).
    baseline_candidate = next(
        (c for c in candidates if c.main_deploy_altitude_m == baseline_main_deploy_altitude_m
         and c.main_cd_s == baseline_main_cd_s),
        None,
    )
    if baseline_candidate:
        baseline_drift_m = baseline_candidate.predicted_drift_m
        reduction_pct = 100.0 * (baseline_drift_m - recommended.predicted_drift_m) / baseline_drift_m if baseline_drift_m else 0.0
    else:
        worst_drift = max(c.predicted_drift_m for c in candidates)
        reduction_pct = 100.0 * (worst_drift - recommended.predicted_drift_m) / worst_drift if worst_drift else 0.0

    return RecoveryOptimizationResult(
        max_safe_impact_velocity_m_s=max_safe_impact_velocity_m_s,
        candidates=candidates,
        pareto_front=pareto_front,
        recommended=recommended,
        footprint_reduction_pct=round(reduction_pct, 1),
    )
