#!/usr/bin/env python3
"""
generate_sample_flight_log.py
===============================

Stage 5 (real flight validation) needs a logged flight to compare
against. Since this repository ships as a software deliverable with no
associated hardware launch, this script generates a clearly-labeled
SYNTHETIC "actual" flight log: it flies the same nominal configuration
the main pipeline will select (K740-Synth motor, baseline fin, baseline
recovery) and applies small random perturbations representative of the
kind of sim-vs-reality residual real flights typically show (a few
percent on apogee/velocity, a bit more on descent rate since parachute
performance is the least predictable part of any real flight).

>>> To validate against a REAL flight: replace data/sample_flight_log.csv
>>> with your own logger export (any altimeter/GPS logger works — just
>>> match the 4 columns below) and re-run the pipeline. Nothing else
>>> needs to change; Stage 5 doesn't care whether the data is real.
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone

from apogee.schemas import AirframeSpec, FinGeometry, LaunchSite
from apogee.stage0_environment import run_stage0
from apogee.utils.motor_parser import parse_eng_file
from apogee.utils.rocket_builder import build_motor_from_curve, build_rocket
from rocketpy import Flight

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_flight_log.csv"


def main(seed: int = 7):
    rng = random.Random(seed)

    site = LaunchSite(name="Lagos Test Range", latitude=6.5244, longitude=3.3792,
                       elevation_m=41.0, timezone="UTC")
    launch_dt = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
    _, env = run_stage0(site, launch_dt, surface_wind_m_s=4.5, surface_wind_heading_deg=270.0)

    motor_dir = Path(__file__).resolve().parent.parent / "config" / "motors"
    eng_path = str(motor_dir / "K740-Synth.eng")
    curve = parse_eng_file(eng_path)
    motor = build_motor_from_curve(curve, eng_path)

    airframe = AirframeSpec(radius_m=0.0515, dry_mass_kg=3.6, dry_inertia_kg_m2=(1.0, 1.0, 0.012),
                             center_of_dry_mass_m=1.05, rail_length_m=5.2)
    fin = FinGeometry(fin_id="baseline", root_chord_m=0.10, tip_chord_m=0.03, span_m=0.075,
                       sweep_length_m=0.055, position_m=0.20)

    rocket = build_rocket(airframe, motor, fin=fin, add_parachutes=True,
                           drogue_cd_s=1.1, main_cd_s=6.5, main_deploy_altitude_m=250.0)
    flight = Flight(rocket=rocket, environment=env, rail_length=airframe.rail_length_m,
                     inclination=84, heading=90, terminate_on_apogee=False, max_time=400, verbose=False)

    nominal_apogee = flight.apogee - env.elevation
    nominal_velocity = flight.max_speed
    nominal_descent = abs(flight.speed(flight.t_final))
    nominal_time = flight.t_final

    # Representative sim-vs-reality residuals (see stage5_validation.py
    # docstring for what real flights typically show and why).
    actual_apogee = nominal_apogee * (1 + rng.gauss(0, 0.03))
    actual_velocity = nominal_velocity * (1 + rng.gauss(0, 0.025))
    actual_descent = nominal_descent * (1 + rng.gauss(0, 0.06))
    actual_time = nominal_time * (1 + rng.gauss(0, 0.01))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "apogee_m", "max_velocity_m_s", "descent_rate_m_s", "flight_time_s"])
        writer.writerow([
            "synthetic_demo_flight_log",
            round(actual_apogee, 1), round(actual_velocity, 2),
            round(actual_descent, 2), round(actual_time, 1),
        ])

    print(f"Wrote {OUT_PATH}")
    print(f"  nominal sim : apogee={nominal_apogee:.1f}m  v_max={nominal_velocity:.1f}m/s  "
          f"descent={nominal_descent:.2f}m/s  t={nominal_time:.1f}s")
    print(f"  synthetic actual: apogee={actual_apogee:.1f}m  v_max={actual_velocity:.1f}m/s  "
          f"descent={actual_descent:.2f}m/s  t={actual_time:.1f}s")


if __name__ == "__main__":
    main()
