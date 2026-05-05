#!/usr/bin/env bash
# ============================================================================
# Runtime verification flow
#
# Requires: Docker daemon running, ports 5432/6379/8000 available.
# This flow builds the image, starts the smoke stack, waits for readiness,
# runs HTTP smoke tests, then tears down.
#
# Gate: FLOW_KEEP_SMOKE_ENV=true   Keep the smoke env running after finish.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"

cleanup() {
    local exit_code=$?

    if [[ "${FLOW_KEEP_SMOKE_ENV:-false}" == "true" ]]; then
        if (( exit_code != 0 )); then
            log_warn "Keeping smoke environment for debugging because FLOW_KEEP_SMOKE_ENV=true"
        else
            log_warn "FLOW_KEEP_SMOKE_ENV=true, smoke environment is still running"
        fi
        exit "$exit_code"
    fi

    bash scripts/smoke/down.sh || true
    exit "$exit_code"
}

trap cleanup EXIT

log_section "Running runtime verification flow"

smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"
if [[ ! -f "$smoke_env_path" ]]; then
    log_info "Smoke env file not found, generating it from the shared template"
    make env-smoke-prepare
fi

make image-build
make env-smoke-up
make env-smoke-wait
make verify-smoke

log_section "Runtime verification passed"
