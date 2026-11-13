import threading
import time
from typing import Any, Dict, Optional, Tuple

class SimpleTtlCache:
    """
    In-memory thread-safe TTL cache for spatial coordinate responses.
    Allows custom precision rounding (e.g. 0.1 deg ~ 11 km grid, or 0.001 deg ~ 110 m grid).
    """
    def __init__(self, ttl_seconds: int = 3600, max_entries: int = 1000, precision: int = 3):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.precision = precision
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _get_key(self, lat: float, lon: float, category: str, precision: Optional[int] = None, scene_id: Optional[str] = None, grid_step: Optional[float] = None) -> str:
        if grid_step is not None and grid_step > 0:
            rounded_lat = round(round(lat / grid_step) * grid_step, 6)
            rounded_lon = round(round(lon / grid_step) * grid_step, 6)
        else:
            p = precision if precision is not None else self.precision
            rounded_lat = round(lat, p)
            rounded_lon = round(lon, p)
        extra = f":{scene_id}" if scene_id else ""
        return f"{category}:{rounded_lat}:{rounded_lon}{extra}"

    def get(self, lat: float, lon: float, category: str, precision: Optional[int] = None, scene_id: Optional[str] = None, grid_step: Optional[float] = None) -> Optional[Any]:
        key = self._get_key(lat, lon, category, precision, scene_id, grid_step)
        with self._lock:
            if key in self._store:
                timestamp, data = self._store[key]
                if time.time() - timestamp < self.ttl_seconds:
                    return data
                else:
                    self._store.pop(key, None)
        return None

    def set(self, lat: float, lon: float, category: str, value: Any, precision: Optional[int] = None, scene_id: Optional[str] = None, grid_step: Optional[float] = None) -> None:
        key = self._get_key(lat, lon, category, precision, scene_id, grid_step)
        now = time.time()
        with self._lock:
            if len(self._store) >= self.max_entries:
                # Purge oldest 20% safely from snapshot
                items_snapshot = list(self._store.items())
                items_snapshot.sort(key=lambda item: item[1][0])
                for k, _ in items_snapshot[:self.max_entries // 5]:
                    self._store.pop(k, None)
            self._store[key] = (now, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

# Standard micro-scale cache (1 hour TTL, ~110m resolution)
cache = SimpleTtlCache(ttl_seconds=3600, precision=3)

# 24-hour TTL hazard & geospatial telemetry cache keyed on 0.1 degree grid (~11km)
hazard_cache = SimpleTtlCache(ttl_seconds=86400, precision=1)

# 7-day TTL satellite vision cache keyed on 0.002 degree grid (~220m) plus scene id
vision_cache = SimpleTtlCache(ttl_seconds=604800, precision=3)

