from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, cast

from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.domain.angle_scan.model import (
    AngleScanDirection,
    validate_direction,
    validate_interval,
    validate_interval_within_range,
    validate_range,
)
from rheed_capture.infrastructure.config.defaults import (
    DEFAULT_ANGLE_SCAN_DIRECTION,
    DEFAULT_ANGLE_SCAN_INTERVAL_DEG,
    DEFAULT_ANGLE_SCAN_RANGE_DEG,
    DEFAULT_ANGLE_SCAN_RETURN_TO_START,
    DEFAULT_ANGLE_SCAN_WAIT_AFTER_MOVE_MS,
    DEFAULT_EXPOSURE_MS_VALUES,
    DEFAULT_GAIN_VALUES,
    DEFAULT_MOTOR_DRIVER,
    DEFAULT_PREVIEW_CLAHE_ENABLED,
    DEFAULT_PREVIEW_EXPOSURE_MS,
    DEFAULT_PREVIEW_GAIN,
    DEFAULT_PREVIEW_GRID_COLS,
    DEFAULT_PREVIEW_GRID_ENABLED,
    DEFAULT_PREVIEW_GRID_ROWS,
)
from rheed_capture.infrastructure.config.migrations import migrate_settings_dict
from rheed_capture.infrastructure.motor.defaults import (
    DEFAULT_MOTOR_PORT,
    DEFAULT_MOTOR_SLAVE,
    DEFAULT_POSITION_UNITS_PER_DEG,
)


def _default_exposure_ms_list() -> list[float]:
    """Sequence/Angle Scanで共有する露光時間リストの既定値。"""
    return list(DEFAULT_EXPOSURE_MS_VALUES)


def _default_gain_list() -> list[int]:
    """Sequence/Angle Scanで共有するゲインリストの既定値。"""
    return list(DEFAULT_GAIN_VALUES)


def _as_mapping(value: object) -> dict[str, Any]:
    """JSON由来の任意値を、安全にdictとして扱うための正規化関数。"""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)

    return {}


def _require_non_negative_wait_time(wait_after_move_ms: int) -> None:
    """Angle Scanの移動後待機時間が負でないことを検証する。"""
    if wait_after_move_ms < 0:
        msg = "移動後待機時間は0以上にしてください。"
        raise ValueError(msg)


def _require_positive_motor_speed(motor_speed_rpm: float) -> None:
    """モータ速度が正の値であることを検証する。"""
    if motor_speed_rpm <= 0:
        msg = "モーター速度は正の値にしてください。"
        raise ValueError(msg)


@dataclass(frozen=True)
class PreviewSettings:
    """プレビュー表示と画像処理に関する設定モデル。"""

    exposure_ms: float = DEFAULT_PREVIEW_EXPOSURE_MS
    gain: int = DEFAULT_PREVIEW_GAIN
    enable_clahe: bool = DEFAULT_PREVIEW_CLAHE_ENABLED
    show_grid: bool = DEFAULT_PREVIEW_GRID_ENABLED
    grid_rows: int = DEFAULT_PREVIEW_GRID_ROWS
    grid_cols: int = DEFAULT_PREVIEW_GRID_COLS

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreviewSettings:
        """schema_version=1形式のdictからPreview設定を復元する。"""
        preview = _as_mapping(data.get("preview"))
        clahe = _as_mapping(preview.get("clahe"))
        grid = _as_mapping(preview.get("grid"))
        defaults = cls()

        return cls(
            exposure_ms=float(preview.get("exposure_ms", defaults.exposure_ms)),
            gain=int(preview.get("gain", defaults.gain)),
            enable_clahe=bool(clahe.get("enabled", defaults.enable_clahe)),
            show_grid=bool(grid.get("enabled", defaults.show_grid)),
            grid_rows=int(grid.get("rows", defaults.grid_rows)),
            grid_cols=int(grid.get("cols", defaults.grid_cols)),
        )

    def with_grid(self, grid: PreviewGridSettings) -> PreviewSettings:
        """Panel側で保持するGrid設定をPreview設定へ合成する。"""
        return replace(
            self,
            show_grid=grid.show_grid,
            grid_rows=grid.rows,
            grid_cols=grid.cols,
        )

    def to_dict(self) -> dict[str, Any]:
        """settings.jsonへ保存する新schema形式へ変換する。"""
        return {
            "exposure_ms": self.exposure_ms,
            "gain": self.gain,
            "clahe": {"enabled": self.enable_clahe},
            "grid": {
                "enabled": self.show_grid,
                "rows": self.grid_rows,
                "cols": self.grid_cols,
            },
        }


@dataclass(frozen=True)
class PreviewGridSettings:
    """ImageViewer側のGrid描画状態を保存用に受け渡す小さな値オブジェクト。"""

    show_grid: bool = False
    rows: int = 4
    cols: int = 4


@dataclass(frozen=True)
class SequenceCaptureSettings:
    """通常Sequence撮影の条件リスト設定。"""

    exposure_ms_list: list[float] = field(default_factory=_default_exposure_ms_list)
    gain_list: list[int] = field(default_factory=_default_gain_list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceCaptureSettings:
        """dictからSequence撮影設定を復元し、不足値は既定値で補う。"""
        defaults = cls()
        return cls(
            exposure_ms_list=list(data.get("exposure_ms_list", defaults.exposure_ms_list)),
            gain_list=list(data.get("gain_list", defaults.gain_list)),
        )

    def to_dict(self) -> dict[str, Any]:
        """settings.jsonへ保存するSequence設定dictへ変換する。"""
        return {
            "exposure_ms_list": self.exposure_ms_list,
            "gain_list": self.gain_list,
        }


@dataclass(frozen=True)
class AngleScanCaptureSettings:
    """Angle Scan撮影の条件、走査範囲、モータ動作に関する設定。"""

    exposure_ms_list: list[float] = field(default_factory=_default_exposure_ms_list)
    gain_list: list[int] = field(default_factory=_default_gain_list)
    range_deg: float = DEFAULT_ANGLE_SCAN_RANGE_DEG
    interval_deg: float = DEFAULT_ANGLE_SCAN_INTERVAL_DEG
    direction: AngleScanDirection = DEFAULT_ANGLE_SCAN_DIRECTION
    wait_after_move_ms: int = DEFAULT_ANGLE_SCAN_WAIT_AFTER_MOVE_MS
    motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM
    return_to_start: bool = DEFAULT_ANGLE_SCAN_RETURN_TO_START

    def __post_init__(self) -> None:
        """Domain側の角度制約とモータ設定制約を検証する。"""
        validate_range(self.range_deg)
        validate_interval(self.interval_deg)
        validate_interval_within_range(self.range_deg, self.interval_deg)
        validate_direction(self.direction)
        _require_positive_motor_speed(self.motor_speed_rpm)
        _require_non_negative_wait_time(self.wait_after_move_ms)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AngleScanCaptureSettings:
        """dictからAngle Scan設定を復元し、不足値は既定値で補う。"""
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
            wait_after_move_ms=int(data.get("wait_after_move_ms", defaults.wait_after_move_ms)),
            motor_speed_rpm=float(data.get("motor_speed_rpm", defaults.motor_speed_rpm)),
            return_to_start=bool(data.get("return_to_start", defaults.return_to_start)),
        )

    def to_dict(self) -> dict[str, Any]:
        """settings.jsonへ保存するAngle Scan設定dictへ変換する。"""
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
    """AZD-CDモータ接続と角度換算キャリブレーションの設定。"""

    port: str = DEFAULT_MOTOR_PORT
    slave: int = DEFAULT_MOTOR_SLAVE
    position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG
    driver: str = DEFAULT_MOTOR_DRIVER

    def __post_init__(self) -> None:
        """角度からモータ位置単位へ変換する係数を検証する。"""
        if self.position_units_per_deg <= 0:
            msg = "1degあたりのモーター位置単位は正の値にしてください。"
            raise ValueError(msg)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MotorDeviceSettings:
        """新schemaのdevice.motor dictからモータ設定を復元する。"""
        connection = _as_mapping(data.get("connection"))
        calibration = _as_mapping(data.get("calibration"))

        return cls(
            port=str(connection.get("port", DEFAULT_MOTOR_PORT)),
            slave=int(connection.get("slave_id", DEFAULT_MOTOR_SLAVE)),
            position_units_per_deg=float(
                calibration.get("position_units_per_deg", DEFAULT_POSITION_UNITS_PER_DEG)
            ),
            driver=str(data.get("driver", DEFAULT_MOTOR_DRIVER)),
        )

    def to_dict(self) -> dict[str, Any]:
        """settings.jsonへ保存するdevice.motor dictへ変換する。"""
        return {
            "driver": self.driver,
            "connection": {
                "type": "serial",
                "port": self.port,
                "slave_id": self.slave,
            },
            "calibration": {
                "position_units_per_deg": self.position_units_per_deg,
            },
        }


@dataclass(frozen=True)
class DeviceSettings:
    """外部装置設定をまとめるルート設定モデル。"""

    motor: MotorDeviceSettings = field(default_factory=MotorDeviceSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceSettings:
        """device dictから外部装置設定を復元する。"""
        return cls(motor=MotorDeviceSettings.from_dict(_as_mapping(data.get("motor"))))

    def to_dict(self) -> dict[str, Any]:
        """settings.jsonへ保存するdevice dictへ変換する。"""
        return {"motor": self.motor.to_dict()}


@dataclass(frozen=True)
class StorageSettings:
    """保存先UIが扱うroot directory設定。"""

    root_dir: str = ""


@dataclass(frozen=True)
class AppSettingsData:
    """アプリ全体の設定を束ね、旧形式移行と新形式保存を担当するモデル。"""

    root_dir: str = ""
    preview: PreviewSettings = field(default_factory=PreviewSettings)
    sequence_capture: SequenceCaptureSettings = field(default_factory=SequenceCaptureSettings)
    angle_scan: AngleScanCaptureSettings = field(default_factory=AngleScanCaptureSettings)
    device: DeviceSettings = field(default_factory=DeviceSettings)
    schema_version: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettingsData:
        """旧形式を必要に応じて移行し、AppSettingsDataへ復元する。"""
        migrated = migrate_settings_dict(data)
        output = _as_mapping(migrated.get("output"))

        return cls(
            root_dir=str(output.get("root_dir", "")),
            preview=PreviewSettings.from_dict(migrated),
            sequence_capture=SequenceCaptureSettings.from_dict(
                _as_mapping(migrated.get("sequence_capture"))
            ),
            angle_scan=AngleScanCaptureSettings.from_dict(
                _as_mapping(migrated.get("angle_scan"))
            ),
            device=DeviceSettings.from_dict(_as_mapping(migrated.get("device"))),
            schema_version=1,
        )

    def to_dict(self) -> dict[str, Any]:
        """settings.jsonへ保存するschema_version=1形式へ変換する。"""
        return {
            "schema_version": self.schema_version,
            "output": {"root_dir": self.root_dir},
            "preview": self.preview.to_dict(),
            "sequence_capture": self.sequence_capture.to_dict(),
            "angle_scan": self.angle_scan.to_dict(),
            "device": self.device.to_dict(),
        }
