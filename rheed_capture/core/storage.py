import logging
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
    """1回の実験セッションにおけるディレクトリパスと連番状態を管理するクラス。
    呼び出し側から複雑なパス操作を隠蔽する。
    """

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

        # 初期化時に今日の実験フォルダ (yymmdd または yymmdd-n) を確定させる
        self.date_prefix = datetime.now(JST).strftime("%y%m%d")
        self.experiment_dir = self._resolve_experiment_dir()

        # シーケンス状態の管理
        self.sequence_counter = 0
        self.current_sequence_dir = None

        logger.info("データ保存先が決定しました: %s", self.experiment_dir)

    def _resolve_experiment_dir(self) -> Path:
        """Yymmdd フォルダを決定する。既に存在する場合は -2, -3 とインクリメントする"""

        def date_dir_name(date_str: str, num: int) -> str:
            if num == 1:
                return date_str

            return f"{date_str}-{num}"

        counter = 1
        while True:
            branch_dir = self.root_dir / date_dir_name(self.date_prefix, counter)
            if not branch_dir.exists():
                branch_dir.mkdir(parents=True)
                return branch_dir

            counter += 1

    def start_new_sequence(self) -> None:
        """新しい撮影シーケンスを開始する。
        image_001, image_002 のように連番フォルダを作成し、内部カウンタを進める。
        """
        self.sequence_counter += 1
        dir_name = f"image_{self.sequence_counter:03d}"

        self.current_sequence_dir = self.experiment_dir / dir_name
        self.current_sequence_dir.mkdir(parents=True, exist_ok=True)

    def save_frame(
        self, image_data: np.ndarray, exposure_ms: float, gain: float, metadata: dict
    ) -> Path:
        """現在のシーケンスフォルダに画像ファイルを保存する。
        ファイル名の規則: {yymmdd}-{n}_expo{Exposure}_gain{Gain}.tiff

        Args:
            image_data: 保存する生データ(uint16)
            exposure_ms: 露光時間
            gain: ゲイン
            metadata: 埋め込むメタデータ

        Returns:
            Path: 保存されたファイルの絶対パス

        """
        if self.current_sequence_dir is None:
            msg = "シーケンスが開始されていません。先に start_new_sequence() を呼び出してください。"
            raise RuntimeError(msg)

        # ファイル名の生成
        prefix = f"{self.date_prefix}-{self.sequence_counter}"
        filename = f"{prefix}_expo{exposure_ms:g}_gain{gain:g}.tiff"
        file_path = self.current_sequence_dir / filename

        # 実際の書き込みは TiffWriter に委譲
        TiffWriter.save(file_path, image_data, metadata)

        return file_path
