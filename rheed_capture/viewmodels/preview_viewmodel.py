import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.services.preview_worker import PreviewWorker


class PreviewViewModel(QObject):
    # === データパススルー用シグナル
    # 処理済みの画像 (UI表示用の8bit ndarray) を送るシグナル
    image_ready = Signal(np.ndarray)
    # 12bitヒストグラム配列と統計量を送るシグナル (hist_array, mean, std)
    histogram_ready = Signal(np.ndarray, float, float)
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
        self._worker.error_occurred.connect(self.error_occurred)
        self._worker.preview_paused.connect(self.preview_paused)

        # 状態の保持
        self._exposure = 50.0
        self._gain = 0
        self._clahe_enabled = False

    def load_settings(self, settings: dict) -> None:
        """設定ファイルから状態を復元し、システムに適用する"""
        self.set_exposure(settings.get("preview_expo", 50.0))
        self.set_gain(settings.get("preview_gain", 0))
        self.set_clahe_enabled(settings.get("enable_clahe", False))

    def get_settings_to_save(self) -> dict:
        """保存用の設定辞書を生成する"""
        return {
            "preview_expo": self._exposure,
            "preview_gain": self._gain,
            "enable_clahe": self._clahe_enabled,
        }

    def start_preview(self) -> None:
        """プレビュー開始"""
        self._worker.start()

    def stop_preview(self) -> None:
        """プレビュー停止 (終了処理)"""
        self._worker.stop()
        self._worker.wait(2000)

    def pause_preview(self) -> None:
        """シーケンス撮影開始などのため、プレビューを一時停止する"""
        self._worker.request_pause()

    def resume_preview(self) -> None:
        """
        プレビューを再開する。
        他サービスによって変更された可能性のあるカメラ設定を、
        ViewModelが保持している現在のプレビュー設定で上書き復元する。
        """
        # 1. カメラハードウェアの設定を復元
        self._camera.set_exposure(self._exposure)
        self._camera.set_gain(self._gain)
        self._worker.set_processing_enabled(self._clahe_enabled)

        # 2. Workerスレッドの画像取得ループを再開
        self._worker.resume()

    @Slot(float)
    def set_exposure(self, value: float) -> None:
        self._exposure = value
        self._camera.set_exposure(value)
        self.exposure_updated.emit(value)  # UI同期用

    @Slot(int)
    def set_gain(self, value: int) -> None:
        self._gain = value
        self._camera.set_gain(value)
        self.gain_updated.emit(value)

    @Slot(bool)
    def set_clahe_enabled(self, enabled: bool) -> None:
        self._clahe_enabled = enabled
        self._worker.set_processing_enabled(enabled)
        self.clahe_enabled_updated.emit(enabled)
