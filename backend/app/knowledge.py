import asyncio
import json
import re
from uuid import uuid4

import httpx
from sqlalchemy import select

from .schemas import DocumentInput
from .milvus import MilvusClient
from .storage import Storage


def chunk_text(content: str, size: int = 700, overlap: int = 100) -> list[str]:
    content = content.strip().replace('\r\n', '\n')
    chunks, current = [], ''
    for paragraph in re.split(r'\n\s*\n', content):
        if not paragraph.strip():
            continue
        if current and len(current) + len(paragraph) > size:
            chunks.append(current)
            current = current[-overlap:]
        current = (current + '\n\n' + paragraph).strip()
        while len(current) > size:
            chunks.append(current[:size])
            current = current[size - overlap:]
    if current:
        chunks.append(current)
    return chunks


def tokens(text: str) -> set[str]:
    normalized = ''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+', text.lower()))
    return {normalized[i:i + 2] for i in range(len(normalized) - 1)}


class Knowledge:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.settings = storage.settings
        self.client = None

    async def start(self):
        if self.settings.knowledge_backend == 'milvus':
            if not self.settings.ark_api_key.get_secret_value() or not self.settings.ark_embedding_model:
                raise ValueError('Milvus 模式需要配置 ARK_API_KEY 和 ARK_EMBEDDING_MODEL')
            self.client = MilvusClient(self.settings.milvus_uri, self.settings.milvus_token.get_secret_value())
            name = self.settings.milvus_collection
            if not await self.client.has_collection(name):
                await self.client.create_collection(name, self.settings.embedding_dimension)
            if await self.client.dimension(name) != self.settings.embedding_dimension:
                raise ValueError('Milvus 集合向量维度与 EMBEDDING_DIMENSION 不一致')
            await self.client.ensure_loaded(name)
            # Existing local documents are reindexed when switching to Milvus.
            for doc in await asyncio.to_thread(self.storage.rows, select(self.storage.documents)):
                await self.index(doc['id'])

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        api = self.settings.ark_embedding_api
        multimodal = api == 'multimodal' or (
            api == 'auto' and self.settings.ark_embedding_model.startswith('doubao-embedding-vision'))
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            async def request(endpoint, payload):
                response = await client.post(self.settings.ark_base_url.rstrip('/') + endpoint,
                    headers={'Authorization': 'Bearer ' + self.settings.ark_api_key.get_secret_value()},
                    json={'model': self.settings.ark_embedding_model, 'encoding_format': 'float', **payload})
                if response.is_error:
                    raise ValueError(f'嵌入模型调用失败（HTTP {response.status_code}），请检查模型权限与配置')
                return response.json()['data']

            if multimodal:
                # Multimodal input items form ONE vector, so each chunk needs its own request.
                semaphore = asyncio.Semaphore(4)

                async def embed_text(text):
                    async with semaphore:
                        data = await request('/embeddings/multimodal', {
                            'input': [{'type': 'text', 'text': text}],
                            'dimensions': self.settings.embedding_dimension})
                        return data['embedding']

                vectors = await asyncio.gather(*(embed_text(text) for text in texts))
            else:
                data = await request('/embeddings', {'input': texts})
                vectors = [item['embedding'] for item in sorted(data, key=lambda item: item['index'])]
            if len(vectors) != len(texts) or any(len(v) != self.settings.embedding_dimension for v in vectors):
                raise ValueError('嵌入模型返回数量或向量维度不匹配')
            return vectors

    async def add(self, item: DocumentInput) -> dict:
        document_id = str(uuid4())
        chunks = chunk_text(item.content)
        await asyncio.to_thread(self.storage.save_document, document_id, item.title, item.category, item.content, chunks)
        try:
            await self.index(document_id)
        except Exception:
            await asyncio.to_thread(self.storage.set_index_status, document_id, 'failed')
            raise
        return {'id': document_id, 'title': item.title, 'chunks': len(chunks),
                'index_status': self.settings.knowledge_backend}

    async def index(self, document_id: str):
        rows = await asyncio.to_thread(self.storage.rows, select(self.storage.chunks).where(
            self.storage.chunks.c.document_id == document_id).order_by(self.storage.chunks.c.position))
        if self.client:
            for start in range(0, len(rows), 16):
                batch = rows[start:start + 16]
                vectors = await self.embeddings([row['text'] for row in batch])
                await self.client.upsert(collection_name=self.settings.milvus_collection,
                    data=[{**row, 'vector': vector} for row, vector in zip(batch, vectors, strict=True)])
        await asyncio.to_thread(self.storage.set_index_status, document_id, self.settings.knowledge_backend)

    async def search(self, query: str, limit: int = 4) -> list[dict]:
        if self.client:
            documents = await asyncio.to_thread(self.storage.rows, select(self.storage.documents.c.id).where(
                self.storage.documents.c.index_status == 'milvus'))
            if not documents:
                return []
            vector = (await self.embeddings([query]))[0]
            results = await self.client.search(
                collection_name=self.settings.milvus_collection, data=[vector], limit=limit,
                output_fields=['document_id', 'title', 'text', 'position'],
                filter='document_id in ' + json.dumps([doc['id'] for doc in documents]))
            return [{**hit['entity'], 'id': str(hit['id']), 'score': round(hit['distance'], 4),
                     'retrieval': 'milvus'} for hit in results if hit['distance'] >= 0.25]
        query_tokens = tokens(query)
        rows = await asyncio.to_thread(self.storage.rows, select(self.storage.chunks).join(
            self.storage.documents, self.storage.documents.c.id == self.storage.chunks.c.document_id
        ).where(self.storage.documents.c.index_status == 'local'))
        scored = []
        for row in rows:
            matched = len(query_tokens & tokens(row['title'] + row['text']))
            score = matched / max(1, len(query_tokens))
            if matched >= 2 and score >= 0.04:
                scored.append({**row, 'score': round(score, 4), 'retrieval': 'keyword'})
        return sorted(scored, key=lambda item: item['score'], reverse=True)[:limit]

    async def delete(self, document_id: str):
        if self.client:
            await self.client.delete(collection_name=self.settings.milvus_collection,
                                    filter=f'document_id == "{document_id}"')
        return await asyncio.to_thread(self.storage.delete_document, document_id)

    async def close(self):
        if self.client:
            await self.client.close()
