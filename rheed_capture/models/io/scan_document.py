from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class AngleScanDocumentSettings:
    """scan.jsonに保存する角度走査条件。"""

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
    """1つの撮影条件。"""

    exposure_ms: float
    gain: int

    def to_dict(self) -> dict[str, Any]:
        return {"exposure_ms": self.exposure_ms, "gain": self.gain}


@dataclass(frozen=True)
class CaptureExecutionSettings:
    """撮影ループとリトライの実行条件。"""

    loop_order: list[str] = field(default_factory=lambda: ["angle", "condition"])
    retry_limit: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_order": self.loop_order,
            "retry_limit": self.retry_limit,
        }


@dataclass(frozen=True)
class AngleScanStorageFormat:
    """角度走査データの保存名規則。"""

    angle_directory_format: str = "angle{angle:+06.1f}"
    filename_format: str = "{scan_id}_angle{angle:+06.1f}_exp{exposure:g}_gain{gain:g}.tiff"

    def to_dict(self) -> dict[str, Any]:
        return {
            "angle_directory_format": self.angle_directory_format,
            "filename_format": self.filename_format,
        }


@dataclass(frozen=True)
class AngleScanDocument:
    """scan.json全体のスキーマ。"""

    schema_version: int
    scan_id: str
    created_at: str
    angle_scan: AngleScanDocumentSettings
    capture_conditions: list[CaptureCondition]
    capture: CaptureExecutionSettings = field(default_factory=CaptureExecutionSettings)
    storage: AngleScanStorageFormat = field(default_factory=AngleScanStorageFormat)
    notes: str = ""

    def with_scan_id(self, scan_id: str) -> AngleScanDocument:
        return replace(self, scan_id=scan_id)

    def with_created_at(self, created_at: str) -> AngleScanDocument:
        return replace(self, created_at=created_at)

    def to_dict(self) -> dict[str, Any]:
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
