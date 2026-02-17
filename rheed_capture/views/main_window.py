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
from rheed_capture.services.capture_service import CaptureService
from rheed_capture.services.preview_worker import PreviewWorker
from rheed_capture.views.components.histogram_viewer import HistogramPanel
from rheed_capture.views.components.image_viewer import ImageViewer
from rheed_capture.views.components.preview_panel import PreviewPanel
from rheed_capture.views.components.sequence_panel import SequencePanel
from rheed_capture.views.components.storage_panel import StoragePanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
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
        self._start_preview()
        self._load_settings()

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

        self.preview_panel.exposure_changed.connect(self.camera.set_exposure)
        self.preview_panel.gain_changed.connect(self.camera.set_gain)

        self.sequence_panel.start_requested.connect(self._on_start_sequence_requested)
        self.sequence_panel.cancel_requested.connect(self._on_cancel_sequence)
        self.sequence_panel.validation_error.connect(self._show_error)

    def _start_preview(self) -> None:
        self.preview_worker = PreviewWorker(self.camera)
        self.preview_worker.image_ready.connect(self.image_viewer.update_image)
        self.preview_worker.histogram_ready.connect(self.histogram_panel.update_histogram)
        self.preview_worker.error_occurred.connect(self._show_error)

        self.preview_panel.clahe_toggled.connect(self.preview_worker.set_processing_enabled)

        # 初期パラメータを適用
        exp_dict = self.preview_panel.get_values()
        self.camera.set_exposure(exp_dict["preview_expo"])
        self.camera.set_gain(exp_dict["preview_gain"])
        self.preview_worker.set_processing_enabled(exp_dict["enable_clahe"])

        self.preview_worker.start()

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
        self.sequence_panel.set_capturing_state(True)
        self.preview_panel.set_controls_enabled(False)

        self._current_expo_list = expo_list
        self._current_gain_list = gain_list

        self.preview_worker.preview_paused.connect(
            self._start_capture_service_after_pause, Qt.ConnectionType.SingleShotConnection
        )
        self.preview_worker.request_pause()

    @Slot()
    def _start_capture_service_after_pause(self) -> None:
        self.capture_service = CaptureService(
            self.camera, self.storage, self._current_expo_list, self._current_gain_list
        )
        self.capture_service.progress_update.connect(self.sequence_panel.update_progress)
        self.capture_service.sequence_finished.connect(self._on_sequence_finished)
        self.capture_service.error_occurred.connect(self._show_error)
        self.capture_service.start()

    @Slot()
    def _on_cancel_sequence(self) -> None:
        if self.capture_service and self.capture_service.isRunning():
            self.capture_service.cancel()
            self.sequence_panel.btn_cancel.setEnabled(False)

    @Slot(bool, str)
    def _on_sequence_finished(self, success: bool, saved_dir_name: str) -> None:
        self.sequence_panel.set_capturing_state(False)
        self.preview_panel.set_controls_enabled(True)
        self.preview_worker.resume()
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

        self.preview_panel.set_values(
            settings.get("preview_expo", 50.0),
            settings.get("preview_gain", 0.0),
            settings.get("enable_clahe", False),
        )
        self.sequence_panel.set_values(
            settings.get("seq_expo_list", "10, 50, 100"), settings.get("seq_gain_list", "0")
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.capture_service and self.capture_service.isRunning():
            QMessageBox.warning(self, "Warning", "Cannot close while capturing.")
            event.ignore()
            return

        settings_to_save = {}
        settings_to_save.update(self.storage_panel.get_values())
        settings_to_save.update(self.preview_panel.get_values())
        settings_to_save.update(self.sequence_panel.get_values())
        AppSettings.save(settings_to_save)

        if hasattr(self, "preview_worker"):
            self.preview_worker.stop()
            self.preview_worker.wait(2000)

        self.camera.disconnect()
        event.accept()
