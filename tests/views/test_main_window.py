import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.models.hardware.camera_device import CameraDevice
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
    storage.increment_branch.return_value = "260215-2"
    return storage


@pytest.fixture(autouse=True)
def mock_settings() -> types.GeneratorType:
    with patch("rheed_capture.views.main_window.AppSettings") as mock_app_settings:
        mock_app_settings.load.return_value = {
            "root_dir": "dummy/root",
            "preview_expo": 15.5,
            "preview_gain": 2.0,
            "seq_expo_list": [10.0, 20.0],
            "seq_gain_list": [0, 1],
            "enable_clahe": True,
        }
        yield mock_app_settings


def test_main_window_initialization(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    assert window.preview_panel.spin_expo.value() == 15.5
    assert window.sequence_panel.edit_seq_expo.text() == "10, 20"
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

    window.close()

    mock_settings.save.assert_called_once()
    saved_data = mock_settings.save.call_args[0][0]
    assert saved_data["preview_expo"] == 99.9
    assert saved_data["enable_clahe"] is False
    assert saved_data["seq_expo_list"] == [10.0, 20.0]
