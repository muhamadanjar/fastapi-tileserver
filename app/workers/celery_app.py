from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "tileserver",
    broker=settings.RABBITMQ_URL,
    backend="rpc://",
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
