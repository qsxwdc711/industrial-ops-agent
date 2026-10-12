import asyncio
import json
import logging
from contextlib import suppress

import aio_pika

from .cache import Cache
from .schemas import Telemetry
from .processing import calculate
from .storage import Storage

logger = logging.getLogger(__name__)


class Pipeline:
    """Durable inbox -> parse -> calculate -> store; ACK follows commit."""

    def __init__(self, storage: Storage, cache: Cache):
        self.storage, self.cache = storage, cache
        self.raw = asyncio.Queue(maxsize=512)
        self.parsed = asyncio.Queue(maxsize=512)
        self.calculated = asyncio.Queue(maxsize=512)
        self.tasks: list[asyncio.Task] = []
        self.connection = None
        self.channel = None
        self.broker_queue = None
        self.consumer_tag = None
        self.aggregate_error: str | None = None

    async def start(self):
        await asyncio.to_thread(self.storage.recover_events)
        if self.storage.settings.queue_backend == 'rabbitmq':
            self.connection = await aio_pika.connect_robust(self.storage.settings.rabbitmq_url, timeout=10)
            self.channel = await self.connection.channel(publisher_confirms=True)
            await self.channel.set_qos(prefetch_count=32)
            self.broker_queue = await self.channel.declare_queue('industrial.telemetry', durable=True)
            self.consumer_tag = await self.broker_queue.consume(self.consume)
        self.tasks = [asyncio.create_task(self.parse(), name='parse-worker'),
                      asyncio.create_task(self.compute(), name='calculation-worker'),
                      asyncio.create_task(self.write(), name='storage-worker'),
                      asyncio.create_task(self.dispatch(), name='inbox-dispatcher'),
                      asyncio.create_task(self.aggregate(), name='hourly-aggregation')]

    async def consume(self, message: aio_pika.IncomingMessage):
        try:
            item = Telemetry.model_validate_json(message.body)
            if not await asyncio.to_thread(self.storage.device, item.device_id):
                await message.reject(requeue=False)
                return
            await asyncio.to_thread(self.storage.accept, item)
            future = asyncio.get_running_loop().create_future()
            await self.raw.put((item.model_dump(mode='json'), future))
            if await future:
                await message.ack()
            else:
                # The inbox schedules up to three retries; poison messages are not looped forever.
                await message.reject(requeue=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('RabbitMQ message handling failed')
            if not message.processed:
                await message.reject(requeue=False)

    async def dispatch(self):
        while True:
            records = await asyncio.to_thread(self.storage.pending)
            for record in records:
                event_id = record['event_id']
                await asyncio.to_thread(self.storage.mark_event, event_id, 'queued')
                try:
                    if self.channel:
                        await self.channel.default_exchange.publish(aio_pika.Message(
                            json.dumps(record['payload']).encode(),
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            message_id=event_id), routing_key='industrial.telemetry')
                    else:
                        future = asyncio.get_running_loop().create_future()
                        await self.raw.put((record['payload'], future))
                except asyncio.CancelledError:
                    await asyncio.to_thread(self.storage.mark_event, event_id, 'pending')
                    raise
                except Exception:
                    logger.exception('Failed to enqueue telemetry')
                    await asyncio.to_thread(self.storage.fail_event, event_id)
            await asyncio.sleep(0.3)

    async def parse(self):
        while True:
            payload, future = await self.raw.get()
            try:
                item = Telemetry.model_validate(payload)
                await self.parsed.put((item, future))
            except Exception:
                logger.exception('Telemetry parsing failed')
                await asyncio.to_thread(self.storage.fail_event, payload['event_id'])
                if not future.done():
                    future.set_result(False)
            finally:
                self.raw.task_done()

    async def compute(self):
        while True:
            item, future = await self.parsed.get()
            try:
                await self.calculated.put((calculate(item), future))
            except Exception:
                logger.exception('Telemetry calculation failed')
                await asyncio.to_thread(self.storage.fail_event, item.event_id)
                if not future.done():
                    future.set_result(False)
            finally:
                self.parsed.task_done()

    async def write(self):
        while True:
            batch = [await self.calculated.get()]
            while len(batch) < 32:
                try:
                    batch.append(self.calculated.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                await asyncio.to_thread(self.storage.store_batch, [item for item, _ in batch])
                success = True
            except Exception:
                logger.exception('Telemetry batch persistence failed')
                for item, _ in batch:
                    await asyncio.to_thread(self.storage.fail_event, item.item.event_id)
                success = False
            finally:
                for _, future in batch:
                    if not future.done():
                        future.set_result(success)
                    self.calculated.task_done()
            if success:
                try:
                    await self.cache.invalidate()
                except Exception:
                    logger.exception('Data committed, but cache invalidation failed')

    async def aggregate(self):
        while True:
            try:
                await asyncio.to_thread(self.storage.aggregate)
                self.aggregate_error = None
                await self.cache.invalidate()
            except Exception:
                self.aggregate_error = '小时聚合失败，请检查后端日志'
                logger.exception('Hourly aggregation failed')
            await asyncio.sleep(self.storage.settings.aggregate_interval)

    async def close(self):
        # Stop publishing before draining stages; unprocessed inbox records replay on restart.
        for task in self.tasks[3:]:
            task.cancel()
        for task in self.tasks[3:]:
            with suppress(asyncio.CancelledError):
                await task
        if self.broker_queue and self.consumer_tag:
            await self.broker_queue.cancel(self.consumer_tag)
        with suppress(TimeoutError):
            async with asyncio.timeout(10):
                await self.raw.join()
                await self.parsed.join()
                await self.calculated.join()
        for task in self.tasks[:3]:
            task.cancel()
        for task in self.tasks[:3]:
            with suppress(asyncio.CancelledError):
                await task
        if self.connection:
            await self.connection.close()
