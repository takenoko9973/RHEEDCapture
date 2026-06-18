from __future__ import annotations

import json
import logging
from pathlib import Path

from rheed_capture.infrastructure.config.schema import AppSettingsData

logger = logging.getLogger(__name__)


class AppSettings:
    """settings.jsonの読み書きだけを担当するInfrastructureクラス。"""

    FILE_PATH = Path("settings.json")

    @classmethod
    def save(cls, settings: AppSettingsData) -> None:
        """現在の設定モデルを新schema形式のJSONとして保存する。"""
        try:
            with cls.FILE_PATH.open("w", encoding="utf-8") as f:
                json.dump(settings.to_dict(), f, ensure_ascii=False, indent=4)
        except Exception:
            logger.exception("設定の保存に失敗しました")

    @classmethod
    def load(cls) -> AppSettingsData:
        """settings.jsonを読み込み、存在しない/壊れている場合は既定値を返す。"""
        if not cls.FILE_PATH.exists():
            return AppSettingsData()

        try:
            with cls.FILE_PATH.open(encoding="utf-8") as f:
                return AppSettingsData.from_dict(json.load(f))
        except Exception:
            logger.exception("設定の読み込みに失敗しました")
            return AppSettingsData()
