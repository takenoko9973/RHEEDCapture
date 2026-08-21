from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from rheed_capture.application.ports.camera import (
    CameraError,
    CameraFrame,
    TriggerCaptureSession,
)
from rheed_capture.domain.acquisition_statistics import (
    AcquisitionSample,
    AcquisitionStatistics,
    AcquisitionStatisticsMeter,
)
from rheed_capture.infrastructure.config.schema import AcquisitionSettings
from rheed_capture.presentation.qt.preview.processor import PreviewPipeline

if TYPE_CHECKING:
    from rheed_capture.infrastructure.camera.basler_camera import CameraDevice

PREVIEW_RETRIEVE_POLL_TIMEOUT_MS = 100
PREVIEW_PAUSED_SLEEP_SEC = 0.1
PREVIEW_ERROR_SLEEP_SEC = 0.1


class PreviewWorker(QThread):
    """Trigger Sessionを所有スレッドで扱うPreview取得worker。"""

    raw_frame_ready = Signal(object)
    image_ready = Signal(np.ndarray)
    histogram_ready = Signal(np.ndarray, float, float)
    error_occurred = Signal(str)
    preview_paused = Signal()

    def __init__(
        self,
        camera_device: CameraDevice,
        parent: QObject | None = None,
        *,
        acquisition_settings: AcquisitionSettings | None = None,
    ) -> None:
        """カメラと初期Acquisition設定を受け取りworkerを生成する。"""
        super().__init__(parent)
        self.camera_device = camera_device
        self.pipeline = PreviewPipeline()
        self.raw_frame_ready.connect(self.pipeline.process_frame)
        self.pipeline.image_ready.connect(self.image_ready)
        self.pipeline.histogram_ready.connect(self.histogram_ready)
        self.pipeline.error_occurred.connect(self.error_occurred)

        self._lifecycle_lock = threading.Lock()
        self._is_running = False
        # QThread.start() はrun()を非同期に呼ぶため、開始直後のstop()を
        # _is_runningだけで表すとrun()冒頭の初期化で終了要求が消える。
        self._stop_requested = True
        self.enable_processing = False

        self._pause_requested = False
        self._resume_requested = False
        self._is_paused = False
        self._settings_lock = threading.Lock()
        self._acquisition_settings = acquisition_settings or AcquisitionSettings()
        self._pending_acquisition_settings: AcquisitionSettings | None = None
        self._pending_exposure_ms: float | None = None
        self._pending_gain: int | None = None
        self._rearm_requested = False

        self._session: TriggerCaptureSession | None = None
        self._statistics_lock = threading.Lock()
        self._statistics_meter = AcquisitionStatisticsMeter()
        self._statistics_active = False
        self._accumulator: np.ndarray | None = None
        self._accumulation_progress = 0
        self._accumulation_target = 1
        self._waiting_for_trigger = False

    def start(
        self,
        priority: QThread.Priority = QThread.Priority.InheritPriority,
    ) -> None:
        """終了要求を解除してPreview threadを開始する。"""
        with self._lifecycle_lock:
            self._stop_requested = False
        super().start(priority)

    def run(self) -> None:
        """Trigger Sessionを所有スレッドで実行し、終了時に必ずcloseする。"""
        with self._lifecycle_lock:
            if self._stop_requested:
                return
            self._is_running = True
        self._reset_statistics(active=True)
        self._reset_accumulator()

        try:
            self._run_preview_loop()
        finally:
            self._close_active_session()
            with self._lifecycle_lock:
                self._is_running = False
                self._stop_requested = True
            self._reset_statistics(active=False)

    def _run_preview_loop(self) -> None:
        """pause、設定変更、Trigger取得を一つの所有スレッドloopで処理する。"""
        while self._is_running:
            self._process_pause_request()
            if self._wait_while_paused():
                continue

            if self._rearm_requested:
                self._rearm_preview()

            if self._session is None and not self._start_preview_session():
                continue

            self._retrieve_and_handle_frame()

    def _process_pause_request(self) -> None:
        """pause要求をSession closeと統計境界へ変換する。"""
        if not self._pause_requested:
            return

        self._close_active_session()
        self._apply_pending_settings()
        self._pause_requested = False
        self._is_paused = True
        self._reset_statistics(active=False)
        self._reset_accumulator()
        self.preview_paused.emit()

    def _wait_while_paused(self) -> bool:
        """pause中はresume要求だけを処理し、まだpauseならTrueを返す。"""
        if self._resume_requested:
            self._resume_requested = False
            self._is_paused = False
            self._reset_statistics(active=True)
            self._reset_accumulator()
            return False

        if not self._is_paused:
            return False

        time.sleep(PREVIEW_PAUSED_SLEEP_SEC)
        return True

    def _rearm_preview(self) -> None:
        """現在Sessionを閉じ、予約設定を適用して統計を再開する。"""
        self._close_active_session()
        settings_changed = self._apply_pending_settings()
        if settings_changed:
            self._reset_statistics(active=True)
            self._reset_accumulator()

    def _start_preview_session(self) -> bool:
        """現在設定のUnlimited Trigger Sessionを開始する。"""
        try:
            self._session = self.camera_device.start_trigger_session(
                settings=self._acquisition_settings.to_trigger_settings(),
                expected_frames=None,
            )
            self._reset_accumulator()
        except CameraError as e:
            self.error_occurred.emit(str(e))
            time.sleep(PREVIEW_ERROR_SLEEP_SEC)
            return False
        return True

    def _retrieve_and_handle_frame(self) -> None:
        """次のRaw frameを取得し、CameraError時はSessionを再arm可能にする。"""
        session = self._session
        if session is None:
            return

        try:
            camera_frame = self._retrieve_next_frame(session)
        except CameraError as e:
            self.error_occurred.emit(str(e))
            self._close_active_session()
            time.sleep(PREVIEW_ERROR_SLEEP_SEC)
            return

        if camera_frame is not None:
            self._handle_camera_frame(camera_frame)

    def _retrieve_next_frame(
        self,
        session: TriggerCaptureSession,
    ) -> CameraFrame | None:
        """現在のTrigger modeに従い、次のRaw frameを一つ取得する。"""
        if self._acquisition_settings.mode == "software":
            self._waiting_for_trigger = False
            try:
                session.wait_until_ready(PREVIEW_RETRIEVE_POLL_TIMEOUT_MS)
            except TimeoutError:
                return None

            session.execute_software_trigger()
            try:
                return session.retrieve_frame(PREVIEW_RETRIEVE_POLL_TIMEOUT_MS)
            except TimeoutError:
                return None

        self._waiting_for_trigger = True
        try:
            camera_frame = session.retrieve_frame(PREVIEW_RETRIEVE_POLL_TIMEOUT_MS)
        except TimeoutError:
            return None

        self._waiting_for_trigger = False
        return camera_frame

    def _handle_camera_frame(self, camera_frame: CameraFrame | np.ndarray | object) -> None:
        """Raw到着を統計へ記録し、積算完了時だけPreviewへ通知する。"""
        if isinstance(camera_frame, CameraFrame):
            raw_image = camera_frame.image
        elif isinstance(camera_frame, np.ndarray):
            raw_image = camera_frame
        else:
            raw_image = getattr(camera_frame, "image", None)
        if not isinstance(raw_image, np.ndarray):
            return

        self._record_acquisition()
        if self._accumulation_progress >= self._accumulation_target:
            self._accumulator = None
            self._accumulation_progress = 0
        self._accumulation_progress += 1
        if self._accumulation_target == 1:
            self.raw_frame_ready.emit(raw_image)
            return

        image_uint64 = np.asarray(raw_image, dtype=np.uint64)
        if self._accumulator is None:
            self._accumulator = image_uint64.copy()
        else:
            self._accumulator += image_uint64

        if self._accumulation_progress < self._accumulation_target:
            return

        accumulated_image = np.clip(self._accumulator, 0, 65535).astype(np.uint16)
        self.raw_frame_ready.emit(accumulated_image)

    def statistics_snapshot(self) -> AcquisitionStatistics | None:
        """表示時点のPreview取得統計を返す。"""
        with self._statistics_lock:
            if not self._statistics_active:
                return None
            statistics = self._statistics_meter.snapshot(
                time.perf_counter(),
                include_average=False,
            )
            return replace(
                statistics,
                accumulation_progress=self._accumulation_progress,
                accumulation_target=self._accumulation_target,
                waiting_for_trigger=self._waiting_for_trigger,
            )

    def _record_acquisition(self) -> None:
        """正常取得Raw frameをmeterへ記録する。"""
        sample = self._take_acquisition_sample()
        if sample is None:
            timestamp = time.perf_counter()
            payload_bytes = None
        else:
            timestamp = sample.timestamp
            payload_bytes = sample.payload_bytes

        with self._statistics_lock:
            self._statistics_meter.record_frame(timestamp, payload_bytes)

    def _take_acquisition_sample(self) -> AcquisitionSample | None:
        """カメラが提供する直前取得sampleを型検証付きで取り出す。"""
        take_sample = getattr(self.camera_device, "take_acquisition_sample", None)
        if not callable(take_sample):
            return None

        sample = take_sample()
        return sample if isinstance(sample, AcquisitionSample) else None

    def _reset_statistics(self, *, active: bool) -> None:
        """Preview開始、停止、再armの境界で統計を初期化する。"""
        with self._statistics_lock:
            self._statistics_meter.reset()
            self._statistics_active = active

    def _reset_accumulator(self) -> None:
        """現在設定の積算枚数へ状態を戻し、未完成画像を破棄する。"""
        settings = self._acquisition_settings
        self._accumulation_target = (
            settings.accumulation_frames if settings.accumulation_enabled else 1
        )
        self._accumulator = None
        self._accumulation_progress = 0
        self._waiting_for_trigger = settings.mode == "hardware"

    def _apply_pending_settings(self) -> bool:
        """Session close後に予約済み設定を適用し、rearm要求を消費する。"""
        with self._settings_lock:
            acquisition_settings = self._pending_acquisition_settings
            exposure_ms = self._pending_exposure_ms
            gain = self._pending_gain
            self._pending_acquisition_settings = None
            self._pending_exposure_ms = None
            self._pending_gain = None
            self._rearm_requested = False

        settings_changed = acquisition_settings is not None
        if acquisition_settings is not None:
            self._acquisition_settings = acquisition_settings

        if exposure_ms is not None:
            self.camera_device.set_exposure(exposure_ms)
        if gain is not None:
            self.camera_device.set_gain(gain)
        return settings_changed or exposure_ms is not None or gain is not None

    def _close_active_session(self) -> None:
        """所有スレッドからだけ現在のTrigger Sessionをcloseする。"""
        session = self._session
        if session is None:
            return

        self._session = None
        try:
            session.close()
        except CameraError as e:
            self.error_occurred.emit(str(e))

    def stop(self) -> None:
        """Preview loopへ終了を要求する。Session closeはworker側で行う。"""
        with self._lifecycle_lock:
            self._stop_requested = True
            self._is_running = False

    def request_pause(self) -> None:
        """次のloopでSessionを閉じてPreviewをpauseするよう要求する。"""
        self._pause_requested = True

    def resume(self) -> None:
        """pause状態をworker側で解除し、現在設定のSessionを再armする。"""
        self._resume_requested = True
        # 既存呼出側は要求直後にpause flagを参照するため、表示状態だけ先に戻す。
        # Session再開と統計初期化は次のworker loopで行う。
        self._is_paused = False

    def request_exposure(self, exposure_ms: float) -> None:
        """Session close後に所有スレッドで適用する露光時間を予約する。"""
        with self._settings_lock:
            self._pending_exposure_ms = exposure_ms
            self._rearm_requested = True

    def request_gain(self, gain: int) -> None:
        """Session close後に所有スレッドで適用するGainを予約する。"""
        with self._settings_lock:
            self._pending_gain = gain
            self._rearm_requested = True

    def set_acquisition_settings(self, settings: AcquisitionSettings) -> None:
        """Acquisition設定変更をSession close後の再armとして予約する。"""
        with self._settings_lock:
            if not self.isRunning():
                self._acquisition_settings = settings
                return
            self._pending_acquisition_settings = settings
            self._rearm_requested = True

    def set_processing_enabled(self, enabled: bool) -> None:
        """プレビュー画像処理の有効状態を更新する。"""
        self.enable_processing = enabled
        self.pipeline.set_processing_enabled(enabled)
