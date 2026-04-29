import json
import logging

import aio_pika
from aio_pika import DeliveryMode, Message

from app.core.config import settings

logger = logging.getLogger(__name__)

QUEUE_NAME = "tiling_jobs"


class RabbitMQPublisher:
    def __init__(self):
        self._connection: aio_pika.RobustConnection | None = None
        self._channel: aio_pika.RobustChannel | None = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        self._channel = await self._connection.channel()
        await self._channel.declare_queue(QUEUE_NAME, durable=True)
        logger.info("RabbitMQ publisher connected.")

    async def close(self) -> None:
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        logger.info("RabbitMQ publisher disconnected.")

    async def publish_tiling_job(
        self,
        upload_id: str,
        layer_id: str,
        file_type: str,
        source_path: str,
    ) -> None:
        payload = json.dumps(
            {
                "upload_id": upload_id,
                "layer_id": layer_id,
                "file_type": file_type,
                "source_path": source_path,
            }
        )
        await self._channel.default_exchange.publish(
            Message(
                body=payload.encode(),
                delivery_mode=DeliveryMode.PERSISTENT,
            ),
            routing_key=QUEUE_NAME,
        )
        logger.info("Tiling job queued: layer_id=%s upload_id=%s", layer_id, upload_id)
