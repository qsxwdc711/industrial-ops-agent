# 首版验证记录

## 结果

- 后端：`RUN_INFRA_TESTS=1 INFRA_QUEUE_BACKEND=rabbitmq RUN_MILVUS_TESTS=1 pytest -q`，**23 passed**；随后增加测试队列隔离，相关 3 项基础设施测试复验通过。
- 前端：TypeScript 编译与 Vite 生产构建通过。
- 浏览器：Microsoft Edge 桌面及 390px 窄屏检查通过，无捕获到的页面运行错误、无横向溢出。
- 浏览器操作：设备筛选与模拟采样、告警确认、知识导入/检索/删除、MCP 证据诊断、连续问答与会话保存。真实模型与真实向量检索启用后，这些操作再次通过。
- 报告显示：发现真实模型 Markdown 标记直接显示为文字后，增加标题、强调、列表和表格渲染。修改后通过生产构建及历史会话浏览器检查，确认已保存的诊断/追问报告和证据可以加载，390px 下无横向溢出；此复验没有新增模型调用。
- npm audit：0 vulnerabilities。
- pip check：No broken requirements found。
- Docker Compose：app/vector profile 的配置校验通过。
- Windows 启动脚本：PowerShell 语法校验通过。

## 实际服务覆盖

- MySQL：使用本机缓存的 `mysql:8.0` 镜像，在本项目独立数据库和端口 3316 上验证 96 张遥测分片、写入、告警和 MCP 数据查询。
- Redis：使用本机缓存镜像、端口 6381 与测试数据库 15，验证概览缓存命中和写入后的失效。修复 MySQL SUM 聚合返回 Decimal 无法写入 JSON 缓存的问题。
- Milvus：使用本机缓存的 `milvusdb/milvus:v2.5.10`、独立 etcd/MinIO 服务，通过官方 v2 REST API 验证创建集合、8 维测试向量写入、COSINE 检索、来源字段、删除和维度保护。自动化向量测试使用测试替身。另用用户配置的方舟多模态嵌入模型完成 1024 维真实向量请求、4 份演示资料索引和带来源的知识检索，并在浏览器完成真实文档导入/检索/删除。
- MCP：测试和工作台都实际通过 Python SDK 的 stdio 协议调用证据服务。
- 火山方舟：用户配置完成后切换为 `LLM_MODE=ark`。真实 `/api/analysis` 返回 1,366 字符报告、866 次 token 事件，包含指标、告警、日志、知识 4 类工具证据，用时 44.66 秒（单次样本，不是性能保证）。随后浏览器真实诊断及追问通过。嵌入接入点是多模态模型，使用 `/embeddings/multimodal`，每个切片单独请求；配置 `ARK_EMBEDDING_API=multimodal`，修复原文本接口不兼容的问题。HTTP 契约测试覆盖 Model ID 自动识别与 Endpoint ID 显式配置、切片与向量对应、维度检查。
- RabbitMQ：Docker Desktop 直拉官方镜像及国内镜像出现 EOF/TLS 超时，改用主机从 DaoCloud 下载官方 `rabbitmq:4.1-management-alpine` 的固定 Linux amd64 清单及镜像层，验证 SHA256 后 `docker load`。导入后检查了全部 11 层的 RootFS diff IDs 以及 Entrypoint、Cmd、Env 与下载配置一致。容器健康检查通过。实际 MySQL 96 分表测试使用真实 RabbitMQ；工作台也切到 RabbitMQ 并完成采样入库、设备最新状态更新和 Redis 缓存失效/重建。默认持久化队列为 `industrial.telemetry`，测试使用独立随机队列，避免分走工作台消息。

Compose 默认镜像为 MySQL 8.4、Redis 7.4、Milvus 2.6.0；本次受网络影响使用缓存镜像验证，未验证这些默认镜像的完整容器构建。

## 本机小样本查询

在 1,152 条演示数据、16 张 SQLite 分片、进程内缓存下，100 次 HTTP 概览查询、并发 4，P50 7.28ms、P95 29.93ms、最大 32.44ms。这是本机小样本缓存查询，不能推导亿级设备数据或整个智能诊断流程的性能。

## 当前运行与重现

工作台：`http://127.0.0.1:5173`；API：`http://127.0.0.1:8000`；RabbitMQ 管理界面：`http://127.0.0.1:15673`。

本机当前运行配置为方舟真实模型、RabbitMQ、Redis、Milvus、MCP stdio；设备采样与知识资料仍使用明确标注的演示数据。工作台保留原 SQLite 数据与 16 分片，未迁移已保存会话。MySQL 的 96 张分片另在本项目独立数据库验证通过。仓库 `.env.example` 仍以无需外部服务的演示配置作为初始默认；个人真实配置留在已忽略的 `backend/.env`，没有提交密钥。

下载失败时的重现方法与脚本见 README。重新启动当前配置前需确保 RabbitMQ、Redis 和 Milvus 容器运行。依照用户选择，本轮只完成本地联调，没有发布站点。

依赖版本记录于 `backend/requirements.lock.txt` 和 `frontend/package-lock.json`。浏览器截图保存在 `frontend/test-results/overview.png`、`assistant.png`、`mobile.png`，这些测试产物不提交 Git。

后续规模验证需要构造明确的数据规模、时间窗口、缓存命中率和并发条件；当前未声称达到亿级数据性能，也未实现分片数变更时的在线迁移。接入管线按单后端进程运行，多进程部署前需增加数据库收件箱抢占与跨进程协调。
