"""Recording ViewModelの見込み枚数とService境界を検証する。"""

from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from rheed_capture.infrastructure.config.schema import (
    AcquisitionSettings,
    RecordingCaptureSettings,
)
from rheed_capture.presentation.qt.viewmodels.recording import RecordingViewModel


def test_expected_frames_uses_ceil_plus_first_frame_and_indefinite_marker(
    qtbot: QtBot,
) -> None:
    """有限Durationはceil(duration/interval)+1、無期限は`-`で通知する。"""
    view_model = RecordingViewModel(MagicMock(), MagicMock())

    with qtbot.waitSignal(view_model.expected_frames_updated) as finite_signal:
        view_model.load_settings(
            RecordingCaptureSettings(
                rate_mode="interval",
                interval_ms=400.0,
                duration_sec=1.0,
            )
        )

    with qtbot.waitSignal(view_model.expected_frames_updated) as indefinite_signal:
        view_model.update_duration_sec(0.0)

    assert finite_signal.args == ["about 4"]
    assert indefinite_signal.args == ["-"]


def test_start_recording_resolves_fps_and_preserves_direct_frame_connection(
    qtbot: QtBot,
) -> None:
    """開始時はFPSを間隔へ変換し、取得設定とDirect frame接続を維持する。"""
    _ = qtbot
    camera = MagicMock()
    storage = MagicMock()
    acquisition = AcquisitionSettings(accumulation_frames=4)
    view_model = RecordingViewModel(camera, storage)
    view_model.load_settings(
        RecordingCaptureSettings(
            exposure_ms=12.0,
            gain=3,
            rate_mode="fps",
            fps=20.0,
            interval_ms=999.0,
            duration_sec=2.0,
            tiff_compression_enabled=False,
        )
    )
    view_model.load_acquisition_settings(acquisition)
    service = MagicMock()

    with patch(
        "rheed_capture.presentation.qt.viewmodels.recording.RecordingService",
        return_value=service,
    ) as service_class:
        view_model.start_recording()

    settings = service_class.call_args.args[2]
    assert service_class.call_args.args[:2] == (camera, storage)
    assert settings.exposure_ms == 12.0
    assert settings.gain == 3
    assert settings.rate_mode == "fps"
    assert settings.target_interval_ms == 50.0
    assert settings.duration_ms == 2000.0
    assert settings.tiff_compression_enabled is False
    assert service_class.call_args.args[3] == acquisition
    service.frame_captured.connect.assert_called_once_with(
        view_model.frame_captured,
        Qt.ConnectionType.DirectConnection,
    )
    service.start.assert_called_once_with()
