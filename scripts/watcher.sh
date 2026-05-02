#!/bin/bash
# watcher.sh: Monitors experiment state and validates each run upon completion

STATE_FILE="experiment-results/.experiment-state"
VALIDATION_LOG="experiment-results/live_validation.log"

mkdir -p "$(dirname "$STATE_FILE")"
touch "$STATE_FILE"

echo "==========================================================" > "$VALIDATION_LOG"
echo "  LIVE VALIDATION DASHBOARD — shipping-rate-service       " >> "$VALIDATION_LOG"
echo "  Started: $(date)                                        " >> "$VALIDATION_LOG"
echo "==========================================================" >> "$VALIDATION_LOG"

# Tail the state file, reading new lines as they are appended
tail -n 0 -f "$STATE_FILE" | while IFS= read -r line; do
    if [[ "$line" == DONE:shipping-rate-service_* ]]; then
        run_id="${line#DONE:}"
        # Parse run_id: shipping-rate-service_b1_gradual_rep1
        # Extract components
        config=$(echo "$run_id" | awk -F'_' '{print $2}')
        pattern=$(echo "$run_id" | awk -F'_' '{print $3}')
        rep_str=$(echo "$run_id" | awk -F'_' '{print $4}')
        rep="${rep_str#rep}"
        
        echo -e "\n[$(date +'%H:%M:%S')] 🔄 Run finished: $run_id" >> "$VALIDATION_LOG"
        echo "[$(date +'%H:%M:%S')] ⏳ Validating..." >> "$VALIDATION_LOG"
        
        # Run validator for this specific run
        # Output is captured
        validation_out=$(python3 scripts/deep_validate.py --service shipping-rate-service --config "$config" --pattern "$pattern" --rep "$rep" 2>&1)
        
        # Check verdict
        if echo "$validation_out" | grep -q "EXPERIMENT HAS CRITICAL ISSUES"; then
            echo "⛔ VERDICT: CRITICAL FAILED" >> "$VALIDATION_LOG"
            echo "$validation_out" | grep "🔴" >> "$VALIDATION_LOG"
        elif echo "$validation_out" | grep -q "warnings detected"; then
            echo "⚠️ VERDICT: PASSED WITH WARNINGS" >> "$VALIDATION_LOG"
            echo "$validation_out" | grep "🟡" >> "$VALIDATION_LOG"
        else
            echo "✅ VERDICT: PERFECT PASS" >> "$VALIDATION_LOG"
        fi
        
        echo "----------------------------------------------------------" >> "$VALIDATION_LOG"
    fi
done
