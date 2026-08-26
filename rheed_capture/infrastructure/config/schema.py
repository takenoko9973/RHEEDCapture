from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import isfinite
from typing import Any, Literal, cast

from rheed_capture.application.ports.camera import TriggerSettings
from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.domain.angle_scan.model import (
    AngleScanDirection,
    validate_direction,
    validate_interval,
    validate_interval_within_range,
    validate_range,
)
from rheed_capture.infrastructure.config.defaults import (
    ACQUISITION_HARDWARE_ACTIVATIONS,
    ACQUISITION_HARDWARE_SOURCES,
    DEFAULT_ACQUISITION_ACCUMULATION_ENABLED,
    DEFAULT_ACQUISITION_ACCUMULATION_FRAMES,
    DEFAULT_ACQUISITION_FPS_LIMIT,
    DEFAULT_ACQUISITION_HARDWARE_ACTIVATION,
    DEFAULT_ACQUISITION_HARDWARE_DELAY_US,
    DEFAULT_ACQUISITION_HARDWARE_SOURCE,
    DEFAULT_ACQUISITION_MODE,
    DEFAULT_ACQUISITION_TRIGGER_WAIT_TIMEOUT_SEC,
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
    DEFAULT_RECORDING_TIFF_COMPRESSION_ENABLED,
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


def _optional_section(data: dict[str, Any], key: str) -> dict[str, Any] | None:
    """存在すればdictとして返し、欠落時だけNoneを返す。"""
    value = data.get(key)
    if value is None:
        return None

    if isinstance(value, dict):
        return cast("dict[str, Any]", value)

    msg = f"settings section must be an object: {key}"
    raise ValueError(msg)


def _require_non_negative_wait_time(wait_after_move_ms: int) -> None:
    """Angle Scanの移動後待機時間が0以上であることを検証する。"""
    if wait_after_move_ms < 0:
        msg = "移動後待機時間は0以上にしてください。"
        raise ValueError(msg)


def _require_positive_motor_speed(motor_speed_rpm: float) -> None:
    """Angle Scanのモーター速度が正であることを検証する。"""
    if motor_speed_rpm <= 0:
        msg = "モーター速度は正の値にしてください。"
        raise ValueError(msg)


def _require_bool(value: object, field_name: str) -> bool:
    """設定値がJSON booleanであることを検証して返す。"""
    if not isinstance(value, bool):
        msg = f"{field_name} must be a boolean."
        raise ValueError(msg)  # noqa: TRY004
    return value


def filter_existing_float_values(
    selected_values: list[float],
    valid_values: set[float],
) -> list[float]:
    """候補リストから消えた露光時間を選択状態から除外する。"""
    return [value for value in selected_values if value in valid_values]


def filter_existing_int_values(selected_values: list[int], valid_values: set[int]) -> list[int]:
    """候補リストから消えたゲインを選択状態から除外する。"""
    return [value for value in selected_values if value in valid_values]


AcquisitionMode = Literal["software", "hardware"]
AcquisitionHardwareSource = Literal["Line1", "Line3", "Action1"]
AcquisitionHardwareActivation = Literal["RisingEdge", "FallingEdge"]


def _require_finite_number(value: object, field_name: str) -> float:
    """設定値を有限な数値へ変換し、型不一致を明示的に拒否する。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{field_name} must be a number."
        raise ValueError(msg)  # noqa: TRY004

    converted = float(value)
    if not isfinite(converted):
        msg = f"{field_name} must be finite."
        raise ValueError(msg)

    return converted


def _require_non_negative_number(value: object, field_name: str) -> float:
    """有限な0以上の数値を検証する。"""
    converted = _require_finite_number(value, field_name)
    if converted < 0:
        msg = f"{field_name} must be >= 0."
        raise ValueError(msg)

    return converted


@dataclass(frozen=True)
class AcquisitionSettings:
    """Previewと保存撮影で共有するTrigger取得設定。"""

    mode: AcquisitionMode = DEFAULT_ACQUISITION_MODE
    hardware_source: AcquisitionHardwareSource = DEFAULT_ACQUISITION_HARDWARE_SOURCE
    hardware_activation: AcquisitionHardwareActivation = DEFAULT_ACQUISITION_HARDWARE_ACTIVATION
    hardware_delay_us: float = DEFAULT_ACQUISITION_HARDWARE_DELAY_US
    fps_limit: float | None = DEFAULT_ACQUISITION_FPS_LIMIT
    accumulation_enabled: bool = DEFAULT_ACQUISITION_ACCUMULATION_ENABLED
    accumulation_frames: int = DEFAULT_ACQUISITION_ACCUMULATION_FRAMES
    trigger_wait_timeout_sec: float = DEFAULT_ACQUISITION_TRIGGER_WAIT_TIMEOUT_SEC

    def __post_init__(self) -> None:
        """共有取得設定の列挙値と数値制約を検証する。"""
        if self.mode not in ("software", "hardware"):
            msg = f"Unknown acquisition mode: {self.mode}"
            raise ValueError(msg)
        if self.hardware_source not in ACQUISITION_HARDWARE_SOURCES:
            msg = f"Unknown hardware_source: {self.hardware_source}"
            raise ValueError(msg)
        if self.hardware_activation not in ACQUISITION_HARDWARE_ACTIVATIONS:
            msg = f"Unknown hardware_activation: {self.hardware_activation}"
            raise ValueError(msg)

        _require_non_negative_number(self.hardware_delay_us, "hardware_delay_us")
        if self.fps_limit is not None:
            fps_limit = _require_finite_number(self.fps_limit, "fps_limit")
            if fps_limit <= 0:
                msg = "fps_limit must be > 0 or None."
                raise ValueError(msg)
        if not isinstance(self.accumulation_enabled, bool):
            msg = "accumulation_enabled must be a boolean."
            raise ValueError(msg)  # noqa: TRY004
        if (
            isinstance(self.accumulation_frames, bool)
            or not isinstance(self.accumulation_frames, int)
            or self.accumulation_frames <= 0
        ):
            msg = "accumulation_frames must be a positive integer."
            raise ValueError(msg)
        _require_non_negative_number(
            self.trigger_wait_timeout_sec,
            "trigger_wait_timeout_sec",
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AcquisitionSettings:
        """settings.jsonのacquisitionセクションから設定を作る。"""
        defaults = cls()
        mode = data.get("mode", defaults.mode)
        hardware_source = data.get("hardware_source", defaults.hardware_source)
        hardware_activation = data.get("hardware_activation", defaults.hardware_activation)
        hardware_delay_us = _require_non_negative_number(
            data.get("hardware_delay_us", defaults.hardware_delay_us),
            "hardware_delay_us",
        )
        fps_value = data.get("fps_limit", defaults.fps_limit)
        fps_limit = (
            None
            if fps_value is None
            else _require_finite_number(fps_value, "fps_limit")
        )
        accumulation_enabled = data.get(
            "accumulation_enabled",
            defaults.accumulation_enabled,
        )
        accumulation_frames = data.get(
            "accumulation_frames",
            defaults.accumulation_frames,
        )
        trigger_wait_timeout_sec = _require_non_negative_number(
            data.get(
                "trigger_wait_timeout_sec",
                defaults.trigger_wait_timeout_sec,
            ),
            "trigger_wait_timeout_sec",
        )

        return cls(
            mode=cast("AcquisitionMode", mode),
            hardware_source=cast("AcquisitionHardwareSource", hardware_source),
            hardware_activation=cast("AcquisitionHardwareActivation", hardware_activation),
            hardware_delay_us=hardware_delay_us,
            fps_limit=fps_limit,
            accumulation_enabled=accumulation_enabled,
            accumulation_frames=accumulation_frames,
            trigger_wait_timeout_sec=trigger_wait_timeout_sec,
        )

    def to_dict(self) -> dict[str, Any]:
        """AcquisitionSettingsをsettings.json保存用dictへ変換する。"""
        return {
            "mode": self.mode,
            "hardware_source": self.hardware_source,
            "hardware_activation": self.hardware_activation,
            "hardware_delay_us": self.hardware_delay_us,
            "fps_limit": self.fps_limit,
            "accumulation_enabled": self.accumulation_enabled,
            "accumulation_frames": self.accumulation_frames,
            "trigger_wait_timeout_sec": self.trigger_wait_timeout_sec,
        }

    def to_trigger_settings(self) -> TriggerSettings:
        """Task1のCamera Portへ渡すTrigger設定へ変換する。"""
        return TriggerSettings(
            mode=self.mode,
            hardware_source=self.hardware_source,
            hardware_activation=self.hardware_activation,
            hardware_delay_us=self.hardware_delay_us,
            fps_limit=self.fps_limit,
        )


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
        """settings.jsonのpreviewセクションからPreviewSettingsを作る。"""
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
        """ImageViewer由来のGrid設定を反映したPreviewSettingsを返す。"""
        return replace(
            self,
            show_grid=grid.show_grid,
            grid_rows=grid.rows,
            grid_cols=grid.cols,
        )

    def to_dict(self) -> dict[str, Any]:
        """PreviewSettingsをsettings.json保存用dictへ変換する。"""
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
        """settings.jsonのsequence_captureセクションから設定を作る。"""
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
        """SequenceCaptureSettingsをsettings.json保存用dictへ変換する。"""
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
        """Angle Scan撮影条件の入力制約を検証する。"""
        validate_range(self.range_deg)
        validate_interval(self.interval_deg)
        validate_interval_within_range(self.range_deg, self.interval_deg)
        validate_direction(self.direction)
        _require_positive_motor_speed(self.motor_speed_rpm)
        _require_non_negative_wait_time(self.wait_after_move_ms)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AngleScanCaptureSettings:
        """settings.jsonのangle_scanセクションから設定を作る。"""
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
        """AngleScanCaptureSettingsをsettings.json保存用dictへ変換する。"""
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


RecordingRateMode = Literal["fps", "interval"]


@dataclass(frozen=True)
class RecordingCaptureSettings:
    """Recording撮影の単一条件とレート入力状態。"""

    exposure_ms: float = DEFAULT_PREVIEW_EXPOSURE_MS
    gain: int = DEFAULT_PREVIEW_GAIN
    rate_mode: RecordingRateMode = "interval"
    fps: float = 10.0
    interval_ms: float = 100.0
    duration_sec: float = 0.0
    tiff_compression_enabled: bool = DEFAULT_RECORDING_TIFF_COMPRESSION_ENABLED

    def __post_init__(self) -> None:
        """Recordingのrate_modeが既知の入力モードであることを検証する。"""
        if self.rate_mode not in ("fps", "interval"):
            msg = "Recording rate_mode must be 'fps' or 'interval'."
            raise ValueError(msg)
        _require_bool(self.tiff_compression_enabled, "tiff_compression_enabled")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingCaptureSettings:
        """settings.jsonのrecording_captureセクションから設定を作る。"""
        return cls(
            exposure_ms=float(data["exposure_ms"]),
            gain=int(data["gain"]),
            rate_mode=cast("RecordingRateMode", str(data["rate_mode"])),
            fps=float(data["fps"]),
            interval_ms=float(data["interval_ms"]),
            duration_sec=float(data["duration_sec"]),
            tiff_compression_enabled=_require_bool(
                data.get(
                    "tiff_compression_enabled",
                    DEFAULT_RECORDING_TIFF_COMPRESSION_ENABLED,
                ),
                "tiff_compression_enabled",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """RecordingCaptureSettingsをsettings.json保存用dictへ変換する。"""
        return {
            "exposure_ms": self.exposure_ms,
            "gain": self.gain,
            "rate_mode": self.rate_mode,
            "fps": self.fps,
            "interval_ms": self.interval_ms,
            "duration_sec": self.duration_sec,
            "tiff_compression_enabled": self.tiff_compression_enabled,
        }


@dataclass(frozen=True)
class MotorDeviceSettings:
    """AZD-CDモータ接続と角度換算キャリブレーションの設定。"""

    port: str = DEFAULT_MOTOR_PORT
    slave: int = DEFAULT_MOTOR_SLAVE
    position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG
    driver: str = DEFAULT_MOTOR_DRIVER

    def __post_init__(self) -> None:
        """モーター角度換算係数が正であることを検証する。"""
        if self.position_units_per_deg <= 0:
            msg = "1degあたりのモーター位置単位は正の値にしてください。"
            raise ValueError(msg)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MotorDeviceSettings:
        """settings.jsonのdevice.motorセクションから設定を作る。"""
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
        """MotorDeviceSettingsをsettings.json保存用dictへ変換する。"""
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
        """settings.jsonのdeviceセクションからDeviceSettingsを作る。"""
        return cls(motor=MotorDeviceSettings.from_dict(_as_mapping(data.get("motor"))))

    def to_dict(self) -> dict[str, Any]:
        """DeviceSettingsをsettings.json保存用dictへ変換する。"""
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
    acquisition: AcquisitionSettings = field(default_factory=AcquisitionSettings)
    sequence_capture: SequenceCaptureSettings = field(default_factory=SequenceCaptureSettings)
    angle_scan: AngleScanCaptureSettings = field(default_factory=AngleScanCaptureSettings)
    recording_capture: RecordingCaptureSettings = field(
        default_factory=RecordingCaptureSettings
    )
    device: DeviceSettings = field(default_factory=DeviceSettings)
    schema_version: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettingsData:
        """settings.jsonのdictからAppSettingsDataを作る。"""
        return AppSettingsParser(data).parse()

    def to_dict(self) -> dict[str, Any]:
        """AppSettingsDataをsettings.json保存用dictへ変換する。"""
        return {
            "schema_version": self.schema_version,
            "output": {"root_dir": self.root_dir},
            "exposure_ms_values": self.exposure_ms_values,
            "gain_values": self.gain_values,
            "preview": self.preview.to_dict(),
            "acquisition": self.acquisition.to_dict(),
            "sequence_capture": self.sequence_capture.to_dict(),
            "angle_scan": self.angle_scan.to_dict(),
            "recording_capture": self.recording_capture.to_dict(),
            "device": self.device.to_dict(),
        }


class AppSettingsParser:
    """settings.jsonのdictを設定モデルへ変換する境界。"""

    def __init__(self, data: dict[str, Any]) -> None:
        """parse対象のsettings.json由来dictを保持する。"""
        self.data = data

    def parse(self) -> AppSettingsData:
        """settings.json由来dictをAppSettingsDataへ変換する。"""
        output = _as_mapping(self.data.get("output"))
        exposure_ms_values = [
            float(value)
            for value in list(
                self.data.get("exposure_ms_values", _default_exposure_ms_values())
            )
        ]
        gain_values = [
            int(value) for value in list(self.data.get("gain_values", _default_gain_values()))
        ]
        sequence_capture = SequenceCaptureSettings.from_dict(
            _as_mapping(self.data.get("sequence_capture"))
        )
        angle_scan = AngleScanCaptureSettings.from_dict(_as_mapping(self.data.get("angle_scan")))
        acquisition = self._parse_acquisition()
        recording_capture = self._parse_recording_capture()
        exposure_set = set(exposure_ms_values)
        gain_set = set(gain_values)

        return AppSettingsData(
            root_dir=str(output.get("root_dir", "")),
            exposure_ms_values=exposure_ms_values,
            gain_values=gain_values,
            preview=PreviewSettings.from_dict(self.data),
            acquisition=acquisition,
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
            recording_capture=recording_capture,
            device=DeviceSettings.from_dict(_as_mapping(self.data.get("device"))),
            schema_version=1,
        )

    def _parse_recording_capture(self) -> RecordingCaptureSettings:
        """Recording設定を読み込み、未作成セクションだけ既定値で補う。"""
        section = _optional_section(self.data, "recording_capture")
        if section is None:
            # 録画機能追加直後の設定欠落だけを局所的に補い、他セクションは保持する。
            return RecordingCaptureSettings()

        return RecordingCaptureSettings.from_dict(section)

    def _parse_acquisition(self) -> AcquisitionSettings:
        """Acquisition設定を読み込み、セクション欠落時だけ既定値で補う。"""
        if "acquisition" not in self.data:
            return AcquisitionSettings()

        section = self.data["acquisition"]
        if not isinstance(section, dict):
            msg = "settings section must be an object: acquisition"
            raise ValueError(msg)  # noqa: TRY004

        return AcquisitionSettings.from_dict(cast("dict[str, Any]", section))
