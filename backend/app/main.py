import asyncio
import json
import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .agents import build_graph
from .cache import Cache
from .config import Settings
from .knowledge import Knowledge
from .pipeline import Pipeline
from .schemas import AnalysisInput, DeviceInput, DocumentInput, LogInput, Telemetry
from .seed import seed
from .storage import Storage
from .tools import Tools

logger = logging.getLogger(__name__)


def sse(event: str, data: dict) -> str:
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        storage = Storage(config)
        cache, knowledge = Cache(config), Knowledge(storage)
        pipeline = Pipeline(storage, cache)
        app.state.storage, app.state.knowledge = storage, knowledge
        app.state.pipeline, app.state.cache = pipeline, cache
        app.state.analysis_slots = asyncio.Semaphore(2)
        try:
            await asyncio.to_thread(storage.initialize)
            if config.demo_seed:
                await asyncio.to_thread(seed, storage)
            await cache.start()
            await knowledge.start()
            await pipeline.start()
            yield
        finally:
            await pipeline.close()
            await knowledge.close()
            await cache.close()
            storage.engine.dispose()

    app = FastAPI(title='工业智能运维系统', version='0.1.0', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins.split(','),
                       allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])

    async def ensure_device(device_id: str):
        device = await asyncio.to_thread(app.state.storage.device, device_id)
        if not device:
            raise HTTPException(404, '设备不存在')
        return device

    @app.get('/api/health')
    async def health():
        return {'status': 'ok', 'demo_data': await asyncio.to_thread(app.state.storage.has_demo_data), 'llm_mode': config.llm_mode,
                'ark_configured': config.ark_configured, 'queue_backend': config.queue_backend,
                'cache_backend': config.cache_backend, 'knowledge_backend': config.knowledge_backend,
                'mcp_transport': config.mcp_transport, 'shard_count': config.shard_count,
                'aggregation_error': app.state.pipeline.aggregate_error,
                'simulation_enabled': config.demo_seed,
                'queue_depth': sum(queue.qsize() for queue in [app.state.pipeline.raw,
                    app.state.pipeline.parsed, app.state.pipeline.calculated])}

    @app.get('/api/overview')
    async def overview():
        start = perf_counter()
        value = await app.state.cache.get('overview')
        cached = value is not None
        if value is None:
            value = await asyncio.to_thread(app.state.storage.overview)
            await app.state.cache.put('overview', value)
        return {**value, 'query_ms': round((perf_counter() - start) * 1000, 2), 'cache_hit': cached}

    @app.get('/api/devices')
    async def devices(q: str = Query(default='', max_length=100)):
        table = app.state.storage.devices
        stmt = select(table).order_by(table.c.id)
        if q:
            stmt = stmt.where(table.c.id.contains(q) | table.c.name.contains(q))
        return await asyncio.to_thread(app.state.storage.rows, stmt)

    @app.get('/api/devices/{device_id}')
    async def device_detail(device_id: str):
        return await ensure_device(device_id)

    @app.post('/api/devices', status_code=201)
    async def register_device(item: DeviceInput):
        try:
            await asyncio.to_thread(app.state.storage.register_device, item.model_dump())
        except IntegrityError as error:
            raise HTTPException(409, '设备编号已存在') from error
        await app.state.cache.invalidate()
        return await ensure_device(item.id)

    @app.post('/api/logs', status_code=201)
    async def append_log(item: LogInput):
        await ensure_device(item.device_id)
        await asyncio.to_thread(app.state.storage.append_log, item.model_dump())
        return {'saved': True}

    @app.get('/api/devices/{device_id}/telemetry')
    async def telemetry(device_id: str, hours: int = Query(default=24, ge=1, le=168)):
        await ensure_device(device_id)
        return await asyncio.to_thread(app.state.storage.history, device_id, hours)

    @app.post('/api/telemetry', status_code=202)
    async def ingest(item: Telemetry):
        await ensure_device(item.device_id)
        try:
            accepted = await asyncio.to_thread(app.state.storage.accept, item)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {'event_id': item.event_id, 'accepted': accepted,
                'message': '已进入处理队列' if accepted else '重复事件，已忽略'}

    @app.get('/api/events/{event_id}')
    async def event_status(event_id: str):
        result = await asyncio.to_thread(app.state.storage.event_status, event_id)
        if result is None:
            raise HTTPException(404, '事件不存在')
        return result

    @app.post('/api/devices/{device_id}/simulate', status_code=202)
    async def simulate(device_id: str):
        if not config.demo_seed:
            raise HTTPException(403, '当前环境未启用演示数据')
        device = await ensure_device(device_id)
        item = Telemetry(device_id=device_id, temperature=round((device['temperature'] or 50) + 0.2, 1),
            vibration=device['vibration'] or 1.6, current=device['current'] or 20,
            pressure=device['pressure'] or 0, ambient_temperature=26.4, humidity=58, source='demo-simulator')
        return await ingest(item)

    @app.get('/api/alerts')
    async def alerts():
        return await asyncio.to_thread(app.state.storage.device_alerts)

    @app.post('/api/alerts/{alert_id}/acknowledge')
    async def acknowledge(alert_id: str):
        changed = await asyncio.to_thread(app.state.storage.acknowledge, alert_id)
        if not changed:
            raise HTTPException(409, '告警不存在或已确认')
        await app.state.cache.invalidate()
        return {'status': 'acknowledged'}

    @app.get('/api/knowledge')
    async def documents():
        table = app.state.storage.documents
        stmt = select(table.c.id, table.c.title, table.c.category, table.c.chunks,
                      table.c.index_status, table.c.created_at).order_by(table.c.created_at.desc())
        return await asyncio.to_thread(app.state.storage.rows, stmt)

    @app.get('/api/knowledge/search')
    async def search_knowledge(q: str = Query(min_length=2, max_length=2000)):
        try:
            return await app.state.knowledge.search(q)
        except Exception as error:
            logger.exception('Knowledge search failed')
            raise HTTPException(502, '知识检索失败，请检查检索服务配置') from error

    @app.get('/api/knowledge/{document_id}')
    async def document_detail(document_id: str):
        table = app.state.storage.documents
        rows = await asyncio.to_thread(app.state.storage.rows, select(table).where(table.c.id == document_id))
        if not rows:
            raise HTTPException(404, '文档不存在')
        return rows[0]

    @app.post('/api/knowledge', status_code=201)
    async def add_document(item: DocumentInput):
        try:
            return await app.state.knowledge.add(item)
        except Exception as error:
            logger.exception('Knowledge indexing failed')
            raise HTTPException(502, '文档索引失败；原文已保留，可在修复服务后重新索引') from error

    @app.post('/api/knowledge/{document_id}/reindex')
    async def reindex_document(document_id: str):
        await document_detail(document_id)
        try:
            await app.state.knowledge.index(document_id)
        except Exception as error:
            logger.exception('Knowledge reindexing failed')
            raise HTTPException(502, '重新索引失败，请检查嵌入模型与 Milvus 配置') from error
        return {'status': config.knowledge_backend}

    @app.delete('/api/knowledge/{document_id}')
    async def delete_document(document_id: str):
        await document_detail(document_id)
        await app.state.knowledge.delete(document_id)
        return {'deleted': True}

    @app.get('/api/sessions')
    async def sessions():
        table = app.state.storage.sessions
        return await asyncio.to_thread(app.state.storage.rows, select(table).order_by(table.c.created_at.desc()).limit(30))

    @app.get('/api/sessions/{session_id}')
    async def session_detail(session_id: str):
        table = app.state.storage.sessions
        rows = await asyncio.to_thread(app.state.storage.rows, select(table).where(table.c.id == session_id))
        if not rows:
            raise HTTPException(404, '会话不存在')
        return {**rows[0], 'messages': await asyncio.to_thread(app.state.storage.session_messages, session_id)}

    @app.post('/api/analysis')
    async def analysis(item: AnalysisInput):
        await ensure_device(item.device_id)
        if config.llm_mode == 'ark' and not config.ark_configured:
            raise HTTPException(503, '请在后端配置 ARK_API_KEY 和 ARK_MODEL')
        if app.state.analysis_slots.locked():
            raise HTTPException(429, '当前分析任务较多，请稍后重试')
        history = []
        if item.session_id:
            previous = await session_detail(item.session_id)
            if previous['device_id'] != item.device_id:
                raise HTTPException(409, '切换设备后请新建会话')
            session_id, history = item.session_id, previous['messages']
        else:
            session_id = await asyncio.to_thread(app.state.storage.create_session, item.device_id, item.question)

        async def stream():
            async with app.state.analysis_slots:
                yield sse('session', {'session_id': session_id, 'mode': config.llm_mode})
                await asyncio.to_thread(app.state.storage.save_message, session_id, 'user', item.question, mode=config.llm_mode)
                try:
                    async with asyncio.timeout(180):
                        async with Tools(app.state.storage, app.state.knowledge).connected() as tools:
                            graph = build_graph(config, tools)
                            initial = {'question': item.question, 'device_id': item.device_id, 'history': history}
                            async for mode, update in graph.astream(initial, stream_mode=['custom', 'updates'],
                                                                   config={'recursion_limit': 40}):
                                if mode == 'custom':
                                    yield sse(update['type'], update)
                                elif 'finish' in update:
                                    result = update['finish']['result']
                                    result['session_id'] = session_id
                                    await asyncio.to_thread(app.state.storage.save_message, session_id, 'assistant',
                                        result['report'], result['evidence'], config.llm_mode)
                                    yield sse('result', result)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception('Analysis failed')
                    yield sse('error', {'message': '分析失败，请检查模型配置、网络和证据服务；详情见后端日志。'})
        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    return app


app = create_app()
