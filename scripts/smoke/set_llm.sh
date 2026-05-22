#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

PROVIDER="${1:-}"
EMBED_PROVIDER="${2:-}"

if [[ -z "$PROVIDER" ]]; then
    log_error "Usage: make set-llm PROVIDER=<llm_provider> [EMBED_PROVIDER=<embed_provider>]"
    log_error "       (or $0 <llm_provider> [embed_provider])"
    log_error ""
    log_error "Examples:"
    log_error "  make set-llm PROVIDER=mock                    # LLM=mock, EMBED unchanged"
    log_error "  make set-llm PROVIDER=gemini                  # LLM=gemini, EMBED unchanged"
    log_error "  make set-llm PROVIDER=gemini EMBED_PROVIDER=google  # LLM=gemini, EMBED=google"
    log_error "  make set-llm PROVIDER=mock EMBED_PROVIDER=mock      # both mock"
    exit 1
fi

smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"

update_env_smoke() {
    local key="$1"
    local value="$2"
    if [[ ! -f "$smoke_env_path" ]]; then
        log_error "Missing $smoke_env_path. Please run 'make env-smoke-prepare' first."
        exit 1
    fi
    if grep -q "^${key}=" "$smoke_env_path"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$smoke_env_path"
    else
        echo "${key}=${value}" >> "$smoke_env_path"
    fi
    log_info "Updated ${key}=${value} in $smoke_env_path"
}

write_secret_for_provider() {
    local provider="$1"
    local key="$2"
    local secret_file_var="SMOKE_${provider^^}_API_KEY_FILE"
    local default_path="./secrets/smoke/${provider}_api_key.txt"
    local secret_path
    local secret_dir

    if [[ "$provider" == "bifrost_encryption" ]]; then
        secret_file_var="SMOKE_BIFROST_ENCRYPTION_KEY_FILE"
        default_path="./secrets/smoke/bifrost_encryption_key.txt"
    fi

    secret_path="$(smoke_env_value "$secret_file_var" "$default_path")"
    secret_path="$(resolve_project_path "$secret_path")"
    secret_dir="$(dirname "$secret_path")"

    mkdir -p "$secret_dir"

    local tmp
    tmp="$(mktemp -p "$secret_dir" tmp.XXXXXX)"
    (
        umask 077
        printf '%s' "$key" > "$tmp"
    )
    chmod 600 "$tmp"
    mv "$tmp" "$secret_path"

    log_info "API key securely written to $secret_path"
}

# --- LLM Provider ---
if [[ "$PROVIDER" == "mock" ]]; then
    update_env_smoke "LLM_PROVIDER" "mock"
else
    KEY=""
    if [[ ! -t 0 ]]; then
        if ! read -r KEY; then
            log_error "Failed to read API key from stdin."
            exit 1
        fi
        if [[ -z "$KEY" ]]; then
            log_error "API key read from stdin is empty."
            exit 1
        fi
    else
        read -rsp "Enter API Key for LLM ${PROVIDER}: " KEY || true
        echo ""
        if [[ -z "$KEY" ]]; then
            log_error "API key cannot be empty."
            exit 1
        fi
    fi
    if [[ "$PROVIDER" == "bifrost" && "$KEY" != sk-bf-* ]]; then
        log_error "Bifrost virtual keys must start with 'sk-bf-'."
        exit 1
    fi

    write_secret_for_provider "$PROVIDER" "$KEY"
    update_env_smoke "LLM_PROVIDER" "$PROVIDER"

    if [[ "$PROVIDER" == "bifrost" ]]; then
        BIFROST_ENC_KEY=""
        if [[ ! -t 0 ]]; then
            read -r BIFROST_ENC_KEY || true
        else
            read -rsp "Enter Bifrost Encryption Key: " BIFROST_ENC_KEY || true
            echo ""
        fi
        if [[ -n "$BIFROST_ENC_KEY" ]]; then
            write_secret_for_provider "bifrost_encryption" "$BIFROST_ENC_KEY"
        else
            log_warn "BIFROST_ENCRYPTION_KEY not set. Bifrost may fail to start."
        fi
    fi
fi

# --- Embed Provider ---
if [[ -n "$EMBED_PROVIDER" ]]; then
    if [[ "$EMBED_PROVIDER" == "mock" ]]; then
        update_env_smoke "RAG_EMBED_PROVIDER" "mock"
    else
        EMBED_KEY=""
        if [[ ! -t 0 ]]; then
            if ! read -r EMBED_KEY; then
                log_error "Failed to read embed API key from stdin."
                exit 1
            fi
            if [[ -z "$EMBED_KEY" ]]; then
                log_error "Embed API key read from stdin is empty."
                exit 1
            fi
        else
            read -rsp "Enter API Key for Embed ${EMBED_PROVIDER}: " EMBED_KEY || true
            echo ""
            if [[ -z "$EMBED_KEY" ]]; then
                log_error "Embed API key cannot be empty."
                exit 1
            fi
        fi

        write_secret_for_provider "$EMBED_PROVIDER" "$EMBED_KEY"
        update_env_smoke "RAG_EMBED_PROVIDER" "$EMBED_PROVIDER"
    fi
fi
