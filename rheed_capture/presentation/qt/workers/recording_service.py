from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from rheed_capture.application.capture.frame_capturer import (
    DEFAULT_CAPTURE_RETRY_LIMIT,
    CaptureConditionApplier,
    FrameGrabber,
)
from rheed_capture.application.capture.recording import (
    RecordingCapture,
    RecordingHooks,
)
from rheed_capture.application.capture.recording import (
    RecordingSettings as ApplicationRecordingSettings,
)
from rheed_capture.data_formats.storage_naming import RECORDING_SAVE_QUEUE_MAX_SIZE
from rheed_capture.infrastructure.storage.async_tiff_save_worker import AsyncTiffSaveWorker
from rheed_capture.presentation.qt.workers.capture_worker import CaptureWorker

if TYPE_CHECKING:
    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
    from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage

logger = logging.getLogger(__name__)

RecordingSettings = ApplicationRecordingSettings


class RecordingService(CaptureWorker):
    """RecordingCaptureをQt workerとして実行するService。"""

    saved_frames_updated = Signal(int)
    recording_finished = Signal(bool, str)

    def __init__(
        self,
        camera_device: CameraDevice,
        storage: ExperimentStorage,
        settings: RecordingSettings,
        parent: QObject | None = None,
    ) -> None:
        """カメラ、Storage、撮影条件を保持してworkerを初期化する。"""
        self.camera = camera_device
        self.storage = storage
        self.settings = settings
        self.max_retries = DEFAULT_CAPTURE_RETRY_LIMIT
        super().__init__(self._run_recording_capture, parent=parent)
        self.finished.connect(self.recording_finished)

    def _run_recording_capture(self, cancellation_token: CancellationToken) -> str:
        """RecordingSessionを作成して録画Use Caseを実行する。"""
        logger.info("録画を開始します...")

        # Recordingのsample名は、ユーザーが選択した保存rootディレクトリ名を使う。
        session = self.storage.start_recording_session(
            sample_name=self.storage.root_dir.name,
            exposure_ms=self.settings.exposure_ms,
            gain=self.settings.gain,
            rate_mode=self.settings.rate_mode,
            target_interval_ms=self.settings.target_interval_ms,
            duration_ms=self.settings.duration_ms,
        )
        capture = RecordingCapture(
            CaptureConditionApplier(self.camera),
            FrameGrabber(self.camera, max_retries=self.max_retries),
            session,
            self.settings,
            save_worker=AsyncTiffSaveWorker(
                max_queue_size=RECORDING_SAVE_QUEUE_MAX_SIZE
            ),
        )
        capture.run(
            cancellation_token,
            hooks=RecordingHooks(
                on_saved_frames_changed=self.saved_frames_updated.emit,
                # Previewは表示専用なので、保存用データとは別に画像だけを通知する。
                on_frame_captured=lambda frame: self.frame_captured.emit(frame.image),
            ),
        )

        logger.info("録画が終了しました。")
        return str(session.dir_name)
