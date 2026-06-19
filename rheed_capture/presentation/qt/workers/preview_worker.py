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

    def run(self) -> None:
        self._is_running = True

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

    def stop(self) -> None:
        self._is_running = False

    def request_pause(self) -> None:
        self._pause_requested = True

    def resume(self) -> None:
        self._is_paused = False

    def set_processing_enabled(self, enabled: bool) -> None:
        self.enable_processing = enabled
        self.pipeline.set_processing_enabled(enabled)
