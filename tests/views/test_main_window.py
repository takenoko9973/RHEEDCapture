import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from rheed_capture.application.ports.camera import ImageFormatSnapshot
from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics
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
    ACQUISITION_STATISTICS_UI_INTERVAL_MS,
    MainWindow,
)
from rheed_capture.presentation.qt.preview.processor import PreviewDiagnostics, PreviewInput
from rheed_capture.presentation.qt.workers.recording_service import RecordingService


@pytest.fixture
def mock_camera() -> MagicMock:
    """MainWindowテスト用のCamera mockを作る。"""
    camera = MagicMock(spec=CameraDevice)

    def mock_wait_until_ready(*args, **kwargs) -> None:  # noqa: ARG001
        """Previewのフレーム待機を短時間だけ再現する。"""
        time.sleep(0.01)
        raise TimeoutError

    camera.start_trigger_session.return_value.wait_until_ready.side_effect = (
        mock_wait_until_ready
    )
    camera.start_trigger_session.return_value.retrieve_frame.side_effect = (
        mock_wait_until_ready
    )
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


def test_main_window_composes_capture_modes_and_settings(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """MainWindowが撮影modeとsettingsのtop-level構成を組み立てる。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    assert window.control_tabs.count() == 2
    assert window.capture_tabs.count() == 3
    assert window.capture_tabs.widget(0) is window.sequence_panel
    assert window.capture_tabs.widget(1) is window.angle_scan_panel
    assert window.capture_tabs.widget(2) is window.recording_panel
    assert window.recording_settings_panel.chk_tiff_compression.isChecked() is False
    assert window.recording_vm.get_settings_to_save().tiff_compression_enabled is False
    assert window.motor_settings_panel.spin_motor_slave.value() == 3
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
    window.recording_settings_panel.chk_tiff_compression.setChecked(False)

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
    assert saved_data.sequence_capture.selected_exposure_ms_values == [10.0, 20.0]
    assert saved_data.angle_scan.selected_exposure_ms_values == [10.0]
    assert saved_data.angle_scan.range_deg == 5.0
    assert saved_data.recording_capture.rate_mode == "interval"
    assert saved_data.recording_capture.interval_ms == 25.0
    assert saved_data.recording_capture.tiff_compression_enabled is False
    assert saved_data.device.motor.port == "COM8"


def test_acquisition_statistics_status_uses_only_preview_and_recording(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """短いsummaryを500 ms更新し、有限撮影では空表示にする。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    assert (
        window._acquisition_statistics_timer.interval()  # noqa: SLF001
        == ACQUISITION_STATISTICS_UI_INTERVAL_MS
    )
    preview_statistics = AcquisitionStatistics(
        current_fps=10.0,
        average_fps=None,
        frame_count=12,
        payload_bytes_per_second=20_000_000.0,
    )
    recording_statistics = AcquisitionStatistics(
        current_fps=9.0,
        average_fps=8.0,
        frame_count=100,
        payload_bytes_per_second=12_000_000.0,
        save_queue_depth=0,
        save_queue_peak_depth=4,
    )
    diagnostics = PreviewDiagnostics(
        preview_processing_fps=30.0,
        graph_processing_fps=30.0,
        preview_display_fps=60.0,
        graph_display_fps=60.0,
        active_display_hz=60.0,
        preview_processed_frames=12,
        graph_processed_frames=12,
        preview_display_frames=12,
        graph_display_frames=12,
        preview_input_drop_count=0,
        graph_input_drop_count=0,
        preview_result_drop_count=0,
        graph_result_drop_count=0,
    )

    with (
        patch.object(
            window.preview_vm,
            "acquisition_statistics_snapshot",
            return_value=preview_statistics,
        ),
        patch.object(
            window.recording_vm,
            "acquisition_statistics_snapshot",
            return_value=recording_statistics,
        ),
        patch.object(
            window.preview_vm,
            "diagnostics_snapshot",
            return_value=diagnostics,
        ),
    ):
        window.capture_coordinator.active_mode = None
        window._update_acquisition_statistics_display()  # noqa: SLF001
    assert window.acquisition_statistics_label.text() == (
        "Preview | Camera 10.0 fps | 20.0 MB/s"
    )

    with patch.object(window.preview_vm, "diagnostics_snapshot", return_value=diagnostics):
        window.capture_coordinator.active_mode = "sequence"
        window._update_acquisition_statistics_display()  # noqa: SLF001
        assert window.acquisition_statistics_label.text() == ""

        window.capture_coordinator.active_mode = "angle_scan"
        window._update_acquisition_statistics_display()  # noqa: SLF001
        assert window.acquisition_statistics_label.text() == ""

    with (
        patch.object(
            window.recording_vm,
            "acquisition_statistics_snapshot",
            return_value=recording_statistics,
        ),
        patch.object(
            window.preview_vm,
            "diagnostics_snapshot",
            return_value=diagnostics,
        ),
    ):
        window.capture_coordinator.active_mode = "recording"
        window._update_acquisition_statistics_display()  # noqa: SLF001
    assert window.acquisition_statistics_label.text() == (
        "Recording | Camera 9.0 fps | 12.0 MB/s | Save Q 0"
    )

    window.capture_coordinator.active_mode = None
    window.close()


def test_status_statistics_and_diagnostics_form_one_spaced_centered_unit(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """統計summaryとDiagnostics操作を余白付きの単一status unitに配置する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    layout = window.status_statistics_widget.layout()
    assert layout is not None
    margins = layout.contentsMargins()
    statistics_item = layout.itemAt(0)
    diagnostics_item = layout.itemAt(1)

    assert layout.count() == 2
    assert statistics_item is not None
    assert diagnostics_item is not None
    assert statistics_item.widget() is window.acquisition_statistics_label
    assert diagnostics_item.widget() is window.diagnostics_button
    assert margins.left() > 0
    assert margins.right() > 0
    assert layout.spacing() > 0
    assert layout.alignment() & Qt.AlignmentFlag.AlignVCenter
    assert diagnostics_item.alignment() & Qt.AlignmentFlag.AlignCenter

    window.close()


def test_acquisition_controls_lock_during_capture_and_recording_rate_uses_mode(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """共通設定は撮影中にlockし、Hardware modeではRecording rateをlockする。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    with (
        patch.object(window.preview_vm, "set_acquisition_settings") as preview_set,
        patch.object(window.recording_vm, "set_acquisition_settings") as recording_set,
        patch.object(window.capture_vm, "load_settings") as sequence_load,
        patch.object(window.angle_scan_vm, "load_settings") as angle_scan_load,
    ):
        window.acquisition_settings_panel.cmb_mode.setCurrentText("Hardware")

    assert preview_set.call_args.args[0].mode == "hardware"
    assert recording_set.call_args.args[0].mode == "hardware"
    assert sequence_load.call_args.args[0].acquisition.mode == "hardware"
    assert angle_scan_load.call_args.args[0].acquisition.mode == "hardware"
    assert window.recording_panel.btn_rate_interval.isEnabled() is False
    assert window.recording_panel.btn_rate_fps.isEnabled() is False

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
            finally:
                window.capture_coordinator.leave()
            assert window.recording_settings_panel.isEnabled() is True
    finally:
        window.close()


def test_display_refresh_updates_preview_diagnostics_and_refreshes_preview(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """表示rateとTimer tickをPreviewの診断値と表示更新へ伝える。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    window.display_refresh.on_refresh_rate_changed(144.0)

    assert window.preview_vm.diagnostics_snapshot().active_display_hz == 144.0
    with patch.object(window.preview_vm._worker, "refresh_display") as refresh_display:  # noqa: SLF001
        window.display_refresh.timer.timeout.emit()
    refresh_display.assert_called_once_with()
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
        service.frame_captured.emit(
            PreviewInput(
                np.ones((2, 2), dtype=np.uint16),
                ImageFormatSnapshot(12, 16, "Mono12Packed", "MsbAligned"),
            )
        )

    emitter = threading.Thread(target=emit_frame)
    emitter.start()
    emitter.join(timeout=1.0)
    assert submit_called.wait(1.0)
    assert emitter_thread_id == submit_thread_id
    window.close()


def test_diagnostics_button_opens_one_modeless_reusable_dialog(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """Diagnostics操作UIが同じmodeless Dialogを開閉する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    dialog = window.diagnostics_dialog

    assert window.diagnostics_button.text() == "Diagnostics"
    assert dialog.isModal() is False
    assert dialog.isVisible() is False

    window.diagnostics_button.click()
    assert dialog.isVisible() is True
    assert window.diagnostics_dialog is dialog

    dialog.close()
    assert dialog.isVisible() is False

    window.diagnostics_button.click()
    assert dialog.isVisible() is True
    assert window.diagnostics_dialog is dialog

    window.diagnostics_button.click()
    assert dialog.isVisible() is False
    window.close()


def test_main_window_close_hides_visible_diagnostics_dialog(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """MainWindow終了を受理したときvisibleなDiagnosticsも閉じる。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    window.diagnostics_button.click()
    assert window.diagnostics_dialog.isVisible() is True

    window.close()

    assert window.diagnostics_dialog.isVisible() is False


def test_diagnostics_refreshes_only_while_dialog_is_visible(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """既存500 ms更新はDiagnosticsがvisibleの時だけ値を反映する。"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)
    statistics = AcquisitionStatistics(
        current_fps=10.0,
        average_fps=None,
        frame_count=12,
        payload_bytes_per_second=20_000_000.0,
    )
    diagnostics = PreviewDiagnostics(
        preview_processing_fps=30.0,
        graph_processing_fps=20.0,
        preview_display_fps=60.0,
        graph_display_fps=50.0,
        active_display_hz=60.0,
        preview_processed_frames=12,
        graph_processed_frames=12,
        preview_display_frames=12,
        graph_display_frames=12,
        preview_input_drop_count=1,
        graph_input_drop_count=0,
        preview_result_drop_count=2,
        graph_result_drop_count=3,
    )

    with (
        patch.object(
            window.preview_vm,
            "acquisition_statistics_snapshot",
            return_value=statistics,
        ),
        patch.object(window.preview_vm, "diagnostics_snapshot", return_value=diagnostics),
        patch.object(window.diagnostics_dialog, "update_values") as update_values,
    ):
        window.capture_coordinator.active_mode = None
        window._update_acquisition_statistics_display()  # noqa: SLF001
        update_values.assert_not_called()

        window.diagnostics_button.click()
        window._update_acquisition_statistics_display()  # noqa: SLF001

    update_values.assert_called_once_with(None, statistics, diagnostics)

    window.diagnostics_dialog.hide()
    window.close()
