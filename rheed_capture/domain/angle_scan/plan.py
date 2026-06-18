from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from rheed_capture.domain.angle_scan.model import (
    ANGLE_EPSILON,
    AngleScanDirection,
    validate_direction,
    validate_interval,
    validate_interval_within_range,
    validate_range,
)


@dataclass(frozen=True)
class MotorAngleCalibration:
    position_units_per_deg: float

    def __post_init__(self) -> None:
        if self.position_units_per_deg <= 0:
            msg = "1degあたりのモーター位置単位は正の値にしてください。"
            raise ValueError(msg)

    def angle_to_units(self, angle_deg: float) -> int:
        position_units = Decimal(str(angle_deg)) * Decimal(str(self.position_units_per_deg))
        return int(position_units.to_integral_value(rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class AngleMove:
    angle_deg: float
    target_units: int
    delta_units: int
    capture: bool


@dataclass(frozen=True)
class AngleScanPlan:
    angle_segments: list[list[float]]
    capture_angles: list[float]
    moves: list[AngleMove]


def build_angle_list(range_deg: float, interval_deg: float, sign: int = 1) -> list[float]:
    validate_range(range_deg)
    validate_interval(interval_deg)
    validate_interval_within_range(range_deg, interval_deg)
    if sign not in {-1, 1}:
        msg = "走査方向の符号は+1または-1で指定してください。"
        raise ValueError(msg)

    target = Decimal(str(range_deg))
    interval = Decimal(str(interval_deg))

    angles: list[float] = []
    step_count = int(target // interval)

    for index in range(step_count + 1):
        angle = interval * Decimal(index)
        if angle <= target:
            angles.append(float(angle) * sign)

    endpoint = float(target) * sign
    if abs(angles[-1] - endpoint) > ANGLE_EPSILON:
        angles.append(endpoint)

    return angles


def build_angle_segments(
    range_deg: float,
    interval_deg: float,
    direction: AngleScanDirection,
) -> list[list[float]]:
    validate_direction(direction)

    if direction == "positive":
        return [build_angle_list(range_deg, interval_deg, sign=1)]

    if direction == "negative":
        return [build_angle_list(range_deg, interval_deg, sign=-1)]

    return [
        build_angle_list(range_deg, interval_deg, sign=1),
        build_angle_list(range_deg, interval_deg, sign=-1),
    ]


def flatten_capture_angles(angle_segments: list[list[float]]) -> list[float]:
    capture_angles: list[float] = []

    for segment_index, segment in enumerate(angle_segments):
        if segment_index == 0:
            capture_angles.extend(segment)
            continue

        capture_angles.extend(segment[1:])

    return capture_angles


def build_angle_scan_plan(
    range_deg: float,
    interval_deg: float,
    direction: AngleScanDirection,
    calibration: MotorAngleCalibration,
) -> AngleScanPlan:
    angle_segments = build_angle_segments(range_deg, interval_deg, direction)
    capture_angles = flatten_capture_angles(angle_segments)
    moves = build_motion_moves(angle_segments, calibration)

    return AngleScanPlan(
        angle_segments=angle_segments,
        capture_angles=capture_angles,
        moves=moves,
    )


def build_motion_moves(
    angle_segments: list[list[float]],
    calibration: MotorAngleCalibration,
    *,
    initial_position_units: int = 0,
) -> list[AngleMove]:
    current_units = initial_position_units
    moves: list[AngleMove] = []

    for segment_index, segment in enumerate(angle_segments):
        for angle_index, angle_deg in enumerate(segment):
            target_units = calibration.angle_to_units(angle_deg)
            delta_units = target_units - current_units
            capture = not (segment_index > 0 and angle_index == 0)

            moves.append(
                AngleMove(
                    angle_deg=angle_deg,
                    target_units=target_units,
                    delta_units=delta_units,
                    capture=capture,
                )
            )
            current_units = target_units

    return moves


def angle_to_position_units(
    angle_deg: float,
    position_units_per_deg: float,
) -> int:
    return MotorAngleCalibration(position_units_per_deg).angle_to_units(angle_deg)


def build_motion_unit_deltas(
    angles_deg: list[float],
    position_units_per_deg: float,
    *,
    initial_position_units: int = 0,
) -> list[int]:
    calibration = MotorAngleCalibration(position_units_per_deg)
    moves = build_motion_moves(
        [angles_deg],
        calibration,
        initial_position_units=initial_position_units,
    )

    return [move.delta_units for move in moves]
