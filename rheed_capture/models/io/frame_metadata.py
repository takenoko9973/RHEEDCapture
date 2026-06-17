from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SequenceFrameMetadata:
    """通常シーケンスで保存するTIFFメタデータ。"""

    exposure_ms: float
    gain: int
    timestamp: str
    bit_depth_sensor: int = 12
    bit_depth_saved: int = 16
    alignment: str = "MsbAligned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "exposure_ms": self.exposure_ms,
            "gain": self.gain,
            "timestamp": self.timestamp,
            "bit_depth_sensor": self.bit_depth_sensor,
            "bit_depth_saved": self.bit_depth_saved,
            "alignment": self.alignment,
        }


@dataclass(frozen=True)
class AngleScanFrameMetadata:
    """角度走査で保存するTIFFメタデータ。"""

    scan_id: str
    target_angle_deg: float
    exposure_ms: float
    gain: int
    timestamp: str
    capture_mode: str = "angle_scan"
    actual_angle_deg: float | None = None
    angle_coordinate: str = "relative"
    angle_reference: str = "scan_start"
    bit_depth_sensor: int = 12
    bit_depth_saved: int = 16
    alignment: str = "MsbAligned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "capture_mode": self.capture_mode,
            "scan_id": self.scan_id,
            "target_angle_deg": self.target_angle_deg,
            "actual_angle_deg": self.actual_angle_deg,
            "angle_coordinate": self.angle_coordinate,
            "angle_reference": self.angle_reference,
            "exposure_ms": self.exposure_ms,
            "gain": self.gain,
            "timestamp": self.timestamp,
            "bit_depth_sensor": self.bit_depth_sensor,
            "bit_depth_saved": self.bit_depth_saved,
            "alignment": self.alignment,
        }
