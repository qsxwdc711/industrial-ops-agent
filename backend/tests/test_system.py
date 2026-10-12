import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from pydantic import SecretStr
from sqlalchemy import func, select

from app.agents import Plan
from app.config import Settings
from app.knowledge import Knowledge, chunk_text
from app.main import create_app
from app.storage import Storage
from app.tools import Tools


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    filename = tmp_path_factory.mktemp('industrial') / 'test.db'
    app = create_app(Settings(_env_file=None, database_url=f'sqlite:///{filename.as_posix()}',
        shard_count=16, mcp_transport='local', aggregate_interval=3600))
    with TestClient(app) as test_client:
        yield test_client


def wait_processed(client, event_id):
    for _ in range(100):
        status = client.get(f'/api/events/{event_id}').json()
        if status['status'] == 'completed':
            return
        assert status['status'] != 'failed', status
        time.sleep(.05)
    pytest.fail('The persisted telemetry event was not processed')


def stream_events(response):
    return [(block.splitlines()[0].removeprefix('event: '),
             json.loads(block.splitlines()[1].removeprefix('data: ')))
            for block in response.text.strip().split('\n\n')]


def test_health_and_actual_seed_counts(client):
    health = client.get('/api/health').json()
    overview = client.get('/api/overview').json()
    assert health['llm_mode'] == 'demo'
    assert health['demo_data'] is True
    assert 'api_key' not in json.dumps(health).lower()
    assert overview['total_devices'] == 12
    assert overview['telemetry_count'] == 12 * 96
    assert len(overview['trend']) >= 23


def test_persistent_ingestion_deduplicates_and_rejects_conflicting_id(client):
    storage = client.app.state.storage
    table = storage.shards[storage.shard_number('P-102')]
    with storage.engine.connect() as conn:
        before = conn.scalar(select(func.count()).select_from(table))
    payload = {'event_id': 'test-idempotence', 'device_id': 'P-102',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'temperature': 91.5, 'vibration': 8.1, 'current': 22, 'pressure': .55}
    first = client.post('/api/telemetry', json=payload)
    assert first.status_code == 202 and first.json()['accepted']
    assert client.post('/api/telemetry', json=payload).json()['accepted'] is False
    wait_processed(client, payload['event_id'])
    with storage.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(table)) == before + 1
    assert client.get('/api/devices/P-102').json()['status'] == 'critical'
    assert any(alert['device_id'] == 'P-102' for alert in client.get('/api/alerts').json())
    assert client.post('/api/telemetry', json={**payload, 'temperature': 50}).status_code == 409


def test_late_samples_do_not_replace_latest_device_state(client):
    before = client.get('/api/devices/P-102').json()
    payload = {'event_id': 'test-delayed', 'device_id': 'P-102',
        'timestamp': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        'temperature': 40, 'vibration': 1, 'current': 15, 'pressure': .5}
    client.post('/api/telemetry', json=payload)
    wait_processed(client, payload['event_id'])
    assert client.get('/api/devices/P-102').json()['temperature'] == before['temperature']


def test_input_validation_and_unknown_device(client):
    payload = {'device_id': 'unknown', 'temperature': 50, 'vibration': 1, 'current': 15, 'pressure': .5}
    assert client.post('/api/telemetry', json=payload).status_code == 404
    assert client.post('/api/telemetry', json={**payload, 'device_id': 'P-101', 'timestamp': '2026-10-11T12:00:00'}).status_code == 422
    assert client.get('/api/devices/P-101/telemetry?hours=9999').status_code == 422


def test_register_device_then_ingest_first_sample_and_log(client):
    registered = client.post('/api/devices', json={'id': 'P-999', 'name': '新接入水泵', 'kind': 'pump', 'area': '测试区域'})
    assert registered.status_code == 201 and registered.json()['status'] == 'offline'
    assert registered.json()['temperature'] is None
    assert client.post('/api/logs', json={'device_id': 'P-999', 'message': '设备完成现场安装'}).status_code == 201
    response = client.post('/api/telemetry', json={'device_id': 'P-999', 'temperature': 52,
        'vibration': 1.8, 'current': 20, 'pressure': .6})
    wait_processed(client, response.json()['event_id'])
    assert client.get('/api/devices/P-999').json()['status'] == 'normal'


def test_acknowledge_is_separate_from_device_health(client):
    alert = next(item for item in client.get('/api/alerts').json() if item['status'] == 'open')
    original = client.get(f'/api/devices/{alert["device_id"]}').json()['status']
    assert client.post(f'/api/alerts/{alert["id"]}/acknowledge').status_code == 200
    assert client.post(f'/api/alerts/{alert["id"]}/acknowledge').status_code == 409
    assert client.get(f'/api/devices/{alert["device_id"]}').json()['status'] == original


def test_document_import_search_citation_and_delete(client):
    content = '专用密封泄漏检查：对比密封处漏液记录，检查密封面磨损以及冲洗管路堵塞。\n\n保留维修日期与现场记录。'
    response = client.post('/api/knowledge', json={'title': '密封泄漏检查规程', 'category': 'procedure', 'content': content})
    assert response.status_code == 201
    doc = response.json()
    results = client.get('/api/knowledge/search', params={'q': '密封泄漏冲洗管路堵塞'}).json()
    hit = next(item for item in results if item['document_id'] == doc['id'])
    assert hit['text'] in content and hit['position'] == 0 and hit['retrieval'] == 'keyword'
    assert client.get('/api/knowledge/search', params={'q': '量子纠缠星际航行'}).json() == []
    assert client.delete(f'/api/knowledge/{doc["id"]}').status_code == 200
    assert client.get(f'/api/knowledge/{doc["id"]}').status_code == 404


def test_long_document_chunking_preserves_tail():
    text = '轴承润滑检查。' * 500 + '最后一段唯一标记'
    chunks = chunk_text(text)
    assert len(chunks) > 1 and all(len(chunk) <= 700 for chunk in chunks)
    assert '最后一段唯一标记' in chunks[-1]


def test_blank_document_is_rejected_before_indexing(client):
    response = client.post('/api/knowledge', json={'title': '空白文档', 'content': ' ' * 30})
    assert response.status_code == 422


def test_long_session_returns_recent_context(client):
    storage = client.app.state.storage
    session = storage.create_session('P-101', '长会话测试')
    for index in range(120):
        storage.save_message(session, 'user', f'问题-{index}')
    messages = storage.session_messages(session)
    assert len(messages) == 100
    assert messages[0]['content'] == '问题-20' and messages[-1]['content'] == '问题-119'


def test_existing_shard_count_cannot_be_changed(client):
    settings = client.app.state.storage.settings.model_copy(update={'shard_count': 17})
    changed = Storage(settings)
    try:
        with pytest.raises(ValueError, match='SHARD_COUNT'):
            changed.initialize()
    finally:
        changed.engine.dispose()


def test_demo_graph_stream_and_followup_context(client):
    first = client.post('/api/analysis', json={'device_id': 'P-101', 'question': '分析水泵温度与振动异常'})
    assert first.status_code == 200
    events = stream_events(first)
    result = next(data for event, data in events if event == 'result')
    assert result['mode'] == 'demo' and '未调用大语言模型' in result['report']
    assert {item['tool'] for item in result['evidence']} == {'query_metrics', 'query_alerts', 'query_logs', 'search_knowledge'}
    assert len([event for event, _ in events if event == 'step']) == 5
    second = client.post('/api/analysis', json={'device_id': 'P-101', 'question': '继续整理人工检查建议', 'session_id': result['session_id']})
    assert any(event == 'result' for event, _ in stream_events(second))
    detail = client.get(f'/api/sessions/{result["session_id"]}').json()
    assert [message['role'] for message in detail['messages']] == ['user', 'assistant', 'user', 'assistant']
    assert client.post('/api/analysis', json={'device_id': 'P-102', 'question': '切换设备分析', 'session_id': result['session_id']}).status_code == 409


def test_mcp_stdio_returns_real_database_evidence(client):
    storage = client.app.state.storage
    settings = storage.settings.model_copy(update={'mcp_transport': 'stdio'})
    mcp_storage = Storage(settings)

    async def run():
        async with Tools(mcp_storage, Knowledge(mcp_storage)).connected() as tools:
            result = await tools.call('query_metrics', {'device_id': 'P-101'}, 'P-101')
            assert result['device']['id'] == 'P-101'
            assert result['summary']['samples'] > 0
            with pytest.raises(ValueError, match='所选设备'):
                await tools.call('query_logs', {'device_id': 'P-102'}, 'P-101')
    try:
        asyncio.run(run())
    finally:
        mcp_storage.engine.dispose()


def test_missing_ark_configuration_fails_explicitly(client):
    config = client.app.state.storage.settings.model_copy(update={'llm_mode': 'ark'})
    with TestClient(create_app(config)) as other:
        response = other.post('/api/analysis', json={'device_id': 'P-101', 'question': '分析运行状态'})
        assert response.status_code == 503


def test_real_model_workflow_executes_tool_calls_using_test_double(client, monkeypatch):
    instances = []

    class FakeArk:
        def __init__(self, **kwargs):
            self.calls = 0
            instances.append(self)

        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            return Plan(steps=['query_metrics', 'search_knowledge'])

        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            self.calls += 1
            if self.calls == 1:
                yield AIMessageChunk(content='', tool_call_chunks=[{
                    'name': 'query_logs', 'args': '{"device_id":"P-101"}', 'id': 'call-1', 'index': 0}])
            else:
                assert messages[-1].type == 'tool'
                yield AIMessageChunk(content='依据设备指标与日志，建议核查轴承润滑。')

    monkeypatch.setattr('app.agents.ChatOpenAI', FakeArk)
    config = client.app.state.storage.settings.model_copy(update={'llm_mode': 'ark', 'ark_model': 'test-model', 'ark_api_key': SecretStr('test-key')})
    with TestClient(create_app(config)) as other:
        result = next(data for event, data in stream_events(other.post('/api/analysis', json={
            'device_id': 'P-101', 'question': '分析温度与振动'})) if event == 'result')
        assert result['mode'] == 'ark'
        assert any(item['tool'] == 'query_logs' for item in result['evidence'])
        assert instances[0].calls == 2


def test_tool_failure_has_error_event_and_no_fake_success(client, monkeypatch):
    async def fail(*args, **kwargs):
        raise ValueError('test tool disconnected')
    monkeypatch.setattr(Tools, 'call', fail)
    events = stream_events(client.post('/api/analysis', json={'device_id': 'P-101', 'question': '分析设备指标'}))
    assert any(event == 'error' for event, _ in events)
    assert not any(event == 'result' for event, _ in events)
