from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureCondition:
    exposure_ms: float
    gain: int
