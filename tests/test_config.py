import tempfile
from pathlib import Path

from rheed_capture.models.io.config_manager import ConfigManager


def test_config_save_load() -> None:
    """JSON形式での設定保存と読み込みのテスト"""
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.json"

        test_data = {
            "root_dir": "/dummy/path",
            "preview_exposure": 50.5,
            "sequence_exp_list": [10.0, 20.0],
        }

        # 保存
        ConfigManager.save(config_path, test_data)
        assert config_path.exists()

        # 読み込み
        loaded_data = ConfigManager.load(config_path)
        assert loaded_data["root_dir"] == "/dummy/path"
        assert loaded_data["preview_exposure"] == 50.5
        assert loaded_data["sequence_exp_list"] == [10.0, 20.0]


def test_config_load_not_found() -> None:
    """設定ファイルがない場合は空の辞書を返すか"""
    data = ConfigManager.load(Path("not_exist.json"))
    assert isinstance(data, dict)
    assert len(data) == 0
