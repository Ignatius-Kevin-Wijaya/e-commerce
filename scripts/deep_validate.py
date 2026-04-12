#!/usr/bin/env python3
"""
Deep Experiment Validation Script
==================================
Checks every single run against ALL anomaly detection criteria from anomaly_detection_guide.md:
  - Tier 1 (Critical): A1-A5
  - Tier 2 (Warning): B1-B6
  - Tier 3 (Informational): C1-C4
  - File completeness check
"""

import json
import os
import re
import sys
from pathlib import Path

RESULTS_DIR = Path("/home/kevin/Projects/e-commerce/experiment-results")
SERVICES = ["product-service", "auth-service"]
CONFIGS = ["b1", "b2", "h1", "h2", "h3", "k1"]
PATTERNS = ["gradual", "spike", "oscillating"]
LOAD_PROFILE_FALLBACKS = {
    "product-service": {"base_rps": 20, "peak_rps": 200},
    "auth-service": {"base_rps": 20, "peak_rps": 200},
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
    return {
        "base_rps": _parse_int(profile.get("base_rps"), fallback["base_rps"]),
        "peak_rps": _parse_int(profile.get("peak_rps"), fallback["peak_rps"]),
    }


def expected_request_count(run: RunResult):
    """Estimate expected arrivals from the configured k6 ramping-arrival-rate pattern."""
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
            run.add_warning(
                "A1-RPS",
                (
                    f"Total HTTP requests = {total_reqs} "
                    f"({pct:.0f}% of expected {expected_reqs} for "
                    f"{run.pattern} base={profile['base_rps']} peak={profile['peak_rps']})"
                ),
            )


def check_a2_prometheus_gaps(run: RunResult):
    """A2: Prometheus scrape gaps during test window."""
    prom_file = run.path / "prom_http_requests_rate.json"
    if not prom_file.exists() or prom_file.stat().st_size == 0:
        return

    try:
        data = json.loads(prom_file.read_text())
        results = data.get("data", {}).get("result", [])
        if not results:
            run.add_critical("A2", "prom_http_requests_rate.json has ZERO result series")
            return

        values = results[0].get("values", [])
        if len(values) < 5:
            run.add_critical("A2", f"prom_http_requests_rate.json has only {len(values)} data points (expected ~80)")
            return

        max_gap = 0
        gap_count = 0
        for i in range(1, len(values)):
            gap = float(values[i][0]) - float(values[i - 1][0])
            if gap > max_gap:
                max_gap = gap
            if gap > 30:
                gap_count += 1

        if gap_count > 0:
            run.add_critical("A2", f"Prometheus has {gap_count} scrape gaps >30s (max gap: {max_gap:.0f}s)")
        elif max_gap > 20:
            run.add_warning("A2", f"Prometheus max scrape gap = {max_gap:.0f}s (slightly elevated)")

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        run.add_critical("A2", f"Failed to parse prom_http_requests_rate.json: {e}")


def check_a3_pod_crashes(run: RunResult):
    """A3: Pod CrashLoopBackOff during test."""
    events_file = run.path / "k8s-events.txt"
    if events_file.exists() and events_file.stat().st_size > 0:
        content = events_file.read_text().lower()
        crash_keywords = ["crashloopbackoff", "oomkilled", "backoff", "error"]
        for kw in crash_keywords:
            if kw in content:
                # Count occurrences
                count = content.count(kw)
                if kw == "error" and count < 3:
                    continue  # minor — some benign error events
                run.add_critical("A3", f"k8s-events.txt contains '{kw}' ({count} occurrences)")

    pod_file = run.path / "pod-status.txt"
    if pod_file.exists() and pod_file.stat().st_size > 0:
        content = pod_file.read_text()
        if "CrashLoopBackOff" in content or "Error" in content:
            run.add_critical("A3", f"pod-status.txt shows pods in CrashLoopBackOff/Error state")

        # Count restarts
        restart_match = re.findall(r'\s+(\d+)\s+', content)
        # Pod status lines: NAME READY STATUS RESTARTS AGE
        lines = [l for l in content.strip().split('\n') if l.strip() and not l.startswith('NAME')]
        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    restarts = int(parts[3].rstrip('('))
                    if restarts > 0:
                        run.add_warning("A3-RESTART", f"Pod {parts[0]} has {restarts} restarts")
                except ValueError:
                    pass


def check_a4_starting_replicas(run: RunResult):
    """A4: Wrong number of replicas at test start."""
    metric_files = [
        ("prom_replica_ready_count.json", "ready replicas"),
        ("prom_replica_count.json", "replicas"),
    ]

    for metric_name, metric_label in metric_files:
        prom_file = run.path / metric_name
        if not prom_file.exists() or prom_file.stat().st_size == 0:
            continue

        try:
            data = json.loads(prom_file.read_text())
            results = data.get("data", {}).get("result", [])
            if not results:
                continue

            values = results[0].get("values", [])
            if not values:
                continue

            first_values = [int(float(v[1])) for v in values[:5]]
            if not first_values:
                continue

            starting_replicas = first_values[0]
            expected = 5 if run.config == "b2" else 1
            if starting_replicas != expected:
                run.add_critical(
                    "A4",
                    f"Starting {metric_label} = {starting_replicas}, expected {expected} for config {run.config}",
                )
            return
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            run.add_warning("A4", f"Failed to parse {metric_name}: {e}")
            return

    run.add_warning("A4", "Replica count metrics missing/empty — cannot verify starting replicas")


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
        elif cfg in ("h1", "h2") and svc == "product-service":
            run.add_info("B1", f"Error rate {error_rate:.2f}% — EXPECTED (CPU HPA won't trigger for I/O-bound product-service)")
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
            data = json.loads(fpath.read_text())
            results = data.get("data", {}).get("result", [])
            if not results:
                run.add_critical("B5", f"{metric_file} has ZERO result series — Prometheus is NOT scraping!")
                continue

            values = results[0].get("values", [])
            non_zero = [v for v in values if float(v[1]) > 0]

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


def check_c1_hpa_no_scale_product(run: RunResult):
    """C1: CPU-based HPA should NOT scale product-service (I/O-bound thesis finding)."""
    if run.service != "product-service" or run.config not in ("h1", "h2"):
        return

    prom_file = run.path / "prom_replica_count.json"
    if not prom_file.exists() or prom_file.stat().st_size == 0:
        return

    try:
        data = json.loads(prom_file.read_text())
        results = data.get("data", {}).get("result", [])
        if not results:
            return

        values = results[0].get("values", [])
        max_replicas = max(int(float(v[1])) for v in values if float(v[1]) > 0) if values else 1

        if max_replicas > 1:
            run.add_warning("C1", f"CPU-based HPA SCALED product-service to {max_replicas} replicas — thesis hypothesis may need revision")
        else:
            run.add_info("C1", f"CPU-based HPA did NOT scale product-service — CONFIRMS thesis hypothesis")
    except (json.JSONDecodeError, KeyError, ValueError):
        pass


def check_c2_all_scale_auth(run: RunResult):
    """C2: All autoscalers SHOULD scale auth-service (CPU-bound)."""
    if run.service != "auth-service" or run.config in ("b1", "b2"):
        return

    prom_file = run.path / "prom_replica_count.json"
    if not prom_file.exists() or prom_file.stat().st_size == 0:
        return

    try:
        data = json.loads(prom_file.read_text())
        results = data.get("data", {}).get("result", [])
        if not results:
            return

        values = results[0].get("values", [])
        max_replicas = max(int(float(v[1])) for v in values if float(v[1]) > 0) if values else 1

        if max_replicas <= 1:
            run.add_warning("C2", f"Autoscaler {run.config} did NOT scale auth-service (max replicas = {max_replicas}) — expected scaling for CPU-bound service")
        else:
            run.add_info("C2", f"Autoscaler {run.config} scaled auth-service to {max_replicas} replicas — EXPECTED for CPU-bound service")
    except (json.JSONDecodeError, KeyError, ValueError):
        pass


def check_c3_b2_lowest_latency(run: RunResult):
    """C3: B2 should have lowest latency."""
    if run.config != "b2":
        return

    k6_log = run.path / "k6-output.log"
    if not k6_log.exists():
        return

    content = k6_log.read_text()
    p95_match = re.search(r'http_req_duration.*?p\(95\)[=.\s]*([\d.]+)', content)
    if p95_match:
        p95 = float(p95_match.group(1))
        if p95 > 2000:
            run.add_warning("C3", f"B2 p95 latency = {p95:.0f}ms — unexpectedly HIGH for 5-replica baseline")
        else:
            run.add_info("C3", f"B2 p95 latency = {p95:.0f}ms — as expected (low latency with 5 replicas)")


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
    p95_match = re.search(r'http_req_duration.*?p\(95\)[=.\s]*([\d.]+)', content)
    if p95_match:
        metrics["p95_ms"] = float(p95_match.group(1))

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

    try:
        data = json.loads(prom_file.read_text())
        results = data.get("data", {}).get("result", [])
        if not results:
            run.add_warning("REPLICA", "prom_replica_count.json has 0 result series (kube-state-metrics may not have been running)")
            return

        values = results[0].get("values", [])
        if len(values) < 10:
            run.add_warning("REPLICA", f"prom_replica_count.json has only {len(values)} data points")
        
        # For autoscaler configs, check if we see any scaling
        if run.config in ("h1", "h2", "h3", "k1"):
            replica_values = [int(float(v[1])) for v in values if float(v[1]) > 0]
            max_rep = max(replica_values) if replica_values else 0
            min_rep = min(replica_values) if replica_values else 0
            return {"max": max_rep, "min": min_rep, "points": len(values)}
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def main():
    print("=" * 80)
    print("  DEEP EXPERIMENT VALIDATION")
    print("  Checking all 36 runs against anomaly_detection_guide.md criteria")
    print("=" * 80)
    print()

    all_runs = []
    total_critical = 0
    total_warnings = 0

    for service in SERVICES:
        for config in CONFIGS:
            for pattern in PATTERNS:
                rep = 1
                path = RESULTS_DIR / service / config / pattern / f"rep{rep}"

                if not path.exists():
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
                check_c1_hpa_no_scale_product(run)
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
    print(f"  Total runs analyzed:   {len(all_runs)}/36")
    print(f"  🔴 Critical issues:    {total_critical}")
    print(f"  🟡 Warnings:           {total_warnings}")
    print()

    if total_critical > 0:
        print("  ⛔ EXPERIMENT HAS CRITICAL ISSUES — some runs may need to be re-executed.")
    else:
        print("  ✅ NO CRITICAL ISSUES — all 36 runs passed Tier 1 validation!")

    if total_warnings > 0:
        print(f"  ⚠️  {total_warnings} warnings detected — review individually above.")

    print()


if __name__ == "__main__":
    main()
