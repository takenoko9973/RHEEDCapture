from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.application.capture.frame_capturer import CapturedFrame
from rheed_capture.domain.image_processor import ImageProcessor


class PreviewPipeline(QObject):
    """通常プレビューと撮影中Rawフレームを同じ表示処理へ通すPipeline。"""

    image_ready = Signal(np.ndarray)
    histogram_ready = Signal(np.ndarray, float, float)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None, *, min_interval_sec: float = 0.0) -> None:
        super().__init__(parent)

        self.enable_processing = False
        self.min_interval_sec = min_interval_sec
        self._last_emit_monotonic = 0.0

    @Slot(bool)
    def set_processing_enabled(self, enabled: bool) -> None:
        """CLAHEを含む表示用画像処理のON/OFFを切り替える。"""
        self.enable_processing = enabled

    @Slot(object)
    def process_frame(self, frame: object) -> None:
        """Raw画像またはCapturedFrameを表示用画像とヒストグラムへ変換して通知する。"""
        raw_image = self._extract_raw_image(frame)
        if raw_image is None or self._should_drop_for_throttle():
            return

        try:
            # 保存用Raw画像には触れず、表示用データだけをここで生成する。
            image_12bit = np.right_shift(raw_image, 4).ravel()
            mean_val = float(np.mean(image_12bit))
            std_val = float(np.std(image_12bit))
            hist, _ = np.histogram(image_12bit, range=(0, 4095), bins=256)
            self.histogram_ready.emit(hist, mean_val, std_val)

            display_image = (
                ImageProcessor.apply_double_clahe(raw_image)
                if self.enable_processing
                else ImageProcessor.to_8bit_preview(raw_image)
            )
            self.image_ready.emit(display_image)
            self._last_emit_monotonic = time.monotonic()

        except Exception as e:  # noqa: BLE001
            self.error_occurred.emit(f"プレビュー更新エラー: {e}")

    def _extract_raw_image(self, frame: object) -> np.ndarray | None:
        """通常プレビューのndarrayと撮影済みCapturedFrameを同じRaw画像へ正規化する。"""
        if isinstance(frame, CapturedFrame):
            return frame.image

        if isinstance(frame, np.ndarray):
            return frame

        return None

    def _should_drop_for_throttle(self) -> bool:
        """表示更新だけを間引く。撮影・保存側のRawフレーム数には影響しない。"""
        if self.min_interval_sec <= 0:
            return False

        return time.monotonic() - self._last_emit_monotonic < self.min_interval_sec
