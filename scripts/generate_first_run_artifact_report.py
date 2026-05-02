#!/usr/bin/env python3
"""
generate_first_run_artifact_report.py
=====================================
Builds a thesis-style artifact bundle for the currently available first-run
datasets:
  - 36 core runs: auth-service + shipping-rate-service
  - 18 exploratory runs: product-service

Outputs:
  - Markdown report
  - CSV + JSON summaries
  - Compact summary heatmaps
  - Full thesis figure bundle via generate_thesis_graphs.py
"""

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import generate_thesis_graphs as gt  # noqa: E402


CONFIGS = gt.CONFIGS
PATTERNS = gt.PATTERNS
PATTERN_LABELS = gt.PATTERN_LABELS
CONFIG_LABELS = gt.CONFIG_LABELS
CORE_SERVICES = gt.CORE_SERVICES
EXPLORATORY_SERVICES = gt.EXPLORATORY_SERVICES
ALL_SERVICES = CORE_SERVICES + EXPLORATORY_SERVICES
CORE_SET = set(CORE_SERVICES)


def parse_duration_to_ms(raw: str) -> float:
    unit_ms = {
        "ns": 1e-6,
        "us": 1e-3,
        "µs": 1e-3,
        "ms": 1.0,
        "s": 1000.0,
        "m": 60_000.0,
        "h": 3_600_000.0,
    }
    matches = re.findall(r"([0-9.]+)(ns|us|µs|ms|s|m|h)", raw)
    if not matches:
        return math.nan
    return sum(float(value) * unit_ms[unit] for value, unit in matches)


def parse_k6_extended(log_path: Path) -> dict:
    metrics = {
        "p95_ms": math.nan,
        "error_rate": math.nan,
        "avg_rps": math.nan,
        "http_reqs_total": math.nan,
        "dropped_iterations": 0,
    }
    if not log_path.exists():
        return metrics

    content = log_path.read_text(errors="replace")

    match = re.search(r"http_req_duration[^\n]*p\(95\)=([^\s]+)", content)
    if match:
        metrics["p95_ms"] = parse_duration_to_ms(match.group(1))

    match = re.search(r"http_req_failed[^:]*:\s+([0-9.]+)%", content)
    if match:
        metrics["error_rate"] = float(match.group(1))

    match = re.search(r"http_reqs[^:]*:\s+(\d+)\s+([0-9.]+)/s", content)
    if match:
        metrics["http_reqs_total"] = float(match.group(1))
        metrics["avg_rps"] = float(match.group(2))

    match = re.search(r"dropped_iterations[^:]*:\s+(\d+)", content)
    if match:
        metrics["dropped_iterations"] = int(match.group(1))

    return metrics


def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def load_series_max(path: Path) -> float:
    data = load_json(path, {})
    values = []
    for result in data.get("data", {}).get("result", []):
        for _, raw in result.get("values", []):
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue
    return max(values) if values else math.nan


def count_replica_changes(replica_df) -> int:
    if replica_df.empty:
        return 0
    values = replica_df["value"].tolist()
    return sum(1 for idx in range(1, len(values)) if values[idx] != values[idx - 1])


def detect_foreign_k6_jobs(rep_dir: Path, metadata: dict) -> list[str]:
    events_path = rep_dir / "k8s-events.txt"
    if not events_path.exists():
        return []
    current_job = metadata.get("k6_job_name", "")
    content = events_path.read_text(errors="replace")
    jobs = sorted(set(re.findall(r"job/(k6-[^\s]+)", content)))
    return [job for job in jobs if job != current_job]


def detect_early_ready_contamination(rep_data: dict) -> bool:
    ready = rep_data.get("replicas_ready")
    if ready is None or ready.empty:
        return False
    early_values = ready["value"].tolist()[:12]
    return any(v > 1 for v in early_values[:4]) and any(v == 1 for v in early_values[4:])


def summarize_runs(results_dir: Path) -> list[dict]:
    data = gt.load_all_data(results_dir)
    rows = []

    for service in ALL_SERVICES:
        for config in CONFIGS:
            for pattern in PATTERNS:
                rep_dir = results_dir / service / config / pattern / "rep1"
                if not rep_dir.exists():
                    continue

                rep_data = data.get(service, {}).get(config, {}).get(pattern, {}).get(1)
                if not rep_data:
                    continue

                metadata = load_json(rep_dir / "metadata.json", {})
                k6 = parse_k6_extended(rep_dir / "k6-output.log")
                duration = metadata.get("duration_seconds") or 720
                cost_musd = gt.compute_cost_index(rep_data["replicas"], duration) * 1000
                foreign_jobs = detect_foreign_k6_jobs(rep_dir, metadata)

                rows.append({
                    "service": service,
                    "scope": "core" if service in CORE_SET else "exploratory",
                    "config": config,
                    "pattern": pattern,
                    "run_id": metadata.get("run_id", f"{service}_{config}_{pattern}_rep1"),
                    "duration_seconds": duration,
                    "p95_ms": k6["p95_ms"],
                    "error_rate": k6["error_rate"],
                    "avg_rps": k6["avg_rps"],
                    "http_reqs_total": k6["http_reqs_total"],
                    "dropped_iterations": k6["dropped_iterations"],
                    "max_replicas": load_series_max(rep_dir / "prom_replica_count.json"),
                    "max_ready_replicas": load_series_max(rep_dir / "prom_replica_ready_count.json"),
                    "scaling_changes": count_replica_changes(rep_data["replicas"]),
                    "cost_musd": cost_musd,
                    "latency_capped": bool(rep_data.get("latency_capped")),
                    "foreign_k6_jobs": foreign_jobs,
                    "foreign_k6_job_count": len(foreign_jobs),
                    "early_ready_contamination": detect_early_ready_contamination(rep_data),
                })

    return rows


def write_csv(rows: list[dict], path: Path):
    if not rows:
        return
    fieldnames = [
        "service",
        "scope",
        "config",
        "pattern",
        "run_id",
        "duration_seconds",
        "p95_ms",
        "error_rate",
        "avg_rps",
        "http_reqs_total",
        "dropped_iterations",
        "max_replicas",
        "max_ready_replicas",
        "scaling_changes",
        "cost_musd",
        "latency_capped",
        "foreign_k6_job_count",
        "foreign_k6_jobs",
        "early_ready_contamination",
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = row.copy()
            out["foreign_k6_jobs"] = ";".join(row["foreign_k6_jobs"])
            writer.writerow(out)


def write_json(obj, path: Path):
    path.write_text(json.dumps(obj, indent=2))


def format_ms(value: float) -> str:
    if value is None or math.isnan(value):
        return "N/A"
    if value >= 1000:
        return f"{value / 1000:.2f}s"
    return f"{value:.0f}ms"


def format_pct(value: float) -> str:
    if value is None or math.isnan(value):
        return "N/A"
    return f"{value:.2f}%"


def format_musd(value: float) -> str:
    if value is None or math.isnan(value):
        return "N/A"
    return f"{value:.3f} m$"


def pct_change(new: float, old: float) -> str:
    if any(math.isnan(v) for v in (new, old)) or old == 0:
        return "N/A"
    return f"{((new - old) / old) * 100:+.1f}%"


def table_md(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def plot_dual_heatmap(rows: list[dict], services: list[str], metric_key: str, title: str,
                      out_path: Path, cmap: str, value_formatter):
    gt.apply_style()
    fig, axes = plt.subplots(1, len(services), figsize=(6.5 * len(services), 5.8), constrained_layout=True)
    if len(services) == 1:
        axes = [axes]

    matrices = []
    for service in services:
        matrix = np.full((len(CONFIGS), len(PATTERNS)), np.nan)
        for i, config in enumerate(CONFIGS):
            for j, pattern in enumerate(PATTERNS):
                row = next((r for r in rows if r["service"] == service and r["config"] == config and r["pattern"] == pattern), None)
                if row is not None:
                    matrix[i, j] = row.get(metric_key, math.nan)
        matrices.append(matrix)

    finite_values = np.concatenate([m[np.isfinite(m)] for m in matrices if np.isfinite(m).any()]) if matrices else np.array([])
    vmin = float(np.nanmin(finite_values)) if finite_values.size else 0.0
    vmax = float(np.nanmax(finite_values)) if finite_values.size else 1.0
    if math.isclose(vmin, vmax):
        vmax = vmin + 1.0

    for ax, service, matrix in zip(axes, services, matrices):
        im = ax.imshow(matrix, cmap=cmap, aspect="auto", vmin=vmin, vmax=vmax)
        ax.set_title(service, fontweight="bold")
        ax.set_xticks(range(len(PATTERNS)))
        ax.set_xticklabels([PATTERN_LABELS[p] for p in PATTERNS], rotation=20, ha="right")
        ax.set_yticks(range(len(CONFIGS)))
        ax.set_yticklabels([config.upper() for config in CONFIGS])

        for i in range(len(CONFIGS)):
            for j in range(len(PATTERNS)):
                value = matrix[i, j]
                label = value_formatter(value)
                text_color = "white" if np.isfinite(value) and value > (vmin + vmax) / 2 else "black"
                ax.text(j, i, label, ha="center", va="center", fontsize=8, color=text_color)

    fig.suptitle(title, fontsize=13, fontweight="bold")
    cbar = fig.colorbar(im, ax=axes, shrink=0.88)
    cbar.ax.tick_params(labelsize=8)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_product_appendix_heatmaps(rows: list[dict], out_path: Path):
    product_rows = [row for row in rows if row["service"] == "product-service"]
    gt.apply_style()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), constrained_layout=True)
    specs = [
        ("p95_ms", "Product-Service Appendix: p95 Latency (ms)", "magma", format_ms),
        ("error_rate", "Product-Service Appendix: Error Rate (%)", "Reds", format_pct),
    ]

    for ax, (metric_key, title, cmap, formatter) in zip(axes, specs):
        matrix = np.full((len(CONFIGS), len(PATTERNS)), np.nan)
        for i, config in enumerate(CONFIGS):
            for j, pattern in enumerate(PATTERNS):
                row = next((r for r in product_rows if r["config"] == config and r["pattern"] == pattern), None)
                if row is not None:
                    matrix[i, j] = row.get(metric_key, math.nan)

        finite = matrix[np.isfinite(matrix)]
        vmin = float(np.nanmin(finite)) if finite.size else 0.0
        vmax = float(np.nanmax(finite)) if finite.size else 1.0
        if math.isclose(vmin, vmax):
            vmax = vmin + 1.0

        im = ax.imshow(matrix, cmap=cmap, aspect="auto", vmin=vmin, vmax=vmax)
        ax.set_title(title, fontweight="bold", fontsize=11)
        ax.set_xticks(range(len(PATTERNS)))
        ax.set_xticklabels([PATTERN_LABELS[p] for p in PATTERNS], rotation=20, ha="right")
        ax.set_yticks(range(len(CONFIGS)))
        ax.set_yticklabels([config.upper() for config in CONFIGS])

        for i in range(len(CONFIGS)):
            for j in range(len(PATTERNS)):
                value = matrix[i, j]
                label = formatter(value)
                text_color = "white" if np.isfinite(value) and value > (vmin + vmax) / 2 else "black"
                ax.text(j, i, label, ha="center", va="center", fontsize=8, color=text_color)

        cbar = fig.colorbar(im, ax=ax, shrink=0.88)
        cbar.ax.tick_params(labelsize=8)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def run_command(cmd: list[str]) -> str:
    completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return completed.stdout


def parse_validator_counts(output: str) -> dict:
    counts = {"critical": 0, "warnings": 0, "info": 0}
    patterns = {
        "critical": r"Critical issues:\s+(\d+)",
        "warnings": r"Warnings:\s+(\d+)",
        "info": r"Info:\s+(\d+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            counts[key] = int(match.group(1))
    return counts


def validator_snapshot() -> dict:
    snapshot = {}
    services = ["auth-service", "shipping-rate-service"]
    for service in services:
        validate_output = run_command(["bash", str(SCRIPT_DIR / "validate-results.sh"), service])
        deep_output = run_command([
            sys.executable,
            str(SCRIPT_DIR / "deep_validate.py"),
            "--service",
            service,
            "--config",
            ",".join(CONFIGS),
            "--rep",
            "1",
        ])
        snapshot[service] = {
            "validate_results": parse_validator_counts(validate_output),
            "deep_validate": parse_validator_counts(deep_output),
        }
    return snapshot


def render_existing_figures(results_dir: Path, figures_dir: Path):
    run_command([
        sys.executable,
        str(SCRIPT_DIR / "generate_thesis_graphs.py"),
        "--results-dir",
        str(results_dir),
        "--out-dir",
        str(figures_dir),
    ])


def select_best(rows: list[dict], service: str, pattern: str, autoscaler_only: bool = False) -> dict | None:
    configs = {"h1", "h2", "h3", "k1"} if autoscaler_only else set(CONFIGS)
    candidates = [
        row for row in rows
        if row["service"] == service and row["pattern"] == pattern and row["config"] in configs and not math.isnan(row["p95_ms"])
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: row["p95_ms"])


def build_report(rows: list[dict], validation: dict, out_dir: Path, figures_dir: Path) -> str:
    core_rows = [row for row in rows if row["scope"] == "core"]
    product_rows = [row for row in rows if row["service"] == "product-service"]
    auth_rows = [row for row in rows if row["service"] == "auth-service"]
    shipping_rows = [row for row in rows if row["service"] == "shipping-rate-service"]

    auth_contaminated = sum(1 for row in auth_rows if row["foreign_k6_job_count"] > 0)
    shipping_contaminated = sum(1 for row in shipping_rows if row["foreign_k6_job_count"] > 0)

    best_table_rows = []
    for service in CORE_SERVICES:
        for pattern in PATTERNS:
            best_all = select_best(rows, service, pattern, autoscaler_only=False)
            best_auto = select_best(rows, service, pattern, autoscaler_only=True)
            best_table_rows.append([
                service,
                PATTERN_LABELS[pattern],
                f"{best_all['config'].upper()} ({format_ms(best_all['p95_ms'])})" if best_all else "N/A",
                f"{best_auto['config'].upper()} ({format_ms(best_auto['p95_ms'])})" if best_auto else "N/A",
            ])

    validation_rows = [
        [
            "auth-service",
            f"{validation['auth-service']['validate_results']['critical']} critical / {validation['auth-service']['validate_results']['warnings']} warnings",
            f"{validation['auth-service']['deep_validate']['critical']} critical / {validation['auth-service']['deep_validate']['warnings']} warnings",
            "Performance-useful, but artifact scoping is contaminated by older event exports.",
        ],
        [
            "shipping-rate-service",
            f"{validation['shipping-rate-service']['validate_results']['critical']} critical / {validation['shipping-rate-service']['validate_results']['warnings']} warnings",
            f"{validation['shipping-rate-service']['deep_validate']['critical']} critical / {validation['shipping-rate-service']['deep_validate']['warnings']} warnings",
            "Clean first sweep; acceptable as current thesis-quality shipping evidence.",
        ],
    ]

    decomposition_rows = []
    for service in CORE_SERVICES:
        for pattern in PATTERNS:
            h1 = next(row for row in rows if row["service"] == service and row["config"] == "h1" and row["pattern"] == pattern)
            h3 = next(row for row in rows if row["service"] == service and row["config"] == "h3" and row["pattern"] == pattern)
            k1 = next(row for row in rows if row["service"] == service and row["config"] == "k1" and row["pattern"] == pattern)
            decomposition_rows.append([
                service,
                PATTERN_LABELS[pattern],
                format_ms(h1["p95_ms"]),
                format_ms(h3["p95_ms"]),
                format_ms(k1["p95_ms"]),
                pct_change(h3["p95_ms"], h1["p95_ms"]),
                pct_change(k1["p95_ms"], h3["p95_ms"]),
                pct_change(k1["p95_ms"], h1["p95_ms"]),
            ])

    product_comparison_rows = []
    for pattern in PATTERNS:
        b1 = next(row for row in product_rows if row["config"] == "b1" and row["pattern"] == pattern)
        b2 = next(row for row in product_rows if row["config"] == "b2" and row["pattern"] == pattern)
        h3 = next(row for row in product_rows if row["config"] == "h3" and row["pattern"] == pattern)
        k1 = next(row for row in product_rows if row["config"] == "k1" and row["pattern"] == pattern)
        product_comparison_rows.append([
            PATTERN_LABELS[pattern],
            f"{format_ms(b1['p95_ms'])} / {format_pct(b1['error_rate'])}",
            f"{format_ms(b2['p95_ms'])} / {format_pct(b2['error_rate'])}",
            f"{format_ms(h3['p95_ms'])} / {format_pct(h3['error_rate'])}",
            f"{format_ms(k1['p95_ms'])} / {format_pct(k1['error_rate'])}",
        ])

    report_lines = [
        "# Full Artifact Report — Current First-Run Dataset",
        "",
        f"Generated: {datetime.now(timezone.utc).astimezone().isoformat()}",
        "",
        "## Scope",
        "",
        "- 36 core first runs: `auth-service` + `shipping-rate-service`",
        "- 18 exploratory first runs: `product-service`",
        "- Source directory: `experiment-results/`",
        "",
        "## Executive Verdict",
        "",
        "- `shipping-rate-service` is the clean part of the current core matrix. Its 18-run first sweep passes the current validator stack and is suitable as the wait-dominant side of the thesis comparison.",
        "- `auth-service` still shows the expected CPU-dominant performance story, but its current first-run artifacts are not fully clean: all 18 auth `k8s-events.txt` files contain foreign k6 jobs from neighboring runs, so older event exports contaminate deep per-run validation.",
        "- `product-service` remains valuable only as an appendix case. The first 18 runs are overwhelmingly dependency-limited and should not be revived as part of the final controlled matrix.",
        "",
        "## Validation Snapshot",
        "",
        table_md(
            ["Service", "validate-results.sh", "deep_validate.py", "Interpretation"],
            validation_rows,
        ),
        "",
        f"Auth artifact caveat: `{auth_contaminated}/18` auth runs contain foreign k6 jobs inside `k8s-events.txt`, while shipping has `{shipping_contaminated}/18` such cases.",
        "",
        "## Best Configs By Pattern",
        "",
        table_md(
            ["Service", "Pattern", "Best Overall p95", "Best Autoscaled p95"],
            best_table_rows,
        ),
        "",
        "## Core Findings",
        "",
        "### Auth-Service",
        "",
        "- The control behavior is visible in performance terms: `B1` is a true overloaded lower bound, with roughly `48%–63%` failed requests and `p95 ≈ 60s` across all three patterns.",
        "- `B2` is the absolute latency winner for all three auth patterns, but it pays the highest fixed cost because it runs at `5` replicas throughout.",
        "- Among autoscaled auth configs, `H2` is the strongest overall result in the current rep1 data. It wins `gradual` and `spike`, while `H1` is the least-bad autoscaled option under `oscillating` load.",
        "- Request-rate methods do not currently beat CPU-based HPA on auth. In the current data, `H3` and `K1` are materially worse than `H1/H2` on `spike` and `oscillating`, which supports the thesis claim that CPU remains the right signal for a bcrypt-heavy service.",
        "- The dataset caveat is methodological, not purely performance-related: these auth runs predate the later run-scoped event exporter fixes, so they are still useful analytically but not yet the cleanest final evidence set.",
        "",
        "### Shipping-Rate-Service",
        "",
        "- `B1` and `B2` now give a strong, clean envelope: `B1` sits around `p95 ≈ 5.1–5.2s`, while `B2` holds roughly `916–917ms` in all three patterns.",
        "- `Gradual` load is where request-rate scaling is clearest: `H3` and `K1` both land near `~0.97s`, much closer to `B2` than to `H1` (`1.62s`) or `B1` (`5.18s`).",
        "- `Spike` load remains the hardest case for all reactive autoscalers. `H1`, `H2`, `H3`, and `K1` all cluster near `~5.1–5.3s`, while only fixed-overprovisioned `B2` stays below `1s`. That is a scale-lag result, not an autoscaler-broken result.",
        "- `Oscillating` load is the most nuanced shipping pattern. `H1` is surprisingly strong (`~942ms`), `K1` is next (`~1.13s`), and `H2/H3` remain near `~5s`. This shows the shipping workload is still wait-dominant in architecture, but CPU rises enough under concurrency that CPU HPA is not completely blind.",
        "",
        "## Decomposition: Metric Effect vs Engine Effect",
        "",
        table_md(
            ["Service", "Pattern", "H1 p95", "H3 p95", "K1 p95", "Metric Effect (H3 vs H1)", "Engine Effect (K1 vs H3)", "Combined (K1 vs H1)"],
            decomposition_rows,
        ),
        "",
        "Reading guide:",
        "- Negative percentages are improvements because lower p95 latency is better.",
        "- On auth, the current rep1 data shows request-rate helps only in `gradual`; it hurts badly in `spike` and `oscillating`.",
        "- On shipping, request-rate helps strongly in `gradual`, but engine/metric effects are pattern-dependent rather than universal.",
        "",
        "## Product-Service Appendix",
        "",
        "- The product dataset is exactly why the thesis pivot was the right call: all 18 first runs are already bad before any fine-grained comparison, with roughly `87%–96%` failed requests and `p95 ≈ 31–60s`.",
        "- `B2` is worse than `B1` in every product pattern, which means adding fixed app replicas did not rescue the workload and often made it worse.",
        "- `H3` and `K1` also fail to repair the situation. In several product runs they are slower, fail more often, and deliver fewer total requests than the simpler baselines. That points to downstream database limitation, not autoscaler inactivity.",
        "",
        table_md(
            ["Pattern", "B1 (p95 / err)", "B2 (p95 / err)", "H3 (p95 / err)", "K1 (p95 / err)"],
            product_comparison_rows,
        ),
        "",
        "Interpretation: keep product-service in the thesis as a supporting cautionary case about scaling the wrong tier, not as part of the final statistical core matrix.",
        "",
        "## Artifact Inventory",
        "",
        f"- Report directory: `{out_dir}`",
        "- Machine-readable summaries:",
        "  - `core_first_run_summary.csv`",
        "  - `product_first_run_summary.csv`",
        "  - `all_first_run_summary.json`",
        "  - `validation_snapshot.json`",
        "- Summary figures created specifically for this report:",
        "  - `summary_core_p95_heatmaps.png`",
        "  - `summary_core_error_heatmaps.png`",
        "  - `summary_core_cost_heatmaps.png`",
        "  - `summary_product_appendix_heatmaps.png`",
        f"- Full figure bundle from `generate_thesis_graphs.py`: `{figures_dir}`",
        "",
        "## Thesis Use Recommendation",
        "",
        "- Use the current shipping first sweep directly in the thesis as the wait-dominant core evidence.",
        "- Use the current auth first sweep as a strong directional CPU-bound result set, but label it as requiring a clean rerun if you want the full 36-run core matrix to be artifact-clean under the latest exporter/validator rules.",
        "- Use product only in the appendix or discussion chapter as evidence that autoscaling the app tier cannot fix a downstream bottleneck.",
        "",
    ]
    return "\n".join(report_lines)


def main():
    parser = argparse.ArgumentParser(description="Generate first-run artifact report and figures.")
    parser.add_argument("--results-dir", default="experiment-results", help="Experiment results directory")
    parser.add_argument(
        "--out-dir",
        default="experiment-results/artifacts/first-run-report",
        help="Output directory for report, summaries, and figures",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    out_dir = Path(args.out_dir)
    figures_dir = out_dir / "figures"

    out_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    rows = summarize_runs(results_dir)
    if not rows:
        print(f"No runs found under {results_dir}", file=sys.stderr)
        sys.exit(1)

    core_rows = [row for row in rows if row["scope"] == "core"]
    product_rows = [row for row in rows if row["scope"] == "exploratory"]

    write_csv(core_rows, out_dir / "core_first_run_summary.csv")
    write_csv(product_rows, out_dir / "product_first_run_summary.csv")
    write_json(rows, out_dir / "all_first_run_summary.json")

    validation = validator_snapshot()
    write_json(validation, out_dir / "validation_snapshot.json")

    plot_dual_heatmap(
        rows,
        CORE_SERVICES,
        "p95_ms",
        "Core First-Run Summary — p95 Latency",
        out_dir / "summary_core_p95_heatmaps.png",
        "magma_r",
        format_ms,
    )
    plot_dual_heatmap(
        rows,
        CORE_SERVICES,
        "error_rate",
        "Core First-Run Summary — Error Rate",
        out_dir / "summary_core_error_heatmaps.png",
        "Reds",
        format_pct,
    )
    plot_dual_heatmap(
        rows,
        CORE_SERVICES,
        "cost_musd",
        "Core First-Run Summary — Resource Cost Index",
        out_dir / "summary_core_cost_heatmaps.png",
        "viridis",
        format_musd,
    )
    plot_product_appendix_heatmaps(rows, out_dir / "summary_product_appendix_heatmaps.png")

    render_existing_figures(results_dir, figures_dir)

    report = build_report(rows, validation, out_dir, figures_dir)
    (out_dir / "first_run_artifact_report.md").write_text(report)
    print(f"Artifact bundle written to {out_dir}")


if __name__ == "__main__":
    main()
