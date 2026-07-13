from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, Self

if TYPE_CHECKING:
    from types import TracebackType

    import numpy as np


class CameraError(RuntimeError):
    """カメラ操作または状態遷移の失敗を表す。"""


type FrameReadbackSource = Literal["camera", "simulation"]


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

    # pypylon converterでMono16 / MsbAlignedへ変換した、画像処理前のRaw相当画像。
    image: np.ndarray
    readback: FrameReadback


class SoftwareTriggerSession(Protocol):
    """ソフトトリガー取得中だけカメラを所有するセッション。"""

    def wait_until_ready(self, timeout_ms: int) -> None:
        """指定時間内にFrameStartトリガー受付可能になるまで待つ。"""
        ...

    def execute_trigger(self) -> None:
        """ソフトウェアFrameStartトリガーを1回発行する。"""
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

    def start_software_trigger_session(
        self,
        *,
        expected_frames: int | None,
    ) -> SoftwareTriggerSession:
        """IDLE状態からソフトトリガー取得セッションを開始する。"""
        ...
