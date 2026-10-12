# Industrial Ops Implementation Plan

**Goal:** 在当前目录交付可运行的 Python + React 工业运维系统，贯通五项已确认功能。

**Architecture:** FastAPI 模块化后端配合 React 前端。基础设施通过配置切换，本地演示与真实模型/向量服务的状态明确区分。

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, asyncio, RabbitMQ, Redis, LangGraph, LangChain model adapters, MCP, Milvus, React, TypeScript, Vite.

用户已要求开始执行，本计划在当前会话按步骤实施。

## 1. 配置、存储与演示场景

- [x] 新建 `backend/app/config.py`, `schemas.py`, `storage.py`, `seed.py`，提供配置校验、固定分片、持久化收件箱、小时聚合、设备/告警/知识/会话存储。
- [x] SHA256 路由使用 `int.from_bytes(hashlib.sha256(device_id.encode()).digest()[:8], 'big') % shard_count`；保存分片元数据并检测配置漂移。
- [x] 使用 `pytest tests/test_system.py -q` 验证重复事件不产生重复遥测、改变分片数被拒绝、演示数据显式标记。

## 2. 异步接入与缓存

- [x] 新建 `pipeline.py`, `cache.py`，接入返回 202 和事件编号，收件箱保留失败信息；解析、计算与写入分成三级有界队列。
- [x] RabbitMQ 发布使用持久化消息，消费者写入成功后 ACK；Redis 对概览结果执行有 TTL 的缓存。
- [x] 测试发送同一个 event_id 两次后，分片中的记录数只增长一次，并确认指标越阈值生成告警。

## 3. 知识检索与 MCP

- [x] 新建 `knowledge.py`, `tools.py`, `mcp_server.py`；知识导入保留文档与片段编号，关键词模式显式命名；Milvus 使用嵌入模型与 COSINE 检索。
- [x] MCP 通过 `StdioServerParameters(command=sys.executable, args=['-m', 'app.mcp_server'])` 建立会话；只读工具返回结构化设备、告警与日志证据。
- [x] 验证无关问题不强行引用文档；通过 MCP 客户端调用指标工具并核对设备编号。

## 4. 智能体与 API

- [x] 新建 `agents.py`, `main.py`；LangGraph 按 planner → executor → analyst → tools → analyst 编排，工具调用最多四轮。
- [x] SSE 事件使用 `event: step\ndata: {json}\n\n`、`token`、`result` 和 `error`；保存会话消息和诊断报告，处理断开连接与超时。
- [x] pytest 覆盖诊断证据、会话延续、非法设备、未配置真实模型时的错误以及流中失败事件。

## 5. React 工作台

- [x] 新建 `frontend/src/{App.tsx,api.ts,types.ts,styles.css}`，实现五个页面、设备筛选/详情、告警确认、文档导入/删除、诊断流和历史会话。
- [x] 运行 `npm run build`；浏览器测试访问五个页面、确认告警、导入知识、触发并完成诊断，保存截图。

## 6. 启动、部署与交付

- [x] 新建 README、环境变量示例、Dockerfiles、Compose、Windows 启动脚本、性能测试脚本。
- [x] 验证 `docker compose config --quiet`；记录依赖锁与测试结果，说明外部模型和向量检索的凭据要求。

完整验证结果见 `docs/verification-2026-10-12.md`。用户完成个人凭据配置后，真实方舟诊断、追问和多模态嵌入检索均已联调通过；RabbitMQ 经 DaoCloud 镜像下载、SHA256 校验及导入后，真实采样入库验证通过。本机工作台使用 RabbitMQ、Redis、Milvus 与 MCP stdio，保留原 SQLite 会话和 16 分片；MySQL 96 分表通过独立集成测试。用户选择先完成本地联调，部署方案后续决定。
