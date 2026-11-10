"""Conservative, unit-testable gates for the Apogee engineering report.

Passing these gates means only that the configured analysis checks passed.
It is never a launch authorization; range approval and competent human review
remain external requirements.
"""


def evaluate_readiness_gates(
    *,
    launch_datetime_is_future: bool,
    environment_passed: bool,
    motor_within_impulse_limit: bool,
    motor_within_apogee_tolerance: bool,
    stability_passed: bool,
    baseline_success_rate_pct: float,
    confirmation_success_rate_pct: float,
    minimum_success_rate_pct: float,
    recovery_has_safe_candidate: bool,
    recovery_recommended_is_safe: bool,
    validation_is_physical: bool,
    validation_within_tolerance: bool | None,
) -> list[str]:
    """Return all blocking issues; an empty list means analysis gates passed."""
    issues: list[str] = []

    if not launch_datetime_is_future:
        issues.append(
            "Mission timing: configured launch time is not in the future; "
            "a past launch window cannot receive a readiness pass."
        )
    if not environment_passed:
        issues.append(
            "Stage 0: environmental gate failed (the configured ground-band wind limit)."
        )
    if not motor_within_impulse_limit:
        issues.append(
            "Stage 1: selected motor exceeds the configured total-impulse eligibility "
            "limit; motor eligibility failed."
        )
    if not motor_within_apogee_tolerance:
        issues.append(
            "Stage 1: selected motor is outside the configured apogee tolerance."
        )
    if not stability_passed:
        issues.append(
            "Stage 4: no evaluated fin configuration met the minimum static-margin threshold."
        )

    if baseline_success_rate_pct < minimum_success_rate_pct:
        issues.append(
            f"Stage 2 baseline: Monte Carlo successful-run rate {baseline_success_rate_pct:.2f}% "
            f"is below the required {minimum_success_rate_pct:.2f}%."
        )
    if confirmation_success_rate_pct < minimum_success_rate_pct:
        issues.append(
            f"Stage 2 confirmation: Monte Carlo successful-run rate {confirmation_success_rate_pct:.2f}% "
            f"is below the required {minimum_success_rate_pct:.2f}%."
        )

    if not recovery_has_safe_candidate:
        issues.append(
            "Stage 3: no evaluated recovery configuration satisfies the maximum "
            "impact-velocity constraint; the least-unsafe candidate is diagnostic only."
        )
    elif not recovery_recommended_is_safe:
        issues.append(
            "Stage 3: selected recovery configuration violates the maximum "
            "impact-velocity constraint."
        )

    if not validation_is_physical:
        issues.append(
            "Stage 5: no non-synthetic, configuration-matched physical flight-data validation is available; "
            "synthetic demonstration data cannot satisfy this evidence gate."
        )
    elif validation_within_tolerance is not True:
        issues.append(
            "Stage 5: physical flight-data comparison is outside the configured "
            "acceptance tolerance or could not be evaluated."
        )

    return issues
