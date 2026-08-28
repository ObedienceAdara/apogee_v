"""
apogee.utils.motor_parser
==========================

Parses RASP-format ``.eng`` solid motor thrust curve files — the de facto
standard format used by every motor manufacturer (Cesaroni, AeroTech,
Estes) and by thrustcurve.org.

File format (RASP .eng), for reference:

    ; comment lines start with a semicolon
    <name> <diameter_mm> <length_mm> <delays> <prop_mass_kg> <total_mass_kg> <manufacturer>
    <time_s> <thrust_N>
    <time_s> <thrust_N>
    ...
    ;

This parser is intentionally standalone (no rocketpy import) so it can be
unit tested in isolation and reused anywhere a thrust curve needs to be
read — rocketpy itself only needs the file path at simulation time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ThrustCurve:
    name: str
    diameter_mm: float
    length_mm: float
    delays: str
    propellant_mass_kg: float
    total_mass_kg: float
    manufacturer: str
    time_s: list[float] = field(default_factory=list)
    thrust_n: list[float] = field(default_factory=list)

    @property
    def dry_mass_kg(self) -> float:
        return round(self.total_mass_kg - self.propellant_mass_kg, 6)

    @property
    def burn_time_s(self) -> float:
        return self.time_s[-1] if self.time_s else 0.0

    @property
    def total_impulse_n_s(self) -> float:
        """Trapezoidal integration of the thrust curve."""
        impulse = 0.0
        for i in range(1, len(self.time_s)):
            dt = self.time_s[i] - self.time_s[i - 1]
            impulse += 0.5 * (self.thrust_n[i] + self.thrust_n[i - 1]) * dt
        return impulse

    @property
    def impulse_class(self) -> str:
        """NAR/TRA letter classification — each class doubles the previous."""
        ns = self.total_impulse_n_s
        thresholds = [
            ("A", 2.5), ("B", 5), ("C", 10), ("D", 20), ("E", 40),
            ("F", 80), ("G", 160), ("H", 320), ("I", 640), ("J", 1280),
            ("K", 2560), ("L", 5120), ("M", 10240), ("N", 20480), ("O", 40960),
        ]
        for letter, upper in thresholds:
            if ns <= upper:
                return letter
        return "O+"


def parse_eng_file(path: str | Path) -> ThrustCurve:
    """Parse a single RASP .eng file into a ThrustCurve."""
    path = Path(path)
    header = None
    times: list[float] = []
    thrusts: list[float] = []

    with open(path, "r") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            if header is None:
                parts = line.split()
                if len(parts) < 7:
                    raise ValueError(
                        f"{path}: malformed .eng header line: {line!r}"
                    )
                header = parts
                continue
            parts = line.split()
            if len(parts) != 2:
                # Trailing terminator lines / stray data — skip rather than crash,
                # matching how real-world .eng files in the wild are formatted.
                continue
            t, thrust = float(parts[0]), float(parts[1])
            times.append(t)
            thrusts.append(thrust)

    if header is None or not times:
        raise ValueError(f"{path}: no valid thrust data found")

    name, diameter_mm, length_mm, delays, prop_mass, total_mass = header[:6]
    manufacturer = " ".join(header[6:]) if len(header) > 6 else "unknown"

    return ThrustCurve(
        name=name,
        diameter_mm=float(diameter_mm),
        length_mm=float(length_mm),
        delays=delays,
        propellant_mass_kg=float(prop_mass),
        total_mass_kg=float(total_mass),
        manufacturer=manufacturer,
        time_s=times,
        thrust_n=thrusts,
    )


def discover_motor_library(directory: str | Path) -> dict[str, ThrustCurve]:
    """Parse every .eng file in a directory into a {motor_id: ThrustCurve} map."""
    directory = Path(directory)
    library = {}
    for eng_file in sorted(directory.glob("*.eng")):
        curve = parse_eng_file(eng_file)
        library[curve.name] = curve
    return library
