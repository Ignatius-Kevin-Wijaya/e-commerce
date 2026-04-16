#!/usr/bin/env python3
"""
generate_thesis_graphs.py — Thesis Figure Generation Pipeline
=============================================================
Crawls experiment-results/, parses all Prometheus JSON arrays and k6 logs,
computes 95% CI statistics across repetitions, and emits all required thesis
figures as high-resolution PNGs into thesis-figures/.

Usage:
    python generate_thesis_graphs.py [--results-dir <path>] [--out-dir <path>]

Run via wrapper (handles venv):
    ./scripts/generate_thesis.sh
"""

import argparse
import json
import os
import re
import sys
import warnings
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless rendering — no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
from matplotlib.gridspec import GridSpec

warnings.filterwarnings("ignore")

# ── Constants ────────────────────────────────────────────────────────────────

# Ordered config list as they appear in the thesis
CONFIGS = ["b1", "b2", "h1", "h2", "h3", "k1"]
PATTERNS = ["gradual", "spike", "oscillating"]
CORE_SERVICES = ["shipping-rate-service", "auth-service"]
EXPLORATORY_SERVICES = ["product-service"]
SERVICES = CORE_SERVICES + EXPLORATORY_SERVICES
REPS = [1, 2, 3, 4, 5]

# AKS D4as_v5 node: $0.172/hour ÷ 4 vCPU ≈ $0.043/core-hour
# Core thesis services request 250m CPU → 0.25 vCPU baseline per pod
CPU_REQUEST_CORES = 0.25
PRICE_PER_CPU_SECOND = (0.172 / 4) / 3600  # $/second per vCPU core

# Display labels and colors for each config
CONFIG_LABELS = {
    "b1": "B1 (No Autoscaler)",
    "b2": "B2 (No Autoscaler)",
    "h1": "H1 (HPA CPU)",
    "h2": "H2 (HPA Tuned CPU)",
    "h3": "H3 (HPA RPS)",
    "k1": "K1 (KEDA RPS)",
}
CONFIG_COLORS = {
    "b1": "#888888",
    "b2": "#aaaaaa",
    "h1": "#2196F3",   # blue
    "h2": "#9C27B0",   # purple
    "h3": "#FF9800",   # orange
    "k1": "#4CAF50",   # green
}
PATTERN_MARKERS = {
    "gradual":     "o",
    "spike":       "^",
    "oscillating": "s",
}
PATTERN_LABELS = {
    "gradual":     "Gradual Ramp",
    "spike":       "Sudden Spike",
    "oscillating": "Oscillating",
}

# ── Utility: Prometheus JSON → DataFrame ───────────────────────────────────

SERVICE_HANDLER_FILTERS = {
    "product-service": "/products",
    "auth-service": "/auth/login",
    "shipping-rate-service": "/shipping/quotes",
}


def load_prom_series(filepath: Path, handler_filter: str = "/products") -> pd.DataFrame:
    """
    Load a Prometheus range-query JSON file.
    Returns a DataFrame with columns [ts, value] filtered to the target handler.
    Returns empty DataFrame if file missing or empty.
    """
    if not filepath.exists():
        return pd.DataFrame(columns=["ts", "value"])
    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return pd.DataFrame(columns=["ts", "value"])

    if data.get("status") != "success":
        return pd.DataFrame(columns=["ts", "value"])

    rows = []
    for result in data.get("data", {}).get("result", []):
        metric = result.get("metric", {})
        handler = metric.get("handler", "")
        # For replica / CPU files there's no handler — include all
        if handler_filter and handler and handler != handler_filter:
            continue
        for ts, val in result.get("values", []):
            try:
                v = float(val)
                if not np.isnan(v) and not np.isinf(v):
                    rows.append({"ts": int(ts), "value": v})
            except (ValueError, TypeError):
                pass

    if not rows:
        return pd.DataFrame(columns=["ts", "value"])

    df = pd.DataFrame(rows)
    # Collapse multiple pods by summing (replica count, CPU) or taking max (latency)
    return df.groupby("ts", as_index=False)["value"].sum()


def load_prom_latency(filepath: Path, handler_filter: str = "/products") -> pd.DataFrame:
    """Load latency series — take max across pods rather than sum."""
    if not filepath.exists():
        return pd.DataFrame(columns=["ts", "value"])
    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return pd.DataFrame(columns=["ts", "value"])

    if data.get("status") != "success":
        return pd.DataFrame(columns=["ts", "value"])

    rows = []
    for result in data.get("data", {}).get("result", []):
        metric = result.get("metric", {})
        handler = metric.get("handler", "")
        if handler_filter and handler and handler != handler_filter:
            continue
        for ts, val in result.get("values", []):
            try:
                v = float(val)
                if not np.isnan(v) and not np.isinf(v):
                    rows.append({"ts": int(ts), "value": v})
            except (ValueError, TypeError):
                pass

    if not rows:
        return pd.DataFrame(columns=["ts", "value"])

    df = pd.DataFrame(rows)
    return df.groupby("ts", as_index=False)["value"].max()


# ── Utility: k6 log → scalar KPIs ─────────────────────────────────────────

def parse_k6_log(log_path: Path) -> dict:
    """
    Extract scalar KPIs from a k6 stdout log file.
    Returns dict with keys: p95_ms, error_rate, avg_rps
    """
    kpis = {"p95_ms": np.nan, "error_rate": np.nan, "avg_rps": np.nan}
    if not log_path.exists():
        return kpis

    content = log_path.read_text(errors="replace")

    # p95 — formats: "p(95)=4.72s" or "p(95)=472.3ms"
    m = re.search(r"p\(95\)=([0-9.]+)(ms|s)\b", content)
    if m:
        val, unit = float(m.group(1)), m.group(2)
        kpis["p95_ms"] = val if unit == "ms" else val * 1000

    # error rate — "http_req_failed...: 31.03% ..."
    m = re.search(r"http_req_failed[^:]*:\s+([0-9.]+)%", content)
    if m:
        kpis["error_rate"] = float(m.group(1))

    # average throughput — "http_reqs...: 30308  42.09/s"
    m = re.search(r"http_reqs[^:]*:\s+\d+\s+([0-9.]+)/s", content)
    if m:
        kpis["avg_rps"] = float(m.group(1))

    return kpis


# ── Utility: normalize timestamp → relative seconds ───────────────────────

def normalize_ts(df: pd.DataFrame, start_epoch: int) -> pd.DataFrame:
    """Convert absolute epoch timestamps to seconds-since-experiment-start."""
    df = df.copy()
    df["t"] = df["ts"] - start_epoch
    return df.sort_values("t").reset_index(drop=True)


# ── Data Loading: single rep ───────────────────────────────────────────────

def load_rep(rep_dir: Path, service: str, start_epoch: int = None) -> dict:
    """
    Load all data for a single rep directory.
    Returns a dict with DataFrames and scalar KPIs.
    """
    meta_path = rep_dir / "metadata.json"
    if start_epoch is None and meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        start_epoch = meta.get("start_epoch", 0)

    handler = SERVICE_HANDLER_FILTERS.get(service, "/products")

    rps = normalize_ts(
        load_prom_series(rep_dir / "prom_http_requests_rate.json", handler),
        start_epoch
    )
    latency = normalize_ts(
        load_prom_latency(rep_dir / "prom_p95_latency.json", handler),
        start_epoch
    )
    replicas = normalize_ts(
        load_prom_series(rep_dir / "prom_replica_count.json", ""),
        start_epoch
    )
    replicas_ready = normalize_ts(
        load_prom_series(rep_dir / "prom_replica_ready_count.json", ""),
        start_epoch
    )
    cpu = normalize_ts(
        load_prom_series(rep_dir / "prom_cpu_usage.json", ""),
        start_epoch
    )
    k6 = parse_k6_log(rep_dir / "k6-output.log")

    return {
        "rps": rps,
        "latency": latency,
        "replicas": replicas,
        "replicas_ready": replicas_ready,
        "cpu": cpu,
        "k6": k6,
        "start_epoch": start_epoch,
    }


# ── Data Loading: full sweep ───────────────────────────────────────────────

def load_all_data(results_dir: Path) -> dict:
    """
    Crawl all experiment results and return nested dict:
    data[service][config][pattern][rep_n] = rep_data_dict
    """
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))

    for service in SERVICES:
        for config in CONFIGS:
            for pattern in PATTERNS:
                for rep in REPS:
                    rep_dir = results_dir / service / config / pattern / f"rep{rep}"
                    if not rep_dir.exists():
                        continue
                    try:
                        data[service][config][pattern][rep] = load_rep(rep_dir, service=service)
                    except Exception as e:
                        print(f"  ⚠️  Skipping {rep_dir.name}: {e}")

    return data


# ── Stats helper ───────────────────────────────────────────────────────────

def ci95(values: list) -> tuple:
    """Return (mean, half_ci) for 95% CI assuming t-distribution."""
    arr = np.array([v for v in values if v is not None and not np.isnan(v)])
    if len(arr) == 0:
        return np.nan, np.nan
    if len(arr) == 1:
        return arr[0], 0.0
    mean = np.mean(arr)
    se = np.std(arr, ddof=1) / np.sqrt(len(arr))
    # t-critical for 95% CI, df=n-1 (use 2.776 for n=5)
    t_crit = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}.get(len(arr), 2.0)
    return mean, t_crit * se


def compute_cost_index(replicas_df: pd.DataFrame, duration_s: float) -> float:
    """
    Resource Cost Index = Σ(active_pods × Δt × cpu_request) × price_per_cpu_second
    Approximation using trapezoidal integration of replica count over time.
    """
    if replicas_df.empty:
        return np.nan
    t = replicas_df["t"].values
    r = replicas_df["value"].values
    # Only integrate over positive active-load interval
    mask = (t >= 0) & (t <= duration_s)
    if mask.sum() < 2:
        return np.nan
    area = np.trapz(r[mask], t[mask])  # pod-seconds
    return area * CPU_REQUEST_CORES * PRICE_PER_CPU_SECOND


# ── Figure helpers ─────────────────────────────────────────────────────────

THESIS_STYLE = {
    "figure.dpi": 150,
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.35,
    "legend.fontsize": 8,
}


def apply_style():
    plt.rcParams.update(THESIS_STYLE)


def save_fig(fig, out_dir: Path, name: str):
    path = out_dir / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ Saved {path.name}")


# ── Average time-series across reps ───────────────────────────────────────

def avg_timeseries(rep_dicts: list, key: str, grid_step: int = 15) -> pd.DataFrame:
    """
    Given a list of rep data dicts, average the time-series for `key`
    onto a common grid with `grid_step` second intervals.
    Returns DataFrame with columns [t, value].
    """
    if not rep_dicts:
        return pd.DataFrame(columns=["t", "value"])

    # Find common time bounds
    all_t = []
    for r in rep_dicts:
        df = r.get(key, pd.DataFrame())
        if not df.empty:
            all_t.extend(df["t"].tolist())

    if not all_t:
        return pd.DataFrame(columns=["t", "value"])

    t_min = max(0, int(min(all_t)))
    t_max = int(max(all_t))
    grid = np.arange(t_min, t_max + grid_step, grid_step)

    interpolated = []
    for r in rep_dicts:
        df = r.get(key, pd.DataFrame())
        if df.empty:
            continue
        # Interpolate onto common grid
        vals = np.interp(grid, df["t"].values, df["value"].values,
                         left=np.nan, right=np.nan)
        interpolated.append(vals)

    if not interpolated:
        return pd.DataFrame(columns=["t", "value"])

    mat = np.vstack(interpolated)
    mean_vals = np.nanmean(mat, axis=0)
    return pd.DataFrame({"t": grid, "value": mean_vals})


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH 1: Annotated 4-Panel Scaling Timeline
# ══════════════════════════════════════════════════════════════════════════════

def plot_scaling_timeline(data: dict, service: str, pattern: str, out_dir: Path):
    """
    4-panel time-series: RPS | Replicas | p95 Latency | CPU
    One averaged line per config, overlaid on a shared time axis.
    """
    apply_style()
    configs_present = [c for c in CONFIGS if data.get(service, {}).get(c, {}).get(pattern)]
    if not configs_present:
        print(f"  ⚠️  No data for {service}/{pattern} — skipping timeline")
        return

    fig = plt.figure(figsize=(12, 10))
    gs = GridSpec(4, 1, figure=fig, hspace=0.08)
    ax_rps = fig.add_subplot(gs[0])
    ax_rep = fig.add_subplot(gs[1], sharex=ax_rps)
    ax_lat = fig.add_subplot(gs[2], sharex=ax_rps)
    ax_cpu = fig.add_subplot(gs[3], sharex=ax_rps)

    legend_handles = []

    for config in configs_present:
        reps_data = list(data[service][config][pattern].values())
        color = CONFIG_COLORS[config]
        label = CONFIG_LABELS[config]

        ts_rps     = avg_timeseries(reps_data, "rps")
        ts_rep     = avg_timeseries(reps_data, "replicas")
        ts_lat     = avg_timeseries(reps_data, "latency")
        ts_cpu     = avg_timeseries(reps_data, "cpu")

        lw = 2.0 if config in ("h3", "k1") else 1.5
        ls = "-"

        if not ts_rps.empty:
            ax_rps.plot(ts_rps["t"], ts_rps["value"], color=color, lw=lw, ls=ls)
        if not ts_rep.empty:
            ax_rep.plot(ts_rep["t"], ts_rep["value"], color=color, lw=lw, ls=ls)
        if not ts_lat.empty:
            ax_lat.plot(ts_lat["t"], ts_lat["value"] * 1000, color=color, lw=lw, ls=ls)  # s→ms
        if not ts_cpu.empty:
            ax_cpu.plot(ts_cpu["t"], ts_cpu["value"] * 100, color=color, lw=lw, ls=ls)   # cores→%

        legend_handles.append(mpatches.Patch(color=color, label=label))

    # Styling
    ax_rps.set_ylabel("RPS")
    ax_rps.set_title(f"Scaling Timeline — {service}  |  {PATTERN_LABELS[pattern]}", fontsize=12, fontweight="bold")
    ax_rep.set_ylabel("Active Pods")
    ax_rep.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax_lat.set_ylabel("p95 Latency (ms)")
    ax_cpu.set_ylabel("CPU (%)")
    ax_cpu.set_xlabel("Time (seconds from experiment start)")

    # Hide x-tick labels on top three panels
    plt.setp(ax_rps.get_xticklabels(), visible=False)
    plt.setp(ax_rep.get_xticklabels(), visible=False)
    plt.setp(ax_lat.get_xticklabels(), visible=False)

    ax_rps.legend(handles=legend_handles, loc="upper left", ncol=3, framealpha=0.8)

    save_fig(fig, out_dir, f"fig1_timeline_{service.replace('-','_')}_{pattern}")


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH 2: Pareto Frontier Scatterplot (Cost vs Latency)
# ══════════════════════════════════════════════════════════════════════════════

def plot_pareto_frontier(data: dict, service: str, out_dir: Path):
    """
    Scatterplot: x=Resource Cost Index ($), y=mean p95 Latency (ms)
    One point per (config, pattern) combo. Pareto frontier curve drawn.
    """
    apply_style()
    fig, ax = plt.subplots(figsize=(9, 6))

    points = []  # (cost, latency, config, pattern)

    for config in CONFIGS:
        for pattern in PATTERNS:
            reps_dict = data.get(service, {}).get(config, {}).get(pattern, {})
            if not reps_dict:
                continue

            latencies, costs = [], []
            for rep_data in reps_dict.values():
                # k6 scalar p95
                p95 = rep_data["k6"].get("p95_ms", np.nan)
                if not np.isnan(p95):
                    latencies.append(p95)

                # Cost from replica integral
                meta_path = None
                # Duration from k6 log approximation — use 720s (12 min test)
                duration = 720
                cost = compute_cost_index(rep_data["replicas"], duration)
                if not np.isnan(cost):
                    costs.append(cost)

            if not latencies or not costs:
                continue

            mean_lat, _ = ci95(latencies)
            mean_cost, _ = ci95(costs)
            points.append((mean_cost, mean_lat, config, pattern))

    if not points:
        print(f"  ⚠️  Not enough data for Pareto plot ({service})")
        plt.close(fig)
        return

    # Plot each point
    for cost, lat, config, pattern in points:
        ax.scatter(
            cost * 1000,  # convert to millidollars for readability
            lat,
            color=CONFIG_COLORS[config],
            marker=PATTERN_MARKERS[pattern],
            s=120,
            zorder=5,
            edgecolors="white",
            linewidths=0.8,
        )
        ax.annotate(f"{CONFIG_LABELS[config].split('(')[0].strip()}\n{pattern[:3]}.",
                    (cost * 1000, lat),
                    textcoords="offset points", xytext=(6, 4),
                    fontsize=7, color=CONFIG_COLORS[config])

    # Draw Pareto frontier (non-dominated points — lower cost AND lower latency)
    if len(points) >= 2:
        pts_arr = np.array([(c, l) for c, l, _, _ in points])
        dominated = np.zeros(len(pts_arr), dtype=bool)
        for i in range(len(pts_arr)):
            for j in range(len(pts_arr)):
                if i != j:
                    if pts_arr[j, 0] <= pts_arr[i, 0] and pts_arr[j, 1] <= pts_arr[i, 1]:
                        dominated[i] = True
                        break
        frontier = pts_arr[~dominated]
        if len(frontier) >= 2:
            frontier = frontier[frontier[:, 0].argsort()]
            ax.plot(frontier[:, 0] * 1000, frontier[:, 1],
                    "k--", lw=1.5, alpha=0.6, label="Pareto Frontier", zorder=4)

    # Legend: configs
    config_handles = [mpatches.Patch(color=CONFIG_COLORS[c], label=CONFIG_LABELS[c])
                      for c in CONFIGS if any(c == p[2] for p in points)]
    pattern_handles = [mlines.Line2D([], [], color="gray", marker=PATTERN_MARKERS[p],
                                     linestyle="None", markersize=8, label=PATTERN_LABELS[p])
                       for p in PATTERNS if any(p == pt[3] for pt in points)]
    ax.legend(handles=config_handles + pattern_handles, fontsize=8, loc="upper right")

    ax.set_xlabel("Resource Cost Index (millidollars, m$)")
    ax.set_ylabel("Mean p95 Latency (ms)")
    ax.set_title(f"Pareto Frontier — Cost vs Latency\n{service}", fontweight="bold")

    save_fig(fig, out_dir, f"fig2_pareto_{service.replace('-','_')}")


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH 3: Bar Charts with 95% CI Error Bars
# ══════════════════════════════════════════════════════════════════════════════

def plot_bar_charts(data: dict, service: str, out_dir: Path):
    """
    3 grouped bar charts (one per KPI): p95 Latency, Error Rate, Time-to-Scale.
    Groups = load patterns, bars within group = configs.
    Error bars = 95% CI across 5 reps.
    """
    apply_style()

    kpi_specs = [
        ("p95_ms",     "p95 Latency (ms)",      "fig3a_bar_latency"),
        ("error_rate", "Error Rate (%)",         "fig3b_bar_errorrate"),
    ]

    for kpi_key, kpi_label, fig_name in kpi_specs:
        configs_with_data = []
        grouped = {}  # pattern → config → (mean, ci)

        for pattern in PATTERNS:
            grouped[pattern] = {}
            for config in CONFIGS:
                reps_dict = data.get(service, {}).get(config, {}).get(pattern, {})
                vals = [r["k6"].get(kpi_key, np.nan) for r in reps_dict.values()
                        if not np.isnan(r["k6"].get(kpi_key, np.nan))]
                if vals:
                    grouped[pattern][config] = ci95(vals)
                    if config not in configs_with_data:
                        configs_with_data.append(config)

        if not configs_with_data:
            print(f"  ⚠️  No data for bar chart {kpi_key} ({service})")
            continue

        fig, ax = plt.subplots(figsize=(10, 5))
        n_configs = len(configs_with_data)
        n_patterns = len(PATTERNS)
        group_width = 0.8
        bar_width = group_width / n_configs
        x = np.arange(n_patterns)

        for i, config in enumerate(configs_with_data):
            means, cis, positions = [], [], []
            for j, pattern in enumerate(PATTERNS):
                stats = grouped[pattern].get(config, (np.nan, np.nan))
                means.append(stats[0])
                cis.append(stats[1])
                positions.append(x[j] + (i - n_configs / 2 + 0.5) * bar_width)

            # Replace NaN with 0 for plotting
            means_plot = [m if not np.isnan(m) else 0 for m in means]
            cis_plot   = [c if not np.isnan(c) else 0 for c in cis]

            ax.bar(positions, means_plot, bar_width * 0.9,
                   color=CONFIG_COLORS[config],
                   label=CONFIG_LABELS[config],
                   alpha=0.88,
                   yerr=cis_plot,
                   capsize=4,
                   error_kw={"elinewidth": 1.2, "ecolor": "black"})

        ax.set_xticks(x)
        ax.set_xticklabels([PATTERN_LABELS[p] for p in PATTERNS])
        ax.set_ylabel(kpi_label)
        ax.set_title(f"{kpi_label} by Configuration & Load Pattern\n{service}", fontweight="bold")
        ax.legend(ncol=3, loc="upper right", fontsize=8)

        save_fig(fig, out_dir, f"{fig_name}_{service.replace('-','_')}")


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH 4: Decomposition Table (Metric Effect / Engine Effect / Combined)
# ══════════════════════════════════════════════════════════════════════════════

def generate_decomposition_table(data: dict, out_dir: Path) -> str:
    """
    Computes and outputs the decomposition table as both a markdown file
    and a matplotlib table PNG.
    Metric Effect = H3 vs H1  (same engine, different metric)
    Engine Effect = K1 vs H3  (same metric, different engine)
    Combined      = K1 vs H1  (full upgrade)
    """
    def mean_p95(service, config, pattern):
        reps = data.get(service, {}).get(config, {}).get(pattern, {})
        vals = [r["k6"].get("p95_ms", np.nan) for r in reps.values()]
        vals = [v for v in vals if not np.isnan(v)]
        return np.mean(vals) if vals else np.nan

    rows = []
    header = ["Service", "Pattern", "H1 p95 (ms)", "H3 p95 (ms)", "K1 p95 (ms)",
              "Metric Effect", "Engine Effect", "Combined"]

    for service in SERVICES:
        for pattern in PATTERNS:
            h1 = mean_p95(service, "h1", pattern)
            h3 = mean_p95(service, "h3", pattern)
            k1 = mean_p95(service, "k1", pattern)

            def pct_change(new, old):
                if np.isnan(new) or np.isnan(old) or old == 0:
                    return "N/A"
                return f"{((new - old) / old) * 100:+.1f}%"

            rows.append([
                service,
                PATTERN_LABELS[pattern],
                f"{h1:.0f}" if not np.isnan(h1) else "N/A",
                f"{h3:.0f}" if not np.isnan(h3) else "N/A",
                f"{k1:.0f}" if not np.isnan(k1) else "N/A",
                pct_change(h3, h1),  # Metric Effect
                pct_change(k1, h3),  # Engine Effect
                pct_change(k1, h1),  # Combined
            ])

    # Save as markdown
    md_lines = ["# Decomposition Table: Metric Effect vs Engine Effect\n"]
    md_lines.append("| " + " | ".join(header) + " |")
    md_lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for row in rows:
        md_lines.append("| " + " | ".join(str(v) for v in row) + " |")

    md_path = out_dir / "fig4_decomposition_table.md"
    md_path.write_text("\n".join(md_lines))
    print(f"  ✅ Saved {md_path.name}")

    # Save as PNG table (if there's data)
    if not rows:
        return "\n".join(md_lines)

    apply_style()
    fig, ax = plt.subplots(figsize=(14, max(3, len(rows) * 0.55 + 1.5)))
    ax.axis("off")

    short_header = ["Service", "Pattern", "H1 (ms)", "H3 (ms)", "K1 (ms)",
                    "Metric\nEffect (H3-H1)", "Engine\nEffect (K1-H3)", "Combined\n(K1-H1)"]

    table = ax.table(
        cellText=[r for r in rows],
        colLabels=short_header,
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.6)

    # Color header
    for col in range(len(short_header)):
        table[0, col].set_facecolor("#37474F")
        table[0, col].set_text_props(color="white", fontweight="bold")

    # Color effect columns (green=improvement, red=degradation)
    for row_idx, row in enumerate(rows):
        for col_offset, col_idx in enumerate([5, 6, 7]):
            val = row[col_idx]
            cell = table[row_idx + 1, col_offset + 5]
            if val.startswith("-"):
                cell.set_facecolor("#C8E6C9")  # light green — improvement
            elif val.startswith("+"):
                cell.set_facecolor("#FFCDD2")  # light red — degradation

    ax.set_title("Decomposition Table: Metric Effect vs Engine Effect",
                 fontsize=11, fontweight="bold", pad=15)

    save_fig(fig, out_dir, "fig4_decomposition_table")
    return "\n".join(md_lines)


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH 5: CPU vs RPS Scatter (product-service exploratory diagnostic)
# ══════════════════════════════════════════════════════════════════════════════

def plot_cpu_vs_rps(data: dict, out_dir: Path, pattern: str = "spike"):
    """
    Scatterplot: x=RPS, y=CPU %
    Color encodes time for the exploratory product-service run.
    This is retained as a downstream-bottleneck diagnostic, not a core figure.
    """
    apply_style()
    service = "product-service"
    config = "b1"

    reps_dict = data.get(service, {}).get(config, {}).get(pattern, {})
    if not reps_dict:
        reps_dict = data.get(service, {}).get(config, {}).get("gradual", {})
        pattern = "gradual"
    if not reps_dict:
        print(f"  ⚠️  No data for CPU vs RPS scatter — skipping")
        return

    fig, ax = plt.subplots(figsize=(8, 5))

    all_rps, all_cpu, all_t = [], [], []
    for rep_data in reps_dict.values():
        rps_df = rep_data["rps"]
        cpu_df = rep_data["cpu"]
        if rps_df.empty or cpu_df.empty:
            continue
        # Join on nearest timestamp
        merged = pd.merge_asof(
            rps_df.sort_values("t"),
            cpu_df.rename(columns={"value": "cpu"}).sort_values("t"),
            on="t", direction="nearest", tolerance=30
        ).dropna()
        if merged.empty:
            continue
        all_rps.extend(merged["value"].tolist())
        all_cpu.extend(merged["cpu"].tolist())
        all_t.extend(merged["t"].tolist())

    if not all_rps:
        print(f"  ⚠️  No merged RPS/CPU data — skipping scatter")
        plt.close(fig)
        return

    sc = ax.scatter(all_rps, np.array(all_cpu) * 100,
                    c=all_t, cmap="plasma", s=25, alpha=0.7, zorder=5)
    cbar = plt.colorbar(sc, ax=ax)
    cbar.set_label("Time (seconds)")

    ax.set_xlabel("Incoming RPS")
    ax.set_ylabel("CPU Utilization (%)")
    ax.set_title(
        f"CPU Utilization vs Incoming RPS\n{service} — {PATTERN_LABELS[pattern]}\n"
        "(Exploratory diagnostic for dependency-limited behavior)",
        fontweight="bold"
    )

    save_fig(fig, out_dir, "fig5_cpu_vs_rps_product_service")


# ══════════════════════════════════════════════════════════════════════════════
# GRAPH 6: Pod Count Timeline (oscillating load — thrashing check)
# ══════════════════════════════════════════════════════════════════════════════

def plot_pod_timeline_oscillating(data: dict, service: str, out_dir: Path):
    """
    Step chart of pod count over time during oscillating load.
    4 configs overlaid. Background bands = high/low load phases.
    """
    apply_style()
    pattern = "oscillating"

    configs_present = [c for c in ["h1", "h2", "h3", "k1"]
                       if data.get(service, {}).get(c, {}).get(pattern)]
    if not configs_present:
        print(f"  ⚠️  No oscillating data for {service} — skipping pod timeline")
        return

    fig, ax = plt.subplots(figsize=(12, 5))

    for config in configs_present:
        reps_data = list(data[service][config][pattern].values())
        ts = avg_timeseries(reps_data, "replicas")
        if ts.empty:
            continue
        ax.step(ts["t"], ts["value"], color=CONFIG_COLORS[config],
                label=CONFIG_LABELS[config], lw=2, where="post")

    # Background shading: oscillating load phases
    # Warmup: 0-120s, then alternating 90s high/low
    warmup_end = 120
    phase_duration = 90 + 10  # 90s hold + 10s ramp
    ax.axvspan(0, warmup_end, alpha=0.08, color="gray", label="Warm-up")

    t = warmup_end
    high = True
    while t < 900:  # 15 min max
        end = min(t + phase_duration, 900)
        color = "#FF5252" if high else "#2196F3"
        ax.axvspan(t, end, alpha=0.08, color=color)
        high = not high
        t = end

    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.set_xlabel("Time (seconds from experiment start)")
    ax.set_ylabel("Active Pods")
    ax.set_title(f"Pod Scaling Timeline — Oscillating Load\n{service}", fontweight="bold")

    high_patch = mpatches.Patch(color="#FF5252", alpha=0.25, label="High Load Phase")
    low_patch  = mpatches.Patch(color="#2196F3", alpha=0.25, label="Low Load Phase")
    ax.legend(fontsize=8, loc="upper right")

    save_fig(fig, out_dir, f"fig6_pod_timeline_oscillating_{service.replace('-','_')}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Generate all thesis figures from experiment results.")
    parser.add_argument("--results-dir", default="experiment-results",
                        help="Path to experiment-results directory (default: ./experiment-results)")
    parser.add_argument("--out-dir",     default="thesis-figures",
                        help="Output directory for PNG files (default: ./thesis-figures)")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Parse data only; do not render graphs (validation mode)")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    out_dir     = Path(args.out_dir)

    if not results_dir.exists():
        print(f"❌ Results directory not found: {results_dir}")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📂 Results dir: {results_dir.resolve()}")
    print(f"📁 Output dir:  {out_dir.resolve()}\n")

    # Load all data
    print("⏳ Loading experiment data...")
    data = load_all_data(results_dir)

    # Report what we found
    total_reps = sum(
        len(data[s][c][p])
        for s in data for c in data[s] for p in data[s][c]
    )
    print(f"✅ Loaded {total_reps} rep directories\n")

    if args.dry_run:
        print("🔍 Dry-run mode — data validation only, no graphs rendered.")
        for service in CORE_SERVICES:
            for config in CONFIGS:
                for pattern in PATTERNS:
                    reps = data.get(service, {}).get(config, {}).get(pattern, {})
                    if reps:
                        k6 = [r["k6"] for r in reps.values()]
                        p95s = [k.get("p95_ms", float("nan")) for k in k6]
                        print(f"  {service}/{config}/{pattern}: {len(reps)} reps, "
                              f"p95 = {[f'{v:.0f}ms' if not np.isnan(v) else 'N/A' for v in p95s]}")
        return

    print("🎨 Rendering graphs...\n")

    # ── Figure 1: Scaling Timeline (all services × patterns) ──────────────
    print("📊 Figure 1: Annotated Scaling Timelines")
    for service in CORE_SERVICES:
        for pattern in PATTERNS:
            plot_scaling_timeline(data, service, pattern, out_dir)

    # ── Figure 2: Pareto Frontier ─────────────────────────────────────────
    print("\n📊 Figure 2: Pareto Frontier Scatterplots")
    for service in CORE_SERVICES:
        plot_pareto_frontier(data, service, out_dir)

    # ── Figure 3: Bar Charts with CI ──────────────────────────────────────
    print("\n📊 Figure 3: Bar Charts with 95% CI Error Bars")
    for service in CORE_SERVICES:
        plot_bar_charts(data, service, out_dir)

    # ── Figure 4: Decomposition Table ────────────────────────────────────
    print("\n📊 Figure 4: Decomposition Table")
    generate_decomposition_table(data, out_dir)

    # ── Figure 5: CPU vs RPS Scatter ──────────────────────────────────────
    print("\n📊 Figure 5: CPU vs RPS Scatter (I/O-bound proof)")
    plot_cpu_vs_rps(data, out_dir)

    # ── Figure 6: Pod Timeline (oscillating) ─────────────────────────────
    print("\n📊 Figure 6: Pod Count Timeline — Oscillating Load")
    for service in CORE_SERVICES:
        plot_pod_timeline_oscillating(data, service, out_dir)

    print(f"\n🎉 Done! All figures saved to ./{out_dir}/")
    print("   Use ./scripts/generate_thesis.sh for automatic venv handling.\n")


if __name__ == "__main__":
    main()
