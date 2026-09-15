#!/usr/bin/env bash
# Continuous Optimization Loop
# Runs benchmarks, exports successful sessions, fine-tunes, swaps model, and repeats.
#
# Usage:
#   ./scripts/optimize_loop.sh
#   ./scripts/optimize_loop.sh --interval 3600  # custom interval in seconds
#   INTERVAL=1800 ./scripts/optimize_loop.sh     # custom interval via env var

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INTERVAL="${INTERVAL:-3600}"
DATA_DIR="finetune_data"
OUTPUT_DIR="finetune_output"
LOG_FILE="optimize_loop.log"
MAX_MODEL_TURNS="${MAX_MODEL_TURNS:-20}"
BENCHMARK_TIMEOUT="${BENCHMARK_TIMEOUT:-300}"

# Allow overriding interval via CLI argument
while [[ $# -gt 0 ]]; do
    case $1 in
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --benchmark-timeout)
            BENCHMARK_TIMEOUT="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--interval SECONDS] [--benchmark-timeout SECONDS]"
            exit 1
            ;;
    esac
done

cd "$PROJECT_ROOT"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

run_benchmarks() {
    log "=== Running benchmark suite ==="
    local output
    output=$(timeout "$BENCHMARK_TIMEOUT" python -c "
import json, sqlite3
from tests.benchmarks.runner import BenchmarkModel, run_benchmark_suite

# Use a fresh DB for benchmarks
import os
db_path = 'calib_test_tmp/benchmark_run.db'
if os.path.exists(db_path):
    os.remove(db_path)

model = BenchmarkModel()
results = run_benchmark_suite(model, db_path, max_rounds=$MAX_MODEL_TURNS)
print(json.dumps({'benchmark_results': results, 'db_path': db_path}))
" 2>&1) || {
        log "Benchmark run failed or timed out"
        return 1
    }
    log "Benchmark results: $output"
}

export_training_data() {
    log "=== Exporting training data ==="
    local count
    count=$(timeout 120 python main.py --profile lite --dry-run --export-data --export-path "$DATA_DIR" 2>&1) || true
    log "Exported training data: $count"
}

fine_tune_model() {
    log "=== Fine-tuning model ==="

    # Check if we have training data
    if [ ! -d "$DATA_DIR" ] || [ -z "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
        log "No training data available, skipping fine-tuning"
        return 1
    fi

    timeout 3600 python scripts/fine_tune.py \
        --data-dir "$DATA_DIR" \
        --output-dir "$OUTPUT_DIR" \
        --epochs 3 \
        --lr 2e-4 \
        2>&1 | tee -a "$LOG_FILE"
    log "Fine-tuning complete"
}

swap_model() {
    log "=== Swapping to fine-tuned model ==="

    local new_model="$OUTPUT_DIR"
    if [ ! -d "$new_model" ]; then
        log "Fine-tuned model not found at $new_model, skipping swap"
        return 1
    fi

    timeout 60 python scripts/swap_model.py \
        --model-path "$new_model" \
        2>&1 | tee -a "$LOG_FILE"
    log "Model swap complete"
}

compare_and_report() {
    log "=== Comparing results ==="
    log "Running comparison benchmarks with new model..."
    timeout "$BENCHMARK_TIMEOUT" python main.py --profile full --dry-run 2>&1 | tee -a "$LOG_FILE" || true
}

main_loop() {
    log "Starting continuous optimization loop (interval: $INTERVAL seconds)"
    log "Press Ctrl+C to stop"

    while true; do
        local cycle_start
        cycle_start=$(date +%s)

        log "=== Starting optimization cycle ==="

        # Step 1: Run benchmarks
        run_benchmarks || log "Benchmarks failed, continuing anyway..."

        # Step 2: Export successful sessions
        export_training_data

        # Step 3: Fine-tune model
        if fine_tune_model; then
            # Step 4: Swap to fine-tuned model
            if swap_model; then
                # Step 5: Compare results
                compare_and_report
            fi
        else
            log "Fine-tuning skipped or failed"
        fi

        local cycle_end
        cycle_end=$(date +%s)
        local elapsed=$((cycle_end - cycle_start))
        log "=== Cycle complete (took ${elapsed}s) ==="
        log "Sleeping for $INTERVAL seconds..."

        sleep "$INTERVAL"
    done
}

# Run the main loop
main_loop
