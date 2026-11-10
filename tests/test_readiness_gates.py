"""Unit tests for conservative Flight Readiness engineering gates."""

from apogee.readiness import evaluate_readiness_gates


def _evaluate(**overrides):
    values = dict(
        launch_datetime_is_future=True,
        environment_passed=True,
        motor_within_impulse_limit=True,
        motor_within_apogee_tolerance=True,
        stability_passed=True,
        baseline_convergence_pct=100.0,
        confirmation_convergence_pct=100.0,
        minimum_convergence_pct=95.0,
        recovery_has_safe_candidate=True,
        recovery_recommended_is_safe=True,
        validation_is_physical=True,
        validation_within_tolerance=True,
    )
    values.update(overrides)
    return evaluate_readiness_gates(**values)


def test_all_configured_engineering_gates_can_pass():
    assert _evaluate() == []


def test_past_launch_time_blocks_readiness():
    issues = _evaluate(launch_datetime_is_future=False)
    assert any("not in the future" in issue for issue in issues)


def test_motor_over_impulse_limit_blocks_readiness():
    issues = _evaluate(motor_within_impulse_limit=False)
    assert any("impulse eligibility limit" in issue for issue in issues)


def test_recovery_without_safe_candidate_blocks_readiness():
    issues = _evaluate(
        recovery_has_safe_candidate=False,
        recovery_recommended_is_safe=False,
    )
    assert any("no evaluated recovery configuration" in issue for issue in issues)


def test_recommended_recovery_must_meet_impact_limit():
    issues = _evaluate(recovery_recommended_is_safe=False)
    assert any("violates the maximum impact-velocity constraint" in issue for issue in issues)


def test_baseline_and_confirmation_convergence_are_independent_gates():
    issues = _evaluate(
        baseline_convergence_pct=90.0,
        confirmation_convergence_pct=92.0,
    )
    assert any("baseline" in issue and "90.00%" in issue for issue in issues)
    assert any("confirmation" in issue and "92.00%" in issue for issue in issues)


def test_synthetic_or_missing_physical_validation_blocks_readiness():
    issues = _evaluate(validation_is_physical=False, validation_within_tolerance=None)
    assert any("non-synthetic physical flight-data validation" in issue for issue in issues)


def test_out_of_tolerance_physical_validation_blocks_readiness():
    issues = _evaluate(validation_is_physical=True, validation_within_tolerance=False)
    assert any("outside the configured acceptance tolerance" in issue for issue in issues)
