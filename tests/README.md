# Test Guide

`tests/` 目录按测试目标拆分。目录负责回答“这是什么层级的测试”，marker 负责回答“它需要什么能力”，profile 负责回答“当前按什么环境运行”。

## 目录标准

- `unit/`: 纯单元测试，默认必须通过；不依赖真实 PostgreSQL、Redis、S3、TaskIQ worker 或外部 HTTP 服务。
- `unit/api|services|repositories|workflows|infra|ai|worker|...`: 在 `unit/` 内按源码领域继续细分，优先镜像 `backend/` 的模块边界。
- `component/`: 进程内组件测试；允许使用 FastAPI ASGI、router、middleware、dependency override 和 fake service，不依赖真实外部服务。
- `integration/`: 集成测试；依赖真实 PostgreSQL、Redis、TaskIQ worker 或完整应用生命周期，文件必须使用 `pytest.mark.integration`。
- `smoke/`: 真实 HTTP stack 冒烟测试；访问运行中环境，用来判断关键链路是否基本可用。
- `performance/`: 并发、负载、性能测试；默认不跑，必须使用 `pytest.mark.performance`。
- `manual/`: 手动验证材料，不作为默认自动化测试集的一部分。

更具体的写法标准见 [CONVENTIONS.md](./CONVENTIONS.md)。

## 推荐命令

- 单元测试：

```bash
make qa-test-unit
```

- 集成测试：

```bash
make qa-test-integration
```

- Marker 审计：

```bash
make qa-test-markers
```

- 组件测试：

```bash
make qa-test-component
```

- 本地默认 profile：

```bash
make qa-test-local
```

- CI 安全 profile：

```bash
make qa-test-ci
```

- 外部依赖 profile：

```bash
make qa-test-external
```

- 全量默认测试，排除 performance：

```bash
uv run pytest
```

- 只跑 smoke：

```bash
uv run pytest -m smoke
```

- 跑 performance：

```bash
uv run pytest -m performance
```

- 跑 unit + component + integration：

```bash
uv run pytest tests/unit tests/component tests/integration
```

## 其他说明

- 测试 profile 通过 `DEWFLOW_TEST_PROFILE` 控制，允许值为 `unit|local|ci|external`。
- 真实依赖通过 `TEST_*` 变量覆盖，例如 `TEST_DATABASE_URL`、`TEST_REDIS_URL`。
- `evals/` 已迁移到项目根目录，不再属于 `pytest` 测试集。
- 诊断脚本放在 `scripts/diagnostics/`。
- Locust 脚本位置：`tests/performance/locustfile.py`。
