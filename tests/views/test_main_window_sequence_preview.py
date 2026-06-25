import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.infrastructure.config.schema import (
    AppSettingsData,
    PreviewSettings,
    RecordingCaptureSettings,
    SequenceCaptureSettings,
)
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.main_window import MainWindow


@pytest.fixture
def mock_camera() -> MagicMock:
    """保存先プレビュー更新テスト用のCamera mockを作る。"""
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
    """保存先プレビュー更新テスト用のStorage mockを作る。"""
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("dummy/root")
    mock_dir = MagicMock(spec=Path)
    mock_dir.name = "260215"
    storage.get_current_experiment_dir.return_value = mock_dir
    storage.get_next_sequence_dir_name.return_value = "image_006"
    storage.get_next_angle_scan_dir_name.return_value = "angle_scan_002"
    storage.get_next_recording_dir_name.return_value = "record-3"
    return storage


@pytest.fixture(autouse=True)
def mock_settings() -> types.GeneratorType:
    """AppSettings.load/saveを保存先プレビュー用設定に差し替える。"""
    with patch("rheed_capture.presentation.qt.main_window.AppSettings") as mock_app_settings:
        mock_app_settings.load.return_value = AppSettingsData(
            root_dir="dummy/root",
            exposure_ms_values=[10.0, 20.0],
            gain_values=[0, 1],
            preview=PreviewSettings(exposure_ms=15.5, gain=2, enable_clahe=True),
            sequence_capture=SequenceCaptureSettings(
                selected_exposure_ms_values=[10.0, 20.0],
                selected_gain_values=[0, 1],
            ),
            recording_capture=RecordingCaptureSettings(),
        )
        yield mock_app_settings


def test_main_window_updates_sequence_preview(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """Timer更新で各撮影種別の次保存先表示が更新されることを確認する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    window._sequence_preview_timer.stop()  # noqa: SLF001

    assert window.sequence_panel.lbl_next_sequence_preview.text() == "image_006"
    assert window.angle_scan_panel.lbl_next_angle_scan_preview.text() == "angle_scan_002"
    assert window.recording_panel.lbl_next_recording_preview.text() == "record-3"

    mock_storage.get_next_sequence_dir_name.return_value = "image_009"
    mock_storage.get_next_angle_scan_dir_name.return_value = "angle_scan_003"
    mock_storage.get_next_recording_dir_name.return_value = "record-4"
    window._on_sequence_preview_timer()  # noqa: SLF001

    assert window.sequence_panel.lbl_next_sequence_preview.text() == "image_009"
    assert window.angle_scan_panel.lbl_next_angle_scan_preview.text() == "angle_scan_003"
    assert window.recording_panel.lbl_next_recording_preview.text() == "record-4"
    window.close()


def test_sequence_preview_timer_skips_refresh_while_capturing(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """撮影中は保存先プレビューTimerがStorage再走査を行わない。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    window._sequence_preview_timer.stop()  # noqa: SLF001

    before = mock_storage.refresh_capture_counters_from_disk.call_count
    window.capture_coordinator.enter("sequence")
    window._on_sequence_preview_timer()  # noqa: SLF001
    assert mock_storage.refresh_capture_counters_from_disk.call_count == before

    window.capture_coordinator.leave()
    with patch.object(window.capture_vm, "is_running", return_value=False):
        window._on_sequence_preview_timer()  # noqa: SLF001
    assert mock_storage.refresh_capture_counters_from_disk.call_count == before + 2
    window.close()


def test_start_angle_scan_does_not_pause_preview_before_service_start(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """Angle Scan開始時はService開始前にPreview停止を要求しない。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    window._sequence_preview_timer.stop()  # noqa: SLF001

    with (
        patch.object(window.preview_vm, "pause_preview") as pause_preview,
        patch.object(window.angle_scan_vm, "start_angle_scan") as start_angle_scan,
    ):
        window._on_start_angle_scan_requested()  # noqa: SLF001

    pause_preview.assert_not_called()
    start_angle_scan.assert_called_once_with()
    window.capture_coordinator.leave()
    window.close()
