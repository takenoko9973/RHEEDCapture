import time
from dataclasses import dataclass

from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.infrastructure.motor.defaults import (
    DEFAULT_POSITION_UNITS_PER_DEG,
    motor_rpm_to_speed_units,
)


@dataclass(frozen=True)
class MockMoveRecord:
    delta_units: int
    start_units: int
    end_units: int
    motor_speed_rpm: float
    estimated_duration_sec: float


class MockRotationMotor:
    def __init__(
        self,
        *,
        position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG,
    ) -> None:
        self.position_units_per_deg = position_units_per_deg
        self.position_units = 0
        self.move_log: list[MockMoveRecord] = []

    def move_relative_units(
        self,
        position_units: int,
        motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM,
        *,
        timeout: float = 10.0,
    ) -> MockMoveRecord:
        speed_units_per_sec = motor_rpm_to_speed_units(
            motor_speed_rpm,
            position_units_per_deg=self.position_units_per_deg,
        )
        estimated_duration_sec = abs(position_units) / speed_units_per_sec

        if estimated_duration_sec > timeout:
            msg = (
                "Mock motor move timed out: "
                f"{estimated_duration_sec:.3f}s > {timeout:.3f}s"
            )
            raise TimeoutError(msg)

        start_units = self.position_units
        end_units = start_units + position_units
        record = MockMoveRecord(
            delta_units=position_units,
            start_units=start_units,
            end_units=end_units,
            motor_speed_rpm=motor_speed_rpm,
            estimated_duration_sec=estimated_duration_sec,
        )
        self.move_log.append(record)

        time.sleep(min(estimated_duration_sec, 0.2))
        self.position_units = end_units
        return record
