from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from rheed_capture.application.capture.frame_capturer import (
    DEFAULT_CAPTURE_RETRY_LIMIT,
    FrameCapturer,
)
from rheed_capture.application.capture.sequence import SequenceCapture
from rheed_capture.presentation.qt.workers.capture_worker import CaptureWorker

if TYPE_CHECKING:
    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
    from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage

logger = logging.getLogger(__name__)


class CaptureService(CaptureWorker):
    progress_update = Signal(int, int)
    sequence_finished = Signal(bool, str)

    def __init__(
        self,
        camera_device: CameraDevice,
        storage: ExperimentStorage,
        exposure_list: list[float],
        gain_list: list[int],
        parent: QObject | None = None,
    ) -> None:
        self.camera = camera_device
        self.storage = storage
        self.max_retries = DEFAULT_CAPTURE_RETRY_LIMIT
        self._exposure_list = exposure_list
        self._gain_list = gain_list
        super().__init__(self._run_sequence_capture, parent=parent)
        self.finished.connect(self.sequence_finished)

    def _run_sequence_capture(self, cancellation_token: CancellationToken) -> str:
        logger.info("撮影シーケンスを開始します...")

        session = self.storage.start_sequence_session()
        capture = SequenceCapture(
            FrameCapturer(self.camera, max_retries=self.max_retries),
            session,
            self._exposure_list,
            self._gain_list,
        )
        capture.run(
            cancellation_token,
            on_progress=self.progress_update.emit,
            on_frame_captured=self.frame_captured.emit,
        )

        logger.info("撮影シーケンスが正常に完了しました。")
        return str(session.dir_name)
