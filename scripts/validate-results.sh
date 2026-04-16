#!/usr/bin/env bash
# ============================================================================
# Post-Run Validation — Scans completed runs for anomalies
# ============================================================================
# Usage: bash scripts/validate-results.sh
#        bash scripts/validate-results.sh shipping-rate-service    # Single service
# ============================================================================

set -euo pipefail

RESULTS_DIR="./experiment-results"
FILTER="${1:-}"

python3 - "${RESULTS_DIR}" "${FILTER}" <<'PYEOF'
import json
import pathlib
import re
import sys

results_dir = pathlib.Path(sys.argv[1])
service_filter = sys.argv[2]

print("================================================================")
print("  EXPERIMENT RESULTS VALIDATION")
print("================================================================")
print("")

total = 0
critical = 0
warnings = 0
info = 0


def parse_k6_metrics(log_path: pathlib.Path):
    text = log_path.read_text(errors="ignore")

    def first_match(pattern):
        match = re.search(pattern, text, re.MULTILINE)
        return match.groups() if match else None

    dropped_match = first_match(r"dropped_iterations[^\n]*?(\d+)")
    dropped = int(dropped_match[0]) if dropped_match else 0

    fail_match = first_match(r"http_req_failed[^\n]*?([0-9.]+)%")
    fail_pct = float(fail_match[0]) if fail_match else None

    return {
        "dropped_iterations": dropped,
        "fail_pct": fail_pct,
    }


def parse_prometheus_stats(prom_path: pathlib.Path):
    data = json.loads(prom_path.read_text())
    result = data.get("data", {}).get("result", [])
    timestamps = set()
    non_zero = 0

    for series in result:
        for ts, value in series.get("values", []):
            timestamps.add(float(ts))
            if float(value) > 0:
                non_zero += 1

    sorted_ts = sorted(timestamps)
    gap_count = sum(1 for i in range(1, len(sorted_ts)) if sorted_ts[i] - sorted_ts[i - 1] > 30)

    return {
        "series_count": len(result),
        "non_zero_points": non_zero,
        "gap_count": gap_count,
    }


def parse_pod_status(pod_status_path: pathlib.Path):
    restarts = 0
    bad_statuses = []

    lines = pod_status_path.read_text().splitlines()
    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split()
        if len(cols) < 4:
            continue

        name = cols[0]
        status = cols[2]
        restart_count = cols[3]

        try:
            restarts += int(restart_count)
        except ValueError:
            pass

        if status not in ("Running", "Completed"):
            bad_statuses.append(f"{name}={status}")

    return {
        "restart_count": restarts,
        "bad_statuses": bad_statuses,
    }


def file_has_content(path: pathlib.Path):
    return path.exists() and path.stat().st_size > 0


for metadata_path in sorted(results_dir.rglob("metadata.json")):
    run_dir = metadata_path.parent
    metadata = json.loads(metadata_path.read_text())
    service = metadata["service"]
    config = metadata["config"]
    run_id = metadata["run_id"]

    if service_filter and service != service_filter:
        continue

    total += 1
    issues = []

    k6_log = run_dir / "k6-output.log"
    if not file_has_content(k6_log):
        issues.append(("critical", "No k6 output log"))
    else:
        k6_metrics = parse_k6_metrics(k6_log)
        dropped = k6_metrics["dropped_iterations"]
        fail_pct = k6_metrics["fail_pct"]

        if dropped > 0:
            if config == "b1":
                issues.append(("info", f"k6 dropped {dropped} iterations (expected for under-provisioned baseline)"))
            elif dropped <= 200:
                issues.append(("warning", f"k6 dropped {dropped} iterations (small under-delivery)"))
            else:
                issues.append(("critical", f"k6 dropped {dropped} iterations (under-delivered RPS)"))

        if fail_pct is not None and fail_pct > 5:
            if config == "b1":
                issues.append(("info", f"Error rate {fail_pct:.2f}% (expected for under-provisioned baseline)"))
            elif fail_pct > 20:
                issues.append(("critical", f"Error rate {fail_pct:.2f}%"))
            else:
                issues.append(("warning", f"Error rate {fail_pct:.2f}%"))

    prom_rate = run_dir / "prom_http_requests_rate.json"
    if not file_has_content(prom_rate):
        issues.append(("critical", "No Prometheus RPS data"))
    else:
        try:
            prom_stats = parse_prometheus_stats(prom_rate)
            if prom_stats["series_count"] == 0 or prom_stats["non_zero_points"] == 0:
                issues.append(("critical", "Prometheus data is empty or all zeros"))
            elif prom_stats["gap_count"] > 0:
                if config in ("h3", "k1") and prom_stats["gap_count"] > 2:
                    issues.append(("critical", f"{prom_stats['gap_count']} Prometheus scrape gaps >30s"))
                else:
                    issues.append(("warning", f"{prom_stats['gap_count']} Prometheus scrape gaps >30s"))
        except Exception as exc:
            issues.append(("critical", f"Failed to parse Prometheus data: {exc}"))

    duration = metadata.get("duration_seconds")
    if duration is not None:
        if duration < 900:
            issues.append(("critical", f"Run too short ({duration}s < 900s)"))
        elif duration > 1500:
            issues.append(("warning", f"Run unusually long ({duration}s > 1500s)"))

    pod_status = run_dir / "pod-status.txt"
    if file_has_content(pod_status):
        pod_stats = parse_pod_status(pod_status)
        if pod_stats["bad_statuses"]:
            issues.append(("critical", f"Pods not healthy at export: {', '.join(pod_stats['bad_statuses'])}"))
        if pod_stats["restart_count"] > 0:
            if config == "b1":
                issues.append(("info", f"Observed {pod_stats['restart_count']} pod restarts (expected under baseline overload)"))
            else:
                issues.append(("warning", f"Observed {pod_stats['restart_count']} pod restarts"))
    else:
        issues.append(("warning", "No pod-status snapshot"))

    hpa_status = run_dir / "hpa-status.yaml"
    keda_status = run_dir / "keda-status.yaml"
    if config in ("h1", "h2", "h3", "k1") and not file_has_content(hpa_status):
        issues.append(("warning", "Missing scoped HPA status export"))
    if config == "k1" and not file_has_content(keda_status):
        issues.append(("warning", "Missing scoped KEDA status export"))

    if issues:
        print(f"── {run_id} ──")
        for level, message in issues:
            if level == "critical":
                critical += 1
                prefix = "🔴 CRITICAL"
            elif level == "warning":
                warnings += 1
                prefix = "🟡 WARNING"
            else:
                info += 1
                prefix = "🟢 INFO"
            print(f"  {prefix}: {message}")
        print("")

print("================================================================")
print(f"  RESULTS: {total} runs scanned")
print(f"    🔴 Critical issues: {critical}")
print(f"    🟡 Warnings:        {warnings}")
print(f"    🟢 Info:            {info}")
if critical == 0 and warnings == 0:
    print("    ✅ All clean!")
print("================================================================")
PYEOF
