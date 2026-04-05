#!/usr/bin/env bash
# ============================================================================
# Post-Run Validation — Scans all completed runs for anomalies
# ============================================================================
# Usage: bash scripts/validate-results.sh
#        bash scripts/validate-results.sh product-service    # Single service
# ============================================================================

set -euo pipefail

RESULTS_DIR="./experiment-results"
FILTER="${1:-}"

echo "================================================================"
echo "  EXPERIMENT RESULTS VALIDATION"
echo "================================================================"
echo ""

TOTAL=0
CRITICAL=0
WARNINGS=0

for metadata in $(find "${RESULTS_DIR}" -name "metadata.json" | sort); do
  dir=$(dirname "${metadata}")
  run_id=$(python3 -c "import json; print(json.load(open('${metadata}'))['run_id'])")
  service=$(python3 -c "import json; print(json.load(open('${metadata}'))['service'])")
  config=$(python3 -c "import json; print(json.load(open('${metadata}'))['config'])")

  # Filter by service if specified
  [[ -n "${FILTER}" && "${service}" != "${FILTER}" ]] && continue

  TOTAL=$((TOTAL + 1))
  issues=""

  # ── Check 1: k6 output exists ──────────────────────────────────────────────
  if [[ ! -f "${dir}/k6-output.log" ]] || [[ ! -s "${dir}/k6-output.log" ]]; then
    issues="${issues}\n  🔴 CRITICAL: No k6 output log"
    CRITICAL=$((CRITICAL + 1))
  else
    # ── Check 2: Dropped iterations (k6 couldn't generate enough RPS) ────────
    if grep -q "dropped_iterations" "${dir}/k6-output.log" 2>/dev/null; then
      dropped=$(grep "dropped_iterations" "${dir}/k6-output.log" | grep -oP '\d+' | head -1)
      if [[ -n "${dropped}" && "${dropped}" -gt 0 ]]; then
        issues="${issues}\n  🔴 CRITICAL: k6 dropped ${dropped} iterations (under-delivered RPS)"
        CRITICAL=$((CRITICAL + 1))
      fi
    fi

    # ── Check 3: Error rate ──────────────────────────────────────────────────
    fail_line=$(grep "http_req_failed" "${dir}/k6-output.log" 2>/dev/null || true)
    if [[ -n "${fail_line}" ]]; then
      fail_pct=$(echo "${fail_line}" | grep -oP '[\d.]+%' | head -1 | tr -d '%')
      if [[ -n "${fail_pct}" ]]; then
        # High error rate is expected for B1 and H1/H2 on product-service
        is_expected=false
        if [[ "${config}" == "b1" ]]; then is_expected=true; fi
        if [[ "${config}" == "h1" || "${config}" == "h2" ]] && [[ "${service}" == "product-service" ]]; then is_expected=true; fi

        if (( $(echo "${fail_pct} > 5" | bc -l) )); then
          if ${is_expected}; then
            issues="${issues}\n  🟢 INFO: Error rate ${fail_pct}% (expected for ${config}/${service})"
          else
            issues="${issues}\n  🟡 WARNING: Error rate ${fail_pct}% (unexpected for ${config})"
            WARNINGS=$((WARNINGS + 1))
          fi
        fi
      fi
    fi
  fi

  # ── Check 4: Prometheus data has content ───────────────────────────────────
  if [[ ! -f "${dir}/prom_http_requests_rate.json" ]] || [[ ! -s "${dir}/prom_http_requests_rate.json" ]]; then
    issues="${issues}\n  🔴 CRITICAL: No Prometheus RPS data"
    CRITICAL=$((CRITICAL + 1))
  else
    # Check for all-zeros (Prometheus not actually scraping)
    non_zero=$(python3 -c "
import json
try:
    data = json.load(open('${dir}/prom_http_requests_rate.json'))
    result = data.get('data',{}).get('result',[])
    if not result:
        print(0)
    else:
        values = result[0].get('values',[])
        nz = sum(1 for v in values if float(v[1]) > 0)
        print(nz)
except: print(-1)
" 2>/dev/null)
    if [[ "${non_zero}" == "0" ]] || [[ "${non_zero}" == "-1" ]]; then
      issues="${issues}\n  🔴 CRITICAL: Prometheus data is all zeros (scraping broken)"
      CRITICAL=$((CRITICAL + 1))
    fi

    # Check for scrape gaps > 30s
    gaps=$(python3 -c "
import json
try:
    data = json.load(open('${dir}/prom_http_requests_rate.json'))
    result = data.get('data',{}).get('result',[])
    if result:
        values = result[0].get('values',[])
        gap_count = sum(1 for i in range(1,len(values)) if float(values[i][0])-float(values[i-1][0]) > 30)
        print(gap_count)
    else: print(0)
except: print(-1)
" 2>/dev/null)
    if [[ -n "${gaps}" && "${gaps}" -gt 0 ]]; then
      if [[ "${config}" == "h3" || "${config}" == "k1" ]]; then
        issues="${issues}\n  🔴 CRITICAL: ${gaps} Prometheus scrape gaps >30s (H3/K1 depend on Prometheus)"
        CRITICAL=$((CRITICAL + 1))
      else
        issues="${issues}\n  🟡 WARNING: ${gaps} Prometheus scrape gaps >30s"
        WARNINGS=$((WARNINGS + 1))
      fi
    fi
  fi

  # ── Check 5: Run duration sanity ──────────────────────────────────────────
  duration=$(python3 -c "import json; print(json.load(open('${metadata}'))['duration_seconds'])" 2>/dev/null)
  if [[ -n "${duration}" ]]; then
    if [[ "${duration}" -lt 600 ]]; then
      issues="${issues}\n  🔴 CRITICAL: Run too short (${duration}s < 600s)"
      CRITICAL=$((CRITICAL + 1))
    elif [[ "${duration}" -gt 1200 ]]; then
      issues="${issues}\n  🟡 WARNING: Run too long (${duration}s > 1200s)"
      WARNINGS=$((WARNINGS + 1))
    fi
  fi

  # ── Check 6: Pod crashes ──────────────────────────────────────────────────
  if [[ -f "${dir}/k8s-events.txt" ]]; then
    crashes=$(grep -ci "CrashLoopBackOff\|OOMKilled\|BackOff\|Error" "${dir}/k8s-events.txt" 2>/dev/null || echo 0)
    if [[ "${crashes}" -gt 0 ]]; then
      issues="${issues}\n  🔴 CRITICAL: ${crashes} crash/error events detected"
      CRITICAL=$((CRITICAL + 1))
    fi
  fi

  # ── Report ─────────────────────────────────────────────────────────────────
  if [[ -n "${issues}" ]]; then
    echo "── ${run_id} ──"
    echo -e "${issues}"
    echo ""
  fi
done

echo "================================================================"
echo "  RESULTS: ${TOTAL} runs scanned"
echo "    🔴 Critical issues: ${CRITICAL}"
echo "    🟡 Warnings:        ${WARNINGS}"
if [[ ${CRITICAL} -eq 0 && ${WARNINGS} -eq 0 ]]; then
  echo "    ✅ All clean!"
fi
echo "================================================================"
