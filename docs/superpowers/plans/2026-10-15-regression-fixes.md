# Regression Fixes Implementation Plan

> 用户已授权在当前会话内直接完成修复与验证，不另行委派、提交或发布。

**Goal:** 修复测试报告中的四个功能缺陷，并为 Redis 端口与方舟代理问题提供项目内的持久配置。

**Architecture:** 保持收件箱、队列、分片和 LangGraph 的现有结构。幂等比较复用首次接收时间；输入清理放在 Pydantic 模型；方舟 HTTP 连接由应用生命周期管理。端口和代理策略通过配置公开。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、httpx、React/CSS、Docker Compose、pytest、Playwright。

## Task 1: 幂等、输入校验和窄屏样式

修改 `backend/app/storage.py`、`backend/app/schemas.py`、`frontend/src/styles.css`，扩展 `backend/tests/test_acceptance.py`。

- [x] 执行现有三个失败用例，确认修复前仍失败：

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q tests/test_acceptance.py -k 'repeated_event_without_explicit_timestamp or whitespace_only'
```

- [x] 在 accept 中只序列化一次 payload；重复事件比较前，对省略 timestamp 的请求执行：

```python
if existing is not None and 'timestamp' not in item.model_fields_set:
    payload['timestamp'] = existing['timestamp']
```

- [x] 在 LogInput.message 和 AnalysisInput.question 添加各自 field_validator；执行 `value = value.strip()`，`len(value) < 2` 抛 ValueError，否则返回 value。
- [x] 在 max-width:720px 的媒体查询内为 `.heading-actions` 设置 `max-width:100%; flex-wrap:wrap; flex-shrink:1`。
- [x] 扩展测试验证：重试只保留一条历史及首次时间；更改 temperature/source/device/timestamp 仍 409；并发重复提交仅一次 accepted；所有空白类别及单字符拒绝，正常文本去除首尾空白。
- [x] 运行扩展后的 acceptance 后端测试，预期全部通过。

## Task 2: 方舟 HTTP 生命周期与 Redis 配置

修改 `backend/app/config.py`、`backend/app/main.py`、`backend/app/agents.py`、`backend/app/knowledge.py`、`compose.yaml`、`backend/.env.example`、`backend/tests/test_infrastructure.py`、`README.md`。本机被忽略的配置仅同步 Redis 连接与镜像，不输出或改动凭据。

- [x] 添加 `ark_trust_env: bool = False`，聊天/嵌入客户端使用该值。
- [x] lifespan 在 ark 模式创建 `httpx.AsyncClient(timeout=45, trust_env=config.ark_trust_env)`，存入 app.state，并在 finally 关闭；build_graph 接收该客户端并传给 ChatOpenAI 的 `http_async_client`。
- [x] Compose Redis 配置改为：

```yaml
image: ${REDIS_IMAGE:-redis:7.4-alpine}
ports: ["127.0.0.1:${REDIS_PORT:-16381}:6379"]
```

- [x] 同步示例和测试默认 Redis URL 至 localhost:16381；Compose 透传 ARK_TRUST_ENV。
- [x] 补充代理策略默认值、显式 opt-in、HTTP 客户端关闭及传入真实模型路径的验证。客户端使用受控网络响应测试，不额外调用真实模型。

## Task 3: 完整回归与结果记录

- [x] 使用本机已有镜像启动本项目真实基础设施，保留已有 Redis 数据卷；配置相同的 16381 宿主端口。
- [x] 运行 `RUN_INFRA_TESTS=1 INFRA_QUEUE_BACKEND=rabbitmq RUN_MILVUS_TESTS=1 pytest -q -ra`，将 JUnit 写入 `docs/test-results/2026-10-15-fixed/backend-full.xml`。预期 0 failed、0 skipped。
- [x] 运行 `npm run build`，预期 TypeScript 和 Vite 均成功。
- [x] 用隔离数据启动前后端，保留原系统代理环境、不设置 NO_PROXY；依次执行 `npm run test:e2e` 和 `npm run test:acceptance`。预期原有流程通过、33 项浏览器验收全部通过。
- [x] 查看 320px 设备页截图，确认按钮可访问且没有页面溢出；检查真实诊断/追问报告及证据已保存。
- [x] 清理本轮测试进程、队列和向量集合，恢复初始容器运行状态；保留结果和截图。
- [x] 更新原报告的当前修复状态，新增 `docs/fix-verification-2026-10-15.md`；执行 `git diff --check` 并逐项复核改动。
