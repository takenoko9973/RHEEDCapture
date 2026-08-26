from typing import cast

import pytest

from rheed_capture.infrastructure.config.schema import (
    AppSettingsData,
    RecordingCaptureSettings,
)


def test_app_settings_data_reads_and_saves_numeric_candidate_schema() -> None:
    """数値候補形式のsettingsを読み込み保存形式へ戻せることを確認する。"""
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
        "recording_capture": {
            "exposure_ms": 50.0,
            "gain": 1,
            "rate_mode": "fps",
            "fps": 20.0,
            "interval_ms": 50.0,
            "duration_sec": 10.0,
            "tiff_compression_enabled": False,
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
    assert settings.recording_capture.rate_mode == "fps"
    assert settings.recording_capture.fps == 20.0
    assert settings.recording_capture.tiff_compression_enabled is False

    saved = settings.to_dict()
    assert "exposure_chips" not in saved
    assert "gain_chips" not in saved
    assert "selected_exposure_chip_ids" not in saved["sequence_capture"]
    assert saved["exposure_ms_values"] == [10.0, 20.0]
    assert saved["recording_capture"]["rate_mode"] == "fps"
    assert saved["recording_capture"]["tiff_compression_enabled"] is False


def test_missing_recording_capture_section_uses_section_default() -> None:
    """recording_capture未作成時だけ同セクションの既定値を使う。"""
    raw_settings = {
        "schema_version": 1,
        "output": {"root_dir": "D:/new"},
        "preview": {
            "exposure_ms": 42.0,
            "gain": 569,
            "clahe": {"enabled": False},
            "grid": {"enabled": False, "rows": 4, "cols": 4},
        },
    }

    settings = AppSettingsData.from_dict(raw_settings)

    assert settings.preview.gain == 569
    assert settings.recording_capture.rate_mode == "interval"
    assert settings.recording_capture.interval_ms == 100.0
    assert settings.recording_capture.tiff_compression_enabled is True


def test_existing_recording_capture_section_missing_compression_uses_true_default() -> None:
    """既存Recording設定に新圧縮キーがなくても従来zlibを維持する。"""
    settings = AppSettingsData.from_dict(
        {
            "recording_capture": {
                "exposure_ms": 50.0,
                "gain": 1,
                "rate_mode": "interval",
                "fps": 10.0,
                "interval_ms": 100.0,
                "duration_sec": 0.0,
            }
        }
    )

    assert settings.recording_capture.tiff_compression_enabled is True
    assert settings.to_dict()["recording_capture"]["tiff_compression_enabled"] is True


@pytest.mark.parametrize("invalid_value", [None, 0, 1, "false", {}, []])
def test_recording_compression_setting_rejects_non_boolean_values(
    invalid_value: object,
) -> None:
    """Recording圧縮設定はJSON boolean以外を受け入れない。"""
    data = {
        "exposure_ms": 50.0,
        "gain": 1,
        "rate_mode": "interval",
        "fps": 10.0,
        "interval_ms": 100.0,
        "duration_sec": 0.0,
        "tiff_compression_enabled": invalid_value,
    }

    with pytest.raises(ValueError, match="tiff_compression_enabled"):
        RecordingCaptureSettings.from_dict(data)

    with pytest.raises(ValueError, match="tiff_compression_enabled"):
        RecordingCaptureSettings(tiff_compression_enabled=cast("bool", invalid_value))


def test_present_but_invalid_recording_capture_section_raises() -> None:
    """recording_captureが存在して不正な場合は読み込み失敗にする。"""
    raw_settings = {
        "schema_version": 1,
        "recording_capture": {
            "exposure_ms": 50.0,
            "gain": 1,
            "rate_mode": "bad",
            "fps": 20.0,
            "interval_ms": 50.0,
            "duration_sec": 10.0,
        },
    }

    with pytest.raises(ValueError, match="rate_mode"):
        AppSettingsData.from_dict(raw_settings)


def test_acquisition_settings_roundtrip_and_trigger_conversion() -> None:
    """共通Acquisition設定を読み込み、保存後も値とTrigger変換を保つ。"""
    raw_settings = {
        "acquisition": {
            "mode": "hardware",
            "hardware_source": "Line3",
            "hardware_activation": "FallingEdge",
            "hardware_delay_us": 12.5,
            "fps_limit": 24.0,
            "accumulation_enabled": True,
            "accumulation_frames": 4,
            "trigger_wait_timeout_sec": 2.5,
        }
    }

    settings = AppSettingsData.from_dict(raw_settings)

    assert settings.schema_version == 1
    assert settings.acquisition.mode == "hardware"
    assert settings.acquisition.hardware_source == "Line3"
    assert settings.acquisition.hardware_activation == "FallingEdge"
    assert settings.acquisition.hardware_delay_us == 12.5
    assert settings.acquisition.fps_limit == 24.0
    assert settings.acquisition.accumulation_enabled is True
    assert settings.acquisition.accumulation_frames == 4
    assert settings.acquisition.trigger_wait_timeout_sec == 2.5

    saved = settings.to_dict()
    restored = AppSettingsData.from_dict(saved)
    assert restored.acquisition == settings.acquisition
    trigger_settings = restored.acquisition.to_trigger_settings()
    assert trigger_settings.mode == "hardware"
    assert trigger_settings.hardware_source == "Line3"
    assert trigger_settings.hardware_activation == "FallingEdge"
    assert trigger_settings.hardware_delay_us == 12.5
    assert trigger_settings.fps_limit == 24.0


def test_missing_acquisition_section_uses_defaults() -> None:
    """既存settingsにacquisition sectionがなくても既定値で読み込める。"""
    settings = AppSettingsData.from_dict({"schema_version": 1})

    assert settings.acquisition.mode == "software"
    assert settings.acquisition.hardware_source == "Line1"
    assert settings.acquisition.hardware_activation == "RisingEdge"
    assert settings.acquisition.hardware_delay_us == 0.0
    assert settings.acquisition.fps_limit is None
    assert settings.acquisition.accumulation_enabled is False
    assert settings.acquisition.accumulation_frames == 1
    assert settings.acquisition.trigger_wait_timeout_sec == 0.0


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("mode", "burst", "mode"),
        ("hardware_source", "Line2", "hardware_source"),
        ("hardware_activation", "Both", "hardware_activation"),
        ("hardware_delay_us", -1.0, "hardware_delay_us"),
        ("fps_limit", 0.0, "fps_limit"),
        ("accumulation_frames", 0, "accumulation_frames"),
        ("accumulation_frames", 1.5, "accumulation_frames"),
        ("trigger_wait_timeout_sec", -1.0, "trigger_wait_timeout_sec"),
    ],
)
def test_present_but_invalid_acquisition_setting_raises(
    field: str,
    value: object,
    match: str,
) -> None:
    """存在するacquisitionの不正値を既定値へ黙って置換しない。"""
    with pytest.raises(ValueError, match=match):
        AppSettingsData.from_dict({"acquisition": {field: value}})


def test_present_but_non_object_acquisition_section_raises() -> None:
    """acquisition sectionがobject以外の場合は明示的に失敗する。"""
    with pytest.raises(ValueError, match="acquisition"):
        AppSettingsData.from_dict({"acquisition": None})
