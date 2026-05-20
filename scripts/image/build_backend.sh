#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker

log_section "Building web image"
docker build --target web -t "${DOCKER_IMAGE_NAME_WEB:-dewflow-backend:2.0.0-web}" .

log_section "Building worker image"
docker build --target worker -t "${DOCKER_IMAGE_NAME_AI:-dewflow-backend:2.0.0-ai}" .
