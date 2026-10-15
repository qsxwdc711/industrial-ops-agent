from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class Telemetry(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()), pattern=r'^[\w-]{1,80}$')
    device_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    temperature: float = Field(ge=-50, le=180)
    vibration: float = Field(ge=0, le=100)
    current: float = Field(ge=0, le=1000)
    pressure: float = Field(ge=0, le=100)
    ambient_temperature: float | None = Field(default=None, ge=-50, le=100)
    humidity: float | None = Field(default=None, ge=0, le=100)
    source: str = Field(default='device-gateway', min_length=1, max_length=80)

    @field_validator('timestamp')
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError('timestamp 必须包含时区，例如 2026-10-11T08:00:00Z')
        if value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('采样时间不能超过当前时间 5 分钟')
        return value.astimezone(timezone.utc)


class DeviceInput(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')
    name: str = Field(min_length=2, max_length=80)
    kind: Literal['pump', 'motor']
    area: str = Field(min_length=2, max_length=80)

    @field_validator('name', 'area')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if len(value.strip()) < 2:
            raise ValueError('名称和区域至少需要两个有效字符')
        return value.strip()


class LogInput(BaseModel):
    device_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')
    level: Literal['info', 'warning', 'error'] = 'info'
    message: str = Field(min_length=2, max_length=500)

    @field_validator('message')
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError('日志至少需要两个有效字符')
        return value


class DocumentInput(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    category: Literal['manual', 'case', 'procedure'] = 'manual'
    content: str = Field(min_length=20, max_length=100_000)

    @field_validator('title', 'content')
    @classmethod
    def nonblank(cls, value: str, info) -> str:
        minimum = 20 if info.field_name == 'content' else 2
        if len(value.strip()) < minimum:
            raise ValueError(f'至少需要 {minimum} 个有效字符')
        return value.strip()


class AnalysisInput(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    device_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')
    session_id: str | None = Field(default=None, pattern=r'^[a-f0-9-]{36}$')

    @field_validator('question')
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError('问题至少需要两个有效字符')
        return value
