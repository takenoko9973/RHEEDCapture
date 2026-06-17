import logging

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.settings import AppSettings, AppSettingsData, PreviewSettings
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.viewmodels.angle_scan_viewmodel import AngleScanViewModel
from rheed_capture.viewmodels.capture_viewmodel import CaptureViewModel
from rheed_capture.viewmodels.preview_viewmodel import PreviewViewModel
from rheed_capture.views.components.angle_scan_panel import AngleScanPanel
from rheed_capture.views.components.histogram_viewer import HistogramPanel
from rheed_capture.views.components.image_viewer import ImageViewer
from rheed_capture.views.components.motor_settings_panel import MotorSettingsPanel
from rheed_capture.views.components.preview_panel import PreviewPanel
from rheed_capture.views.components.sequence_panel import SequencePanel
from rheed_capture.views.components.storage_panel import StoragePanel
from rheed_capture.views.grid_spec import DEFAULT_GRID_SHAPE

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    preview_vm: PreviewViewModel
    capture_vm: CaptureViewModel
    angle_scan_vm: AngleScanViewModel

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
        self._setup_sequence_preview_timer()
        self._load_settings()

        self.preview_vm.start_preview()

    def _setup_viewmodels(self) -> None:
        """ViewModelのインスタンス化"""
        self.preview_vm = PreviewViewModel(self.camera)
        self.capture_vm = CaptureViewModel(self.camera, self.storage)
        self.angle_scan_vm = AngleScanViewModel(self.camera, self.storage)

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
        self.angle_scan_panel = AngleScanPanel()
        self.motor_settings_panel = MotorSettingsPanel()
        self.capture_tabs = QTabWidget()
        self.capture_tabs.addTab(self.sequence_panel, "Sequence")
        self.capture_tabs.addTab(self.angle_scan_panel, "Angle Scan")
        self.control_tabs = QTabWidget()
        self.histogram_panel = HistogramPanel()

        self._update_storage_display()

        # 2. レイアウトへの配置
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        control_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        control_layout.setContentsMargins(0, 0, 0, 0)

        capture_tab = QWidget()
        capture_layout = QVBoxLayout(capture_tab)
        capture_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        capture_layout.setContentsMargins(0, 0, 0, 0)
        capture_layout.addWidget(self.preview_panel)
        capture_layout.addWidget(self.histogram_panel)
        capture_layout.addWidget(self.capture_tabs)

        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.addWidget(self.motor_settings_panel)

        self.control_tabs.addTab(capture_tab, "Capture")
        self.control_tabs.addTab(settings_tab, "Settings")
        control_layout.addWidget(self.storage_panel)
        control_layout.addWidget(self.control_tabs)

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

    def _setup_bindings(self) -> None:
        """View と ViewModel のシグナル結線"""
        self._setup_preview_bindings()
        self._setup_sequence_bindings()
        self._setup_angle_scan_bindings()
        self._setup_motor_settings_bindings()

    def _setup_preview_bindings(self) -> None:
        """プレビュー操作と表示更新の結線。"""
        self.preview_panel.exposure_changed.connect(self.preview_vm.set_exposure)
        self.preview_panel.gain_changed.connect(self.preview_vm.set_gain)
        self.preview_panel.clahe_toggled.connect(self.preview_vm.set_clahe_enabled)
        # CLAHE は worker 側の画像処理、Grid は viewer 側の表示オーバーレイとして扱う。
        self.preview_panel.grid_enabled_changed.connect(self.image_viewer.set_grid_enabled)
        self.preview_panel.grid_shape_changed.connect(self.image_viewer.set_grid_shape)

        self.preview_vm.image_ready.connect(self.image_viewer.update_image)
        self.preview_vm.histogram_ready.connect(self.histogram_panel.update_histogram)
        self.preview_vm.exposure_updated.connect(self.preview_panel.update_exposure_ui)
        self.preview_vm.gain_updated.connect(self.preview_panel.update_gain_ui)
        self.preview_vm.clahe_enabled_updated.connect(self.preview_panel.update_clahe_ui)
        self.preview_vm.error_occurred.connect(self._show_error)

    def _setup_sequence_bindings(self) -> None:
        """通常シーケンス撮影の結線。"""
        self.sequence_panel.expo_text_edited.connect(self.capture_vm.update_expo_from_text)
        self.sequence_panel.gain_text_edited.connect(self.capture_vm.update_gain_from_text)

        self.capture_vm.expo_text_updated.connect(self.sequence_panel.update_expo_ui)
        self.capture_vm.gain_text_updated.connect(self.sequence_panel.update_gain_ui)

        self.sequence_panel.start_requested.connect(self._on_start_sequence_requested)
        self.sequence_panel.cancel_requested.connect(self.capture_vm.cancel_sequence)

        self.capture_vm.progress_updated.connect(self.sequence_panel.update_progress)
        self.capture_vm.sequence_finished.connect(self._on_sequence_finished)
        self.capture_vm.error_occurred.connect(self._show_error)

    def _setup_angle_scan_bindings(self) -> None:
        """角度走査撮影の結線。"""
        self.angle_scan_panel.expo_text_edited.connect(self.angle_scan_vm.update_expo_from_text)
        self.angle_scan_panel.gain_text_edited.connect(self.angle_scan_vm.update_gain_from_text)
        self.angle_scan_panel.range_angle_changed.connect(self.angle_scan_vm.update_range_angle)
        self.angle_scan_panel.interval_angle_changed.connect(
            self.angle_scan_vm.update_interval_angle
        )
        self.angle_scan_panel.settling_time_changed.connect(
            self.angle_scan_vm.update_settling_time_ms
        )
        self.angle_scan_panel.motor_speed_changed.connect(self.angle_scan_vm.update_motor_speed)
        self.angle_scan_panel.return_to_start_changed.connect(
            self.angle_scan_vm.update_return_to_start
        )
        self.angle_scan_panel.scan_direction_changed.connect(self.angle_scan_vm.update_scan_direction)

        self.angle_scan_vm.expo_text_updated.connect(self.angle_scan_panel.update_expo_ui)
        self.angle_scan_vm.gain_text_updated.connect(self.angle_scan_panel.update_gain_ui)
        self.angle_scan_vm.range_angle_updated.connect(
            self.angle_scan_panel.update_range_angle_ui
        )
        self.angle_scan_vm.interval_angle_updated.connect(
            self.angle_scan_panel.update_interval_angle_ui
        )
        self.angle_scan_vm.settling_time_updated.connect(
            self.angle_scan_panel.update_settling_time_ui
        )
        self.angle_scan_vm.motor_speed_updated.connect(
            self.angle_scan_panel.update_motor_speed_ui
        )
        self.angle_scan_vm.return_to_start_updated.connect(
            self.angle_scan_panel.update_return_to_start_ui
        )
        self.angle_scan_vm.scan_direction_updated.connect(
            self.angle_scan_panel.update_scan_direction_ui
        )

        self.angle_scan_panel.start_requested.connect(self._on_start_angle_scan_requested)
        self.angle_scan_panel.cancel_requested.connect(self.angle_scan_vm.cancel_angle_scan)
        self.angle_scan_vm.progress_updated.connect(self.angle_scan_panel.update_progress)
        self.angle_scan_vm.angle_scan_finished.connect(self._on_angle_scan_finished)
        self.angle_scan_vm.error_occurred.connect(self._show_error)
        self._setup_angle_scan_preview_bindings()

    def _setup_motor_settings_bindings(self) -> None:
        """モーター装置設定の結線。"""
        self.motor_settings_panel.motor_port_edited.connect(self.angle_scan_vm.update_motor_port)
        self.motor_settings_panel.motor_slave_changed.connect(self.angle_scan_vm.update_motor_slave)
        self.motor_settings_panel.position_units_per_deg_changed.connect(
            self.angle_scan_vm.update_position_units_per_deg
        )
        self.angle_scan_vm.motor_port_updated.connect(
            self.motor_settings_panel.update_motor_port_ui
        )
        self.angle_scan_vm.motor_slave_updated.connect(
            self.motor_settings_panel.update_motor_slave_ui
        )
        self.angle_scan_vm.position_units_per_deg_updated.connect(
            self.motor_settings_panel.update_position_units_per_deg_ui
        )

    def _setup_angle_scan_preview_bindings(self) -> None:
        """角度走査中のプレビュー再開/停止要求を結線する。"""
        self.angle_scan_vm.preview_resume_requested.connect(self.preview_vm.resume_preview)
        self.angle_scan_vm.preview_pause_requested.connect(self.preview_vm.pause_preview)
        self.preview_vm.preview_paused.connect(self.angle_scan_vm.notify_preview_paused)

    def _setup_sequence_preview_timer(self) -> None:
        # 外部で image_xxx が削除/追加される運用に追従するため、定期的に再同期する。
        self._sequence_preview_timer = QTimer(self)
        self._sequence_preview_timer.setInterval(2000)
        self._sequence_preview_timer.timeout.connect(self._on_sequence_preview_timer)
        self._sequence_preview_timer.start()

    def _update_storage_display(self, *, refresh_counters: bool = True) -> None:
        # set_root_dir()直後のように既に再スキャン済みの場面では、
        # 不要なディスク走査を避けるため refresh_counters=False を使う。
        if refresh_counters:
            self.storage.refresh_capture_counters_from_disk()

        self.storage_panel.update_displays(
            str(self.storage.root_dir), self.storage.get_current_experiment_dir().name
        )
        self.sequence_panel.update_next_sequence_preview(self.storage.get_next_sequence_dir_name())
        self.angle_scan_panel.update_next_angle_scan_preview(
            self.storage.get_next_angle_scan_dir_name()
        )

    @Slot()
    def _on_sequence_preview_timer(self) -> None:
        # 撮影中は CaptureService 側でシーケンス番号を確定するため、ここで再スキャンしない。
        if self.capture_vm.is_running() or self.angle_scan_vm.is_running():
            return

        self._update_storage_display()

    @Slot()
    def _on_browse_root(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Root Directory", str(self.storage.root_dir)
        )
        if dir_path:
            self.storage.set_root_dir(dir_path)
            self._update_storage_display(refresh_counters=False)

    @Slot()
    def _on_new_branch(self) -> None:
        self.storage.increment_branch()
        self._update_storage_display(refresh_counters=False)

        new_name = self.storage_panel.lbl_target_dir.text()
        QMessageBox.information(
            self, "Branch Updated", f"Next capture will be saved in:\n{new_name}"
        )

        msg = f"Branch Updated: Next capture will be saved in '{new_name}'"
        self.statusBar().showMessage(msg, 5000)

    @Slot(list, list)
    def _on_start_sequence_requested(self) -> None:
        # UIをキャプチャ中の状態（ボタン無効化など）に変更
        self.sequence_panel.set_capturing_state(True)
        self.angle_scan_panel.setEnabled(False)
        self.motor_settings_panel.setEnabled(False)
        self.preview_panel.set_controls_enabled(False)
        self._sequence_preview_timer.stop()

        # workerが停止処理を完了したら、captureを開始するように
        self.preview_vm.preview_paused.connect(
            self.capture_vm.start_sequence, Qt.ConnectionType.SingleShotConnection
        )
        self.preview_vm.pause_preview()

    @Slot(bool, str)
    def _on_sequence_finished(self, success: bool, saved_dir_name: str) -> None:
        self.sequence_panel.set_capturing_state(False)
        self.angle_scan_panel.setEnabled(True)
        self.motor_settings_panel.setEnabled(True)
        self.preview_panel.set_controls_enabled(True)

        self.preview_vm.resume_preview()
        self._update_storage_display()
        self._sequence_preview_timer.start()
        if success:
            # ステータスバーに保存先を表示 (5000ミリ秒 = 5秒間で自動消去)
            msg = f"Capture Complete: Saved to '{saved_dir_name}'"
            self.status_bar.showMessage(msg, 10000)

    @Slot()
    def _on_start_angle_scan_requested(self) -> None:
        self.angle_scan_panel.set_capturing_state(True)
        self.sequence_panel.setEnabled(False)
        self.motor_settings_panel.setEnabled(False)
        self.preview_panel.set_controls_enabled(False)
        self._sequence_preview_timer.stop()

        self.preview_vm.preview_paused.connect(
            self.angle_scan_vm.start_angle_scan, Qt.ConnectionType.SingleShotConnection
        )
        self.preview_vm.pause_preview()

    @Slot(bool, str)
    def _on_angle_scan_finished(self, success: bool, saved_dir_name: str) -> None:
        self.angle_scan_panel.set_capturing_state(False)
        self.sequence_panel.setEnabled(True)
        self.motor_settings_panel.setEnabled(True)
        self.preview_panel.set_controls_enabled(True)

        self.preview_vm.resume_preview()
        self._update_storage_display()
        self._sequence_preview_timer.start()
        if success:
            msg = f"Angle Scan Complete: Saved to '{saved_dir_name}'"
            self.status_bar.showMessage(msg, 10000)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def _load_settings(self) -> None:
        settings = AppSettings.load()

        if settings.root_dir:
            self.storage.set_root_dir(settings.root_dir)
            self._update_storage_display(refresh_counters=False)

        self.preview_vm.load_settings(settings.preview)
        self.capture_vm.load_settings(settings.sequence_capture)
        self.angle_scan_vm.load_settings(settings)
        self._apply_grid_settings(settings.preview)

    def _apply_grid_settings(self, settings: PreviewSettings) -> None:
        # Grid は Panel(操作状態) と Viewer(描画状態) の両方へ同時反映する。
        default_rows, default_cols = DEFAULT_GRID_SHAPE
        grid_rows = settings.grid_rows or default_rows
        grid_cols = settings.grid_cols or default_cols
        show_grid = settings.show_grid
        self.preview_panel.apply_grid_settings(show_grid, grid_rows, grid_cols)
        self.image_viewer.set_grid_enabled(show_grid)
        self.image_viewer.set_grid_shape(grid_rows, grid_cols)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # キャプチャ中は終了をブロック
        if self.capture_vm.is_running() or self.angle_scan_vm.is_running():
            QMessageBox.warning(self, "Warning", "Cannot close while capturing.")
            event.ignore()
            return

        preview_settings = self.preview_vm.get_settings_to_save().with_grid(
            self.preview_panel.get_grid_settings_to_save()
        )
        settings_to_save = AppSettingsData(
            root_dir=self.storage_panel.get_settings_to_save().root_dir,
            preview=preview_settings,
            sequence_capture=self.capture_vm.get_settings_to_save(),
            angle_scan=self.angle_scan_vm.get_angle_scan_settings(),
            device=self.angle_scan_vm.get_device_settings(),
        )
        AppSettings.save(settings_to_save)

        self._sequence_preview_timer.stop()

        # バックグラウンドスレッドの停止とカメラの切断
        self.preview_vm.stop_preview()
        self.camera.disconnect()

        event.accept()
