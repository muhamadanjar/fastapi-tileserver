"""HTTP session helpers for Esri REST requests."""

from __future__ import annotations

import logging
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_READ_TIMEOUT = 120
DEFAULT_TIMEOUT = (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT)
DEFAULT_RETRY_TOTAL = 3
DEFAULT_RETRY_BACKOFF = 0.6
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
SAFE_RETRY_METHODS = frozenset({"HEAD", "GET", "OPTIONS"})
IDEMPOTENT_POST_METHODS = frozenset({"HEAD", "GET", "OPTIONS", "POST"})

_SSL_WARNINGS_DISABLED = False


def timeout_tuple(
    timeout: int | float | tuple | None,
    *,
    default: tuple[int, int] = DEFAULT_TIMEOUT,
) -> tuple | int | float:
    """Return a requests-compatible timeout value."""
    if timeout is None:
        return default
    return timeout


def _retry(
    methods: Iterable[str],
    *,
    total: int = DEFAULT_RETRY_TOTAL,
    backoff: float = DEFAULT_RETRY_BACKOFF,
) -> Retry:
    return Retry(
        total=total,
        connect=total,
        read=total,
        status=total,
        status_forcelist=RETRY_STATUS_CODES,
        allowed_methods=frozenset(methods),
        backoff_factor=backoff,
        raise_on_status=False,
        respect_retry_after_header=True,
    )


def mount_retry_adapters(
    session: requests.Session,
    *,
    retry_total: int = DEFAULT_RETRY_TOTAL,
    backoff: float = DEFAULT_RETRY_BACKOFF,
    retry_post: bool = False,
) -> requests.Session:
    """Attach bounded retry adapters to an existing session and return it."""
    if not hasattr(session, "mount"):
        return session
    methods = IDEMPOTENT_POST_METHODS if retry_post else SAFE_RETRY_METHODS
    adapter = HTTPAdapter(
        max_retries=_retry(methods, total=retry_total, backoff=backoff)
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def create_retry_session(
    *,
    headers: dict | None = None,
    retry_total: int = DEFAULT_RETRY_TOTAL,
    backoff: float = DEFAULT_RETRY_BACKOFF,
    retry_post: bool = False,
) -> requests.Session:
    """Create a requests Session with bounded retries for transient failures."""
    session = mount_retry_adapters(
        requests.Session(),
        retry_total=retry_total,
        backoff=backoff,
        retry_post=retry_post,
    )
    if headers:
        session.headers.update(headers)
    return session


def disable_ssl_warnings_once(*, service_url: str = "") -> None:
    """Disable urllib3 SSL warnings only once per process."""
    global _SSL_WARNINGS_DISABLED
    if _SSL_WARNINGS_DISABLED:
        return
    _SSL_WARNINGS_DISABLED = True
    if service_url:
        logger.warning("SSL verification disabled for %s", service_url)
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        logger.debug("Failed to disable urllib3 SSL warnings", exc_info=True)
