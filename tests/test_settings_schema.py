from rheed_capture.models.io.settings import AppSettingsData


def test_app_settings_data_round_trips_current_schema() -> None:
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

    assert settings.root_dir == "D:/data"
    assert settings.preview.exposure_ms == 15.5
    assert settings.angle_scan.direction == "both"
    assert settings.angle_scan.motor_speed_rpm == 900.0
    assert settings.device.motor.port == "COM8"
    assert settings.to_dict() == raw_settings
