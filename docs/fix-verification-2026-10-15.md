# 问题修复与回归验证：2026-10-15

首轮测试报告中的四个功能缺陷已修复，同时处理了 Redis 端口和方舟系统代理两个启动环境问题。完整回归结果为 **后端 120 passed、0 failed、0 skipped；浏览器验收 33 passed、0 failed**。

首轮失败证据仍保存在 [原测试报告](test-report-2026-10-15.md)；本轮结果保存在独立的 `test-results/2026-10-15-fixed/` 目录。

## 修复内容

| 问题 | 修复后行为 | 验证 |
| --- | --- | --- |
| F-01：省略时间戳的同一事件重试返回 409 | 沿用首次收件箱记录的时间进行比较，相同请求返回 202 / accepted=false；显式时间戳或其他数据变化仍返回 409 | SQLite、真实 MySQL/RabbitMQ、并发 HTTP 重试均通过 |
| F-02：全空格问题触发分析 | 去除首尾空白后，少于两个字符返回 422，不创建会话或调用模型 | 空格、制表符、换行、Unicode 空白、单字符及合法文本清理均通过 |
| F-03：全空格日志入库 | 同样在后端按清理后的有效文本校验，无效内容返回 422，合法日志保存清理后的内容 | API 与数据库内容核验通过 |
| F-04：320px 设备管理页溢出 | 操作按钮组限制最大宽度、允许收缩与换行，三个按钮仍可使用 | 320px 页面宽度恢复为 320px；五页在四种宽度下均通过 |
| Redis 6381 被 Windows 保留 | Compose 默认宿主端口改为 16381，可用 REDIS_PORT 覆盖；同步后端、测试默认值与示例 | 正式项目 Redis 容器通过新映射启动并健康，无临时 Redis 容器 |
| 失效系统代理导致方舟连接失败 | 聊天和嵌入默认直连，ARK_TRUST_ENV=true 可显式继承系统代理；聊天连接由应用启动/关闭管理 | 保留原系统代理、不设置 NO_PROXY 时，真实诊断和追问通过 |

幂等修复没有修改数据库结构或原有事件记录；重复请求不改变首次时间。等价时区表示的显式时间戳仍可去重，不同时间戳继续冲突。

## 测试结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 修复前原始三个失败用例 | 3 failed | [before.xml](test-results/2026-10-15-fixed/before.xml) |
| 扩展后端验收 | 96 passed | [acceptance.xml](test-results/2026-10-15-fixed/acceptance.xml) |
| 完整后端，含真实基础设施 | **120 passed，0 skipped，113.43 秒** | [backend-full.xml](test-results/2026-10-15-fixed/backend-full.xml) |
| 前端 TypeScript / Vite 生产构建 | 通过 | `npm run build` |
| 原有真实模型浏览器 smoke | 通过：采样、告警、知识导入/检索/删除、诊断、追问和窄屏 | 本地日志 `test-results/2026-10-15-fixed/browser-smoke.log` |
| 全部浏览器验收 | **33 passed，0 failed**，无捕获的未处理页面运行错误 | [browser-final.json](test-results/2026-10-15-fixed/browser-final.json) |
| Python 依赖检查 | No broken requirements found | `pip check` |
| Compose app/vector 配置 | 通过 | `docker compose --profile app --profile vector config --quiet` |
| 修改内容校验 | 通过 | `git diff --check` |

后端新增的覆盖包括 18 组重试数据冲突、等价时区、并发重试、无效文本不产生副作用、有效文本清理，以及通过受控 HTTP 响应驱动真实 LangChain/OpenAI SDK，验证代理配置传入和 HTTP 客户端关闭。真实嵌入 HTTP 契约同时检查 ARK_TRUST_ENV=false/true 两种配置。

浏览器仍按五个页面 × 320/390/768/1440px 检查布局，另在 320/390px 加载真实历史报告。浏览器的 HTTP/SSE 故障和取消场景使用受控注入；真实模型成功流程独立使用实际服务。

## 真实服务与重试验证

本轮基础设施测试实际使用 MySQL 96 张分片、RabbitMQ、Redis 和 Milvus。浏览器使用独立的 SQLite 16 分片测试库，连接真实 RabbitMQ、Redis、Milvus、MCP stdio、方舟聊天和嵌入模型，不将两种数据库路径描述为同一条浏览器链路。

- 原系统代理仍存在，NO_PROXY 未设置，ARK_TRUST_ENV=false。
- 真实模型首轮诊断保存 2,229 字符，追问保存 2,189 字符；两次报告各有指标、告警、日志、知识四类工具证据。
- 另以 8 路并发发送 16 次完全相同且省略 timestamp 的 HTTP 请求，全部返回 202，只有一次 accepted=true，RabbitMQ 处理后历史中恰好一条记录。
- 回传该记录的显式时间戳仍去重；更改时间戳或温度均返回 409。
- 真实后端对空白问题和空白日志返回 422，空白问题未新增会话。

模式、计数和消息长度见 [live-services.json](test-results/2026-10-15-fixed/live-services.json)。真实模型连通和报告生成已验证，本轮未评估故障诊断准确率，也未重新执行大规模性能测试。

## 截图

[320px 设备页修复后](test-results/2026-10-15-fixed/devices-320.png) 与 [修复前](test-results/2026-10-15/device-overflow-320.png) 可对照按钮换行和页面宽度。

[真实模型桌面报告](test-results/2026-10-15-fixed/real-analysis.png)、[390px 历史报告](test-results/2026-10-15-fixed/saved-analysis-390.png)。

## 配置与运行

仓库默认配置和 `backend/.env.example` 已更新。本机被忽略的 `backend/.env` 仅同步 Redis URL 的端口至 16381，保留其他设置；根目录被忽略的 `.env` 设置 REDIS_PORT=16381、REDIS_IMAGE=redis:latest，继续使用原来缓存的 Redis 8.2.1 镜像，避免对原数据卷降级读取。没有修改 Windows 系统代理、保留端口、模型密钥或其他项目。

代理需要显式启用时，在后端配置 `ARK_TRUST_ENV=true`。Redis 需要其他宿主端口时，修改根目录 REDIS_PORT 并同步本地后端 REDIS_URL；容器内连接仍为 redis:6379。

完整后端回归：

```powershell
# 需本项目 MySQL / RabbitMQ / Redis / Milvus 已运行
Set-Location backend
$env:RUN_INFRA_TESTS='1'
$env:INFRA_QUEUE_BACKEND='rabbitmq'
$env:RUN_MILVUS_TESTS='1'
..\.venv\Scripts\python.exe -m pytest -q -ra
```

隔离测试前后端在 8000/5173 运行后，依次执行：

```powershell
Set-Location frontend
npm run build
npm run test:e2e
npm run test:acceptance
```

这些浏览器测试会写入演示采样、确认告警、新增设备，并调用所配置的模型和嵌入服务；本轮使用专门的测试数据环境。

## 清理与交付

已关闭测试前后端、删除本轮专用 RabbitMQ 队列与 Milvus 集合，并将本轮启动的六个基础设施容器恢复为停止状态。保留本机 Redis 的新端口映射及原数据卷，测试数据库保留在被忽略的 `backend/data/qa-fixed-20261015/` 供复核。原业务 SQLite 数据库和原知识集合未用于浏览器写操作。

代码、回归测试与验证文档包含于项目；提交与远程仓库状态以 Git 记录为准。
