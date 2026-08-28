from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from rheed_capture.infrastructure.config.schema import (
    AcquisitionSettings,
    AngleScanCaptureSettings,
    AppSettingsData,
    DeviceSettings,
    MotorDeviceSettings,
)
from rheed_capture.presentation.qt.viewmodels.angle_scan import AngleScanViewModel


class _FakeSignal:
    def connect(self, slot: object, *connection_types: object) -> None:  # noqa: ARG002
        """Qt signalのslotと接続種別を受け取るfake接続を記録しない。"""
        return


class _FakeAngleScanService:
    progress_update = _FakeSignal()
    frame_captured = _FakeSignal()
    scan_finished = _FakeSignal()
    error_occurred = _FakeSignal()
    preview_resume_requested = _FakeSignal()
    preview_pause_requested = _FakeSignal()

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def start(self) -> None:
        return

    def isRunning(self) -> bool:  # noqa: N802
        return False


def test_angle_scan_viewmodel_passes_device_conversion_to_motor_config(
    qtbot: QtBot,
) -> None:
    # QApplicationを用意するためにqtbot fixtureを受け取る。
    _ = qtbot

    motor_factory = MagicMock(return_value=MagicMock())
    view_model = AngleScanViewModel(MagicMock(), MagicMock(), motor_factory=motor_factory)
    view_model.load_settings(
        AppSettingsData(
            angle_scan=AngleScanCaptureSettings(motor_speed_rpm=4.0),
            device=DeviceSettings(
                motor=MotorDeviceSettings(
                    port="COM8",
                    slave=3,
                    position_units_per_deg=40.0,
                )
            ),
        )
    )

    with (
        patch(
            "rheed_capture.presentation.qt.viewmodels.angle_scan.AngleScanService",
            _FakeAngleScanService,
        ),
    ):
        view_model.start_angle_scan()

    motor_factory.assert_called_once_with("COM8", 3, 40.0)


def test_angle_scan_passes_ordered_conditions_and_preserves_direct_connection(
    qtbot: QtBot,
) -> None:
    """Angle Scan開始は選択順の直積とDirect frame接続を維持する。"""
    _ = qtbot
    camera = MagicMock()
    storage = MagicMock()
    motor = MagicMock()
    acquisition = AcquisitionSettings(accumulation_frames=2)
    view_model = AngleScanViewModel(
        camera,
        storage,
        motor_factory=MagicMock(return_value=motor),
    )
    view_model.load_settings(
        AppSettingsData(
            exposure_ms_values=[20.0, 10.0],
            gain_values=[2, 1],
            angle_scan=AngleScanCaptureSettings(
                selected_exposure_ms_values=[20.0, 10.0],
                selected_gain_values=[2, 1],
            ),
            acquisition=acquisition,
        )
    )
    service = MagicMock()

    with patch(
        "rheed_capture.presentation.qt.viewmodels.angle_scan.AngleScanService",
        return_value=service,
    ) as service_class:
        view_model.start_angle_scan()

    conditions = service_class.call_args.args[3]
    assert [(condition.exposure_ms, condition.gain) for condition in conditions] == [
        (20.0, 2),
        (20.0, 1),
        (10.0, 2),
        (10.0, 1),
    ]
    assert service_class.call_args.args[:3] == (camera, storage, motor)
    assert service_class.call_args.args[5] == acquisition
    service.frame_captured.connect.assert_called_once_with(
        view_model.frame_captured,
        Qt.ConnectionType.DirectConnection,
    )
    service.start.assert_called_once_with()
