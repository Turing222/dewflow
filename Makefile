SHELL := /bin/bash

DOCKER_IMAGE_NAME_WEB ?= ai-tutor-backend:web-v1
DOCKER_IMAGE_NAME_AI ?= ai-tutor-backend:ai-v1
SMOKE_COMPOSE_FILE ?= docker-compose.db.yml
DEBUG_COMPOSE_FILE ?= docker-compose.debug.yml
SMOKE_ENV_FILE ?= .env.smoke
SMOKE_ENV_TEMPLATE ?= .env.smoke.template
SMOKE_BASE_URL ?= http://localhost:8000
SMOKE_LIVE_PATH ?= /api/v1/health_check/live
SMOKE_READY_PATH ?= /api/v1/health_check/db_ready
UNIT_TARGETS ?= tests/unit
COMPONENT_TARGETS ?= tests/component
INTEGRATION_TARGETS ?= tests/integration
EVAL_DATASET ?= evals/dataset.sample.jsonl
EVAL_OUTPUT ?= evals/reports/answer_report.json
EVAL_API_OUTPUT ?= evals/reports/api_answer_report.json
EVAL_RETRIEVAL_OUTPUT ?= evals/reports/retrieval_report.json
PERF_USERS ?= 5
PERF_SPAWN_RATE ?= 1
PERF_RUN_TIME ?= 1m
PERF_PROFILE ?= perf/profiles/enterprise_smoke.json
PERF_OUTPUT ?= perf/reports/chat_api_load_report.json
PYTEST_ARGS ?=

export DOCKER_IMAGE_NAME_WEB DOCKER_IMAGE_NAME_AI
export SMOKE_COMPOSE_FILE
export DEBUG_COMPOSE_FILE
export SMOKE_ENV_FILE
export SMOKE_ENV_TEMPLATE
export SMOKE_BASE_URL
export SMOKE_LIVE_PATH
export SMOKE_READY_PATH
export EVAL_DATASET EVAL_OUTPUT EVAL_API_OUTPUT EVAL_RETRIEVAL_OUTPUT
export PERF_USERS PERF_SPAWN_RATE PERF_RUN_TIME PERF_PROFILE PERF_OUTPUT

.DEFAULT_GOAL := help

.PHONY: help \
	qa-lint qa-boundaries qa-format qa-typecheck qa-layer-deps qa-alembic-check qa-config-check qa-test-markers qa-test-unit qa-test-component qa-test-integration qa-test-local qa-test-ci qa-test-external qa-test-all qa-checks qa-eval-rag qa-eval-api qa-perf-chat qa-perf-chat-locust qa-agent-flow \
	image-build \
	env-smoke-prepare env-smoke-check env-smoke-up env-smoke-wait env-smoke-create-kb env-smoke-down env-smoke-logs \
	env-debug-up env-debug-down env-debug-logs env-debug-services \
	set-llm seed-dev \
	verify-smoke \
	flow-static flow-runtime flow-dev-check flow-ci layer-deps \
	lint format typecheck test check clean-cache

help:
	@printf '%s\n' \
		'Available targets:' \
		'  qa-lint              Run Ruff lint checks' \
		'  qa-boundaries        Check Web/Worker import boundaries' \
		'  qa-format            Run Ruff formatter' \
		'  qa-typecheck         Run type checking' \
			'  qa-layer-deps        Verify each extras layer can import independently' \
			'  qa-alembic-check     Validate migration chain integrity' \
			'  qa-config-check      Validate config/env for deployment contexts' \
			'  qa-test-markers      Audit pytest dependency markers' \
			'  qa-test-unit         Run unit tests (UNIT_TARGETS=...)' \
			'  qa-test-component    Run component tests (COMPONENT_TARGETS=...)' \
			'  qa-test-integration  Run integration tests (INTEGRATION_TARGETS=...)' \
			'  qa-test-local        Run local default pytest profile' \
		'  qa-test-ci           Run CI-safe pytest profile' \
		'  qa-test-external     Run tests that need external dependencies' \
		'  qa-test-all          Run all pytest suites except excluded markers' \
		'  qa-eval-rag          Run opt-in RAG retrieval and answer evals' \
		'  qa-eval-api          Run opt-in RAG answer eval through HTTP API' \
		'  qa-perf-chat         Run opt-in chat load profile with HTTP runner' \
		'  qa-perf-chat-locust  Run exploratory chat load test with Locust' \
		'  qa-agent-flow        Reserved entrypoint for agent/C2C flow tests' \
		'  qa-checks            Run lint and typecheck via scripts' \
		'  image-build          Build the backend Docker image' \
		'  env-smoke-prepare    Generate the smoke env file from template' \
		'  env-smoke-check      Run preflight checks for smoke environment (API keys)' \
		'  env-smoke-up         Start the smoke environment' \
		'  env-smoke-wait       Wait until the smoke environment is reachable' \
		'  env-smoke-create-kb  Create a manual/smoke knowledge base for an existing user' \
		'  env-debug-up         Start Docker dependencies for VS Code debugging' \
		'  env-debug-down       Stop Docker debug dependencies' \
		'  env-debug-logs       Show recent Docker debug dependency logs' \
		'  env-debug-services   List services enabled by the debug compose stack' \
		'  set-llm              Set API key securely (Usage: make set-llm PROVIDER=gemini [EMBED_PROVIDER=google])' \
		'  seed-dev             Seed fixed local data for admin/permission testing' \
		'  verify-smoke         Run smoke HTTP checks against the running stack' \
		'  env-smoke-down       Stop the smoke environment' \
		'  env-smoke-logs       Show recent smoke logs' \
		'  flow-static          Run L1 static checks and deterministic tests' \
		'  flow-runtime         Run runtime checks (build+smoke up+smoke tests+smoke down)' \
		'  flow-dev-check       Run the full dev verification flow (static + runtime)' \
		'  flow-ci              Alias for the dev verification flow'

qa-lint:
	uv run ruff check .

qa-boundaries:
	uv run python scripts/check_import_boundaries.py

qa-format:
	uv run ruff format .

qa-typecheck:
	uv run ty check .

qa-layer-deps:
	bash scripts/qa/layer_deps_check.sh

qa-alembic-check:
	bash scripts/qa/alembic_check.sh

qa-config-check:
	uv run python scripts/qa/config_check.py $(ARGS)

qa-test-markers:
	uv run python scripts/qa/check_test_markers.py

qa-test-unit:
	DEWFLOW_TEST_PROFILE=unit bash scripts/qa/run_unit.sh $(PYTEST_ARGS) $(UNIT_TARGETS)

qa-test-component:
	DEWFLOW_TEST_PROFILE=unit uv run pytest $(PYTEST_ARGS) $(COMPONENT_TARGETS)

qa-test-integration:
	DEWFLOW_TEST_PROFILE=local bash scripts/qa/run_integration.sh $(PYTEST_ARGS) $(INTEGRATION_TARGETS)

qa-test-local:
	DEWFLOW_TEST_PROFILE=local uv run pytest -m "not performance" $(PYTEST_ARGS)

qa-test-ci:
	DEWFLOW_TEST_PROFILE=ci uv run pytest -m "not performance and not local_only and not requires_llm and not requires_s3" $(PYTEST_ARGS)

qa-test-external:
	DEWFLOW_TEST_PROFILE=external uv run pytest -m "requires_llm or requires_s3 or requires_taskiq" $(PYTEST_ARGS)

qa-test-all:
	uv run pytest $(PYTEST_ARGS)

qa-eval-rag:
	uv run python -m evals.eval_retrieval --dataset "$(EVAL_DATASET)" --output "$(EVAL_RETRIEVAL_OUTPUT)" $(ARGS)
	uv run python -m evals.eval_answer --dataset "$(EVAL_DATASET)" --output "$(EVAL_OUTPUT)" $(ARGS)

qa-eval-api:
	uv run python -m evals.eval_api_answer --dataset "$(EVAL_DATASET)" --output "$(EVAL_API_OUTPUT)" --base-url "$(SMOKE_BASE_URL)" $(ARGS)

qa-perf-chat:
	uv run python -m perf.chat_api_load --profile "$(PERF_PROFILE)" --output "$(PERF_OUTPUT)" --base-url "$(SMOKE_BASE_URL)" $(ARGS)

qa-perf-chat-locust:
	uv run locust -f tests/performance/locustfile.py --host "$(SMOKE_BASE_URL)" --headless -u "$(PERF_USERS)" -r "$(PERF_SPAWN_RATE)" -t "$(PERF_RUN_TIME)" $(ARGS)

qa-agent-flow:
	@printf '%s\n' 'Agent/C2C flow tests are reserved for L3 and should reuse tests/smoke helpers.'

qa-checks:
	bash scripts/qa/run_checks.sh

image-build:
	bash scripts/image/build_backend.sh

env-smoke-prepare:
	bash scripts/smoke/prepare_env.sh

env-smoke-check:
	bash scripts/smoke/check_env.sh

env-smoke-up: env-smoke-check
	bash scripts/smoke/up.sh

env-smoke-wait:
	bash scripts/smoke/wait.sh

env-smoke-create-kb:
	bash scripts/smoke/create_kb.sh $(ARGS)

set-llm:
	@bash scripts/smoke/set_llm.sh "$(PROVIDER)" "$(or $(EMBED_PROVIDER),)"

seed-dev:
	uv run python scripts/seed/dev_seed.py $(ARGS)

env-smoke-down:
	bash scripts/smoke/down.sh

env-smoke-logs:
	SMOKE_ENV_FILE="$(SMOKE_ENV_FILE)" docker compose --env-file "$(SMOKE_ENV_FILE)" -f "$(SMOKE_COMPOSE_FILE)" logs --tail=200

env-debug-up:
	SMOKE_ENV_FILE="$(SMOKE_ENV_FILE)" docker compose --env-file "$(SMOKE_ENV_FILE)" -f "$(SMOKE_COMPOSE_FILE)" -f "$(DEBUG_COMPOSE_FILE)" up -d --remove-orphans

env-debug-down:
	SMOKE_ENV_FILE="$(SMOKE_ENV_FILE)" docker compose --env-file "$(SMOKE_ENV_FILE)" -f "$(SMOKE_COMPOSE_FILE)" -f "$(DEBUG_COMPOSE_FILE)" down

env-debug-logs:
	SMOKE_ENV_FILE="$(SMOKE_ENV_FILE)" docker compose --env-file "$(SMOKE_ENV_FILE)" -f "$(SMOKE_COMPOSE_FILE)" -f "$(DEBUG_COMPOSE_FILE)" logs --tail=200

env-debug-services:
	SMOKE_ENV_FILE="$(SMOKE_ENV_FILE)" docker compose --env-file "$(SMOKE_ENV_FILE)" -f "$(SMOKE_COMPOSE_FILE)" -f "$(DEBUG_COMPOSE_FILE)" config --services

verify-smoke:
	bash scripts/smoke/test.sh

flow-static:
	$(MAKE) qa-lint
	$(MAKE) qa-boundaries
	$(MAKE) qa-test-markers
	$(MAKE) qa-typecheck
	$(MAKE) qa-layer-deps
	$(MAKE) qa-alembic-check
	$(MAKE) qa-config-check
	$(MAKE) qa-test-unit
	$(MAKE) qa-test-component

flow-runtime:
	bash scripts/flow/runtime_check.sh

flow-dev-check:
	$(MAKE) flow-static
	$(MAKE) flow-runtime

flow-ci: flow-dev-check

lint: qa-lint

format: qa-format

typecheck: qa-typecheck

test: qa-test-all

layer-deps: qa-layer-deps

check: flow-static

clean-cache:
	uv run python -c "import pathlib; [p.unlink() for p in pathlib.Path('.').rglob('*.py[co]')]; [p.rmdir() for p in pathlib.Path('.').rglob('__pycache__')]"
