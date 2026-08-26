import json
from pathlib import Path

import pytest

from rheed_capture.infrastructure.config.json_store import AppSettings
from rheed_capture.infrastructure.config.schema import AppSettingsData


def test_app_settings_save_load(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    original_path = AppSettings.FILE_PATH
    AppSettings.FILE_PATH = settings_path
    try:
        settings = AppSettingsData(root_dir="/dummy/path")

        AppSettings.save(settings)
        assert settings_path.exists()

        loaded = AppSettings.load()
        assert loaded.root_dir == "/dummy/path"
        assert loaded.to_dict()["schema_version"] == 1
    finally:
        AppSettings.FILE_PATH = original_path


def test_app_settings_load_not_found(tmp_path: Path) -> None:
    original_path = AppSettings.FILE_PATH
    AppSettings.FILE_PATH = tmp_path / "not_exist.json"
    try:
        settings = AppSettings.load()
        assert isinstance(settings, AppSettingsData)
    finally:
        AppSettings.FILE_PATH = original_path


def test_app_settings_load_invalid_json_uses_defaults(tmp_path: Path) -> None:
    """JSON decode失敗時は既定設定へ戻す。"""
    settings_path = tmp_path / "invalid.json"
    settings_path.write_text("{invalid", encoding="utf-8")
    original_path = AppSettings.FILE_PATH
    AppSettings.FILE_PATH = settings_path
    try:
        settings = AppSettings.load()
        assert isinstance(settings, AppSettingsData)
    finally:
        AppSettings.FILE_PATH = original_path


def test_app_settings_load_invalid_acquisition_propagates_validation_error(
    tmp_path: Path,
) -> None:
    """JSON内のAcquisition不正値は既定値へ置換せずValueErrorを伝播する。"""
    settings_path = tmp_path / "invalid_acquisition.json"
    settings_path.write_text(
        json.dumps({"acquisition": {"fps_limit": 0}}),
        encoding="utf-8",
    )
    original_path = AppSettings.FILE_PATH
    AppSettings.FILE_PATH = settings_path
    try:
        with pytest.raises(ValueError, match="fps_limit"):
            AppSettings.load()
    finally:
        AppSettings.FILE_PATH = original_path
