import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.application.capture.frame_capturer import CapturedFrame
from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.infrastructure.config.schema import AcquisitionSettings, PreviewSettings
from rheed_capture.presentation.qt.preview.processor import PreviewDiagnostics, PreviewInput
from rheed_capture.presentation.qt.viewmodels.acquisition_statistics import (
    format_preview_realtime_diagnostics,
    format_preview_statistics,
)
from rheed_capture.presentation.qt.workers.preview_worker import PreviewWorker


class PreviewViewModel(QObject):
    # === データパススルー用シグナル
    # 処理済みの画像 (UI表示用の8bit ndarray) を送るシグナル
    image_ready = Signal(np.ndarray)
    # センサ強度scaleのヒストグラム配列と統計量を送るシグナル (hist_array, mean, std)
    histogram_ready = Signal(np.ndarray, float, float)
    image_format_updated = Signal(int)
    error_occurred = Signal(str)  # エラー発生シグナル
    preview_paused = Signal()  # 一時停止完了シグナル

    # === カメラ設定更新通知用シグナル
    exposure_updated = Signal(float)
    gain_updated = Signal(int)
    clahe_enabled_updated = Signal(bool)

    def __init__(self, camera: CameraDevice) -> None:
        super().__init__()
        self._camera = camera

        self._worker = PreviewWorker(camera)

        # WorkerのシグナルをViewModelのシグナルに中継（繋ぎ直し）
        self._worker.image_ready.connect(self.image_ready)
        self._worker.histogram_ready.connect(self.histogram_ready)
        self._worker.image_format_changed.connect(self.image_format_updated)
        self._worker.error_occurred.connect(self.error_occurred)
        self._worker.preview_paused.connect(self.preview_paused)

        # 状態の保持
        self._exposure = 50.0
        self._gain = 0
        self._clahe_enabled = False
        self._acquisition_settings = AcquisitionSettings()

    def load_settings(self, settings: PreviewSettings) -> None:
        """設定ファイルから状態を復元し、システムに適用する"""
        self.set_exposure(settings.exposure_ms)
        self.set_gain(settings.gain)
        self.set_clahe_enabled(settings.enable_clahe)

    def get_settings_to_save(self) -> PreviewSettings:
        """保存用のプレビュー設定を生成する"""
        return PreviewSettings(
            exposure_ms=self._exposure,
            gain=self._gain,
            enable_clahe=self._clahe_enabled,
        )

    def load_acquisition_settings(self, settings: AcquisitionSettings) -> None:
        """保存済みAcquisition設定をPreviewWorkerへ反映する。"""
        self.set_acquisition_settings(settings)

    @Slot(object)
    def set_acquisition_settings(self, settings: AcquisitionSettings) -> None:
        """Acquisition設定を保持し、Preview中はSessionを再armする。"""
        self._acquisition_settings = settings
        self._worker.set_acquisition_settings(settings)

    def start_preview(self) -> None:
        """プレビュー開始"""
        self._worker.start()

    def stop_preview(self) -> None:
        """プレビュー停止 (終了処理)"""
        self._worker.stop()
        if not self._worker.wait(2000):
            msg = "Preview worker did not stop within 2000 ms"
            raise RuntimeError(msg)
        self._worker.pipeline.stop()

    def get_acquisition_statistics_text(self) -> str:
        """現在のPreview取得統計を短いstatus summaryへ変換して返す。"""
        statistics = self.acquisition_statistics_snapshot()
        if statistics is None:
            return ""
        return format_preview_statistics(statistics)

    def acquisition_statistics_snapshot(self) -> AcquisitionStatistics | None:
        """現在のPreview取得統計snapshotを返す。"""
        return self._worker.statistics_snapshot()

    def get_realtime_diagnostics_text(self) -> str:
        """PreviewとGraphの処理・表示診断値をstatus bar表示用に返す。"""
        return format_preview_realtime_diagnostics(self.diagnostics_snapshot())

    def pause_preview(self) -> None:
        """シーケンス撮影開始などのため、プレビューを一時停止する"""
        self._worker.request_pause()

    def resume_preview(self) -> None:
        """
        プレビューを再開する。
        他サービスによって変更された可能性のあるカメラ設定を、
        ViewModelが保持している現在のプレビュー設定で上書き復元する。
        """
        # 再開済みでも直接書き込まず、Worker所有スレッドで停止してから設定を復元する。
        self._worker.request_exposure(self._exposure)
        self._worker.request_gain(self._gain)
        self._worker.set_processing_enabled(self._clahe_enabled)

        # 設定予約後にWorkerの画像取得ループを再開する。
        self._worker.resume()

    @Slot(float)
    def set_exposure(self, value: float) -> None:
        """露光時間を保持し、プレビュー中はWorkerへ安全な更新を予約する。"""
        self._exposure = value
        if self._worker.isRunning():
            self._worker.request_exposure(value)
        else:
            self._camera.set_exposure(value)
        self.exposure_updated.emit(value)  # UI同期用

    @Slot(int)
    def set_gain(self, value: int) -> None:
        """Gainを保持し、プレビュー中はWorkerへ安全な更新を予約する。"""
        self._gain = value
        if self._worker.isRunning():
            self._worker.request_gain(value)
        else:
            self._camera.set_gain(value)
        self.gain_updated.emit(value)

    @Slot(bool)
    def set_clahe_enabled(self, enabled: bool) -> None:
        self._clahe_enabled = enabled
        self._worker.set_processing_enabled(enabled)
        self.clahe_enabled_updated.emit(enabled)

    @Slot(object)
    def process_captured_frame(self, frame: CapturedFrame | PreviewInput) -> None:
        """確定済み画像形式を持つ撮影frameをPreviewへ投入する。"""
        self._worker.submit_frame(frame)

    @Slot()
    def refresh_display(self) -> None:
        """表示refresh tickで最新のPreviewとGraph結果だけを反映する。"""
        self._worker.refresh_display()

    def set_display_refresh_rate(self, refresh_rate_hz: float) -> None:
        """active screenのrefresh rateを診断値へ反映する。"""
        self._worker.set_display_refresh_rate(refresh_rate_hz)

    def diagnostics_snapshot(self) -> PreviewDiagnostics:
        """Preview、Graph、表示の診断値を返す。"""
        return self._worker.diagnostics_snapshot()
