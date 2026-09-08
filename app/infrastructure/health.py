"""
Infrastructure health checks for database, Redis, and RabbitMQ.
"""
import asyncio
import logging
from typing import Dict, Any

import redis.asyncio as aioredis
from kombu import Connection as KombuConnection

from app.core.config import settings
from app.infrastructure.db.connection import db

logger = logging.getLogger(__name__)


async def check_database() -> Dict[str, Any]:
    """Check database connectivity."""
    try:
        ok = await db.health_check()
        return {"status": "connected" if ok else "disconnected"}
    except Exception as e:
        logger.warning("Database health check failed: %s", e)
        return {"status": "disconnected", "error": str(e)}


async def check_redis() -> Dict[str, Any]:
    """Check Redis connectivity via PING."""
    try:
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=5)
        try:
            pong = await client.ping()
            return {"status": "connected" if pong else "disconnected"}
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning("Redis health check failed: %s", e)
        return {"status": "disconnected", "error": str(e)}


def _check_rabbitmq_sync() -> bool:
    """Synchronous RabbitMQ check via kombu (broker_url)."""
    conn = KombuConnection(settings.RABBITMQ_URL)
    conn.connect()
    try:
        conn.transport.ensure_connection(conn, timeout=5)
        return True
    except Exception:
        raise
    finally:
        conn.close()


async def check_rabbitmq() -> Dict[str, Any]:
    """Check RabbitMQ connectivity."""
    try:
        ok = await asyncio.to_thread(_check_rabbitmq_sync)
        return {"status": "connected" if ok else "disconnected"}
    except Exception as e:
        logger.warning("RabbitMQ health check failed: %s", e)
        return {"status": "disconnected", "error": str(e)}


async def check_all_infrastructure() -> Dict[str, Any]:
    """Run all infrastructure health checks concurrently."""
    db_result, redis_result, rabbit_result = await asyncio.gather(
        check_database(),
        check_redis(),
        check_rabbitmq(),
    )

    all_ok = (
        db_result["status"] == "connected"
        and redis_result["status"] == "connected"
        and rabbit_result["status"] == "connected"
    )

    return {
        "status": "healthy" if all_ok else "degraded",
        "service": "tileserver_api",
        "infrastructure": {
            "database": db_result,
            "redis": redis_result,
            "rabbitmq": rabbit_result,
        },
    }
