from celery import Celery
from kombu import Queue
from app.core.config import settings

celery_app = Celery(
    "tileserver",
    broker=settings.RABBITMQ_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    # Dedicated queue: upload_api's worker shares this broker and would
    # otherwise consume (and discard) tiling tasks from the default 'celery' queue.
    task_queues=[Queue('tileserver', durable=True)],
    task_default_queue='tileserver',
    # Use pika as RabbitMQ client
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
)
