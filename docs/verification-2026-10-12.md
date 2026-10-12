# 首版验证记录

## 结果

- 后端：`RUN_INFRA_TESTS=1 RUN_MILVUS_TESTS=1 pytest -q`，**21 passed**。
- 前端：TypeScript 编译与 Vite 生产构建通过。
- 浏览器：Microsoft Edge 桌面及 390px 窄屏检查通过，无捕获到的页面运行错误、无横向溢出。
- 浏览器操作：设备筛选与模拟采样、告警确认、知识导入/检索/删除、MCP 证据诊断、连续问答与会话保存。
- npm audit：0 vulnerabilities。
- pip check：No broken requirements found。
- Docker Compose：app/vector profile 的配置校验通过。
- Windows 启动脚本：PowerShell 语法校验通过。

## 实际服务覆盖

- MySQL：使用本机缓存的 `mysql:8.0` 镜像，在本项目独立数据库和端口 3316 上验证 96 张遥测分片、写入、告警和 MCP 数据查询。
- Redis：使用本机缓存镜像、端口 6381 与测试数据库 15，验证概览缓存命中和写入后的失效。修复 MySQL SUM 聚合返回 Decimal 无法写入 JSON 缓存的问题。
- Milvus：使用本机缓存的 `milvusdb/milvus:v2.5.10`、独立 etcd/MinIO 服务，通过官方 v2 REST API 验证创建集合、8 维测试向量写入、COSINE 检索、来源字段、删除和维度保护。向量由测试替身生成，不代表真实嵌入模型效果。
- MCP：测试和工作台都实际通过 Python SDK 的 stdio 协议调用证据服务。
- 火山方舟：使用可控模型替身验证规划和 ReAct 工具反馈，使用 HTTP 替身验证嵌入请求格式与维度检查。未提供真实 API Key/Model ID，未进行付费模型调用。
- RabbitMQ：持久化发布、消费确认与收件箱重试适配器及 Compose 已实现。镜像下载发生校验失败/EOF，真实 RabbitMQ 联调未完成。当前真实 MySQL/Redis 测试使用本地队列。

Compose 默认镜像为 MySQL 8.4、Redis 7.4、Milvus 2.6.0；本次受网络影响使用缓存镜像验证，未验证这些默认镜像的完整容器构建。

## 本机小样本查询

在 1,152 条演示数据、16 张 SQLite 分片、进程内缓存下，100 次 HTTP 概览查询、并发 4，P50 7.28ms、P95 29.93ms、最大 32.44ms。这是本机小样本缓存查询，不能推导亿级设备数据或整个智能诊断流程的性能。

## 当前运行与重现

工作台：`http://127.0.0.1:5173`；API：`http://127.0.0.1:8000`。默认为演示数据、规则分析、本地关键词检索。配置 `backend/.env` 并重启后端可切换真实模型和基础设施。

依赖版本记录于 `backend/requirements.lock.txt` 和 `frontend/package-lock.json`。浏览器截图保存在 `frontend/test-results/overview.png`、`assistant.png`、`mobile.png`，这些测试产物不提交 Git。

后续规模验证需要构造明确的数据规模、时间窗口、缓存命中率和并发条件；当前未声称达到亿级数据性能，也未实现分片数变更时的在线迁移。接入管线按单后端进程运行，多进程部署前需增加数据库收件箱抢占与跨进程协调。
