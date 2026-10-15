import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.knowledge import Knowledge
from app.schemas import DocumentInput
from app.storage import Storage


@pytest.mark.skipif(os.getenv('RUN_MILVUS_TESTS') != '1', reason='Opt-in real Milvus test, synthetic test vectors')
def test_real_milvus_index_search_citation_delete(tmp_path, monkeypatch):
    name = 'industrial_test_' + uuid4().hex[:12]
    settings = Settings(_env_file=None,
        database_url=f'sqlite:///{(tmp_path / "vector.db").as_posix()}', demo_seed=False,
        knowledge_backend='milvus', milvus_uri='http://localhost:19531', milvus_collection=name,
        embedding_dimension=8, ark_api_key=SecretStr('test-only'), ark_embedding_model='test-only')
    storage = Storage(settings)
    storage.initialize()
    knowledge = Knowledge(storage)

    async def synthetic_vectors(self, texts):
        # Validate real Milvus IO with controlled vectors, without billing an external model.
        return [[1.0] + [0.0] * 7 for _ in texts]

    monkeypatch.setattr(Knowledge, 'embeddings', synthetic_vectors)

    async def run():
        try:
            await knowledge.start()
            document = await knowledge.add(DocumentInput(title='测试轴承润滑手册', category='manual',
                content='轴承温度与振动同步上升时，需要核查润滑状态、轴系对中以及基础紧固情况。记录测点和采集时间。'))
            hits = await knowledge.search('轴承润滑检查')
            assert hits and hits[0]['document_id'] == document['id']
            assert hits[0]['title'] == '测试轴承润滑手册' and hits[0]['retrieval'] == 'milvus'
            assert hits[0]['position'] == 0 and hits[0]['score'] > .99
            await knowledge.delete(document['id'])
            assert await knowledge.search('轴承润滑检查') == []
            other = Knowledge(Storage(settings.model_copy(update={'embedding_dimension': 16})))
            try:
                with pytest.raises(ValueError, match='向量维度'):
                    await other.start()
            finally:
                await other.close()
                other.storage.engine.dispose()
        finally:
            if knowledge.client:
                await knowledge.client.call('collections/drop', {'collectionName': name})
            await knowledge.close()
    try:
        asyncio.run(run())
    finally:
        storage.engine.dispose()


@pytest.mark.parametrize('model,api', [
    ('doubao-embedding-vision-250615', 'auto'), ('ep-test-endpoint', 'multimodal')])
def test_multimodal_chunks_are_embedded_separately(tmp_path, monkeypatch, model, api):
    settings = Settings(_env_file=None,
        database_url=f'sqlite:///{(tmp_path / "multimodal.db").as_posix()}',
        ark_api_key=SecretStr('test-only'), ark_embedding_model=model,
        ark_embedding_api=api, embedding_dimension=1024)
    storage = Storage(settings)
    knowledge = Knowledge(storage)
    actual_client = httpx.AsyncClient
    inputs = []

    def handler(request):
        import json
        payload = json.loads(request.content)
        assert request.url.path == '/api/v3/embeddings/multimodal'
        assert payload['dimensions'] == 1024
        assert len(payload['input']) == 1 and payload['input'][0]['type'] == 'text'
        text = payload['input'][0]['text']
        inputs.append(text)
        value = 1.0 if text == '轴承检查' else 2.0
        return httpx.Response(200, json={'data': {'embedding': [value] * 1024}})

    monkeypatch.setattr('app.knowledge.httpx.AsyncClient',
                        lambda **kwargs: actual_client(transport=httpx.MockTransport(handler), **kwargs))

    async def run():
        vectors = await knowledge.embeddings(['轴承检查', '电机温升'])
        assert [vector[0] for vector in vectors] == [1.0, 2.0]
        assert sorted(inputs) == sorted(['轴承检查', '电机温升'])
        assert await knowledge.embeddings([]) == []

    try:
        asyncio.run(run())
    finally:
        storage.engine.dispose()


@pytest.mark.parametrize('trust_env', [False, True])
def test_embedding_http_contract_and_dimension_check(tmp_path, monkeypatch, trust_env):
    settings = Settings(_env_file=None,
        database_url=f'sqlite:///{(tmp_path / "embedding.db").as_posix()}',
        ark_api_key=SecretStr('test-only'), ark_embedding_model='embedding-test', embedding_dimension=8,
        ark_trust_env=trust_env)
    storage = Storage(settings)
    knowledge = Knowledge(storage)
    actual_client = httpx.AsyncClient

    def handler(request):
        import json
        payload = json.loads(request.content)
        assert request.url.path == '/api/v3/embeddings'
        assert request.headers['Authorization'] == 'Bearer test-only'
        assert payload['model'] == 'embedding-test'
        return httpx.Response(200, json={'data': [{'index': i, 'embedding': [1.0] * 8}
                                              for i, _ in enumerate(payload['input'])]})

    def mock_client(**kwargs):
        assert kwargs['trust_env'] is trust_env
        return actual_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr('app.knowledge.httpx.AsyncClient', mock_client)

    async def run():
        assert len(await knowledge.embeddings(['轴承检查', '电机温升'])) == 2
        knowledge.settings.embedding_dimension = 16
        with pytest.raises(ValueError, match='维度不匹配'):
            await knowledge.embeddings(['轴承检查'])
    try:
        asyncio.run(run())
    finally:
        storage.engine.dispose()
