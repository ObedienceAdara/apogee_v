"""
apogee.report
===============

Renders a ``FlightReadinessReport`` into the artifact a real range-safety
/ technical review actually wants: a single Markdown document (easy to
convert to PDF with pandoc, or paste into Notion/Confluence) with the
dispersion ellipse, stability curve, and recovery trade-off plotted
alongside the numbers — not just a wall of JSON.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from apogee.schemas import FlightReadinessReport


def _plot_dispersion(report: FlightReadinessReport, out_path: Path) -> None:
    d = report.dispersion
    xs = [r.landing_x_m for r in d.runs if r.converged]
    ys = [r.landing_y_m for r in d.runs if r.converged]

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(xs, ys, s=18, alpha=0.6, color="#2563eb", label=f"{d.n_converged} MC landings")
    ax.scatter([0], [0], marker="*", s=250, color="#dc2626", label="Launch point", zorder=5)

    ell = d.landing_ellipse_95
    theta = np.linspace(0, 2 * np.pi, 200)
    ex = ell.semi_major_m * np.cos(theta)
    ey = ell.semi_minor_m * np.sin(theta)
    rot = np.radians(ell.rotation_deg)
    rx = ex * np.cos(rot) - ey * np.sin(rot) + ell.center_x_m
    ry = ex * np.sin(rot) + ey * np.cos(rot) + ell.center_y_m
    ax.plot(rx, ry, color="#dc2626", lw=2, label="95% confidence ellipse")

    ax.set_xlabel("Downrange X (m)")
    ax.set_ylabel("Downrange Y (m)")
    ax.set_title(f"{report.mission.mission_name}\nLanding Dispersion (95% confidence)")
    ax.axis("equal")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _plot_stability(report: FlightReadinessReport, out_path: Path) -> None:
    s = report.stability
    machs = [p.mach for p in s.curve]
    margins = [p.static_margin_cal for p in s.curve]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(machs, margins, color="#2563eb", lw=2)
    ax.axhline(s.safety_threshold_cal, color="#dc2626", ls="--", lw=1.5,
               label=f"Safety threshold ({s.safety_threshold_cal:.1f} cal)")
    ax.axvspan(0.8, 1.2, color="#f59e0b", alpha=0.15, label="Transonic band (M0.8-1.2)")
    ax.set_xlabel("Mach number")
    ax.set_ylabel("Static margin (calibers)")
    ax.set_title(f"Static Margin vs Mach — fin '{s.fin.fin_id}'")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _plot_recovery_pareto(report: FlightReadinessReport, out_path: Path) -> None:
    r = report.recovery
    all_drift = [c.predicted_drift_m for c in r.candidates]
    all_v = [c.predicted_impact_velocity_m_s for c in r.candidates]
    pf_drift = [c.predicted_drift_m for c in r.pareto_front]
    pf_v = [c.predicted_impact_velocity_m_s for c in r.pareto_front]

    fig, ax = plt.subplots(figsize=(7, 5.5))
    ax.scatter(all_drift, all_v, s=30, alpha=0.4, color="#94a3b8", label="All candidates")
    order = np.argsort(pf_drift)
    pf_drift_sorted = np.array(pf_drift)[order]
    pf_v_sorted = np.array(pf_v)[order]
    ax.plot(pf_drift_sorted, pf_v_sorted, color="#dc2626", marker="o", lw=2, label="Pareto front")
    ax.scatter([r.recommended.predicted_drift_m], [r.recommended.predicted_impact_velocity_m_s],
               marker="*", s=300, color="#16a34a", zorder=5, label="Recommended")
    ax.axhline(r.max_safe_impact_velocity_m_s, color="#f59e0b", ls="--",
               label=f"Max safe impact velocity ({r.max_safe_impact_velocity_m_s:.1f} m/s)")
    ax.set_xlabel("Horizontal drift (m)")
    ax.set_ylabel("Impact velocity (m/s)")
    ax.set_title("Recovery Trade-off: Drift vs. Impact Velocity")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def generate_plots(report: FlightReadinessReport, out_dir: str | Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "dispersion": out_dir / "dispersion_ellipse.png",
        "stability": out_dir / "stability_margin.png",
        "recovery": out_dir / "recovery_pareto.png",
    }
    _plot_dispersion(report, paths["dispersion"])
    _plot_stability(report, paths["stability"])
    _plot_recovery_pareto(report, paths["recovery"])
    return paths


def _motor_table(report: FlightReadinessReport) -> str:
    lines = ["| Motor | Impulse (Ns) | Class | Apogee (m) | Error (%) | Max Mach | Cert OK | Cost ($) |",
             "|---|---|---|---|---|---|---|---|"]
    for c in report.motor_selection.shortlist:
        lines.append(
            f"| {c.motor_id} | {c.total_impulse_n_s:.0f} | {c.impulse_class.value} | "
            f"{c.predicted_apogee_m:.0f} | {c.apogee_error_pct:+.2f} | {c.predicted_max_mach:.2f} | "
            f"{'Yes' if c.passes_certification else 'No'} | {c.cost_usd if c.cost_usd else '-'} |"
        )
    return "\n".join(lines)


def _stability_table(report: FlightReadinessReport, all_results) -> str:
    lines = ["| Fin | Root (m) | Span (m) | Area (m2) | Min Margin (cal) | @ Mach | Stable |",
             "|---|---|---|---|---|---|---|"]
    for r in all_results:
        area = 0.5 * (r.fin.root_chord_m + r.fin.tip_chord_m) * r.fin.span_m
        lines.append(
            f"| {r.fin.fin_id} | {r.fin.root_chord_m:.3f} | {r.fin.span_m:.3f} | {area:.4f} | "
            f"{r.min_margin_cal:.2f} | {r.min_margin_mach:.2f} | {'Yes' if r.is_stable else 'NO'} |"
        )
    return "\n".join(lines)


def render_markdown(report: FlightReadinessReport, all_stability_results, plot_paths: dict[str, Path],
                     out_path: str | Path) -> Path:
    m = report.mission
    e = report.environment
    ms = report.motor_selection
    s = report.stability
    d = report.dispersion
    rc = report.recovery
    v = report.validation

    go_banner = "GO FOR LAUNCH" if report.overall_go_for_launch else "NO-GO — SEE BLOCKING ISSUES"

    lines = []
    lines.append(f"# Flight Readiness Report — {m.mission_name}")
    lines.append(f"\n**Generated:** {report.generated_at_utc.isoformat()}  ")
    lines.append(f"**Status:** **{go_banner}**\n")

    if report.blocking_issues:
        lines.append("## Blocking Issues\n")
        for issue in report.blocking_issues:
            lines.append(f"- ⚠️ {issue}")
        lines.append("")

    lines.append("## 1. Launch Window & Environment (Stage 0)\n")
    lines.append(f"- **Site:** {e.site.name} ({e.site.latitude:.4f}, {e.site.longitude:.4f}), "
                 f"{e.site.elevation_m:.0f} m elevation")
    lines.append(f"- **Launch time (UTC):** {e.launch_datetime_utc.isoformat()}")
    lines.append(f"- **Sun elevation:** {e.scorecard.sun_elevation_deg:.1f} deg "
                 f"({'civil twilight or darker' if e.scorecard.is_civil_twilight_or_darker else 'daylight'})")
    lines.append(f"- **Max ground-band wind:** {e.scorecard.max_wind_speed_m_s:.1f} m/s "
                 f"({'within limits' if e.scorecard.wind_within_limits else 'EXCEEDS LIMIT'})")
    lines.append(f"- **Go/No-Go:** {'GO' if e.scorecard.overall_go else 'NO-GO'}")
    for note in e.scorecard.notes:
        lines.append(f"  - {note}")
    lines.append("")

    lines.append("## 2. Motor Selection (Stage 1)\n")
    lines.append(f"- **Target apogee:** {ms.target_apogee_m:.0f} m (+/-{ms.apogee_tolerance_pct:.1f}%)")
    lines.append(f"- **Selected motor:** {ms.selected.motor_id} "
                 f"({ms.selected.total_impulse_n_s:.0f} Ns, class {ms.selected.impulse_class.value})")
    lines.append(f"- **Predicted apogee:** {ms.selected.predicted_apogee_m:.0f} m "
                 f"({ms.selected.apogee_error_pct:+.2f}% from target)")
    lines.append(f"- **Predicted Max-Q:** {ms.selected.predicted_max_q_pa/1000:.1f} kPa | "
                 f"**Max Mach:** {ms.selected.predicted_max_mach:.2f}\n")
    lines.append("**Motor trade study (shortlist):**\n")
    lines.append(_motor_table(report))
    lines.append("")

    lines.append("## 3. Stability Margin vs Mach (Stage 4)\n")
    lines.append(f"- **Selected fin set:** {s.fin.fin_id} "
                 f"({s.fin.n_fins} fins, root {s.fin.root_chord_m*100:.1f} cm, span {s.fin.span_m*100:.1f} cm)")
    lines.append(f"- **Minimum static margin:** {s.min_margin_cal:.2f} cal at Mach {s.min_margin_mach:.2f}")
    lines.append(f"- **Transonic-band minimum:** {s.transonic_min_margin_cal:.2f} cal "
                 f"({'DIP DETECTED' if s.transonic_dip_detected else 'no dip detected'})")
    lines.append(f"- **Stable across full flight:** {'YES' if s.is_stable else 'NO'}\n")
    for note in s.notes:
        lines.append(f"  - {note}")
    lines.append(f"\n![Stability margin vs Mach]({plot_paths['stability'].name})\n")
    lines.append("**Fin geometry sweep (all candidates evaluated):**\n")
    lines.append(_stability_table(report, all_stability_results))
    lines.append("")

    lines.append("## 4. Six-DOF Monte Carlo Dispersion (Stage 2, confirmation run)\n")
    lines.append(f"- **Runs:** {d.n_runs} ({d.n_converged} converged)")
    lines.append(f"- **Apogee:** {d.apogee_mean_m:.0f} m +/- {d.apogee_std_m:.0f} m (1-sigma)")
    lines.append(f"- **Max-Q:** {d.max_q_mean_pa/1000:.1f} kPa +/- {d.max_q_std_pa/1000:.1f} kPa")
    ell = d.landing_ellipse_95
    lines.append(f"- **95% landing ellipse:** semi-major {ell.semi_major_m:.0f} m, "
                 f"semi-minor {ell.semi_minor_m:.0f} m, centered "
                 f"({ell.center_x_m:.0f}, {ell.center_y_m:.0f}) m from the pad, "
                 f"rotated {ell.rotation_deg:.0f} deg")
    lines.append(f"\n![Landing dispersion ellipse]({plot_paths['dispersion'].name})\n")

    lines.append("## 5. Recovery System Optimization (Stage 3)\n")
    lines.append(f"- **Recommended:** drogue Cd·S={rc.recommended.drogue_cd_s:.1f}, "
                 f"main Cd·S={rc.recommended.main_cd_s:.1f}, "
                 f"main deploy altitude={rc.recommended.main_deploy_altitude_m:.0f} m AGL")
    lines.append(f"- **Predicted drift:** {rc.recommended.predicted_drift_m:.0f} m | "
                 f"**Impact velocity:** {rc.recommended.predicted_impact_velocity_m_s:.2f} m/s "
                 f"(limit {rc.max_safe_impact_velocity_m_s:.1f} m/s)")
    lines.append(f"- **Footprint reduction vs. baseline config:** {rc.footprint_reduction_pct:.1f}%")
    lines.append(f"- **Pareto-optimal candidates:** {len(rc.pareto_front)} of {len(rc.candidates)} evaluated")
    lines.append(f"\n![Recovery drift vs impact-velocity trade-off]({plot_paths['recovery'].name})\n")

    if v:
        lines.append("## 6. Real Flight Validation (Stage 5)\n")
        lines.append(f"- **Source:** {v.actual.source}")
        lines.append(f"- **Apogee error:** {v.apogee_error_pct:+.2f}%  "
                     f"(sim {v.simulated.apogee_m:.0f} m vs actual {v.actual.apogee_m:.0f} m)")
        lines.append(f"- **Max velocity error:** {v.velocity_error_pct:+.2f}%")
        lines.append(f"- **Descent rate error:** {v.descent_rate_error_pct:+.2f}%")
        lines.append(f"- **Within {v.acceptable_error_pct:.0f}% acceptance band:** "
                     f"{'YES' if v.within_acceptable_error else 'NO'}\n")
        for cause in v.likely_causes:
            lines.append(f"  - {cause}")
        lines.append("")
    else:
        lines.append("## 6. Real Flight Validation (Stage 5)\n")
        lines.append("_Skipped — no flight log configured. See README \"Using real flight data.\"_\n")

    lines.append("---")
    lines.append("_Report generated automatically by the Apogee pipeline. "
                 "Motor thrust curves are synthetic demo data unless replaced — see README._")

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines))
    return out_path
