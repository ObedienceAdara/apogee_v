"""
apogee.schemas
==============

Every stage of the Apogee pipeline talks to the next stage through a typed
Pydantic model, never through loose dicts. This is the "data contract"
layer: Stage 1's output schema IS Stage 2's input schema, enforced at
runtime. If a stage tries to hand off malformed data, this fails loudly
at the boundary instead of silently corrupting a Monte Carlo run three
stages downstream.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Stage 0 — Environment & Launch Window
# --------------------------------------------------------------------------- #

class LaunchSite(BaseModel):
    name: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    elevation_m: float = Field(..., description="Site elevation above sea level, meters")
    timezone: str = Field(default="UTC", description="IANA timezone string")


class WindLevel(BaseModel):
    """One row of a site wind-by-altitude profile."""
    altitude_agl_m: float
    wind_speed_m_s: float
    wind_heading_deg: float = Field(..., ge=0, le=360)


class GoNoGoScorecard(BaseModel):
    sun_elevation_deg: float
    is_civil_twilight_or_darker: bool
    max_wind_speed_m_s: float
    wind_within_limits: bool
    overall_go: bool
    notes: list[str] = Field(default_factory=list)


class EnvironmentReport(BaseModel):
    site: LaunchSite
    launch_datetime_utc: datetime
    wind_profile: list[WindLevel]
    scorecard: GoNoGoScorecard
    # Serialized identity of the rocketpy.Environment built from this data;
    # the actual object is reconstructed by stage1+ from this report, not
    # pickled across stages, to keep the contract inspectable/loggable.
    atmospheric_model: str = "custom_atmosphere"


# --------------------------------------------------------------------------- #
# Stage 1 — Motor Selection
# --------------------------------------------------------------------------- #

class ImpulseClass(str, Enum):
    H = "H"
    I = "I"
    J = "J"
    K = "K"
    L = "L"


class AirframeSpec(BaseModel):
    """Fixed airframe geometry the motor optimizer must fit into."""
    radius_m: float
    dry_mass_kg: float
    dry_inertia_kg_m2: tuple[float, float, float]
    center_of_dry_mass_m: float
    power_off_drag_curve: str = "default"
    power_on_drag_curve: str = "default"
    rail_length_m: float = 5.2
    certification_level_max_impulse_n_s: float = Field(
        default=5120.0, description="Max total impulse the flier is certified for"
    )


class MotorCandidate(BaseModel):
    motor_id: str
    manufacturer: str
    impulse_class: ImpulseClass
    thrust_curve_file: str
    total_impulse_n_s: float
    burn_time_s: float
    propellant_mass_kg: float
    dry_mass_kg: float
    cost_usd: Optional[float] = None
    predicted_apogee_m: Optional[float] = None
    predicted_max_q_pa: Optional[float] = None
    predicted_max_mach: Optional[float] = None
    apogee_error_pct: Optional[float] = None
    passes_certification: Optional[bool] = None
    rank_score: Optional[float] = None


class MotorSelectionResult(BaseModel):
    target_apogee_m: float
    apogee_tolerance_pct: float
    shortlist: list[MotorCandidate]
    selected: MotorCandidate


# --------------------------------------------------------------------------- #
# Stage 4 — Stability
# --------------------------------------------------------------------------- #

class FinGeometry(BaseModel):
    fin_id: str
    n_fins: int = 4
    root_chord_m: float
    tip_chord_m: float
    span_m: float
    sweep_length_m: float
    position_m: float


class StabilityPoint(BaseModel):
    time_s: float
    mach: float
    static_margin_cal: float


class StabilityResult(BaseModel):
    fin: FinGeometry
    curve: list[StabilityPoint]
    min_margin_cal: float
    min_margin_mach: float
    transonic_min_margin_cal: float
    transonic_dip_detected: bool
    is_stable: bool
    safety_threshold_cal: float = 1.0
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Stage 2 — Six-DOF Monte Carlo Dispersion
# --------------------------------------------------------------------------- #

class DispersionRunResult(BaseModel):
    run_id: int
    apogee_m: float
    max_q_pa: float
    max_mach: float
    max_velocity_m_s: float = 0.0
    landing_x_m: float
    landing_y_m: float
    time_to_apogee_s: float
    flight_time_s: float
    converged: bool
    failure_reason: Optional[str] = None


class DispersionEllipse(BaseModel):
    center_x_m: float
    center_y_m: float
    semi_major_m: float
    semi_minor_m: float
    rotation_deg: float
    confidence: float = 0.95


class DispersionAnalysisResult(BaseModel):
    n_runs: int
    n_converged: int
    convergence_rate_pct: float
    failure_reasons: list[str] = Field(default_factory=list)
    runs: list[DispersionRunResult]
    landing_ellipse_95: DispersionEllipse
    apogee_mean_m: float
    apogee_std_m: float
    max_q_mean_pa: float
    max_q_std_pa: float
    max_velocity_mean_m_s: float
    max_velocity_std_m_s: float


# --------------------------------------------------------------------------- #
# Stage 3 — Recovery Optimization
# --------------------------------------------------------------------------- #

class RecoveryCandidate(BaseModel):
    drogue_cd_s: float
    main_cd_s: float
    main_deploy_altitude_m: float
    predicted_drift_m: float
    predicted_impact_velocity_m_s: float
    is_pareto_optimal: bool = False


class RecoveryOptimizationResult(BaseModel):
    max_safe_impact_velocity_m_s: float
    has_safe_candidate: bool
    recommended_is_safe: bool
    candidates: list[RecoveryCandidate]
    pareto_front: list[RecoveryCandidate]
    recommended: RecoveryCandidate
    footprint_reduction_pct: float


# --------------------------------------------------------------------------- #
# Stage 5 — Real Flight Validation
# --------------------------------------------------------------------------- #

class FlightLogRecord(BaseModel):
    source: str = Field(..., description="e.g. 'synthetic_demo' or a real logger filename")
    is_synthetic: bool = False
    apogee_m: float = Field(..., gt=0)
    max_velocity_m_s: float = Field(..., gt=0)
    descent_rate_m_s: float = Field(..., gt=0)
    flight_time_s: float = Field(..., gt=0)


class ValidationResult(BaseModel):
    simulated: FlightLogRecord
    actual: FlightLogRecord
    is_physical_validation: bool
    apogee_error_pct: float
    velocity_error_pct: float
    descent_rate_error_pct: float
    within_acceptable_error: bool
    acceptable_error_pct: float = 8.0
    likely_causes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Top-level mission config (loaded from YAML) and final report bundle
# --------------------------------------------------------------------------- #

class MissionConfig(BaseModel):
    mission_name: str
    site: LaunchSite
    launch_datetime_utc: datetime
    target_apogee_m: float
    apogee_tolerance_pct: float = 5.0
    airframe: AirframeSpec
    motor_library_dir: str
    n_dispersion_runs: int = 200
    minimum_monte_carlo_convergence_pct: float = Field(default=95.0, gt=0, le=100)
    max_safe_impact_velocity_m_s: float = 7.0
    stability_safety_threshold_cal: float = 1.0
    flight_log_csv: Optional[str] = None
    flight_log_is_synthetic: bool = False

    @field_validator("apogee_tolerance_pct")
    @classmethod
    def _tol_positive(cls, v):
        if v <= 0:
            raise ValueError("apogee_tolerance_pct must be positive")
        return v


class FlightReadinessReport(BaseModel):
    mission: MissionConfig
    environment: EnvironmentReport
    motor_selection: MotorSelectionResult
    stability: StabilityResult
    dispersion: DispersionAnalysisResult
    recovery: RecoveryOptimizationResult
    validation: Optional[ValidationResult] = None
    generated_at_utc: datetime
    engineering_gates_passed: bool
    # This software cannot grant range approval, certify hardware, or authorize a launch.
    launch_authorization_status: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    blocking_issues: list[str] = Field(default_factory=list)
