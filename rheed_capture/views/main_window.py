import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.settings import AppSettings
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.viewmodels.capture_viewmodel import CaptureViewModel
from rheed_capture.viewmodels.preview_viewmodel import PreviewViewModel
from rheed_capture.views.components.histogram_viewer import HistogramPanel
from rheed_capture.views.components.image_viewer import ImageViewer
from rheed_capture.views.components.preview_panel import PreviewPanel
from rheed_capture.views.components.sequence_panel import SequencePanel
from rheed_capture.views.components.storage_panel import StoragePanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    preview_vm: PreviewViewModel
    capture_vm: CaptureViewModel

    def __init__(self, camera: CameraDevice, storage: ExperimentStorage) -> None:
        super().__init__()
        self.camera = camera
        self.storage = storage
        self.capture_service = None

        self.setWindowTitle("RHEED Capture System")
        self.resize(1200, 700)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        self._setup_ui()
        self._setup_viewmodels()
        self._setup_bindings()
        self._load_settings()

        self.preview_vm.start_preview()

    def _setup_viewmodels(self) -> None:
        """ViewModelのインスタンス化"""
        self.preview_vm = PreviewViewModel(self.camera)
        self.capture_vm = CaptureViewModel(self.camera, self.storage)

    def _setup_ui(self) -> None:
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # 1. コンポーネントのインスタンス化
        self.image_viewer = ImageViewer()
        self.storage_panel = StoragePanel()
        self.preview_panel = PreviewPanel(
            self.camera.get_exposure_bounds(), self.camera.get_gain_bounds()
        )
        self.sequence_panel = SequencePanel()
        self.histogram_panel = HistogramPanel()

        self._update_storage_display()

        # 2. レイアウトへの配置
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        control_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        control_layout.setContentsMargins(0, 0, 0, 0)

        control_layout.addWidget(self.storage_panel)
        control_layout.addWidget(self.preview_panel)
        control_layout.addWidget(self.histogram_panel)
        control_layout.addWidget(self.sequence_panel)

        # === Splitterへ配置
        self.splitter.addWidget(self.image_viewer)
        self.splitter.addWidget(control_widget)

        # パネル側を優先して拡大するように設定
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        # 初期表示時の幅のバランス
        self.splitter.setSizes([720, 300])

        # 3. シグナルの結線
        self.storage_panel.browse_requested.connect(self._on_browse_root)
        self.storage_panel.new_branch_requested.connect(self._on_new_branch)

        self.sequence_panel.validation_error.connect(self._show_error)

    def _setup_bindings(self) -> None:
        """View と ViewModel のシグナル結線"""
        # ====== プレビュー関連の結線 ======
        # View -> ViewModel (操作の伝達)
        self.preview_panel.exposure_changed.connect(self.preview_vm.set_exposure)
        self.preview_panel.gain_changed.connect(self.preview_vm.set_gain)
        self.preview_panel.clahe_toggled.connect(self.preview_vm.set_clahe_enabled)

        # ViewModel -> View (状態・データの反映)
        self.preview_vm.image_ready.connect(self.image_viewer.update_image)
        self.preview_vm.histogram_ready.connect(self.histogram_panel.update_histogram)
        self.preview_vm.exposure_updated.connect(self.preview_panel.update_exposure_ui)
        self.preview_vm.gain_updated.connect(self.preview_panel.update_gain_ui)
        self.preview_vm.clahe_enabled_updated.connect(self.preview_panel.update_clahe_ui)
        self.preview_vm.error_occurred.connect(self._show_error)

        # ====== キャプチャ（シーケンス）関連の結線 ======
        # View -> 操作 -> MainWindowのオーケストレーションメソッドへ
        self.sequence_panel.start_requested.connect(self._on_start_sequence_requested)
        self.sequence_panel.cancel_requested.connect(self.capture_vm.cancel_sequence)

        # ViewModel -> View (進捗などの反映)
        self.capture_vm.progress_updated.connect(self.sequence_panel.update_progress)
        self.capture_vm.sequence_finished.connect(self._on_sequence_finished)
        self.capture_vm.error_occurred.connect(self._show_error)

    def _update_storage_display(self) -> None:
        self.storage_panel.update_displays(
            str(self.storage.root_dir), self.storage.get_current_experiment_dir().name
        )

    @Slot()
    def _on_browse_root(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Root Directory", str(self.storage.root_dir)
        )
        if dir_path:
            self.storage.set_root_dir(dir_path)
            self._update_storage_display()

    @Slot()
    def _on_new_branch(self) -> None:
        self.storage.increment_branch()
        self._update_storage_display()

        new_name = self.storage_panel.lbl_target_dir.text()
        QMessageBox.information(
            self, "Branch Updated", f"Next capture will be saved in:\n{new_name}"
        )

        msg = f"Branch Updated: Next capture will be saved in '{new_name}'"
        self.statusBar().showMessage(msg, 5000)

    @Slot(list, list)
    def _on_start_sequence_requested(self, expo_list: list[float], gain_list: list[int]) -> None:
        # UIをキャプチャ中の状態（ボタン無効化など）に変更
        self.sequence_panel.set_capturing_state(True)
        self.preview_panel.set_controls_enabled(False)

        self.capture_vm.set_conditions(expo_list, gain_list)

        # workerが停止処理を完了したら、captureを開始するように
        self.preview_vm.preview_paused.connect(
            self.capture_vm.start_sequence, Qt.ConnectionType.SingleShotConnection
        )
        self.preview_vm.pause_preview()

    @Slot(bool, str)
    def _on_sequence_finished(self, success: bool, saved_dir_name: str) -> None:
        self.sequence_panel.set_capturing_state(False)
        self.preview_panel.set_controls_enabled(True)

        self.preview_vm.resume_preview()
        if success:
            # ステータスバーに保存先を表示 (5000ミリ秒 = 5秒間で自動消去)
            msg = f"Capture Complete: Saved to '{saved_dir_name}'"
            self.status_bar.showMessage(msg, 10000)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def _load_settings(self) -> None:
        settings = AppSettings.load()
        if not settings:
            return

        if "root_dir" in settings:
            self.storage.set_root_dir(settings["root_dir"])
            self._update_storage_display()

        self.preview_vm.load_settings(settings)
        self.sequence_panel.set_values(
            settings.get("seq_expo_list", "10, 50, 100"), settings.get("seq_gain_list", "0")
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # キャプチャ中は終了をブロック
        if self.capture_vm.is_running():
            QMessageBox.warning(self, "Warning", "Cannot close while capturing.")
            event.ignore()
            return

        settings_to_save = {}
        settings_to_save.update(self.storage_panel.get_values())
        settings_to_save.update(self.preview_vm.get_settings_to_save())
        settings_to_save.update(self.sequence_panel.get_values())
        AppSettings.save(settings_to_save)

        # バックグラウンドスレッドの停止とカメラの切断
        self.preview_vm.stop_preview()
        self.camera.disconnect()

        event.accept()
