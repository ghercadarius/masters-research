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

DATAPLANE_VARIANTS_OVERRIDE=""
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dataplanes|--dataplane-variants)
      DATAPLANE_VARIANTS_OVERRIDE="$2"
      shift
      ;;
    *)
      PASSTHROUGH_ARGS+=("$1")
      ;;
  esac
  shift
done

if [[ -n "$DATAPLANE_VARIANTS_OVERRIDE" ]]; then
  DATAPLANE_VARIANTS_OVERRIDE="${DATAPLANE_VARIANTS_OVERRIDE//,/ }"
  read -r -a VARIANTS <<< "$DATAPLANE_VARIANTS_OVERRIDE"
elif [[ -n "${DATAPLANE_VARIANTS:-}" ]]; then
  DATAPLANE_VARIANTS_CLEAN="${DATAPLANE_VARIANTS//,/ }"
  read -r -a VARIANTS <<< "$DATAPLANE_VARIANTS_CLEAN"
else
  VARIANTS=(baseline calico cilium)
fi

log "Dataplane variants: ${VARIANTS[*]}"

for variant in "${VARIANTS[@]}"; do
  DATAPLANE_MODE="$(normalize_dataplane_mode "$variant")"
  MATRIX_LABEL="dataplane-${DATAPLANE_MODE}"
  MATRIX_BASE_DIR="$ITERATION_DIR/results/benchmarks/${DATAPLANE_MODE}"
  log "Running dataplane benchmark for $DATAPLANE_MODE"
  log "Matrix label: $MATRIX_LABEL"
  log "Matrix base dir: $MATRIX_BASE_DIR"
  log "Selection: $SELECTION"
  EFFECTIVE_SELECTION="$SELECTION"
  if [[ "$DATAPLANE_MODE" != "baseline" && "$SELECTION" == "all" ]]; then
    mapfile -t FILTERED_SKUS < <(list_all_skus | grep -v '^c4-')
    if [[ ${#FILTERED_SKUS[@]} -eq 0 ]]; then
      log "No SKUs remain after filtering out c4-*; skipping $DATAPLANE_MODE"
      continue
    fi
    EFFECTIVE_SELECTION="$(IFS=','; echo "${FILTERED_SKUS[*]}")"
    log "Filtered selection (excluding c4-*): $EFFECTIVE_SELECTION"
  fi
  MATRIX_LABEL="$MATRIX_LABEL" \
    MATRIX_BASE_DIR="$MATRIX_BASE_DIR" \
    bash "$SCRIPT_DIR/run_selected_skus.sh" "$EFFECTIVE_SELECTION" --dataplane "$DATAPLANE_MODE" "${PASSTHROUGH_ARGS[@]}"
done

log "Dataplane benchmarks finished"
