from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, Self

if TYPE_CHECKING:
    from types import TracebackType

    import numpy as np


class CameraError(RuntimeError):
    """カメラ操作または状態遷移の失敗を表す。"""


type TriggerMode = Literal["software", "hardware"]
type FrameReadbackSource = Literal["camera", "host", "simulation"]

SENSOR_BIT_DEPTH_8 = 8
SENSOR_BIT_DEPTH_12 = 12
SAVED_BIT_DEPTH_8 = 8
SAVED_BIT_DEPTH_12 = 16


@dataclass(frozen=True)
class ImageFormatSnapshot:
    """1つの撮影Sessionで確定した画像形式と保存形式を保持する。"""

    bit_depth_sensor: int
    bit_depth_saved: int
    pixel_format: str
    alignment: str | None

    def __post_init__(self) -> None:
        """センサbit depthと保存形式の対応を検証する。"""
        if (
            isinstance(self.bit_depth_sensor, bool)
            or not isinstance(self.bit_depth_sensor, int)
            or self.bit_depth_sensor not in (SENSOR_BIT_DEPTH_8, SENSOR_BIT_DEPTH_12)
        ):
            msg = "bit_depth_sensor must be 8 or 12."
            raise ValueError(msg)
        if not isinstance(self.pixel_format, str) or not self.pixel_format:
            msg = "pixel_format must be a non-empty string."
            raise ValueError(msg)

        expected_saved_depth = (
            SAVED_BIT_DEPTH_8
            if self.bit_depth_sensor == SENSOR_BIT_DEPTH_8
            else SAVED_BIT_DEPTH_12
        )
        expected_alignment = (
            None if self.bit_depth_sensor == SENSOR_BIT_DEPTH_8 else "MsbAligned"
        )
        expected_pixel_formats = (
            ("Mono8",)
            if self.bit_depth_sensor == SENSOR_BIT_DEPTH_8
            else ("Mono12", "Mono12Packed")
        )
        if self.bit_depth_saved != expected_saved_depth:
            msg = "bit_depth_saved does not match bit_depth_sensor."
            raise ValueError(msg)
        if self.alignment != expected_alignment:
            msg = "alignment does not match bit_depth_sensor."
            raise ValueError(msg)
        if self.pixel_format not in expected_pixel_formats:
            msg = f"pixel_format does not match bit_depth_sensor: {self.pixel_format}"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, int | str | None]:
        """保存用のimage_format辞書へ変換する。"""
        return {
            "bit_depth_sensor": self.bit_depth_sensor,
            "bit_depth_saved": self.bit_depth_saved,
            "pixel_format": self.pixel_format,
            "alignment": self.alignment,
        }


@dataclass(frozen=True)
class TriggerSettings:
    """1取得Sessionへ適用するtriggerとcamera FPS設定を保持する。"""

    mode: TriggerMode
    hardware_source: str
    hardware_activation: str
    hardware_delay_us: float
    fps_limit: float | None
    sensor_bit_depth: int = 12

    def __post_init__(self) -> None:
        """共通設定の数値制約をSession開始前に検証する。"""
        if self.mode not in ("software", "hardware"):
            msg = "Trigger modeはsoftwareまたはhardwareにしてください。"
            raise ValueError(msg)
        if not isinstance(self.hardware_source, str) or not self.hardware_source.strip():
            msg = "Hardware trigger sourceは空にできません。"
            raise ValueError(msg)
        if not isinstance(self.hardware_activation, str) or not self.hardware_activation.strip():
            msg = "Hardware trigger activationは空にできません。"
            raise ValueError(msg)
        if (
            isinstance(self.hardware_delay_us, bool)
            or not isinstance(self.hardware_delay_us, (int, float))
            or not math.isfinite(self.hardware_delay_us)
            or self.hardware_delay_us < 0
        ):
            msg = "Hardware trigger delayは0以上にしてください。"
            raise ValueError(msg)
        if self.fps_limit is not None and (
            isinstance(self.fps_limit, bool)
            or not isinstance(self.fps_limit, (int, float))
            or not math.isfinite(self.fps_limit)
            or self.fps_limit <= 0
        ):
            msg = "FPS Limitは正の値またはUnlimitedにしてください。"
            raise ValueError(msg)
        if (
            isinstance(self.sensor_bit_depth, bool)
            or not isinstance(self.sensor_bit_depth, int)
            or self.sensor_bit_depth not in (SENSOR_BIT_DEPTH_8, SENSOR_BIT_DEPTH_12)
        ):
            msg = "Sensor bit depthは8または12の整数にしてください。"
            raise ValueError(msg)


DEFAULT_TRIGGER_SETTINGS = TriggerSettings(
    mode="software",
    hardware_source="Line1",
    hardware_activation="RisingEdge",
    hardware_delay_us=0.0,
    fps_limit=None,
)


@dataclass(frozen=True)
class FrameReadback:
    """取得フレームに対応する撮影設定とcamera timestampを保持する。"""

    exposure_ms: float
    gain: int
    camera_timestamp_ticks: int
    camera_timestamp_frequency_hz: int
    source: FrameReadbackSource


@dataclass(frozen=True)
class CameraFrame:
    """Raw画像と、そのフレームに対応する読戻し情報を保持する。"""

    image: np.ndarray
    readback: FrameReadback
    image_format: ImageFormatSnapshot


class TriggerCaptureSession(Protocol):
    """Trigger取得中だけカメラを所有するセッション。"""

    def wait_until_ready(self, timeout_ms: int) -> None:
        """指定時間内にFrameStartトリガー受付可能になるまで待つ。"""
        ...

    def execute_software_trigger(self) -> None:
        """Software modeでFrameStartトリガーを1回発行する。"""
        ...

    def retrieve_frame(self, timeout_ms: int) -> CameraFrame:
        """発行済みトリガーに対応する1フレームを取得する。"""
        ...

    def close(self) -> None:
        """取得を停止してトリガー設定を解除する。"""
        ...

    def __enter__(self) -> Self:
        """開始済みセッションを返す。"""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """例外の有無にかかわらずセッションを閉じる。"""
        ...


class Camera(Protocol):
    """Application層が利用する保存撮影用カメラPort。"""

    def set_exposure(self, exposure_ms: float) -> None:
        """露光時間をミリ秒単位で設定する。"""
        ...

    def set_gain(self, gain: int) -> None:
        """カメラゲインを設定する。"""
        ...

    def configure_image_format(self, sensor_bit_depth: int) -> ImageFormatSnapshot:
        """IDLE状態で画像転送形式とconverterを設定し、readback済みsnapshotを返す。"""
        ...

    def start_trigger_session(
        self,
        *,
        settings: TriggerSettings,
        expected_frames: int | None,
    ) -> TriggerCaptureSession:
        """IDLE状態から指定modeのtrigger取得セッションを開始する。"""
        ...
