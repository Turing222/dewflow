# Dewflow Context

## Overview

Dewflow Backend is a Python 3.12 FastAPI async web server with TaskIQ workers.

- Web: FastAPI HTTP API at `backend/api/v1/`
- Worker: TaskIQ async tasks at `backend/worker/`
- Database: PostgreSQL + pgvector through SQLAlchemy async
- Cache/Broker: Redis db 0 for app, db 1 for TaskIQ
- Observability: OpenTelemetry to Langfuse
- Storage: local filesystem or S3-compatible storage

## Directory Map

```text
backend/
  api/v1/endpoint/    HTTP endpoints
  api/v1/api.py       Router registration
  api/dependencies.py FastAPI dependency injection
  api/deps/           Dependency providers
  contracts/          Abstract interfaces
  models/orm/         SQLAlchemy ORM models
  models/schemas/     Pydantic DTOs
  config/             Pydantic settings
  services/           Business logic
  repositories/       Data access
  infra/              DB, Redis, TaskIQ broker
  middleware/         FastAPI middleware
  worker/             TaskIQ tasks
  core/               Exceptions and constants
  utils/              Generic helpers
tests/                unit, component, integration, smoke, manual tests
scripts/              Shell and Python automation
configs/              Deployment configs
alembic/              Migration chain
```
