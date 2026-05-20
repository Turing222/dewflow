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
make frontend-test
make frontend-build
pnpm --dir frontend --filter admin lint
```

## 新增功能的最低测试建议

- 新 API：schema parse 或 API helper test。
- 新 query：query key、enabled 条件、invalidation。
- 新表单：关键校验和 submit payload。
- 新流式逻辑：chunk parser、error event、done event、abort。

## TODO

- 明确是否引入 MSW。
- 明确 hook 测试工具和样例。
- 补充 stream parser 测试样例。
