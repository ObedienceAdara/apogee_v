"""Unit tests for apogee.utils.motor_parser — run with: pytest tests/"""

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from apogee.utils.motor_parser import discover_motor_library, parse_eng_file


@pytest.fixture
def sample_eng_file(tmp_path):
    content = textwrap.dedent("""\
        ; test motor, not real
        TestJ350 54 254 0 0.2450 0.4800 Synth-Motors
        0.0000 0.00
        0.2000 250.00
        1.0000 400.00
        2.0000 300.00
        2.5000 0.00
        ;
    """)
    path = tmp_path / "TestJ350.eng"
    path.write_text(content)
    return path


def test_parse_eng_file_header_fields(sample_eng_file):
    curve = parse_eng_file(sample_eng_file)
    assert curve.name == "TestJ350"
    assert curve.diameter_mm == 54.0
    assert curve.length_mm == 254.0
    assert curve.propellant_mass_kg == 0.2450
    assert curve.total_mass_kg == 0.4800
    assert curve.manufacturer == "Synth-Motors"


def test_parse_eng_file_thrust_data(sample_eng_file):
    curve = parse_eng_file(sample_eng_file)
    assert curve.time_s == [0.0, 0.2, 1.0, 2.0, 2.5]
    assert curve.thrust_n == [0.0, 250.0, 400.0, 300.0, 0.0]


def test_dry_mass_computed_correctly(sample_eng_file):
    curve = parse_eng_file(sample_eng_file)
    assert curve.dry_mass_kg == pytest.approx(0.235, abs=1e-6)


def test_burn_time_is_last_timestamp(sample_eng_file):
    curve = parse_eng_file(sample_eng_file)
    assert curve.burn_time_s == 2.5


def test_total_impulse_trapezoidal_integration(sample_eng_file):
    curve = parse_eng_file(sample_eng_file)
    # trapezoidal integration by hand over the 5 points above
    expected = (
        0.5 * (0 + 250) * 0.2 +
        0.5 * (250 + 400) * 0.8 +
        0.5 * (400 + 300) * 1.0 +
        0.5 * (300 + 0) * 0.5
    )
    assert curve.total_impulse_n_s == pytest.approx(expected, rel=1e-6)


def test_impulse_class_classification():
    from apogee.utils.motor_parser import ThrustCurve
    # J-class: 640 < total_impulse <= 1280 Ns
    curve = ThrustCurve(
        name="X", diameter_mm=54, length_mm=254, delays="0",
        propellant_mass_kg=0.2, total_mass_kg=0.4, manufacturer="Test",
        time_s=[0, 1], thrust_n=[900, 900],  # impulse = 900 Ns -> class J
    )
    assert curve.impulse_class == "J"


def test_malformed_header_raises(tmp_path):
    path = tmp_path / "bad.eng"
    path.write_text("TooFewFields 54 254\n0.0 0.0\n")
    with pytest.raises(ValueError):
        parse_eng_file(path)


def test_empty_thrust_data_raises(tmp_path):
    path = tmp_path / "empty.eng"
    path.write_text("Empty 54 254 0 0.2 0.4 Test\n;\n")
    with pytest.raises(ValueError):
        parse_eng_file(path)


def test_discover_motor_library(tmp_path):
    for name, impulse_ish_thrust in [("A1", 100), ("B2", 200)]:
        content = f"{name} 29 100 0 0.05 0.10 Test\n0.0 0.0\n1.0 {impulse_ish_thrust}.0\n2.0 0.0\n;\n"
        (tmp_path / f"{name}.eng").write_text(content)
    (tmp_path / "notes.txt").write_text("not a motor file")  # should be ignored

    library = discover_motor_library(tmp_path)
    assert set(library.keys()) == {"A1", "B2"}
    assert all(hasattr(c, "total_impulse_n_s") for c in library.values())


def test_real_synthetic_motor_library_parses():
    """Integration check against the actual generated demo library, if present."""
    motor_dir = Path(__file__).resolve().parent.parent / "config" / "motors"
    if not motor_dir.exists() or not list(motor_dir.glob("*.eng")):
        pytest.skip("Run scripts/generate_synthetic_motors.py first")
    library = discover_motor_library(motor_dir)
    assert len(library) >= 4
    for motor_id, curve in library.items():
        assert curve.total_impulse_n_s > 0
        assert curve.burn_time_s > 0
        assert curve.dry_mass_kg > 0
