import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.services.angle_scan_plan import (
    angle_to_position_units,
    build_angle_list,
    build_motion_unit_deltas,
)
from rheed_capture.services.angle_scan_service import AngleScanService, AngleScanSettings


@pytest.fixture
def mock_camera() -> MagicMock:
    camera = MagicMock(spec=CameraDevice)
    camera.grab_one.return_value = np.zeros((10, 10), dtype=np.uint16)
    return camera


def acknowledge_preview_pause(service: AngleScanService) -> None:
    service.preview_pause_requested.connect(service.notify_preview_paused)


def test_build_angle_list_uses_current_position_as_zero() -> None:
    assert build_angle_list(1.0, 0.5, sign=1) == [0.0, 0.5, 1.0]
    assert build_angle_list(1.0, 0.5, sign=-1) == [0.0, -0.5, -1.0]
    assert build_angle_list(5.0, 0.6, sign=1) == [
        0.0,
        0.6,
        1.2,
        1.8,
        2.4,
        3.0,
        3.6,
        4.2,
        4.8,
        5.0,
    ]


def test_angle_scan_service_moves_by_delta_and_saves(
    qtbot: QtBot, tmp_path: Path, mock_camera: MagicMock
) -> None:
    storage = ExperimentStorage(tmp_path)
    motor = MagicMock()
    settings = AngleScanSettings(
        range_deg=1.0,
        interval_deg=0.5,
        direction="positive",
        settling_time_ms=0,
        return_to_start_after_scan=True,
        motor_speed_rpm=4.0,
    )
    service = AngleScanService(mock_camera, storage, motor, [10.0], [0], settings)
    acknowledge_preview_pause(service)

    with qtbot.waitSignal(service.scan_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is True
    assert blocker.args[1] == "angle_scan_001"
    assert [call.args[0] for call in motor.move_relative_units.call_args_list] == [
        angle_to_position_units(0.5),
        angle_to_position_units(1.0) - angle_to_position_units(0.5),
        -angle_to_position_units(1.0),
    ]
    assert [call.args[1] for call in motor.move_relative_units.call_args_list] == [
        4.0,
        4.0,
        4.0,
    ]
    assert mock_camera.grab_one.call_count == 3
    assert (
        storage.get_current_experiment_dir()
        / "angle_scan_001"
        / "angle+000.5"
        / "as001_angle+000.5_exp10_gain0.tiff"
    ).exists()


def test_angle_scan_service_saves_positive_interval_for_negative_scan(
    qtbot: QtBot, tmp_path: Path, mock_camera: MagicMock
) -> None:
    storage = ExperimentStorage(tmp_path)
    motor = MagicMock()
    settings = AngleScanSettings(
        range_deg=1.0,
        interval_deg=0.5,
        direction="negative",
        settling_time_ms=0,
        return_to_start_after_scan=False,
        motor_speed_rpm=4.0,
    )
    service = AngleScanService(mock_camera, storage, motor, [10.0], [0], settings)
    acknowledge_preview_pause(service)

    with qtbot.waitSignal(service.scan_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is True
    assert [call.args[0] for call in motor.move_relative_units.call_args_list] == [
        angle_to_position_units(-0.5),
        angle_to_position_units(-1.0) - angle_to_position_units(-0.5),
    ]

    with (
        storage.get_current_experiment_dir() / "angle_scan_001" / "scan.json"
    ).open(encoding="utf-8") as f:
        scan_document = json.load(f)

    assert "target_deg" not in scan_document["angle_scan"]
    assert "target_from_current_deg" not in scan_document["angle_scan"]
    assert "settling_time_ms" not in scan_document["angle_scan"]
    assert "scan_opposite_direction" not in scan_document["angle_scan"]
    assert "reverse_scan" not in scan_document["angle_scan"]
    assert "speed_units" not in scan_document["angle_scan"]
    assert scan_document["angle_scan"]["range_deg"] == 1.0
    assert scan_document["angle_scan"]["interval_deg"] == 0.5
    assert scan_document["angle_scan"]["direction"] == "negative"
    assert scan_document["angle_scan"]["motor_speed_rpm"] == 4.0
    assert scan_document["angle_scan"]["position_units_per_deg"] == 31.25
    assert scan_document["angle_scan"]["capture_angles_deg"] == [0.0, -0.5, -1.0]
    assert scan_document["angle_scan"]["wait_after_move_ms"] == 0
    assert scan_document["angle_scan"]["return_to_start"] is False


def test_angle_scan_service_scans_opposite_direction_after_returning_to_zero(
    qtbot: QtBot, tmp_path: Path, mock_camera: MagicMock
) -> None:
    storage = ExperimentStorage(tmp_path)
    motor = MagicMock()
    settings = AngleScanSettings(
        range_deg=1.0,
        interval_deg=0.5,
        direction="both",
        settling_time_ms=0,
        return_to_start_after_scan=False,
        motor_speed_rpm=4.0,
    )
    service = AngleScanService(mock_camera, storage, motor, [10.0], [0], settings)
    acknowledge_preview_pause(service)

    with qtbot.waitSignal(service.scan_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is True

    with (
        storage.get_current_experiment_dir() / "angle_scan_001" / "scan.json"
    ).open(encoding="utf-8") as f:
        scan_document = json.load(f)

    assert scan_document["angle_scan"]["direction"] == "both"
    assert scan_document["angle_scan"]["capture_angles_deg"] == [0.0, 0.5, 1.0, -0.5, -1.0]
    assert [call.args[0] for call in motor.move_relative_units.call_args_list] == [
        angle_to_position_units(0.5),
        angle_to_position_units(1.0) - angle_to_position_units(0.5),
        -angle_to_position_units(1.0),
        angle_to_position_units(-0.5),
        angle_to_position_units(-1.0) - angle_to_position_units(-0.5),
    ]
    assert mock_camera.grab_one.call_count == 5


def test_angle_scan_service_does_not_move_at_zero_degree_capture_point(
    qtbot: QtBot, tmp_path: Path, mock_camera: MagicMock
) -> None:
    storage = ExperimentStorage(tmp_path)
    motor = MagicMock()
    settings = AngleScanSettings(
        range_deg=0.5,
        interval_deg=0.5,
        direction="positive",
        settling_time_ms=0,
        return_to_start_after_scan=True,
        motor_speed_rpm=4.0,
    )
    service = AngleScanService(mock_camera, storage, motor, [10.0], [0], settings)
    acknowledge_preview_pause(service)

    with qtbot.waitSignal(service.scan_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is True
    assert [call.args[0] for call in motor.move_relative_units.call_args_list] == [
        angle_to_position_units(0.5),
        -angle_to_position_units(0.5),
    ]
    assert mock_camera.grab_one.call_count == 2


@pytest.mark.parametrize(
    ("interval_deg", "message"),
    [
        (0.0, "正の値"),
        (-0.5, "正の値"),
        (0.1, r"0\.5deg以上"),
    ],
)
def test_angle_scan_service_rejects_invalid_interval(
    mock_camera: MagicMock, tmp_path: Path, interval_deg: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        AngleScanService(
            mock_camera,
            ExperimentStorage(tmp_path),
            MagicMock(),
            [10.0],
            [0],
            AngleScanSettings(
                range_deg=1.0,
                interval_deg=interval_deg,
                direction="positive",
                settling_time_ms=0,
                return_to_start_after_scan=False,
            ),
        )


def test_angle_scan_service_rejects_out_of_range_range(
    mock_camera: MagicMock, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="90deg"):
        AngleScanService(
            mock_camera,
            ExperimentStorage(tmp_path),
            MagicMock(),
            [10.0],
            [0],
            AngleScanSettings(
                range_deg=90.5,
                interval_deg=0.5,
                direction="positive",
                settling_time_ms=0,
                return_to_start_after_scan=False,
            ),
        )


def test_angle_scan_service_rejects_interval_larger_than_range(
    mock_camera: MagicMock, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="走査範囲以下"):
        AngleScanService(
            mock_camera,
            ExperimentStorage(tmp_path),
            MagicMock(),
            [10.0],
            [0],
            AngleScanSettings(
                range_deg=1.0,
                interval_deg=1.5,
                direction="positive",
                settling_time_ms=0,
                return_to_start_after_scan=False,
            ),
        )


def test_angle_to_position_units_uses_configurable_device_condition() -> None:
    assert angle_to_position_units(0.5) == 16
    assert angle_to_position_units(1.0) == 31
    assert angle_to_position_units(-0.5) == -16
    assert angle_to_position_units(0.5, position_units_per_deg=40.0) == 20


def test_motion_unit_deltas_compensate_fractional_rounding() -> None:
    assert build_motion_unit_deltas([0.0, 0.5, 1.0, 1.5, 2.0]) == [
        0,
        16,
        15,
        16,
        16,
    ]
    assert sum(build_motion_unit_deltas([0.0, 0.5, 1.0])) == angle_to_position_units(1.0)


def test_angle_scan_service_rejects_invalid_position_units_per_deg(
    mock_camera: MagicMock, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="1deg"):
        AngleScanService(
            mock_camera,
            ExperimentStorage(tmp_path),
            MagicMock(),
            [10.0],
            [0],
            AngleScanSettings(
                range_deg=1.0,
                interval_deg=0.5,
                direction="positive",
                settling_time_ms=0,
                return_to_start_after_scan=False,
                position_units_per_deg=0.0,
            ),
        )
