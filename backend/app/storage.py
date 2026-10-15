import hashlib
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    JSON, Column, DateTime, Float, Index, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, event, func, insert, select, update,
)
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .schemas import Telemetry
from .processing import ProcessedTelemetry, calculate


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def serial(row) -> dict:
    def convert(value):
        if isinstance(value, datetime):
            return value.isoformat() + 'Z'
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        return value
    return {key: convert(value) for key, value in dict(row).items()}


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.url = settings.database_url
        if self.url.startswith('sqlite:///'):
            filename = self.url.removeprefix('sqlite:///')
            if filename != ':memory:':
                Path(filename).parent.mkdir(parents=True, exist_ok=True)
                self.url = 'sqlite:///' + Path(filename).resolve().as_posix()
        self.engine = create_engine(self.url, pool_pre_ping=True,
                                    connect_args={'check_same_thread': False, 'timeout': 30}
                                    if self.url.startswith('sqlite') else {})
        if self.url.startswith('sqlite'):
            @event.listens_for(self.engine, 'connect')
            def sqlite_settings(connection, _):
                connection.execute('PRAGMA journal_mode=WAL')
                connection.execute('PRAGMA busy_timeout=30000')
        self.meta = MetaData()
        self.registry = Table('system_meta', self.meta, Column('key', String(80), primary_key=True),
                              Column('value', String(200)))
        self.devices = Table('devices', self.meta,
            Column('id', String(32), primary_key=True), Column('name', String(80)),
            Column('kind', String(32)), Column('area', String(80)), Column('status', String(20)),
            Column('temperature', Float), Column('vibration', Float), Column('current', Float),
            Column('pressure', Float), Column('last_seen', DateTime), Column('demo', Integer))
        self.inbox = Table('ingest_events', self.meta,
            Column('event_id', String(80), primary_key=True), Column('device_id', String(32), index=True),
            Column('payload', JSON), Column('status', String(20), index=True),
            Column('attempts', Integer, default=0), Column('error', String(500)),
            Column('updated_at', DateTime))
        self.alerts = Table('alerts', self.meta,
            Column('id', String(36), primary_key=True), Column('device_id', String(32), index=True),
            Column('metric', String(32)), Column('severity', String(20)), Column('message', String(200)),
            Column('value', Float), Column('threshold', Float), Column('status', String(20)),
            Column('created_at', DateTime), Column('acknowledged_at', DateTime))
        self.logs = Table('device_logs', self.meta,
            Column('id', String(36), primary_key=True), Column('device_id', String(32), index=True),
            Column('level', String(20)), Column('message', String(500)), Column('created_at', DateTime))
        self.documents = Table('knowledge_documents', self.meta,
            Column('id', String(36), primary_key=True), Column('title', String(160)),
            Column('category', String(32)), Column('content', Text), Column('chunks', Integer),
            Column('index_status', String(32)), Column('created_at', DateTime))
        self.chunks = Table('knowledge_chunks', self.meta,
            Column('id', String(80), primary_key=True), Column('document_id', String(36), index=True),
            Column('title', String(160)), Column('text', Text), Column('position', Integer))
        self.aggregates = Table('hourly_aggregates', self.meta,
            Column('id', String(80), primary_key=True), Column('device_id', String(32), index=True),
            Column('bucket', String(32), index=True), Column('temperature', Float),
            Column('vibration', Float), Column('current', Float), Column('pressure', Float),
            Column('samples', Integer))
        self.sessions = Table('chat_sessions', self.meta,
            Column('id', String(36), primary_key=True), Column('device_id', String(32)),
            Column('title', String(100)), Column('created_at', DateTime))
        self.messages = Table('chat_messages', self.meta,
            Column('id', String(36), primary_key=True), Column('session_id', String(36), index=True),
            Column('role', String(20)), Column('content', Text), Column('evidence', JSON),
            Column('mode', String(20)), Column('created_at', DateTime))
        self.shards = [Table(f'telemetry_{number:03d}', self.meta,
            Column('event_id', String(80), primary_key=True), Column('device_id', String(32), index=True),
            Column('timestamp', DateTime, index=True), Column('temperature', Float),
            Column('vibration', Float), Column('current', Float), Column('pressure', Float),
            Column('ambient_temperature', Float), Column('humidity', Float),
            Column('source', String(80)), Column('health_score', Float),
            UniqueConstraint('device_id', 'event_id')) for number in range(settings.shard_count)]
        for table in self.shards:
            Index(f'ix_{table.name}_device_time', table.c.device_id, table.c.timestamp)

    def initialize(self):
        # Check before creating new shard tables: changing N would strand old data.
        self.registry.create(self.engine, checkfirst=True)
        with self.engine.begin() as conn:
            saved = conn.scalar(select(self.registry.c.value).where(self.registry.c.key == 'shard_count'))
            if saved and int(saved) != self.settings.shard_count:
                raise ValueError('SHARD_COUNT 与已有数据库不一致；先迁移数据，不能直接修改分片数')
            if not saved:
                conn.execute(insert(self.registry).values(key='shard_count', value=str(self.settings.shard_count)))
        self.meta.create_all(self.engine)

    def shard_number(self, device_id: str) -> int:
        return int.from_bytes(hashlib.sha256(device_id.encode()).digest()[:8], 'big') % len(self.shards)

    def rows(self, statement) -> list[dict]:
        with self.engine.connect() as conn:
            return [serial(row) for row in conn.execute(statement).mappings()]

    def device(self, device_id: str) -> dict | None:
        rows = self.rows(select(self.devices).where(self.devices.c.id == device_id))
        return rows[0] if rows else None

    def register_device(self, values: dict):
        with self.engine.begin() as conn:
            conn.execute(insert(self.devices).values(**values, status='offline', demo=0))

    def append_log(self, values: dict):
        with self.engine.begin() as conn:
            conn.execute(insert(self.logs).values(id=str(uuid4()), **values, created_at=utcnow()))

    def has_demo_data(self) -> bool:
        with self.engine.connect() as conn:
            return bool(conn.scalar(select(self.devices.c.id).where(self.devices.c.demo == 1).limit(1)))

    def accept(self, item: Telemetry) -> bool:
        payload = item.model_dump(mode='json')
        with self.engine.begin() as conn:
            try:
                conn.execute(insert(self.inbox).values(event_id=item.event_id, device_id=item.device_id,
                    payload=payload, status='pending', attempts=0, updated_at=utcnow()))
                return True
            except IntegrityError:
                existing = conn.scalar(select(self.inbox.c.payload).where(self.inbox.c.event_id == item.event_id))
                # A retry without a client timestamp keeps the first receipt time.
                if existing is not None and 'timestamp' not in item.model_fields_set:
                    payload['timestamp'] = existing['timestamp']
                if existing != payload:
                    raise ValueError('event_id 已被不同数据使用')
                return False

    def pending(self) -> list[dict]:
        return self.rows(select(self.inbox).where(self.inbox.c.status == 'pending').limit(100))

    def event_status(self, event_id: str) -> dict | None:
        rows = self.rows(select(self.inbox.c.event_id, self.inbox.c.status, self.inbox.c.attempts,
                                self.inbox.c.error).where(self.inbox.c.event_id == event_id))
        return rows[0] if rows else None

    def mark_event(self, event_id: str, status: str, error: str | None = None):
        with self.engine.begin() as conn:
            conn.execute(update(self.inbox).where(self.inbox.c.event_id == event_id)
                         .values(status=status, error=error, updated_at=utcnow()))

    def recover_events(self):
        with self.engine.begin() as conn:
            conn.execute(update(self.inbox).where(self.inbox.c.status == 'queued').values(status='pending'))

    def fail_event(self, event_id: str):
        with self.engine.begin() as conn:
            previous = conn.scalar(select(self.inbox.c.attempts).where(self.inbox.c.event_id == event_id)) or 0
            conn.execute(update(self.inbox).where(self.inbox.c.event_id == event_id).values(
                attempts=previous + 1, status='failed' if previous >= 2 else 'pending',
                error='数据处理失败，请检查后端日志', updated_at=utcnow()))

    def store_batch(self, items: list[Telemetry | ProcessedTelemetry]):
        with self.engine.begin() as conn:
            for item in items:
                self.store_telemetry(item, connection=conn)

    def store_telemetry(self, item: Telemetry | ProcessedTelemetry, connection=None) -> bool:
        processed = calculate(item) if isinstance(item, Telemetry) else item
        item = processed.item
        table = self.shards[self.shard_number(item.device_id)]
        values = item.model_dump()
        values['timestamp'] = processed.timestamp
        values['health_score'] = processed.health_score
        status = processed.status
        with nullcontext(connection) if connection is not None else self.engine.begin() as conn:
            exists = conn.scalar(select(table.c.event_id).where(table.c.event_id == item.event_id))
            if exists:
                conn.execute(update(self.inbox).where(self.inbox.c.event_id == item.event_id)
                             .values(status='completed', error=None, updated_at=utcnow()))
                return False
            conn.execute(insert(table).values(**values))
            device = conn.execute(select(self.devices).where(self.devices.c.id == item.device_id)).mappings().one()
            # Delayed messages belong in history, but cannot overwrite newer device state.
            if not device['last_seen'] or values['timestamp'] >= device['last_seen']:
                conn.execute(update(self.devices).where(self.devices.c.id == item.device_id).values(
                    temperature=item.temperature, vibration=item.vibration, current=item.current,
                    pressure=item.pressure, last_seen=values['timestamp'], status=status))
                for metric, warning, critical, label in [('temperature', 70, 85, '温度'), ('vibration', 4.5, 7.1, '振动')]:
                    value = getattr(item, metric)
                    if value < warning:
                        continue
                    existing = conn.execute(select(self.alerts).where(
                        self.alerts.c.device_id == item.device_id, self.alerts.c.metric == metric,
                        self.alerts.c.status != 'resolved')).mappings().first()
                    if not existing:
                        conn.execute(insert(self.alerts).values(id=str(uuid4()), device_id=item.device_id,
                            metric=metric, severity='critical' if value >= critical else 'warning',
                            message=f'{label}超过阈值，请检查设备运行状态', value=value,
                            threshold=critical if value >= critical else warning, status='open',
                            created_at=values['timestamp']))
                    else:
                        severity = 'critical' if value >= critical else 'warning'
                        alert_values = dict(value=value, severity=severity,
                                            threshold=critical if value >= critical else warning)
                        if existing['severity'] != 'critical' and severity == 'critical':
                            alert_values.update(status='open', acknowledged_at=None)
                        conn.execute(update(self.alerts).where(self.alerts.c.id == existing['id']).values(**alert_values))
            conn.execute(update(self.inbox).where(self.inbox.c.event_id == item.event_id)
                         .values(status='completed', error=None, updated_at=utcnow()))
        return True

    def history(self, device_id: str, hours: int = 24, limit: int = 300) -> list[dict]:
        table = self.shards[self.shard_number(device_id)]
        rows = self.rows(select(table).where(table.c.device_id == device_id,
            table.c.timestamp >= utcnow() - timedelta(hours=hours)).order_by(table.c.timestamp.desc()).limit(limit))
        return list(reversed(rows))

    def metric_summary(self, device_id: str) -> dict:
        table = self.shards[self.shard_number(device_id)]
        metrics = ['temperature', 'vibration', 'current', 'pressure']
        condition = (table.c.device_id == device_id) & (table.c.timestamp >= utcnow() - timedelta(hours=24))
        with self.engine.connect() as conn:
            values = conn.execute(select(func.count().label('samples'), *[
                agg(table.c[key]).label(f'{key}_{suffix}') for key in metrics
                for suffix, agg in [('min', func.min), ('max', func.max)]
            ]).where(condition)).mappings().one()
            first = conn.execute(select(table).where(condition).order_by(table.c.timestamp).limit(1)).mappings().first()
            last = conn.execute(select(table).where(condition).order_by(table.c.timestamp.desc()).limit(1)).mappings().first()
        result = {'samples': values['samples']}
        if first and last:
            for key in metrics:
                result[key] = {'min': values[f'{key}_min'], 'max': values[f'{key}_max'],
                               'change': round(last[key] - first[key], 3)}
        return result

    def device_alerts(self, device_id: str | None = None) -> list[dict]:
        stmt = select(self.alerts).order_by(self.alerts.c.created_at.desc()).limit(200)
        if device_id:
            stmt = stmt.where(self.alerts.c.device_id == device_id)
        return self.rows(stmt)

    def device_logs(self, device_id: str) -> list[dict]:
        return self.rows(select(self.logs).where(self.logs.c.device_id == device_id)
                         .order_by(self.logs.c.created_at.desc()).limit(20))

    def aggregate(self):
        bucket_func = (lambda col: func.strftime('%Y-%m-%dT%H:00:00Z', col)) if self.url.startswith('sqlite') else (
            lambda col: func.date_format(col, '%Y-%m-%dT%H:00:00Z'))
        with self.engine.begin() as conn:
            for table in self.shards:
                bucket = bucket_func(table.c.timestamp)
                stmt = select(table.c.device_id, bucket.label('bucket'), func.count().label('samples'),
                    *[func.avg(table.c[key]).label(key) for key in ['temperature', 'vibration', 'current', 'pressure']]
                ).where(table.c.timestamp >= utcnow() - timedelta(hours=48)).group_by(table.c.device_id, bucket)
                for row in conn.execute(stmt).mappings():
                    values = dict(row)
                    key = f'{row["device_id"]}:{row["bucket"]}'
                    exists = conn.scalar(select(self.aggregates.c.id).where(self.aggregates.c.id == key))
                    conn.execute(update(self.aggregates).where(self.aggregates.c.id == key).values(**values)
                                 if exists else insert(self.aggregates).values(id=key, **values))

    def overview(self) -> dict:
        devices = self.rows(select(self.devices).order_by(self.devices.c.id))
        alerts = self.device_alerts()
        with self.engine.connect() as conn:
            total = sum(conn.scalar(select(func.count()).select_from(table)) for table in self.shards)
            events = dict(conn.execute(select(self.inbox.c.status, func.count()).group_by(self.inbox.c.status)).all())
        trend = self.rows(select(self.aggregates.c.bucket,
            func.avg(self.aggregates.c.temperature).label('temperature'),
            func.avg(self.aggregates.c.vibration).label('vibration'),
            func.sum(self.aggregates.c.samples).label('samples')).where(
                self.aggregates.c.bucket >= (utcnow() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:00:00Z')
            ).group_by(self.aggregates.c.bucket).order_by(self.aggregates.c.bucket))
        return {'devices': devices, 'alerts': alerts, 'trend': trend, 'telemetry_count': total,
                'events': events, 'shard_count': len(self.shards),
                'total_devices': len(devices), 'normal_devices': sum(d['status'] == 'normal' for d in devices),
                'open_alerts': sum(a['status'] == 'open' for a in alerts),
                'critical_devices': sum(d['status'] == 'critical' for d in devices)}

    def acknowledge(self, alert_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(update(self.alerts).where(self.alerts.c.id == alert_id,
                self.alerts.c.status == 'open').values(status='acknowledged', acknowledged_at=utcnow()))
            return bool(result.rowcount)

    def save_document(self, document_id: str, title: str, category: str, content: str, chunks: list[str]):
        with self.engine.begin() as conn:
            conn.execute(insert(self.documents).values(id=document_id, title=title, category=category,
                content=content, chunks=len(chunks), index_status='pending', created_at=utcnow()))
            conn.execute(insert(self.chunks), [dict(id=f'{document_id}:{i}', document_id=document_id,
                title=title, text=text, position=i) for i, text in enumerate(chunks)])

    def set_index_status(self, document_id: str, status: str):
        with self.engine.begin() as conn:
            conn.execute(update(self.documents).where(self.documents.c.id == document_id).values(index_status=status))

    def delete_document(self, document_id: str):
        with self.engine.begin() as conn:
            conn.execute(self.chunks.delete().where(self.chunks.c.document_id == document_id))
            return bool(conn.execute(self.documents.delete().where(self.documents.c.id == document_id)).rowcount)

    def create_session(self, device_id: str, question: str) -> str:
        session_id = str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(self.sessions).values(id=session_id, device_id=device_id,
                title=question[:60], created_at=utcnow()))
        return session_id

    def save_message(self, session_id: str, role: str, content: str, evidence=None, mode='demo'):
        with self.engine.begin() as conn:
            conn.execute(insert(self.messages).values(id=str(uuid4()), session_id=session_id,
                role=role, content=content, evidence=evidence or [], mode=mode, created_at=utcnow()))

    def session_messages(self, session_id: str) -> list[dict]:
        recent = self.rows(select(self.messages).where(self.messages.c.session_id == session_id)
                           .order_by(self.messages.c.created_at.desc()).limit(100))
        return list(reversed(recent))
