from __future__ import annotations

from typing import Any, cast

from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.infrastructure.config.defaults import (
    DEFAULT_ANGLE_SCAN_DIRECTION,
    DEFAULT_ANGLE_SCAN_INTERVAL_DEG,
    DEFAULT_ANGLE_SCAN_RANGE_DEG,
    DEFAULT_ANGLE_SCAN_RETURN_TO_START,
    DEFAULT_ANGLE_SCAN_WAIT_AFTER_MOVE_MS,
    DEFAULT_EXPOSURE_MS_VALUES,
    DEFAULT_GAIN_VALUES,
    DEFAULT_MOTOR_DRIVER,
    DEFAULT_PREVIEW_CLAHE_ENABLED,
    DEFAULT_PREVIEW_EXPOSURE_MS,
    DEFAULT_PREVIEW_GAIN,
    DEFAULT_PREVIEW_GRID_COLS,
    DEFAULT_PREVIEW_GRID_ENABLED,
    DEFAULT_PREVIEW_GRID_ROWS,
)
from rheed_capture.infrastructure.motor.defaults import (
    DEFAULT_MOTOR_PORT,
    DEFAULT_MOTOR_SLAVE,
    DEFAULT_POSITION_UNITS_PER_DEG,
)


def _as_mapping(value: object) -> dict[str, Any]:
    """旧設定の任意値を、安全にdictとして扱うための小さな正規化関数。"""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)

    return {}


def migrate_settings_dict(data: dict[str, Any]) -> dict[str, Any]:
    """旧形式またはschema未指定の設定dictをschema_version=1形式へ移行する。"""
    if data.get("schema_version") == 1:
        return data

    device = _as_mapping(data.get("device"))
    motor = _as_mapping(device.get("motor"))

    return {
        "schema_version": 1,
        "output": {
            "root_dir": str(data.get("root_dir", "")),
        },
        "preview": {
            "exposure_ms": float(data.get("preview_expo", DEFAULT_PREVIEW_EXPOSURE_MS)),
            "gain": int(data.get("preview_gain", DEFAULT_PREVIEW_GAIN)),
            "clahe": {
                "enabled": bool(data.get("enable_clahe", DEFAULT_PREVIEW_CLAHE_ENABLED)),
            },
            "grid": {
                "enabled": bool(data.get("show_preview_grid", DEFAULT_PREVIEW_GRID_ENABLED)),
                "rows": int(data.get("preview_grid_rows", DEFAULT_PREVIEW_GRID_ROWS)),
                "cols": int(data.get("preview_grid_cols", DEFAULT_PREVIEW_GRID_COLS)),
            },
        },
        "sequence_capture": _as_mapping(data.get("sequence_capture"))
        or {
            "exposure_ms_list": list(DEFAULT_EXPOSURE_MS_VALUES),
            "gain_list": list(DEFAULT_GAIN_VALUES),
        },
        "angle_scan": _as_mapping(data.get("angle_scan"))
        or {
            "exposure_ms_list": list(DEFAULT_EXPOSURE_MS_VALUES),
            "gain_list": list(DEFAULT_GAIN_VALUES),
            "range_deg": DEFAULT_ANGLE_SCAN_RANGE_DEG,
            "interval_deg": DEFAULT_ANGLE_SCAN_INTERVAL_DEG,
            "direction": DEFAULT_ANGLE_SCAN_DIRECTION,
            "wait_after_move_ms": DEFAULT_ANGLE_SCAN_WAIT_AFTER_MOVE_MS,
            "motor_speed_rpm": DEFAULT_MOTOR_SPEED_RPM,
            "return_to_start": DEFAULT_ANGLE_SCAN_RETURN_TO_START,
        },
        "device": {
            "motor": {
                "driver": str(motor.get("driver", DEFAULT_MOTOR_DRIVER)),
                "connection": {
                    "type": "serial",
                    "port": str(motor.get("port", DEFAULT_MOTOR_PORT)),
                    "slave_id": int(motor.get("slave", DEFAULT_MOTOR_SLAVE)),
                },
                "calibration": {
                    "position_units_per_deg": float(
                        motor.get("position_units_per_deg", DEFAULT_POSITION_UNITS_PER_DEG)
                    ),
                },
            }
        },
    }
