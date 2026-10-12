"""Small async adapter for Milvus's official v2 REST API."""
import asyncio

import httpx


class MilvusClient:
    def __init__(self, uri: str, token: str = ''):
        self.http = httpx.AsyncClient(base_url=uri.rstrip('/'), timeout=60, trust_env=False,
            headers={'Authorization': 'Bearer ' + token} if token else {})

    async def call(self, path: str, body: dict):
        response = await self.http.post('/v2/vectordb/' + path, json=body)
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 0:
            raise ValueError(f'Milvus {path} 失败，错误码 {result.get("code")}')
        return result.get('data', {})

    async def has_collection(self, name: str) -> bool:
        return (await self.call('collections/has', {'collectionName': name}))['has']

    async def create_collection(self, collection_name: str, dimension: int):
        await self.call('collections/create', {
            'collectionName': collection_name,
            'schema': {'autoId': False, 'enableDynamicField': True, 'fields': [
                {'fieldName': 'id', 'dataType': 'VarChar', 'isPrimary': True,
                 'elementTypeParams': {'max_length': '80'}},
                {'fieldName': 'vector', 'dataType': 'FloatVector', 'elementTypeParams': {'dim': str(dimension)}},
                {'fieldName': 'document_id', 'dataType': 'VarChar', 'elementTypeParams': {'max_length': '36'}},
                {'fieldName': 'title', 'dataType': 'VarChar', 'elementTypeParams': {'max_length': '1024'}},
                {'fieldName': 'text', 'dataType': 'VarChar', 'elementTypeParams': {'max_length': '4096'}},
                {'fieldName': 'position', 'dataType': 'Int64'},
            ]},
            'indexParams': [{'fieldName': 'vector', 'indexName': 'vector', 'metricType': 'COSINE',
                             'params': {'index_type': 'AUTOINDEX'}}],
            'params': {'consistencyLevel': 'Strong'},
        })

    async def dimension(self, name: str) -> int:
        data = await self.call('collections/describe', {'collectionName': name})
        field = next(item for item in data['fields'] if item['name'] == 'vector')
        params = field['params']
        if isinstance(params, list):
            params = {item['key']: item['value'] for item in params}
        return int(params['dim'])

    async def ensure_loaded(self, name: str):
        await self.call('collections/load', {'collectionName': name})
        async with asyncio.timeout(60):
            while True:
                state = await self.call('collections/describe', {'collectionName': name})
                if state['load'] == 'LoadStateLoaded':
                    return
                await asyncio.sleep(.5)

    async def upsert(self, collection_name: str, data: list[dict]):
        return await self.call('entities/upsert', {'collectionName': collection_name, 'data': data})

    async def search(self, collection_name: str, data: list, limit: int, output_fields: list[str], filter: str):
        rows = await self.call('entities/search', {'collectionName': collection_name, 'data': data,
            'annsField': 'vector', 'limit': limit, 'outputFields': output_fields, 'filter': filter})
        return [{'id': str(row['id']), 'distance': row['distance'],
                 'entity': {key: row[key] for key in output_fields}} for row in rows]

    async def delete(self, collection_name: str, filter: str):
        return await self.call('entities/delete', {'collectionName': collection_name, 'filter': filter})

    async def close(self):
        await self.http.aclose()
