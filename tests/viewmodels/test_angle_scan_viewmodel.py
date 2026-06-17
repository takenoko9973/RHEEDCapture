from unittest.mock import MagicMock, patch

from pytestqt.qtbot import QtBot

from rheed_capture.models.hardware.rotation_motor import MotorConnectionConfig
from rheed_capture.models.io.settings import (
    AngleScanCaptureSettings,
    AppSettingsData,
    DeviceSettings,
    MotorDeviceSettings,
)
from rheed_capture.viewmodels.angle_scan_viewmodel import AngleScanViewModel


class _FakeSignal:
    def connect(self, slot: object) -> None:  # noqa: ARG002
        return


class _FakeAngleScanService:
    progress_update = _FakeSignal()
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

    view_model = AngleScanViewModel(MagicMock(), MagicMock())
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
            "rheed_capture.viewmodels.angle_scan_viewmodel.AzdCdRotationMotor"
        ) as mock_motor,
        patch(
            "rheed_capture.viewmodels.angle_scan_viewmodel.AngleScanService",
            _FakeAngleScanService,
        ),
    ):
        view_model.start_angle_scan()

    motor_config = mock_motor.call_args.args[0]
    assert isinstance(motor_config, MotorConnectionConfig)
    assert motor_config.port == "COM8"
    assert motor_config.slave == 3
    assert motor_config.position_units_per_deg == 40.0
