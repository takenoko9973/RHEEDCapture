import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AppSettings:
    FILE_PATH = Path("settings.json")

    @classmethod
    def save(cls, data: dict) -> None:
        try:
            with cls.FILE_PATH.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            logger.exception("設定の保存に失敗しました")

    @classmethod
    def load(cls) -> dict:
        if not cls.FILE_PATH.exists():
            return {}

        try:
            with cls.FILE_PATH.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception("設定の読み込みに失敗しました")
            return {}
