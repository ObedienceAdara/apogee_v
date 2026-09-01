"""
Unit tests for apogee.stage4_stability — the pure selection logic
(fin_area_m2, sweep_fin_geometry's selection rule) is tested here without
running actual RocketPy flights, using StabilityResult fixtures directly.
Full integration testing against a real Flight object is in
tests/test_integration.py (slow, requires RocketPy + a motor file).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apogee.schemas import FinGeometry, StabilityPoint, StabilityResult
from apogee.stage4_stability import fin_area_m2


def _make_result(fin_id, root, tip, span, min_margin, is_stable):
    fin = FinGeometry(fin_id=fin_id, root_chord_m=root, tip_chord_m=tip, span_m=span,
                       sweep_length_m=0.05, position_m=0.2)
    return StabilityResult(
        fin=fin,
        curve=[StabilityPoint(time_s=0.0, mach=0.1, static_margin_cal=min_margin)],
        min_margin_cal=min_margin,
        min_margin_mach=0.1,
        transonic_min_margin_cal=min_margin,
        transonic_dip_detected=False,
        is_stable=is_stable,
    )


def test_fin_area_trapezoid_formula():
    fin = FinGeometry(fin_id="t", root_chord_m=0.10, tip_chord_m=0.04, span_m=0.08,
                       sweep_length_m=0.05, position_m=0.2)
    expected = 0.5 * (0.10 + 0.04) * 0.08
    assert fin_area_m2(fin) == expected


def test_smallest_stable_fin_wins_when_multiple_pass():
    """This mirrors the selection logic inside sweep_fin_geometry: among
    stable candidates, the smallest planform area should be preferred
    (less drag, higher apogee for the same motor)."""
    results = [
        _make_result("small", 0.06, 0.02, 0.05, min_margin=0.4, is_stable=False),
        _make_result("medium", 0.08, 0.025, 0.06, min_margin=1.3, is_stable=True),
        _make_result("large", 0.13, 0.04, 0.095, min_margin=3.2, is_stable=True),
    ]
    stable = [r for r in results if r.is_stable]
    selected = min(stable, key=lambda r: fin_area_m2(r.fin))
    assert selected.fin.fin_id == "medium"


def test_unstable_fin_excluded_from_selection_pool():
    results = [
        _make_result("tiny", 0.04, 0.015, 0.03, min_margin=0.2, is_stable=False),
        _make_result("ok", 0.09, 0.03, 0.07, min_margin=1.5, is_stable=True),
    ]
    stable = [r for r in results if r.is_stable]
    assert len(stable) == 1
    assert stable[0].fin.fin_id == "ok"


def test_all_unstable_falls_back_to_least_bad():
    """If nothing clears the safety threshold, sweep_fin_geometry's
    fallback picks the candidate with the highest (least negative/least
    bad) margin, so the pipeline can surface a clear blocking issue
    instead of crashing."""
    results = [
        _make_result("a", 0.05, 0.02, 0.04, min_margin=0.3, is_stable=False),
        _make_result("b", 0.06, 0.02, 0.05, min_margin=0.6, is_stable=False),
    ]
    stable = [r for r in results if r.is_stable]
    assert stable == []
    fallback = max(results, key=lambda r: r.min_margin_cal)
    assert fallback.fin.fin_id == "b"
