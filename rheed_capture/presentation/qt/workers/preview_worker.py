import threading
import time

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from rheed_capture.application.ports.camera import CameraError
from rheed_capture.domain.capture_defaults import DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.presentation.qt.preview.processor import PreviewPipeline

PREVIEW_RETRIEVE_POLL_TIMEOUT_MS = 100
PREVIEW_IDLE_SLEEP_SEC = 0.02
PREVIEW_PAUSED_SLEEP_SEC = 0.1


class PreviewWorker(QThread):
    raw_frame_ready = Signal(object)
    image_ready = Signal(np.ndarray)
    histogram_ready = Signal(np.ndarray, float, float)
    error_occurred = Signal(str)
    preview_paused = Signal()

    def __init__(self, camera_device: CameraDevice, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.camera_device = camera_device
        self.pipeline = PreviewPipeline()
        self.raw_frame_ready.connect(self.pipeline.process_frame)
        self.pipeline.image_ready.connect(self.image_ready)
        self.pipeline.histogram_ready.connect(self.histogram_ready)
        self.pipeline.error_occurred.connect(self.error_occurred)

        self._is_running = False
        self.enable_processing = False

        self._pause_requested = False
        self._is_paused = False
        self._settings_lock = threading.Lock()
        self._pending_exposure_ms: float | None = None
        self._pending_gain: int | None = None

    def run(self) -> None:
        """所有スレッド内でプレビューloopを実行し、終了時に取得を停止する。"""
        self._is_running = True

        try:
            self._run_preview_loop()
        finally:
            try:
                self.camera_device.stop_grabbing()
            except CameraError as e:
                # 終了処理の失敗は握りつぶさず、UIへ診断情報を通知する。
                self.error_occurred.emit(str(e))

    def _run_preview_loop(self) -> None:
        """pauseと設定変更を処理しながらプレビューフレームを取得する。"""
        while self._is_running:
            if self._pause_requested:
                self.camera_device.stop_grabbing()
                self._is_paused = True
                self._pause_requested = False
                self.preview_paused.emit()

            if self._is_paused:
                time.sleep(PREVIEW_PAUSED_SLEEP_SEC)
                continue

            try:
                self._apply_pending_camera_settings()
                self.camera_device.start_preview_grab()
                exposure_ms = self.camera_device.get_exposure()
                timeout_ms = min(
                    int(exposure_ms + DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS),
                    PREVIEW_RETRIEVE_POLL_TIMEOUT_MS,
                )
                raw_image = self.camera_device.retrieve_preview_frame(timeout_ms=timeout_ms)
            except CameraError as e:
                self.error_occurred.emit(str(e))
                time.sleep(PREVIEW_PAUSED_SLEEP_SEC)
                continue

            if raw_image is not None:
                self.raw_frame_ready.emit(raw_image)
            else:
                time.sleep(PREVIEW_IDLE_SLEEP_SEC)

    def _apply_pending_camera_settings(self) -> None:
        """取得を止めてからUIスレッドで予約された露光時間とGainを適用する。"""
        with self._settings_lock:
            exposure_ms = self._pending_exposure_ms
            gain = self._pending_gain
            self._pending_exposure_ms = None
            self._pending_gain = None

        if exposure_ms is None and gain is None:
            return

        # Basler nodeを取得中に変更しないよう、所有スレッドで明示的にIDLEへ戻す。
        self.camera_device.stop_grabbing()
        if exposure_ms is not None:
            self.camera_device.set_exposure(exposure_ms)
        if gain is not None:
            self.camera_device.set_gain(gain)

    def stop(self) -> None:
        self._is_running = False

    def request_pause(self) -> None:
        """次のloopでプレビューを停止するよう要求する。"""
        self._pause_requested = True

    def resume(self) -> None:
        """pause状態を解除して次のloopでプレビューを再開する。"""
        self._is_paused = False

    def request_exposure(self, exposure_ms: float) -> None:
        """所有スレッドで適用する露光時間を予約する。"""
        with self._settings_lock:
            self._pending_exposure_ms = exposure_ms

    def request_gain(self, gain: int) -> None:
        """所有スレッドで適用するGainを予約する。"""
        with self._settings_lock:
            self._pending_gain = gain

    def set_processing_enabled(self, enabled: bool) -> None:
        self.enable_processing = enabled
        self.pipeline.set_processing_enabled(enabled)
