from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

from rheed_capture.models.domain.angle_scan import (
    AngleScanDirection,
    validate_direction,
    validate_interval,
    validate_interval_within_range,
    validate_range,
)
from rheed_capture.models.hardware.motor_defaults import (
    DEFAULT_MOTOR_PORT,
    DEFAULT_MOTOR_SLAVE,
    DEFAULT_MOTOR_SPEED_RPM,
    DEFAULT_POSITION_UNITS_PER_DEG,
)

logger = logging.getLogger(__name__)


def _default_exposure_ms_list() -> list[float]:
    """通常撮影と角度走査で共有する露光時間の初期値。"""
    return [10.0, 50.0, 100.0]


def _default_gain_list() -> list[int]:
    """通常撮影と角度走査で共有するゲインの初期値。"""
    return [0]


def _as_mapping(value: object) -> dict[str, Any]:
    """JSON由来の値がdictでなければ空dictとして扱う。"""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)

    return {}


def _require_non_negative_wait_time(wait_after_move_ms: int) -> None:
    """撮影前待機時間の共通検証。0msは許可する。"""
    if wait_after_move_ms < 0:
        msg = "移動後待機時間は0以上にしてください。"
        raise ValueError(msg)


def _require_positive_motor_speed(motor_speed_rpm: float) -> None:
    """角度走査で使うモーター速度の共通検証。"""
    if motor_speed_rpm <= 0:
        msg = "モーター速度は正の値にしてください。"
        raise ValueError(msg)


@dataclass(frozen=True)
class PreviewSettings:
    """プレビュー表示とプレビュー用カメラ条件。"""

    exposure_ms: float = 50.0
    gain: int = 0
    enable_clahe: bool = False
    show_grid: bool = False
    grid_rows: int = 4
    grid_cols: int = 4

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreviewSettings:
        defaults = cls()
        return cls(
            exposure_ms=float(data.get("preview_expo", defaults.exposure_ms)),
            gain=int(data.get("preview_gain", defaults.gain)),
            enable_clahe=bool(data.get("enable_clahe", defaults.enable_clahe)),
            show_grid=bool(data.get("show_preview_grid", defaults.show_grid)),
            grid_rows=int(data.get("preview_grid_rows", defaults.grid_rows)),
            grid_cols=int(data.get("preview_grid_cols", defaults.grid_cols)),
        )

    def with_grid(self, grid: PreviewGridSettings) -> PreviewSettings:
        return replace(
            self,
            show_grid=grid.show_grid,
            grid_rows=grid.rows,
            grid_cols=grid.cols,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_expo": self.exposure_ms,
            "preview_gain": self.gain,
            "enable_clahe": self.enable_clahe,
            "show_preview_grid": self.show_grid,
            "preview_grid_rows": self.grid_rows,
            "preview_grid_cols": self.grid_cols,
        }


@dataclass(frozen=True)
class PreviewGridSettings:
    """プレビュー画像上に重ねるグリッド設定。"""

    show_grid: bool = False
    rows: int = 4
    cols: int = 4


@dataclass(frozen=True)
class SequenceCaptureSettings:
    """通常シーケンス撮影の条件。"""

    exposure_ms_list: list[float] = field(default_factory=_default_exposure_ms_list)
    gain_list: list[int] = field(default_factory=_default_gain_list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceCaptureSettings:
        defaults = cls()
        return cls(
            exposure_ms_list=list(data.get("exposure_ms_list", defaults.exposure_ms_list)),
            gain_list=list(data.get("gain_list", defaults.gain_list)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exposure_ms_list": self.exposure_ms_list,
            "gain_list": self.gain_list,
        }


@dataclass(frozen=True)
class AngleScanCaptureSettings:
    """角度走査撮影の条件。"""

    exposure_ms_list: list[float] = field(default_factory=_default_exposure_ms_list)
    gain_list: list[int] = field(default_factory=_default_gain_list)
    range_deg: float = 5.0
    interval_deg: float = 0.5
    direction: AngleScanDirection = "both"
    wait_after_move_ms: int = 1000
    motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM
    return_to_start: bool = False

    def __post_init__(self) -> None:
        validate_range(self.range_deg)
        validate_interval(self.interval_deg)
        validate_interval_within_range(self.range_deg, self.interval_deg)
        validate_direction(self.direction)
        _require_positive_motor_speed(self.motor_speed_rpm)
        _require_non_negative_wait_time(self.wait_after_move_ms)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AngleScanCaptureSettings:
        defaults = cls()

        return cls(
            exposure_ms_list=list(data.get("exposure_ms_list", defaults.exposure_ms_list)),
            gain_list=list(data.get("gain_list", defaults.gain_list)),
            range_deg=float(data.get("range_deg", defaults.range_deg)),
            interval_deg=float(data.get("interval_deg", defaults.interval_deg)),
            direction=cast(
                "AngleScanDirection",
                str(data.get("direction", defaults.direction)),
            ),
            wait_after_move_ms=int(
                data.get("wait_after_move_ms", defaults.wait_after_move_ms)
            ),
            motor_speed_rpm=float(data.get("motor_speed_rpm", defaults.motor_speed_rpm)),
            return_to_start=bool(data.get("return_to_start", defaults.return_to_start)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exposure_ms_list": self.exposure_ms_list,
            "gain_list": self.gain_list,
            "range_deg": self.range_deg,
            "interval_deg": self.interval_deg,
            "direction": self.direction,
            "wait_after_move_ms": self.wait_after_move_ms,
            "motor_speed_rpm": self.motor_speed_rpm,
            "return_to_start": self.return_to_start,
        }


@dataclass(frozen=True)
class MotorDeviceSettings:
    """モーター装置の通信条件と角度換算条件。"""

    port: str = DEFAULT_MOTOR_PORT
    slave: int = DEFAULT_MOTOR_SLAVE
    position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG

    def __post_init__(self) -> None:
        if self.position_units_per_deg <= 0:
            msg = "1degあたりのモーター位置単位は正の値にしてください。"
            raise ValueError(msg)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MotorDeviceSettings:
        return cls(
            port=str(data.get("port", DEFAULT_MOTOR_PORT)),
            slave=int(data.get("slave", DEFAULT_MOTOR_SLAVE)),
            position_units_per_deg=float(
                data.get("position_units_per_deg", DEFAULT_POSITION_UNITS_PER_DEG)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "slave": self.slave,
            "position_units_per_deg": self.position_units_per_deg,
        }


@dataclass(frozen=True)
class DeviceSettings:
    """アプリが扱う外部装置の設定。"""

    motor: MotorDeviceSettings = field(default_factory=MotorDeviceSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceSettings:
        return cls(motor=MotorDeviceSettings.from_dict(_as_mapping(data.get("motor"))))

    def to_dict(self) -> dict[str, Any]:
        return {"motor": self.motor.to_dict()}


@dataclass(frozen=True)
class StorageSettings:
    """保存先ディレクトリの設定。"""

    root_dir: str = ""


@dataclass(frozen=True)
class AppSettingsData:
    """settings.json全体のスキーマ。"""

    root_dir: str = ""
    preview: PreviewSettings = field(default_factory=PreviewSettings)
    sequence_capture: SequenceCaptureSettings = field(default_factory=SequenceCaptureSettings)
    angle_scan: AngleScanCaptureSettings = field(default_factory=AngleScanCaptureSettings)
    device: DeviceSettings = field(default_factory=DeviceSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettingsData:
        return cls(
            root_dir=str(data.get("root_dir", "")),
            preview=PreviewSettings.from_dict(data),
            sequence_capture=SequenceCaptureSettings.from_dict(
                _as_mapping(data.get("sequence_capture"))
            ),
            angle_scan=AngleScanCaptureSettings.from_dict(
                _as_mapping(data.get("angle_scan"))
            ),
            device=DeviceSettings.from_dict(_as_mapping(data.get("device"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_dir": self.root_dir,
            **self.preview.to_dict(),
            "sequence_capture": self.sequence_capture.to_dict(),
            "angle_scan": self.angle_scan.to_dict(),
            "device": self.device.to_dict(),
        }


class AppSettings:
    FILE_PATH = Path("settings.json")

    @classmethod
    def save(cls, settings: AppSettingsData) -> None:
        try:
            with cls.FILE_PATH.open("w", encoding="utf-8") as f:
                json.dump(settings.to_dict(), f, ensure_ascii=False, indent=4)
        except Exception:
            logger.exception("設定の保存に失敗しました")

    @classmethod
    def load(cls) -> AppSettingsData:
        if not cls.FILE_PATH.exists():
            return AppSettingsData()

        try:
            with cls.FILE_PATH.open(encoding="utf-8") as f:
                return AppSettingsData.from_dict(json.load(f))
        except Exception:
            logger.exception("設定の読み込みに失敗しました")
            return AppSettingsData()
