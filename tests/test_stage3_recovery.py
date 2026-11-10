"""Unit tests for the Pareto-front logic in apogee.stage3_recovery."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apogee.schemas import RecoveryCandidate
from apogee.stage3_recovery import _compute_pareto_front, _select_recommendation


def _c(drift, impact_v):
    return RecoveryCandidate(
        drogue_cd_s=1.1, main_cd_s=6.0, main_deploy_altitude_m=250.0,
        predicted_drift_m=drift, predicted_impact_velocity_m_s=impact_v,
    )


def test_dominated_candidate_excluded():
    # b is strictly worse than a on both axes -> dominated, excluded
    a = _c(drift=500, impact_v=5.0)
    b = _c(drift=600, impact_v=6.0)
    front = _compute_pareto_front([a, b])
    assert a in front
    assert b not in front


def test_non_dominated_tradeoff_both_kept():
    # a has less drift but higher impact velocity than b -> neither dominates
    a = _c(drift=500, impact_v=6.5)
    b = _c(drift=800, impact_v=5.0)
    front = _compute_pareto_front([a, b])
    assert a in front and b in front


def test_identical_points_both_kept():
    a = _c(drift=500, impact_v=5.0)
    b = _c(drift=500, impact_v=5.0)
    front = _compute_pareto_front([a, b])
    assert len(front) == 2


def test_front_sorted_by_drift_ascending():
    a = _c(drift=900, impact_v=4.0)
    b = _c(drift=500, impact_v=6.9)
    c = _c(drift=700, impact_v=5.0)
    front = _compute_pareto_front([a, b, c])
    drifts = [x.predicted_drift_m for x in front]
    assert drifts == sorted(drifts)


def test_pareto_flag_set_on_result_objects():
    a = _c(drift=500, impact_v=5.0)
    b = _c(drift=900, impact_v=6.0)  # dominated by a
    _compute_pareto_front([a, b])
    assert a.is_pareto_optimal is True
    assert b.is_pareto_optimal is False



def test_no_safe_recovery_candidate_selects_least_unsafe_for_diagnostics():
    candidates = [
        _c(drift=300, impact_v=9.0),
        _c(drift=900, impact_v=7.8),
        _c(drift=500, impact_v=8.1),
    ]
    selected, has_safe = _select_recommendation(candidates, max_safe_impact_velocity_m_s=7.0)
    assert has_safe is False
    assert selected.predicted_impact_velocity_m_s == 7.8
    assert selected.predicted_drift_m == 900


def test_safe_recovery_candidate_with_lowest_drift_is_selected():
    candidates = [
        _c(drift=300, impact_v=7.2),
        _c(drift=600, impact_v=6.8),
        _c(drift=800, impact_v=5.0),
    ]
    selected, has_safe = _select_recommendation(candidates, max_safe_impact_velocity_m_s=7.0)
    assert has_safe is True
    assert selected.predicted_drift_m == 600
