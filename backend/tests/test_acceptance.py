"""Additional acceptance tests; all business data and injected failures are isolated."""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.schemas import Telemetry
from app.storage import Storage
from app.tools import Tools


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, database_url=f'sqlite:///{(tmp_path / "acceptance.db").as_posix()}',
                        demo_seed=False, mcp_transport='local', aggregate_interval=3600)
    with TestClient(create_app(settings), raise_server_exceptions=False) as instance:
        for device_id, kind in [('QA-P', 'pump'), ('QA-M', 'motor')]:
            assert instance.post('/api/devices', json={
                'id': device_id, 'name': f'验收设备{device_id}', 'kind': kind, 'area': '验收区域'}).status_code == 201
        yield instance


def sample(**changes):
    return {'event_id': str(uuid4()), 'device_id': 'QA-P',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'temperature': 50, 'vibration': 2, 'current': 20, 'pressure': .5, **changes}


def processed(client, event_id, terminal='completed'):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = client.get(f'/api/events/{event_id}').json()
        if value['status'] == terminal:
            return value
        time.sleep(.05)
    pytest.fail(f'Event did not become {terminal}: {value}')


@pytest.mark.parametrize('changes', [
    {'temperature': -50.01}, {'temperature': 180.01}, {'vibration': -1}, {'vibration': 101},
    {'current': -1}, {'current': 1001}, {'pressure': -1}, {'pressure': 101},
    {'ambient_temperature': -51}, {'ambient_temperature': 101}, {'humidity': -1}, {'humidity': 101},
    {'event_id': ''}, {'event_id': 'x' * 81}, {'event_id': 'invalid/id'},
    {'source': ''}, {'source': 'x' * 81}, {'device_id': 'invalid/id'},
    {'timestamp': '2026-10-15T10:00:00'},
    {'timestamp': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()},
])
def test_reject_invalid_telemetry(client, changes):
    assert client.post('/api/telemetry', json=sample(**changes)).status_code == 422


@pytest.mark.parametrize('changes', [
    {'id': ''}, {'id': 'bad id'}, {'id': 'x' * 33}, {'name': ' ' * 3}, {'name': 'a'},
    {'area': ' ' * 3}, {'kind': 'fan'},
])
def test_reject_invalid_device_registration(client, changes):
    data = {'id': 'QA-NEW', 'name': '验收水泵', 'area': '验收区域', 'kind': 'pump', **changes}
    assert client.post('/api/devices', json=data).status_code == 422


@pytest.mark.parametrize('method,path', [
    ('get', '/api/devices/MISSING'), ('get', '/api/devices/MISSING/telemetry'),
    ('get', '/api/events/MISSING'), ('get', '/api/knowledge/MISSING'),
    ('delete', '/api/knowledge/MISSING'), ('post', '/api/knowledge/MISSING/reindex'),
    ('get', '/api/sessions/MISSING'),
])
def test_missing_resources_return_404(client, method, path):
    assert getattr(client, method)(path).status_code == 404


@pytest.mark.parametrize('hours', [0, -1, 169, 'invalid'])
def test_history_window_validation(client, hours):
    assert client.get('/api/devices/QA-P/telemetry', params={'hours': hours}).status_code == 422


def test_device_duplicate_search_and_simulation_disabled(client):
    duplicate = {'id': 'QA-P', 'name': '重复水泵', 'kind': 'pump', 'area': '验收区域'}
    assert client.post('/api/devices', json=duplicate).status_code == 409
    assert len(client.get('/api/devices', params={'q': 'QA-P'}).json()) == 1
    assert len(client.get('/api/devices', params={'q': '验收设备'}).json()) == 2
    assert client.get('/api/devices', params={'q': "' OR 1=1 --"}).json() == []
    assert client.post('/api/devices/QA-P/simulate').status_code == 403


@pytest.mark.parametrize('temperature,vibration,status', [
    (69.99, 4.49, 'normal'), (70, 2, 'warning'), (50, 4.5, 'warning'),
    (85, 2, 'critical'), (50, 7.1, 'critical'), (-50, 0, 'normal'),
])
def test_status_thresholds_and_environment_storage(client, temperature, vibration, status):
    data = sample(temperature=temperature, vibration=vibration, ambient_temperature=28.4, humidity=67)
    assert client.post('/api/telemetry', json=data).status_code == 202
    processed(client, data['event_id'])
    assert client.get('/api/devices/QA-P').json()['status'] == status
    row = client.get('/api/devices/QA-P/telemetry').json()[-1]
    assert row['ambient_temperature'] == 28.4 and row['humidity'] == 67
    assert 0 <= row['health_score'] <= 100


def test_timezone_normalization_and_order(client):
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    for moment in [recent, recent - timedelta(minutes=1)]:
        data = sample(timestamp=moment.astimezone(timezone(timedelta(hours=8))).isoformat())
        assert client.post('/api/telemetry', json=data).status_code == 202
        processed(client, data['event_id'])
    history = client.get('/api/devices/QA-P/telemetry').json()
    assert [row['timestamp'] for row in history] == sorted(row['timestamp'] for row in history)
    assert datetime.fromisoformat(history[-1]['timestamp']) == recent


def test_overview_cache_invalidation_on_ingest_and_acknowledge(client):
    assert client.get('/api/overview').json()['telemetry_count'] == 0
    assert client.get('/api/overview').json()['cache_hit'] is True
    data = sample(temperature=90, vibration=8)
    client.post('/api/telemetry', json=data)
    processed(client, data['event_id'])
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        overview = client.get('/api/overview').json()
        if overview['telemetry_count'] == 1:
            break
        time.sleep(.02)
    assert overview['telemetry_count'] == 1 and overview['open_alerts'] == 2
    alert = client.get('/api/alerts').json()[0]
    assert client.post(f'/api/alerts/{alert["id"]}/acknowledge').status_code == 200
    assert client.get('/api/overview').json()['open_alerts'] == 1


def test_warning_escalation_reopens_acknowledged_alert_without_duplicates(client):
    for temperature in [72, 90]:
        data = sample(temperature=temperature)
        client.post('/api/telemetry', json=data)
        processed(client, data['event_id'])
        alerts = client.get('/api/alerts').json()
        assert len(alerts) == 1
        if temperature == 72:
            assert client.post(f'/api/alerts/{alerts[0]["id"]}/acknowledge').status_code == 200
    assert alerts[0]['severity'] == 'critical' and alerts[0]['status'] == 'open'
    assert alerts[0]['acknowledged_at'] is None


def test_transient_write_failure_retries_then_commits_once(client, monkeypatch):
    storage = client.app.state.storage
    original = storage.store_batch
    calls = []

    def fail_once(items):
        calls.append(len(items))
        if len(calls) == 1:
            raise RuntimeError('injected transient storage failure')
        return original(items)

    monkeypatch.setattr(storage, 'store_batch', fail_once)
    data = sample()
    client.post('/api/telemetry', json=data)
    result = processed(client, data['event_id'])
    assert result['attempts'] == 1 and len(calls) == 2
    assert len(client.get('/api/devices/QA-P/telemetry').json()) == 1


def test_permanent_write_failure_stops_after_three_attempts(client, monkeypatch):
    def fail(items):
        raise RuntimeError('injected permanent storage failure')

    monkeypatch.setattr(client.app.state.storage, 'store_batch', fail)
    data = sample()
    client.post('/api/telemetry', json=data)
    result = processed(client, data['event_id'], 'failed')
    time.sleep(.4)
    assert result['attempts'] == 3
    assert client.get(f'/api/events/{data["event_id"]}').json()['attempts'] == 3
    assert client.get('/api/devices/QA-P/telemetry').json() == []


def test_batch_transaction_rolls_back_on_invalid_second_item(tmp_path):
    # No running dispatcher may consume the pending event during this transaction check.
    storage = Storage(Settings(_env_file=None, database_url=f'sqlite:///{(tmp_path / "rollback.db").as_posix()}'))
    try:
        storage.initialize()
        storage.register_device({'id': 'QA-P', 'name': '事务验收设备', 'kind': 'pump', 'area': '验收区域'})
        first, second = Telemetry(**sample()), Telemetry(**sample(device_id='MISSING'))
        storage.accept(first)
        with pytest.raises(Exception):
            storage.store_batch([first, second])
        assert storage.history('QA-P') == []
        assert storage.event_status(first.event_id)['status'] == 'pending'
    finally:
        storage.engine.dispose()


def test_hourly_aggregate_counts_and_averages_are_idempotent(client):
    storage = client.app.state.storage
    stamp = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    for index, temperature in enumerate([40, 60]):
        data = sample(timestamp=(stamp + timedelta(minutes=index)).isoformat(), temperature=temperature)
        client.post('/api/telemetry', json=data)
        processed(client, data['event_id'])
    storage.aggregate()
    storage.aggregate()
    rows = storage.rows(select(storage.aggregates))
    assert len(rows) == 1 and rows[0]['samples'] == 2 and rows[0]['temperature'] == 50


def test_document_index_failure_preserves_original_and_can_be_retried(client, monkeypatch):
    knowledge = client.app.state.knowledge
    original = knowledge.index

    async def fail(document_id):
        raise RuntimeError('injected embedding outage')

    monkeypatch.setattr(knowledge, 'index', fail)
    content = '轴承维护手册要求记录润滑状态以及温度振动变化，并核查设备编号和现场时间。'
    assert client.post('/api/knowledge', json={'title': '故障恢复手册', 'content': content}).status_code == 502
    doc = client.get('/api/knowledge').json()[0]
    assert doc['index_status'] == 'failed'
    assert client.get(f'/api/knowledge/{doc["id"]}').json()['content'] == content
    monkeypatch.setattr(knowledge, 'index', original)
    assert client.post(f'/api/knowledge/{doc["id"]}/reindex').status_code == 200
    assert client.get('/api/knowledge').json()[0]['index_status'] == 'local'
    assert client.get('/api/knowledge/search', params={'q': '润滑状态'}).json()
    assert client.delete(f'/api/knowledge/{doc["id"]}').status_code == 200
    storage = client.app.state.storage
    with storage.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(storage.chunks)) == 0


@pytest.mark.parametrize('query', ['', 'a', 'x' * 2001])
def test_knowledge_query_length_validation(client, query):
    assert client.get('/api/knowledge/search', params={'q': query}).status_code == 422


def test_knowledge_service_errors_are_explicit(client, monkeypatch):
    async def fail(query):
        raise RuntimeError('injected search outage')

    monkeypatch.setattr(client.app.state.knowledge, 'search', fail)
    assert client.get('/api/knowledge/search', params={'q': '轴承润滑'}).status_code == 502


def test_analysis_rejects_missing_session_and_capacity_exhaustion(client):
    data = {'device_id': 'QA-P', 'question': '分析设备状态'}
    assert client.post('/api/analysis', json={**data, 'session_id': str(uuid4())}).status_code == 404

    async def occupy():
        await client.app.state.analysis_slots.acquire()
        await client.app.state.analysis_slots.acquire()

    client.portal.call(occupy)
    try:
        assert client.post('/api/analysis', json=data).status_code == 429
        assert client.get('/api/sessions').json() == []
    finally:
        client.portal.call(client.app.state.analysis_slots.release)
        client.portal.call(client.app.state.analysis_slots.release)


def test_no_sample_analysis_reports_evidence_gap_and_persists_across_restart(client):
    response = client.post('/api/analysis', json={'device_id': 'QA-P', 'question': '分析没有采样的新设备'})
    assert response.status_code == 200 and '尚未收到该设备的采样数据' in response.text
    sessions = client.get('/api/sessions').json()
    settings = client.app.state.storage.settings
    with TestClient(create_app(settings)) as restarted:
        messages = restarted.get(f'/api/sessions/{sessions[0]["id"]}').json()['messages']
        assert [message['role'] for message in messages] == ['user', 'assistant']
        assert len(messages[1]['evidence']) == 4


def test_tools_reject_unknown_tool_and_other_device(client):
    storage = client.app.state.storage
    tools = Tools(storage, client.app.state.knowledge)

    async def check():
        with pytest.raises(ValueError, match='允许列表'):
            await tools.call('execute_sql', {'sql': 'DROP TABLE devices'}, 'QA-P')
        with pytest.raises(ValueError, match='所选设备'):
            await tools.call('query_logs', {'device_id': 'QA-M'}, 'QA-P')

    asyncio.run(check())


def test_cors_allows_frontend_and_rejects_unknown_origin(client):
    for origin, allowed in [('http://127.0.0.1:5173', True), ('https://invalid.example', False)]:
        response = client.options('/api/telemetry', headers={
            'Origin': origin, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'Content-Type'})
        assert response.status_code == (200 if allowed else 400)
        assert ('access-control-allow-origin' in response.headers) is allowed


def test_repeated_event_without_explicit_timestamp_is_idempotent(client):
    """A gateway retry of an identical JSON body must not become a different event."""
    data = sample()
    del data['timestamp']
    assert client.post('/api/telemetry', json=data).status_code == 202
    table = client.app.state.storage.inbox
    original = client.app.state.storage.rows(select(table.c.payload).where(table.c.event_id == data['event_id']))[0]['payload']
    second = client.post('/api/telemetry', json=data)
    assert second.status_code == 202, second.text
    assert second.json()['accepted'] is False
    processed(client, data['event_id'])
    history = client.get('/api/devices/QA-P/telemetry').json()
    assert len(history) == 1
    assert datetime.fromisoformat(history[0]['timestamp']) == datetime.fromisoformat(original['timestamp'])


@pytest.mark.parametrize('explicit_timestamp', [False, True])
@pytest.mark.parametrize('changes', [
    {'temperature': 51}, {'vibration': 3}, {'current': 21}, {'pressure': .6},
    {'source': 'other-gateway'}, {'humidity': 60}, {'ambient_temperature': 25},
    {'device_id': 'QA-M'}, {'timestamp': '2026-01-01T00:00:00Z'},
])
def test_retry_still_rejects_changed_data(client, explicit_timestamp, changes):
    data = sample()
    if not explicit_timestamp:
        del data['timestamp']
    assert client.post('/api/telemetry', json=data).status_code == 202
    assert client.post('/api/telemetry', json={**data, **changes}).status_code == 409


def test_explicit_retry_accepts_equivalent_timezone_but_rejects_changed_time(client):
    data = sample()
    assert client.post('/api/telemetry', json=data).status_code == 202
    stamp = datetime.fromisoformat(data['timestamp'])
    same_time = stamp.astimezone(timezone(timedelta(hours=8))).isoformat()
    response = client.post('/api/telemetry', json={**data, 'timestamp': same_time})
    assert response.status_code == 202 and response.json()['accepted'] is False
    changed = (stamp - timedelta(seconds=1)).isoformat()
    assert client.post('/api/telemetry', json={**data, 'timestamp': changed}).status_code == 409


def test_concurrent_retries_without_timestamp_only_accept_once(client):
    data = sample()
    del data['timestamp']
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post('/api/telemetry', json=data), range(16)))
    assert all(response.status_code == 202 for response in responses)
    assert sum(response.json()['accepted'] for response in responses) == 1
    processed(client, data['event_id'])
    assert len(client.get('/api/devices/QA-P/telemetry').json()) == 1


def test_whitespace_only_question_is_rejected(client):
    response = client.post('/api/analysis', json={'device_id': 'QA-P', 'question': '   '})
    assert response.status_code == 422, response.text[:300]


def test_whitespace_only_log_message_is_rejected(client):
    response = client.post('/api/logs', json={'device_id': 'QA-P', 'message': '   '})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('text', ['\t\r\n', '\u3000\u00a0', ' x ', '\u3000字\u3000'])
@pytest.mark.parametrize('path,field', [('/api/analysis', 'question'), ('/api/logs', 'message')])
def test_reject_text_without_two_effective_characters(client, path, field, text):
    response = client.post(path, json={'device_id': 'QA-P', field: text})
    assert response.status_code == 422
    assert client.get('/api/sessions').json() == []
    assert client.app.state.storage.device_logs('QA-P') == []


def test_valid_question_and_log_are_trimmed_before_persistence(client):
    assert client.post('/api/logs', json={'device_id': 'QA-P', 'message': ' \t巡检完成\n '}).status_code == 201
    assert client.app.state.storage.device_logs('QA-P')[0]['message'] == '巡检完成'
    response = client.post('/api/analysis', json={'device_id': 'QA-P', 'question': ' \t检查设备状态\n '})
    assert 'event: result' in response.text
    session = client.get('/api/sessions').json()[0]
    assert session['title'] == '检查设备状态'
    assert client.get(f'/api/sessions/{session["id"]}').json()['messages'][0]['content'] == '检查设备状态'


@pytest.mark.parametrize('trust_env', [False, True])
def test_ark_http_policy_real_sdk_and_client_lifecycle(tmp_path, monkeypatch, trust_env):
    """Exercise real LangChain/OpenAI serialization with a controlled HTTP transport."""
    clients, options, requests = [], [], []
    actual_client = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Bearer test-only'
        assert request.url.path == '/api/v3/chat/completions'
        body = json.loads(request.content)
        if not body.get('stream'):
            return httpx.Response(200, json={
                'id': 'chatcmpl-plan', 'object': 'chat.completion', 'created': 1, 'model': 'test-model',
                'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                    'role': 'assistant', 'content': None, 'tool_calls': [{
                        'id': 'plan-1', 'type': 'function', 'function': {
                            'name': 'Plan', 'arguments': json.dumps({'steps': ['query_metrics']})}}]}}]})
        chunk = {'id': 'chatcmpl-report', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'test-model',
                 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': '根据设备证据，建议人工核查。'}, 'finish_reason': None}]}
        body = f'data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body, headers={'Content-Type': 'text/event-stream'})

    def create_http_client(**kwargs):
        options.append(kwargs)
        instance = actual_client(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(instance)
        return instance

    monkeypatch.setattr('app.main.httpx', SimpleNamespace(AsyncClient=create_http_client))
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    monkeypatch.delenv('NO_PROXY', raising=False)
    settings = Settings(_env_file=None, database_url=f'sqlite:///{(tmp_path / "ark-http.db").as_posix()}',
                        demo_seed=False, llm_mode='ark', ark_api_key='test-only', ark_model='test-model',
                        ark_trust_env=trust_env, mcp_transport='local')
    with TestClient(create_app(settings)) as instance:
        instance.post('/api/devices', json={'id': 'QA-P', 'name': '模型验收设备', 'kind': 'pump', 'area': '验收区域'})
        response = instance.post('/api/analysis', json={'device_id': 'QA-P', 'question': '分析设备状态'})
        assert 'event: result' in response.text and 'event: error' not in response.text
        assert '根据设备证据，建议人工核查。' in response.text
        assert instance.app.state.model_http is clients[0]
        assert not clients[0].is_closed
    assert len(clients) == 1 and clients[0].is_closed
    assert options[0]['trust_env'] is trust_env
    assert len(requests) == 2


def test_ark_connections_default_to_direct_access():
    assert Settings(_env_file=None).ark_trust_env is False
