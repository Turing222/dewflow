#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_smoke_env_file

smoke_env_path="$(resolve_project_path "$SMOKE_ENV_FILE")"

set -a
source "$smoke_env_path"
set +a

# Docker secrets are not accessible from the host; read the password file instead.
SMOKE_POSTGRES_PASSWORD_FILE="${SMOKE_POSTGRES_PASSWORD_FILE:-$PROJECT_ROOT/secrets/smoke/postgres_password.txt}"
if [[ -f "$SMOKE_POSTGRES_PASSWORD_FILE" ]]; then
    export POSTGRES_PASSWORD="$(< "$SMOKE_POSTGRES_PASSWORD_FILE")"
fi

exec .venv/bin/python scripts/smoke/create_kb.py --username "${SMOKE_TEST_USER:-smoke-test-user}" "$@"
