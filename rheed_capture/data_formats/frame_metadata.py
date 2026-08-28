from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SequenceFrameMetadata:
    """Sequence TIFFへ埋め込む撮影条件と時刻情報。"""

    exposure_ms: float
    gain: int
    camera_exposure_ms: float
    camera_gain: int
    # software trigger発行直前のPC時刻。画像受信完了時刻ではない。
    timestamp: str
    # sourceにより、実機のcamera tickかシミュレーション時刻かを区別する。
    camera_timestamp_ticks: int
    camera_timestamp_frequency_hz: int
    camera_timestamp_source: Literal["camera", "host", "simulation"]

    def to_dict(self) -> dict[str, Any]:
        """TIFF metadataへ渡す辞書を返す。"""
        return {
            "exposure_ms": self.exposure_ms,
            "gain": self.gain,
            "camera_exposure_ms": self.camera_exposure_ms,
            "camera_gain": self.camera_gain,
            "timestamp": self.timestamp,
            "camera_timestamp_ticks": self.camera_timestamp_ticks,
            "camera_timestamp_frequency_hz": self.camera_timestamp_frequency_hz,
            "camera_timestamp_source": self.camera_timestamp_source,
        }


@dataclass(frozen=True)
class AngleScanFrameMetadata:
    """Angle Scan TIFFへ埋め込む角度、撮影条件、時刻情報。"""

    scan_id: str
    target_angle_deg: float
    exposure_ms: float
    gain: int
    camera_exposure_ms: float
    camera_gain: int
    # software trigger発行直前のPC時刻。画像受信完了時刻ではない。
    timestamp: str
    # sourceにより、実機のcamera tickかシミュレーション時刻かを区別する。
    camera_timestamp_ticks: int
    camera_timestamp_frequency_hz: int
    camera_timestamp_source: Literal["camera", "host", "simulation"]
    capture_mode: str = "angle_scan"
    actual_angle_deg: float | None = None
    angle_coordinate: str = "relative"
    angle_reference: str = "scan_start"

    def to_dict(self) -> dict[str, Any]:
        """TIFF metadataへ渡す辞書を返す。"""
        return {
            "capture_mode": self.capture_mode,
            "scan_id": self.scan_id,
            "target_angle_deg": self.target_angle_deg,
            "actual_angle_deg": self.actual_angle_deg,
            "angle_coordinate": self.angle_coordinate,
            "angle_reference": self.angle_reference,
            "exposure_ms": self.exposure_ms,
            "gain": self.gain,
            "camera_exposure_ms": self.camera_exposure_ms,
            "camera_gain": self.camera_gain,
            "timestamp": self.timestamp,
            "camera_timestamp_ticks": self.camera_timestamp_ticks,
            "camera_timestamp_frequency_hz": self.camera_timestamp_frequency_hz,
            "camera_timestamp_source": self.camera_timestamp_source,
        }
