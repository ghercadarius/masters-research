#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "$SCRIPT_DIR/lib.sh"

load_common_env
ensure_core_dirs
dependency_check
DATAPLANE_MODE="$(normalize_dataplane_mode "${DATAPLANE_MODE:-baseline}")"

START_ARGS=()
if [[ "$DATAPLANE_MODE" == "calico" ]]; then
  START_ARGS+=(--cni=calico)
fi
if [[ "$DATAPLANE_MODE" == "cilium" ]]; then
  START_ARGS+=(--cni=cilium)
fi

log "Starting base Minikube profile $MINIKUBE_PROFILE"
minikube start \
  --profile="$MINIKUBE_PROFILE" \
  --driver=kvm2 \
  --nodes=1 \
  --cpus="$BASE_CPUS" \
  --memory="$BASE_MEMORY_MB" \
  "${START_ARGS[@]}"

configure_dataplane "$DATAPLANE_MODE"

ensure_namespace "$NAMESPACE"
start_tunnel_if_needed
write_runtime_state

log "Startup complete. Common elements are ready."
