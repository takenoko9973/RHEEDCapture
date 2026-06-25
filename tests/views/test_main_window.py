import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
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
from rheed_capture.presentation.qt.main_window import MainWindow


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
    window.close()


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
    assert saved_data.sequence_capture.selected_exposure_ms_values == [10.0, 20.0]
    assert saved_data.angle_scan.selected_exposure_ms_values == [10.0]
    assert saved_data.angle_scan.range_deg == 5.0
    assert saved_data.angle_scan.direction == "both"
    assert saved_data.angle_scan.motor_speed_rpm == 4.0
    assert saved_data.recording_capture.rate_mode == "interval"
    assert saved_data.recording_capture.interval_ms == 25.0
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
