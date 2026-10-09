#!/usr/bin/env python3
"""
Part 12 analyses of the open-loop campaign (thesis_blueprint/12-deviation-and-analysis-plan.md).

The plan was fixed in commit b7fa4d3 before reps 3-5 existed; the 2026-10-09 additions (O4 timing from the HPA's
lastScaleTime, the choice of test, and the exploratory session check) were written before this script ran.

Outcomes per run (KPI window = k6 t 120-540 s)
  O1  seconds over SLO        10 s bins whose p95 (failed requests = infinite) exceeds the SLO, x 10
  O2  error %                 requests not answered successfully (503 rejections, timeouts, other failures)
  O3  goodput                 successful requests per second
  O4  time to scale           onset -> first increase of the HPA's desired replicas (lastScaleTime);
                              onset -> first new pod Ready (pod watcher, exact lastTransitionTime)
  O5  resource use            Ready replica-seconds (pod watcher) and CPU core-seconds (Prometheus)

Analyses
  A1  median, min, max per cell (service x pattern x config)
  A2  H2 vs H3, H3 vs K1, H1 vs H2 per service x pattern on O1 and O2: exact two-sided rank-sum
      (Mann-Whitney) permutation test with midranks, Vargha-Delaney A12, Holm within each family of 3
  A3  share of the B1->B2 gap closed on O1 medians: (B1 - X) / (B1 - B2)
  A4  dispersion (range, MAD) of O1 and O2 per cell; CPU (H1, H2) vs request-rate (H3, K1) cells compared with
      the same exact test; anti-phase scale-downs (desired replicas decrease inside a peak window)
  S   exploratory session check (not pre-registered): reps 1-2 vs reps 3-5
  A5  resource use against O1 per service x pattern, non-dominated configs marked
  A6  mechanism figures (load, autoscaler reading, replicas) for selected runs

Run on Windows with the bundled interpreter (reads the campaign folder, writes only to --out):
  PYTHONUTF8=1 tools/python312/python.exe scripts/analyze_openloop_campaign.py
"""

import argparse
import csv
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PILOT_OPENLOOP_DIR", str(ROOT / "experiment-results-openloop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilot_openloop as po  # noqa: E402  (window statistics, raw-data cache, config)

SERVICES = po.SERVICES
PATTERNS = po.PATTERNS
CONFIGS = po.CONFIGS
AUTOSCALED = po.AUTOSCALED
SHORT = {"auth-service": "auth", "shipping-rate-service": "shipping"}
CONTRASTS = [("h2", "h3", "metric"), ("h3", "k1", "engine"), ("h1", "h2", "default vs tuned")]
SESSION_1 = (1, 2)            # reps 1-2: 2026-10-06 12:33 -> 10-07 13:31 UTC
SESSION_2 = (3, 4, 5)         # reps 3-5: 2026-10-07 14:32 -> 10-09 02:47 UTC (after an AKS stop and start)
PROM_STEP = 15.0              # query_range step used by the runner
RATE_WINDOW = 60.0            # rate(...[1m]) in the CPU export
SELECTED_RUNS = [             # A6: the three cells that failed G6, plus a request-rate contrast
    ("auth-service", "h2", "oscillating"),
    ("auth-service", "h3", "oscillating"),
    ("auth-service", "h1", "gradual"),
    ("shipping-rate-service", "h1", "oscillating"),
]


# ── parsing helpers ──────────────────────────────────────────────────────────

def iso_epoch(text):
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def quantity(value):
    """Kubernetes quantity ('15500m', '2', '1.5k') or number -> float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"([0-9.]+)([mkMG]?)", str(value))
    if not m:
        return None
    scale = {"": 1.0, "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9}[m.group(2)]
    return float(m.group(1)) * scale


def hpa_snapshots(run_dir, service):
    snaps = []
    path = run_dir / "hpa-timeline.jsonl"
    if not path.exists():
        return snaps
    for line in path.read_text(errors="ignore").splitlines():
        try:
            snap = json.loads(line)
        except json.JSONDecodeError:
            continue
        hpas = [h for h in snap.get("hpas", []) if service in h.get("name", "")]
        if not hpas:
            continue
        h = hpas[0]
        reading = None
        for m in h.get("metrics") or []:
            cur = (m.get("resource") or m.get("pods") or m.get("external") or m.get("object") or {}).get("current") or {}
            if "averageUtilization" in cur:
                reading = float(cur["averageUtilization"])
            else:
                reading = quantity(cur.get("averageValue", cur.get("value")))
        snaps.append({"ts": snap["ts"], "name": h.get("name"), "desired": h.get("desired"),
                      "current": h.get("current"), "last_scale": iso_epoch(h.get("last_scale")),
                      "reading": reading})
    return snaps


def scale_changes(snaps):
    """Changes of desired replicas, dated by the HPA's lastScaleTime (second resolution).

    A change is first visible in a snapshot; lastScaleTime in that snapshot dates it. If lastScaleTime is missing
    or older than the previous snapshot, the snapshot time is used and the change is flagged."""
    out = []
    for prev, cur in zip(snaps, snaps[1:]):
        if prev["desired"] is None or cur["desired"] is None or cur["desired"] == prev["desired"]:
            continue
        ls = cur["last_scale"]
        exact = ls is not None and ls >= prev["ts"] - 1.0
        out.append({"t": ls if exact else cur["ts"], "seen": cur["ts"], "from": prev["desired"],
                    "to": cur["desired"], "exact": exact})
    return out


def pod_records(run_dir):
    """Per pod: creation, node, and Ready intervals [start, end) from the ~6 s pod watcher.

    Start = the pod's exact Ready transition (lastTransitionTime); end = midpoint between the last snapshot showing it
    Ready and not terminating and the first that does not (a terminating pod is removed from the Service endpoints)."""
    path = run_dir / "pod-timeline.jsonl"
    snaps = []
    if path.exists():
        for line in path.read_text(errors="ignore").splitlines():
            try:
                snaps.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    pods = {}
    open_since = {}      # pod -> start of its current Ready interval
    last_serving = {}    # pod -> last snapshot time it was Ready and not terminating
    last_seen = {}       # pod -> last snapshot time it appeared at all
    for snap in snaps:
        ts = snap["ts"]
        seen = set()
        for p in snap.get("pods", []):
            name = p["name"]
            seen.add(name)
            rec = pods.setdefault(name, {"created": iso_epoch(p.get("created")), "node": p.get("node"),
                                         "intervals": []})
            serving = bool(p.get("ready")) and not p.get("deleting")
            if serving:
                if name not in open_since:
                    # Use the exact transition time when it falls after the previous sighting (or the pod is new).
                    rs = iso_epoch(p.get("ready_since"))
                    prev = last_seen.get(name)
                    open_since[name] = rs if rs is not None and (prev is None or rs >= prev - 1.0) else ts
                last_serving[name] = ts
            elif name in open_since:
                rec["intervals"].append((open_since.pop(name), (last_serving[name] + ts) / 2))
            last_seen[name] = ts
        for name in list(open_since):
            if name not in seen:
                pods[name]["intervals"].append((open_since.pop(name), (last_serving[name] + ts) / 2))
    end_ts = snaps[-1]["ts"] if snaps else None
    for name, since in open_since.items():
        pods[name]["intervals"].append((since, end_ts))
    return pods


def ready_seconds(pods, a, b):
    total = 0.0
    for rec in pods.values():
        for s, e in rec["intervals"]:
            lo, hi = max(s, a), min(e, b)
            if hi > lo:
                total += hi - lo
    return total


def ready_count(pods, t):
    return sum(1 for rec in pods.values() for s, e in rec["intervals"] if s <= t < e)


def cpu_core_seconds(run_dir, t_start):
    """Sum of the per-pod 1-minute CPU rate (15 s step) x 15 s. A rate[1m] sample at time t averages [t-60, t], so the
    samples are shifted by half the window (30 s) to cover the KPI window 120-540 s."""
    pods = po.per_pod(run_dir / "prom_cpu_usage.json")
    lo, hi = t_start + po.LOAD_WINDOW[0] + RATE_WINDOW / 2, t_start + po.LOAD_WINDOW[1] + RATE_WINDOW / 2
    by_ts = defaultdict(float)
    for series in pods.values():
        for t, v in series.items():
            if lo <= t < hi:
                by_ts[t] += v
    return sum(by_ts.values()) * PROM_STEP, len(by_ts)


# ── statistics ───────────────────────────────────────────────────────────────

def midranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def rank_sum_test(x, y):
    """Exact two-sided permutation test of the rank sum (Mann-Whitney) with midranks for ties.

    Counts every split of the pooled observations into groups of len(x) and len(y) whose rank sum lies at least as
    far from its mean as the observed one. Returns (U for x, p)."""
    n, N = len(x), len(x) + len(y)
    w = [int(round(2 * r)) for r in midranks(list(x) + list(y))]   # doubled midranks are integers
    obs, centre = sum(w[:n]), n * (N + 1)                          # doubled rank sum and its mean
    dp = [defaultdict(int) for _ in range(n + 1)]
    dp[0][0] = 1
    for wi in w:
        for k in range(n, 0, -1):
            for s, c in list(dp[k - 1].items()):
                dp[k][s + wi] += c
    total = math.comb(N, n)
    extreme = sum(c for s, c in dp[n].items() if abs(s - centre) >= abs(obs - centre))
    u = obs / 2 - n * (n + 1) / 2
    return u, extreme / total


def a12(x, y):
    """Vargha-Delaney A12: P(X > Y) + 0.5 P(X = Y)."""
    gt = sum(1 for a in x for b in y if a > b)
    eq = sum(1 for a in x for b in y if a == b)
    return (gt + 0.5 * eq) / (len(x) * len(y))


def holm(pvalues):
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted, running = [None] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvalues) - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def sign_test(worse, better):
    n, k = worse + better, min(worse, better)
    if n == 0:
        return None
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def med(values):
    vals = [v for v in values if v is not None]
    return float(np.median(vals)) if vals else None


def mad(values):
    m = med(values)
    return med([abs(v - m) for v in values]) if m is not None else None


# ── per-run outcomes ─────────────────────────────────────────────────────────

def analyze(run_dir, cfg):
    r = po.analyze_run(run_dir, cfg)
    meta = po.load_json(run_dir / "metadata.json") or {}
    service, config, pattern = r["service"], r["config"], r["pattern"]
    t_start = po.scenario_starts(run_dir / "k6-output.log")[f"openloop_{pattern}"]
    onset = t_start + po.ONSET
    w0, w1 = t_start + po.LOAD_WINDOW[0], t_start + po.LOAD_WINDOW[1]
    lw = r["load_window"]
    snaps = hpa_snapshots(run_dir, service)
    changes = scale_changes(snaps)
    pods = pod_records(run_dir)
    ups = [c for c in changes if c["to"] > c["from"]]
    downs = [c for c in changes if c["to"] < c["from"]]
    first_up = next((c for c in ups if c["t"] >= onset - 1.0), None)
    new_ready = sorted(s for rec in pods.values() if rec["created"] is not None and rec["created"] >= onset - 5
                       for s, _ in rec["intervals"][:1])
    peaks = [(t_start + a, t_start + b) for a, b in po.PEAK_WINDOWS[pattern]]
    anti = [c for c in downs if any(a <= c["t"] < b for a, b in peaks)]
    core_s, cpu_samples = cpu_core_seconds(run_dir, t_start)
    base = [(name, rec["node"]) for name, rec in pods.items() if any(s <= onset < e for s, e in rec["intervals"])]
    return {
        "service": service, "config": config, "pattern": pattern, "rep": r["rep"],
        "plan_position": r["plan_position"], "run_dir": run_dir.relative_to(po.PILOT_DIR).as_posix(),
        "t_start": t_start,
        "O1_slo_s": lw["slo_violation_s"], "O2_error_pct": lw["error_pct"], "O3_goodput_rps": lw["goodput_rps"],
        "timeout_pct": lw["timeout_pct"], "shed_pct": lw["shed_pct"], "requests": lw["requests"],
        "O4_first_up_s": (first_up["t"] - onset) if first_up else None,
        "O4_first_up_exact": first_up["exact"] if first_up else None,
        "O4_first_new_ready_s": (new_ready[0] - onset) if new_ready else None,
        "O5_replica_s": ready_seconds(pods, w0, w1),
        "O5_cpu_core_s": core_s, "cpu_samples": cpu_samples,
        "scale_ups_before_onset": sum(1 for c in ups if t_start <= c["t"] < onset - 1.0),
        "anti_phase_downs": len(anti),
        "anti_phase_times_s": [round(c["t"] - t_start, 1) for c in anti],
        "inexact_scale_times": sum(1 for c in changes if not c["exact"]),
        "scale_changes": [{"t_k6": round(c["t"] - t_start, 1), "from": c["from"], "to": c["to"]} for c in changes],
        "base_pods": base, "hpa_name": snaps[0]["name"] if snaps else None,
        "raw_md5_verified": (meta.get("raw_results") or {}).get("verified"),
    }


# ── analyses ─────────────────────────────────────────────────────────────────

OUTCOMES = [("O1_slo_s", "O1 s over SLO", 0), ("O2_error_pct", "O2 error %", 2), ("O3_goodput_rps", "O3 goodput req/s", 2),
            ("O4_first_up_s", "O4 first scale-up s", 1), ("O4_first_new_ready_s", "O4 first new pod Ready s", 1),
            ("O5_replica_s", "O5 Ready replica-s", 0), ("O5_cpu_core_s", "O5 CPU core-s", 1)]


def run_analyses(runs):
    cells = defaultdict(dict)
    for r in runs:
        cells[(r["service"], r["pattern"], r["config"])][r["rep"]] = r
    res = {"A1": {}, "A2": [], "A3": {}, "A4": {"dispersion": {}, "cpu_vs_rate": [], "anti_phase": {}},
           "S": {}, "A5": {}}

    # A1
    for key, reps in cells.items():
        out = {}
        for field, _, _ in OUTCOMES:
            vals = [reps[k][field] for k in sorted(reps)]
            present = [v for v in vals if v is not None]
            out[field] = {"values": vals, "median": med(present), "min": min(present) if present else None,
                          "max": max(present) if present else None, "missing": len(vals) - len(present)}
        res["A1"]["|".join(key)] = out

    # A2
    for service in SERVICES:
        for pattern in PATTERNS:
            for field in ("O1_slo_s", "O2_error_pct"):
                family = []
                for a, b, label in CONTRASTS:
                    xa = [cells[(service, pattern, a)][k][field] for k in sorted(cells[(service, pattern, a)])]
                    xb = [cells[(service, pattern, b)][k][field] for k in sorted(cells[(service, pattern, b)])]
                    u, p = rank_sum_test(xa, xb)
                    family.append({"service": service, "pattern": pattern, "outcome": field, "contrast": f"{a} vs {b}",
                                   "factor": label, "median_a": med(xa), "median_b": med(xb), "U_a": u, "p": p,
                                   "A12_a_gt_b": a12(xa, xb)})
                for row, adj in zip(family, holm([f["p"] for f in family])):
                    row["p_holm"] = adj
                    row["significant_0.05"] = adj <= 0.05
                res["A2"].extend(family)

    # A3
    for service in SERVICES:
        for pattern in PATTERNS:
            b1 = med([r["O1_slo_s"] for r in cells[(service, pattern, "b1")].values()])
            b2 = med([r["O1_slo_s"] for r in cells[(service, pattern, "b2")].values()])
            row = {"B1": b1, "B2": b2}
            for c in AUTOSCALED:
                x = med([r["O1_slo_s"] for r in cells[(service, pattern, c)].values()])
                row[c] = {"median": x, "gap_closed": (b1 - x) / (b1 - b2) if b1 != b2 else None}
            res["A3"][f"{service}|{pattern}"] = row

    # A4 dispersion and CPU vs request-rate
    disp = {}
    for key, reps in cells.items():
        if key[2] not in AUTOSCALED:
            continue
        d = {}
        for field in ("O1_slo_s", "O2_error_pct"):
            vals = [reps[k][field] for k in sorted(reps)]
            d[field] = {"range": max(vals) - min(vals), "mad": mad(vals)}
        disp["|".join(key)] = d
    res["A4"]["dispersion"] = disp
    for field in ("O1_slo_s", "O2_error_pct"):
        for stat in ("range", "mad"):
            cpu = [v[field][stat] for k, v in disp.items() if k.split("|")[2] in ("h1", "h2")]
            rr = [v[field][stat] for k, v in disp.items() if k.split("|")[2] in ("h3", "k1")]
            u, p = rank_sum_test(cpu, rr)
            res["A4"]["cpu_vs_rate"].append({"outcome": field, "dispersion": stat, "n_cpu": len(cpu), "n_rate": len(rr),
                                             "median_cpu": med(cpu), "median_rate": med(rr), "U_cpu": u, "p": p,
                                             "A12_cpu_gt_rate": a12(cpu, rr)})
    for key, reps in cells.items():
        if key[2] in AUTOSCALED:
            res["A4"]["anti_phase"]["|".join(key)] = [reps[k]["anti_phase_downs"] for k in sorted(reps)]

    # Exploratory session check
    s = {"cells": {}, "sign_tests": {}, "within_session_dispersion": {}, "base_pod_nodes": {}}
    for key, reps in cells.items():
        row = {}
        for field in ("O1_slo_s", "O2_error_pct"):
            m1 = med([reps[k][field] for k in SESSION_1])
            m2 = med([reps[k][field] for k in SESSION_2])
            row[field] = {"session1_median": m1, "session2_median": m2, "difference": m1 - m2}
        s["cells"]["|".join(key)] = row
    for group, configs in (("B1/B2", ("b1", "b2")), ("autoscaled", tuple(AUTOSCALED))):
        for field in ("O1_slo_s", "O2_error_pct"):
            diffs = [v[field]["difference"] for k, v in s["cells"].items() if k.split("|")[2] in configs]
            worse, better = sum(1 for d in diffs if d > 0), sum(1 for d in diffs if d < 0)
            s["sign_tests"][f"{group}|{field}"] = {"cells": len(diffs), "session1_worse": worse,
                                                    "session1_better": better, "ties": len(diffs) - worse - better,
                                                    "p_two_sided": sign_test(worse, better)}
    for key, reps in cells.items():
        if key[2] not in AUTOSCALED:
            continue
        row = {}
        for field in ("O1_slo_s", "O2_error_pct"):
            m1 = med([reps[k][field] for k in SESSION_1])
            m2 = med([reps[k][field] for k in SESSION_2])
            resid = [reps[k][field] - (m1 if k in SESSION_1 else m2) for k in sorted(reps)]
            row[field] = {"range_within": max(resid) - min(resid), "mad_within": mad(resid),
                          "range_all": disp["|".join(key)][field]["range"], "mad_all": disp["|".join(key)][field]["mad"]}
        s["within_session_dispersion"]["|".join(key)] = row
    for service in SERVICES:
        for session, reps_ in (("session1", SESSION_1), ("session2", SESSION_2)):
            nodes = defaultdict(int)
            names = defaultdict(int)
            for r in runs:
                if r["service"] == service and r["rep"] in reps_:
                    for name, node in r["base_pods"]:
                        nodes[node] += 1
                        names[name] += 1
            s["base_pod_nodes"][f"{service}|{session}"] = {"nodes": dict(nodes), "pods": dict(names)}
    res["S"] = s

    # A5
    for service in SERVICES:
        for pattern in PATTERNS:
            pts = {}
            for c in CONFIGS:
                reps = cells[(service, pattern, c)]
                pts[c] = {"O1": med([r["O1_slo_s"] for r in reps.values()]),
                          "replica_s": med([r["O5_replica_s"] for r in reps.values()]),
                          "cpu_core_s": med([r["O5_cpu_core_s"] for r in reps.values()])}
            front = {}
            for res_key in ("replica_s", "cpu_core_s"):
                front[res_key] = sorted(c for c in CONFIGS if not any(
                    pts[o]["O1"] <= pts[c]["O1"] and pts[o][res_key] <= pts[c][res_key]
                    and (pts[o]["O1"] < pts[c]["O1"] or pts[o][res_key] < pts[c][res_key]) for o in CONFIGS))
            res["A5"][f"{service}|{pattern}"] = {"points": pts, "non_dominated": front}
    return res


# ── report ───────────────────────────────────────────────────────────────────

def fmt(v, d=1):
    if v is None:
        return "–"
    if isinstance(v, float) and math.isinf(v):
        return "inf"
    return f"{v:.{d}f}"


def write_report(runs, res, out_dir):
    L = []
    L.append("# Part 12 analyses — open-loop campaign (180 runs)\n")
    L.append("Generated by `scripts/analyze_openloop_campaign.py` from `experiment-results-openloop/`. Plan: "
             "`thesis_blueprint/12-deviation-and-analysis-plan.md`. KPI window k6 t 120–540 s; onset k6 t 120 s. "
             "Cells are service × pattern × config, 5 reps each.\n")
    flags = sum(r["inexact_scale_times"] for r in runs)
    pre = sum(r["scale_ups_before_onset"] for r in runs)
    L.append(f"Checks: {len(runs)} runs; scale changes without a usable `lastScaleTime` (snapshot time used): {flags}; "
             f"scale-ups before onset: {pre}; CPU samples per run in the window: "
             f"{min(r['cpu_samples'] for r in runs)}–{max(r['cpu_samples'] for r in runs)}.\n")

    L.append("## A1 — median [min–max] per cell\n")
    for service in SERVICES:
        for pattern in PATTERNS:
            L.append(f"\n### {SHORT[service]} · {pattern}\n")
            L.append("| Config | " + " | ".join(lbl for _, lbl, _ in OUTCOMES) + " |")
            L.append("|---|" + "---|" * len(OUTCOMES))
            for c in CONFIGS:
                a = res["A1"][f"{service}|{pattern}|{c}"]
                cols = []
                for field, _, d in OUTCOMES:
                    x = a[field]
                    if x["median"] is None:
                        cols.append("–")
                    else:
                        miss = f" ({x['missing']} none)" if x["missing"] else ""
                        cols.append(f"{fmt(x['median'], d)} [{fmt(x['min'], d)}–{fmt(x['max'], d)}]{miss}")
                L.append(f"| {c.upper()} | " + " | ".join(cols) + " |")

    L.append("\n## A2 — planned contrasts (exact rank-sum test, A12, Holm within each family of 3)\n")
    L.append("A12 = probability that a run of the first config has a higher value than a run of the second "
             "(higher O1/O2 = worse). 5 vs 5: smallest two-sided p = 0.0079.\n")
    L.append("| Service | Pattern | Outcome | Contrast | Medians | U | p | p (Holm) | A12 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for row in res["A2"]:
        sig = " **sig.**" if row["significant_0.05"] else ""
        d = 0 if row["outcome"] == "O1_slo_s" else 2
        L.append(f"| {SHORT[row['service']]} | {row['pattern']} | {row['outcome'].split('_')[0]} | "
                 f"{row['contrast'].upper()} ({row['factor']}) | {fmt(row['median_a'], d)} vs {fmt(row['median_b'], d)} | "
                 f"{fmt(row['U_a'], 1)} | {row['p']:.4f} | {row['p_holm']:.4f}{sig} | {row['A12_a_gt_b']:.2f} |")

    L.append("\n## A3 — share of the B1→B2 gap closed (O1 medians)\n")
    L.append("| Service | Pattern | B1 | B2 | H1 | H2 | H3 | K1 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for key, row in res["A3"].items():
        service, pattern = key.split("|")
        cols = [f"{fmt(row[c]['median'], 0)} s → "
                + (f"{fmt(100 * row[c]['gap_closed'], 1)}%" if row[c]["gap_closed"] is not None else "–")
                for c in AUTOSCALED]
        L.append(f"| {SHORT[service]} | {pattern} | {fmt(row['B1'], 0)} | {fmt(row['B2'], 0)} | " + " | ".join(cols) + " |")

    L.append("\n## A4 — repeatability\n")
    L.append("Dispersion over the 5 reps (range / MAD):\n")
    L.append("| Service | Pattern | Config | O1 range | O1 MAD | O2 range | O2 MAD | Anti-phase scale-downs per rep |")
    L.append("|---|---|---|---|---|---|---|---|")
    for service in SERVICES:
        for pattern in PATTERNS:
            for c in AUTOSCALED:
                k = f"{service}|{pattern}|{c}"
                d = res["A4"]["dispersion"][k]
                L.append(f"| {SHORT[service]} | {pattern} | {c.upper()} | {fmt(d['O1_slo_s']['range'], 0)} | "
                         f"{fmt(d['O1_slo_s']['mad'], 0)} | {fmt(d['O2_error_pct']['range'], 2)} | "
                         f"{fmt(d['O2_error_pct']['mad'], 2)} | {res['A4']['anti_phase'][k]} |")
    L.append("\nCPU-based (H1, H2; 12 cells) vs request-rate (H3, K1; 12 cells), exact rank-sum test on the per-cell "
             "dispersions (four tests, reported without correction):\n")
    L.append("| Outcome | Dispersion | Median CPU | Median request-rate | U (CPU) | p | A12 (CPU > rate) |")
    L.append("|---|---|---|---|---|---|---|")
    for row in res["A4"]["cpu_vs_rate"]:
        d = 0 if row["outcome"] == "O1_slo_s" else 2
        L.append(f"| {row['outcome'].split('_')[0]} | {row['dispersion']} | {fmt(row['median_cpu'], d)} | "
                 f"{fmt(row['median_rate'], d)} | {fmt(row['U_cpu'], 1)} | {row['p']:.4f} | {row['A12_cpu_gt_rate']:.2f} |")
    per_cfg = defaultdict(lambda: [0, 0])
    for k, counts in res["A4"]["anti_phase"].items():
        c = k.split("|")[2]
        per_cfg[c][0] += sum(counts)
        per_cfg[c][1] += sum(1 for x in counts if x > 0)
    L.append("\nAnti-phase scale-downs (desired replicas decreased inside a peak window), all 30 runs per config: " +
             "; ".join(f"{c.upper()} {per_cfg[c][0]} in {per_cfg[c][1]} runs" for c in AUTOSCALED) + ".\n")

    S = res["S"]
    L.append("\n## Exploratory session check (not pre-registered) — reps 1–2 vs reps 3–5\n")
    L.append("| Group | Outcome | Cells | Session 1 worse | Session 1 better | Ties | Sign test p (two-sided) |")
    L.append("|---|---|---|---|---|---|---|")
    for k, v in S["sign_tests"].items():
        group, field = k.split("|")
        L.append(f"| {group} | {field.split('_')[0]} | {v['cells']} | {v['session1_worse']} | {v['session1_better']} | "
                 f"{v['ties']} | {fmt(v['p_two_sided'], 4)} |")
    L.append("\nPer cell (session 1 median / session 2 median):\n")
    L.append("| Service | Pattern | Config | O1 | O2 | O2 range all → within sessions |")
    L.append("|---|---|---|---|---|---|")
    for service in SERVICES:
        for pattern in PATTERNS:
            for c in CONFIGS:
                k = f"{service}|{pattern}|{c}"
                v = S["cells"][k]
                w = S["within_session_dispersion"].get(k)
                wtxt = (f"{fmt(w['O2_error_pct']['range_all'], 2)} → {fmt(w['O2_error_pct']['range_within'], 2)}"
                        if w else "–")
                L.append(f"| {SHORT[service]} | {pattern} | {c.upper()} | {fmt(v['O1_slo_s']['session1_median'], 0)} / "
                         f"{fmt(v['O1_slo_s']['session2_median'], 0)} | {fmt(v['O2_error_pct']['session1_median'], 2)} / "
                         f"{fmt(v['O2_error_pct']['session2_median'], 2)} | {wtxt} |")
    L.append("\nNode of the pod(s) serving at onset, per session (run counts):\n")
    for k, v in S["base_pod_nodes"].items():
        L.append(f"- {k}: nodes {v['nodes']}; pods {v['pods']}")

    L.append("\n## A5 — resource use against O1 (cell medians; non-dominated configs)\n")
    L.append("| Service | Pattern | Non-dominated (replica-s) | Non-dominated (CPU core-s) | Medians: config O1 s / replica-s / core-s |")
    L.append("|---|---|---|---|---|")
    for k, v in res["A5"].items():
        service, pattern = k.split("|")
        pts = "; ".join(f"{c.upper()} {fmt(p['O1'], 0)}/{fmt(p['replica_s'], 0)}/{fmt(p['cpu_core_s'], 1)}"
                        for c, p in v["points"].items())
        L.append(f"| {SHORT[service]} | {pattern} | {', '.join(c.upper() for c in v['non_dominated']['replica_s'])} | "
                 f"{', '.join(c.upper() for c in v['non_dominated']['cpu_core_s'])} | {pts} |")
    (out_dir / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ── figures ──────────────────────────────────────────────────────────────────

COLORS = {"b1": "#7f7f7f", "b2": "#2b2b2b", "h1": "#1f77b4", "h2": "#17becf", "h3": "#ff7f0e", "k1": "#2ca02c"}


def figures(runs, res, cfg, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    cells = defaultdict(dict)
    for r in runs:
        cells[(r["service"], r["pattern"], r["config"])][r["rep"]] = r

    # A1 overview: O1 per run
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), sharey="row")
    for i, service in enumerate(SERVICES):
        for j, pattern in enumerate(PATTERNS):
            ax = axes[i][j]
            for x, c in enumerate(CONFIGS):
                vals = [cells[(service, pattern, c)][k]["O1_slo_s"] for k in sorted(cells[(service, pattern, c)])]
                jitter = np.linspace(-0.18, 0.18, len(vals))
                ax.scatter(x + jitter, vals, color=COLORS[c], s=22, zorder=3)
                ax.hlines(np.median(vals), x - 0.3, x + 0.3, color=COLORS[c], lw=2)
            ax.set_xticks(range(len(CONFIGS)), [c.upper() for c in CONFIGS])
            ax.set_title(f"{SHORT[service]} · {pattern}")
            ax.grid(axis="y", alpha=0.3)
            if j == 0:
                ax.set_ylabel("O1 seconds over SLO (120–540 s)")
    fig.suptitle("O1 per run (dots) and cell median (bar), 5 reps per cell")
    fig.tight_layout()
    fig.savefig(fig_dir / "a1_o1_per_run.png", dpi=130)
    plt.close(fig)

    # A5 Pareto views
    for res_key, label in (("replica_s", "Ready replica-seconds"), ("cpu_core_s", "CPU core-seconds")):
        fig, axes = plt.subplots(2, 3, figsize=(13, 7))
        for i, service in enumerate(SERVICES):
            for j, pattern in enumerate(PATTERNS):
                ax = axes[i][j]
                v = res["A5"][f"{service}|{pattern}"]
                offsets = {"b1": (5, 4), "b2": (5, 4), "h1": (5, 4), "h2": (5, 4), "h3": (5, -11), "k1": (-14, 6)}
                for c, p in v["points"].items():
                    nd = c in v["non_dominated"][res_key]
                    ax.scatter(p[res_key], p["O1"], color=COLORS[c], s=60 if nd else 30,
                               edgecolor="black" if nd else "none", zorder=3)
                    ax.annotate(c.upper(), (p[res_key], p["O1"]), textcoords="offset points", xytext=offsets[c],
                                fontsize=8)
                ax.set_title(f"{SHORT[service]} · {pattern}")
                ax.set_xlabel(f"median {label} (KPI window)")
                ax.set_ylabel("median O1 s over SLO")
                ax.grid(alpha=0.3)
        fig.suptitle(f"A5 — resource use vs seconds over SLO (outlined = non-dominated, {label})")
        fig.tight_layout()
        fig.savefig(fig_dir / f"a5_pareto_{res_key}.png", dpi=130)
        plt.close(fig)

    # A6 mechanism figures
    for service, config, pattern in SELECTED_RUNS:
        fig, axes = plt.subplots(3, 2, figsize=(13, 8.5), sharex=True)
        for col, rep in enumerate((1, 2)):
            r = cells[(service, pattern, config)][rep]
            run_dir = po.PILOT_DIR / r["run_dir"]
            meta = po.load_json(run_dir / "metadata.json") or {}
            lp = meta.get("load_profile") or {}
            t0 = r["t_start"]
            raw = po.Raw.load(run_dir, meta["run_id"])
            sid = raw.scn_id(f"openloop_{pattern}")
            start = raw.e_end - raw.e_ms / 1000.0 - t0
            m = raw.e_scn == sid
            edges = np.arange(0, 721, 10)
            ok = np.histogram(start[m & raw.e_ok], edges)[0] / 10
            bad = np.histogram(start[m & ~raw.e_ok], edges)[0] / 10
            ax = axes[0][col]
            sched_t, sched_r, t, rate = [0.0], [float(lp.get("base_rate"))], 0.0, float(lp.get("base_rate"))
            for dur, target in po.rate_stages(pattern, lp.get("base_rate"), lp.get("peak_rate")):
                t += dur
                sched_t.append(t)
                sched_r.append(float(target))
            ax.plot(sched_t, sched_r, color="black", lw=1, label="scheduled req/s")
            ax.bar(edges[:-1], ok, width=10, align="edge", color="#2ca02c", alpha=0.6, label="succeeded req/s")
            ax.bar(edges[:-1], bad, width=10, align="edge", bottom=ok, color="#d62728", alpha=0.6, label="failed req/s")
            ax.set_title(f"{SHORT[service]} {config.upper()} {pattern} rep {rep}: O1 {fmt(r['O1_slo_s'], 0)} s, "
                         f"errors {fmt(r['O2_error_pct'], 2)}%")
            ax.set_ylabel("req/s")
            snaps = hpa_snapshots(run_dir, service)
            ts = [s["ts"] - t0 for s in snaps]
            ax = axes[1][col]
            ax.step(ts, [s["reading"] for s in snaps], where="post", color=COLORS[config], label="HPA metric reading")
            target = {"h1": 80, "h2": 50}.get(config)
            if target is None:
                target = 5 if service == "auth-service" else 15
            ax.axhline(target, color="grey", ls="--", lw=1, label=f"target {target}")
            ax.set_ylabel("CPU % of request" if config in ("h1", "h2") else "req/s per pod")
            ax = axes[2][col]
            ax.step(ts, [s["desired"] for s in snaps], where="post", color="#9467bd", label="desired")
            pods = pod_records(run_dir)
            grid = np.arange(0, 720, 1.0)
            ax.plot(grid, [ready_count(pods, t0 + g) for g in grid], color="black", lw=1, label="Ready pods")
            ax.set_ylabel("replicas")
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            ax.set_xlabel("k6 time (s)")
            for a, b in po.PEAK_WINDOWS[pattern]:
                for row in range(3):
                    axes[row][col].axvspan(a, b, color="#ffdd99", alpha=0.35, lw=0)
            for row in range(3):
                axes[row][col].set_xlim(60, 660)
                axes[row][col].grid(alpha=0.3)
        for row in range(3):
            axes[row][0].legend(loc="upper left", fontsize=7)
        fig.suptitle("A6 — load, autoscaler reading and replicas (shaded: peak windows)")
        fig.tight_layout()
        fig.savefig(fig_dir / f"a6_{SHORT[service]}_{config}_{pattern}.png", dpi=120)
        plt.close(fig)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", default=str(po.PILOT_DIR / "analysis" / "part12"))
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = po.load_config()
    runs = [analyze(d, cfg) for d in po.pilot_run_dirs()]
    if len(runs) != 180:
        print(f"warning: {len(runs)} runs found, expected 180", file=sys.stderr)
    res = run_analyses(runs)
    with (out_dir / "runs.csv").open("w", newline="", encoding="utf-8") as fh:
        cols = ["service", "pattern", "config", "rep", "plan_position", "O1_slo_s", "O2_error_pct", "O3_goodput_rps",
                "timeout_pct", "shed_pct", "requests", "O4_first_up_s", "O4_first_new_ready_s", "O5_replica_s",
                "O5_cpu_core_s", "anti_phase_downs", "scale_ups_before_onset", "inexact_scale_times", "run_dir"]
        w = csv.writer(fh)
        w.writerow(cols)
        for r in sorted(runs, key=lambda r: (r["service"], r["pattern"], r["config"], r["rep"])):
            w.writerow([round(r[c], 4) if isinstance(r[c], float) else r[c] for c in cols])
    (out_dir / "results.json").write_text(json.dumps({"runs": runs, "analyses": res}, indent=1, default=str),
                                          encoding="utf-8")
    write_report(runs, res, out_dir)
    if not args.no_figures:
        figures(runs, res, cfg, out_dir)
    print(f"{len(runs)} runs analysed -> {out_dir}")


if __name__ == "__main__":
    main()
