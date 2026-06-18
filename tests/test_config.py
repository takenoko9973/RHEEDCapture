from pathlib import Path

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
