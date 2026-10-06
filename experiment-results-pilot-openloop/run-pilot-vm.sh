#!/usr/bin/env bash
# Runs the open-loop pilot to completion (resuming after any failure), then stops AKS.
# AKS is stopped ONLY when every planned run is DONE and the runner has exited.
cd /home/kevin/e-commerce-vus || exit 1
DIR=experiment-results-pilot-openloop
TOTAL=$(grep -cvE '^[[:space:]]*(#|$)' "$DIR/runlist.txt")
stall=0; prev=-1; attempt=0
while true; do
  done_n=$(grep -c '^DONE:' "$DIR/.pilot-state" 2>/dev/null); done_n=${done_n:-0}
  [ "$done_n" -ge "$TOTAL" ] && break
  if [ "$done_n" -le "$prev" ]; then stall=$((stall + 1)); else stall=0; fi
  if [ "$stall" -ge 4 ]; then
    echo "[pilot-vm] $(date -u) no progress in 4 attempts at ${done_n}/${TOTAL} - giving up; AKS left RUNNING"
    exit 1
  fi
  prev=$done_n; attempt=$((attempt + 1))
  echo "[pilot-vm] $(date -u) attempt ${attempt}: ${done_n}/${TOTAL} done"
  bash scripts/run-pilot-openloop.sh run --resume
  echo "[pilot-vm] $(date -u) runner exited with $?"
  sleep 60
done
echo "[pilot-vm] $(date -u) all ${TOTAL} runs DONE"
tar czf /home/kevin/pilot-openloop-results.tgz "$DIR" && ls -la /home/kevin/pilot-openloop-results.tgz
echo "[pilot-vm] $(date -u) k6 jobs still present (should be none):"
kubectl get jobs -n ecommerce -l app=k6 --no-headers 2>&1
echo "[pilot-vm] $(date -u) stopping AKS"
az aks stop -g ecommerce -n ecommerce-aks
echo "[pilot-vm] $(date -u) AKS power state: $(az aks show -g ecommerce -n ecommerce-aks --query powerState.code -o tsv)"
