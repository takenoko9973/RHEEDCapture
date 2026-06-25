from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.application.capture.recording import (
    RateMode,
    interval_from_fps,
    normalize_duration_ms,
)
from rheed_capture.infrastructure.config.schema import RecordingCaptureSettings
from rheed_capture.presentation.qt.workers.recording_service import (
    RecordingService,
    RecordingSettings,
)

if TYPE_CHECKING:
    from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
    from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage


class RecordingViewModel(QObject):
    """Recording UI状態を保持し、RecordingServiceへ撮影条件を渡すViewModel。"""

    saved_frames_updated = Signal(int)
    expected_frames_updated = Signal(str)
    frame_captured = Signal(object)
    recording_finished = Signal(bool, str)
    error_occurred = Signal(str)

    def __init__(self, camera: CameraDevice, storage: ExperimentStorage) -> None:
        """カメラとStorageを保持し、Recordingの初期UI状態を設定する。"""
        super().__init__()
        self._camera = camera
        self._storage = storage
        self._recording_service: RecordingService | None = None

        self._exposure_ms = 50.0
        self._gain = 0
        self._rate_mode: RateMode = "interval"
        self._fps = 10.0
        self._interval_ms = 100.0
        self._duration_sec = 0.0

    def load_settings(self, settings: RecordingCaptureSettings) -> None:
        """保存済みRecording設定をViewModelへ読み込む。"""
        self._exposure_ms = settings.exposure_ms
        self._gain = settings.gain
        self._rate_mode = settings.rate_mode
        self._fps = settings.fps
        self._interval_ms = settings.interval_ms
        self._duration_sec = settings.duration_sec
        self._emit_expected_frames()

    def get_settings_to_save(self) -> RecordingCaptureSettings:
        """現在のRecording UI状態を保存用設定へ変換する。"""
        return RecordingCaptureSettings(
            exposure_ms=self._exposure_ms,
            gain=self._gain,
            rate_mode=self._rate_mode,
            fps=self._fps,
            interval_ms=self._interval_ms,
            duration_sec=self._duration_sec,
        )

    @Slot(float)
    def update_exposure_ms(self, value: float) -> None:
        """露光時間の変更を反映し、見込み枚数を更新する。"""
        self._exposure_ms = value
        self._emit_expected_frames()

    @Slot(int)
    def update_gain(self, value: int) -> None:
        """Gainの変更を反映する。"""
        self._gain = value

    @Slot(str)
    def update_rate_mode(self, value: str) -> None:
        """FPS/Interval入力モードの変更を反映する。"""
        self._rate_mode = cast("RateMode", value)
        self._emit_expected_frames()

    @Slot(float)
    def update_fps(self, value: float) -> None:
        """FPS値の変更を反映し、FPS選択中なら見込み枚数を更新する。"""
        self._fps = value
        if self._rate_mode == "fps":
            self._emit_expected_frames()

    @Slot(float)
    def update_interval_ms(self, value: float) -> None:
        """Interval値の変更を反映し、Interval選択中なら見込み枚数を更新する。"""
        self._interval_ms = value
        if self._rate_mode == "interval":
            self._emit_expected_frames()

    @Slot(float)
    def update_duration_sec(self, value: float) -> None:
        """Duration値の変更を反映し、見込み枚数を更新する。"""
        self._duration_sec = value
        self._emit_expected_frames()

    @Slot()
    def start_recording(self) -> None:
        """現在のUI状態からRecordingServiceを作成して録画を開始する。"""
        try:
            settings = self._build_recording_settings()
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.recording_finished.emit(False, "")
            return

        self._recording_service = RecordingService(self._camera, self._storage, settings)
        # ServiceのSignalをViewModelのSignalとして中継し、PanelとMainWindowを疎結合に保つ。
        self._recording_service.saved_frames_updated.connect(self.saved_frames_updated)
        self._recording_service.frame_captured.connect(self.frame_captured)
        self._recording_service.recording_finished.connect(self.recording_finished)
        self._recording_service.error_occurred.connect(self.error_occurred)
        self._recording_service.start()

    @Slot()
    def stop_recording(self) -> None:
        """実行中のRecordingServiceへキャンセルを要求する。"""
        if self.is_running() and self._recording_service:
            self._recording_service.cancel()

    def is_running(self) -> bool:
        """RecordingServiceが実行中かを返す。"""
        return self._recording_service is not None and self._recording_service.isRunning()

    def _build_recording_settings(self) -> RecordingSettings:
        """UI入力値をUse Caseが要求するRecordingSettingsへ変換する。"""
        target_interval_ms = (
            interval_from_fps(self._fps)
            if self._rate_mode == "fps"
            else self._interval_ms
        )
        return RecordingSettings(
            exposure_ms=self._exposure_ms,
            gain=self._gain,
            rate_mode=self._rate_mode,
            target_interval_ms=target_interval_ms,
            duration_ms=normalize_duration_ms(self._duration_sec),
        )

    def _emit_expected_frames(self) -> None:
        """Durationと選択中Rateから見込みフレーム数を通知する。"""
        duration_ms = normalize_duration_ms(self._duration_sec)
        if duration_ms is None:
            self.expected_frames_updated.emit("-")
            return

        try:
            interval_ms = (
                interval_from_fps(self._fps)
                if self._rate_mode == "fps"
                else self._interval_ms
            )
        except ValueError:
            self.expected_frames_updated.emit("-")
            return

        expected_frames = math.ceil(duration_ms / interval_ms) + 1
        self.expected_frames_updated.emit(f"about {expected_frames}")
