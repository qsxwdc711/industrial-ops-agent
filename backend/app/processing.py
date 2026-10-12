"""Small domain computations, independent from queue and persistence code."""
from dataclasses import dataclass
from datetime import datetime, timezone

from .schemas import Telemetry


@dataclass(frozen=True)
class ProcessedTelemetry:
    item: Telemetry
    timestamp: datetime
    health_score: float
    status: str


def calculate(item: Telemetry) -> ProcessedTelemetry:
    health_score = max(0, round(100 - max(0, item.temperature - 55) * 1.1
                               - max(0, item.vibration - 2) * 5, 1))
    status = 'critical' if item.temperature >= 85 or item.vibration >= 7.1 else (
        'warning' if item.temperature >= 70 or item.vibration >= 4.5 else 'normal')
    return ProcessedTelemetry(item, item.timestamp.astimezone(timezone.utc).replace(tzinfo=None), health_score, status)
