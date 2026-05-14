#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "$SCRIPT_DIR/lib.sh"

load_common_env
ensure_core_dirs

if [[ $# -lt 1 ]]; then
  SELECTION="all"
else
  SELECTION="$1"
  shift
fi

if [[ -n "${DATAPLANE_VARIANTS:-}" ]]; then
  read -r -a VARIANTS <<< "$DATAPLANE_VARIANTS"
else
  VARIANTS=(baseline calico-ebpf cilium)
fi

for variant in "${VARIANTS[@]}"; do
  DATAPLANE_MODE="$(normalize_dataplane_mode "$variant")"
  MATRIX_LABEL="dataplane-${DATAPLANE_MODE}"
  log "Running dataplane comparison for $DATAPLANE_MODE"
  DATAPLANE_MODE="$DATAPLANE_MODE" MATRIX_LABEL="$MATRIX_LABEL" bash "$SCRIPT_DIR/run_selected_skus.sh" "$SELECTION" "$@"
done