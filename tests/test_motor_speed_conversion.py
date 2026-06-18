from unittest.mock import MagicMock, patch

import pytest

from rheed_capture.bootstrap import create_motor_factory
from rheed_capture.infrastructure.motor.azd_cd.adapter import AzdCdAdapter
from rheed_capture.infrastructure.motor.azd_cd.driver import AzdCdConfig, AzdCdStatus
from rheed_capture.infrastructure.motor.azd_cd.protocol import (
    OP_RELATIVE_POSITIONING,
    STATUS_MOVE,
)
from rheed_capture.infrastructure.motor.defaults import (
    motor_rpm_to_speed_units,
    motor_speed_units_per_rpm,
)
from rheed_capture.infrastructure.motor.mock import MockRotationMotor


def test_motor_speed_units_per_rpm_is_derived_from_position_units() -> None:
    # 31.25 unit/deg * 360 deg/rev / 60 sec/min = 187.5 unit per rpm
    assert motor_speed_units_per_rpm(position_units_per_deg=31.25) == 187.5
    assert motor_speed_units_per_rpm(position_units_per_deg=40.0) == 240.0


@pytest.mark.parametrize(
    ("motor_speed_rpm", "expected_speed_units"),
    [
        (3.0, 562),
        (3.1, 581),
        (3.3, 619),
        (4.0, 750),
    ],
)
def test_motor_rpm_to_speed_units_uses_driver_rounding_rule(
    motor_speed_rpm: float,
    expected_speed_units: int,
) -> None:
    assert motor_rpm_to_speed_units(motor_speed_rpm) == expected_speed_units


def test_adapter_converts_rpm_before_sending_speed_to_driver() -> None:
    driver = MagicMock()
    driver.read_status.return_value = AzdCdStatus(upper_word=0, lower_word=STATUS_MOVE)

    driver_factory = MagicMock()
    driver_factory.return_value.__enter__.return_value = driver

    with patch(
        "rheed_capture.infrastructure.motor.azd_cd.adapter.AzdCdDriver",
        driver_factory,
    ):
        adapter = AzdCdAdapter(
            AzdCdConfig(port="COM1", slave=2),
            position_units_per_deg=31.25,
        )
        adapter.start_relative_units(position_units=10, motor_speed_rpm=4.0)

    driver.set_operation_type.assert_called_once_with(OP_RELATIVE_POSITIONING)
    driver.set_speed_units.assert_called_once_with(750)
    driver.set_position_units.assert_called_once_with(10)
    driver.start_on.assert_called_once_with()
    driver.start_off.assert_called_once_with()


def test_mock_rotation_motor_tracks_position_and_move_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rheed_capture.infrastructure.motor.mock.time.sleep", lambda _sec: None)
    motor = MockRotationMotor(position_units_per_deg=31.25)

    record = motor.move_relative_units(375, motor_speed_rpm=4.0)

    assert motor.position_units == 375
    assert motor.move_log == [record]
    assert record.delta_units == 375
    assert record.start_units == 0
    assert record.end_units == 375
    assert record.motor_speed_rpm == 4.0


@pytest.mark.parametrize("port", ["MOCK", "mock://motor"])
def test_motor_factory_uses_mock_motor_for_simulation_ports(port: str) -> None:
    factory = create_motor_factory()

    motor = factory(port, 2, 31.25)

    assert isinstance(motor, MockRotationMotor)
    assert motor.position_units_per_deg == 31.25
