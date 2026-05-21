# Admin Frontend

当前前端只保留 `apps/admin` 这一个应用，负责聊天主页和管理员入口。

## 文档

- [前端文档索引](../../docs/README.md)
- [架构约定](../../docs/architecture.md)
- [逐步改造计划](../../docs/migration-plan.md)

## 常用命令

在仓库根目录执行：

```bash
make frontend-lint
make frontend-typecheck
make frontend-test
make frontend-build
make frontend-e2e-mock
make frontend-check
```

如果只想在前端目录里跑：

```bash
pnpm --dir frontend --filter admin lint
pnpm --dir frontend --filter admin typecheck
pnpm --dir frontend --filter admin test
pnpm --dir frontend --filter admin build
pnpm --dir frontend --filter admin test:e2e:mock
pnpm --dir frontend --filter admin dev
```

真实后端 smoke e2e 需要先启动后端，并提供测试账号：

```bash
E2E_SMOKE_USER=... E2E_SMOKE_PASS=... make frontend-e2e-smoke
```

## 测试范围

- `Vitest + jsdom + Testing Library`
- 路由级 smoke test
- Playwright mock e2e
- 真实后端 smoke e2e（手动触发）
- API 路径和流式请求的基础测试

这一步先保证最基础的前端验证链路可跑，再继续做镜像和 CI 拆分。
