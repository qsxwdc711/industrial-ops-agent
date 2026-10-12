# 智维 · 工业智能运维系统

首版检查结果与验证范围见 [验证记录](docs/verification-2026-10-12.md)。

面向水泵、电机的 Python + React 运维工作台，连接设备数据、告警、日志、知识文档和智能分析。系统以单机开发原型实现五项功能；亿级数据、扩展分片迁移与生产部署能力需另行验证。

## 已实现的功能

| 模块 | 实现 |
| --- | --- |
| 数据接入 | FastAPI 接入设备与环境指标，持久化收件箱、事件幂等、解析/计算/存储三级有界队列、最多 32 条事务批写、三次处理重试 |
| 数据存储 | SQLAlchemy 支持 SQLite/MySQL，设备编号 SHA256 路由至固定分片，设备/时间复合索引，小时聚合 |
| 查询缓存 | 本地 TTL 缓存或 Redis；遥测写入、告警确认后使概览缓存失效 |
| 智能分析 | LangGraph 规划、逐步执行、故障分析与 ReAct 工具反馈循环；方舟兼容 OpenAI 接口；SSE 输出进度和文本 |
| 多源证据 | MCP stdio 提供设备指标、告警与日志只读工具；模型不能执行任意 SQL 或控制设备 |
| 知识库 | 手册/案例/规程导入、段落切片、来源引用；本地关键词检索或 Milvus + 独立嵌入模型向量检索 |
| 上下文 | SQLite/MySQL 保存会话与工具证据，同一设备的后续问题带入最近 12 条历史消息 |
| 前端 | React + TypeScript，运行总览、设备登记与详情、告警确认、知识管理、智能助手与历史对话；适配窄屏 |

**演示模式明确使用模拟设备数据和规则分析。没有 API Key 时也可以完整操作工作台；这不代表已调用真实模型或执行向量检索。** 初次启动创建 12 台设备、1,152 条历史采样和 4 份演示资料。默认 16 张分片，支持配置 1–128 张。设备状态、告警处置状态和数据处理状态分别管理；告警确认不会把异常设备改为正常。

智能分析包含规划与分析两个模型角色，指标、告警、日志和知识查询作为受控工具任务共享证据。

## 本地启动（Windows）

需要 Python 3.12 或 3.13、Node.js 20+。当前前端使用兼容 Node 20.18 的 Vite 6.4.4。首次安装在项目根目录运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
Set-Location frontend
npm ci
Set-Location ..
```

之后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

浏览器打开 [工作台](http://127.0.0.1:5173)，API 文档位于 [Swagger](http://127.0.0.1:8000/docs)。关闭启动脚本会停止它启动的后端。也可以在两个终端分别运行：

```powershell
# 终端一：项目根目录
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
# 终端二：frontend 目录
npm run dev
```

## 接入火山引擎方舟

在 `backend/.env` 中修改下列配置，然后重启后端：

```dotenv
LLM_MODE=ark
ARK_API_KEY=在本机填写你的方舟APIKey
ARK_MODEL=在方舟控制台复制ModelID或EndpointID
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

选择支持 Function Calling/工具调用的模型。API Key 只由后端读取，前端不会拿到密钥。真实模型配置缺失返回 503；模型或工具调用失败通过 SSE error 显示，不会偷偷返回规则结果。界面会显示当前模型模式。`ARK_MODEL` 的示例说明文字必须替换成控制台提供的真实 ID。

## 真实基础设施

本地开发可以只使用 SQLite，不需要 Docker。消息队列、缓存和 MySQL 的真实连接配置已提供，运行：

```powershell
docker compose up -d mysql rabbitmq redis
```

在 `backend/.env` 设置：

```dotenv
DATABASE_URL=mysql+pymysql://industrial:industrial@localhost:3316/industrial?charset=utf8mb4
QUEUE_BACKEND=rabbitmq
RABBITMQ_URL=amqp://industrial:industrial@localhost:5673/
CACHE_BACKEND=redis
REDIS_URL=redis://localhost:6381/0
```

RabbitMQ 管理界面位于 [本地管理界面](http://127.0.0.1:15673)，开发账号为 `industrial / industrial`。Compose 创建独立的项目服务和数据卷，不复用电脑上已有的数据库。开发密码仅用于本机原型。

### RabbitMQ 镜像下载失败时

Compose 支持通过 `RABBITMQ_IMAGE` 单独替换 RabbitMQ 镜像源。使用 [DaoCloud 公共镜像服务](https://github.com/DaoCloud/public-image-mirror)：

```powershell
$env:RABBITMQ_IMAGE='m.daocloud.io/docker.io/library/rabbitmq:4.1-management-alpine'
docker compose up -d rabbitmq
```

如果主机能访问镜像源，但 Docker Desktop 下载仍出现 EOF 或 TLS 超时，可以用本项目脚本从主机下载固定的 Linux amd64 镜像清单和镜像层，校验 SHA256 后导入：

```powershell
.\.venv\Scripts\python.exe scripts\download_rabbitmq.py
docker load --input backend\data\rabbitmq-image\rabbitmq.tar
Remove-Item Env:RABBITMQ_IMAGE -ErrorAction SilentlyContinue
docker compose up -d --pull never rabbitmq
```

脚本支持镜像层断点续传，下载文件位于已忽略的 `backend/data`。它不修改 Docker 的全局镜像源配置。固定的镜像清单与平台见脚本；升级 RabbitMQ 或在其他架构运行时需重新选择并核验清单。

完整容器运行：

```powershell
docker compose --profile app up -d --build
```

容器后端默认建 **96 张分片**，使用 MySQL + RabbitMQ + Redis。工作台仍为 5173。若同时运行本地后端，需要先停止本地服务以释放 8000/5173 端口。Compose 的模型变量从项目根目录 `.env` 或宿主环境读取；它不会自动读取 `backend/.env`。

## Milvus 向量检索

先启动 Milvus。后端通过官方 v2 REST API 异步访问，无需额外安装 Python 向量库客户端：

```powershell
docker compose --profile vector up -d milvus
```

配置 `backend/.env`：

```dotenv
KNOWLEDGE_BACKEND=milvus
MILVUS_URI=http://localhost:19531
MILVUS_TOKEN=
ARK_API_KEY=在本机填写你的方舟APIKey
ARK_EMBEDDING_MODEL=嵌入模型的ModelID或EndpointID
ARK_EMBEDDING_API=auto
EMBEDDING_DIMENSION=模型实际返回的维度
```

嵌入模型与聊天模型分别配置。`auto` 自动识别 `doubao-embedding-vision` Model ID，使用 [多模态向量化接口](https://docs.volcengine.com/docs/ark/multimodal-vectorization-api?lang=zh)；其余默认调用 `/embeddings`。多模态模型使用 Endpoint ID 时，需要显式配置 `ARK_EMBEDDING_API=multimodal`。多模态接口每个文档切片分别请求一个向量，最多四个请求并发，并指定 `EMBEDDING_DIMENSION`（1024 或 2048）。也可以设为 `text` 强制使用文本接口。嵌入和本地 Milvus HTTP 请求直接连接服务，避免系统代理干扰。

启用 Milvus 身份验证时填 `MILVUS_TOKEN`。向量维度与已有集合不一致时启动失败。切换到 Milvus时及重启后端时会重新索引已有文档，并可能产生嵌入 API 费用。索引失败保留原文并显示失败状态，可在前端重新索引。

容器模式还需在根目录 `.env` 设置相关变量，并同时启用 `app`、`vector` 两个 profile。

## 数据与 API 示例

前端“设备管理 → 添加设备”登记设备，或调用 `POST /api/devices`：

```json
{"id":"P-109","name":"新增循环水泵","kind":"pump","area":"循环水站"}
```

向 `POST /api/telemetry` 提交数据：

```json
{"event_id":"gateway-sample-001","device_id":"P-109","temperature":62.5,"vibration":2.1,"current":21.8,"pressure":0.55,"ambient_temperature":26.4,"humidity":58,"source":"device-gateway"}
```

接口返回 202，使用 `GET /api/events/{event_id}` 检查是否完成。未给 timestamp 时使用当前 UTC 时间；指定时需携带时区。同一 event_id 同一内容会去重，若内容冲突则返回 409。遥测中的较旧采样只进入历史，不覆盖设备最新状态。温度和振动阈值是演示规则，实际设备需依据规格配置。

`POST /api/logs` 接入日志：

```json
{"device_id":"P-109","level":"info","message":"完成轴承润滑，现场异响待复查"}
```

生成演示采样：

```powershell
.\.venv\Scripts\python.exe scripts\simulate.py --device P-101 --count 10
```

## 验证

```powershell
# 后端测试，包含真实 MCP stdio 协议调用和可控模型测试替身
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q
Set-Location ..

# 前端检查
Set-Location frontend
npm run build
# 需要本地前后端已运行，使用系统 Microsoft Edge
npm run test:e2e
Set-Location ..

# 本机概览查询测量，输出样本规模、并发和 P50/P95
.\.venv\Scripts\python.exe scripts\benchmark.py --requests 200 --concurrency 4
```

基础设施测试为显式启用：后端目录设置 `$env:RUN_INFRA_TESTS='1'` 可验证 MySQL/Redis，设置 `$env:INFRA_QUEUE_BACKEND='rabbitmq'` 后追加真实 RabbitMQ 验证；设置 `$env:RUN_MILVUS_TESTS='1'` 可验证真实 Milvus 的索引、检索、引用与删除。Milvus 测试使用受控测试向量，不调用或验证方舟嵌入模型效果。

RabbitMQ 默认队列是 `industrial.telemetry`，可用 `RABBITMQ_QUEUE` 修改。不同数据库实例应使用不同队列，避免消费者分走其他实例的数据。基础设施测试使用随机命名队列，完成后只删除自己的测试队列。

测试替身可验证方舟调用流程和工具反馈，不能证明真实 API 权限或模型效果。50ms 是指定查询场景的优化目标，本地小样本测量不代表亿级数据上的性能。分片数持久化后不能直接改，否则会改变路由；需要设计并验证迁移过程。当前接入管线按单后端进程运行，使用多进程前需要实现收件箱的数据库抢占、任务租约和跨进程协调。当前前端用于本机开发，未实现多用户登录与权限管理。

浏览器测试会使用当前后端配置。在 `LLM_MODE=ark`、`KNOWLEDGE_BACKEND=milvus` 下，它会发起真实诊断、追问、文档嵌入和检索调用；离线验证请使用演示模式。真实服务验证结果记录于验证文档，不以测试替身结果代替。

## 后续站点部署

当前先完成本地联调。后续可以把完整 Docker 服务部署到云服务器，通过反向代理、域名和 HTTPS 访问；需要补齐登录权限及生产配置。如果选择 Codex Sites，可以托管 React 前端，Python API、RabbitMQ、MySQL、Redis 和 Milvus 继续部署在独立后端服务器上，再通过 HTTPS API 接入。方舟密钥始终保存在后端环境变量中。

## 阅读代码的顺序

不熟悉 Python 时，建议沿着一条采样数据看代码：`schemas.py` 的输入模型 → `main.py` 的接入接口 → `storage.py` 的持久化收件箱 → `pipeline.py` 的队列与 `processing.py` 的指标计算 → `storage.py` 的分片与告警。再阅读 `tools.py`/`mcp_server.py` 和 `agents.py`，了解证据如何进入诊断流程。

```mermaid
flowchart LR
  Device[设备/环境采样] --> API[FastAPI]
  API --> Inbox[持久化收件箱]
  Inbox --> Queue[本地队列或 RabbitMQ]
  Queue --> Parse[解析队列]
  Parse --> Compute[指标计算队列]
  Compute --> Write[批量存储队列]
  Write --> DB[(设备分片/告警/聚合)]
  DB --> Cache[TTL 缓存或 Redis]
  React[React 工作台] --> API
  API --> Graph[LangGraph 规划与分析]
  Graph --> MCP[MCP 指标/告警/日志工具]
  MCP --> DB
  Graph --> RAG[关键词检索或 Milvus RAG]
  Graph --> Ark[火山方舟模型 API]
  Graph --> SSE[SSE 进度/结果/证据]
  SSE --> React
```

框架参考：[LangGraph 工作流](https://docs.langchain.com/oss/python/langgraph/workflows-agents)、[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[Milvus Docker Compose](https://milvus.io/docs/install_standalone-docker-compose.md)、[火山方舟调用](https://docs.volcengine.com/docs/ark/online-inference-standard?lang=zh)。
