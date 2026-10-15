# 功能测试报告：2026-10-15

本报告保留 2026-10-15 首轮测试的原始结果：当时发现 4 个功能问题及 2 个本机环境问题。随后用户授权修复，相关问题现已修复，最新结果见 [修复验证](fix-verification-2026-10-15.md)。以下失败结果、代码行号和运行环境描述均对应修复前版本，作为前后对照。

## 最终结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 原有后端测试，默认离线配置 | 21 passed，2 skipped | [原始 JUnit](test-results/2026-10-15/backend-baseline.xml) |
| 全部后端测试，启用真实 MySQL / Redis / RabbitMQ / Milvus | **84 passed，3 failed，0 skipped**，共 87 项，94.26 秒 | [完整 JUnit](test-results/2026-10-15/backend-full.xml) |
| 原有浏览器完整流程，真实方舟与真实嵌入模型 | **通过**，包含诊断和追问 | 本地日志 `test-results/2026-10-15/browser-smoke-direct.log`、[真实服务摘要](test-results/2026-10-15/live-services.json) |
| 新增浏览器验收 | **32 passed，1 failed**，共 33 项 | [最终结构化结果](test-results/2026-10-15/browser-final.json) |
| TypeScript 检查及 Vite 生产构建 | 通过 | `npm run build` |
| Python 依赖完整性、源码编译 | 通过 | `pip check`、`compileall` |
| npm 依赖安全检查 | 0 vulnerabilities | `npm audit --json` |
| Docker Compose app/vector 配置 | 通过 | `docker compose --profile app --profile vector config --quiet` |
| Windows 启动脚本语法 | 通过 | PowerShell Parser 检查 |

后端新增 64 个测试实例；原有 23 项在真实基础设施开启后全部通过。三项新增测试故意保留失败断言，用来复现实际问题，没有标记为跳过或预期失败。

## 功能覆盖

| 模块 | 已验证行为 | 结果和限制 |
| --- | --- | --- |
| 运行总览 | 设备/告警/采样统计、小时趋势、温度/振动切换、缓存命中、数据写入与告警确认后失效、断网提示与重新连接 | 通过；浏览器断网场景使用注入的 HTTP 503 |
| 设备管理 | 水泵/电机登记、重复编号冲突、输入校验、类型筛选、按名称/编号/区域筛选、空列表、离线设备详情、历史采样、模拟采样、分析入口 | 通过；320px 页面存在溢出，见 F-04 |
| 数据接入 | 环境温湿度、指标范围校验、未知设备、时间窗口及时区校验、历史排序、晚到数据不覆盖最新值、事件状态查询、有显式时间戳的幂等和冲突 | 通过；省略时间戳的相同请求重试失败，见 F-01 |
| 队列与存储 | 真实 RabbitMQ 收发、8 路并发 64 条采样、临时失败重试成功、永久失败三次后停止、事务批写失败回滚、收件箱重启重放 | 真实队列和并发通过；重试、回滚等故障在隔离测试库注入 |
| 分片和聚合 | MySQL 96 张分片、SQLite 分片路由、禁止直接变更已有分片数、小时聚合计数/均值及重复执行 | 通过；不等于验证所有分片的大规模负载 |
| 监控告警 | 温度/振动阈值边界、重复异常不新增重复告警、确认和设备健康分别管理、重复确认冲突、已确认预警升级后重新打开、筛选/搜索/分析入口 | 通过 |
| 运行日志 | API 接入、级别与长度模型约束、MCP 日志查询、诊断证据集成 | 正常流程通过；全空格日志被接收，见 F-03 |
| 知识库 | 粘贴和 .md 文件导入、类别选择、超大文件拒绝、原文查看、长文本切片保留尾部、来源和片段、索引失败保留原文、重新索引、删除取消及确认 | 通过；浏览器使用真实嵌入与 Milvus；索引失败恢复使用受控故障 |
| 检索 | 本地关键词检索与无命中、真实 Milvus 创建/写入/检索/删除/维度保护、真实方舟嵌入模型搜索、真实文档重新索引 | 通过；Milvus 自动化底层测试使用受控向量，另有真实嵌入验证 |
| 智能助手 | 规则演示、真实方舟规划/诊断/追问、SSE 步骤和文本、工具调用反馈、报告和引用展示、缺失模型配置、工具故障明确返回 error、容量限制 | 通过；全空格问题被接收，见 F-02；取消/前端 SSE 错误的浏览器场景使用注入请求 |
| 会话与证据 | 历史会话加载、诊断和追问保存、最近上下文、进程重启后会话保留、切换设备新建会话、MCP stdio 协议、拒绝其他设备和未知工具 | 通过 |
| 页面适配 | 五个页面分别在 320/390/768/1440px 检查页面横向溢出，真实历史报告在 320/390px 检查；未捕获到未处理的浏览器运行错误 | 仅设备管理 320px 失败，其余通过 |
| 辅助脚本 | 模拟脚本真实发送 3 条采样；模拟脚本 count=0、压测脚本 requests=0 均按预期拒绝 | 通过；未重新执行镜像下载辅助脚本 |

## 修复前的问题（现均已修复）

### F-01：省略时间戳时，相同事件重试被误判为冲突（P1）

向同一台已登记设备连续提交完全相同的 JSON：

```json
{"event_id":"retry-without-timestamp","device_id":"P-101","temperature":50,"vibration":2,"current":20,"pressure":0.5}
```

预期：第一次返回 202/accepted=true，第二次返回 202/accepted=false，不重复入库。

实际：第一次 202，第二次 **409**，提示 `event_id 已被不同数据使用`。

原因：`backend/app/schemas.py` 为每次请求生成新的默认 timestamp，`backend/app/storage.py:142` 比较包含生成时间的完整 payload，因此相同原始请求不再相等。带相同显式 timestamp 的重试测试通过。此问题会影响依赖服务端补时间的网关重试。

复现测试：`test_repeated_event_without_explicit_timestamp_is_idempotent`。建议在不放松显式时间戳冲突校验的前提下，根据原始输入或首个事件时间实现重试去重。

### F-02：全空格问题仍会触发分析（P2）

请求 `POST /api/analysis`，内容为 `{"device_id":"P-101","question":"   "}`。

预期：422，拒绝无有效文字的问题。

实际：**200**，创建会话并执行完整演示分析。前端有 trim 检查，直接请求 API 可以绕过。后端真实模型模式使用同一个输入模型，存在无意义模型调用的风险；本轮复现使用离线演示，未为此发送真实模型请求。

原因：`backend/app/schemas.py:65` 只校验字符串长度，没有校验 trim 后的内容。复现测试：`test_whitespace_only_question_is_rejected`。

### F-03：全空格日志可以入库（P3）

请求 `POST /api/logs`，内容为 `{"device_id":"P-101","message":"   "}`。

预期：422，拒绝空白日志。

实际：**201**，返回 `{"saved":true}` 并持久化空白内容。

原因：`backend/app/schemas.py:47` 只校验长度。复现测试：`test_whitespace_only_log_message_is_rejected`。

### F-04：设备管理页在 320px 下横向溢出（P2）

步骤：浏览器视口设置为 320 × 844，进入“设备管理”。

预期：页面宽度不超过视口；表格可以在自己的滚动容器内横向滚动。

实际：`document.documentElement.scrollWidth = 368`，`innerWidth = 320`。顶部“添加设备 / 刷新数据 / 智能诊断”按钮组超出视口。390px、768px、1440px 的同一页面检查通过。

定位：`frontend/src/styles.css:351` 的 `.heading-actions` 使用 flex 并禁止收缩，窄屏样式未允许按钮组换行。

复现测试：浏览器 `设备管理: no page overflow at 320px`。[失败截图](test-results/2026-10-15/device-overflow-320.png)。

## 环境问题与复验

1. **Redis 原端口不可绑定。** Windows TCP 排除范围为 6377–6476，包含项目默认宿主端口 6381。启动原 Redis 容器时 Docker 返回 `bind: An attempt was made to access a socket in a way forbidden by its access permissions`。本轮创建临时 `127.0.0.1:16381 → Redis 6379`，后端和基础设施测试通过这个端口完成。新增 `INFRA_REDIS_URL` 测试配置，未修改原容器、Compose 或系统端口设置。
2. **系统代理导致真实模型连接失败。** 原启动进程继承 Windows HTTP/HTTPS 代理 `127.0.0.1:10809`，模型规划请求出现 `httpcore2.ConnectError` / `OpenAIConnectionError`。首轮浏览器 smoke 超时，历史验收也因缺失报告失败。[首轮浏览器结果](test-results/2026-10-15/browser-initial.json)。随后仅在测试进程设置 `NO_PROXY=*` 并重启，真实诊断、追问和历史报告全部通过。没有更改 Windows 系统代理或个人 `.env`；普通启动仍需考虑这两个环境问题。

## 真实服务验证详情

- 测试浏览器后端：独立 SQLite 数据库 `backend/data/qa-20261015/live.db`，16 张分片；真实 RabbitMQ、Redis、Milvus、方舟聊天模型和嵌入模型，MCP 为 stdio。
- MySQL 的 96 张分片路径通过独立基础设施测试验证；浏览器流程没有切换到 MySQL，不将两者描述成同一次全栈运行。
- 实际版本：MySQL 8.0.40、Redis 8.2.1、RabbitMQ 4.1.8、Milvus 镜像 v2.5.10。它们来自本机现有镜像，与 Compose 中部分默认镜像版本不同。
- 真实诊断报告 2,003 字符，追问报告 1,746 字符，分别保存 5 次和 4 次工具证据；覆盖指标、告警、日志、知识四类工具。[桌面报告](test-results/2026-10-15/real-analysis.png)、[390px 历史报告](test-results/2026-10-15/saved-analysis-390.png)。
- 8 路并发提交 64 条采样，64 条事件 completed，历史中恰好 64 条不同 event_id，最新设备值正确。提交与逐条核验共 2.954 秒，此值包含验证开销，不作为吞吐性能结论。
- 真实文档重新索引返回 milvus 状态；真实嵌入检索得到 4 个带文档标题、片段位置和 retrieval=milvus 的结果。
- 模型调用成功及报告保存不等于证明诊断根因正确；本轮没有建立专家标注数据集评估诊断准确率或召回率。

详细服务模式和计数见 [live-services.json](test-results/2026-10-15/live-services.json)。

## 查询测量

正式记录样本：200 次概览 HTTP 查询、并发 4、1,153 条遥测、16 张 SQLite 分片、Redis 缓存，P50 **11.74ms**、P95 **29.39ms**、最大 **33.83ms**。[测量结果](test-results/2026-10-15/benchmark.json)。

较早一次在其他集成测试同时运行时测得 P50 10.43ms、P95 37.69ms、最大 4,078.33ms，说明存在环境负载干扰下的长尾；没有以随后的小样本结果证明不存在长尾。

以上均为本机小样本缓存概览查询，不代表亿级数据、冷缓存、长时间压力、智能诊断耗时或生产服务等级。

## 复现命令

在项目根目录，启动本项目已有 MySQL、RabbitMQ、Milvus 及其依赖后，可创建替代端口 Redis：

```powershell
docker run --detach --rm --name industrial-ops-test-redis --publish 127.0.0.1:16381:6379 redis:latest
Set-Location backend
$env:RUN_INFRA_TESTS='1'
$env:INFRA_QUEUE_BACKEND='rabbitmq'
$env:INFRA_REDIS_URL='redis://localhost:16381/15'
$env:RUN_MILVUS_TESTS='1'
..\.venv\Scripts\python.exe -m pytest -q -ra --junitxml=../docs/test-results/backend-retest.xml
```

修复前版本执行时有上述 3 项后端失败；当前修复后版本执行这些用例应全部通过，不需要启动外部基础设施：

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q tests/test_acceptance.py -k 'repeated_event_without_explicit_timestamp or whitespace_only'
```

浏览器测试需要 8000 后端与 5173 前端已运行。要重现本轮真实模式，需要在独立测试进程中设置正确的 `REDIS_URL`，以及解决本机故障代理；建议继续使用独立数据库、随机命名的 RabbitMQ 队列与 Milvus 集合。

```powershell
Set-Location frontend
npm run build
npm run test:e2e
npm run test:acceptance
```

先运行 smoke，再运行 acceptance；后者会核验前者保存的真实诊断和追问。浏览器测试会新增设备、提交演示采样、确认告警，并调用配置的真实模型和嵌入服务，须指向测试数据环境。

## 范围与清理

- 本轮新增 `backend/tests/test_acceptance.py`、`frontend/tests/acceptance.mjs`，提供 `npm run test:acceptance`，并为基础设施测试增加 `INFRA_REDIS_URL`。业务代码和个人配置未修改。
- 所有浏览器写操作均指向专门创建的测试数据库、`industrial.qa.20261015` 队列、`industrial_qa_20261015` 集合和临时 Redis；未操作原业务 SQLite 数据及原知识向量集合。
- 测试结束后关闭本轮启动的前后端，删除本轮测试队列和向量集合、停止临时 Redis，并将本轮启动的五个项目基础设施容器恢复为停止状态。保留测试数据库、报告和截图用于复核。
- 未执行完整 Docker 镜像重新构建、在线分片迁移、亿级数据压测、长期运行测试、跨机器/跨浏览器兼容性测试或生产安全审计；多用户登录和权限管理也不在当前已实现功能内。
