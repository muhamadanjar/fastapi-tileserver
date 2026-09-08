"""Thin Nominatim (OSM) HTTP client for forward and reverse geocoding."""
from typing import Optional

import requests

from app.core.config import settings


def _coerce_coords(result: dict) -> dict:
    """jsonv2 returns lon/lat as strings; normalize to floats for schemas."""
    result = dict(result)
    for key in ("lon", "lat"):
        if key in result:
            try:
                result[key] = float(result[key])
            except (TypeError, ValueError):
                result[key] = None
    return result


class NominatimClient:
    """Live Nominatim client. No caching — keep it stateless and simple."""

    def __init__(self) -> None:
        self.base_url = settings.NOMINATIM_URL.rstrip("/")
        self.timeout = settings.NOMINATIM_TIMEOUT
        self.headers = {
            "User-Agent": settings.NOMINATIM_USER_AGENT,
            "Accept-Language": "en",
        }

    def forward(self, query: str, limit: int = 1) -> list[dict]:
        """Forward geocode a free-form search string. Returns Nominatim results."""
        resp = requests.get(
            f"{self.base_url}/search",
            params={"q": query, "format": "jsonv2", "addressdetails": 1, "limit": limit},
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [_coerce_coords(r) for r in (resp.json() or [])]

    def reverse(self, lon: float, lat: float) -> Optional[dict]:
        """Reverse geocode a coordinate. Returns a single Nominatim result or None."""
        resp = requests.get(
            f"{self.base_url}/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "zoom": 18},
            headers=self.headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return _coerce_coords(data) if data else None