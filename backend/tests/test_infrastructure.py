"""Opt-in tests against this project's independent Docker services."""
import asyncio
import os
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.cache import Cache
from app.config import Settings
from app.main import create_app
from app.storage import Storage


@pytest.mark.skipif(os.getenv('RUN_INFRA_TESTS') != '1', reason='Opt-in Docker infrastructure test')
def test_mysql_96_shards_redis_and_optional_rabbitmq():
    settings = Settings(_env_file=None, database_url='mysql+pymysql://industrial:industrial@localhost:3316/industrial?charset=utf8mb4',
        shard_count=96, demo_seed=False, queue_backend=os.getenv('INFRA_QUEUE_BACKEND', 'local'),
        rabbitmq_url='amqp://industrial:industrial@localhost:5673/',
        rabbitmq_queue='industrial.test.' + uuid4().hex, cache_backend='redis',
        redis_url='redis://localhost:6381/15', mcp_transport='stdio', aggregate_interval=3600)
    device_id = 'T-' + uuid4().hex[:8]
    storage = None
    try:
        with TestClient(create_app(settings)) as client:
            storage = client.app.state.storage
            registration = client.post('/api/devices', json={'id': device_id, 'name': '基础设施验证水泵', 'kind': 'pump', 'area': '集成测试区域'})
            assert registration.status_code == 201
            event_id = 'infra-' + uuid4().hex
            payload = {'event_id': event_id, 'device_id': device_id, 'temperature': 86,
                       'vibration': 7.4, 'current': 22, 'pressure': .6}
            assert client.post('/api/telemetry', json=payload).status_code == 202
            for _ in range(200):
                if client.get(f'/api/events/{event_id}').json()['status'] == 'completed':
                    break
                time.sleep(.1)
            else:
                pytest.fail('Configured pipeline did not persist telemetry')
            assert client.get(f'/api/devices/{device_id}').json()['status'] == 'critical'
            overview = client.get('/api/overview').json()
            assert overview['shard_count'] == 96 and overview['telemetry_count'] >= 1
            assert client.get('/api/overview').json()['cache_hit']
            response = client.post('/api/analysis', json={'device_id': device_id, 'question': '分析设备温度与振动异常'})
            assert 'event: result' in response.text and 'event: error' not in response.text
    finally:
        if storage is not None:
            # Remove only this test's records, retaining all other devices/data.
            with storage.engine.begin() as conn:
                for table in [*storage.shards, storage.inbox, storage.alerts, storage.logs]:
                    conn.execute(table.delete().where(table.c.device_id == device_id))
                session_ids = [row[0] for row in conn.execute(storage.sessions.select().with_only_columns(storage.sessions.c.id).where(storage.sessions.c.device_id == device_id))]
                if session_ids:
                    conn.execute(storage.messages.delete().where(storage.messages.c.session_id.in_(session_ids)))
                conn.execute(storage.sessions.delete().where(storage.sessions.c.device_id == device_id))
                conn.execute(storage.aggregates.delete().where(storage.aggregates.c.device_id == device_id))
                conn.execute(storage.devices.delete().where(storage.devices.c.id == device_id))
            storage.engine.dispose()
        if settings.queue_backend == 'rabbitmq':
            async def remove_test_queue():
                import aio_pika
                connection = await aio_pika.connect_robust(settings.rabbitmq_url, timeout=10)
                async with connection:
                    channel = await connection.channel()
                    await channel.queue_delete(settings.rabbitmq_queue, if_unused=True, if_empty=True)
            asyncio.run(remove_test_queue())


def test_inbox_replay_after_restart(tmp_path):
    from app.schemas import Telemetry

    settings = Settings(_env_file=None, database_url=f'sqlite:///{(tmp_path / "replay.db").as_posix()}',
                        shard_count=96, demo_seed=False, mcp_transport='local')
    storage = Storage(settings)
    storage.initialize()
    storage.register_device({'id': 'P-900', 'name': '重启验证设备', 'kind': 'pump', 'area': '验证区域'})
    telemetry = Telemetry(device_id='P-900', temperature=60, vibration=2, current=20, pressure=.5)
    storage.accept(telemetry)
    storage.mark_event(telemetry.event_id, 'queued')
    storage.engine.dispose()
    with TestClient(create_app(settings)) as client:
        for _ in range(100):
            if client.get(f'/api/events/{telemetry.event_id}').json()['status'] == 'completed':
                break
            time.sleep(.05)
        else:
            pytest.fail('Queued inbox event was not replayed on restart')
        assert client.get('/api/overview').json()['shard_count'] == 96


def test_local_cache_expires():
    cache = Cache(Settings(_env_file=None))

    async def check():
        await cache.put('overview', {'count': 1}, ttl=.02)
        assert await cache.get('overview') == {'count': 1}
        await asyncio.sleep(.03)
        assert await cache.get('overview') is None
    asyncio.run(check())
