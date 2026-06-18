from rheed_capture.infrastructure.config.schema import AppSettingsData


def test_app_settings_data_reads_legacy_schema_and_saves_new_schema() -> None:
    raw_settings = {
        "root_dir": "D:/data",
        "preview_expo": 15.5,
        "preview_gain": 2,
        "enable_clahe": True,
        "show_preview_grid": True,
        "preview_grid_rows": 8,
        "preview_grid_cols": 8,
        "sequence_capture": {
            "exposure_ms_list": [10.0, 20.0],
            "gain_list": [0, 1],
        },
        "angle_scan": {
            "exposure_ms_list": [10.0, 20.0],
            "gain_list": [0, 1],
            "range_deg": 5.0,
            "interval_deg": 0.5,
            "direction": "both",
            "wait_after_move_ms": 1000,
            "motor_speed_rpm": 900.0,
            "return_to_start": True,
        },
        "device": {
            "motor": {
                "port": "COM8",
                "slave": 3,
                "position_units_per_deg": 31.25,
            },
        },
    }

    settings = AppSettingsData.from_dict(raw_settings)
    saved = settings.to_dict()

    assert settings.root_dir == "D:/data"
    assert settings.preview.exposure_ms == 15.5
    assert settings.angle_scan.direction == "both"
    assert settings.angle_scan.motor_speed_rpm == 900.0
    assert settings.device.motor.port == "COM8"
    assert saved["schema_version"] == 1
    assert saved["output"]["root_dir"] == "D:/data"
    assert saved["preview"]["clahe"]["enabled"] is True
    assert saved["device"]["motor"]["connection"]["slave_id"] == 3


def test_app_settings_data_reads_new_schema() -> None:
    raw_settings = {
        "schema_version": 1,
        "output": {"root_dir": "D:/new"},
        "preview": {
            "exposure_ms": 200.0,
            "gain": 580,
            "clahe": {"enabled": True},
            "grid": {"enabled": False, "rows": 4, "cols": 4},
        },
        "sequence_capture": {"exposure_ms_list": [10.0], "gain_list": [0]},
        "angle_scan": {
            "exposure_ms_list": [10.0],
            "gain_list": [0],
            "range_deg": 5.0,
            "interval_deg": 0.5,
            "direction": "both",
            "wait_after_move_ms": 1000,
            "motor_speed_rpm": 750.0,
            "return_to_start": False,
        },
        "device": {
            "motor": {
                "driver": "azd_cd",
                "connection": {"type": "serial", "port": "COM7", "slave_id": 2},
                "calibration": {"position_units_per_deg": 31.25},
            }
        },
    }

    settings = AppSettingsData.from_dict(raw_settings)

    assert settings.root_dir == "D:/new"
    assert settings.preview.gain == 580
    assert settings.device.motor.port == "COM7"
    assert settings.to_dict() == raw_settings
