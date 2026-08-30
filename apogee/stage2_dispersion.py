"""
apogee.stage2_dispersion
==========================

The computational core of the pipeline: runs N full six-degree-of-freedom
RocketPy flights (boost -> coast -> apogee -> drogue -> main -> landing),
randomizing the inputs a real flight actually has uncertainty in:

  - Wind speed and heading (the whole altitude profile, scaled + rotated
    together per run — wind doesn't vary independently at each altitude
    in reality, it's correlated)
  - Motor thrust curve, within manufacturer-typical tolerance (+/-5-10%
    of total impulse, applied as a uniform scale on the thrust-vs-time
    curve)
  - Dry mass and center-of-gravity, within manufacturing/assembly
    tolerance
  - Launch rail angle (real rails are never perfectly vertical/aimed)

Each run is fully independent, so this is embarrassingly parallel — run
across all available CPU cores with ``ProcessPoolExecutor`` rather than
serially, which is the difference between a 500-run Monte Carlo taking
minutes instead of an hour on a laptop.

Output: a landing dispersion ellipse (95% confidence, via the covariance
matrix of landing x/y points) — this is literally what range safety
officers use to size the closure area around a launch site, and it's the
single artifact competition/industry reviewers most want to see.
"""

from __future__ import annotations

import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

import numpy as np

from apogee.schemas import (
    AirframeSpec, DispersionAnalysisResult, DispersionEllipse,
    DispersionRunResult, LaunchSite,
)

# 95% confidence chi-square value for 2 degrees of freedom
CHI2_95_2DOF = 5.991


@dataclass
class DispersionRunInputs:
    run_id: int
    site: LaunchSite
    launch_dt_iso: str
    base_wind_profile: list[tuple[float, float, float]]  # (alt_agl, speed, heading)
    airframe: AirframeSpec
    eng_file_path: str
    fin_params: tuple  # (n, root, tip, span, sweep, position)
    rail_length_m: float
    drogue_cd_s: float
    main_cd_s: float
    main_deploy_altitude_m: float
    # perturbation draws (pre-sampled so results are reproducible given a seed)
    wind_speed_scale: float
    wind_heading_offset_deg: float
    thrust_scale: float
    mass_scale: float
    cg_offset_m: float
    inclination_deg: float
    heading_deg: float


def _run_one(inputs: DispersionRunInputs) -> DispersionRunResult:
    """Runs in a worker process — imports rocketpy locally and rebuilds
    every object from scratch so nothing complex needs to be pickled
    across the process boundary."""
    from datetime import datetime

    from rocketpy import Environment, Flight, SolidMotor

    from apogee.schemas import FinGeometry
    from apogee.utils.motor_parser import parse_eng_file
    from apogee.utils.rocket_builder import build_motor_from_curve, build_rocket

    try:
        env = Environment(
            latitude=inputs.site.latitude,
            longitude=inputs.site.longitude,
            elevation=inputs.site.elevation_m,
            timezone="UTC",
            max_expected_height=8000.0,
        )
        dt = datetime.fromisoformat(inputs.launch_dt_iso)
        env.set_date((dt.year, dt.month, dt.day, dt.hour), timezone="UTC")

        heights, u_pts, v_pts = [], [], []
        for alt, speed, heading in inputs.base_wind_profile:
            speed_p = speed * inputs.wind_speed_scale
            heading_p = (heading + inputs.wind_heading_offset_deg) % 360.0
            h = alt + inputs.site.elevation_m
            u = speed_p * np.sin(np.radians(heading_p))
            v = speed_p * np.cos(np.radians(heading_p))
            heights.append(h)
            u_pts.append((h, u))
            v_pts.append((h, v))
        env.set_atmospheric_model(type="custom_atmosphere", wind_u=u_pts, wind_v=v_pts)

        curve = parse_eng_file(inputs.eng_file_path)
        motor = build_motor_from_curve(curve, inputs.eng_file_path)
        # apply thrust-curve tolerance by rescaling the motor's thrust Function in place
        motor.thrust *= inputs.thrust_scale

        perturbed_airframe = inputs.airframe.model_copy(update={
            "dry_mass_kg": inputs.airframe.dry_mass_kg * inputs.mass_scale,
            "center_of_dry_mass_m": inputs.airframe.center_of_dry_mass_m + inputs.cg_offset_m,
        })

        n, root, tip, span, sweep, position = inputs.fin_params
        fin = FinGeometry(fin_id="dispersion", n_fins=n, root_chord_m=root, tip_chord_m=tip,
                           span_m=span, sweep_length_m=sweep, position_m=position)

        rocket = build_rocket(
            perturbed_airframe, motor, fin=fin, add_parachutes=True,
            drogue_cd_s=inputs.drogue_cd_s, main_cd_s=inputs.main_cd_s,
            main_deploy_altitude_m=inputs.main_deploy_altitude_m,
        )

        flight = Flight(
            rocket=rocket, environment=env, rail_length=inputs.rail_length_m,
            inclination=inputs.inclination_deg, heading=inputs.heading_deg,
            terminate_on_apogee=False, max_time=400, verbose=False,
        )

        return DispersionRunResult(
            run_id=inputs.run_id,
            apogee_m=round(flight.apogee - env.elevation, 2),
            max_q_pa=round(flight.max_dynamic_pressure, 2),
            max_mach=round(flight.max_mach_number, 4),
            landing_x_m=round(flight.x_impact, 2),
            landing_y_m=round(flight.y_impact, 2),
            time_to_apogee_s=round(flight.apogee_time, 2),
            flight_time_s=round(flight.t_final, 2),
            converged=True,
        )
    except Exception:
        return DispersionRunResult(
            run_id=inputs.run_id, apogee_m=0, max_q_pa=0, max_mach=0,
            landing_x_m=0, landing_y_m=0, time_to_apogee_s=0, flight_time_s=0,
            converged=False,
        )


def _sample_inputs(run_id: int, site: LaunchSite, launch_dt_iso: str,
                    base_wind_profile, airframe: AirframeSpec, eng_file_path: str,
                    fin_params, rail_length_m: float, drogue_cd_s: float, main_cd_s: float,
                    main_deploy_altitude_m: float, rng: random.Random) -> DispersionRunInputs:
    return DispersionRunInputs(
        run_id=run_id, site=site, launch_dt_iso=launch_dt_iso,
        base_wind_profile=base_wind_profile, airframe=airframe, eng_file_path=eng_file_path,
        fin_params=fin_params, rail_length_m=rail_length_m,
        drogue_cd_s=drogue_cd_s, main_cd_s=main_cd_s, main_deploy_altitude_m=main_deploy_altitude_m,
        wind_speed_scale=max(0.05, rng.gauss(1.0, 0.15)),
        wind_heading_offset_deg=rng.gauss(0.0, 10.0),
        thrust_scale=rng.gauss(1.0, 0.05),
        mass_scale=rng.gauss(1.0, 0.02),
        cg_offset_m=rng.gauss(0.0, 0.01),
        inclination_deg=84.0 + rng.gauss(0.0, 1.5),
        heading_deg=90.0 + rng.gauss(0.0, 3.0),
    )


def _confidence_ellipse(x: np.ndarray, y: np.ndarray, confidence: float = 0.95) -> DispersionEllipse:
    cov = np.cov(np.vstack([x, y]))
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    order = eigenvalues.argsort()[::-1]
    eigenvalues, eigenvectors = eigenvalues[order], eigenvectors[:, order]

    semi_major = float(np.sqrt(max(eigenvalues[0], 0.0) * CHI2_95_2DOF))
    semi_minor = float(np.sqrt(max(eigenvalues[1], 0.0) * CHI2_95_2DOF))
    angle = float(np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0])))

    return DispersionEllipse(
        center_x_m=round(float(np.mean(x)), 2),
        center_y_m=round(float(np.mean(y)), 2),
        semi_major_m=round(semi_major, 2),
        semi_minor_m=round(semi_minor, 2),
        rotation_deg=round(angle, 2),
        confidence=confidence,
    )


def run_stage2(site: LaunchSite, launch_dt_iso: str, base_wind_profile: list[tuple[float, float, float]],
               airframe: AirframeSpec, eng_file_path: str, fin_params: tuple, rail_length_m: float,
               n_runs: int = 200, drogue_cd_s: float = 1.1, main_cd_s: float = 6.5,
               main_deploy_altitude_m: float = 250.0, max_workers: int | None = None,
               seed: int = 42) -> DispersionAnalysisResult:
    rng = random.Random(seed)
    jobs = [
        _sample_inputs(i, site, launch_dt_iso, base_wind_profile, airframe, eng_file_path,
                        fin_params, rail_length_m, drogue_cd_s, main_cd_s, main_deploy_altitude_m, rng)
        for i in range(n_runs)
    ]

    results: list[DispersionRunResult] = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_one, job) for job in jobs]
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r.run_id)

    converged = [r for r in results if r.converged]
    n_converged = len(converged)
    if n_converged == 0:
        raise RuntimeError("All Monte Carlo dispersion runs failed to converge — check inputs.")

    x = np.array([r.landing_x_m for r in converged])
    y = np.array([r.landing_y_m for r in converged])
    apogees = np.array([r.apogee_m for r in converged])
    max_qs = np.array([r.max_q_pa for r in converged])

    ellipse = _confidence_ellipse(x, y)

    return DispersionAnalysisResult(
        n_runs=n_runs,
        n_converged=n_converged,
        runs=results,
        landing_ellipse_95=ellipse,
        apogee_mean_m=round(float(np.mean(apogees)), 2),
        apogee_std_m=round(float(np.std(apogees)), 2),
        max_q_mean_pa=round(float(np.mean(max_qs)), 2),
        max_q_std_pa=round(float(np.std(max_qs)), 2),
    )
