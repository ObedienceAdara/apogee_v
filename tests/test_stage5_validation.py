"""Tests for flight-log classification and physical-validation evidence."""

import csv

from apogee.schemas import FlightLogRecord
from apogee.stage5_validation import load_flight_log, run_stage5


def _write_log(path, source):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "source", "apogee_m", "max_velocity_m_s",
            "descent_rate_m_s", "flight_time_s",
        ])
        writer.writerow([source, 2200, 320, 5.5, 330])


def _simulated():
    return FlightLogRecord(
        source="nominal_simulation",
        apogee_m=2200,
        max_velocity_m_s=320,
        descent_rate_m_s=5.5,
        flight_time_s=330,
    )


def test_synthetic_source_marker_cannot_be_overridden_by_config(tmp_path):
    path = tmp_path / "flight.csv"
    _write_log(path, "synthetic_demo_flight_log")
    actual = load_flight_log(path, force_synthetic=False, configuration_verified=True)
    assert actual.is_synthetic is True


def test_operator_must_attest_configuration_match_for_physical_validation(tmp_path):
    path = tmp_path / "flight.csv"
    _write_log(path, "altimeter_export")
    actual = load_flight_log(path, force_synthetic=False, configuration_verified=False)
    result = run_stage5(_simulated(), actual)
    assert actual.is_synthetic is False
    assert result.is_physical_validation is False


def test_non_synthetic_configuration_matched_log_can_count_as_validation_evidence(tmp_path):
    path = tmp_path / "flight.csv"
    _write_log(path, "altimeter_export")
    actual = load_flight_log(path, force_synthetic=False, configuration_verified=True)
    result = run_stage5(_simulated(), actual)
    assert result.is_physical_validation is True
    assert result.within_acceptable_error is True
