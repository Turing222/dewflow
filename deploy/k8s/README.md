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

## 前端部署

前端作为独立的单页应用 (SPA) 通过 Nginx 提供服务：
- **资源利用**: 镜像中移除了所有源码和 node_modules，仅保留构建产物和 nginx 配置，内存和 CPU 开销较低。
- **安全加固**: Nginx 默认监听 `8080` 端口，Deployment 强制启用 `runAsNonRoot: true`，以非 root 用户 UID `101` (nginx) 运行。
- **网络暴露**: Frontend 服务通过 `Service` 暴露在集群内部 (ClusterIP)，并通过外部 `Ingress` 与后端 API 统一暴露；Ingress 会将外部 `/api/v1/...` 重写为后端 `/v1/...`。
- **镜像前置条件**: 部署前需要先构建并推送 `dewflow-frontend:2.0.0` 到集群可拉取的镜像仓库，或替换 `frontend-deployment.yaml` 中的镜像名。

## 使用方式

本地只验证 Worker 会根据 Redis 队列扩缩容时，优先看 `deploy/k8s/local-scaling/README.md`。

1. 先复制并替换 Secret 示例，不要把真实密钥提交到仓库：
   ```bash
   cp deploy/k8s/secret.example.yaml /tmp/dewflow-secret.yaml
   ```

2. 构建并推送前端镜像，或将 `frontend-deployment.yaml` 中的镜像名替换为已发布镜像：
   ```bash
   make frontend-image-build
   # docker tag dewflow-frontend:2.0.0 <registry>/dewflow-frontend:2.0.0
   # docker push <registry>/dewflow-frontend:2.0.0
   ```

3. 复制并根据实际域名配置 Ingress 示例（不包含在 Kustomize 资源内，需手动维护）：
   ```bash
   cp deploy/k8s/frontend-ingress.example.yaml /tmp/dewflow-ingress.yaml
   # 修改 /tmp/dewflow-ingress.yaml 中的 host 等配置
   ```

4. 集群部署（标准部署入口使用 Kustomize 编排，`kubectl apply -k deploy/k8s` 会一并部署 API、Worker 和 Frontend 服务）：
   ```bash
   kubectl apply -f deploy/k8s/namespace.yaml
   kubectl apply -f /tmp/dewflow-secret.yaml
   kubectl apply -k deploy/k8s
   kubectl apply -f /tmp/dewflow-ingress.yaml
   ```

如果集群没有安装 KEDA，需要临时跳过 `worker-keda-scaledobject.yaml`，Worker 仍可按 `worker-deployment.yaml` 的固定副本运行。
