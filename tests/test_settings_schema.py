from rheed_capture.infrastructure.config.schema import AppSettingsData


def test_app_settings_data_reads_and_saves_numeric_candidate_schema() -> None:
    raw_settings = {
        "schema_version": 1,
        "output": {"root_dir": "D:/new"},
        "exposure_ms_values": [10.0, 20.0],
        "gain_values": [0, 1],
        "preview": {
            "exposure_ms": 200.0,
            "gain": 580,
            "clahe": {"enabled": True},
            "grid": {"enabled": False, "rows": 4, "cols": 4},
        },
        "sequence_capture": {
            "selected_exposure_ms_values": [10.0],
            "selected_gain_values": [0],
        },
        "angle_scan": {
            "selected_exposure_ms_values": [10.0, 999.0],
            "selected_gain_values": [0, 999],
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
    assert settings.exposure_ms_values == [10.0, 20.0]
    assert settings.gain_values == [0, 1]
    assert settings.sequence_capture.selected_exposure_ms_values == [10.0]
    assert settings.angle_scan.selected_exposure_ms_values == [10.0]
    assert settings.angle_scan.selected_gain_values == [0]

    saved = settings.to_dict()
    assert "exposure_chips" not in saved
    assert "gain_chips" not in saved
    assert "selected_exposure_chip_ids" not in saved["sequence_capture"]
    assert saved["exposure_ms_values"] == [10.0, 20.0]
