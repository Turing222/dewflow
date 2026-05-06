#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"

cd "$PROJECT_ROOT"

require_cmd docker

log_section "Building web image"
docker build --target web -t "${DOCKER_IMAGE_NAME_WEB:-ai-tutor-backend:web-v1}" .

log_section "Building worker image"
docker build --target worker -t "${DOCKER_IMAGE_NAME_AI:-ai-tutor-backend:ai-v1}" .
