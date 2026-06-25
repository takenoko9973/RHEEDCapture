from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from rheed_capture.data_formats.storage_naming import (
    ANGLE_DIR_PATTERN,
    ANGLE_SCAN_TIFF_FILENAME_PATTERN,
)
from rheed_capture.domain.capture_defaults import DEFAULT_CAPTURE_RETRY_LIMIT


@dataclass(frozen=True)
class AngleScanDocumentSettings:
    """scan.jsonのangle_scanセクションへ保存する走査条件。"""

    coordinate: str
    reference: str
    range_deg: float
    interval_deg: float
    direction: str
    position_units_per_deg: float
    capture_angles_deg: list[float]
    wait_after_move_ms: int
    motor_speed_rpm: float
    return_to_start: bool

    def to_dict(self) -> dict[str, Any]:
        """angle_scanセクションをJSON保存用dictへ変換する。"""
        return {
            "coordinate": self.coordinate,
            "reference": self.reference,
            "range_deg": self.range_deg,
            "interval_deg": self.interval_deg,
            "direction": self.direction,
            "position_units_per_deg": self.position_units_per_deg,
            "capture_angles_deg": self.capture_angles_deg,
            "wait_after_move_ms": self.wait_after_move_ms,
            "motor_speed_rpm": self.motor_speed_rpm,
            "return_to_start": self.return_to_start,
        }


@dataclass(frozen=True)
class CaptureCondition:
    """scan.jsonへ保存する1つの撮影条件。"""

    exposure_ms: float
    gain: int

    def to_dict(self) -> dict[str, Any]:
        """撮影条件をJSON保存用dictへ変換する。"""
        return {"exposure_ms": self.exposure_ms, "gain": self.gain}


@dataclass(frozen=True)
class CaptureExecutionSettings:
    """scan.jsonへ保存する撮影実行条件。"""

    loop_order: list[str] = field(default_factory=lambda: ["angle", "condition"])
    retry_limit: int = DEFAULT_CAPTURE_RETRY_LIMIT

    def to_dict(self) -> dict[str, Any]:
        """撮影実行条件をJSON保存用dictへ変換する。"""
        return {
            "loop_order": self.loop_order,
            "retry_limit": self.retry_limit,
        }


@dataclass(frozen=True)
class AngleScanStorageFormat:
    """scan.jsonへ保存するAngle Scanの保存形式情報。"""

    angle_directory_format: str = ANGLE_DIR_PATTERN
    filename_format: str = ANGLE_SCAN_TIFF_FILENAME_PATTERN

    def to_dict(self) -> dict[str, Any]:
        """保存形式情報をJSON保存用dictへ変換する。"""
        return {
            "angle_directory_format": self.angle_directory_format,
            "filename_format": self.filename_format,
        }


@dataclass(frozen=True)
class AngleScanDocument:
    """Angle Scanのscan.json全体を表す保存モデル。"""

    schema_version: int
    scan_id: str
    created_at: str
    angle_scan: AngleScanDocumentSettings
    capture_conditions: list[CaptureCondition]
    capture: CaptureExecutionSettings = field(default_factory=CaptureExecutionSettings)
    storage: AngleScanStorageFormat = field(default_factory=AngleScanStorageFormat)
    notes: str = ""

    def with_scan_id(self, scan_id: str) -> AngleScanDocument:
        """Storage側で確定したscan_idを反映したモデルを返す。"""
        return replace(self, scan_id=scan_id)

    def with_created_at(self, created_at: str) -> AngleScanDocument:
        """Storage側で確定した作成時刻を反映したモデルを返す。"""
        return replace(self, created_at=created_at)

    def to_dict(self) -> dict[str, Any]:
        """scan.json全体をJSON保存用dictへ変換する。"""
        return {
            "schema_version": self.schema_version,
            "scan_id": self.scan_id,
            "created_at": self.created_at,
            "angle_scan": self.angle_scan.to_dict(),
            "capture_conditions": [
                condition.to_dict() for condition in self.capture_conditions
            ],
            "capture": self.capture.to_dict(),
            "storage": self.storage.to_dict(),
            "notes": self.notes,
        }
