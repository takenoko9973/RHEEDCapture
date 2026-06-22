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
from rheed_capture.infrastructure.motor.defaults import (
    DEFAULT_MOTOR_PORT,
    DEFAULT_MOTOR_SLAVE,
    DEFAULT_POSITION_UNITS_PER_DEG,
)


def _default_exposure_ms_values() -> list[float]:
    """Settings画面の露光時間候補リストの既定値。"""
    return list(DEFAULT_EXPOSURE_MS_VALUES)


def _default_gain_values() -> list[int]:
    """Settings画面のゲイン候補リストの既定値。"""
    return list(DEFAULT_GAIN_VALUES)


def _as_mapping(value: object) -> dict[str, Any]:
    """JSON由来の任意値をdictとして安全に扱うための正規化。"""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)

    return {}


def _require_non_negative_wait_time(wait_after_move_ms: int) -> None:
    if wait_after_move_ms < 0:
        msg = "移動後待機時間は0以上にしてください。"
        raise ValueError(msg)


def _require_positive_motor_speed(motor_speed_rpm: float) -> None:
    if motor_speed_rpm <= 0:
        msg = "モーター速度は正の値にしてください。"
        raise ValueError(msg)


def filter_existing_float_values(
    selected_values: list[float],
    valid_values: set[float],
) -> list[float]:
    """候補リストから消えた露光時間を選択状態から除外する。"""
    return [value for value in selected_values if value in valid_values]


def filter_existing_int_values(selected_values: list[int], valid_values: set[int]) -> list[int]:
    """候補リストから消えたゲインを選択状態から除外する。"""
    return [value for value in selected_values if value in valid_values]


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
        return replace(
            self,
            show_grid=grid.show_grid,
            grid_rows=grid.rows,
            grid_cols=grid.cols,
        )

    def to_dict(self) -> dict[str, Any]:
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
    """通常Sequence撮影で使う候補値の選択状態。"""

    selected_exposure_ms_values: list[float] = field(default_factory=_default_exposure_ms_values)
    selected_gain_values: list[int] = field(default_factory=_default_gain_values)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SequenceCaptureSettings:
        defaults = cls()
        return cls(
            selected_exposure_ms_values=[
                float(value)
                for value in list(
                    data.get(
                        "selected_exposure_ms_values",
                        defaults.selected_exposure_ms_values,
                    )
                )
            ],
            selected_gain_values=[
                int(value)
                for value in list(data.get("selected_gain_values", defaults.selected_gain_values))
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_exposure_ms_values": self.selected_exposure_ms_values,
            "selected_gain_values": self.selected_gain_values,
        }


@dataclass(frozen=True)
class AngleScanCaptureSettings:
    """Angle Scan撮影の条件、走査範囲、モータ動作に関する設定。"""

    selected_exposure_ms_values: list[float] = field(default_factory=_default_exposure_ms_values)
    selected_gain_values: list[int] = field(default_factory=_default_gain_values)
    range_deg: float = DEFAULT_ANGLE_SCAN_RANGE_DEG
    interval_deg: float = DEFAULT_ANGLE_SCAN_INTERVAL_DEG
    direction: AngleScanDirection = DEFAULT_ANGLE_SCAN_DIRECTION
    wait_after_move_ms: int = DEFAULT_ANGLE_SCAN_WAIT_AFTER_MOVE_MS
    motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM
    return_to_start: bool = DEFAULT_ANGLE_SCAN_RETURN_TO_START

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
            selected_exposure_ms_values=[
                float(value)
                for value in list(
                    data.get(
                        "selected_exposure_ms_values",
                        defaults.selected_exposure_ms_values,
                    )
                )
            ],
            selected_gain_values=[
                int(value)
                for value in list(data.get("selected_gain_values", defaults.selected_gain_values))
            ],
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
        return {
            "selected_exposure_ms_values": self.selected_exposure_ms_values,
            "selected_gain_values": self.selected_gain_values,
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
        if self.position_units_per_deg <= 0:
            msg = "1degあたりのモーター位置単位は正の値にしてください。"
            raise ValueError(msg)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MotorDeviceSettings:
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
        return cls(motor=MotorDeviceSettings.from_dict(_as_mapping(data.get("motor"))))

    def to_dict(self) -> dict[str, Any]:
        return {"motor": self.motor.to_dict()}


@dataclass(frozen=True)
class StorageSettings:
    """保存先UIが扱うroot directory設定。"""

    root_dir: str = ""


@dataclass(frozen=True)
class AppSettingsData:
    """アプリ全体の設定を束ねるモデル。"""

    root_dir: str = ""
    exposure_ms_values: list[float] = field(default_factory=_default_exposure_ms_values)
    gain_values: list[int] = field(default_factory=_default_gain_values)
    preview: PreviewSettings = field(default_factory=PreviewSettings)
    sequence_capture: SequenceCaptureSettings = field(default_factory=SequenceCaptureSettings)
    angle_scan: AngleScanCaptureSettings = field(default_factory=AngleScanCaptureSettings)
    device: DeviceSettings = field(default_factory=DeviceSettings)
    schema_version: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettingsData:
        output = _as_mapping(data.get("output"))
        exposure_ms_values = [
            float(value)
            for value in list(data.get("exposure_ms_values", _default_exposure_ms_values()))
        ]
        gain_values = [
            int(value) for value in list(data.get("gain_values", _default_gain_values()))
        ]
        sequence_capture = SequenceCaptureSettings.from_dict(
            _as_mapping(data.get("sequence_capture"))
        )
        angle_scan = AngleScanCaptureSettings.from_dict(_as_mapping(data.get("angle_scan")))
        exposure_set = set(exposure_ms_values)
        gain_set = set(gain_values)

        # 候補から削除された値は選択状態から取り除く。
        return cls(
            root_dir=str(output.get("root_dir", "")),
            exposure_ms_values=exposure_ms_values,
            gain_values=gain_values,
            preview=PreviewSettings.from_dict(data),
            sequence_capture=replace(
                sequence_capture,
                selected_exposure_ms_values=filter_existing_float_values(
                    sequence_capture.selected_exposure_ms_values,
                    exposure_set,
                ),
                selected_gain_values=filter_existing_int_values(
                    sequence_capture.selected_gain_values,
                    gain_set,
                ),
            ),
            angle_scan=replace(
                angle_scan,
                selected_exposure_ms_values=filter_existing_float_values(
                    angle_scan.selected_exposure_ms_values,
                    exposure_set,
                ),
                selected_gain_values=filter_existing_int_values(
                    angle_scan.selected_gain_values,
                    gain_set,
                ),
            ),
            device=DeviceSettings.from_dict(_as_mapping(data.get("device"))),
            schema_version=1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "output": {"root_dir": self.root_dir},
            "exposure_ms_values": self.exposure_ms_values,
            "gain_values": self.gain_values,
            "preview": self.preview.to_dict(),
            "sequence_capture": self.sequence_capture.to_dict(),
            "angle_scan": self.angle_scan.to_dict(),
            "device": self.device.to_dict(),
        }
