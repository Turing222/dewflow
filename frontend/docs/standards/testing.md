# Frontend Testing Standard

## 目标

- 用小成本覆盖架构边界。
- 优先测试容易回归的请求、schema、状态和路由行为。
- 不为了覆盖率数字写脆弱测试。

## 测试分层

Unit / smoke：

- schema parse。
- request helper。
- route smoke。
- store action。
- 纯工具函数。

Integration：

- query hook。
- mutation invalidation。
- token bootstrap。
- unauthorized cleanup。
- stream parser。

Build verification：

- TypeScript build。
- Vite build。
- lint。

## 常用命令

```bash
make frontend-lint
make frontend-typecheck
make frontend-test
make frontend-build
make frontend-e2e-mock
make frontend-check
```

真实后端 smoke e2e 不作为 PR 默认阻塞项。需要先启动后端并提供账号：

```bash
E2E_SMOKE_USER=... E2E_SMOKE_PASS=... make frontend-e2e-smoke
```

## 新增功能的最低测试建议

- 新 API：schema parse 或 API helper test。
- 新 query：query key、enabled 条件、invalidation。
- 新表单：关键校验和 submit payload。
- 新流式逻辑：chunk parser、error event、done event、abort。

## Mock 数据

- Vitest/MSW 和 Playwright mock e2e 共享 `src/test/mock-data` 中的基础响应数据。
- Playwright 仍使用 `page.route`，不强制迁移到浏览器侧 MSW。
