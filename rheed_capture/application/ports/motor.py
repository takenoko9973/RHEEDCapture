from __future__ import annotations

from typing import Protocol

DEFAULT_MOTOR_SPEED_RPM = 4.0


class RotationMotor(Protocol):
    def move_relative_units(
        self,
        position_units: int,
        motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM,
        *,
        timeout: float = 10.0,
    ) -> object | None:
        ...
