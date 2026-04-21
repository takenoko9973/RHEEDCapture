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
    storage.get_next_sequence_dir_name.return_value = "image_006"
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


def test_main_window_updates_sequence_preview(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    window._sequence_preview_timer.stop()  # noqa: SLF001

    assert window.sequence_panel.lbl_next_sequence_preview.text() == "image_006"

    mock_storage.get_next_sequence_dir_name.return_value = "image_009"
    window._on_sequence_preview_timer()  # noqa: SLF001

    assert window.sequence_panel.lbl_next_sequence_preview.text() == "image_009"
    window.close()


def test_sequence_preview_timer_skips_refresh_while_capturing(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    window._sequence_preview_timer.stop()  # noqa: SLF001

    before = mock_storage.refresh_sequence_counter_from_disk.call_count
    with patch.object(window.capture_vm, "is_running", return_value=True):
        window._on_sequence_preview_timer()  # noqa: SLF001
    assert mock_storage.refresh_sequence_counter_from_disk.call_count == before

    with patch.object(window.capture_vm, "is_running", return_value=False):
        window._on_sequence_preview_timer()  # noqa: SLF001
    assert mock_storage.refresh_sequence_counter_from_disk.call_count == before + 1
    window.close()
