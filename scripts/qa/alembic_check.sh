#!/usr/bin/env bash
# ============================================================================
# Alembic migration health check
#
# Validates:
#   1. Revision chain integrity (alembic heads succeeds)
#   2. No orphan / unreachable revision files
#   3. Single head (warns on multiple, exits 1 if unexpected)
#   4. Optional: database is at latest migration (if DB is reachable)
#
# Environment:
#   ALEMBIC_CHECK_DB=1   Attempt database connectivity check (default: skip)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

ok()  { printf "${GREEN}[OK]${NC}   %s\n" "$1"; }
fail() { printf "${RED}[FAIL]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }

_failures=0

_inc_fail() { _failures=$((_failures + 1)); }

# ── Check 1: alembic heads (validates all revision files chain) ────────

echo "==> Checking revision chain integrity (alembic heads)"
if heads_output="$(uv run alembic heads 2>&1)"; then
    ok "Revision chain is valid"
else
    fail "Broken revision chain:"
    echo "$heads_output" | sed 's/^/      /'
    _inc_fail
fi

# ── Check 2: Single head (warn if multiple branches exist) ──────────────

echo ""
echo "==> Checking for multiple migration heads"
head_count="$(uv run alembic heads 2>/dev/null | wc -l)"
if (( head_count == 0 )); then
    fail "No migration heads found"
    _inc_fail
elif (( head_count == 1 )); then
    head_rev="$(uv run alembic heads 2>/dev/null | tr -d ' ')"
    ok "Single migration head: $head_rev"
else
    warn "$head_count migration heads found (branched history):"
    uv run alembic heads 2>/dev/null | sed 's/^/      /'
    warn "Note: Multiple heads may be valid if using branch merges, but usually indicates unmerged branches."
fi

# ── Check 3: Verify all revisions are connected (no orphans) ────────────

echo ""
echo "==> Checking for orphan revision files"
versions_dir="alembic/versions"
orphan_count=0
if [[ -d "$versions_dir" ]]; then
    declare -A _rev_ids
    declare -A _down_refs

    for f in "$versions_dir"/*.py; do
        rel="${f#$versions_dir/}"
        # skip __init__.py and pycache
        [[ "$rel" == __* ]] && continue
        
        rev_id="$(head -20 "$f" | grep -oP 'revision\s*=\s*["'\'']\K[^"'\'']+' | head -1 || true)"
        down_line="$(head -20 "$f" | grep -E '^down_revision\s*=' || true)"

        if [[ -n "$rev_id" ]]; then
            _rev_ids["$rev_id"]="$f"
            # Extract all string literals from down_revision line (supports tuples)
            if [[ -n "$down_line" ]]; then
                for d in $(echo "$down_line" | grep -oP '["'\'']\K[^"'\'']+(?=["'\''])' || true); do
                    if [[ -n "$d" && "$d" != "None" ]]; then
                        _down_refs["$d"]=1
                    fi
                done
            fi
        fi
    done

    # Cache heads output to avoid spawning multiple python processes
    _cached_heads="$(uv run alembic heads 2>/dev/null | tr -d ' ' || true)"
    
    for rev_id in "${!_rev_ids[@]}"; do
        # A revision is orphan if it is NOT referenced as a down_revision by any other revision
        # AND it is not a head revision
        if [[ -z "${_down_refs[$rev_id]:-}" ]]; then
            # Check if it's a head
            is_head="false"
            for head_line in $_cached_heads; do
                if [[ "$head_line" == "$rev_id" ]]; then
                    is_head="true"
                    break
                fi
            done
            
            if [[ "$is_head" == "false" ]]; then
                warn "Orphan revision (not a head, not referenced): $rev_id (${_rev_ids[$rev_id]})"
                orphan_count=$((orphan_count + 1))
            fi
        fi
    done
fi

if (( orphan_count == 0 )); then
    ok "No orphan revisions"
else
    _inc_fail
fi

# ── Check 4: Database up-to-date (optional, gated by env) ───────────────

echo ""
echo "==> Checking database migration status"
if [[ "${ALEMBIC_CHECK_DB:-0}" != "1" ]]; then
    warn "Skipping DB connectivity check (set ALEMBIC_CHECK_DB=1 to enable)"
else
    # Try to get the current DB revision
    if current_output="$(uv run alembic current 2>&1)"; then
        current_rev="$(echo "$current_output" | head -1 | tr -d ' ')"
        head_rev="$(uv run alembic heads 2>/dev/null | tr -d ' ')"
        if [[ "$current_rev" == "$head_rev" ]]; then
            ok "Database is at latest migration ($current_rev)"
        else
            fail "Database is behind: current=$current_rev, head=$head_rev"
            _inc_fail
        fi
    else
        warn "Cannot connect to database (is it running?):"
        echo "$current_output" | sed 's/^/      /'
    fi
fi

# ── Summary ────────────────────────────────────────────────────────────

echo ""
if (( _failures == 0 )); then
    echo "All Alembic checks passed."
    exit 0
else
    echo "$_failures Alembic check(s) failed."
    exit 1
fi
