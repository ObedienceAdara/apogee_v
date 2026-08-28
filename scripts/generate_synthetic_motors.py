#!/usr/bin/env python3
"""
generate_synthetic_motors.py
=============================

RocketPy needs real thrust-curve files to simulate a motor, but real
manufacturer .eng files (Cesaroni, AeroTech) are proprietary/distributed
via thrustcurve.org and can't be vendored into this repo or fetched from
a sandboxed environment with no outbound internet.

This script generates a small library of *synthetic but physically
plausible* solid-motor thrust curves spanning the H-K impulse classes,
written in the real RASP .eng format, so the Stage 1 motor optimizer has
a genuine multi-motor library to search over out of the box.

Each curve follows a standard three-phase solid-propellant burn shape:
  1. Ignition spike (progressive)
  2. Sustained regressive burn (thrust tapers as burn surface area drops)
  3. Tail-off

>>> To use REAL motor data instead: download .eng files for your actual
>>> motors from https://www.thrustcurve.org and drop them into
>>> config/motors/ — the parser and optimizer don't care where the file
>>> came from, only that it's valid RASP format.
"""

from __future__ import annotations

import math
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "config" / "motors"

# (motor_id, diameter_mm, length_mm, total_impulse_target_Ns, burn_time_s,
#  peak_thrust_N, propellant_mass_kg, total_mass_kg, cost_usd)
MOTOR_SPECS = [
    ("H128-Synth",  29,  173,  188.0, 1.5,  188.0, 0.062, 0.128,  28.0),
    ("H242-Synth",  29,  173,  190.0, 0.8,  330.0, 0.070, 0.135,  30.0),
    ("I195-Synth",  38,  212,  435.0, 2.2,  260.0, 0.128, 0.255,  46.0),
    ("I350-Synth",  38,  212,  440.0, 1.3,  400.0, 0.135, 0.262,  49.0),
    ("J350-Synth",  54,  254,  865.0, 2.5,  420.0, 0.245, 0.480,  85.0),
    ("J450-Synth",  54,  254,  880.0, 2.0,  520.0, 0.252, 0.488,  89.0),
    ("K550-Synth",  54,  325, 1730.0, 3.2,  650.0, 0.462, 0.910, 155.0),
    ("K740-Synth",  54,  325, 1725.0, 2.4,  830.0, 0.470, 0.915, 160.0),
]


def thrust_shape(t: float, burn_time: float, peak_thrust: float) -> float:
    """Progressive spike -> regressive sustain -> tail-off, normalized burn shape."""
    x = t / burn_time
    if x <= 0.06:
        # Fast ignition ramp to a spike above sustain level
        return peak_thrust * (x / 0.06) * 1.15
    if x <= 0.10:
        # Settle from spike down to sustain thrust
        settle = (x - 0.06) / 0.04
        return peak_thrust * (1.15 - 0.35 * settle)
    if x <= 0.85:
        # Regressive sustain: gentle decay as core burns outward
        sustain_progress = (x - 0.10) / 0.75
        return peak_thrust * 0.80 * (1 - 0.28 * sustain_progress)
    # Tail-off: exponential decay to zero
    tail_progress = (x - 0.85) / 0.15
    return peak_thrust * 0.80 * 0.72 * math.exp(-4.5 * tail_progress)


def generate_curve(peak_thrust: float, burn_time: float, n_points: int = 45):
    pts = []
    for i in range(n_points + 1):
        t = burn_time * i / n_points
        thrust = max(0.0, thrust_shape(t, burn_time, peak_thrust))
        pts.append((round(t, 4), round(thrust, 2)))
    if pts[-1][1] != 0.0:
        pts.append((round(burn_time, 4), 0.0))
    return pts


def scale_to_target_impulse(points: list[tuple[float, float]], target_impulse: float) -> list[tuple[float, float]]:
    impulse = 0.0
    for i in range(1, len(points)):
        t0, f0 = points[i - 1]
        t1, f1 = points[i]
        impulse += 0.5 * (f0 + f1) * (t1 - t0)
    if impulse <= 0:
        return points
    scale = target_impulse / impulse
    return [(t, round(f * scale, 2)) for t, f in points]


def write_eng_file(motor_id, diameter_mm, length_mm, total_impulse, burn_time,
                    peak_thrust, prop_mass, total_mass, manufacturer="Synth-Motors"):
    raw = generate_curve(peak_thrust, burn_time)
    scaled = scale_to_target_impulse(raw, total_impulse)

    lines = [
        f"; {motor_id} synthetic thrust curve — generated for the Apogee",
        f"; demo pipeline. NOT a real certified motor. Total impulse ~{total_impulse:.0f} Ns.",
        f"{motor_id} {diameter_mm} {length_mm} 0 {prop_mass:.4f} {total_mass:.4f} {manufacturer}",
    ]
    for t, f in scaled:
        lines.append(f"{t:.4f} {f:.2f}")
    lines.append(";")

    out_path = OUT_DIR / f"{motor_id}.eng"
    out_path.write_text("\n".join(lines) + "\n")
    return out_path


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for spec in MOTOR_SPECS:
        motor_id, dia, length, impulse, burn_t, peak, prop_m, total_m, cost = spec
        path = write_eng_file(motor_id, dia, length, impulse, burn_t, peak, prop_m, total_m)
        written.append((motor_id, path, cost))
        print(f"  wrote {path.name:22s} total_impulse~{impulse:7.1f} Ns  burn={burn_t:.2f}s")

    # Small cost/metadata sidecar the motor selector reads alongside the .eng files
    meta_path = OUT_DIR / "motor_costs.csv"
    with open(meta_path, "w") as f:
        f.write("motor_id,cost_usd\n")
        for motor_id, _, cost in written:
            f.write(f"{motor_id},{cost}\n")
    print(f"  wrote {meta_path.name}")
    print(f"\n{len(written)} synthetic motors written to {OUT_DIR}")


if __name__ == "__main__":
    main()
