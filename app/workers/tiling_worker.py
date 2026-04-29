"""
Tiling worker — consumes the 'tiling_jobs' RabbitMQ queue and runs TilingService.

Run with:
    python -m app.workers.tiling_worker
"""
import json
import logging
import time
from pathlib import Path

import pika
import pika.exceptions

from app.core.config import settings
from app.domain.models import JobStatus
from app.infrastructure.db.connection import get_sync_session
from app.infrastructure.db.repository import SyncUploadSessionRepository
from app.infrastructure.services.tiling_service import TilingService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

QUEUE_NAME = "tiling_jobs"


def _get_repo() -> SyncUploadSessionRepository:
    session = next(get_sync_session())
    return SyncUploadSessionRepository(session)


def process_message(
    channel: pika.adapters.blocking_connection.BlockingChannel,
    method: pika.spec.Basic.Deliver,
    _properties: pika.spec.BasicProperties,
    body: bytes,
) -> None:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("Invalid message payload: %s", exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    upload_id: str = data.get("upload_id", "")
    layer_id: str = data["layer_id"]
    file_type: str = data["file_type"]
    source_path = Path(data["source_path"])

    logger.info("Processing tiling job: layer_id=%s upload_id=%s", layer_id, upload_id)

    repo = _get_repo()

    try:
        if upload_id:
            repo.set_status(upload_id, JobStatus.processing)

        TilingService.process_tiling(file_type, source_path, layer_id)

        if upload_id:
            repo.set_status(upload_id, JobStatus.done)

        channel.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("Tiling complete: layer_id=%s", layer_id)

    except Exception as exc:
        logger.exception("Tiling failed: layer_id=%s error=%s", layer_id, exc)
        if upload_id:
            repo.set_status(upload_id, JobStatus.failed, error_message=str(exc))
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def run_worker() -> None:
    logger.info("Starting tiling worker, connecting to %s", settings.RABBITMQ_URL)
    while True:
        try:
            params = pika.URLParameters(settings.RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=process_message)
            logger.info("Worker ready, waiting for messages...")
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError as exc:
            logger.warning("RabbitMQ connection lost (%s), retrying in 5s...", exc)
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Worker shutting down.")
            break


if __name__ == "__main__":
    run_worker()
