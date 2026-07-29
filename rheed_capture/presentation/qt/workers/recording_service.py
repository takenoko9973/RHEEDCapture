from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from rheed_capture.application.capture.frame_capturer import (
    DEFAULT_CAPTURE_RETRY_LIMIT,
    CaptureConditionApplier,
    FrameGrabber,
    GrabbedFrame,
)
from rheed_capture.application.capture.recording import (
    RecordingCapture,
    RecordingHooks,
)
from rheed_capture.application.capture.recording import (
    RecordingSettings as ApplicationRecordingSettings,
)
from rheed_capture.data_formats.storage_naming import RECORDING_SAVE_QUEUE_MAX_SIZE
from rheed_capture.domain.acquisition_statistics import (
    AcquisitionStatistics,
    AcquisitionStatisticsMeter,
)
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
        self._statistics_lock = threading.Lock()
        self._statistics_meter = AcquisitionStatisticsMeter()
        self._statistics_active = False
        super().__init__(self._run_recording_capture, parent=parent)
        self.finished.connect(self.recording_finished)

    def _run_recording_capture(self, cancellation_token: CancellationToken) -> str:
        """RecordingSessionを作成して録画Use Caseを実行する。"""
        logger.info("録画を開始します...")
        self._reset_statistics(active=True, started_at=time.perf_counter())

        try:
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
                    on_frame_captured=self._on_frame_captured,
                ),
            )
        finally:
            self._reset_statistics(active=False)

        logger.info("録画が終了しました。")
        return str(session.dir_name)

    def statistics_snapshot(self) -> AcquisitionStatistics | None:
        """表示時点のRecording取得統計を返す。"""
        with self._statistics_lock:
            if not self._statistics_active:
                return None
            return self._statistics_meter.snapshot(
                time.perf_counter(),
                include_average=True,
            )

    def _on_frame_captured(self, frame: GrabbedFrame) -> None:
        """正常取得フレームを統計へ記録してPreview表示へ通知する。"""
        sample = self.camera.take_acquisition_sample()
        if sample is None:
            # Payloadを取得できない環境でも、成功フレーム数によるFPSは維持する。
            timestamp = time.perf_counter()
            payload_bytes = None
        else:
            timestamp = sample.timestamp
            payload_bytes = sample.payload_bytes

        with self._statistics_lock:
            self._statistics_meter.record_frame(timestamp, payload_bytes)

        # Previewは表示専用なので、保存用データとは別に画像だけを通知する。
        self.frame_captured.emit(frame.image)

    def _reset_statistics(
        self,
        *,
        active: bool,
        started_at: float | None = None,
    ) -> None:
        """Recording全体の開始と終了に合わせてmeterを初期化する。"""
        with self._statistics_lock:
            self._statistics_meter.reset(started_at=started_at)
            self._statistics_active = active
