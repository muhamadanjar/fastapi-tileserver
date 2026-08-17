"""Verify the OAuth service-token client behaviors Tileserver relies on.

Audience, scope, outage, renewal, and redaction are enforced by the shared
service_auth client; these tests lock the caller-side contract so a wrong
audience or missing scope can never produce a working token silently.
"""

import logging

import httpx
import pytest

from service_auth.client import SyncOAuthServiceClient
from service_auth.errors import AuthorizationServiceUnavailable
from service_auth.observability import record_auth_event

TOKEN_URL = "https://identity/oauth/token"
CLIENT_ID = "tileserver-client"
CLIENT_SECRET = "tileserver-secret"
AUDIENCE = "upload-api"
SCOPES = ("upload.artifacts.read", "upload.artifacts.lease")


def _client(handler, *, refresh_skew_seconds: int = 60) -> SyncOAuthServiceClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SyncOAuthServiceClient(
        TOKEN_URL,
        CLIENT_ID,
        CLIENT_SECRET,
        AUDIENCE,
        SCOPES,
        refresh_skew_seconds=refresh_skew_seconds,
        client=http,
    )


def _token_payload(**overrides) -> dict:
    payload = {
        "access_token": "opaque-token",
        "expires_in": 600,
        "audience": AUDIENCE,
        "scope": " ".join(SCOPES),
    }
    payload.update(overrides)
    return payload


def test_wrong_audience_is_rejected():
    def handler(request):
        return httpx.Response(
            200,
            json=_token_payload(audience="some-other-api"),
        )

    with pytest.raises(AuthorizationServiceUnavailable):
        _client(handler).access_token()


def test_missing_scope_is_rejected():
    def handler(request):
        return httpx.Response(
            200,
            json=_token_payload(scope="upload.artifacts.read"),
        )

    with pytest.raises(AuthorizationServiceUnavailable):
        _client(handler).access_token()


def test_token_endpoint_outage_raises_unavailable():
    def handler(request):
        return httpx.Response(503, text="identity down")

    with pytest.raises(AuthorizationServiceUnavailable):
        _client(handler).access_token()


def test_token_is_renewed_before_expiry():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_token_payload())

    # refresh_skew >= expires_in forces a re-acquisition on the next call,
    # proving the client renews rather than reusing a stale token.
    client = _client(handler, refresh_skew_seconds=600)
    assert client.access_token() == "opaque-token"
    assert client.access_token() == "opaque-token"
    client.close()
    assert calls == 2


def test_token_is_reused_while_still_valid():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_token_payload(expires_in=600))

    client = _client(handler, refresh_skew_seconds=60)
    first = client.access_token()
    second = client.access_token()
    third = client.access_token()
    client.close()
    assert first == second == third == "opaque-token"
    assert calls == 1


def test_auth_events_never_expose_secrets(caplog):
    caplog.set_level(logging.INFO, logger="service_auth.events")
    record_auth_event(
        "token_acquisition",
        outcome="success",
        client_id=CLIENT_ID,
        audience=AUDIENCE,
        access_token="super-secret-token",
        client_secret="super-secret-password",
    )
    assert len(caplog.records) > 0
    assert all(
        "super-secret-token" not in record.message and "super-secret-password" not in record.message
        for record in caplog.records
    )
