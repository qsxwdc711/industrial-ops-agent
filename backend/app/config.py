from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND.parent / '.env', BACKEND / '.env'),
        env_file_encoding='utf-8', extra='ignore',
    )
    database_url: str = f'sqlite:///{(BACKEND / "data/industrial.db").as_posix()}'
    shard_count: int = Field(default=16, ge=1, le=128)
    demo_seed: bool = True
    queue_backend: Literal['local', 'rabbitmq'] = 'local'
    rabbitmq_url: str = 'amqp://industrial:industrial@localhost:5672/'
    rabbitmq_queue: str = Field(default='industrial.telemetry', min_length=1, max_length=200)
    cache_backend: Literal['memory', 'redis'] = 'memory'
    redis_url: str = 'redis://localhost:6379/0'
    llm_mode: Literal['demo', 'ark'] = 'demo'
    ark_api_key: SecretStr = SecretStr('')
    ark_model: str = ''
    ark_base_url: str = 'https://ark.cn-beijing.volces.com/api/v3'
    ark_embedding_model: str = ''
    ark_embedding_api: Literal['auto', 'text', 'multimodal'] = 'auto'
    embedding_dimension: int = Field(default=1024, ge=8, le=8192)
    knowledge_backend: Literal['local', 'milvus'] = 'local'
    milvus_uri: str = 'http://localhost:19530'
    milvus_collection: str = 'industrial_knowledge'
    milvus_token: SecretStr = SecretStr('')
    mcp_transport: Literal['stdio', 'local'] = 'stdio'
    aggregate_interval: int = Field(default=300, ge=1)
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'

    @property
    def ark_configured(self) -> bool:
        return bool(self.ark_api_key.get_secret_value() and self.ark_model)
