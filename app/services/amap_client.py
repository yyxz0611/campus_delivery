"""高德地图 Web 服务封装：地理编码 + 步行路径规划（校内配送用真实路网）。

Key 从 .env 读取（AMAP_KEY）。未配置时 enabled=False，调用方应降级到 haversine 直线距离。
"""
from __future__ import annotations

import math

from ..config import settings

_TIMEOUT = 5


class AmapClient:
    base = "https://restapi.amap.com/v3"

    def __init__(self) -> None:
        self.key = settings.amap_key

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _get(self, path: str, params: dict) -> dict:
        import requests  # 延迟导入，避免无 Key 场景下强制依赖

        params = {**params, "key": self.key}
        resp = requests.get(f"{self.base}{path}", params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if str(data.get("status")) != "1":
            raise RuntimeError(f"高德 API 错误: {data.get('info')} (infocode={data.get('infocode')})")
        return data

    def geocode(self, address: str) -> tuple[float, float] | None:
        """地址 → 经纬度 (lon, lat)。"""
        data = self._get("/geocode/geo", {"address": address})
        geocodes = data.get("geocodes") or []
        if not geocodes:
            return None
        lon, _, lat = geocodes[0]["location"].partition(",")
        return float(lon), float(lat)

    def walking(self, origin: tuple[float, float], dest: tuple[float, float]) -> dict | None:
        """步行路径规划，返回 {distance(米), polyline([[lon,lat],...])}。"""
        data = self._get(
            "/direction/walking",
            {
                "origin": f"{origin[0]:.6f},{origin[1]:.6f}",
                "destination": f"{dest[0]:.6f},{dest[1]:.6f}",
            },
        )
        paths = (data.get("route") or {}).get("paths") or []
        if not paths:
            return None
        path = paths[0]
        polyline: list[list[float]] = []
        for step in path.get("steps", []):
            for pair in (step.get("polyline") or "").split(";"):
                if not pair:
                    continue
                lon, _, lat = pair.partition(",")
                polyline.append([float(lon), float(lat)])
        return {"distance": int(path.get("distance", 0)), "polyline": polyline}


amap = AmapClient()


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """球面直线距离（米），高德不可用时的降级。"""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))