import time

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from rheed_capture.models.domain.image_processor import ImageProcessor
from rheed_capture.models.hardware.camera_device import CameraDevice


class PreviewWorker(QThread):
    """プレビュー画像を別スレッドで継続的に取得・処理し、UIスレッドに送るワーカースレッド"""

    # 処理済みの画像 (UI表示用の8bit ndarray) を送るシグナル
    image_ready = Signal(np.ndarray)
    # 12bitヒストグラム配列と統計量を送るシグナル (hist_array, mean, std)
    histogram_ready = Signal(np.ndarray, float, float)

    error_occurred = Signal(str)  # エラー発生を通知するシグナル
    preview_paused = Signal()  # 一時停止を知らせるシグナル

    def __init__(self, camera_device: CameraDevice, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.camera_device = camera_device

        self._is_running = False
        self.enable_processing = False  # CLAHE処理のON/OFFフラグ

        self._pause_requested = False
        self._is_paused = False

    def run(self) -> None:
        """スレッドのメインループ"""
        self._is_running = True

        while self._is_running:
            # 一時停止の要求が来たらカメラを止めて報告する
            if self._pause_requested:
                self.camera_device.stop_grabbing()
                self._is_paused = True
                self._pause_requested = False
                self.preview_paused.emit()

            if self._is_paused:
                # 一時停止中はカメラにアクセスせず、短いスリープで待機
                time.sleep(0.1)
                continue

            self.camera_device.start_preview_grab()

            # 画像の取得 (タイムアウト短めでUI停止を防ぐ)
            expo_time = self.camera_device.get_exposure()
            raw_image = self.camera_device.retrieve_preview_frame(timeout_ms=int(expo_time + 500))

            if raw_image is None:
                continue

            try:
                # 12-bitデータ (0-4095) のヒストグラムを計算
                # カメラデータはMsbAlignedで4bit左シフトされているため、4bit右シフトで12bitに変換
                image_12bit = np.right_shift(raw_image, 4).ravel()
                mean_val = float(np.mean(image_12bit))
                std_val = float(np.std(image_12bit))
                hist, _ = np.histogram(image_12bit, range=(0, 4095), bins=256)
                self.histogram_ready.emit(hist, mean_val, std_val)

                # 画像処理
                display_image = (
                    ImageProcessor.apply_double_clahe(raw_image)  # CLAHEを2段適用
                    if self.enable_processing
                    else ImageProcessor.to_8bit_preview(raw_image)  # 8bitにスケーリング
                )

                # 結果の送信
                self.image_ready.emit(display_image)

            except Exception as e:  # noqa: BLE001
                self.error_occurred.emit(f"プレビュー更新エラー: {e}")

    def stop(self) -> None:
        """ループを終了し、スレッドの停止を要求する"""
        self._is_running = False

    def request_pause(self) -> None:
        """シーケンス撮影開始時などに、プレビューを一時停止させる"""
        self._pause_requested = True

    def resume(self) -> None:
        """シーケンス終了後にプレビューを再開させる"""
        self._is_paused = False

    def set_processing_enabled(self, enabled: bool) -> None:
        """画像処理のON/OFFを切り替える"""
        self.enable_processing = enabled
