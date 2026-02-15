import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import tifffile

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")


class TiffWriter:
    """TIFFファイルの書き込みのみを担当する静的クラス (状態を持たない)"""

    @staticmethod
    def save(file_path: Path, image_data: np.ndarray, metadata: dict) -> None:
        """16bit画像データを非圧縮TIFFとして保存し、メタデータを埋め込む。"""
        try:
            tifffile.imwrite(file_path, image_data, photometric="minisblack", metadata=metadata)
        except Exception:
            logger.exception("TIFF保存に失敗しました (%s)", file_path)
            raise


class ExperimentStorage:
    root_dir: Path

    _branch_number: int
    _sequence_counter: int

    def __init__(self, root_dir: str | Path) -> None:
        self.date_str = datetime.now(JST).strftime("%y%m%d")
        self._branch_number = 1  # yymmdd-n
        self._sequence_counter = 0  # 写真枚数をカウント

        self.set_root_dir(root_dir)

    def set_root_dir(self, root_dir: str | Path) -> None:
        """ルートディレクトリを設定し、既存のブランチと連番をスキャンする"""
        self.root_dir = Path(root_dir)

        if not self.root_dir.exists():
            return

        # 今日の日付の最大のブランチ (yymmdd-n) を探す
        self._branch_number = self._search_max_branch()
        # そのブランチ内にある最大の連番 (image_nnn) を探す
        self._sequence_counter = self._search_max_sequence()

        exp_dir = self.get_current_experiment_dir()
        logger.info("保存先設定: %s (Next Sequence: %d)", exp_dir, self._sequence_counter + 1)

    def get_current_experiment_dir(self) -> Path:
        """現在ターゲットとなっている実験ディレクトリのパスを取得 (作成はしない)"""
        if self._branch_number == 1:
            return self.root_dir / f"{self.date_str}"

        return self.root_dir / f"{self.date_str}-{self._branch_number}"

    def get_current_sequence_dir(self) -> Path:
        """現在ターゲットとなっている画像ディレクトリのパスを取得 (作成はしない)"""
        exp_dir = self.get_current_experiment_dir()
        return exp_dir / f"image_{self._sequence_counter:03d}"

    def _search_max_branch(self) -> int:
        """最大のブランチ番号 (yymmdd-n) を探す"""
        pattern = re.compile(rf"^{re.escape(self.date_str)}(?:-(\d+))?$")

        # 条件に合致するディレクトリのみを抽出し、接尾辞の番号をリスト化
        suffixes = [
            int(match.group(1) or 1)
            for path in Path(self.root_dir).iterdir()
            if path.is_dir() and (match := pattern.match(path.name))
        ]

        return max(suffixes, default=1)

    def _search_max_sequence(self) -> int:
        """そのブランチ内にある最大の連番 (image_nnn) を探す"""
        exp_dir = self.get_current_experiment_dir()
        if not exp_dir.exists():
            return 0  # 作成してなければ 0 を返す

        pattern = re.compile(r"image_(\d{3})")

        # 条件に合致するディレクトリのみを抽出し、接尾辞の番号をリスト化
        suffixes = [
            int(match.group(1) or 1)
            for path in Path(exp_dir).iterdir()
            if path.is_dir() and (match := pattern.match(path.name))
        ]

        return max(suffixes, default=0)

    def increment_branch(self) -> None:
        """手動で新しいブランチ(-n)に進める。連番はリセットされる。"""
        self._branch_number = self._branch_number + 1
        self._sequence_counter = 0

    def start_new_sequence(self) -> None:
        """ここで初めてフォルダを作成する (Lazy Creation)"""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        exp_dir = self.get_current_experiment_dir()
        exp_dir.mkdir(parents=True, exist_ok=True)

        self._sequence_counter += 1
        sequence_dir = self.get_current_sequence_dir()
        sequence_dir.mkdir(parents=True, exist_ok=True)
        logger.info("新規シーケンス作成: %s", self.get_current_sequence_dir())

    def save_frame(
        self, image_data: np.ndarray, exposure_ms: float, gain: float, metadata: dict
    ) -> Path:
        """画像データを保存する"""
        if not self.get_current_sequence_dir().exists():
            msg = "シーケンスが開始されていません。"
            raise RuntimeError(msg)

        exp_dir_name = self.get_current_experiment_dir().name
        filename = f"{exp_dir_name}-{self._sequence_counter}_expo{exposure_ms:g}_gain{gain:g}.tiff"

        file_path = self.get_current_sequence_dir() / filename
        TiffWriter.save(file_path, image_data, metadata)
        return file_path
