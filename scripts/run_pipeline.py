#!/usr/bin/env python3
"""
run_pipeline.py
=================

Command-line entry point for the Apogee Flight Readiness pipeline.

Usage
-----
    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --config config/mission_config.yaml
    python scripts/run_pipeline.py --quick          # fast smoke test (20 MC runs/stage)
    python scripts/run_pipeline.py --workers 8       # override Monte Carlo parallelism
    python scripts/run_pipeline.py --json-out outputs/report.json

Outputs (written to outputs/ by default):
    outputs/flight_readiness_report.md   — the human-readable FRR
    outputs/flight_readiness_report.json — the full machine-readable result
    outputs/dispersion_ellipse.png
    outputs/stability_margin.png
    outputs/recovery_pareto.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apogee.pipeline import run_pipeline
from apogee.report import generate_plots, render_markdown


def main():
    parser = argparse.ArgumentParser(description="Run the Apogee mission certification pipeline")
    parser.add_argument("--config", default="config/mission_config.yaml",
                         help="Path to mission_config.yaml")
    parser.add_argument("--quick", action="store_true",
                         help="Fast smoke-test mode: 20 Monte Carlo runs per stage instead of the configured n_dispersion_runs")
    parser.add_argument("--workers", type=int, default=None,
                         help="Max worker processes for Monte Carlo dispersion (default: os.cpu_count())")
    parser.add_argument("--out-dir", default="outputs", help="Directory to write the report + plots into")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report, all_stability_results = run_pipeline(args.config, quick=args.quick, max_workers=args.workers)

    plot_paths = generate_plots(report, out_dir)
    md_path = render_markdown(report, all_stability_results, plot_paths, out_dir / "flight_readiness_report.md")

    json_path = out_dir / "flight_readiness_report.json"
    json_path.write_text(report.model_dump_json(indent=2))

    print()
    print("=" * 70)
    print(f"STATUS: {'GO FOR LAUNCH' if report.overall_go_for_launch else 'NO-GO'}")
    print(f"Report:  {md_path}")
    print(f"Data:    {json_path}")
    print(f"Plots:   {out_dir}/*.png")
    print("=" * 70)


if __name__ == "__main__":
    main()
