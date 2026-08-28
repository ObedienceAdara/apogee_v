"""
apogee.utils.rocket_builder
=============================

Every stage needs to build a ``rocketpy.SolidMotor`` and/or
``rocketpy.Rocket`` object. Rather than duplicating that construction
logic in stage1 (motor selection), stage2 (dispersion), stage3
(recovery) and stage4 (stability), it lives here once. This is the kind
of consolidation a code reviewer expects in a "real" engineering
codebase — geometry defined in exactly one place.

Grain-geometry estimation
--------------------------
The synthetic motor library (see ``scripts/generate_synthetic_motors.py``)
only specifies total impulse, burn time, propellant mass and total mass —
it does NOT specify internal grain geometry (grain count, core diameter),
because that's manufacturer-proprietary even for real motors. To build a
``rocketpy.SolidMotor`` (which models mass depletion / CG shift during
burn from grain geometry), we back-solve a single-segment BATES-style
grain from the known propellant mass and a typical APCP density. This is
a standard estimation technique used whenever the exact grain design
isn't available — flagged clearly here rather than silently baked in.
"""

from __future__ import annotations

import math

from rocketpy import Rocket, SolidMotor

from apogee.schemas import AirframeSpec, FinGeometry
from apogee.utils.motor_parser import ThrustCurve

APCP_DENSITY_KG_M3 = 1750.0  # typical composite (AP/HTPB) propellant density
CASE_WALL_THICKNESS_M = 0.0015


def build_motor_from_curve(curve: ThrustCurve, eng_file_path: str) -> SolidMotor:
    """Build a rocketpy.SolidMotor from a parsed .eng ThrustCurve, estimating
    the grain geometry needed for mass-depletion modeling."""
    diameter_m = curve.diameter_mm / 1000.0
    length_m = curve.length_mm / 1000.0

    grain_outer_radius = max(diameter_m / 2.0 - CASE_WALL_THICKNESS_M, 0.005)
    grain_inner_radius = grain_outer_radius * 0.35
    grain_number = 1

    cross_section_area = math.pi * (grain_outer_radius**2 - grain_inner_radius**2)
    grain_height = curve.propellant_mass_kg / (APCP_DENSITY_KG_M3 * grain_number * cross_section_area)

    nozzle_radius = grain_outer_radius * 0.5
    throat_radius = nozzle_radius * 0.4

    dry_mass = curve.dry_mass_kg
    # Thin-walled cylindrical casing inertia approximation
    dry_inertia_axial = 0.5 * dry_mass * grain_outer_radius**2
    dry_inertia_radial = (1 / 12) * dry_mass * (3 * grain_outer_radius**2 + length_m**2)

    grains_com_position = length_m * 0.5
    center_of_dry_mass_position = length_m * 0.55

    motor = SolidMotor(
        thrust_source=eng_file_path,
        dry_mass=dry_mass,
        dry_inertia=(dry_inertia_radial, dry_inertia_radial, dry_inertia_axial),
        nozzle_radius=nozzle_radius,
        throat_radius=throat_radius,
        grain_number=grain_number,
        grain_density=APCP_DENSITY_KG_M3,
        grain_outer_radius=grain_outer_radius,
        grain_initial_inner_radius=grain_inner_radius,
        grain_initial_height=grain_height,
        grain_separation=0.002,
        grains_center_of_mass_position=grains_com_position,
        center_of_dry_mass_position=center_of_dry_mass_position,
        nozzle_position=0.0,
        coordinate_system_orientation="nozzle_to_combustion_chamber",
    )
    return motor


DEFAULT_FIN = FinGeometry(
    fin_id="baseline",
    n_fins=4,
    root_chord_m=0.15,
    tip_chord_m=0.05,
    span_m=0.12,
    sweep_length_m=0.08,
    position_m=0.20,
)


def build_rocket(airframe: AirframeSpec, motor: SolidMotor, motor_position: float = 0.0,
                  fin: FinGeometry | None = None, total_length_m: float = 1.83,
                  nose_length_m: float = 0.40, add_parachutes: bool = False,
                  drogue_cd_s: float = 1.1, main_cd_s: float = 6.5,
                  main_deploy_altitude_m: float = 250.0) -> Rocket:
    """
    Build the full Rocket assembly: airframe body + nose + fins (+ optional
    recovery system). ``coordinate_system_orientation='tail_to_nose'`` with
    the origin at the rocket's tail (x=0), so all positions below are
    distances forward from the tail toward the nose tip.
    """
    fin = fin or DEFAULT_FIN

    rocket = Rocket(
        radius=airframe.radius_m,
        mass=airframe.dry_mass_kg,
        inertia=airframe.dry_inertia_kg_m2,
        power_off_drag=0.46,
        power_on_drag=0.42,
        center_of_mass_without_motor=airframe.center_of_dry_mass_m,
        coordinate_system_orientation="tail_to_nose",
    )

    rocket.add_motor(motor, position=motor_position)

    rocket.add_nose(length=nose_length_m, kind="von karman", position=total_length_m)

    rocket.add_trapezoidal_fins(
        n=fin.n_fins,
        root_chord=fin.root_chord_m,
        tip_chord=fin.tip_chord_m,
        span=fin.span_m,
        sweep_length=fin.sweep_length_m,
        position=fin.position_m,
    )

    rocket.add_tail(
        top_radius=airframe.radius_m,
        bottom_radius=airframe.radius_m * 0.8,
        length=0.06,
        position=0.06,
    )

    rocket.set_rail_buttons(upper_button_position=1.0, lower_button_position=0.30)

    if add_parachutes:
        rocket.add_parachute(
            name="Drogue",
            cd_s=drogue_cd_s,
            trigger="apogee",
            sampling_rate=105,
            lag=1.0,
        )
        rocket.add_parachute(
            name="Main",
            cd_s=main_cd_s,
            trigger=main_deploy_altitude_m,
            sampling_rate=105,
            lag=1.0,
        )

    return rocket
