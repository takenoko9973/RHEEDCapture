import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.settings import (
    AngleScanCaptureSettings,
    AppSettingsData,
    DeviceSettings,
    MotorDeviceSettings,
    PreviewSettings,
    SequenceCaptureSettings,
)
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.views.main_window import MainWindow


@pytest.fixture
def mock_camera() -> MagicMock:
    camera = MagicMock(spec=CameraDevice)

    def mock_retrieve(*args, **kwargs) -> None:  # noqa: ARG001
        time.sleep(0.01)

    camera.retrieve_preview_frame.side_effect = mock_retrieve
    camera.get_exposure_bounds.return_value = (1, 10000)
    camera.get_gain_bounds.return_value = (0, 48)
    return camera


@pytest.fixture
def mock_storage() -> MagicMock:
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("dummy/root")
    mock_dir = MagicMock(spec=Path)
    mock_dir.name = "260215"
    storage.get_current_experiment_dir.return_value = mock_dir
    storage.get_next_sequence_dir_name.return_value = "image_001"
    storage.get_next_angle_scan_dir_name.return_value = "angle_scan_001"
    storage.increment_branch.return_value = "260215-2"
    return storage


@pytest.fixture(autouse=True)
def mock_settings() -> types.GeneratorType:
    with patch("rheed_capture.views.main_window.AppSettings") as mock_app_settings:
        mock_app_settings.load.return_value = AppSettingsData(
            root_dir="dummy/root",
            preview=PreviewSettings(
                exposure_ms=15.5,
                gain=2,
                enable_clahe=True,
                show_grid=True,
                grid_rows=8,
                grid_cols=8,
            ),
            sequence_capture=SequenceCaptureSettings(
                exposure_ms_list=[10.0, 20.0],
                gain_list=[0, 1],
            ),
            angle_scan=AngleScanCaptureSettings(
                exposure_ms_list=[10.0, 20.0],
                gain_list=[0, 1],
                range_deg=5.0,
                direction="both",
                motor_speed_rpm=4.0,
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
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    assert window.preview_panel.spin_expo.value() == 15.5
    assert window.preview_panel.chk_show_grid.isChecked() is True
    assert window.preview_panel.cmb_grid_shape.currentText() == "8x8"
    assert window.sequence_panel.edit_seq_expo.text() == "10.0, 20.0"
    assert window.angle_scan_panel.edit_expo.text() == "10.0, 20.0"
    assert window.angle_scan_panel.spin_range_deg.value() == 5.0
    assert window.angle_scan_panel.btn_direction_both.isChecked() is True
    assert window.angle_scan_panel.spin_motor_speed_rpm.value() == 4.0
    assert window.motor_settings_panel.edit_motor_port.text() == "COM8"
    assert window.motor_settings_panel.spin_motor_slave.value() == 3
    assert window.motor_settings_panel.spin_position_units_per_deg.value() == 31.25
    assert window.control_tabs.count() == 2
    assert window.control_tabs.tabText(0) == "Capture"
    assert window.control_tabs.tabText(1) == "Settings"
    assert window.capture_tabs.count() == 2
    assert window.capture_tabs.tabText(0) == "Sequence"
    assert window.capture_tabs.tabText(1) == "Angle Scan"
    window.close()


def test_branch_update_logic(qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock) -> None:
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    with patch("rheed_capture.views.main_window.QMessageBox.information") as mock_msg:
        window._on_new_branch()  # noqa: SLF001
        mock_storage.increment_branch.assert_called_once()
        mock_msg.assert_called_once()
    window.close()


def test_settings_save_on_close(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock, mock_settings: MagicMock
) -> None:
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    window.preview_panel.spin_expo.setValue(99.9)
    window.preview_panel.chk_processing.setChecked(False)
    window.preview_panel.chk_show_grid.setChecked(False)
    window.preview_panel.cmb_grid_shape.setCurrentText("2x2")

    window.close()

    mock_settings.save.assert_called_once()
    saved_data = mock_settings.save.call_args[0][0]
    assert isinstance(saved_data, AppSettingsData)
    assert saved_data.preview.exposure_ms == 99.9
    assert saved_data.preview.enable_clahe is False
    assert saved_data.preview.show_grid is False
    assert saved_data.preview.grid_rows == 2
    assert saved_data.preview.grid_cols == 2
    assert saved_data.sequence_capture.exposure_ms_list == [10.0, 20.0]
    assert saved_data.angle_scan.exposure_ms_list == [10.0, 20.0]
    assert saved_data.angle_scan.range_deg == 5.0
    assert saved_data.angle_scan.direction == "both"
    assert saved_data.angle_scan.motor_speed_rpm == 4.0
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
