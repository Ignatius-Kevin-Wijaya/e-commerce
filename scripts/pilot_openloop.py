#!/usr/bin/env python3
"""
Open-loop pilot analysis + validation (experiment-results-pilot-openloop/).

Subcommands
  ladder   [DIR ...]   per-step table for calibration ladders (default: all)
  validate             per-run validity checks for pilot runs
  report               all pilot metrics -> analysis/summary.json + analysis/tables.md

Data sources per run
  k6-results.json.gz   raw per-request k6 samples (req_e2e_duration, http_req_*, dropped_iterations, vus)
  k6-output.log        k6 summary + SCENARIO_START line (wall-clock start of each scenario)
  pod-timeline.jsonl   5 s pod snapshots with exact Ready transition times
  k8s-events.txt       ScalingReplicaSet / SuccessfulRescale events
  prom_*.json          per-pod request rate, pod readiness, CPU, k6 resources

Definitions (fixed before any pilot data existed)
  * Request latency = req_e2e_duration: client wall-clock time per request,
    including the TCP connect that http_req_duration leaves out.
  * Requests are binned by START time (end time - latency).
  * Failed requests (status outside 200-399, incl. timeouts = status 0 at the
    request timeout) count as infinitely slow in every p95/p99/SLO statistic.
  * Load window = k6 t in [120 s, 540 s): excludes the 2 m warm-up and the
    3 m ramp-down. Spike onset = k6 t = 120 s.
  * SLO-violation seconds = 10 s bins in the load window whose p95 > SLO.
  * Per-pod check: during the peak, a pod Ready for >= 60 s whose mean share of
    the per-pod request rate or CPU (vs. the mean of such pods) is < 20%.

Run on Windows with the bundled interpreter:
  PYTHONUTF8=1 tools/python312/python.exe scripts/pilot_openloop.py report
"""

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import os

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = Path(os.environ.get("PILOT_OPENLOOP_DIR", ROOT / "experiment-results-pilot-openloop"))
CLOSED_DIR = ROOT / "experiment-results"
CACHE_DIR = PILOT_DIR / "analysis" / "cache"

SERVICES = ["auth-service", "shipping-rate-service"]
CONFIGS = ["b1", "b2", "h1", "h2", "h3", "k1"]
AUTOSCALED = ["h1", "h2", "h3", "k1"]
PATTERNS = ["gradual", "spike", "oscillating"]

# HPA condition reasons meaning the autoscaler could not read its metric.
METRIC_FAILURE_REASONS = {
    "FailedGetPodsMetric", "FailedGetExternalMetric", "FailedGetResourceMetric",
    "FailedGetObjectMetric", "FailedComputeMetricsReplicas",
}

# Robustness gate, fixed 2026-10-06 before any v2 data existed: replicate runs
# agree when their range is within 25% of the mean OR within one quantization
# step (two 10 s SLO bins; one error-% point).
GATE_REL = 0.25
GATE_FLOOR_SLO_S = 20.0
GATE_FLOOR_ERR_PTS = 1.0

LOAD_WINDOW = (120.0, 540.0)
ONSET = 120.0
PEAK_WINDOWS = {
    "spike": [(130.0, 540.0)],
    "gradual": [(420.0, 540.0)],
    "oscillating": [(130.0, 210.0), (310.0, 390.0), (490.0, 540.0)],
}
SLO_BIN = 10.0
POD_READY_MIN_AGE = 60.0
POD_SHARE_FLOOR = 0.20
LADDER_SKIP = 30.0           # seconds skipped at the start of each ladder step
INF = float("inf")

# k6 stage shapes (seconds, target) — mirrors openloop-common.js rateStages().
def rate_stages(pattern, base, peak):
    if pattern == "gradual":
        return [(120, base), (300, peak), (120, peak), (180, 0)]
    if pattern == "spike":
        return [(120, base), (10, peak), (410, peak), (180, 0)]
    if pattern == "oscillating":
        return [(120, base), (10, peak), (80, peak), (10, base), (80, base), (10, peak),
                (80, peak), (10, base), (80, base), (10, peak), (50, peak), (180, 0)]
    raise ValueError(pattern)


def offered_requests(pattern, base, peak, t0, t1):
    """Integral of the scheduled arrival rate over k6 time [t0, t1)."""
    total, t, rate = 0.0, 0.0, float(base)
    for duration, target in rate_stages(pattern, base, peak):
        a, b = t, t + duration
        lo, hi = max(a, t0), min(b, t1)
        if hi > lo:
            r_lo = rate + (target - rate) * (lo - a) / duration
            r_hi = rate + (target - rate) * (hi - a) / duration
            total += (r_lo + r_hi) / 2 * (hi - lo)
        t, rate = b, float(target)
    return total


# ── generic parsing ──────────────────────────────────────────────────────────

_SEC_CACHE = {}
_TZ_RE = re.compile(r"([+-])(\d\d):(\d\d)$")


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_time(text):
    """RFC3339 with up to ns precision -> epoch seconds (float)."""
    key = text[:19]
    base = _SEC_CACHE.get(key)
    if base is None:
        base = datetime.strptime(key, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        _SEC_CACHE[key] = base
    rest = text[19:]
    offset = 0.0
    if rest.endswith("Z"):
        rest = rest[:-1]
    else:
        m = _TZ_RE.search(rest)
        if m:
            sign = 1 if m.group(1) == "+" else -1
            offset = sign * (int(m.group(2)) * 3600 + int(m.group(3)) * 60)
            rest = rest[: m.start()]
    frac = float("0" + rest) if rest.startswith(".") else 0.0
    return base + frac - offset


def iso_epoch(text):
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def prom_series(path):
    """{label-tuple: (ts ndarray, value ndarray)} from a query_range export."""
    data = load_json(path) or {}
    out = []
    for s in (data.get("data") or {}).get("result", []):
        vals = s.get("values") or []
        ts = np.array([float(v[0]) for v in vals])
        ys = np.array([float(v[1]) if v[1] not in ("NaN", "+Inf", "-Inf") else np.nan for v in vals])
        out.append((s.get("metric") or {}, ts, ys))
    return out


def per_pod(path):
    """{pod: {ts: value}} summing duplicate series for the same pod."""
    pods = {}
    for metric, ts, ys in prom_series(path):
        pod = metric.get("pod")
        if not pod:
            continue
        d = pods.setdefault(pod, {})
        for t, y in zip(ts, ys):
            if np.isfinite(y):
                d[t] = d.get(t, 0.0) + y
    return pods


def scenario_starts(log_path):
    starts = {}
    try:
        for m in re.finditer(r"SCENARIO_START name=(\S+) start_ms=(\d+)", Path(log_path).read_text(errors="ignore")):
            starts.setdefault(m.group(1), int(m.group(2)) / 1000.0)
    except OSError:
        pass
    return starts


def pctl(values, q):
    """Linear-interpolated percentile; failures are +inf, so a percentile that
    reaches into them is reported as +inf (i.e. 'beyond the timeout')."""
    if len(values) == 0:
        return None
    arr = np.asarray(values, dtype=float)
    finite_max = np.max(arr[np.isfinite(arr)]) if np.isfinite(arr).any() else 0.0
    sentinel = max(finite_max, 1.0) * 1e6
    v = float(np.percentile(np.where(np.isfinite(arr), arr, sentinel), q))
    return INF if v > finite_max else v


def fmt_ms(v):
    if v is None:
        return "n/a"
    if v == INF:
        return "fail"
    return f"{v:.0f}"


def fmt(v, digits=1):
    if v is None:
        return "n/a"
    if isinstance(v, float) and v == INF:
        return "inf"
    return f"{v:.{digits}f}"


def jsonable(o):
    """Recursively convert numpy scalars and +/-inf (-> None) for json.dumps."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


# ── raw k6 data ──────────────────────────────────────────────────────────────

class Raw:
    """Per-request arrays from k6-results.json.gz (cached as .npz)."""

    FIELDS = ("e_end", "e_ms", "e_ok", "e_status", "e_scn",
              "h_end", "h_ms", "h_err", "h_scn",
              "d_t", "d_scn", "v_t", "v_val")

    def __init__(self, arrays, scenarios):
        self.__dict__.update(arrays)
        self.scenarios = scenarios

    @classmethod
    def load(cls, run_dir, cache_key):
        raw_path = run_dir / "k6-results.json.gz"
        if not raw_path.exists():
            return None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = CACHE_DIR / f"{cache_key}.npz"
        # Tie the cache to the exact raw file: run ids repeat across result dirs (pilot,
        # smoke, campaign) and mtimes do not survive copies or a git checkout. A key-only
        # check once served smoke data for two v1 pilot runs (found 2026-10-06).
        raw_md5 = file_md5(raw_path)
        if cache.exists():
            with np.load(cache, allow_pickle=False) as z:
                if "raw_md5" in z.files and z["raw_md5"].item() == raw_md5:
                    scenarios = [str(s) for s in z["scenarios"]]
                    return cls({k: z[k] for k in cls.FIELDS}, scenarios)

        scn_index = {}
        def scn(tags):
            name = tags.get("scenario") or ""
            if tags.get("group", "").startswith("::setup") or name in ("", "setup", "teardown"):
                return -1
            return scn_index.setdefault(name, len(scn_index))

        e_end, e_ms, e_ok, e_status, e_scn = [], [], [], [], []
        h_end, h_ms, h_err, h_scn = [], [], [], []
        d_t, d_scn, v_t, v_val = [], [], [], []
        wanted = {"req_e2e_duration", "http_req_duration", "dropped_iterations", "vus"}
        with gzip.open(raw_path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if 'Point"' not in line:
                    continue
                # k6 writes {"type":..,"data":{..},"metric":".."}: the name is last.
                i = line.rfind('"metric":')
                j = line.find('"', i + 9) if i >= 0 else -1
                if j < 0 or line[j + 1: line.find('"', j + 1)] not in wanted:
                    continue
                try:
                    point = json.loads(line)
                except json.JSONDecodeError:
                    continue
                metric = point["metric"]
                data = point["data"]
                tags = data.get("tags") or {}
                t = parse_time(data["time"])
                value = float(data["value"])
                if metric == "req_e2e_duration":
                    s = scn(tags)
                    if s < 0:
                        continue
                    status = int(tags.get("status", "0") or 0)
                    e_end.append(t); e_ms.append(value); e_status.append(status)
                    e_ok.append(200 <= status < 400); e_scn.append(s)
                elif metric == "http_req_duration":
                    s = scn(tags)
                    if s < 0:
                        continue
                    h_end.append(t); h_ms.append(value)
                    h_err.append(int(tags.get("error_code", "0") or 0)); h_scn.append(s)
                elif metric == "dropped_iterations":
                    d_t.append(t); d_scn.append(scn(tags))
                elif metric == "vus":
                    v_t.append(t); v_val.append(value)

        arrays = {
            "e_end": np.array(e_end), "e_ms": np.array(e_ms), "e_ok": np.array(e_ok, dtype=bool),
            "e_status": np.array(e_status, dtype=int), "e_scn": np.array(e_scn, dtype=int),
            "h_end": np.array(h_end), "h_ms": np.array(h_ms), "h_err": np.array(h_err, dtype=int),
            "h_scn": np.array(h_scn, dtype=int),
            "d_t": np.array(d_t), "d_scn": np.array(d_scn, dtype=int),
            "v_t": np.array(v_t), "v_val": np.array(v_val),
        }
        scenarios = [None] * len(scn_index)
        for name, i in scn_index.items():
            scenarios[i] = name
        np.savez_compressed(cache, scenarios=np.array(scenarios, dtype=str), raw_md5=np.array(raw_md5), **arrays)
        return cls(arrays, scenarios)

    def scn_id(self, name):
        return self.scenarios.index(name) if name in self.scenarios else -2


def window_stats(raw, scn_id, t0, t1, timeout_ms, slo_ms=None, bin_s=SLO_BIN, rel0=0.0):
    """Statistics for requests STARTED in absolute time [t0, t1)."""
    start = raw.e_end - raw.e_ms / 1000.0
    m = (raw.e_scn == scn_id) & (start >= t0) & (start < t1)
    lat = np.where(raw.e_ok[m], raw.e_ms[m], INF)
    n = int(m.sum())
    ok = int(raw.e_ok[m].sum())
    timeouts = int(((raw.e_status[m] == 0) & (raw.e_ms[m] >= 0.98 * timeout_ms)).sum())
    hstart = raw.h_end - raw.h_ms / 1000.0
    hm = (raw.h_scn == scn_id) & (hstart >= t0) & (hstart < t1)
    dropped = int(((raw.d_scn == scn_id) & (raw.d_t >= t0) & (raw.d_t < t1)).sum())
    dur = t1 - t0
    out = {
        "requests": n,
        "ok": ok,
        "dropped": dropped,
        "attempted_rps": (n + dropped) / dur,
        "completed_rps": n / dur,
        "goodput_rps": ok / dur,
        "error_pct": 100.0 * (n - ok) / n if n else None,
        "timeout_pct": 100.0 * timeouts / n if n else None,
        # 503 = shed by admission control (v2); failures like any other.
        "shed_pct": 100.0 * int((raw.e_status[m] == 503).sum()) / n if n else None,
        "timeouts_e2e": timeouts,
        "timeouts_k6_code1050": int((raw.h_err[hm] == 1050).sum()),
        "p50_ms": pctl(lat, 50),
        "p95_ms": pctl(lat, 95),
        "p99_ms": pctl(lat, 99),
        "p95_ok_ms": pctl(raw.e_ms[m][raw.e_ok[m]], 95),
        "p95_http_req_duration_ms": pctl(raw.h_ms[hm], 95),
    }
    if slo_ms is not None:
        bins = []
        edges = np.arange(t0, t1 + 1e-9, bin_s)
        for a, b in zip(edges[:-1], edges[1:]):
            bm = m & (start >= a) & (start < b)
            p = pctl(np.where(raw.e_ok[bm], raw.e_ms[bm], INF), 95)
            bins.append({"t": a - rel0, "n": int(bm.sum()), "p95": p, "violated": p is None or p > slo_ms})
        violated = [b for b in bins if b["violated"]]
        out["slo_bins"] = bins
        out["slo_violation_s"] = len(violated) * bin_s
        out["last_violation_end_s"] = (max(b["t"] for b in violated) + bin_s) if violated else 0.0
    return out


# ── cluster-side data ────────────────────────────────────────────────────────

def read_events(run_dir):
    events = []
    path = run_dir / "k8s-events.txt"
    if not path.exists():
        return events
    for line in path.read_text(errors="ignore").splitlines()[1:]:
        parts = line.split("\t", 4)
        if len(parts) < 5:
            continue
        ts, etype, reason, obj, msg = parts
        epoch = iso_epoch(ts)
        if epoch is not None:
            events.append({"t": epoch, "reason": reason, "object": obj, "message": msg})
    return events


def pod_ready_times(run_dir):
    """{pod: {'created': epoch, 'ready': epoch|None, 'gone': last-seen epoch}} from the watcher."""
    pods = {}
    path = run_dir / "pod-timeline.jsonl"
    if not path.exists():
        return pods
    for line in path.read_text(errors="ignore").splitlines():
        try:
            snap = json.loads(line)
        except json.JSONDecodeError:
            continue
        for p in snap.get("pods", []):
            rec = pods.setdefault(p["name"], {"created": iso_epoch(p.get("created")), "ready": None,
                                              "first_seen": snap["ts"], "last_seen": snap["ts"],
                                              "deleting": None})
            rec["last_seen"] = snap["ts"]
            if p.get("ready") and p.get("ready_since") and rec["ready"] is None:
                rec["ready"] = iso_epoch(p["ready_since"])
            if p.get("deleting") and rec["deleting"] is None:
                rec["deleting"] = iso_epoch(p["deleting"])
    return pods


def ready_count_at(pods, t):
    return sum(1 for p in pods.values()
               if p["ready"] is not None and p["ready"] <= t
               and (p["deleting"] is None or p["deleting"] > t) and p["last_seen"] >= t - 10)


def scaling_timeline(run_dir, service, onset, peak_end):
    events = read_events(run_dir)
    pods = pod_ready_times(run_dir)
    ups = [e for e in events if e["reason"] == "ScalingReplicaSet" and "Scaled up" in e["message"]
           and e["object"] == f"deployment/{service}"]
    rescales = [e for e in events if e["reason"] == "SuccessfulRescale"]
    first_up = next((e for e in ups if e["t"] >= onset - 1), None)
    first_rescale = next((e for e in rescales if e["t"] >= onset - 1), None)
    new_ready = sorted(p["ready"] for p in pods.values()
                       if p["ready"] is not None and p["created"] is not None and p["created"] >= onset - 5)
    sample_ts = np.arange(onset, peak_end, 5.0)
    counts = [ready_count_at(pods, t) for t in sample_ts] if pods else []
    return {
        "scale_ups_before_onset": len([e for e in ups if e["t"] < onset - 1]),
        "ready_at_onset": ready_count_at(pods, onset) if pods else None,
        "t_first_scale_up_s": (first_up["t"] - onset) if first_up else None,
        "first_scale_up_msg": first_up["message"] if first_up else None,
        "t_first_hpa_rescale_s": (first_rescale["t"] - onset) if first_rescale else None,
        "t_first_new_ready_s": (new_ready[0] - onset) if new_ready else None,
        "max_ready_in_peak": max(counts) if counts else None,
        "t_reach_max_ready_s": (float(sample_ts[counts.index(max(counts))] - onset) if counts else None),
        "scale_up_events": [{"t_rel": round(e["t"] - onset, 1), "msg": e["message"]} for e in ups],
    }


def pod_distribution(run_dir, service, windows):
    """Per-pod share of request rate and CPU during the peak, Ready >= 60 s pods only."""
    ready = pod_ready_times(run_dir)
    rates = per_pod(run_dir / "prom_pod_request_rate.json")
    cpu = per_pod(run_dir / "prom_cpu_usage.json")
    prom_ready = per_pod(run_dir / "prom_pod_ready.json")

    def ready_since(pod):
        if pod in ready and ready[pod]["ready"] is not None:
            return ready[pod]["ready"]
        series = prom_ready.get(pod, {})
        ts = sorted(t for t, v in series.items() if v >= 1)
        return ts[0] if ts else None

    def eligible(pod, t):
        rs = ready_since(pod)
        if rs is None or rs > t - POD_READY_MIN_AGE:
            return False
        rec = ready.get(pod)
        if rec and ((rec["deleting"] is not None and rec["deleting"] <= t) or rec["last_seen"] < t - 10):
            return False
        return True

    result = {}
    for label, series in (("rate", rates), ("cpu", cpu)):
        shares = {}
        timestamps = sorted({t for s in series.values() for t in s})
        for t in timestamps:
            if not any(a <= t < b for a, b in windows):
                continue
            pods_t = [p for p in series if t in series[p] and eligible(p, t)]
            if len(pods_t) < 2:
                continue
            mean = sum(series[p][t] for p in pods_t) / len(pods_t)
            if mean <= 0:
                continue
            for p in pods_t:
                shares.setdefault(p, []).append(series[p][t] / mean)
        result[label] = {p: {"mean_share": float(np.mean(v)), "min_share": float(np.min(v)), "samples": len(v)}
                         for p, v in shares.items()}
    flagged = sorted({p for label in ("rate", "cpu") for p, s in result[label].items()
                      if s["mean_share"] < POD_SHARE_FLOOR})
    # A pod too overloaded to answer Prometheus scrapes has CPU samples but no
    # request-rate samples, so it would silently drop out of the rate shares.
    cpu_ts = {p: [t for t in s if any(a <= t < b for a, b in windows) and eligible(p, t)] for p, s in cpu.items()}
    unscraped = sorted(p for p, ts in cpu_ts.items()
                       if ts and sum(1 for t in ts if t not in rates.get(p, {})) >= max(2, len(ts) // 4))
    return {"per_pod": result, "flagged": flagged, "rate_unscraped": unscraped,
            "pods_checked": sorted(set(result["rate"]) | set(result["cpu"]))}


def run_health(run_dir, meta, service, t_start):
    """Start state, scrape health, metric failures, restarts and pre-auth use."""
    pods = pod_ready_times(run_dir)
    onset = t_start + ONSET
    end = t_start + 720.0

    def ready_at(pod, t):
        # The pod must still be seen by the 5 s watcher AFTER the sample and not
        # be deleted within the next 15 s scrape interval: a pod stopping for a
        # scale-down fails its last scrape for a reason that is not overload.
        rec = pods.get(pod)
        return bool(rec and rec["ready"] is not None and rec["ready"] <= t
                    and (rec["deleting"] is None or rec["deleting"] > t + 15) and rec["last_seen"] >= t)

    out = {
        "ready_at_start": ready_count_at(pods, t_start) if pods else None,
        "ready_at_onset": ready_count_at(pods, onset) if pods else None,
    }

    up_path = run_dir / "prom_up.json"
    out["up_available"] = up_path.exists()
    unscraped = {}
    if up_path.exists():
        for pod, series in per_pod(up_path).items():
            for t, v in series.items():
                if t_start <= t <= end and v < 1 and ready_at(pod, t):
                    unscraped[pod] = unscraped.get(pod, 0) + 1
    out["unscraped_while_ready"] = unscraped

    failures = []
    hpa_path = run_dir / "hpa-timeline.jsonl"
    if hpa_path.exists():
        for line in hpa_path.read_text(errors="ignore").splitlines():
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not (t_start + LOAD_WINDOW[0] <= snap["ts"] < t_start + LOAD_WINDOW[1]):
                continue
            for hpa in snap.get("hpas", []):
                if service not in hpa.get("name", ""):
                    continue
                for cond in hpa.get("conditions", []):
                    if cond.get("reason") in METRIC_FAILURE_REASONS:
                        failures.append((round(snap["ts"] - onset, 1), hpa["name"], cond["reason"]))
    out["metric_failures"] = failures

    restarts = []
    for e in read_events(run_dir):
        if not e["object"].startswith(f"pod/{service}-") or not (t_start - 60 <= e["t"] <= end):
            continue
        msg = e["message"].lower()
        if (e["reason"] == "Killing" and "liveness" in msg) or e["reason"] == "BackOff" or "back-off restarting" in msg:
            restarts.append((round(e["t"] - onset, 1), e["object"], e["message"][:100]))
    out["restarts"] = restarts

    pre = meta.get("preauth_tokens") or {}
    log_path = run_dir / "k6-output.log"
    out["preauth_enabled"] = bool(pre.get("enabled"))
    out["preauth_used"] = log_path.exists() and "PREAUTH_USED tokens=" in log_path.read_text(errors="ignore")
    out["max_inflight"] = (meta.get("service_overrides") or {}).get("max_inflight_requests") or 0
    return out


def k6_resources(run_dir, t0, t1, limits):
    def window_max(path, agg=max):
        vals = [v for s in per_pod(path).values() for t, v in s.items() if t0 <= t <= t1]
        return agg(vals) if vals else None
    cpu_limit = limits[2] if limits else None
    mem_limit = limits[3] if limits else None
    return {
        "cpu_max_cores": window_max(run_dir / "prom_k6_cpu.json"),
        "cpu_limit_cores": cpu_limit,
        "throttled_ratio_max": window_max(run_dir / "prom_k6_cpu_throttled_ratio.json"),
        "throttled_ratio_mean": window_max(run_dir / "prom_k6_cpu_throttled_ratio.json",
                                           agg=lambda v: float(np.mean(v))),
        "memory_max_bytes": window_max(run_dir / "prom_k6_memory.json"),
        "memory_limit_bytes": mem_limit,
    }


def parse_resources(text):
    def cores(s):
        return float(s[:-1]) / 1000 if s.endswith("m") else float(s)
    def mem(s):
        units = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3}
        for u, f in units.items():
            if s.endswith(u):
                return float(s[:-2]) * f
        return float(s)
    try:
        rc, rm, lc, lm = text.split(",")
        return cores(rc), mem(rm), cores(lc), mem(lm)
    except (AttributeError, ValueError):
        return None


def k6_log_facts(log_path):
    text = Path(log_path).read_text(errors="ignore") if Path(log_path).exists() else ""
    runs = re.findall(r"running \((\d+)m(\d+(?:\.\d+)?)s\), (\d+)/(\d+) VUs, (\d+) complete and (\d+) interrupted", text)
    last = runs[-1] if runs else None
    exit_code = re.search(r"\[openloop-wrapper\] k6 exit code (\d+)", text)
    return {
        "elapsed_s": (int(last[0]) * 60 + float(last[1])) if last else None,
        "complete": int(last[4]) if last else None,
        "interrupted": int(last[5]) if last else None,
        "completed_100pct": bool(re.search(r"✓ \[ 100% \]|\[ 100% \]", text)),
        "max_vus_header": int(m.group(1)) if (m := re.search(r"(\d+) max VUs", text)) else None,
        "exit_code": int(exit_code.group(1)) if exit_code else None,
        "summary_dropped": int(m.group(1)) if (m := re.search(r"dropped_iterations\.*: (\d+)", text)) else 0,
    }


def load_config():
    cfg = {}
    path = PILOT_DIR / "pilot-config.env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def slo_for(cfg, service):
    key = "AUTH_SLO_MS" if service == "auth-service" else "SHIPPING_SLO_MS"
    return float(cfg[key]) if cfg.get(key) else None


def timeout_ms_of(meta):
    text = (meta.get("load_profile") or {}).get("request_timeout") or "5s"
    return float(text.rstrip("s")) * 1000.0


# ── ladder ───────────────────────────────────────────────────────────────────

def analyze_ladder(run_dir):
    meta = load_json(run_dir / "metadata.json") or {}
    lp = meta.get("load_profile") or {}
    rates = lp.get("ladder_rates") or []
    step_s = float(re.sub(r"[^0-9]", "", lp.get("ladder_step") or "2m")) * (60 if (lp.get("ladder_step") or "2m").endswith("m") else 1)
    timeout_ms = timeout_ms_of(meta)
    raw = Raw.load(run_dir, f"ladder_{run_dir.name}")
    starts = scenario_starts(run_dir / "k6-output.log")
    cpu = per_pod(run_dir / "prom_cpu_usage.json")
    thr = per_pod(run_dir / "prom_cpu_throttled_ratio.json")
    carrier = per_pod(run_dir / "prom_carrier_cpu.json")
    up = per_pod(run_dir / "prom_up.json")                # v2 exports only
    inflight = per_pod(run_dir / "prom_inflight.json")
    limits = parse_resources(lp.get("k6_resources"))
    rows = []
    for i, rate in enumerate(rates):
        name = f"step{i + 1:02d}_{rate}rps"
        t_start = starts.get(name)
        if raw is None or t_start is None:
            rows.append({"step": name, "rate": rate, "missing": True})
            continue
        a, b = t_start + LADDER_SKIP, t_start + step_s
        st = window_stats(raw, raw.scn_id(name), a, b, timeout_ms)
        # Prometheus rate(...[1m]) at t covers [t-60, t]: use samples whose
        # whole window lies inside the step.
        def mean_in(series_by_pod, reducer=np.mean):
            per = []
            for s in series_by_pod.values():
                vals = [v for t, v in s.items() if t_start + 60 <= t <= b]
                if vals:
                    per.append(reducer(vals))
            return per
        pod_cpu = mean_in(cpu)
        st.update({
            "step": name, "rate": rate,
            "pod_cpu_mean_m": [round(v * 1000) for v in pod_cpu],
            "pod_throttled_mean": [round(float(v), 3) for v in mean_in(thr)],
            "carrier_cpu_total_m": round(sum(mean_in(carrier)) * 1000) if carrier else None,
            "vus_max": float(raw.v_val[(raw.v_t >= t_start) & (raw.v_t < b)].max()) if raw.v_t.size else None,
            # Scrapes that failed during the step (any pod), and peak admitted requests.
            "up_failures": (sum(1 for s in up.values() for t, v in s.items() if t_start <= t <= b and v < 1)
                            if up else None),
            "inflight_max": (max((v for s in inflight.values() for t, v in s.items() if t_start <= t <= b),
                                 default=None) if inflight else None),
        })
        st["k6"] = k6_resources(run_dir, t_start + 60, b, limits)
        rows.append(st)
    return meta, rows


def cmd_ladder(args):
    dirs = [Path(d) for d in args.dirs] or sorted((PILOT_DIR / "calibration").glob("*_*"))
    out = {}
    for d in dirs:
        meta, rows = analyze_ladder(d)
        out[d.name] = {"meta": meta, "steps": rows}
        cap = (meta.get("service_overrides") or {}).get("max_inflight_requests") or 0
        print(f"\n=== {d.name}  ({meta.get('service')} {meta.get('config')}, timeout "
              f"{(meta.get('load_profile') or {}).get('request_timeout')}, cap {cap or 'off'}, "
              f"image {(meta.get('service_overrides') or {}).get('image_tag') or 'manifest'}, "
              f"k6 exit {meta.get('k6_exit_code')}, raw verified {(meta.get('raw_results') or {}).get('verified')}) ===")
        print(f"{'rate':>5} {'attempt/s':>9} {'good/s':>7} {'drop':>5} {'err%':>6} {'shed%':>6} {'tmo%':>6} "
              f"{'p50':>6} {'p95':>6} {'p99':>6} {'p95ok':>6} {'p95http':>7} {'podCPU(m)':>18} {'thr':>12} "
              f"{'carrier':>7} {'k6cpu':>6} {'k6thr':>6} {'k6MiB':>6} {'vus':>5} {'upFail':>6} {'infl':>5}")
        for r in rows:
            if r.get("missing"):
                print(f"{r['rate']:>5}  (missing)")
                continue
            k = r["k6"]
            print(f"{r['rate']:>5} {r['attempted_rps']:>9.2f} {r['goodput_rps']:>7.2f} {r['dropped']:>5} "
                  f"{fmt(r['error_pct'], 2):>6} {fmt(r.get('shed_pct'), 2):>6} {fmt(r['timeout_pct'], 2):>6} {fmt_ms(r['p50_ms']):>6} "
                  f"{fmt_ms(r['p95_ms']):>6} {fmt_ms(r['p99_ms']):>6} {fmt_ms(r['p95_ok_ms']):>6} "
                  f"{fmt_ms(r['p95_http_req_duration_ms']):>7} {str(r['pod_cpu_mean_m']):>18} "
                  f"{str(r['pod_throttled_mean']):>12} {str(r['carrier_cpu_total_m']):>7} "
                  f"{fmt(k['cpu_max_cores'], 2):>6} {fmt(k['throttled_ratio_max'], 3):>6} "
                  f"{fmt((k['memory_max_bytes'] or 0) / 2**20, 0):>6} {fmt(r['vus_max'], 0):>5} "
                  f"{str(r.get('up_failures') if r.get('up_failures') is not None else 'n/a'):>6} "
                  f"{fmt(r.get('inflight_max'), 0):>5}")
    target = PILOT_DIR / "analysis" / "ladder.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(jsonable(out), indent=1))
    print(f"\nwrote {target}")


# ── pilot runs ───────────────────────────────────────────────────────────────

def pilot_run_dirs():
    for service in SERVICES:
        for cfg_dir in sorted((PILOT_DIR / service).glob("*")):
            for pattern_dir in sorted(cfg_dir.glob("*")):
                for rep_dir in sorted(pattern_dir.glob("rep*")):
                    if (rep_dir / "metadata.json").exists():
                        yield rep_dir


def analyze_run(run_dir, cfg):
    meta = load_json(run_dir / "metadata.json") or {}
    lp = meta.get("load_profile") or {}
    service, config, pattern = meta["service"], meta["config"], meta["pattern"]
    base, peak = lp.get("base_rate"), lp.get("peak_rate")
    timeout_ms = timeout_ms_of(meta)
    slo = slo_for(cfg, service)
    raw = Raw.load(run_dir, meta["run_id"])
    starts = scenario_starts(run_dir / "k6-output.log")
    scn_name = f"openloop_{pattern}"
    t_start = starts.get(scn_name) or (meta.get("k6_scenario_start_ms") or 0) / 1000.0 or None
    facts = k6_log_facts(run_dir / "k6-output.log")
    res = {"run_id": meta["run_id"], "service": service, "config": config, "pattern": pattern,
           "rep": meta.get("repetition"), "plan_position": meta.get("plan_position"),
           "base_rate": base, "peak_rate": peak, "timeout_ms": timeout_ms, "slo_ms": slo,
           "pre_vus": lp.get("pre_allocated_vus"), "max_vus": lp.get("max_vus"),
           "raw_verified": (meta.get("raw_results") or {}).get("verified"),
           "k6_exit_code": meta.get("k6_exit_code"), "k6_log": facts}
    if raw is None or t_start is None:
        res["missing_raw"] = True
        return res

    sid = raw.scn_id(scn_name)
    w0, w1 = t_start + LOAD_WINDOW[0], t_start + LOAD_WINDOW[1]
    load = window_stats(raw, sid, w0, w1, timeout_ms, slo, rel0=t_start)
    whole = window_stats(raw, sid, t_start, t_start + 720.0, timeout_ms)
    res["offered_load_window_rps"] = offered_requests(pattern, base, peak, *LOAD_WINDOW) / (LOAD_WINDOW[1] - LOAD_WINDOW[0])
    res["offered_total"] = offered_requests(pattern, base, peak, 0, 720)
    res["load_window"] = load
    res["whole_run"] = {k: whole[k] for k in ("requests", "ok", "dropped", "error_pct", "timeout_pct",
                                              "timeouts_k6_code1050", "p95_ms", "p95_http_req_duration_ms")}
    res["dropped_total"] = int((raw.d_scn == sid).sum()) + int((raw.d_scn < 0).sum())
    res["attempted_total"] = whole["requests"] + whole["dropped"]
    res["vus_max_used"] = float(raw.v_val.max()) if raw.v_val.size else None
    windows = [(t_start + a, t_start + b) for a, b in PEAK_WINDOWS[pattern]]
    res["scaling"] = scaling_timeline(run_dir, service, t_start + ONSET, t_start + LOAD_WINDOW[1])
    res["pods"] = pod_distribution(run_dir, service, windows)
    res["k6"] = k6_resources(run_dir, w0, w1, parse_resources(lp.get("k6_resources")))
    res["health"] = run_health(run_dir, meta, service, t_start)
    return res


def validity_issues(r):
    """Critical issues are tagged with the robustness-gate criterion they break:
    [G1] instrument, [G2] start state, [G3] observability, [G5] per-pod load."""
    crit, warn = [], []
    if r.get("missing_raw"):
        crit.append("[G1] raw per-request data or scenario start missing")
        return crit, warn
    if r["dropped_total"] != 0:
        crit.append(f"[G1] dropped_iterations = {r['dropped_total']}")
    f = r["k6_log"]
    if not r.get("raw_verified"):
        crit.append("[G1] raw results not verified")
    if r.get("k6_exit_code") not in (0,):
        crit.append(f"[G1] k6 exit code {r.get('k6_exit_code')}")
    # Full schedule = every scheduled arrival was reached (started or dropped). k6 fires
    # arrival i when the rate integral reaches i, strictly before the 720 s end: ceil(A) - 1
    # arrivals for an integral A (every run so far: 15,399 of A = 15,400 auth, 54,274 of
    # 54,275 shipping). Not wall-clock (fixed 2026-10-06): k6 can end the scenario at its
    # last arrival (auth spike: 716.5 s), and the global timer includes setup(), whose
    # bcrypt logins padded every v1 auth run past 720 s.
    expected = math.ceil(r["offered_total"] - 1e-6) - 1 if r["offered_total"] else None
    reached = None if f["complete"] is None else f["complete"] + (f["interrupted"] or 0) + r["dropped_total"]
    if not f["completed_100pct"] or expected is None or reached is None or reached < expected:
        crit.append(f"[G1] k6 did not run the full 12 m schedule ({reached} of {expected} scheduled arrivals "
                    f"reached, 100%={f['completed_100pct']})")
    ratio = r["attempted_total"] / r["offered_total"] if r["offered_total"] else None
    if ratio is None or abs(ratio - 1) > 0.02:
        crit.append(f"[G1] attempted/offered = {fmt(ratio, 3)} over the whole schedule")
    if f["interrupted"]:
        warn.append(f"{f['interrupted']} iterations interrupted at the end")
    if r["config"] != "b1" and r["pods"]["flagged"]:
        crit.append(f"[G5] per-pod distribution: {', '.join(r['pods']['flagged'])} below {POD_SHARE_FLOOR:.0%} of mean share")
    h = r.get("health") or {}
    if r["config"] in AUTOSCALED and (h.get("ready_at_start") not in (None, 1) or h.get("ready_at_onset") not in (None, 1)):
        crit.append(f"[G2] {h.get('ready_at_start')} Ready replica(s) at scenario start and {h.get('ready_at_onset')} "
                    f"at onset (expected 1 and 1)")
    if h.get("preauth_enabled") and not h.get("preauth_used"):
        crit.append("[G2] pre-authentication enabled but setup() did not use the tokens")
    if h.get("unscraped_while_ready"):
        crit.append("[G3] Prometheus could not scrape Ready pod(s): " + ", ".join(
            f"{p} ({n} x 15 s)" for p, n in sorted(h["unscraped_while_ready"].items())))
    if h.get("metric_failures"):
        reasons = sorted({reason for _, _, reason in h["metric_failures"]})
        crit.append(f"[G3] autoscaler metric failures in the load window ({len(h['metric_failures'])} snapshots, "
                    f"first at {h['metric_failures'][0][0]:+.0f} s): {', '.join(reasons)}")
    if h.get("restarts"):
        crit.append("[G3] container restarts during the run: " + "; ".join(
            f"{obj} at {t:+.0f} s" for t, obj, _ in h["restarts"]))
    if h and not h.get("up_available"):
        warn.append("no prom_up.json (pre-v2 run): scrape health not checked")
    if r["pods"].get("rate_unscraped"):
        warn.append(f"no request-rate samples (scrape failing, pod likely overloaded) for "
                    f"{', '.join(r['pods']['rate_unscraped'])} during the peak")
    k = r["k6"]
    if k["throttled_ratio_max"] is not None and k["throttled_ratio_max"] > 0.05:
        warn.append(f"k6 CPU throttled in up to {k['throttled_ratio_max']:.1%} of CFS periods")
    if k["memory_max_bytes"] and k["memory_limit_bytes"] and k["memory_max_bytes"] > 0.8 * k["memory_limit_bytes"]:
        warn.append(f"k6 memory {k['memory_max_bytes'] / 2**20:.0f} MiB > 80% of limit")
    if r["vus_max_used"] and r["max_vus"] and r["vus_max_used"] >= r["max_vus"]:
        warn.append(f"all {r['max_vus']} VUs were busy at least once")
    return crit, warn


def cmd_validate(args):
    cfg = load_config()
    n_crit = n_warn = 0
    print("=" * 78)
    print("  OPEN-LOOP PILOT VALIDATION")
    print("=" * 78)
    for run_dir in pilot_run_dirs():
        r = analyze_run(run_dir, cfg)
        crit, warn = validity_issues(r)
        n_crit += len(crit)
        n_warn += len(warn)
        status = "CRIT" if crit else ("WARN" if warn else "OK")
        print(f"\n[{status}] {r['run_id']}")
        if not r.get("missing_raw"):
            lw = r["load_window"]
            print(f"   offered {r['offered_load_window_rps']:.2f} req/s | attempted {lw['attempted_rps']:.2f} | "
                  f"goodput {lw['goodput_rps']:.2f} | dropped {r['dropped_total']} | "
                  f"err {fmt(lw['error_pct'], 2)}% | timeout {fmt(lw['timeout_pct'], 2)}% (load window)")
            pods = r["pods"]["per_pod"]
            shares = ", ".join(f"{p[-5:]}={s['mean_share']:.2f}" for p, s in sorted(pods["rate"].items()))
            print(f"   per-pod rate share in peak (Ready>=60s): {shares or 'n/a (<2 eligible pods)'}")
            cshares = ", ".join(f"{p[-5:]}={s['mean_share']:.2f}" for p, s in sorted(pods["cpu"].items()))
            print(f"   per-pod CPU share in peak  (Ready>=60s): {cshares or 'n/a (<2 eligible pods)'}")
            k = r["k6"]
            print(f"   k6: cpu max {fmt(k['cpu_max_cores'], 2)}/{fmt(k['cpu_limit_cores'], 1)} cores, "
                  f"throttled max {fmt(k['throttled_ratio_max'], 3)}, mem max "
                  f"{fmt((k['memory_max_bytes'] or 0) / 2**20, 0)} MiB, VUs busy max {fmt(r['vus_max_used'], 0)}/{r['max_vus']}")
        for c in crit:
            print(f"   CRITICAL: {c}")
        for w in warn:
            print(f"   WARNING:  {w}")
    print(f"\nTOTAL: {n_crit} critical, {n_warn} warnings")


# ── closed-loop reference ────────────────────────────────────────────────────

def closed_loop_p95(service, config, pattern="spike"):
    vals = []
    for rep in range(1, 6):
        log = CLOSED_DIR / service / config / pattern / f"rep{rep}" / "k6-output.log"
        if not log.exists():
            continue
        m = re.search(r"http_req_duration[^\n]*p\(95\)=([\d.]+)(ms|s)\b", log.read_text(errors="ignore"))
        if m:
            vals.append(float(m.group(1)) * (1 if m.group(2) == "ms" else 1000))
    return vals


def cmd_report(args):
    cfg = load_config()
    runs = [analyze_run(d, cfg) for d in pilot_run_dirs()]
    for r in runs:
        r["critical"], r["warnings"] = validity_issues(r)
    closed = {s: {c: closed_loop_p95(s, c) for c in CONFIGS} for s in SERVICES}
    summary = {"config": cfg, "runs": runs, "closed_loop_spike_p95": closed}
    out_dir = PILOT_DIR / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(jsonable(summary), indent=1))

    lines = []
    lines.append("| run | plan pos | offered req/s | attempted | goodput | dropped | err % | timeout % | p95 ms | p99 ms "
                 "| p95 ok ms | SLO-viol s | onset->scale-up s | onset->new Ready s | ready@onset | max Ready | pod shares (rate) | validity |")
    lines.append("|" + "---|" * 18)
    for r in sorted(runs, key=lambda r: (r["service"], CONFIGS.index(r["config"]), r["rep"])):
        if r.get("missing_raw"):
            lines.append(f"| {r['run_id']} | {r['plan_position']} | missing raw data |" + " |" * 16)
            continue
        lw, sc = r["load_window"], r["scaling"]
        shares = " ".join(f"{s['mean_share']:.2f}" for _, s in sorted(r["pods"]["per_pod"]["rate"].items()))
        lines.append(
            f"| {r['service'].split('-')[0]} {r['config'].upper()} rep{r['rep']} | {r['plan_position']} | "
            f"{r['offered_load_window_rps']:.2f} | {lw['attempted_rps']:.2f} | {lw['goodput_rps']:.2f} | "
            f"{r['dropped_total']} | {fmt(lw['error_pct'], 2)} | {fmt(lw['timeout_pct'], 2)} | "
            f"{fmt_ms(lw['p95_ms'])} | {fmt_ms(lw['p99_ms'])} | {fmt_ms(lw['p95_ok_ms'])} | "
            f"{fmt(lw.get('slo_violation_s'), 0)} | {fmt(sc['t_first_scale_up_s'], 0)} | "
            f"{fmt(sc['t_first_new_ready_s'], 0)} | {sc['ready_at_onset']} | {sc['max_ready_in_peak']} | "
            f"{shares or '-'} | {'CRIT: ' + '; '.join(r['critical']) if r['critical'] else 'ok'} |")
    criteria, aggregates = evaluate_criteria(runs, closed)
    summary["criteria"] = criteria
    summary["aggregates"] = aggregates
    (out_dir / "summary.json").write_text(json.dumps(jsonable(summary), indent=1))

    lines.append("")
    lines.append("| service | config | reps | window p95 ms (per rep) | SLO-viol s (per rep) | err % (per rep) "
                 "| onset->scale-up s | onset->new Ready s | max Ready | closed-loop spike p95 ms (5-rep mean) |")
    lines.append("|" + "---|" * 10)
    for service in SERVICES:
        for config in CONFIGS:
            a = aggregates[service][config]
            if not a["reps"]:
                continue
            lines.append(
                f"| {service} | {config.upper()} | {a['reps']} | {' / '.join(fmt_ms(v) for v in a['p95'])} | "
                f"{' / '.join(fmt(v, 0) for v in a['slo_s'])} | {' / '.join(fmt(v, 2) for v in a['err'])} | "
                f"{' / '.join(fmt(v, 0) for v in a['t_scale'])} | {' / '.join(fmt(v, 0) for v in a['t_ready'])} | "
                f"{' / '.join(str(v) for v in a['max_ready'])} | {fmt(a['closed_p95_mean'], 0)} |")
    lines.append("")
    for c in criteria:
        lines.append(f"- **{c['id']}. {c['name']}: {c['result']}** — {c['evidence']}")
    (out_dir / "tables.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out_dir / 'summary.json'} and tables.md")


def rel_diff(a, b):
    """|a-b| / mean(a, b); 0 when both are 0, inf when exactly one is infinite."""
    if a is None or b is None:
        return None
    if a == INF and b == INF:
        return 0.0
    if a == INF or b == INF:
        return INF
    if a == b:
        return 0.0
    return abs(a - b) / ((a + b) / 2)


def evaluate_criteria(runs, closed):
    """Decision criteria 1-5, as fixed in the task before the pilot ran.

    Operational definitions (fixed before pilot data existed):
      C3 'B1 clearly overloaded': in every B1 rep, SLO-violation >= 210 s
         (half the 420 s load window) OR load-window error % >= max B2 error % + 5.
      C4 'reps agree': |a-b| / mean(a,b) <= 0.25 for window p95 AND SLO-violation
         seconds; both-infinite p95 counts as agreement. Disagreements are listed
         with the scale-up timing of each rep so poll-phase explanations can be checked.
    """
    valid = [r for r in runs if not r.get("missing_raw")]
    agg = {}
    for service in SERVICES:
        agg[service] = {}
        for config in CONFIGS:
            rs = sorted((r for r in valid if r["service"] == service and r["config"] == config), key=lambda r: r["rep"])
            closed_vals = closed.get(service, {}).get(config) or []
            agg[service][config] = {
                "reps": len(rs),
                "p95": [r["load_window"]["p95_ms"] for r in rs],
                "slo_s": [r["load_window"].get("slo_violation_s") for r in rs],
                "err": [r["load_window"]["error_pct"] for r in rs],
                "t_scale": [r["scaling"]["t_first_scale_up_s"] for r in rs],
                "t_ready": [r["scaling"]["t_first_new_ready_s"] for r in rs],
                "max_ready": [r["scaling"]["max_ready_in_peak"] for r in rs],
                "closed_p95_mean": float(np.mean(closed_vals)) if closed_vals else None,
                "closed_p95_reps": closed_vals,
            }

    crit = []
    dropped = [(r["run_id"], r["dropped_total"]) for r in valid]
    bad = [f"{rid}={d}" for rid, d in dropped if d != 0]
    crit.append({"id": 1, "name": "dropped_iterations = 0 in all runs",
                 "result": "PASS" if valid and not bad and len(valid) == len(runs) else "FAIL",
                 "evidence": f"{len(valid)} runs with raw data of {len(runs)}; non-zero: {', '.join(bad) or 'none'}"})

    ev, ok = [], True
    for service in SERVICES:
        for r in (x for x in valid if x["service"] == service and x["config"] == "b2"):
            lw = r["load_window"]
            good = lw["error_pct"] is not None and lw["error_pct"] < 1.0 and lw["p95_ms"] is not None \
                and r["slo_ms"] is not None and lw["p95_ms"] <= r["slo_ms"]
            ok &= good
            ev.append(f"{service} rep{r['rep']}: err {fmt(lw['error_pct'], 2)}%, p95 {fmt_ms(lw['p95_ms'])} vs SLO {fmt(r['slo_ms'], 0)}")
    crit.append({"id": 2, "name": "B2 error < 1% and window p95 <= SLO",
                 "result": "PASS" if ok and ev else "FAIL", "evidence": "; ".join(ev) or "no B2 runs"})

    ev, ok = [], True
    for service in SERVICES:
        b2_err = [r["load_window"]["error_pct"] or 0.0 for r in valid if r["service"] == service and r["config"] == "b2"]
        for r in (x for x in valid if x["service"] == service and x["config"] == "b1"):
            lw = r["load_window"]
            over = (lw.get("slo_violation_s") or 0) >= 210 or \
                (lw["error_pct"] is not None and b2_err and lw["error_pct"] >= max(b2_err) + 5)
            ok &= bool(over)
            ev.append(f"{service} B1 rep{r['rep']}: SLO-viol {fmt(lw.get('slo_violation_s'), 0)} s, err "
                      f"{fmt(lw['error_pct'], 2)}% (B2 max err {fmt(max(b2_err) if b2_err else None, 2)}%)")
    crit.append({"id": 3, "name": "B1 clearly overloaded", "result": "PASS" if ok and ev else "FAIL",
                 "evidence": "; ".join(ev) or "no B1 runs"})

    ev, ok, disagreements = [], True, []
    for service in SERVICES:
        for config in AUTOSCALED:
            a = agg[service][config]
            if a["reps"] == 0:
                continue  # cell not in this run list (the v1 pilot had no H1)
            if a["reps"] != 2:
                ok = False
                ev.append(f"{service} {config}: {a['reps']} reps")
                continue
            d_p95 = rel_diff(*a["p95"])
            d_slo = rel_diff(*a["slo_s"])
            agree = d_p95 is not None and d_slo is not None and d_p95 <= 0.25 and d_slo <= 0.25
            ok &= agree
            ev.append(f"{service} {config.upper()}: p95 {fmt_ms(a['p95'][0])}/{fmt_ms(a['p95'][1])} "
                      f"(diff {fmt(d_p95 * 100 if d_p95 not in (None, INF) else d_p95, 0)}%), SLO-viol "
                      f"{fmt(a['slo_s'][0], 0)}/{fmt(a['slo_s'][1], 0)} s (diff "
                      f"{fmt(d_slo * 100 if d_slo not in (None, INF) else d_slo, 0)}%)")
            if not agree:
                disagreements.append({"service": service, "config": config, "t_scale": a["t_scale"],
                                      "t_ready": a["t_ready"]})
    crit.append({"id": 4, "name": "Reps agree within +/-25% (autoscaled configs)",
                 "result": "PASS" if ok else "FAIL (check poll-phase explanation)",
                 "evidence": "; ".join(ev), "disagreements": disagreements})

    flagged = [f"{r['run_id']}: {', '.join(r['pods']['flagged'])}" for r in valid
               if r["config"] in AUTOSCALED and r["pods"]["flagged"]]
    unchecked = [r["run_id"] for r in valid if r["config"] in AUTOSCALED and not r["pods"]["pods_checked"]]
    crit.append({"id": 5, "name": "Per-pod distribution passes in all autoscaled runs",
                 "result": "PASS" if not flagged else "FAIL",
                 "evidence": f"flagged: {'; '.join(flagged) or 'none'}; runs with <2 eligible pods: {', '.join(unchecked) or 'none'}"})
    return crit, agg


def replicate_agreement(values, floor):
    """(agree, relative range) for replicate values: range <= 25% of the mean or <= floor."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None, None
    if any(v == INF for v in vals):
        return all(v == INF for v in vals), (0.0 if all(v == INF for v in vals) else INF)
    rng = max(vals) - min(vals)
    mean = sum(vals) / len(vals)
    rel = 0.0 if rng == 0 else (rng / mean if mean > 0 else INF)
    return (rel <= GATE_REL or rng <= floor), rel


def runlist_cells(max_rep):
    cells = set()
    path = PILOT_DIR / "runlist.txt"
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) == 4 and int(parts[3]) <= max_rep:
                cells.add((parts[0], parts[2], parts[1]))  # (service, pattern, config)
    return cells


def cmd_gate(args):
    """Robustness gate for switching the campaign to open loop (fixed 2026-10-06,
    before any v2 data). Evaluated on rep blocks 1..N (default 2); every
    criterion must pass — no after-the-fact explanations.
      G1 instrument: dropped = 0, full schedule, verified raw data, k6 exit 0,
         attempted = offered within 2%, in every run
      G2 start state: every autoscaled run has exactly 1 Ready replica at scenario
         start and at spike/ramp onset; pre-auth tokens used when enabled
      G3 observability: no Ready pod unscrapeable, no autoscaler metric failure in
         the load window, no container restart during the run
      G4 calibration: per service x pattern, B2 error < 1% and window p95 <= SLO
         in every rep; B1 SLO-violation >= 210 s or error >= B2 max + 5 points
      G5 per-pod load: no pod below 20% of the mean per-pod share
      G6 reproducibility: per autoscaled service x pattern x config, replicate
         SLO-violation seconds within 25% of the mean or 20 s, AND error % within
         25% or 1 point
    """
    cfg = load_config()
    runs = [r for r in (analyze_run(d, cfg) for d in pilot_run_dirs()) if (r.get("rep") or 0) <= args.reps]
    for r in runs:
        r["critical"], r["warnings"] = validity_issues(r)
    valid = [r for r in runs if not r.get("missing_raw")]

    def tagged(code):
        return [f"{r['run_id']}: {c}" for r in runs for c in r["critical"] if c.startswith(f"[{code}]")]

    criteria = []
    for code, name in (("G1", "instrument"), ("G2", "start state"), ("G3", "observability")):
        hits = tagged(code)
        criteria.append({"id": code, "name": name, "pass": not hits and bool(runs),
                         "evidence": hits or [f"{len(runs)} runs checked, none affected"]})

    ev, ok = [], True
    for service in SERVICES:
        for pattern in PATTERNS:
            cell = [r for r in valid if r["service"] == service and r["pattern"] == pattern]
            b2 = [r for r in cell if r["config"] == "b2"]
            b1 = [r for r in cell if r["config"] == "b1"]
            if not b1 and not b2:
                continue
            b2_err = [r["load_window"]["error_pct"] or 0.0 for r in b2]
            for r in b2:
                lw = r["load_window"]
                good = (lw["error_pct"] is not None and lw["error_pct"] < 1.0 and lw["p95_ms"] is not None
                        and r["slo_ms"] is not None and lw["p95_ms"] <= r["slo_ms"])
                ok &= good
                ev.append(f"{'ok  ' if good else 'FAIL'} {service} {pattern} B2 r{r['rep']}: err {fmt(lw['error_pct'], 2)}%, "
                          f"p95 {fmt_ms(lw['p95_ms'])} vs SLO {fmt(r['slo_ms'], 0)}")
            for r in b1:
                lw = r["load_window"]
                over = (lw.get("slo_violation_s") or 0) >= 210 or (
                    lw["error_pct"] is not None and bool(b2_err) and lw["error_pct"] >= max(b2_err) + 5)
                ok &= bool(over)
                ev.append(f"{'ok  ' if over else 'FAIL'} {service} {pattern} B1 r{r['rep']}: SLO-viol "
                          f"{fmt(lw.get('slo_violation_s'), 0)} s, err {fmt(lw['error_pct'], 2)}%")
            if not b1 or not b2:
                ok = False
                ev.append(f"FAIL {service} {pattern}: missing B1 or B2 runs")
    criteria.append({"id": "G4", "name": "calibration (B2 healthy, B1 overloaded)", "pass": ok and bool(ev), "evidence": ev})

    hits = tagged("G5")
    criteria.append({"id": "G5", "name": "per-pod load distribution", "pass": not hits and bool(runs),
                     "evidence": hits or ["no pod below 20% of the mean share"]})

    ev, ok = [], True
    expected = runlist_cells(args.reps)
    found = {(r["service"], r["pattern"], r["config"]) for r in valid}
    for service, pattern, config in sorted(expected - found):
        ok = False
        ev.append(f"FAIL {service} {pattern} {config.upper()}: no analysable runs")
    for service in SERVICES:
        for pattern in PATTERNS:
            for config in AUTOSCALED:
                rs = sorted((r for r in valid if (r["service"], r["pattern"], r["config"]) == (service, pattern, config)),
                            key=lambda r: r["rep"])
                if not rs:
                    continue
                slo = [r["load_window"].get("slo_violation_s") for r in rs]
                err = [r["load_window"]["error_pct"] for r in rs]
                a_slo, rel_slo = replicate_agreement(slo, GATE_FLOOR_SLO_S)
                a_err, rel_err = replicate_agreement(err, GATE_FLOOR_ERR_PTS)
                agree = bool(a_slo) and bool(a_err)
                ok &= agree
                ev.append(f"{'ok  ' if agree else 'FAIL'} {service} {pattern} {config.upper()}: SLO-viol "
                          f"{' / '.join(fmt(v, 0) for v in slo)} s (range/mean {fmt(rel_slo * 100 if rel_slo not in (None, INF) else rel_slo, 0)}%), "
                          f"err {' / '.join(fmt(v, 2) for v in err)}% (range/mean {fmt(rel_err * 100 if rel_err not in (None, INF) else rel_err, 0)}%)")
    criteria.append({"id": "G6", "name": "reproducibility of autoscaled cells", "pass": ok and bool(ev), "evidence": ev})

    verdict = "PASS" if all(c["pass"] for c in criteria) else "FAIL"
    print("=" * 78)
    print(f"  OPEN-LOOP ROBUSTNESS GATE — rep blocks 1..{args.reps}: {verdict}  ({len(runs)} runs)")
    print("=" * 78)
    for c in criteria:
        print(f"\n[{'PASS' if c['pass'] else 'FAIL'}] {c['id']} {c['name']}")
        for line in c["evidence"]:
            print(f"   {line}")
    out_dir = PILOT_DIR / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gate.json").write_text(json.dumps(jsonable(
        {"verdict": verdict, "reps": args.reps, "criteria": criteria, "runs": runs}), indent=1))
    print(f"\nwrote {out_dir / 'gate.json'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ladder")
    p.add_argument("dirs", nargs="*")
    p.set_defaults(func=cmd_ladder)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    sub.add_parser("report").set_defaults(func=cmd_report)
    p = sub.add_parser("gate", help="robustness gate over rep blocks 1..N")
    p.add_argument("--reps", type=int, default=2)
    p.set_defaults(func=cmd_gate)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
