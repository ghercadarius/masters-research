#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "$SCRIPT_DIR/lib.sh"

load_common_env
ensure_core_dirs
log "Dataplane benchmarks starting (selection=${1:-all})"

if [[ $# -lt 1 ]]; then
  SELECTION="all"
else
  SELECTION="$1"
  shift
fi

if [[ -n "${DATAPLANE_VARIANTS:-}" ]]; then
  read -r -a VARIANTS <<< "$DATAPLANE_VARIANTS"
else
  VARIANTS=(baseline calico calico-ebpf cilium)
fi

for variant in "${VARIANTS[@]}"; do
  DATAPLANE_MODE="$(normalize_dataplane_mode "$variant")"
  MATRIX_LABEL="dataplane-${DATAPLANE_MODE}"
  MATRIX_BASE_DIR="$ITERATION_DIR/results/benchmarks/${DATAPLANE_MODE}"
  log "Running dataplane benchmark for $DATAPLANE_MODE"
  log "Matrix label: $MATRIX_LABEL"
  log "Matrix base dir: $MATRIX_BASE_DIR"
  log "Selection: $SELECTION"
  MATRIX_LABEL="$MATRIX_LABEL" \
    MATRIX_BASE_DIR="$MATRIX_BASE_DIR" \
    bash "$SCRIPT_DIR/run_selected_skus.sh" "$SELECTION" --dataplane "$DATAPLANE_MODE" "$@"
done

log "Dataplane benchmarks finished"
