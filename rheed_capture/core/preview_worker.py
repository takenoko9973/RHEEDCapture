import time

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from rheed_capture.core.camera_device import CameraDevice
from rheed_capture.core.image_processor import ImageProcessor


class PreviewWorker(QThread):
    """プレビュー画像を別スレッドで継続的に取得・処理し、UIスレッドに送るワーカースレッド"""

    # 処理済みの画像 (UI表示用の8bit ndarray) を送るシグナル
    image_ready = Signal(np.ndarray)
    # エラー発生を通知するシグナル
    error_occurred = Signal(str)

    def __init__(self, camera_device: CameraDevice, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.camera_device = camera_device
        self._is_running = False
        self.enable_processing = False  # CLAHE処理のON/OFFフラグ

    def run(self) -> None:
        """スレッドのメインループ"""
        self._is_running = True

        while self._is_running:
            # 画像の取得 (タイムアウト短めでUI停止を防ぐ)
            raw_image = self.camera_device.retrieve_preview_frame(timeout_ms=500)

            if raw_image is not None:
                try:
                    # 画像処理
                    if self.enable_processing:
                        # CLAHEを2段適用
                        display_image = ImageProcessor.apply_double_clahe(raw_image)
                    else:
                        # 未処理時もプレビュー表示用に8bitにスケーリング
                        display_image = (raw_image / 16).astype(np.uint8)

                    # シグナルでUIへ送信
                    self.image_ready.emit(display_image)

                except Exception as e:  # noqa: BLE001
                    self.error_occurred.emit(f"画像処理エラー: {e}")

            # CPU負荷を下げるための微小なスリープ (約30fpsを上限とする)
            time.sleep(0.03)

    def stop(self) -> None:
        """ループを終了し、スレッドの停止を要求する"""
        self._is_running = False

    def set_processing_enabled(self, enabled: bool) -> None:
        """画像処理のON/OFFを切り替える"""
        self.enable_processing = enabled
