from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.presentation.middleware.rate_limit import RateLimitMiddleware


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def incr(self, key):
        self.commands.append(("incr", key))

    def expire(self, key, seconds):
        self.commands.append(("expire", key, seconds))

    async def execute(self):
        count = 0
        for command in self.commands:
            if command[0] == "incr":
                count = self.redis.counts.get(command[1], 0) + 1
                self.redis.counts[command[1]] = count
        return [count, True]


class FakeRedis:
    def __init__(self):
        self.counts = {}

    def pipeline(self, transaction=True):
        assert transaction is True
        return FakePipeline(self)


def make_client(max_requests=2):
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        redis_client=FakeRedis(),
        max_requests=max_requests,
        window_seconds=60,
    )

    @app.get("/items")
    async def items():
        return {"ok": True}

    return TestClient(app)


def test_rate_limit_returns_headers_and_429():
    with make_client() as client:
        first = client.get("/items")
        second = client.get("/items")
        third = client.get("/items")

    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["x-ratelimit-remaining"] == "1"
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert third.status_code == 429
    assert third.json() == {"detail": "Rate limit exceeded."}
    assert "retry-after" in third.headers


def test_excluded_health_path_is_not_limited():
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        redis_client=FakeRedis(),
        max_requests=1,
        window_seconds=60,
    )

    @app.get("/health")
    async def health():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
