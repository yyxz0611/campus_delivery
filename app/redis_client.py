"""Redis 封装：生产对接华为云 DCS Redis，未配置/连接失败时降级为进程内实现。

统一抽象：缓存（get/set）与通知流（push/history）。
降级模式保证本地无 Redis 也能完整跑通 Demo。
"""
from __future__ import annotations

import json
import threading
from typing import Any

from .config import settings


class InMemoryBackend:
    """进程内降级实现（线程安全）。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._streams: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        with self._lock:
            self._data[key] = value

    def push(self, channel: str, payload: dict) -> None:
        with self._lock:
            self._streams.setdefault(channel, []).append(json.dumps(payload, ensure_ascii=False))
            # 每个频道最多保留 200 条
            self._streams[channel] = self._streams[channel][-200:]

    def history(self, channel: str, limit: int = 50) -> list[dict]:
        with self._lock:
            items = self._streams.get(channel, [])[-limit:]
            return [json.loads(i) for i in items]


class RedisClient:
    """统一门面。"""

    def __init__(self) -> None:
        self._redis = None
        self._fallback = InMemoryBackend()
        self._mode = "in-memory"
        self._try_connect()

    def _try_connect(self) -> None:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
            client.ping()
            self._redis = client
            self._mode = "redis"
        except Exception:
            self._redis = None
            self._mode = "in-memory"

    @property
    def mode(self) -> str:
        return self._mode

    def get(self, key: str) -> str | None:
        if self._redis is not None:
            try:
                v = self._redis.get(key)
                return v.decode("utf-8") if v else None
            except Exception:
                pass
        return self._fallback.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        if self._redis is not None:
            try:
                self._redis.set(key, payload, ex=ttl)
                return
            except Exception:
                pass
        self._fallback.set(key, payload, ttl)

    def push(self, channel: str, payload: dict) -> None:
        if self._redis is not None:
            try:
                self._redis.rpush(f"stream:{channel}", json.dumps(payload, ensure_ascii=False, default=str))
                self._redis.ltrim(f"stream:{channel}", -200, -1)
                return
            except Exception:
                pass
        self._fallback.push(channel, payload)

    def history(self, channel: str, limit: int = 50) -> list[dict]:
        if self._redis is not None:
            try:
                raw = self._redis.lrange(f"stream:{channel}", -limit, -1)
                return [json.loads(i) for i in raw]
            except Exception:
                pass
        return self._fallback.history(channel, limit)


redis_client = RedisClient()