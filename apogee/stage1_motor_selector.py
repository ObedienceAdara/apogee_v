"""
apogee.stage1_motor_selector
==============================

Sweeps every motor in the library against the fixed airframe, runs a
quick (terminate-at-apogee) RocketPy flight for each, and ranks
candidates against the target apogee — subject to two hard constraints
that a real flier can't ignore:

  1. Certification level: total impulse must not exceed what the flier
     is certified to fly (this is a real regulatory constraint in high
     power rocketry, not just a modeling nicety).
  2. Apogee tolerance band: predicted apogee must fall within
     +/- apogee_tolerance_pct of the target (range safety / waiver
     altitude ceilings are real hard limits at most launch sites).

The ranking score balances closeness to target apogee against cost, so
"cheapest motor that safely hits the target" wins over "biggest motor
available" — mirroring how a real team picks motors under a budget.
"""

from __future__ import annotations

import csv
from pathlib import Path

from rocketpy import Environment, Flight

from apogee.schemas import AirframeSpec, ImpulseClass, MotorCandidate, MotorSelectionResult
from apogee.utils.motor_parser import discover_motor_library
from apogee.utils.rocket_builder import DEFAULT_FIN, build_motor_from_curve, build_rocket


def _load_costs(motor_dir: Path) -> dict[str, float]:
    costs_file = motor_dir / "motor_costs.csv"
    costs = {}
    if costs_file.exists():
        with open(costs_file) as f:
            for row in csv.DictReader(f):
                costs[row["motor_id"]] = float(row["cost_usd"])
    return costs


def _fly_quick(airframe: AirframeSpec, motor, env: Environment, rail_length_m: float):
    rocket = build_rocket(airframe, motor, fin=DEFAULT_FIN)
    flight = Flight(
        rocket=rocket, environment=env, rail_length=rail_length_m,
        inclination=84, heading=90, terminate_on_apogee=True, verbose=False,
    )
    return flight


def run_stage1(airframe: AirframeSpec, env: Environment, motor_library_dir: str,
               target_apogee_m: float, apogee_tolerance_pct: float = 5.0) -> MotorSelectionResult:
    motor_dir = Path(motor_library_dir)
    curves = discover_motor_library(motor_dir)
    if not curves:
        raise RuntimeError(
            f"No .eng thrust curve files found in {motor_dir}. Run "
            "scripts/generate_synthetic_motors.py or add real .eng files."
        )
    costs = _load_costs(motor_dir)

    candidates: list[MotorCandidate] = []
    for motor_id, curve in curves.items():
        eng_path = str(motor_dir / f"{motor_id}.eng")
        motor = build_motor_from_curve(curve, eng_path)
        flight = _fly_quick(airframe, motor, env, airframe.rail_length_m)

        apogee = flight.apogee - env.elevation  # AGL, not ASL
        max_q = flight.max_dynamic_pressure
        max_mach = flight.max_mach_number
        apogee_error_pct = 100.0 * (apogee - target_apogee_m) / target_apogee_m
        passes_cert = curve.total_impulse_n_s <= airframe.certification_level_max_impulse_n_s
        within_tolerance = abs(apogee_error_pct) <= apogee_tolerance_pct

        candidate = MotorCandidate(
            motor_id=motor_id,
            manufacturer=curve.manufacturer,
            impulse_class=ImpulseClass(curve.impulse_class) if curve.impulse_class in ImpulseClass.__members__ else ImpulseClass.J,
            thrust_curve_file=eng_path,
            total_impulse_n_s=round(curve.total_impulse_n_s, 1),
            burn_time_s=round(curve.burn_time_s, 2),
            propellant_mass_kg=round(curve.propellant_mass_kg, 4),
            dry_mass_kg=round(curve.dry_mass_kg, 4),
            cost_usd=costs.get(motor_id),
            predicted_apogee_m=round(apogee, 1),
            predicted_max_q_pa=round(max_q, 1),
            predicted_max_mach=round(max_mach, 3),
            apogee_error_pct=round(apogee_error_pct, 2),
            passes_certification=passes_cert,
        )
        candidates.append(candidate)

    eligible = [c for c in candidates if c.passes_certification and abs(c.apogee_error_pct) <= apogee_tolerance_pct]

    pool = eligible if eligible else candidates
    for c in pool:
        cost_component = (c.cost_usd / 200.0) if c.cost_usd else 0.5
        c.rank_score = round(abs(c.apogee_error_pct) + cost_component, 3)

    ranked = sorted(pool, key=lambda c: c.rank_score)
    shortlist = ranked[:5]

    if not eligible:
        # Nothing hit the tolerance band and cert limit simultaneously —
        # surface the closest miss rather than silently picking randomly,
        # so the pipeline can flag it as a blocking issue upstream.
        selected = min(candidates, key=lambda c: abs(c.apogee_error_pct))
    else:
        selected = shortlist[0]

    return MotorSelectionResult(
        target_apogee_m=target_apogee_m,
        apogee_tolerance_pct=apogee_tolerance_pct,
        shortlist=shortlist,
        selected=selected,
    )
