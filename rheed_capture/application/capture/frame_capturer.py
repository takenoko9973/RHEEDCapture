from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Never, Protocol
from zoneinfo import ZoneInfo

from rheed_capture.application.ports.camera import Camera, CameraError
from rheed_capture.domain.capture_defaults import (
    DEFAULT_CAPTURE_RETRY_INTERVAL_SEC,
    DEFAULT_CAPTURE_RETRY_LIMIT,
    DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS,
)

if TYPE_CHECKING:
    import numpy as np

    from rheed_capture.domain.capture_condition import CaptureCondition

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class CapturedFrame:
    """保存とプレビュー通知へ渡す、加工前の1フレーム取得結果。"""

    image: np.ndarray
    condition: CaptureCondition
    timestamp: str


@dataclass(frozen=True)
class GrabbedFrame:
    """カメラから取得したRaw画像と撮影時刻情報。"""

    image: np.ndarray
    timestamp: datetime
    monotonic_time_sec: float


class FrameCapture(Protocol):
    """撮影方式が依存する1フレーム取得インターフェース。"""

    def capture(self, condition: CaptureCondition) -> CapturedFrame:
        """指定条件で1フレームを取得する。"""
        ...


class CaptureConditionApplier:
    """露光時間とゲインをカメラへ適用する。"""

    def __init__(self, camera: Camera) -> None:
        """設定対象のカメラPortを保持する。"""
        self.camera = camera

    def apply(self, condition: CaptureCondition) -> None:
        """撮影条件をカメラへ順に設定する。"""
        self.camera.set_exposure(condition.exposure_ms)
        self.camera.set_gain(condition.gain)


class FrameGrabber:
    """1フレーム取得、リトライ、取得時刻付与を担当する。"""

    def __init__(
        self,
        camera: Camera,
        *,
        max_retries: int = DEFAULT_CAPTURE_RETRY_LIMIT,
        retry_interval_sec: float = DEFAULT_CAPTURE_RETRY_INTERVAL_SEC,
    ) -> None:
        """カメラとリトライ条件を保持する。"""
        self.camera = camera
        self.max_retries = max_retries
        self.retry_interval_sec = retry_interval_sec

    def grab(self, timeout_ms: int) -> GrabbedFrame:
        """1枚取得し、失敗時は設定回数まで同じ設定で再試行する。"""
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return self._execute_single_grab(timeout_ms)
            except (CameraError, RuntimeError, TimeoutError) as e:
                logger.warning(
                    "撮影エラー (Attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    e,
                )
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_interval_sec)

        self._raise_max_retry_error(last_error)
        msg = "unreachable"
        raise AssertionError(msg)

    def _execute_single_grab(self, timeout_ms: int) -> GrabbedFrame:
        """1回だけカメラ取得を実行し、Raw画像と時刻を返す。"""
        raw_data = self.camera.grab_one(timeout_ms)
        if raw_data is None:
            self._raise_grab_none_error()

        return GrabbedFrame(
            image=raw_data,
            timestamp=datetime.now(JST),
            monotonic_time_sec=time.perf_counter(),
        )

    def _raise_max_retry_error(self, error: Exception | None) -> Never:
        """最後に観測した例外を原因として、利用者向けの撮影失敗例外を投げる。"""
        msg = "最大リトライ回数に達しました。"
        if error:
            raise RuntimeError(msg) from error

        raise RuntimeError(msg)

    def _raise_grab_none_error(self) -> Never:
        """カメラが正常応答したが画像を返さなかったケースを撮影失敗へ変換する。"""
        msg = "画像データがNoneとして返されました。"
        raise RuntimeError(msg)


class FrameCapturer:
    """既存Sequence/Angle Scan用に条件適用とフレーム取得をまとめる。"""

    def __init__(
        self,
        camera: Camera,
        *,
        max_retries: int = DEFAULT_CAPTURE_RETRY_LIMIT,
        retry_interval_sec: float = DEFAULT_CAPTURE_RETRY_INTERVAL_SEC,
    ) -> None:
        """条件適用とフレーム取得の小さな部品を組み合わせる。"""
        self.condition_applier = CaptureConditionApplier(camera)
        self.frame_grabber = FrameGrabber(
            camera,
            max_retries=max_retries,
            retry_interval_sec=retry_interval_sec,
        )

    def capture(self, condition: CaptureCondition) -> CapturedFrame:
        """指定条件を1回適用してから、リトライ付きで1枚取得する。"""
        self.condition_applier.apply(condition)
        timeout_ms = int(condition.exposure_ms + DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS)
        grabbed = self.frame_grabber.grab(timeout_ms)

        return CapturedFrame(
            image=grabbed.image,
            condition=condition,
            timestamp=grabbed.timestamp.isoformat(),
        )
