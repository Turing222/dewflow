# Dewflow Kubernetes 接入示例

职责：沉淀 Dewflow Backend 迁移到 Kubernetes 的最小部署入口。
边界：当前本地开发仍以 `docker-compose.db.yml` 为主，本目录不改变 compose 运行方式。
副作用：应用这些清单会在目标集群创建 namespace、工作负载、HPA 和 KEDA 扩缩容对象。

## 设计目标

- API 和 Worker 分开部署，匹配现有 `Dockerfile` 的 `web` / `worker` 镜像目标。
- API 作为在线 HTTP 服务，通过 HPA 按 CPU/内存扩缩容。
- Worker 作为异步任务消费者，通过 KEDA 按 Redis TaskIQ 队列积压扩缩容。
- Postgres、Redis、MinIO/S3 作为外部依赖接入；本地验证继续参考 `docker-compose.db.yml`。

## 扩缩容策略

详细设计见 `docs/k8s-scaling-strategy.md`。

API 压力来自在线请求，示例策略为：

- `minReplicas: 1`
- `maxReplicas: 5`
- CPU 平均利用率 70%
- 内存平均利用率 75%

Worker 压力来自后台任务积压，示例策略为：

- `minReplicaCount: 1`
- `maxReplicaCount: 8`
- Redis db=1
- TaskIQ list 名称：`taskiq`
- 队列长度达到 10 时触发扩容

## 使用方式

本地只验证 Worker 会根据 Redis 队列扩缩容时，优先看 `deploy/k8s/local-scaling/README.md`。

先复制并替换 Secret 示例，不要把真实密钥提交到仓库：

```bash
cp deploy/k8s/secret.example.yaml /tmp/dewflow-secret.yaml
```

标准部署入口包含 KEDA `ScaledObject`。集群需要先安装 KEDA CRD 和 controller，再应用基础资源：

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f /tmp/dewflow-secret.yaml
kubectl apply -k deploy/k8s
```

如果集群没有安装 KEDA，需要临时跳过 `worker-keda-scaledobject.yaml`，Worker 仍可按 `worker-deployment.yaml` 的固定副本运行。
