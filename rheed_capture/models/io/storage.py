import json
import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import tifffile

from rheed_capture.models.io.scan_document import AngleScanDocument

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
    _angle_scan_counter: int

    def __init__(self, root_dir: str | Path) -> None:
        self.date_str = datetime.now(JST).strftime("%y%m%d")
        self._branch_number = 1  # yymmdd-n
        self._sequence_counter = 0  # 写真枚数をカウント
        self._angle_scan_counter = 0

        self.set_root_dir(root_dir)

    def set_root_dir(self, root_dir: str | Path) -> None:
        """ルートディレクトリを設定し、既存のブランチと連番をスキャンする"""
        self.root_dir = Path(root_dir)

        if not self.root_dir.exists():
            return

        # 今日の日付の最大のブランチ (yymmdd-n) を探す
        self._branch_number = self._search_max_branch()
        # そのブランチ内にある最大の連番を探す
        self.refresh_capture_counters_from_disk()

        exp_dir = self.get_current_experiment_dir()
        logger.info("保存先設定: %s (Next Sequence: %d)", exp_dir, self.get_next_sequence_number())

    def get_current_experiment_dir(self) -> Path:
        """現在ターゲットとなっている実験ディレクトリのパスを取得 (作成はしない)"""
        if self._branch_number == 1:
            return self.root_dir / f"{self.date_str}"

        return self.root_dir / f"{self.date_str}-{self._branch_number}"

    def get_current_sequence_dir(self) -> Path:
        """現在ターゲットとなっている画像ディレクトリのパスを取得 (作成はしない)"""
        exp_dir = self.get_current_experiment_dir()
        return exp_dir / f"image_{self._sequence_counter:03d}"

    def get_current_angle_scan_dir(self) -> Path:
        """現在ターゲットとなっている角度走査ディレクトリのパスを取得する。"""
        exp_dir = self.get_current_experiment_dir()
        return exp_dir / f"angle_scan_{self._angle_scan_counter:03d}"

    def refresh_sequence_counter_from_disk(self) -> None:
        """現在ブランチ配下を再スキャンし、内部の連番カウンタを同期する。"""
        self._sequence_counter = self._search_max_sequence()

    def refresh_angle_scan_counter_from_disk(self) -> None:
        """現在ブランチ配下を再スキャンし、角度走査の連番カウンタを同期する。"""
        self._angle_scan_counter = self._search_max_angle_scan()

    def refresh_capture_counters_from_disk(self) -> None:
        """現在ブランチ配下を再スキャンし、通常/角度走査の連番を同期する。"""
        self.refresh_sequence_counter_from_disk()
        self.refresh_angle_scan_counter_from_disk()

    def get_next_sequence_dir_name(self) -> str:
        """次回撮影時に作成されるシーケンスディレクトリ名を返す。"""
        return f"image_{self.get_next_sequence_number():03d}"

    def get_next_angle_scan_dir_name(self) -> str:
        """次回角度走査時に作成されるディレクトリ名を返す。"""
        return f"angle_scan_{self.get_next_angle_scan_number():03d}"

    def get_next_sequence_number(self) -> int:
        """次回撮影時に使われるシーケンス番号を返す。"""
        return self._sequence_counter + 1

    def get_next_angle_scan_number(self) -> int:
        """次回角度走査時に使われる走査番号を返す。"""
        return self._angle_scan_counter + 1

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
        return self._search_max_number_in_current_experiment(r"^image_(\d{3})$")

    def _search_max_angle_scan(self) -> int:
        """そのブランチ内にある最大の連番 (angle_scan_nnn) を探す。"""
        return self._search_max_number_in_current_experiment(r"^angle_scan_(\d{3})$")

    def _search_max_number_in_current_experiment(self, pattern_text: str) -> int:
        """現在ブランチ直下で、命名規則に合う最大連番を探す。"""
        exp_dir = self.get_current_experiment_dir()
        if not exp_dir.exists():
            return 0

        pattern = re.compile(pattern_text)
        suffixes = [
            int(match.group(1))
            for path in Path(exp_dir).iterdir()
            if path.is_dir() and (match := pattern.match(path.name))
        ]

        return max(suffixes, default=0)

    def increment_branch(self) -> None:
        """手動で新しいブランチ(-n)に進める。連番はリセットされる。"""
        self._branch_number = self._branch_number + 1
        self._sequence_counter = 0
        self._angle_scan_counter = 0

    def start_new_sequence(self) -> None:
        """ここで初めてフォルダを作成する (Lazy Creation)"""
        # 外部でフォルダ削除・追加が行われる運用に追従するため、
        # 毎回ディスク上の最新状態を再スキャンしてから次番号を確定する。
        self.refresh_capture_counters_from_disk()

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

    def start_new_angle_scan(self, scan_document: AngleScanDocument) -> tuple[str, Path]:
        """角度走査用フォルダを作成し、scan.jsonを保存する。"""
        self.refresh_capture_counters_from_disk()

        self.root_dir.mkdir(parents=True, exist_ok=True)
        exp_dir = self.get_current_experiment_dir()
        exp_dir.mkdir(parents=True, exist_ok=True)

        self._angle_scan_counter += 1
        scan_id = f"as{self._angle_scan_counter:03d}"
        scan_dir = self.get_current_angle_scan_dir()
        scan_dir.mkdir(parents=True, exist_ok=False)

        document = scan_document.with_scan_id(scan_id)
        if not document.created_at:
            document = document.with_created_at(datetime.now(JST).isoformat())

        with (scan_dir / "scan.json").open("w", encoding="utf-8") as f:
            json.dump(document.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info("新規角度走査作成: %s", scan_dir)
        return scan_id, scan_dir

    def save_angle_scan_frame(
        self,
        image_data: np.ndarray,
        scan_id: str,
        target_angle_deg: float,
        exposure_ms: float,
        gain: float,
        metadata: dict,
    ) -> Path:
        """角度走査の画像データを角度別サブフォルダへ保存する。"""
        scan_dir = self.get_current_angle_scan_dir()
        if not scan_dir.exists():
            msg = "角度走査が開始されていません。"
            raise RuntimeError(msg)

        angle_dir = scan_dir / self.format_angle_dir_name(target_angle_deg)
        angle_dir.mkdir(parents=True, exist_ok=True)

        filename = self.format_angle_scan_filename(
            scan_id=scan_id,
            target_angle_deg=target_angle_deg,
            exposure_ms=exposure_ms,
            gain=gain,
        )
        file_path = angle_dir / filename
        if file_path.exists():
            msg = f"同名の角度走査TIFFが既に存在します: {file_path}"
            raise FileExistsError(msg)

        TiffWriter.save(file_path, image_data, metadata)
        return file_path

    @staticmethod
    def format_angle_dir_name(angle_deg: float) -> str:
        return f"angle{angle_deg:+06.1f}"

    @staticmethod
    def format_angle_scan_filename(
        scan_id: str, target_angle_deg: float, exposure_ms: float, gain: float
    ) -> str:
        return (
            f"{scan_id}_angle{target_angle_deg:+06.1f}_"
            f"exp{exposure_ms:g}_gain{gain:g}.tiff"
        )
