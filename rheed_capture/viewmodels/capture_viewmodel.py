from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.services.capture_service import CaptureService


class CaptureViewModel(QObject):
    # View (UI) に公開するパススルー用シグナル
    progress_updated = Signal(int, int)  # (現在の枚数, 全体の枚数)
    sequence_finished = Signal(bool, str)  # (成功フラグ, 保存先ディレクトリ名)
    error_occurred = Signal(str)

    def __init__(self, camera: CameraDevice, storage: ExperimentStorage) -> None:
        super().__init__()
        self._camera = camera
        self._storage = storage
        self._capture_service: CaptureService | None = None

        # 撮影条件の状態保持
        self._expo_list: list[float] = []
        self._gain_list: list[int] = []

    def set_conditions(self, expo_list: list[float], gain_list: list[int]) -> None:
        """Viewから受け取った撮影条件をセットする"""
        self._expo_list = expo_list
        self._gain_list = gain_list

    @Slot()
    def start_sequence(self) -> None:
        """撮影スレッドを生成して開始"""
        # スレッドのインスタンス化 (実行のたびに作り直す設計を維持)
        self._capture_service = CaptureService(
            self._camera, self._storage, self._expo_list, self._gain_list
        )

        # 内部スレッドのシグナルをViewModelのシグナルに中継する
        self._capture_service.progress_update.connect(self.progress_updated)
        self._capture_service.sequence_finished.connect(self.sequence_finished)
        self._capture_service.error_occurred.connect(self.error_occurred)

        self._capture_service.start()

    @Slot()
    def cancel_sequence(self) -> None:
        """撮影のキャンセルを要求する"""
        if self.is_running() and self._capture_service:
            self._capture_service.cancel()

    def is_running(self) -> bool:
        """撮影スレッドが実行中かどうかを判定する"""
        return self._capture_service is not None and self._capture_service.isRunning()
