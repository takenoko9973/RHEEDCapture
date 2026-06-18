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


class FrameCapture(Protocol):
    """撮影方式が依存する1フレーム取得インターフェース。"""

    def capture(self, condition: CaptureCondition) -> CapturedFrame:
        ...


class FrameCapturer:
    """カメラ設定、1フレーム取得、リトライ、取得時刻付与を一か所に集約する。"""

    def __init__(
        self,
        camera: Camera,
        *,
        max_retries: int = DEFAULT_CAPTURE_RETRY_LIMIT,
        retry_interval_sec: float = DEFAULT_CAPTURE_RETRY_INTERVAL_SEC,
    ) -> None:
        self.camera = camera
        self.max_retries = max_retries
        self.retry_interval_sec = retry_interval_sec

    def capture(self, condition: CaptureCondition) -> CapturedFrame:
        """指定条件で1枚取得し、失敗時は設定回数まで同じ条件で再試行する。"""
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return self._execute_single_capture(condition)
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

        self._raise_max_retry_error(condition, last_error)
        msg = "unreachable"
        raise AssertionError(msg)

    def _execute_single_capture(self, condition: CaptureCondition) -> CapturedFrame:
        """リトライを含まない1回分のカメラ操作を実行する。"""
        timeout_ms = int(condition.exposure_ms + DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS)

        self.camera.set_exposure(condition.exposure_ms)
        self.camera.set_gain(condition.gain)

        raw_data = self.camera.grab_one(timeout_ms)
        if raw_data is None:
            self._raise_grab_none_error()

        return CapturedFrame(
            image=raw_data,
            condition=condition,
            timestamp=datetime.now(JST).isoformat(),
        )

    def _raise_max_retry_error(
        self,
        condition: CaptureCondition,
        error: Exception | None,
    ) -> Never:
        """最後に観測した例外を原因として、利用者向けの撮影失敗例外を投げる。"""
        msg = (
            "最大リトライ回数に達しました。"
            f"露光={condition.exposure_ms}ms, ゲイン={condition.gain}"
        )
        if error:
            raise RuntimeError(msg) from error

        raise RuntimeError(msg)

    def _raise_grab_none_error(self) -> Never:
        """カメラが正常応答したが画像を返さなかったケースを撮影失敗へ変換する。"""
        msg = "画像データがNoneとして返されました。"
        raise RuntimeError(msg)
