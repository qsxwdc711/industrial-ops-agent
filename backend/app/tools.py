import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import BACKEND
from .knowledge import Knowledge
from .storage import Storage

TOOL_SPECS = [
    {'type': 'function', 'function': {'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': {argument: {'type': 'string'}},
                       'required': [argument], 'additionalProperties': False}}}
    for name, description, argument in [
        ('query_metrics', '读取设备最新指标和最近24小时趋势摘要。只读。', 'device_id'),
        ('query_alerts', '读取设备告警及其处置状态。只读。', 'device_id'),
        ('query_logs', '读取设备近期运行日志。只读。', 'device_id'),
        ('search_knowledge', '检索维修手册和故障案例，返回可引用的原文片段。', 'query'),
    ]
]


def read_tool(storage: Storage, name: str, device_id: str) -> dict:
    device = storage.device(device_id)
    if not device:
        raise ValueError('设备不存在')
    if name == 'query_metrics':
        return {'device': device, 'summary': storage.metric_summary(device_id),
                'recent_samples': storage.history(device_id, limit=8),
                'source': '设备遥测', 'window_hours': 24}
    if name == 'query_alerts':
        return {'records': storage.device_alerts(device_id), 'source': '监控告警'}
    if name == 'query_logs':
        return {'records': storage.device_logs(device_id), 'source': '运行日志'}
    raise ValueError('不支持的工具')


class Tools:
    def __init__(self, storage: Storage, knowledge: Knowledge):
        self.storage, self.knowledge = storage, knowledge
        self.session = None

    @asynccontextmanager
    async def connected(self):
        if self.storage.settings.mcp_transport == 'local':
            yield self
            return
        env = {key: os.environ[key] for key in ['PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'USERPROFILE'] if key in os.environ}
        env.update(DATABASE_URL=self.storage.url, SHARD_COUNT=str(self.storage.settings.shard_count),
                   DEMO_SEED='false', PYTHONIOENCODING='utf-8')
        params = StdioServerParameters(command=sys.executable, args=['-m', 'app.mcp_server'],
                                       cwd=str(BACKEND), env=env)
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=20)) as session:
                await session.initialize()
                self.session = session
                try:
                    yield self
                finally:
                    self.session = None

    async def call(self, name: str, arguments: dict, allowed_device: str) -> dict:
        if name == 'search_knowledge':
            query = str(arguments.get('query', ''))[:2000]
            return {'records': await self.knowledge.search(query),
                    'source': 'Milvus 向量检索' if self.knowledge.client else '关键词检索（本地演示）'}
        if name not in {'query_metrics', 'query_alerts', 'query_logs'}:
            raise ValueError('工具不在允许列表')
        # A chat is tied to one device, including follow-up model tool calls.
        if arguments.get('device_id') != allowed_device:
            raise ValueError('当前任务只允许查询所选设备')
        if self.session:
            result = await self.session.call_tool(name, {'device_id': allowed_device})
            if result.isError:
                raise ValueError('MCP 工具执行失败')
            if result.structuredContent is not None:
                return result.structuredContent
            return json.loads(next(content.text for content in result.content if content.type == 'text'))
        return await asyncio.to_thread(read_tool, self.storage, name, allowed_device)
