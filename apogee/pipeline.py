"""
apogee.pipeline
=================

Orchestrates the full mission: Stage 0 -> Stage 1 -> Stage 4 -> Stage 2 ->
Stage 3 -> Stage 2 (confirmation re-run) -> Stage 5 -> Flight Readiness
Report.

This is not five independent scripts glued together — it's a single
directed pipeline with two real feedback loops, which is the actual
point of the project:

  1. Stage 4 (stability) runs on the motor Stage 1 selected, using the
     REAL Mach history that motor produces — a different motor changes
     acceleration through the transonic band, which changes the
     stability answer. If every fin candidate fails, that's a blocking
     issue fed back to the top, not a crash.

  2. Stage 3 (recovery) proposes a deployment configuration; Stage 2 is
     then re-run with that exact configuration to CONFIRM the dispersion
     footprint actually shrank, rather than trusting the single-flight
     estimate Stage 3 used internally for speed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from apogee.schemas import (
    AirframeSpec, FinGeometry, FlightReadinessReport, LaunchSite, MissionConfig,
)
from apogee.stage0_environment import run_stage0
from apogee.stage1_motor_selector import run_stage1
from apogee.stage2_dispersion import run_stage2
from apogee.stage3_recovery import run_stage3
from apogee.stage4_stability import sweep_fin_geometry
from apogee.stage5_validation import load_flight_log, run_stage5
from apogee.utils.motor_parser import parse_eng_file
from apogee.utils.rocket_builder import build_motor_from_curve

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("apogee.pipeline")
# RocketPy logs an INFO line per simulated flight ("Simulation completed at
# time: ..."). With hundreds of Monte Carlo flights that drowns out the
# pipeline's own stage-level logging, so keep RocketPy's own logger at
# WARNING while our stage-level messages above stay visible.
logging.getLogger("rocketpy").setLevel(logging.WARNING)

# Fin candidates swept in Stage 4. See README "Tuning the fin sweep" for
# guidance on widening this grid for a real (non-demo) airframe.
FIN_CANDIDATES = [
    FinGeometry(fin_id="medium", n_fins=4, root_chord_m=0.08, tip_chord_m=0.025,
                span_m=0.060, sweep_length_m=0.045, position_m=0.20),
    FinGeometry(fin_id="baseline", n_fins=4, root_chord_m=0.10, tip_chord_m=0.030,
                span_m=0.075, sweep_length_m=0.055, position_m=0.20),
    FinGeometry(fin_id="large", n_fins=4, root_chord_m=0.13, tip_chord_m=0.040,
                span_m=0.095, sweep_length_m=0.070, position_m=0.20),
]


def load_mission_config(path: str | Path) -> MissionConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return MissionConfig(
        mission_name=raw["mission_name"],
        site=LaunchSite(**raw["site"]),
        launch_datetime_utc=raw["launch_datetime_utc"],
        target_apogee_m=raw["target_apogee_m"],
        apogee_tolerance_pct=raw.get("apogee_tolerance_pct", 5.0),
        airframe=AirframeSpec(**raw["airframe"]),
        motor_library_dir=raw["motor_library_dir"],
        n_dispersion_runs=raw.get("n_dispersion_runs", 200),
        max_safe_impact_velocity_m_s=raw.get("max_safe_impact_velocity_m_s", 7.0),
        stability_safety_threshold_cal=raw.get("stability_safety_threshold_cal", 1.0),
        flight_log_csv=raw.get("flight_log_csv"),
    ), raw.get("surface_wind_m_s", 4.5), raw.get("surface_wind_heading_deg", 270.0)


def run_pipeline(config_path: str | Path, quick: bool = False,
                  max_workers: int | None = None) -> tuple[FlightReadinessReport, list]:
    mission, surface_wind, surface_heading = load_mission_config(config_path)
    blocking_issues: list[str] = []

    # ---------------------------------------------------------------- #
    log.info("STAGE 0 — Environment & launch window (Astropy + RocketPy)")
    launch_dt = mission.launch_datetime_utc
    if launch_dt.tzinfo is None:
        launch_dt = launch_dt.replace(tzinfo=timezone.utc)
    env_report, env = run_stage0(mission.site, launch_dt, surface_wind, surface_heading)
    log.info("  sun_elevation=%.1fdeg  max_wind=%.1fm/s  GO=%s",
              env_report.scorecard.sun_elevation_deg, env_report.scorecard.max_wind_speed_m_s,
              env_report.scorecard.overall_go)
    if not env_report.scorecard.overall_go:
        blocking_issues.append("Stage 0: environment scorecard is NO-GO (wind exceeds safety limit).")

    # ---------------------------------------------------------------- #
    log.info("STAGE 1 — Motor selection optimizer")
    motor_selection = run_stage1(
        mission.airframe, env, mission.motor_library_dir,
        mission.target_apogee_m, mission.apogee_tolerance_pct,
    )
    sel = motor_selection.selected
    log.info("  selected=%s  apogee=%.1fm (target %.1fm, err %.2f%%)",
              sel.motor_id, sel.predicted_apogee_m, mission.target_apogee_m, sel.apogee_error_pct)
    if abs(sel.apogee_error_pct) > mission.apogee_tolerance_pct:
        blocking_issues.append(
            f"Stage 1: no motor in the library hits {mission.target_apogee_m:.0f}m within "
            f"{mission.apogee_tolerance_pct:.1f}% — closest is {sel.motor_id} at {sel.apogee_error_pct:+.2f}%."
        )

    # ---------------------------------------------------------------- #
    log.info("STAGE 4 — Stability margin sweep vs Mach (fin geometry)")
    curve = parse_eng_file(sel.thrust_curve_file)
    selected_stability, all_stability = sweep_fin_geometry(
        mission.airframe, build_motor_from_curve(curve, sel.thrust_curve_file), env,
        mission.airframe.rail_length_m, FIN_CANDIDATES, mission.stability_safety_threshold_cal,
    )
    log.info("  selected fin=%s  min_margin=%.2fcal @ M%.2f  stable=%s",
              selected_stability.fin.fin_id, selected_stability.min_margin_cal,
              selected_stability.min_margin_mach, selected_stability.is_stable)
    if not selected_stability.is_stable:
        blocking_issues.append(
            f"Stage 4: no fin candidate keeps static margin above "
            f"{mission.stability_safety_threshold_cal:.1f} cal through the whole flight."
        )

    fin = selected_stability.fin
    n_dispersion = 20 if quick else mission.n_dispersion_runs

    # ---------------------------------------------------------------- #
    log.info("STAGE 2 — Six-DOF Monte Carlo dispersion (baseline recovery config), n=%d", n_dispersion)
    base_wind_tuples = [(w.altitude_agl_m, w.wind_speed_m_s, w.wind_heading_deg) for w in env_report.wind_profile]
    fin_params = (fin.n_fins, fin.root_chord_m, fin.tip_chord_m, fin.span_m, fin.sweep_length_m, fin.position_m)

    baseline_dispersion = run_stage2(
        mission.site, launch_dt.isoformat(), base_wind_tuples, mission.airframe,
        sel.thrust_curve_file, fin_params, mission.airframe.rail_length_m,
        n_runs=n_dispersion, drogue_cd_s=1.1, main_cd_s=6.5, main_deploy_altitude_m=250.0,
        max_workers=max_workers,
    )
    baseline_footprint = baseline_dispersion.landing_ellipse_95.semi_major_m
    log.info("  baseline 95%% ellipse semi-major=%.1fm  apogee=%.1f+/-%.1fm",
              baseline_footprint, baseline_dispersion.apogee_mean_m, baseline_dispersion.apogee_std_m)

    # ---------------------------------------------------------------- #
    log.info("STAGE 3 — Recovery system timing optimizer (Pareto trade study)")
    motor_for_recovery = build_motor_from_curve(curve, sel.thrust_curve_file)
    recovery = run_stage3(
        mission.airframe, motor_for_recovery, env, fin, mission.airframe.rail_length_m,
        mission.max_safe_impact_velocity_m_s,
        baseline_main_deploy_altitude_m=250.0, baseline_main_cd_s=6.5,
    )
    log.info("  recommended: main_deploy=%.0fm  cd_s=%.1f  drift=%.1fm  impact_v=%.2fm/s  footprint_reduction=%.1f%%",
              recovery.recommended.main_deploy_altitude_m, recovery.recommended.main_cd_s,
              recovery.recommended.predicted_drift_m, recovery.recommended.predicted_impact_velocity_m_s,
              recovery.footprint_reduction_pct)

    # ---------------------------------------------------------------- #
    log.info("STAGE 2 (confirmation) — re-running Monte Carlo with optimized recovery config")
    confirmed_dispersion = run_stage2(
        mission.site, launch_dt.isoformat(), base_wind_tuples, mission.airframe,
        sel.thrust_curve_file, fin_params, mission.airframe.rail_length_m,
        n_runs=n_dispersion, drogue_cd_s=recovery.recommended.drogue_cd_s,
        main_cd_s=recovery.recommended.main_cd_s,
        main_deploy_altitude_m=recovery.recommended.main_deploy_altitude_m,
        max_workers=max_workers,
    )
    confirmed_footprint = confirmed_dispersion.landing_ellipse_95.semi_major_m
    actual_reduction = 100.0 * (baseline_footprint - confirmed_footprint) / baseline_footprint if baseline_footprint else 0.0
    log.info("  confirmed 95%% ellipse semi-major=%.1fm  (%.1f%% change vs baseline)",
              confirmed_footprint, actual_reduction)

    # ---------------------------------------------------------------- #
    validation = None
    if mission.flight_log_csv and Path(mission.flight_log_csv).exists():
        log.info("STAGE 5 — Real flight validation")
        actual = load_flight_log(mission.flight_log_csv)
        nominal_run = confirmed_dispersion.runs[0]
        from apogee.schemas import FlightLogRecord
        SPEED_OF_SOUND_LOW_ALT_M_S = 340.0  # max-Mach point occurs early/low-altitude for this airframe
        simulated = FlightLogRecord(
            source="rocketpy_nominal",
            apogee_m=confirmed_dispersion.apogee_mean_m,
            max_velocity_m_s=round(nominal_run.max_mach * SPEED_OF_SOUND_LOW_ALT_M_S, 2),
            descent_rate_m_s=recovery.recommended.predicted_impact_velocity_m_s,
            flight_time_s=nominal_run.flight_time_s,
        )
        validation = run_stage5(simulated, actual)
        log.info("  apogee_error=%.2f%%  velocity_error=%.2f%%  descent_error=%.2f%%  within_tolerance=%s",
                  validation.apogee_error_pct, validation.velocity_error_pct,
                  validation.descent_rate_error_pct, validation.within_acceptable_error)
    else:
        log.info("STAGE 5 — skipped (no flight_log_csv configured/found)")

    # ---------------------------------------------------------------- #
    overall_go = env_report.scorecard.overall_go and selected_stability.is_stable and not blocking_issues

    report = FlightReadinessReport(
        mission=mission,
        environment=env_report,
        motor_selection=motor_selection,
        stability=selected_stability,
        dispersion=confirmed_dispersion,
        recovery=recovery,
        validation=validation,
        generated_at_utc=datetime.now(timezone.utc),
        overall_go_for_launch=overall_go,
        blocking_issues=blocking_issues,
    )
    return report, all_stability
