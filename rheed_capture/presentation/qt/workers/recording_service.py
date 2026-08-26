from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
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
    validate_recording_settings,
)
from rheed_capture.application.capture.recording import (
    RecordingSettings as ApplicationRecordingSettings,
)
from rheed_capture.data_formats.storage_naming import RECORDING_SAVE_QUEUE_MAX_SIZE
from rheed_capture.domain.acquisition_statistics import (
    AcquisitionStatistics,
    AcquisitionStatisticsMeter,
)
from rheed_capture.infrastructure.config.schema import AcquisitionSettings
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
        acquisition_settings: AcquisitionSettings | None = None,
        parent: QObject | None = None,
    ) -> None:
        """カメラ、Storage、撮影条件を保持してworkerを初期化する。"""
        self.camera = camera_device
        self.storage = storage
        self.settings = settings
        self.max_retries = DEFAULT_CAPTURE_RETRY_LIMIT
        # UIの後続変更が進行中Recordingのtrigger設定を変えないsnapshotにする。
        self._acquisition_settings = acquisition_settings or AcquisitionSettings()
        self._trigger_settings = self._acquisition_settings.to_trigger_settings()
        self._accumulation_frames = (
            self._acquisition_settings.accumulation_frames
            if self._acquisition_settings.accumulation_enabled
            else 1
        )
        self._trigger_wait_timeout_sec = (
            self._acquisition_settings.trigger_wait_timeout_sec
        )
        self._statistics_lock = threading.Lock()
        self._statistics_meter = AcquisitionStatisticsMeter()
        self._statistics_active = False
        self._accumulation_progress = 0
        self._waiting_for_trigger = False
        self._save_worker: AsyncTiffSaveWorker | None = None
        super().__init__(self._run_recording_capture, parent=parent)
        self.finished.connect(self.recording_finished)

    def _run_recording_capture(self, cancellation_token: CancellationToken) -> str:
        """RecordingSessionを作成して録画Use Caseを実行する。"""
        logger.info("録画を開始します...")
        self._validate_start_conditions()
        self._reset_statistics(active=True, started_at=time.perf_counter())

        try:
            # Recordingのsample名は、ユーザーが選択した保存rootディレクトリ名を使う。
            if self._accumulation_frames > 1:
                session = self.storage.start_recording_session(
                    sample_name=self.storage.root_dir.name,
                    exposure_ms=self.settings.exposure_ms,
                    gain=self.settings.gain,
                    rate_mode=self.settings.rate_mode,
                    target_interval_ms=self.settings.target_interval_ms,
                    duration_ms=self.settings.duration_ms,
                    accumulation_frames=self._accumulation_frames,
                    tiff_compression_enabled=self.settings.tiff_compression_enabled,
                )
            else:
                session = self.storage.start_recording_session(
                    sample_name=self.storage.root_dir.name,
                    exposure_ms=self.settings.exposure_ms,
                    gain=self.settings.gain,
                    rate_mode=self.settings.rate_mode,
                    target_interval_ms=self.settings.target_interval_ms,
                    duration_ms=self.settings.duration_ms,
                    tiff_compression_enabled=self.settings.tiff_compression_enabled,
                )
            save_worker = AsyncTiffSaveWorker(
                max_queue_size=RECORDING_SAVE_QUEUE_MAX_SIZE
            )
            self._save_worker = save_worker
            capture = RecordingCapture(
                CaptureConditionApplier(self.camera),
                FrameGrabber(
                    self.camera,
                    trigger_settings=self._trigger_settings,
                    max_retries=self.max_retries,
                ),
                session,
                self.settings,
                save_worker=save_worker,
                accumulation_frames=self._accumulation_frames,
                trigger_wait_timeout_sec=self._trigger_wait_timeout_sec,
            )
            capture.run(
                cancellation_token,
                hooks=RecordingHooks(
                    on_saved_frames_changed=self.saved_frames_updated.emit,
                    on_frame_captured=self._on_frame_captured,
                    on_preview_frame_completed=self.frame_captured.emit,
                    on_accumulation_progress=self._on_accumulation_progress,
                    on_waiting_for_trigger_changed=self._on_waiting_for_trigger_changed,
                ),
            )
        finally:
            with self._statistics_lock:
                self._save_worker = None
                self._reset_statistics_locked(active=False)

        logger.info("録画が終了しました。")
        return str(session.dir_name)

    def statistics_snapshot(self) -> AcquisitionStatistics | None:
        """表示時点のRecording取得統計を返す。"""
        with self._statistics_lock:
            if not self._statistics_active:
                return None
            save_worker = self._save_worker
            statistics = self._statistics_meter.snapshot(
                time.perf_counter(),
                include_average=True,
            )
            queue_telemetry = (
                save_worker.queue_telemetry
                if save_worker is not None
                else None
            )
            return replace(
                statistics,
                accumulation_progress=self._accumulation_progress,
                accumulation_target=self._accumulation_frames,
                waiting_for_trigger=self._waiting_for_trigger,
                save_queue_depth=(
                    queue_telemetry.current_depth if queue_telemetry is not None else 0
                ),
                save_queue_peak_depth=(
                    queue_telemetry.peak_depth if queue_telemetry is not None else 0
                ),
            )

    def _on_frame_captured(self, _frame: GrabbedFrame) -> None:
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

    def _on_accumulation_progress(self, progress: int, target: int) -> None:
        """Raw受信済みのgroup内進捗を統計表示へ反映する。"""
        with self._statistics_lock:
            self._accumulation_progress = progress
            self._accumulation_frames = target

    def _on_waiting_for_trigger_changed(self, waiting: bool) -> None:
        """Hardware trigger待機中だけstatus表示を切り替える。"""
        with self._statistics_lock:
            self._waiting_for_trigger = waiting

    def _validate_start_conditions(self) -> None:
        """Session作成前にSoftware recording固有の条件を拒否する。"""
        if self._trigger_settings.mode != "software":
            return
        validate_recording_settings(self.settings, enforce_software_schedule=True)
        fps_limit = self._trigger_settings.fps_limit
        requested_fps = 1000.0 / self.settings.target_interval_ms
        if fps_limit is not None and requested_fps > fps_limit:
            msg = (
                "要求FPSがCamera FPS Limitを超えるため、録画を開始できません。\n\n"
                f"要求FPS: {requested_fps:g}\n"
                f"FPS Limit: {fps_limit:g}"
            )
            raise ValueError(msg)

    def _reset_statistics(
        self,
        *,
        active: bool,
        started_at: float | None = None,
    ) -> None:
        """Recording全体の開始と終了に合わせてmeterを初期化する。"""
        with self._statistics_lock:
            self._reset_statistics_locked(active=active, started_at=started_at)

    def _reset_statistics_locked(
        self,
        *,
        active: bool,
        started_at: float | None = None,
    ) -> None:
        """statistics lockを保持した状態でRecording統計を初期化する。"""
        self._statistics_meter.reset(started_at=started_at)
        self._statistics_active = active
        self._accumulation_progress = 0
        self._waiting_for_trigger = False
