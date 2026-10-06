#!/usr/bin/env bash
# Runs an open-loop plan unattended on ecommerce-vm (resuming after any failure),
# then archives the results and stops AKS.
#
# Usage (on the VM, from anywhere): run-openloop-vm.sh <results-dir> [stop-aks: yes|no] [stop-at: N]
#   stop-at  stop once N runs are DONE (default: the whole run list), e.g. 72 for the
#            campaign's robustness gate after rep blocks 1-2. Runs execute in plan
#            order and each invocation is capped at the runs still missing, so N DONE
#            means plan positions 1..N are complete.
#
# If the runner makes no progress in 4 consecutive attempts the script gives up and
# still stops AKS (nobody is watching), saying so in the log.
cd /home/kevin/e-commerce-vus || exit 1
DIR="$1"; STOP_AKS="${2:-yes}"
export OPENLOOP_RESULTS_DIR="$DIR"
TOTAL=$(grep -cvE '^[[:space:]]*(#|$)' "$DIR/runlist.txt")
STOP_AT="${3:-$TOTAL}"
stall=0; prev=-1; attempt=0; outcome="finished"
while true; do
  done_n=$(grep -c '^DONE:' "$DIR/.pilot-state" 2>/dev/null); done_n=${done_n:-0}
  [ "$done_n" -ge "$STOP_AT" ] && break
  if [ "$done_n" -le "$prev" ]; then stall=$((stall + 1)); else stall=0; fi
  if [ "$stall" -ge 4 ]; then outcome="GAVE UP at ${done_n}/${STOP_AT}"; break; fi
  prev=$done_n; attempt=$((attempt + 1))
  echo "[openloop-vm] $(date -u) attempt ${attempt}: ${done_n}/${STOP_AT} done (${TOTAL} planned, $DIR)"
  bash scripts/run-pilot-openloop.sh run --resume --max-runs $((STOP_AT - done_n))
  echo "[openloop-vm] $(date -u) runner exited with $?"
  sleep 60
done
echo "[openloop-vm] $(date -u) ${outcome}: ${done_n}/${STOP_AT} ($DIR)"
tar czf "/home/kevin/$(basename "$DIR")-results.tgz" "$DIR" && ls -la "/home/kevin/$(basename "$DIR")-results.tgz"
echo "[openloop-vm] $(date -u) k6 jobs still present (should be none):"
kubectl get jobs -n ecommerce -l app=k6 --no-headers 2>&1
if [ "$STOP_AKS" = "yes" ]; then
  echo "[openloop-vm] $(date -u) stopping AKS"
  az aks stop -g ecommerce -n ecommerce-aks
  echo "[openloop-vm] $(date -u) AKS power state: $(az aks show -g ecommerce -n ecommerce-aks --query powerState.code -o tsv)"
fi
