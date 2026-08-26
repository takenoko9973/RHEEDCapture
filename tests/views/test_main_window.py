import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal
from pytestqt.qtbot import QtBot

from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.infrastructure.config.schema import (
    AngleScanCaptureSettings,
    AppSettingsData,
    DeviceSettings,
    MotorDeviceSettings,
    PreviewSettings,
    RecordingCaptureSettings,
    SequenceCaptureSettings,
)
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.main_window import (
    ACQUISITION_STATISTICS_TOOLTIP,
    ACQUISITION_STATISTICS_UI_INTERVAL_MS,
    MainWindow,
)
from rheed_capture.presentation.qt.workers.recording_service import RecordingService


class _FakeScreen(QObject):
    """表示refresh rate変更を再現するQScreen相当のdouble。"""

    refreshRateChanged = Signal(float)  # noqa: N815

    def __init__(self, rate_hz: float) -> None:
        """初期refresh rateを保持する。"""
        super().__init__()
        self.rate_hz = rate_hz

    def refreshRate(self) -> float:  # noqa: N802
        """現在のrefresh rateを返す。"""
        return self.rate_hz


@pytest.fixture
def mock_camera() -> MagicMock:
    """MainWindowテスト用のCamera mockを作る。"""
    camera = MagicMock(spec=CameraDevice)

    def mock_retrieve(*args, **kwargs) -> None:  # noqa: ARG001
        """Preview取得待ちを短時間だけ再現する。"""
        time.sleep(0.01)

    camera.retrieve_preview_frame.side_effect = mock_retrieve
    camera.get_exposure_bounds.return_value = (1, 10000)
    camera.get_gain_bounds.return_value = (0, 48)
    return camera


@pytest.fixture
def mock_storage() -> MagicMock:
    """MainWindowテスト用のStorage mockを作る。"""
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("dummy/root")
    mock_dir = MagicMock(spec=Path)
    mock_dir.name = "260215"
    storage.get_current_experiment_dir.return_value = mock_dir
    storage.get_next_sequence_dir_name.return_value = "image_001"
    storage.get_next_angle_scan_dir_name.return_value = "angle_scan_001"
    storage.get_next_recording_dir_name.return_value = "record-1"
    storage.increment_branch.return_value = "260215-2"
    return storage


@pytest.fixture(autouse=True)
def mock_settings() -> types.GeneratorType:
    """AppSettings.load/saveをテスト用設定に差し替える。"""
    with patch("rheed_capture.presentation.qt.main_window.AppSettings") as mock_app_settings:
        mock_app_settings.load.return_value = AppSettingsData(
            root_dir="dummy/root",
            exposure_ms_values=[10.0, 20.0],
            gain_values=[0, 1],
            preview=PreviewSettings(
                exposure_ms=15.5,
                gain=2,
                enable_clahe=True,
                show_grid=True,
                grid_rows=8,
                grid_cols=8,
            ),
            sequence_capture=SequenceCaptureSettings(
                selected_exposure_ms_values=[10.0, 20.0],
                selected_gain_values=[0, 1],
            ),
            angle_scan=AngleScanCaptureSettings(
                selected_exposure_ms_values=[10.0],
                selected_gain_values=[0],
                range_deg=5.0,
                direction="both",
                motor_speed_rpm=4.0,
            ),
            recording_capture=RecordingCaptureSettings(
                exposure_ms=25.0,
                gain=1,
                rate_mode="fps",
                fps=40.0,
                interval_ms=25.0,
                duration_sec=5.0,
                tiff_compression_enabled=False,
            ),
            device=DeviceSettings(
                motor=MotorDeviceSettings(
                    port="COM8",
                    slave=3,
                    position_units_per_deg=31.25,
                )
            ),
        )
        yield mock_app_settings


def test_main_window_initialization(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """保存済み設定がMainWindowの各Panelへ反映されることを確認する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    assert window.preview_panel.spin_expo.value() == 15.5
    assert window.preview_panel.chk_show_grid.isChecked() is True
    assert window.preview_panel.cmb_grid_shape.currentText() == "8x8"
    assert window.capture_chips_panel.edit_exposure_values.text() == "10, 20"
    assert window.capture_chips_panel.edit_gain_values.text() == "0, 1"
    assert window.sequence_panel.exposure_selector.selected_values() == [10.0, 20.0]
    assert window.sequence_panel.gain_selector.selected_values() == [0, 1]
    assert window.angle_scan_panel.exposure_selector.selected_values() == [10.0]
    assert window.angle_scan_panel.gain_selector.selected_values() == [0]
    assert window.angle_scan_panel.spin_range_deg.value() == 5.0
    assert window.angle_scan_panel.btn_direction_both.isChecked() is True
    assert window.angle_scan_panel.spin_motor_speed_rpm.value() == 4.0
    assert window.motor_settings_panel.edit_motor_port.text() == "COM8"
    assert window.motor_settings_panel.spin_motor_slave.value() == 3
    assert window.motor_settings_panel.spin_position_units_per_deg.value() == 31.25
    assert window.control_tabs.count() == 2
    assert window.control_tabs.tabText(0) == "Capture"
    assert window.control_tabs.tabText(1) == "Settings"
    assert window.capture_tabs.count() == 3
    assert window.capture_tabs.tabText(0) == "Sequence"
    assert window.capture_tabs.tabText(1) == "Angle Scan"
    assert window.capture_tabs.tabText(2) == "Recording"
    assert window.recording_panel.spin_exposure_ms.value() == 25.0
    assert window.recording_panel.spin_gain.value() == 1
    assert window.recording_panel.btn_rate_fps.isChecked() is True
    assert window.recording_panel.rate_value_stack.currentWidget() is (
        window.recording_panel.spin_fps
    )
    assert window.recording_settings_panel.chk_tiff_compression.isChecked() is False
    assert window.recording_vm.get_settings_to_save().tiff_compression_enabled is False
    assert window.capture_settings_section.toggle_button.text() == "Capture"
    assert window.recording_settings_section.toggle_button.text() == "Recording"
    assert window.motor_settings_section.toggle_button.text() == "Motor"
    window.close()


def test_main_window_close_immediately_stops_preview_worker(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """生成直後の終了要求でもPreview workerを起動したままにしない。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    worker = window.preview_vm._worker  # noqa: SLF001

    window.close()

    assert not worker.isRunning()


def test_branch_update_logic(qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock) -> None:
    """Branch更新操作でStorage更新と通知Dialogが呼ばれることを確認する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    with patch("rheed_capture.presentation.qt.main_window.QMessageBox.information") as mock_msg:
        window._on_new_branch()  # noqa: SLF001
        mock_storage.increment_branch.assert_called_once()
        mock_msg.assert_called_once()
    window.close()


def test_settings_save_on_close(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock, mock_settings: MagicMock
) -> None:
    """MainWindow終了時に現在UI状態をsettingsへ保存することを確認する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    window.preview_panel.spin_expo.setValue(99.9)
    window.preview_panel.chk_processing.setChecked(False)
    window.preview_panel.chk_show_grid.setChecked(False)
    window.preview_panel.cmb_grid_shape.setCurrentText("2x2")
    window.recording_panel.btn_rate_interval.click()
    window.recording_settings_panel.chk_tiff_compression.setChecked(True)
    assert window.recording_vm.get_settings_to_save().tiff_compression_enabled is True
    window.recording_settings_panel.chk_tiff_compression.setChecked(False)
    assert (
        window.recording_vm._build_recording_settings().tiff_compression_enabled is False  # noqa: SLF001
    )

    window.close()

    mock_settings.save.assert_called_once()
    saved_data = mock_settings.save.call_args[0][0]
    assert isinstance(saved_data, AppSettingsData)
    assert saved_data.preview.exposure_ms == 99.9
    assert saved_data.preview.enable_clahe is False
    assert saved_data.preview.show_grid is False
    assert saved_data.preview.grid_rows == 2
    assert saved_data.preview.grid_cols == 2
    assert saved_data.exposure_ms_values == [10.0, 20.0]
    assert saved_data.gain_values == [0, 1]
    assert saved_data.acquisition.mode == "software"
    assert saved_data.acquisition.fps_limit is None
    assert saved_data.sequence_capture.selected_exposure_ms_values == [10.0, 20.0]
    assert saved_data.angle_scan.selected_exposure_ms_values == [10.0]
    assert saved_data.angle_scan.range_deg == 5.0
    assert saved_data.angle_scan.direction == "both"
    assert saved_data.angle_scan.motor_speed_rpm == 4.0
    assert saved_data.recording_capture.rate_mode == "interval"
    assert saved_data.recording_capture.interval_ms == 25.0
    assert saved_data.recording_capture.tiff_compression_enabled is False
    assert saved_data.device.motor.port == "COM8"
    assert saved_data.device.motor.slave == 3
    assert saved_data.device.motor.position_units_per_deg == 31.25

    saved_dict = saved_data.to_dict()
    assert "speed_units" not in saved_dict["device"]["motor"]
    assert "rotation_capture" not in saved_dict
    assert "motor_port" not in saved_dict["angle_scan"]
    assert "motor_slave" not in saved_dict["angle_scan"]
    assert "motor_speed" not in saved_dict["angle_scan"]
    assert "speed_units" not in saved_dict["angle_scan"]
    assert "target_from_current_deg" not in saved_dict["angle_scan"]
    assert "reverse_scan" not in saved_dict["angle_scan"]
    assert "position_units_per_deg" not in saved_dict["angle_scan"]
    assert "seq_expo_list" not in saved_dict
    assert "angle_scan_expo_list" not in saved_dict


def test_acquisition_statistics_status_uses_only_preview_and_recording(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """共通status labelを500 ms更新し、有限撮影では空表示にする。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    assert (
        window._acquisition_statistics_timer.interval()  # noqa: SLF001
        == ACQUISITION_STATISTICS_UI_INTERVAL_MS
    )
    assert window.acquisition_statistics_label.toolTip() == ACQUISITION_STATISTICS_TOOLTIP
    assert not window.acquisition_statistics_label.font().bold()
    assert window.acquisition_statistics_label.styleSheet() == ""

    with (
        patch.object(
            window.preview_vm,
            "get_acquisition_statistics_text",
            return_value="Preview 10.0 fps",
        ),
        patch.object(
            window.preview_vm,
            "get_realtime_diagnostics_text",
            return_value="Realtime diagnostics",
        ),
    ):
        window.capture_coordinator.active_mode = None
        window._update_acquisition_statistics_display()  # noqa: SLF001
    assert (
        window.acquisition_statistics_label.text()
        == "Preview 10.0 fps | Realtime diagnostics"
    )

    with patch.object(
        window.preview_vm,
        "get_realtime_diagnostics_text",
        return_value="Realtime diagnostics",
    ):
        window.capture_coordinator.active_mode = "sequence"
        window._update_acquisition_statistics_display()  # noqa: SLF001
        assert window.acquisition_statistics_label.text() == "Realtime diagnostics"

        window.capture_coordinator.active_mode = "angle_scan"
        window._update_acquisition_statistics_display()  # noqa: SLF001
        assert window.acquisition_statistics_label.text() == "Realtime diagnostics"

    with (
        patch.object(
            window.recording_vm,
            "get_acquisition_statistics_text",
            return_value="Recording 9.0 fps | Avg 8.0 fps",
        ),
        patch.object(
            window.preview_vm,
            "get_realtime_diagnostics_text",
            return_value="Realtime diagnostics",
        ),
    ):
        window.capture_coordinator.active_mode = "recording"
        window._update_acquisition_statistics_display()  # noqa: SLF001
    assert (
        window.acquisition_statistics_label.text()
        == "Recording 9.0 fps | Avg 8.0 fps | Realtime diagnostics"
    )

    window.capture_coordinator.active_mode = None
    window.close()


def test_acquisition_controls_lock_during_capture_and_recording_rate_uses_mode(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """共通設定は撮影中にlockし、Hardware modeではRecording rateをlockする。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    window.acquisition_settings_panel.cmb_mode.setCurrentText("Hardware")
    assert window.recording_panel.btn_rate_interval.isEnabled() is False
    assert window.recording_panel.btn_rate_fps.isEnabled() is False
    assert window.preview_vm._acquisition_settings.mode == "hardware"  # noqa: SLF001
    assert window.recording_vm._acquisition_settings.mode == "hardware"  # noqa: SLF001
    assert window.capture_vm._acquisition_settings.mode == "hardware"  # noqa: SLF001
    assert window.angle_scan_vm._acquisition_settings.mode == "hardware"  # noqa: SLF001

    window.capture_coordinator.enter("sequence")
    assert window.acquisition_settings_panel.cmb_mode.isEnabled() is False
    assert window.acquisition_settings_panel.cmb_source.isEnabled() is False
    assert window.acquisition_settings_panel.chk_accumulation.isEnabled() is False

    window.capture_coordinator.leave()
    assert window.acquisition_settings_panel.cmb_mode.isEnabled() is True
    assert window.acquisition_settings_panel.cmb_source.isEnabled() is True
    assert window.recording_panel.btn_rate_interval.isEnabled() is False
    assert window.recording_panel.btn_rate_fps.isEnabled() is False
    window.close()


def test_recording_settings_lock_during_any_capture(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """CaptureCoordinatorのenter/leaveでRecording保存設定をlock・復帰する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    try:
        for capture_mode in ("sequence", "angle_scan", "recording"):
            window.capture_coordinator.enter(capture_mode)
            try:
                assert window.recording_settings_panel.isEnabled() is False
                assert window.recording_settings_panel.chk_tiff_compression.isEnabled() is False
            finally:
                window.capture_coordinator.leave()
            assert window.recording_settings_panel.isEnabled() is True
            assert window.recording_settings_panel.chk_tiff_compression.isEnabled() is True
    finally:
        window.close()


def test_display_refresh_tracks_active_screen_and_rate_changes(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """表示Timerがscreen移動とrefresh rate変更に追従する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    first_screen = _FakeScreen(60.0)
    second_screen = _FakeScreen(144.0)

    window._on_display_screen_changed(first_screen)  # noqa: SLF001
    assert window._display_refresh_timer.interval() == 17  # noqa: SLF001
    assert window._active_display_hz == 60.0  # noqa: SLF001

    first_screen.rate_hz = 120.0
    first_screen.refreshRateChanged.emit(120.0)
    assert window._display_refresh_timer.interval() == 9  # noqa: SLF001
    assert window._active_display_hz == 120.0  # noqa: SLF001

    window._on_display_screen_changed(second_screen)  # noqa: SLF001
    assert window._display_refresh_timer.interval() == 7  # noqa: SLF001
    assert window._active_display_hz == 144.0  # noqa: SLF001

    first_screen.rate_hz = 30.0
    first_screen.refreshRateChanged.emit(30.0)
    assert window._display_refresh_timer.interval() == 7  # noqa: SLF001
    window.close()


def test_recording_preview_submission_does_not_wait_for_gui_thread(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """実RecordingServiceからのPreview入力はGUI処理待ちせずsubmitする。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    submit_called = threading.Event()
    submit_thread_id: list[int] = []
    emitter_thread_id: list[int] = []

    def submit_frame(_frame: object) -> bool:
        """mailbox投入の呼出threadを記録する。"""
        submit_thread_id.append(threading.get_ident())
        submit_called.set()
        return True

    monkeypatch.setattr(window.preview_vm._worker, "submit_frame", submit_frame)  # noqa: SLF001
    monkeypatch.setattr(RecordingService, "start", lambda _service: None)
    window.recording_vm.start_recording()
    service = window.recording_vm._recording_service  # noqa: SLF001
    assert service is not None

    def emit_frame() -> None:
        """Emit a Preview frame from a Recording-worker-like thread."""
        emitter_thread_id.append(threading.get_ident())
        service.frame_captured.emit(np.ones((2, 2), dtype=np.uint16))

    emitter = threading.Thread(target=emit_frame)
    emitter.start()
    emitter.join(timeout=1.0)
    assert submit_called.wait(1.0)
    assert emitter_thread_id == submit_thread_id
    window.close()


def test_realtime_diagnostics_are_visible_in_existing_status_label(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """Preview/Graphの処理・表示FPSとactive Hzを既存status labelへ表示する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    window.preview_vm.set_display_refresh_rate(60.0)
    window.capture_coordinator.active_mode = None

    window._update_acquisition_statistics_display()  # noqa: SLF001

    status_text = window.acquisition_statistics_label.text()
    assert "Realtime" in status_text
    assert "Preview proc/display" in status_text
    assert "Graph proc/display" in status_text
    assert "Active display 60.0 Hz" in status_text
    assert "Drops P/G" in status_text
    window.close()
