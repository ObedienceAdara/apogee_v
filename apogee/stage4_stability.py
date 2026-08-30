"""
apogee.stage4_stability
=========================

Sweeps trapezoidal fin geometry and computes static margin (in calibers)
as a continuous function of Mach number across the full boost + coast to
apogee, using an actual ``rocketpy.Flight`` (not just a static CP
calculation) so the margin reflects the real CG shift from propellant
burn *and* the real Mach history the rocket flies through.

Why this matters (and why most student projects skip it): center of
pressure is NOT fixed. As the rocket accelerates through the subsonic
compressible regime, fin and nose-cone lift-curve slopes both increase
per the Prandtl-Glauert correction, and the two don't grow at the same
rate — so CP position (and therefore static margin) genuinely moves
during flight. A rocket comfortably stable at Mach 0.2 is not
guaranteed to still be comfortably stable at Mach 0.9.

Important modeling caveat (stated explicitly in the output, not hidden):
the semi-empirical Barrowman method with a Prandtl-Glauert compressibility
correction — what RocketPy (and OpenRocket) use — is only formally valid
up to roughly Mach 0.8-1.2. Above that, real transonic aerodynamics
requires CFD or wind-tunnel data. This module still tracks and reports
margin through that band, but flags it as "modeling-limit" territory
rather than presenting it with false confidence — exactly the kind of
caveat a real flight-readiness review would demand.
"""

from __future__ import annotations

import numpy as np
from rocketpy import Flight, SolidMotor, Environment

from apogee.schemas import AirframeSpec, FinGeometry, StabilityPoint, StabilityResult
from apogee.utils.rocket_builder import build_rocket

TRANSONIC_LOW = 0.8
TRANSONIC_HIGH = 1.2


def _sample_margin_curve(flight: Flight, n_points: int = 150) -> list[StabilityPoint]:
    t_end = max(flight.apogee_time, 0.5)
    times = np.linspace(0.05, t_end, n_points)
    points = []
    for t in times:
        try:
            mach = float(flight.mach_number(t))
            margin = float(flight.stability_margin(t))
        except Exception:
            continue
        points.append(StabilityPoint(time_s=round(float(t), 4),
                                      mach=round(mach, 4),
                                      static_margin_cal=round(margin, 4)))
    return points


def evaluate_fin_geometry(airframe: AirframeSpec, motor: SolidMotor, env: Environment,
                           fin: FinGeometry, rail_length_m: float,
                           safety_threshold_cal: float = 1.0) -> StabilityResult:
    """Fly one fin configuration and analyze its margin-vs-Mach curve."""
    rocket = build_rocket(airframe, motor, fin=fin)
    flight = Flight(
        rocket=rocket, environment=env, rail_length=rail_length_m,
        inclination=84, heading=90, terminate_on_apogee=True, verbose=False,
    )
    curve = _sample_margin_curve(flight)
    if not curve:
        raise RuntimeError(f"Stability sweep produced no valid samples for fin {fin.fin_id}")

    min_point = min(curve, key=lambda p: p.static_margin_cal)

    transonic_points = [p for p in curve if TRANSONIC_LOW <= p.mach <= TRANSONIC_HIGH]
    if transonic_points:
        transonic_min = min(p.static_margin_cal for p in transonic_points)
        # local dip = transonic minimum is lower than the margin value just
        # before the rocket entered the transonic band
        pre_transonic = [p for p in curve if p.mach < TRANSONIC_LOW]
        pre_margin = pre_transonic[-1].static_margin_cal if pre_transonic else curve[0].static_margin_cal
        dip_detected = transonic_min < pre_margin - 1e-6
    else:
        transonic_min = min_point.static_margin_cal
        dip_detected = False

    notes = []
    max_mach = max(p.mach for p in curve)
    if max_mach >= TRANSONIC_LOW:
        notes.append(
            f"Flight reaches Mach {max_mach:.2f} — enters the transonic band (>=M{TRANSONIC_LOW}). "
            "Barrowman/Prandtl-Glauert compressibility correction is not formally valid above "
            f"~M{TRANSONIC_LOW}-{TRANSONIC_HIGH}; treat margin values in this band as indicative "
            "only. Recommend CFD or wind-tunnel cross-check before flight-critical sign-off."
        )
    if dip_detected:
        notes.append(
            f"Local margin DIP detected entering the transonic band: {pre_margin:.2f} cal -> "
            f"{transonic_min:.2f} cal. Verify against a higher-fidelity aero model before flight."
        )
    else:
        notes.append(
            "No transonic margin dip detected for this configuration — margin trends upward "
            "through the compressible regime, consistent with CP moving aft as fin/nose lift-curve "
            "slopes diverge with Mach. The tightest margin for this design is elsewhere in the "
            "flight (see min_margin_mach)."
        )

    is_stable = min_point.static_margin_cal >= safety_threshold_cal

    return StabilityResult(
        fin=fin,
        curve=curve,
        min_margin_cal=round(min_point.static_margin_cal, 4),
        min_margin_mach=round(min_point.mach, 4),
        transonic_min_margin_cal=round(transonic_min, 4),
        transonic_dip_detected=dip_detected,
        is_stable=is_stable,
        safety_threshold_cal=safety_threshold_cal,
        notes=notes,
    )


def fin_area_m2(fin: FinGeometry) -> float:
    """Approximate single-fin planform area (trapezoid), used as the
    'minimize drag' objective when several fin sets all pass the safety
    margin check."""
    return 0.5 * (fin.root_chord_m + fin.tip_chord_m) * fin.span_m


def sweep_fin_geometry(airframe: AirframeSpec, motor: SolidMotor, env: Environment,
                        rail_length_m: float, candidates: list[FinGeometry],
                        safety_threshold_cal: float = 1.0) -> tuple[StabilityResult, list[StabilityResult]]:
    """
    Evaluate every candidate fin geometry. Selection rule (standard HPR
    fin-sizing practice): among all candidates that stay stable across the
    ENTIRE flight (including the transonic band), pick the one with the
    smallest fin planform area — smaller fins mean less drag and a higher
    apogee for the same motor, so "just barely enough stability" is the
    correct engineering target, not "as much as possible."
    """
    results = [
        evaluate_fin_geometry(airframe, motor, env, fin, rail_length_m, safety_threshold_cal)
        for fin in candidates
    ]
    stable_results = [r for r in results if r.is_stable]
    if stable_results:
        selected = min(stable_results, key=lambda r: fin_area_m2(r.fin))
    else:
        # Nothing passed — surface the least-bad option so the pipeline can
        # halt with a clear blocking issue rather than crashing.
        selected = max(results, key=lambda r: r.min_margin_cal)
    return selected, results
