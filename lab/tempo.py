"""Horários em ISO 8601, UTC, com milissegundos."""
import time
from datetime import datetime, timezone


def agora_ms() -> int:
    return time.time_ns() // 1_000_000


def iso(t_ms: int | None = None) -> str:
    t_ms = agora_ms() if t_ms is None else t_ms
    return datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{t_ms % 1000:03d}Z"

