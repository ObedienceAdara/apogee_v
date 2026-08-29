"""
apogee.stage0_environment
==========================

Stage 0 of the pipeline: before any flight physics runs, validate the
*conditions*. Two independent checks feed into a single Go/No-Go
scorecard:

  1. Astropy solar geometry — is the sun low enough (civil twilight or
     darker) that optical/video tracking cameras won't be blinded, and
     what's the sun elevation for range-safety visual acquisition?
  2. Site wind profile vs safety limits at each altitude band.

The output is an ``EnvironmentReport`` (the Stage 0→1 data contract) plus
a live ``rocketpy.Environment`` object that every later stage reuses as
the shared atmospheric model — this is the single source of truth for
"what conditions is this rocket flying in," so a Monte Carlo dispersion
run and a motor-selection run never silently use two different winds.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, get_sun
from astropy.time import Time
from rocketpy import Environment

from apogee.schemas import EnvironmentReport, GoNoGoScorecard, LaunchSite, WindLevel

# Civil twilight threshold: sun below -6 deg elevation is generally
# considered safe for camera-based tracking / range visual acquisition.
CIVIL_TWILIGHT_DEG = -6.0
MAX_SAFE_SURFACE_WIND_M_S = 9.0  # ~20 mph, a common high-power rocketry ground-wind limit


def compute_sun_elevation(site: LaunchSite, launch_dt_utc: datetime) -> float:
    """
    Astropy solar geometry: sun elevation (degrees above horizon) at the
    launch site and time, in the topocentric AltAz frame.
    """
    location = EarthLocation(
        lat=site.latitude * u.deg,
        lon=site.longitude * u.deg,
        height=site.elevation_m * u.m,
    )
    obs_time = Time(launch_dt_utc)
    frame = AltAz(obstime=obs_time, location=location)
    sun_altaz = get_sun(obs_time).transform_to(frame)
    return float(sun_altaz.alt.deg)


def build_wind_profile(surface_wind_m_s: float, surface_heading_deg: float,
                        max_altitude_m: float = 4000.0, n_levels: int = 9) -> list[WindLevel]:
    """
    Builds a simple altitude-varying wind profile using a log-wind-shear
    approximation (wind speed increases with altitude, direction backs
    slightly) — standard boundary-layer behavior, used here because we
    have no live sounding/forecast feed available (sandboxed, offline).

    Swap this for a real Wyoming sounding or GFS forecast file in
    production by feeding rocketpy.Environment.set_atmospheric_model
    directly (see README "Using real weather data").
    """
    levels = []
    for i in range(n_levels):
        h = max_altitude_m * i / (n_levels - 1)
        shear_factor = (max(h, 10.0) / 10.0) ** 0.14  # power-law wind shear, common ABL model
        speed = surface_wind_m_s * shear_factor
        heading = (surface_heading_deg + 5.0 * (h / max_altitude_m)) % 360.0
        levels.append(WindLevel(altitude_agl_m=round(h, 1),
                                 wind_speed_m_s=round(speed, 2),
                                 wind_heading_deg=round(heading, 1)))
    return levels


def build_environment(site: LaunchSite, launch_dt_utc: datetime,
                       wind_profile: list[WindLevel],
                       max_expected_height: float = 6000.0) -> Environment:
    """Build the shared rocketpy.Environment every downstream stage will reuse."""
    env = Environment(
        latitude=site.latitude,
        longitude=site.longitude,
        elevation=site.elevation_m,
        timezone=site.timezone if site.timezone != "UTC" else "UTC",
        max_expected_height=max_expected_height,
    )
    env.set_date(
        (launch_dt_utc.year, launch_dt_utc.month, launch_dt_utc.day,
         launch_dt_utc.hour), timezone="UTC"
    )

    heights = np.array([w.altitude_agl_m for w in wind_profile]) + site.elevation_m
    wind_u = np.array([
        w.wind_speed_m_s * np.sin(np.radians(w.wind_heading_deg)) for w in wind_profile
    ])
    wind_v = np.array([
        w.wind_speed_m_s * np.cos(np.radians(w.wind_heading_deg)) for w in wind_profile
    ])

    wind_u_points = list(zip(heights.tolist(), wind_u.tolist()))
    wind_v_points = list(zip(heights.tolist(), wind_v.tolist()))

    env.set_atmospheric_model(
        type="custom_atmosphere",
        wind_u=wind_u_points,
        wind_v=wind_v_points,
    )
    return env


def run_stage0(site: LaunchSite, launch_dt_utc: datetime,
               surface_wind_m_s: float, surface_wind_heading_deg: float) -> tuple[EnvironmentReport, Environment]:
    """Run the full Stage 0 environment + go/no-go check."""
    if launch_dt_utc.tzinfo is None:
        launch_dt_utc = launch_dt_utc.replace(tzinfo=timezone.utc)

    sun_elev = compute_sun_elevation(site, launch_dt_utc)
    wind_profile = build_wind_profile(surface_wind_m_s, surface_wind_heading_deg)
    max_wind = max(w.wind_speed_m_s for w in wind_profile[:3])  # check lower levels (ground ops band)

    notes = []
    is_dark_enough = sun_elev <= CIVIL_TWILIGHT_DEG
    if not is_dark_enough and sun_elev > 45:
        notes.append(
            f"Sun elevation {sun_elev:.1f} deg — high sun angle, optical tracking cameras "
            "may need sun shades; not a blocking issue by itself."
        )
    wind_ok = max_wind <= MAX_SAFE_SURFACE_WIND_M_S
    if not wind_ok:
        notes.append(
            f"Ground-band wind {max_wind:.1f} m/s exceeds the {MAX_SAFE_SURFACE_WIND_M_S:.1f} m/s "
            "safety limit — recommend scrubbing or delaying launch window."
        )
    overall_go = wind_ok  # sun angle is advisory only; wind is the hard gate here

    scorecard = GoNoGoScorecard(
        sun_elevation_deg=round(sun_elev, 2),
        is_civil_twilight_or_darker=is_dark_enough,
        max_wind_speed_m_s=round(max_wind, 2),
        wind_within_limits=wind_ok,
        overall_go=overall_go,
        notes=notes,
    )

    report = EnvironmentReport(
        site=site,
        launch_datetime_utc=launch_dt_utc,
        wind_profile=wind_profile,
        scorecard=scorecard,
    )

    env = build_environment(site, launch_dt_utc, wind_profile)
    return report, env
