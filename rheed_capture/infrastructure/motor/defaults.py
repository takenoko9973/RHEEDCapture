"""モーター制御で共有する初期値。"""

DEFAULT_MOTOR_PORT = "COM7"
DEFAULT_MOTOR_SLAVE = 2
DEFAULT_POSITION_UNITS_PER_DEG = 31.25

DEGREES_PER_MOTOR_REVOLUTION = 360.0
SECONDS_PER_MINUTE = 60.0


def motor_speed_units_per_rpm(
    position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG,
) -> float:
    return position_units_per_deg * DEGREES_PER_MOTOR_REVOLUTION / SECONDS_PER_MINUTE


def motor_rpm_to_speed_units(
    motor_speed_rpm: float,
    *,
    position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG,
) -> int:
    if motor_speed_rpm <= 0:
        msg = "motor_speed_rpm must be positive"
        raise ValueError(msg)

    if position_units_per_deg <= 0:
        msg = "position_units_per_deg must be positive"
        raise ValueError(msg)

    return max(
        1,
        round(motor_speed_rpm * motor_speed_units_per_rpm(position_units_per_deg)),
    )
