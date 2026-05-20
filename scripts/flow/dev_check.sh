#!/usr/bin/env bash
# ============================================================================
# Dev check flow — runs static checks first, then runtime smoke checks.
#
# Usage:
#   make flow-dev-check          # full pipeline
#   make flow-static             # static only (no external services)
#   make flow-runtime            # runtime only (needs Docker/DB/Redis)
#   FLOW_KEEP_SMOKE_ENV=true make flow-runtime   # keep smoke env after run
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

cd "$PROJECT_ROOT"

make flow-static
make flow-runtime
