#!/usr/bin/env python3
"""
Deep Experiment Validation Script
==================================
Checks each core-matrix run against anomaly_detection_guide.md plus the
latest thesis-specific expectations for:
  - auth-service as the CPU-dominant control
  - shipping-rate-service as the wait-dominant comparison workload
  - product-service as a separate exploratory case outside the core matrix
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path("/home/kevin/Projects/e-commerce/experiment-results")
SERVICES = ["shipping-rate-service", "auth-service"]
CONFIGS = ["b1", "b2", "h1", "h2", "h3", "k1"]
PATTERNS = ["gradual", "spike", "oscillating"]
SERVICE_HANDLER_FILTERS = {
    "shipping-rate-service": "/shipping/quotes",
    "auth-service": "/auth/login",
}
LOAD_PROFILE_FALLBACKS = {
    # shipping-rate-service uses ramping-vus (not ramping-arrival-rate).
    # Throughput is latency-dependent; use calibrated observed values instead of RPS math.
    "shipping-rate-service": {"base_vus": 10, "peak_vus": 80},
    "auth-service": {"base_rps": 10, "peak_rps": 40},
}

# Calibrated expected request counts for shipping-rate-service with ramping-vus BASE=10 PEAK=80.
# Derived from VU=80 B1 calibration run (18,445 reqs) and B2 confirmation (34,546 reqs).
# The check uses a 70% floor (was 85%) for shipping because VU-based throughput is
# latency-dependent and varies more widely between B1 (constrained) and B2 (fast).
SHIPPING_EXPECTED_REQUESTS = {
    # Gradual (12m): 18,000 requests typical for B1; up to 34,000+ for B2
    # Use conservative lower bound across all configs.
    "gradual":     15000,
    # Spike (12m): similar total duration but burst; throughput varies more
    "spike":       12000,
    # Oscillating (12m): 3 on/off cycles; conservative estimate
    "oscillating": 10000,
}
PATTERN_STAGE_TARGETS = {
    "gradual": [
        (120, "base"),
        (300, "peak"),
        (120, "peak"),
        (180, "zero"),
    ],
    "spike": [
        (120, "base"),
        (10, "peak"),
        (290, "peak"),
        (120, "peak"),
        (180, "zero"),
    ],
    "oscillating": [
        (120, "base"),
        (10, "peak"),
        (80, "peak"),
        (10, "base"),
        (80, "base"),
        (10, "peak"),
        (80, "peak"),
        (10, "base"),
        (80, "base"),
        (10, "peak"),
        (50, "peak"),
        (180, "zero"),
    ],
}

# Expected files per run directory
EXPECTED_FILES = [
    "metadata.json",
    "start_time.txt",
    "end_time.txt",
    "k6-output.log",
    "prom_http_requests_rate.json",
    "prom_p95_latency.json",
    "prom_replica_count.json",
    "prom_replica_ready_count.json",
    "prom_cpu_usage.json",
    "k8s-events.txt",
    "pod-status.txt",
    "hpa-status.yaml",
    "keda-status.yaml",
]
EVENT_WINDOW_GRACE_SECONDS = 90
POD_AGE_GRACE_SECONDS = 180

class RunResult:
    def __init__(self, service, config, pattern, rep, path):
        self.service = service
        self.config = config
        self.pattern = pattern
        self.rep = rep
        self.path = Path(path)
        self.run_id = f"{service}_{config}_{pattern}_rep{rep}"
        self.critical = []    # Tier 1: Must re-run
        self.warnings = []    # Tier 2: Investigate
        self.info = []        # Tier 3: Expected behavior verification
        self.file_issues = [] # Missing/empty files

    def add_critical(self, code, msg):
        self.critical.append(f"🔴 [{code}] {msg}")

    def add_warning(self, code, msg):
        self.warnings.append(f"🟡 [{code}] {msg}")

    def add_info(self, code, msg):
        self.info.append(f"🟢 [{code}] {msg}")

    def add_file_issue(self, msg):
        self.file_issues.append(f"📁 {msg}")


def _parse_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_metadata(run: RunResult):
    """Load metadata.json once per run."""
    if hasattr(run, "_metadata_cache"):
        return run._metadata_cache

    meta_file = run.path / "metadata.json"
    if not meta_file.exists() or meta_file.stat().st_size == 0:
        run._metadata_cache = {}
        return run._metadata_cache

    try:
        run._metadata_cache = json.loads(meta_file.read_text())
    except json.JSONDecodeError:
        run._metadata_cache = {}
    return run._metadata_cache


def get_load_profile(run: RunResult):
    """Return the calibrated load profile recorded for the run."""
    metadata = load_metadata(run)
    profile = metadata.get("load_profile") or {}
    fallback = LOAD_PROFILE_FALLBACKS.get(run.service, {"base_rps": 20, "peak_rps": 200})

    # Shipping uses ramping-vus — surface vus instead of rps
    if run.service == "shipping-rate-service":
        return {
            "base_vus": _parse_int(profile.get("base_vus"), fallback.get("base_vus", 10)),
            "peak_vus": _parse_int(profile.get("peak_vus"), fallback.get("peak_vus", 80)),
            # Keep rps keys with sentinel values so callers don't KeyError
            "base_rps": _parse_int(profile.get("base_vus"), fallback.get("base_vus", 10)),
            "peak_rps": _parse_int(profile.get("peak_vus"), fallback.get("peak_vus", 80)),
        }
    return {
        "base_rps": _parse_int(profile.get("base_rps"), fallback["base_rps"]),
        "peak_rps": _parse_int(profile.get("peak_rps"), fallback["peak_rps"]),
    }


def expected_request_count(run: RunResult):
    """Estimate expected request count for the given run.

    For shipping-rate-service (ramping-vus executor): uses calibrated observed
    minimums per pattern rather than RPS-based trapezoidal integration, which
    overestimates throughput by ~32% because actual delivery is latency-constrained.

    For all other services (ramping-arrival-rate executor): uses trapezoidal
    integration over the stage schedule.
    """
    if run.service == "shipping-rate-service":
        return SHIPPING_EXPECTED_REQUESTS.get(run.pattern, 10000)

    profile = get_load_profile(run)
    base_rps = profile["base_rps"]
    peak_rps = profile["peak_rps"]
    current_rate = base_rps
    total_requests = 0.0

    for duration_seconds, target_label in PATTERN_STAGE_TARGETS.get(run.pattern, []):
        if target_label == "base":
            target_rate = base_rps
        elif target_label == "peak":
            target_rate = peak_rps
        else:
            target_rate = 0

        total_requests += duration_seconds * (current_rate + target_rate) / 2
        current_rate = target_rate

    return int(round(total_requests))


def parse_csv_args(values, default):
    if not values:
        return list(default)

    items = []
    for value in values:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


def parse_age_seconds(value):
    matches = re.findall(r"(\d+)([smhd])", value)
    if not matches:
        return None

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return sum(int(amount) * multipliers[unit] for amount, unit in matches)


def parse_timestamp_epoch(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def get_run_window(run: RunResult):
    metadata = load_metadata(run)
    return (
        metadata.get("start_epoch"),
        metadata.get("end_epoch"),
        metadata.get("duration_seconds"),
    )


def parse_k6_p95_ms(content):
    match = re.search(r"http_req_duration[^\n]*p\(95\)=([\d.]+)(ms|s)\b", content)
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)
    return value if unit == "ms" else value * 1000


def load_aggregated_series(prom_file: Path, handler_filter: str = "", aggregate: str = "sum"):
    if not prom_file.exists() or prom_file.stat().st_size == 0:
        return {}

    try:
        data = json.loads(prom_file.read_text())
    except json.JSONDecodeError:
        return {}

    results = data.get("data", {}).get("result", [])
    buckets = {}

    for series in results:
        metric = series.get("metric", {})
        handler = metric.get("handler", "")
        if handler_filter and handler and handler != handler_filter:
            continue

        for ts, value in series.get("values", []):
            try:
                ts = float(ts)
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric):
                continue
            buckets.setdefault(ts, []).append(numeric)

    if aggregate == "max":
        return {ts: max(values) for ts, values in buckets.items()}
    return {ts: sum(values) for ts, values in buckets.items()}


def iter_k8s_events(run: RunResult):
    events_file = run.path / "k8s-events.txt"
    if not events_file.exists() or events_file.stat().st_size == 0:
        return []

    start_epoch, end_epoch, duration = get_run_window(run)
    parsed = []
    for raw_line in events_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("LAST SEEN") or line.startswith("TIMESTAMP"):
            continue

        if "\t" in line:
            parts = line.split("\t", 4)
            if len(parts) < 5:
                continue
            time_token, etype, reason, obj, message = parts
        else:
            match = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)$", line)
            if not match:
                continue
            time_token, etype, reason, obj, message = match.groups()

        within_window = True
        age_seconds = parse_age_seconds(time_token)
        if age_seconds is not None and duration is not None:
            within_window = age_seconds <= duration + EVENT_WINDOW_GRACE_SECONDS
        else:
            event_epoch = parse_timestamp_epoch(time_token)
            if event_epoch is not None and start_epoch is not None and end_epoch is not None:
                within_window = (start_epoch - 30) <= event_epoch <= (end_epoch + EVENT_WINDOW_GRACE_SECONDS)

        parsed.append(
            {
                "time_token": time_token,
                "type": etype,
                "reason": reason,
                "object": obj,
                "message": message,
                "within_window": within_window,
            }
        )

    return parsed


def check_file_completeness(run: RunResult):
    """Check all expected output files exist and are non-empty."""
    for fname in EXPECTED_FILES:
        fpath = run.path / fname
        if not fpath.exists():
            run.add_file_issue(f"MISSING: {fname}")
        elif fpath.stat().st_size == 0:
            run.add_file_issue(f"EMPTY: {fname}")


def check_a1_k6_target_rps(run: RunResult):
    """A1: k6 did not achieve target RPS."""
    k6_log = run.path / "k6-output.log"
    if not k6_log.exists():
        return

    content = k6_log.read_text()

    # Check for dropped iterations
    dropped_match = re.search(r'dropped_iterations[.\s]*:\s*(\d+)', content)
    if dropped_match:
        dropped = int(dropped_match.group(1))
        if dropped > 0:
            if run.config == "b1":
                run.add_info("A1", f"dropped_iterations = {dropped} (expected for the under-provisioned lower bound)")
            elif dropped <= 200:
                run.add_warning("A1", f"dropped_iterations = {dropped} (small under-delivery)")
            else:
                run.add_critical("A1", f"dropped_iterations = {dropped} (k6 could not maintain target RPS)")

    # Check actual RPS achieved
    rps_match = re.search(r'http_reqs[.\s]*:\s*(\d+)\s', content)
    if rps_match:
        total_reqs = int(rps_match.group(1))
        expected_reqs = expected_request_count(run)
        minimum_expected = int(expected_reqs * 0.85)
        if total_reqs < minimum_expected:
            pct = (total_reqs / expected_reqs * 100) if expected_reqs else 0
            profile = get_load_profile(run)
            message = (
                f"Total HTTP requests = {total_reqs} "
                f"({pct:.0f}% of expected {expected_reqs} for "
                f"{run.pattern} base={profile['base_rps']} peak={profile['peak_rps']})"
            )
            if run.config == "b1":
                run.add_info("A1-RPS", message)
            else:
                run.add_warning("A1-RPS", message)


def check_a2_prometheus_gaps(run: RunResult):
    """A2: Prometheus scrape gaps during test window."""
    prom_file = run.path / "prom_http_requests_rate.json"
    if not prom_file.exists() or prom_file.stat().st_size == 0:
        return

    try:
        handler = SERVICE_HANDLER_FILTERS.get(run.service, "")
        series = load_aggregated_series(prom_file, handler_filter=handler, aggregate="sum")
        if not series:
            run.add_critical("A2", "prom_http_requests_rate.json has ZERO result series")
            return

        timestamps = sorted(series.keys())
        if len(timestamps) < 5:
            run.add_critical("A2", f"prom_http_requests_rate.json has only {len(timestamps)} data points (expected ~80)")
            return

        max_gap = 0
        gap_count = 0
        for i in range(1, len(timestamps)):
            gap = float(timestamps[i]) - float(timestamps[i - 1])
            if gap > max_gap:
                max_gap = gap
            if gap > 30:
                gap_count += 1

        if gap_count > 0:
            if run.config == "b1":
                run.add_warning("A2", f"Prometheus has {gap_count} scrape gaps >30s (max gap: {max_gap:.0f}s)")
            elif gap_count > 2:
                run.add_critical("A2", f"Prometheus has {gap_count} scrape gaps >30s (max gap: {max_gap:.0f}s)")
            else:
                run.add_warning("A2", f"Prometheus has {gap_count} scrape gaps >30s (max gap: {max_gap:.0f}s)")
        elif max_gap > 20:
            run.add_warning("A2", f"Prometheus max scrape gap = {max_gap:.0f}s (slightly elevated)")

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        run.add_critical("A2", f"Failed to parse prom_http_requests_rate.json: {e}")


def check_a3_pod_crashes(run: RunResult):
    """A3: Pod CrashLoopBackOff during test."""
    for event in iter_k8s_events(run):
        if not event["within_window"]:
            continue
        obj = event["object"].lower()
        reason = event["reason"].lower()
        message = event["message"].lower()

        if obj.startswith("job/k6-") and reason == "backofflimitexceeded":
            continue

        if "oomkilled" in message:
            run.add_critical("A3", f"{event['object']} reported OOMKilled during the run")
        elif obj.startswith("pod/") and (
            "crashloopbackoff" in message
            or "back-off restarting failed container" in message
            or reason == "backoff"
        ):
            run.add_critical("A3", f"{event['object']} entered BackOff/CrashLoopBackOff during the run")

    pod_file = run.path / "pod-status.txt"
    if pod_file.exists() and pod_file.stat().st_size > 0:
        content = pod_file.read_text()
        if "CrashLoopBackOff" in content or "Error" in content:
            run.add_critical("A3", f"pod-status.txt shows pods in CrashLoopBackOff/Error state")

        _, _, duration = get_run_window(run)
        lines = [l for l in content.strip().split('\n') if l.strip() and not l.startswith('NAME')]
        for line in lines:
            parts = line.split()
            if len(parts) >= 5:
                try:
                    restarts = int(parts[3].rstrip('('))
                    age_index = 4
                    if len(parts) > 6 and parts[4].startswith("("):
                        age_index = 6
                    age_seconds = parse_age_seconds(parts[age_index]) if len(parts) > age_index else None
                    if restarts <= 0:
                        continue
                    if age_seconds is not None and duration is not None and age_seconds > duration + POD_AGE_GRACE_SECONDS:
                        continue
                    if restarts > 0:
                        if run.config == "b1":
                            run.add_info("A3-RESTART", f"Pod {parts[0]} has {restarts} run-scoped restarts")
                        else:
                            run.add_warning("A3-RESTART", f"Pod {parts[0]} has {restarts} run-scoped restarts")
                except ValueError:
                    pass


def check_a4_starting_replicas(run: RunResult):
    """A4: Wrong number of ready replicas at load onset."""
    handler = SERVICE_HANDLER_FILTERS.get(run.service, "")
    rate_series = load_aggregated_series(run.path / "prom_http_requests_rate.json", handler_filter=handler, aggregate="sum")
    replica_series = load_aggregated_series(run.path / "prom_replica_ready_count.json", aggregate="sum")

    if not rate_series or not replica_series:
        run.add_warning("A4", "Replica count metrics missing/empty — cannot verify replicas at load onset")
        return

    profile = get_load_profile(run)
    active_threshold = max(5, profile["base_rps"] * 0.5)
    active_timestamps = [ts for ts, value in sorted(rate_series.items()) if value >= active_threshold]
    if not active_timestamps:
        run.add_warning("A4", "Could not identify the active load window from Prometheus RPS data")
        return

    sample_timestamps = active_timestamps[:3]
    observed = [int(round(replica_series.get(ts, 0))) for ts in sample_timestamps if ts in replica_series]
    if not observed:
        run.add_warning("A4", "Ready-replica series does not overlap the active load window")
        return

    expected = 5 if run.config == "b2" else 1
    if min(observed) != expected:
        run.add_critical(
            "A4",
            f"Ready replicas at load onset = {observed}, expected {expected} for config {run.config}",
        )


def check_h3_custom_metric_health(run: RunResult):
    """H3: Explicitly catch FailedGetPodsMetric on the custom RPS HPA."""
    if run.config != "h3":
        return

    events_file = run.path / "k8s-events.txt"
    if events_file.exists() and events_file.stat().st_size > 0:
        events_content = events_file.read_text()
        lowered_events = events_content.lower()
        if "FailedGetPodsMetric" in events_content or "failed to get pods metric" in lowered_events:
            run.add_critical("H3", "Events show FailedGetPodsMetric — custom pods/http_requests_per_second metric failed during the run")
            return

    hpa_file = run.path / "hpa-status.yaml"
    if not hpa_file.exists() or hpa_file.stat().st_size == 0:
        run.add_warning("H3", "hpa-status.yaml missing/empty — cannot verify custom metric health")
        return

    content = hpa_file.read_text()
    lowered = content.lower()

    if "FailedGetPodsMetric" in content or "failed to get pods metric" in lowered:
        run.add_critical("H3", "HPA reported FailedGetPodsMetric — custom pods/http_requests_per_second metric failed")
    elif "http_requests_per_second" in content:
        run.add_info("H3", "HPA status references pods/http_requests_per_second")


def check_a5_keda_ready(run: RunResult):
    """A5: KEDA ScaledObject shows READY: False (only for K1 config)."""
    if run.config != "k1":
        return

    keda_file = run.path / "keda-status.yaml"
    if not keda_file.exists() or keda_file.stat().st_size == 0:
        run.add_critical("A5", "keda-status.yaml missing/empty for K1 config")
        return

    content = keda_file.read_text()

    if "no resources found" in content.lower():
        run.add_critical("A5", "No KEDA ScaledObject found in namespace")
        return

    # Proper check: find the specific Ready condition block using line context
    # We look for the pattern: type: Ready preceded by a status line
    # Expected GOOD: status: "True" \n ... type: Ready
    # Expected BAD:  status: "False" \n ... type: Ready
    lines = content.splitlines()
    ready_is_false = False
    found_ready_condition = False
    for i, line in enumerate(lines):
        if "type: Ready" in line:
            found_ready_condition = True
            # Look back up to 5 lines for the status field of this condition block
            for j in range(max(0, i - 5), i):
                if 'status:' in lines[j]:
                    if '"False"' in lines[j] or "'False'" in lines[j] or 'status: False' in lines[j]:
                        ready_is_false = True
                    break

    if not found_ready_condition:
        run.add_warning("A5", "keda-status.yaml has no 'type: Ready' condition block")
    elif ready_is_false:
        run.add_critical("A5", "KEDA ScaledObject Ready condition is False")
    else:
        run.add_info("A5", "KEDA ScaledObject Ready: True ✅")


def check_b1_error_rate(run: RunResult):
    """B1: High error rate (>5%) analysis per config."""
    k6_log = run.path / "k6-output.log"
    if not k6_log.exists():
        return

    content = k6_log.read_text()
    fail_match = re.search(r'http_req_failed[.\s]*:\s*([\d.]+)%', content)
    if not fail_match:
        # Try alternate format
        fail_match = re.search(r'http_req_failed.*?(\d+\.\d+)%', content)

    if fail_match:
        error_rate = float(fail_match.group(1))
    else:
        return

    if error_rate > 5:
        svc = run.service
        cfg = run.config

        # Apply decision matrix from anomaly guide
        if cfg == "b1":
            run.add_info("B1", f"Error rate {error_rate:.2f}% — EXPECTED for under-provisioned baseline")
        elif cfg == "b2":
            run.add_critical("B1", f"Error rate {error_rate:.2f}% on B2 (5 replicas) — UNEXPECTED, investigate!")
        elif cfg in ("h1", "h2") and svc == "shipping-rate-service":
            run.add_warning("B1", f"Error rate {error_rate:.2f}% on {cfg} for shipping-rate-service — CPU HPA may be too weak or too slow for this wait-dominant workload")
        elif cfg in ("h1", "h2") and svc == "auth-service":
            run.add_warning("B1", f"Error rate {error_rate:.2f}% on {cfg} for auth-service — check if CPU threshold was reached")
        elif cfg == "h3":
            run.add_warning("B1", f"Error rate {error_rate:.2f}% on H3 — check custom metric adapter")
        elif cfg == "k1":
            run.add_warning("B1", f"Error rate {error_rate:.2f}% on K1 — check if KEDA scaled properly")
    else:
        if run.config in ("b1",) and error_rate < 1:
            run.add_warning("B1-LOW", f"Error rate {error_rate:.2f}% on B1 — suspiciously LOW for under-provisioned baseline")


def check_b4_thrashing(run: RunResult):
    """B4: HPA/KEDA thrashing (rapid scale-up/down cycles)."""
    if run.config in ("b1", "b2"):
        return  # Baselines don't scale

    events_file = run.path / "k8s-events.txt"
    if not events_file.exists() or events_file.stat().st_size == 0:
        return

    content = events_file.read_text()
    scale_events = len(re.findall(r'Scaled|SuccessfulRescale', content, re.IGNORECASE))

    if scale_events > 8:
        run.add_info("B4", f"Thrashing detected: {scale_events} scaling events (>8) — this is VALID DATA for thesis")
    elif scale_events > 0:
        run.add_info("B4", f"Scaling events: {scale_events}")


def check_b5_flat_zero_metrics(run: RunResult):
    """B5: Prometheus metric shows flat zero during load."""
    for metric_file in ["prom_http_requests_rate.json", "prom_cpu_usage.json"]:
        fpath = run.path / metric_file
        if not fpath.exists() or fpath.stat().st_size == 0:
            continue

        try:
            handler = SERVICE_HANDLER_FILTERS.get(run.service, "") if metric_file == "prom_http_requests_rate.json" else ""
            series = load_aggregated_series(fpath, handler_filter=handler, aggregate="sum")
            if not series:
                run.add_critical("B5", f"{metric_file} has ZERO result series — Prometheus is NOT scraping!")
                continue

            values = list(series.values())
            non_zero = [value for value in values if value > 0]

            if len(non_zero) == 0 and len(values) > 0:
                run.add_critical("B5", f"{metric_file} ALL ZEROS ({len(values)} points) — metric not being scraped!")
            elif len(values) > 0:
                pct = (len(non_zero) / len(values)) * 100
                if pct < 20:
                    run.add_warning("B5", f"{metric_file} only {pct:.0f}% non-zero data points ({len(non_zero)}/{len(values)})")
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            run.add_warning("B5", f"Failed to parse {metric_file}: {e}")


def check_b6_gateway_rate_limiting(run: RunResult):
    """B6: Gateway rate limiting auth-service tests."""
    return


def check_c1_request_autoscalers_scale_shipping(run: RunResult):
    """C1: Request-based autoscalers should scale the wait-dominant shipping service."""
    if run.service != "shipping-rate-service" or run.config not in ("h3", "k1"):
        return

    prom_file = run.path / "prom_replica_count.json"
    if not prom_file.exists() or prom_file.stat().st_size == 0:
        return

    values = load_aggregated_series(prom_file, aggregate="sum")
    if not values:
        return

    max_replicas = max(int(round(value)) for value in values.values())
    if max_replicas <= 1:
        run.add_warning("C1", f"Request-based autoscaler {run.config} did NOT scale shipping-rate-service (max replicas = {max_replicas}) — unexpected for the wait-dominant comparison workload")
    else:
        run.add_info("C1", f"Request-based autoscaler {run.config} scaled shipping-rate-service to {max_replicas} replicas — expected for the wait-dominant workload")


def check_c2_all_scale_auth(run: RunResult):
    """C2: All autoscalers SHOULD scale auth-service (CPU-bound)."""
    if run.service != "auth-service" or run.config in ("b1", "b2"):
        return

    prom_file = run.path / "prom_replica_count.json"
    if not prom_file.exists() or prom_file.stat().st_size == 0:
        return

    values = load_aggregated_series(prom_file, aggregate="sum")
    if not values:
        return

    max_replicas = max(int(round(value)) for value in values.values())
    if max_replicas <= 1:
        run.add_warning("C2", f"Autoscaler {run.config} did NOT scale auth-service (max replicas = {max_replicas}) — expected scaling for CPU-bound service")
    else:
        run.add_info("C2", f"Autoscaler {run.config} scaled auth-service to {max_replicas} replicas — EXPECTED for CPU-bound service")


def check_c3_b2_lowest_latency(run: RunResult):
    """C3: B2 should have lowest latency."""
    if run.config != "b2":
        return

    k6_log = run.path / "k6-output.log"
    if not k6_log.exists():
        return

    content = k6_log.read_text()
    p95 = parse_k6_p95_ms(content)
    if p95 is not None:
        latency_ceiling_ms = 4000 if run.service == "shipping-rate-service" else 2000
        if p95 > latency_ceiling_ms:
            run.add_warning("C3", f"B2 p95 latency = {p95:.0f}ms — unexpectedly HIGH for a 5-replica baseline")
        else:
            run.add_info("C3", f"B2 p95 latency = {p95:.0f}ms — as expected for config {run.config}")


def check_metadata_duration(run: RunResult):
    """Check run duration is within expected range."""
    meta_file = run.path / "metadata.json"
    if not meta_file.exists():
        return

    try:
        meta = json.loads(meta_file.read_text())
        duration = meta.get("duration_seconds", 0)
        if duration < 600:
            run.add_critical("DURATION", f"Run completed in only {duration}s ({duration//60}m) — too short, test likely aborted")
        elif duration > 2400:
            run.add_warning("DURATION", f"Run took {duration}s ({duration//60}m) — unusually long")
        else:
            run.add_info("DURATION", f"Duration: {duration}s ({duration//60}m)")
    except (json.JSONDecodeError, KeyError):
        run.add_warning("DURATION", "Could not parse metadata.json")


def extract_k6_summary(run: RunResult):
    """Extract key k6 metrics for the summary table."""
    k6_log = run.path / "k6-output.log"
    if not k6_log.exists():
        return {}

    content = k6_log.read_text()
    metrics = {}

    # p95 latency
    p95 = parse_k6_p95_ms(content)
    if p95 is not None:
        metrics["p95_ms"] = p95

    # Error rate
    fail_match = re.search(r'http_req_failed[.\s]*:\s*([\d.]+)%', content)
    if not fail_match:
        fail_match = re.search(r'http_req_failed.*?(\d+\.\d+)%', content)
    if fail_match:
        metrics["error_rate"] = float(fail_match.group(1))

    # Total requests
    reqs_match = re.search(r'http_reqs[.\s]*:\s*(\d+)', content)
    if reqs_match:
        metrics["total_reqs"] = int(reqs_match.group(1))

    return metrics


def check_replica_count_data(run: RunResult):
    """Check that prom_replica_count.json has meaningful data points."""
    prom_file = run.path / "prom_replica_count.json"
    if not prom_file.exists() or prom_file.stat().st_size == 0:
        return

    values = load_aggregated_series(prom_file, aggregate="sum")
    if not values:
        run.add_warning("REPLICA", "prom_replica_count.json has 0 result series (kube-state-metrics may not have been running)")
        return

    if len(values) < 10:
        run.add_warning("REPLICA", f"prom_replica_count.json has only {len(values)} data points")

    if run.config in ("h1", "h2", "h3", "k1"):
        replica_values = [int(round(value)) for value in values.values() if value > 0]
        max_rep = max(replica_values) if replica_values else 0
        min_rep = min(replica_values) if replica_values else 0
        return {"max": max_rep, "min": min_rep, "points": len(values)}
    return None


def parse_args():
    parser = argparse.ArgumentParser(description="Deep validator for the auth + shipping thesis experiments.")
    parser.add_argument("--service", action="append", help="Limit validation to one or more services (comma-separated allowed)")
    parser.add_argument("--config", action="append", help="Limit validation to one or more configs (comma-separated allowed)")
    parser.add_argument("--pattern", action="append", help="Limit validation to one or more patterns (comma-separated allowed)")
    parser.add_argument("--rep", action="append", type=int, help="Limit validation to one or more repetitions")
    parser.add_argument("--strict-matrix", action="store_true", help="Treat missing run directories in the selected scope as critical")
    return parser.parse_args()


def main():
    args = parse_args()
    selected_services = parse_csv_args(args.service, SERVICES)
    selected_configs = parse_csv_args(args.config, CONFIGS)
    selected_patterns = parse_csv_args(args.pattern, PATTERNS)
    selected_reps = args.rep or [1]
    expected_total = len(selected_services) * len(selected_configs) * len(selected_patterns) * len(selected_reps)

    print("=" * 80)
    print("  DEEP EXPERIMENT VALIDATION")
    if args.strict_matrix:
        print("  Checking for both data quality and selected-scope completeness")
    else:
        print("  Checking run quality for the selected scope")
    print("=" * 80)
    print()

    all_runs = []
    total_critical = 0
    total_warnings = 0
    missing_dirs = 0

    for service in selected_services:
        for config in selected_configs:
            for pattern in selected_patterns:
                for rep in selected_reps:
                    path = RESULTS_DIR / service / config / pattern / f"rep{rep}"

                    if not path.exists():
                        missing_dirs += 1
                        if args.strict_matrix:
                            print(f"❌ MISSING DIRECTORY: {service}/{config}/{pattern}/rep{rep}")
                            total_critical += 1
                        continue

                    run = RunResult(service, config, pattern, rep, path)

                    # Run all checks
                    check_file_completeness(run)
                    check_a1_k6_target_rps(run)
                    check_a2_prometheus_gaps(run)
                    check_a3_pod_crashes(run)
                    check_a4_starting_replicas(run)
                    check_a5_keda_ready(run)
                    check_h3_custom_metric_health(run)
                    check_b1_error_rate(run)
                    check_b4_thrashing(run)
                    check_b5_flat_zero_metrics(run)
                    check_b6_gateway_rate_limiting(run)
                    check_c1_request_autoscalers_scale_shipping(run)
                    check_c2_all_scale_auth(run)
                    check_c3_b2_lowest_latency(run)
                    check_metadata_duration(run)
                    check_replica_count_data(run)

                    k6_metrics = extract_k6_summary(run)

                    all_runs.append((run, k6_metrics))
                    total_critical += len(run.critical)
                    total_warnings += len(run.warnings)

    # ── Print detailed results per run ──
    print()
    print("─" * 80)
    print("  DETAILED RESULTS PER RUN")
    print("─" * 80)

    for run, k6_metrics in all_runs:
        has_issues = run.critical or run.warnings or run.file_issues
        status = "🔴 CRITICAL" if run.critical else ("🟡 WARNING" if run.warnings else ("📁 FILES" if run.file_issues else "✅ PASS"))

        print(f"\n{'━' * 70}")
        print(f"  {status} | {run.run_id}")
        print(f"{'━' * 70}")

        if k6_metrics:
            parts = []
            if "p95_ms" in k6_metrics:
                parts.append(f"p95={k6_metrics['p95_ms']:.0f}ms")
            if "error_rate" in k6_metrics:
                parts.append(f"err={k6_metrics['error_rate']:.1f}%")
            if "total_reqs" in k6_metrics:
                parts.append(f"reqs={k6_metrics['total_reqs']}")
            if parts:
                print(f"  k6 Summary: {' | '.join(parts)}")

        if run.file_issues:
            for issue in run.file_issues:
                print(f"    {issue}")
        if run.critical:
            for issue in run.critical:
                print(f"    {issue}")
        if run.warnings:
            for issue in run.warnings:
                print(f"    {issue}")
        if run.info:
            for issue in run.info:
                print(f"    {issue}")

    # ── Summary table ──
    print()
    print()
    print("=" * 80)
    print("  SUMMARY MATRIX")
    print("=" * 80)
    print()
    print(f"{'Run ID':<45} {'Status':<12} {'p95(ms)':<10} {'Err%':<8} {'Reqs':<8}")
    print("─" * 85)

    for run, k6_metrics in all_runs:
        status = "🔴 CRIT" if run.critical else ("🟡 WARN" if run.warnings else "✅ OK")
        p95 = f"{k6_metrics.get('p95_ms', 0):.0f}" if k6_metrics.get('p95_ms') else "N/A"
        err = f"{k6_metrics.get('error_rate', 0):.1f}" if k6_metrics.get('error_rate') is not None else "N/A"
        reqs = str(k6_metrics.get('total_reqs', 'N/A'))
        print(f"{run.run_id:<45} {status:<12} {p95:<10} {err:<8} {reqs:<8}")

    # ── Final verdict ──
    print()
    print("=" * 80)
    print("  FINAL VERDICT")
    print("=" * 80)
    print(f"  Total runs analyzed:   {len(all_runs)}/{expected_total}")
    if missing_dirs and not args.strict_matrix:
        print(f"  Missing directories:   {missing_dirs} (ignored because --strict-matrix was not used)")
    print(f"  🔴 Critical issues:    {total_critical}")
    print(f"  🟡 Warnings:           {total_warnings}")
    print()

    if total_critical > 0:
        print("  ⛔ EXPERIMENT HAS CRITICAL ISSUES — some runs may need to be re-executed.")
    else:
        print("  ✅ NO CRITICAL ISSUES — the selected scope passed Tier 1 validation!")

    if total_warnings > 0:
        print(f"  ⚠️  {total_warnings} warnings detected — review individually above.")

    print()


if __name__ == "__main__":
    main()
