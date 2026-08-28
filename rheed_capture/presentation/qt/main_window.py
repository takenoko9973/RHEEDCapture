import logging
import math
from collections.abc import Callable
from typing import Any, cast

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rheed_capture.application.ports.motor import RotationMotor
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.infrastructure.config.json_store import AppSettings
from rheed_capture.infrastructure.config.schema import (
    AcquisitionSettings,
    AppSettingsData,
    PreviewSettings,
)
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.capture_coordinator import (
    CaptureCoordinator,
    CaptureCoordinatorHooks,
)
from rheed_capture.presentation.qt.diagnostics_dialog import DiagnosticsDialog
from rheed_capture.presentation.qt.panels.acquisition_settings import AcquisitionSettingsPanel
from rheed_capture.presentation.qt.panels.angle_scan import AngleScanPanel
from rheed_capture.presentation.qt.panels.capture_chips import CaptureChipsPanel
from rheed_capture.presentation.qt.panels.motor_settings import MotorSettingsPanel
from rheed_capture.presentation.qt.panels.preview import PreviewPanel
from rheed_capture.presentation.qt.panels.recording import RecordingPanel
from rheed_capture.presentation.qt.panels.recording_settings import RecordingSettingsPanel
from rheed_capture.presentation.qt.panels.sequence import SequencePanel
from rheed_capture.presentation.qt.panels.storage import StoragePanel
from rheed_capture.presentation.qt.viewmodels.acquisition_statistics import (
    format_preview_statistics,
    format_recording_statistics,
)
from rheed_capture.presentation.qt.viewmodels.angle_scan import AngleScanViewModel
from rheed_capture.presentation.qt.viewmodels.preview import PreviewViewModel
from rheed_capture.presentation.qt.viewmodels.recording import RecordingViewModel
from rheed_capture.presentation.qt.viewmodels.sequence import CaptureViewModel
from rheed_capture.presentation.qt.widgets.collapsible_section import CollapsibleSection
from rheed_capture.presentation.qt.widgets.grid_spec import DEFAULT_GRID_SHAPE
from rheed_capture.presentation.qt.widgets.histogram_viewer import HistogramPanel
from rheed_capture.presentation.qt.widgets.image_viewer import ImageViewer

logger = logging.getLogger(__name__)

BRANCH_STATUS_MESSAGE_MS = 5000
CAPTURE_COMPLETE_STATUS_MESSAGE_MS = 10000
ACQUISITION_STATISTICS_UI_INTERVAL_MS = 500
ACQUISITION_STATISTICS_MIN_WIDTH_PX = 220
ACQUISITION_STATISTICS_TOOLTIP = (
    "画像ペイロードの推定または取得値です。\n"
    "Ethernet、IP、UDP、GigE Visionのヘッダや再送分は含みません。"
)


def _display_interval_ms(refresh_rate_hz: float) -> int:
    """表示refresh rateを超えないQTimer間隔へ変換する。"""
    if refresh_rate_hz <= 0:
        msg = "Display refresh rate must be greater than zero."
        raise ValueError(msg)
    return max(1, math.ceil(1000.0 / refresh_rate_hz))


class MainWindow(QMainWindow):
    preview_vm: PreviewViewModel
    capture_vm: CaptureViewModel
    angle_scan_vm: AngleScanViewModel
    recording_vm: RecordingViewModel
    diagnostics_dialog: DiagnosticsDialog

    def __init__(
        self,
        camera: CameraDevice,
        storage: ExperimentStorage,
        motor_factory: Callable[[str, int, float], RotationMotor] | None = None,
    ) -> None:
        """カメラ、Storage、Motor factoryを受け取りMainWindowを構築する。"""
        super().__init__()
        self.camera = camera
        self.storage = storage
        self._motor_factory = motor_factory
        self.capture_coordinator = CaptureCoordinator()
        self.capture_service = None

        self.setWindowTitle("RHEED Capture System")
        self.resize(1200, 700)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        self.acquisition_statistics_label = QLabel()
        self.acquisition_statistics_label.setObjectName("acquisitionStatisticsLabel")
        self.acquisition_statistics_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        # 桁数が変わっても主要status messageの配置が動かない幅を確保する。
        self.acquisition_statistics_label.setMinimumWidth(
            ACQUISITION_STATISTICS_MIN_WIDTH_PX
        )
        self.acquisition_statistics_label.setToolTip(ACQUISITION_STATISTICS_TOOLTIP)
        self.status_bar.addPermanentWidget(self.acquisition_statistics_label)
        self.diagnostics_button = QPushButton("Diagnostics")
        self.diagnostics_button.setObjectName("diagnosticsButton")
        self.status_bar.addPermanentWidget(self.diagnostics_button)

        self._setup_ui()
        self._setup_viewmodels()
        self.diagnostics_dialog = DiagnosticsDialog(self)
        self.diagnostics_button.clicked.connect(self._toggle_diagnostics)
        self._setup_bindings()
        self._setup_sequence_preview_timer()
        self._setup_capture_coordinator()
        self._setup_acquisition_statistics_timer()
        self._setup_display_refresh_timer()
        self._load_settings()

        self.preview_vm.start_preview()

    def _setup_viewmodels(self) -> None:
        """ViewModelのインスタンス化"""
        self.preview_vm = PreviewViewModel(self.camera)
        self.capture_vm = CaptureViewModel(self.camera, self.storage)
        self.angle_scan_vm = AngleScanViewModel(
            self.camera,
            self.storage,
            motor_factory=self._motor_factory,
        )
        self.recording_vm = RecordingViewModel(self.camera, self.storage)

    def _setup_capture_coordinator(self) -> None:
        """撮影開始・終了時の共通UI操作をCoordinatorへ登録する。"""
        self.capture_coordinator.bind(
            CaptureCoordinatorHooks(
                set_sequence_capturing=self.sequence_panel.set_capturing_state,
                set_angle_scan_capturing=self.angle_scan_panel.set_capturing_state,
                set_recording_capturing=self.recording_panel.set_capturing_state,
                set_sequence_enabled=self.sequence_panel.setEnabled,
                set_angle_scan_enabled=self.angle_scan_panel.setEnabled,
                set_recording_enabled=self.recording_panel.setEnabled,
                set_recording_settings_enabled=self.recording_settings_panel.setEnabled,
                set_motor_settings_enabled=self.motor_settings_panel.setEnabled,
                set_acquisition_settings_enabled=(
                    self.acquisition_settings_panel.set_controls_enabled
                ),
                set_preview_controls_enabled=self.preview_panel.set_controls_enabled,
                stop_sequence_preview_timer=self._sequence_preview_timer.stop,
                start_sequence_preview_timer=self._sequence_preview_timer.start,
                pause_preview=self.preview_vm.pause_preview,
                resume_preview=self.preview_vm.resume_preview,
                refresh_storage_display=self._update_storage_display,
            )
        )

    def _setup_ui(self) -> None:  # noqa: PLR0915
        """MainWindowのWidget生成、配置、基本Signal接続を行う。"""
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
        self.recording_panel = RecordingPanel(
            self.camera.get_exposure_bounds(), self.camera.get_gain_bounds()
        )
        self.capture_chips_panel = CaptureChipsPanel()
        self.motor_settings_panel = MotorSettingsPanel()
        self.acquisition_settings_panel = AcquisitionSettingsPanel()
        self.recording_settings_panel = RecordingSettingsPanel()
        self.capture_tabs = QTabWidget()
        self.capture_tabs.addTab(self.sequence_panel, "Sequence")
        self.capture_tabs.addTab(self.angle_scan_panel, "Angle Scan")
        self.capture_tabs.addTab(self.recording_panel, "Recording")
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
        settings_layout.setSpacing(4)

        capture_settings_content = QWidget()
        capture_settings_layout = QVBoxLayout(capture_settings_content)
        capture_settings_layout.setContentsMargins(0, 0, 0, 0)
        capture_settings_layout.setSpacing(4)
        capture_settings_layout.addWidget(self.capture_chips_panel)
        capture_settings_layout.addWidget(self.acquisition_settings_panel)
        self.capture_settings_section = CollapsibleSection(
            "Capture",
            capture_settings_content,
            expanded=True,
        )

        recording_settings_content = QWidget()
        recording_settings_layout = QVBoxLayout(recording_settings_content)
        recording_settings_layout.setContentsMargins(0, 0, 0, 0)
        recording_settings_layout.addWidget(self.recording_settings_panel)
        self.recording_settings_section = CollapsibleSection(
            "Recording",
            recording_settings_content,
            expanded=False,
        )

        motor_settings_content = QWidget()
        motor_settings_layout = QVBoxLayout(motor_settings_content)
        motor_settings_layout.setContentsMargins(0, 0, 0, 0)
        motor_settings_layout.addWidget(self.motor_settings_panel)
        self.motor_settings_section = CollapsibleSection(
            "Motor",
            motor_settings_content,
            expanded=False,
        )

        settings_layout.addWidget(self.capture_settings_section)
        settings_layout.addWidget(self.recording_settings_section)
        settings_layout.addWidget(self.motor_settings_section)
        settings_layout.addStretch(1)

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
        self._setup_recording_bindings()
        self._setup_acquisition_settings_bindings()
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
        self.preview_vm.image_format_updated.connect(
            self.histogram_panel.set_sensor_bit_depth
        )
        self.preview_vm.exposure_updated.connect(self.preview_panel.update_exposure_ui)
        self.preview_vm.gain_updated.connect(self.preview_panel.update_gain_ui)
        self.preview_vm.clahe_enabled_updated.connect(self.preview_panel.update_clahe_ui)
        self.preview_vm.error_occurred.connect(self._show_error)

    def _setup_sequence_bindings(self) -> None:
        """通常シーケンス撮影の結線。"""
        # パネルはチップの選択値だけを通知する。
        self.sequence_panel.exposure_selection_changed.connect(
            self.capture_vm.update_selected_exposure_ms_values
        )
        self.sequence_panel.gain_selection_changed.connect(
            self.capture_vm.update_selected_gain_values
        )
        self.capture_vm.exposure_values_updated.connect(
            self.sequence_panel.update_exposure_values
        )
        self.capture_vm.gain_values_updated.connect(self.sequence_panel.update_gain_values)

        self.sequence_panel.start_requested.connect(self._on_start_sequence_requested)
        self.sequence_panel.cancel_requested.connect(self.capture_vm.cancel_sequence)

        self.capture_vm.progress_updated.connect(self.sequence_panel.update_progress)
        # 受信側はmailbox投入だけなので、capture threadから直接呼び出してGUI eventを蓄積しない。
        self.capture_vm.frame_captured.connect(
            self.preview_vm.process_captured_frame,
            Qt.ConnectionType.DirectConnection,
        )
        self.capture_vm.sequence_finished.connect(self._on_sequence_finished)
        self.capture_vm.error_occurred.connect(self._show_error)

    def _setup_angle_scan_bindings(self) -> None:
        """角度走査撮影の結線。"""
        # Angle Scanの選択状態は専用ViewModelで保持する。
        self.angle_scan_panel.exposure_selection_changed.connect(
            self.angle_scan_vm.update_selected_exposure_ms_values
        )
        self.angle_scan_panel.gain_selection_changed.connect(
            self.angle_scan_vm.update_selected_gain_values
        )
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

        self.angle_scan_vm.exposure_values_updated.connect(
            self.angle_scan_panel.update_exposure_values
        )
        self.angle_scan_vm.gain_values_updated.connect(
            self.angle_scan_panel.update_gain_values
        )
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
        self.angle_scan_vm.frame_captured.connect(
            self.preview_vm.process_captured_frame,
            Qt.ConnectionType.DirectConnection,
        )
        self.angle_scan_vm.angle_scan_finished.connect(self._on_angle_scan_finished)
        self.angle_scan_vm.error_occurred.connect(self._show_error)
        self._setup_angle_scan_preview_bindings()

    def _setup_recording_bindings(self) -> None:
        """録画撮影の結線。"""
        self.recording_panel.exposure_changed.connect(self.recording_vm.update_exposure_ms)
        self.recording_panel.gain_changed.connect(self.recording_vm.update_gain)
        self.recording_panel.rate_mode_changed.connect(self.recording_vm.update_rate_mode)
        self.recording_panel.fps_changed.connect(self.recording_vm.update_fps)
        self.recording_panel.interval_changed.connect(self.recording_vm.update_interval_ms)
        self.recording_panel.duration_changed.connect(self.recording_vm.update_duration_sec)
        self.recording_settings_panel.tiff_compression_changed.connect(
            self.recording_vm.update_tiff_compression_enabled
        )

        self.recording_panel.start_requested.connect(self._on_start_recording_requested)
        self.recording_panel.stop_requested.connect(self.recording_vm.stop_recording)

        self.recording_vm.saved_frames_updated.connect(
            self.recording_panel.update_saved_frames
        )
        self.recording_vm.expected_frames_updated.connect(
            self.recording_panel.update_expected_frames
        )
        self.recording_vm.frame_captured.connect(
            self.preview_vm.process_captured_frame,
            Qt.ConnectionType.DirectConnection,
        )
        self.recording_vm.recording_finished.connect(self._on_recording_finished)
        self.recording_vm.error_occurred.connect(self._show_error)

    def _setup_acquisition_settings_bindings(self) -> None:
        """共通Acquisition設定の変更をPreviewとRecordingへ伝播する。"""
        self.acquisition_settings_panel.settings_changed.connect(
            self._on_acquisition_settings_changed
        )

    @Slot(object)
    def _on_acquisition_settings_changed(self, settings: AcquisitionSettings) -> None:
        """Acquisition設定をPreviewへ渡し、Hardware時のrate入力をlockする。"""
        self.preview_vm.set_acquisition_settings(settings)
        self.recording_vm.set_acquisition_settings(settings)
        self.recording_panel.set_hardware_mode(settings.mode)
        current_settings = self._build_current_settings(settings)
        self.capture_vm.load_settings(current_settings)
        self.angle_scan_vm.load_settings(current_settings)

    def _build_current_settings(
        self,
        acquisition: AcquisitionSettings | None = None,
    ) -> AppSettingsData:
        """現在のUIとViewModel状態から撮影設定snapshotを作る。"""
        return AppSettingsData(
            root_dir=self.storage_panel.get_settings_to_save().root_dir,
            exposure_ms_values=self.capture_chips_panel.exposure_ms_values(),
            gain_values=self.capture_chips_panel.gain_values(),
            preview=self.preview_vm.get_settings_to_save(),
            acquisition=(
                acquisition
                if acquisition is not None
                else self.acquisition_settings_panel.get_settings_to_save()
            ),
            sequence_capture=self.capture_vm.get_settings_to_save(),
            angle_scan=self.angle_scan_vm.get_angle_scan_settings(),
            recording_capture=self.recording_vm.get_settings_to_save(),
            device=self.angle_scan_vm.get_device_settings(),
        )

    def _setup_motor_settings_bindings(self) -> None:
        """モーター装置設定の結線。"""
        # 候補値変更は両撮影モードへ反映する。
        self.capture_chips_panel.exposure_values_changed.connect(
            self._on_exposure_values_changed
        )
        self.capture_chips_panel.gain_values_changed.connect(self._on_gain_values_changed)
        self.capture_chips_panel.error_occurred.connect(self._show_error)
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
        """保存先番号プレビューを定期更新するTimerを開始する。"""
        # 外部で image_xxx が削除/追加される運用に追従するため、定期的に再同期する。
        self._sequence_preview_timer = QTimer(self)
        self._sequence_preview_timer.setInterval(2000)
        self._sequence_preview_timer.timeout.connect(self._on_sequence_preview_timer)
        self._sequence_preview_timer.start()

    def _setup_acquisition_statistics_timer(self) -> None:
        """summaryとvisibleなDiagnosticsを500 ms間隔で更新する。"""
        self._acquisition_statistics_timer = QTimer(self)
        self._acquisition_statistics_timer.setInterval(
            ACQUISITION_STATISTICS_UI_INTERVAL_MS
        )
        self._acquisition_statistics_timer.timeout.connect(
            self._update_acquisition_statistics_display
        )
        self._acquisition_statistics_timer.start()

    def _setup_display_refresh_timer(self) -> None:
        """active QScreenのrefresh rateで表示結果をpullするTimerを設定する。"""
        self._display_refresh_timer = QTimer(self)
        self._display_refresh_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._display_refresh_timer.timeout.connect(self.preview_vm.refresh_display)
        self._active_display_hz = 0.0
        self._display_screen: object | None = None
        self._display_refresh_signal: object | None = None
        self._display_window_handle: object | None = None
        self._bind_display_screen()

    def _bind_display_screen(self) -> None:
        """MainWindowのscreenChangedを接続し、現在screenを同期する。"""
        window_handle = self.windowHandle()
        if window_handle is not None and window_handle is not self._display_window_handle:
            window_handle.screenChanged.connect(self._on_display_screen_changed)
            self._display_window_handle = window_handle

        active_screen = self.screen()
        if active_screen is not self._display_screen:
            self._on_display_screen_changed(active_screen)
        elif active_screen is not None:
            self._on_display_refresh_rate_changed()

    def _on_display_screen_changed(self, screen: object | None) -> None:
        """screen移動時にrefresh rate signalと表示Timerを切り替える。"""
        if self._display_refresh_signal is not None:
            cast("Any", self._display_refresh_signal).disconnect(
                self._on_display_refresh_rate_changed
            )
            self._display_refresh_signal = None

        self._display_screen = screen
        if screen is None:
            self._display_refresh_timer.stop()
            self._active_display_hz = 0.0
            self.preview_vm.set_display_refresh_rate(0.0)
            return

        refresh_signal = getattr(screen, "refreshRateChanged", None)
        if refresh_signal is not None:
            refresh_signal.connect(self._on_display_refresh_rate_changed)
            self._display_refresh_signal = refresh_signal
        self._on_display_refresh_rate_changed()

    def _on_display_refresh_rate_changed(self, refresh_rate_hz: float | None = None) -> None:
        """refresh rate変更をTimer間隔とPreview診断値へ反映する。"""
        if refresh_rate_hz is None:
            screen = self._display_screen
            if screen is None:
                return
            refresh_rate_hz = float(cast("Any", screen).refreshRate())

        if refresh_rate_hz <= 0:
            self._display_refresh_timer.stop()
            self._active_display_hz = 0.0
            self.preview_vm.set_display_refresh_rate(0.0)
            return

        self._active_display_hz = float(refresh_rate_hz)
        self._display_refresh_timer.setInterval(
            _display_interval_ms(self._active_display_hz)
        )
        self.preview_vm.set_display_refresh_rate(self._active_display_hz)
        if not self._display_refresh_timer.isActive():
            self._display_refresh_timer.start()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """表示後に確定したnative windowのactive screenを再同期する。"""
        super().showEvent(event)
        self._bind_display_screen()

    @Slot()
    def _update_acquisition_statistics_display(self) -> None:
        """既存snapshotからsummaryを更新し、visibleなDiagnosticsへ値を渡す。"""
        active_mode = self.capture_coordinator.active_mode
        diagnostics = self.preview_vm.diagnostics_snapshot()
        statistics = None
        if active_mode == "recording":
            statistics = self.recording_vm.acquisition_statistics_snapshot()
            text = (
                format_recording_statistics(statistics, diagnostics)
                if statistics is not None
                else ""
            )
        elif active_mode is None:
            statistics = self.preview_vm.acquisition_statistics_snapshot()
            text = (
                format_preview_statistics(statistics, diagnostics)
                if statistics is not None
                else ""
            )
        else:
            # SequenceとAngle Scanでは取得統計を表示しない。
            text = ""
        self.acquisition_statistics_label.setText(text)
        if self.diagnostics_dialog.isVisible():
            self.diagnostics_dialog.update_values(active_mode, statistics, diagnostics)

    def _toggle_diagnostics(self) -> None:
        """Diagnostics Dialogを追加生成せずmodelessに表示・非表示する。"""
        if self.diagnostics_dialog.isVisible():
            self.diagnostics_dialog.hide()
            return
        self.diagnostics_dialog.show()
        self.diagnostics_dialog.raise_()
        self.diagnostics_dialog.activateWindow()

    def _update_storage_display(self, *, refresh_counters: bool = True) -> None:
        """Storage状態を各Panelの保存先プレビューへ反映する。"""
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
        self.recording_panel.update_next_recording_preview(
            self.storage.get_next_recording_dir_name()
        )

    @Slot()
    def _on_sequence_preview_timer(self) -> None:
        """撮影中でなければ保存先番号プレビューを更新する。"""
        # 撮影中は CaptureService 側でシーケンス番号を確定するため、ここで再スキャンしない。
        if self.capture_coordinator.is_capturing():
            return

        self._update_storage_display()

    @Slot()
    def _on_browse_root(self) -> None:
        """保存ルート選択Dialogを開き、Storageへ反映する。"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Root Directory", str(self.storage.root_dir)
        )
        if dir_path:
            self.storage.set_root_dir(dir_path)
            self._update_storage_display(refresh_counters=False)

    @Slot()
    def _on_new_branch(self) -> None:
        """手動branch更新を実行し、保存先表示とStatusを更新する。"""
        self.storage.increment_branch()
        self._update_storage_display(refresh_counters=False)

        new_name = self.storage_panel.lbl_target_dir.text()
        QMessageBox.information(
            self, "Branch Updated", f"Next capture will be saved in:\n{new_name}"
        )

        msg = f"Branch Updated: Next capture will be saved in '{new_name}'"
        self.statusBar().showMessage(msg, BRANCH_STATUS_MESSAGE_MS)

    @Slot(list, list)
    def _on_start_sequence_requested(self) -> None:
        """Sequence開始要求をCoordinatorへ渡す。"""
        self.acquisition_statistics_label.clear()
        self.capture_coordinator.begin_sequence(
            self._arm_sequence_start_after_preview_pause
        )

    def _arm_sequence_start_after_preview_pause(self) -> None:
        """PreviewWorkerの停止完了を待ってからSequence Workerを開始する。"""
        self.preview_vm.preview_paused.connect(
            self.capture_vm.start_sequence,
            Qt.ConnectionType.SingleShotConnection,
        )

    @Slot()
    def _on_start_recording_requested(self) -> None:
        """Recording開始要求をCoordinatorへ渡す。"""
        self.acquisition_statistics_label.clear()
        self.capture_coordinator.begin_recording(
            self._arm_recording_start_after_preview_pause
        )

    def _arm_recording_start_after_preview_pause(self) -> None:
        """PreviewWorkerの停止完了を待ってからRecording Workerを開始する。"""
        self.preview_vm.preview_paused.connect(
            self.recording_vm.start_recording,
            Qt.ConnectionType.SingleShotConnection,
        )

    @Slot(bool, str)
    def _on_sequence_finished(self, success: bool, saved_dir_name: str) -> None:
        """Sequence終了後にUI状態を戻し、成功時は保存先を表示する。"""
        self.capture_coordinator.leave()
        if success:
            # 完了通知は撮影結果をユーザーが確認できる程度に長めに表示する。
            msg = f"Capture Complete: Saved to '{saved_dir_name}'"
            self.status_bar.showMessage(msg, CAPTURE_COMPLETE_STATUS_MESSAGE_MS)

    @Slot()
    def _on_start_angle_scan_requested(self) -> None:
        """Angle Scan開始要求をCoordinatorへ渡す。"""
        self.acquisition_statistics_label.clear()
        self.capture_coordinator.begin_angle_scan(self.angle_scan_vm.start_angle_scan)

    @Slot(bool, str)
    def _on_angle_scan_finished(self, success: bool, saved_dir_name: str) -> None:
        """Angle Scan終了後にUI状態を戻し、成功時は保存先を表示する。"""
        self.capture_coordinator.leave()
        if success:
            msg = f"Angle Scan Complete: Saved to '{saved_dir_name}'"
            self.status_bar.showMessage(msg, CAPTURE_COMPLETE_STATUS_MESSAGE_MS)

    @Slot(bool, str)
    def _on_recording_finished(self, success: bool, saved_dir_name: str) -> None:
        """Recording終了後にUI状態を戻し、成功時は保存先を表示する。"""
        self.acquisition_statistics_label.clear()
        self.capture_coordinator.leave()
        if success:
            msg = f"Recording Finished: Saved to '{saved_dir_name}'"
            self.status_bar.showMessage(msg, CAPTURE_COMPLETE_STATUS_MESSAGE_MS)

    @Slot(str)
    def _show_error(self, message: str) -> None:
        """ユーザーへエラーダイアログを表示する。"""
        QMessageBox.critical(self, "Error", message)

    def _load_settings(self) -> None:
        """保存済み設定を読み込み、各PanelとViewModelへ反映する。"""
        settings = AppSettings.load()

        if settings.root_dir:
            self.storage.set_root_dir(settings.root_dir)
            self._update_storage_display(refresh_counters=False)

        self.preview_vm.load_settings(settings.preview)
        # 候補値を表示してから、各撮影ViewModelへ選択状態を流す。
        self.capture_chips_panel.set_values(settings.exposure_ms_values, settings.gain_values)
        self.capture_vm.load_settings(settings)
        self.angle_scan_vm.load_settings(settings)
        self.acquisition_settings_panel.apply_settings(settings.acquisition)
        self.preview_vm.load_acquisition_settings(settings.acquisition)
        self.recording_vm.load_acquisition_settings(settings.acquisition)
        self.recording_panel.set_hardware_mode(settings.acquisition.mode)
        self.recording_panel.apply_settings(settings.recording_capture)
        self.recording_settings_panel.apply_settings(settings.recording_capture)
        self.recording_vm.load_settings(settings.recording_capture)
        self._apply_grid_settings(settings.preview)

    @Slot(list)
    def _on_exposure_values_changed(self, exposure_ms_values: list[float]) -> None:
        """露光時間候補の変更を、両撮影モードのチップ候補へ伝播する。"""
        gain_values = self.capture_chips_panel.gain_values()
        self.capture_vm.update_candidate_values(exposure_ms_values, gain_values)
        self.angle_scan_vm.update_candidate_values(exposure_ms_values, gain_values)

    @Slot(list)
    def _on_gain_values_changed(self, gain_values: list[int]) -> None:
        """ゲイン候補の変更を、両撮影モードのチップ候補へ伝播する。"""
        exposure_ms_values = self.capture_chips_panel.exposure_ms_values()
        self.capture_vm.update_candidate_values(exposure_ms_values, gain_values)
        self.angle_scan_vm.update_candidate_values(exposure_ms_values, gain_values)

    def _apply_grid_settings(self, settings: PreviewSettings) -> None:
        """保存済みGrid設定をPreview PanelとImage Viewerへ反映する。"""
        # Grid は Panel(操作状態) と Viewer(描画状態) の両方へ同時反映する。
        default_rows, default_cols = DEFAULT_GRID_SHAPE
        grid_rows = settings.grid_rows or default_rows
        grid_cols = settings.grid_cols or default_cols
        show_grid = settings.show_grid
        self.preview_panel.apply_grid_settings(show_grid, grid_rows, grid_cols)
        self.image_viewer.set_grid_enabled(show_grid)
        self.image_viewer.set_grid_shape(grid_rows, grid_cols)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """終了時に設定保存、Preview停止、カメラ切断を行う。"""
        # キャプチャ中は終了をブロック
        if self.capture_coordinator.is_capturing():
            QMessageBox.warning(self, "Warning", "Cannot close while capturing.")
            event.ignore()
            return

        # top-level QDialogはMainWindowのcloseだけでは非表示にならないため、受理時に明示的に閉じる。
        self.diagnostics_dialog.close()

        preview_settings = self.preview_vm.get_settings_to_save().with_grid(
            self.preview_panel.get_grid_settings_to_save()
        )
        settings_to_save = AppSettingsData(
            root_dir=self.storage_panel.get_settings_to_save().root_dir,
            # 候補値と撮影モード別の選択状態をまとめて保存する。
            exposure_ms_values=self.capture_chips_panel.exposure_ms_values(),
            gain_values=self.capture_chips_panel.gain_values(),
            preview=preview_settings,
            acquisition=self.acquisition_settings_panel.get_settings_to_save(),
            sequence_capture=self.capture_vm.get_settings_to_save(),
            angle_scan=self.angle_scan_vm.get_angle_scan_settings(),
            recording_capture=self.recording_vm.get_settings_to_save(),
            device=self.angle_scan_vm.get_device_settings(),
        )
        AppSettings.save(settings_to_save)

        self._sequence_preview_timer.stop()
        self._acquisition_statistics_timer.stop()
        self._display_refresh_timer.stop()

        # バックグラウンドスレッドの停止とカメラの切断
        self.preview_vm.stop_preview()
        self.camera.disconnect()

        event.accept()
