#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

PROVIDER="${1:-}"

if [[ -z "$PROVIDER" ]]; then
    log_error "Usage: make set-llm PROVIDER=<provider_name> (or $0 <provider_name>)"
    exit 1
fi

smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"

update_env_smoke() {
    local target_provider="$1"
    if [[ ! -f "$smoke_env_path" ]]; then
        log_error "Missing $smoke_env_path. Please run 'make env-smoke-prepare' first."
        exit 1
    fi
    # Use sed to update LLM_PROVIDER
    if grep -q "^LLM_PROVIDER=" "$smoke_env_path"; then
        sed -i "s|^LLM_PROVIDER=.*|LLM_PROVIDER=$target_provider|" "$smoke_env_path"
    else
        echo "LLM_PROVIDER=$target_provider" >> "$smoke_env_path"
    fi
    log_info "Updated LLM_PROVIDER=$target_provider in $smoke_env_path"
}

if [[ "$PROVIDER" == "mock" ]]; then
    update_env_smoke "mock"
    exit 0
fi

KEY=""
if [[ ! -t 0 ]]; then
    # Reading from stdin (e.g., piped input)
    if ! read -r KEY; then
        log_error "Failed to read API key from stdin."
        exit 1
    fi
    if [[ -z "$KEY" ]]; then
        log_error "API key read from stdin is empty."
        exit 1
    fi
else
    # Interactive prompt
    read -rsp "Enter API Key for ${PROVIDER}: " KEY || true
    echo ""
    if [[ -z "$KEY" ]]; then
        log_error "API key cannot be empty."
        exit 1
    fi
fi

secret_file_var="SMOKE_${PROVIDER^^}_API_KEY_FILE"
default_path="./secrets/smoke/${PROVIDER}_api_key.txt"
secret_path="$(smoke_env_value "$secret_file_var" "$default_path")"
secret_path="$(resolve_project_path "$secret_path")"
secret_dir="$(dirname "$secret_path")"

mkdir -p "$secret_dir"

# Atomic write with strict permissions
tmp="$(mktemp -p "$secret_dir" tmp.XXXXXX)"
(
    umask 077
    printf '%s' "$KEY" > "$tmp"
)
chmod 600 "$tmp"
mv "$tmp" "$secret_path"

log_info "API key securely written to $secret_path"

update_env_smoke "$PROVIDER"
