"""HTTP client for lahat_api kodefikasi resolve — layered JWT + OAuth2 CC, cached."""

from __future__ import annotations

import os
import time
import logging
from typing import Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


class LahatKodefikasiClient:
    """Live client for POST /classification/resolve. Stateless aside from token/cache.

    Auth berlapis:
      1) coba service JWT (`LAHAT_API_JWT`) jika ada
      2) kalau 401 dan OAuth CC dikonfigurasi, tuker token via token_url lalu retry

    Cache: in-memory LRU sederhana dengan TTL 60s (key = catalog|component|sorted(codes)).
    Degraded: timeout/connection error → return {} (caller fallback ke raw).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        jwt_token: Optional[str] = None,
        timeout: Optional[float] = None,
        ttl_seconds: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        self.base_url = (base_url or settings.LAHAT_API_BASE_URL).rstrip("/")
        self.jwt_token = jwt_token if jwt_token is not None else settings.LAHAT_API_JWT
        self.timeout = timeout if timeout is not None else float(settings.LAHAT_ENRICHMENT_TIMEOUT_SECONDS)
        self.ttl = ttl_seconds if ttl_seconds is not None else int(settings.LAHAT_ENRICHMENT_TTL_SECONDS)
        self.enabled = enabled if enabled is not None else bool(settings.LAHAT_ENRICHMENT_ENABLED)

        # OAuth2 CC config
        self.oauth_token_url = settings.LAHAT_API_OAUTH_TOKEN_URL
        self.oauth_client_id = settings.LAHAT_API_OAUTH_CLIENT_ID
        self.oauth_client_secret = settings.LAHAT_API_OAUTH_CLIENT_SECRET
        self.oauth_scope = settings.LAHAT_API_OAUTH_SCOPE

        self._cache: dict[str, tuple[float, dict]] = {}
        self._oauth_token: Optional[str] = None
        self._oauth_expiry: float = 0

    def _cache_key(self, catalog_code: str, plan_component: str, codes: list[str]) -> str:
        return f"{catalog_code}|{plan_component}|{','.join(sorted(codes))}"

    def _get_cached(self, key: str) -> Optional[dict]:
        entry = self._cache.get(key)
        if not entry:
            return None
        expiry, value = entry
        if time.time() > expiry:
            self._cache.pop(key, None)
            return None
        return value

    def _set_cached(self, key: str, value: dict) -> None:
        # simple LRU eviction: keep max 1000 entries
        if len(self._cache) >= 1000:
            oldest = min(self._cache.items(), key=lambda kv: kv[1][0])
            self._cache.pop(oldest[0], None)
        self._cache[key] = (time.time() + self.ttl, value)

    def _obtain_oauth_token(self) -> Optional[str]:
        if not (self.oauth_token_url and self.oauth_client_id and self.oauth_client_secret):
            return None
        if self._oauth_token and time.time() < self._oauth_expiry - 30:
            return self._oauth_token
        try:
            resp = requests.post(
                self.oauth_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.oauth_client_id,
                    "client_secret": self.oauth_client_secret,
                    "scope": self.oauth_scope,
                } if self.oauth_scope else {
                    "grant_type": "client_credentials",
                    "client_id": self.oauth_client_id,
                    "client_secret": self.oauth_client_secret,
                },
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token")
            expires_in = int(data.get("expires_in", 3600))
            if token:
                self._oauth_token = token
                self._oauth_expiry = time.time() + expires_in
                return token
        except Exception as exc:
            logger.warning("lahat oauth token failed: %s", exc)
        return None

    def _headers_for(self, use_oauth: bool = False) -> dict:
        if use_oauth:
            tok = self._obtain_oauth_token()
            if tok:
                return {"Authorization": f"Bearer {tok}"}
        if self.jwt_token:
            return {"Authorization": f"Bearer {self.jwt_token}"}
        return {}

    async def resolve(
        self,
        catalog_code: str,
        plan_component: str,
        codes: list[str],
    ) -> dict[str, dict]:
        """Batch resolve codes → dict[domain_code -> item]. Empty on degraded."""
        if not self.enabled:
            return {}
        if not codes:
            return {}
        # deduplicate preserving order for cache key stability
        seen = set()
        uniq = []
        for c in codes:
            if c and str(c).strip() and str(c).strip() not in seen:
                seen.add(str(c).strip())
                uniq.append(str(c).strip())
        if not uniq:
            return {}
        key = self._cache_key(catalog_code, plan_component, uniq)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/api/v1/classification/resolve"
        body = {"catalog_code": catalog_code, "plan_component": plan_component, "codes": uniq}

        # try JWT first
        for attempt, use_oauth in enumerate([False, True]):
            headers = self._headers_for(use_oauth=use_oauth)
            if attempt == 1 and not headers:
                break  # no oauth config
            try:
                import asyncio
                def _do():
                    return requests.post(url, json=body, headers=headers, timeout=self.timeout)
                resp = await asyncio.to_thread(_do)
                if resp.status_code == 401 and attempt == 0:
                    # try oauth fallback
                    continue
                if resp.status_code == 404:
                    # catalog not found → treat as not_found for all
                    logger.warning("lahat catalog not found: %s", catalog_code)
                    self._set_cached(key, {})
                    return {}
                if resp.status_code != 200:
                    logger.warning("lahat resolve %s: %s %s", resp.status_code, url, resp.text[:300])
                    # degraded: cache empty briefly (10s) to avoid hammering
                    self._cache[key] = (time.time() + 10, {})
                    return {}
                data = resp.json()
                # APIResponse wrapper: {data: {items, not_found}} or direct
                payload = data.get("data") if isinstance(data, dict) and "data" in data else data
                items = payload.get("items", []) if isinstance(payload, dict) else []
                result: dict[str, dict] = {}
                for it in items:
                    code = it.get("domain_code")
                    if code:
                        result[code] = it
                self._set_cached(key, result)
                return result
            except requests.exceptions.Timeout:
                logger.warning("lahat resolve timeout catalog=%s codes=%s", catalog_code, uniq[:3])
                self._cache[key] = (time.time() + 10, {})
                return {}
            except Exception as exc:
                logger.warning("lahat resolve error: %s", exc)
                self._cache[key] = (time.time() + 10, {})
                return {}
        return {}
