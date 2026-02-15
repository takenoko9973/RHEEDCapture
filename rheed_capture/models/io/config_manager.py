import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ConfigManager:
    """設定情報をJSONファイルとして保存・復元する静的クラス"""

    @staticmethod
    def save(file_path: Path | str, config_dict: dict) -> None:
        file_path = Path(file_path)

        try:
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(config_dict, f, indent=4)
        except Exception:
            logger.exception("設定の保存に失敗しました")

    @staticmethod
    def load(file_path: Path | str) -> dict:
        path = Path(file_path)
        if not path.exists():
            return {}

        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)

        except Exception:
            logger.exception("設定の読み込みに失敗しました")
            return {}
