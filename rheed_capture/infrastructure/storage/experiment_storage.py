from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from rheed_capture.infrastructure.storage.sessions.angle_scan import AngleScanSession
from rheed_capture.infrastructure.storage.sessions.sequence import SequenceSession

if TYPE_CHECKING:
    import numpy as np

    from rheed_capture.data_formats.angle_scan_document import AngleScanDocument

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")


class ExperimentStorage:
    """実験日ディレクトリ、branch、撮影Session番号を管理するStorage入口。"""

    root_dir: Path

    _branch_number: int
    _sequence_counter: int
    _angle_scan_counter: int

    def __init__(self, root_dir: str | Path) -> None:
        self.date_str = datetime.now(JST).strftime("%y%m%d")
        self._branch_number = 1
        self._sequence_counter = 0
        self._angle_scan_counter = 0
        self._current_sequence_session: SequenceSession | None = None
        self._current_angle_scan_session: AngleScanSession | None = None

        self.set_root_dir(root_dir)

    def set_root_dir(self, root_dir: str | Path) -> None:
        """保存ルートを切り替え、既存ディレクトリから次の番号を再同期する。"""
        self.root_dir = Path(root_dir)

        if not self.root_dir.exists():
            return

        self._branch_number = self._search_max_branch()
        self.refresh_capture_counters_from_disk()

        exp_dir = self.get_current_experiment_dir()
        logger.info("保存先設定: %s (Next Sequence: %d)", exp_dir, self.get_next_sequence_number())

    def get_current_experiment_dir(self) -> Path:
        """現在選択中の実験日/branchディレクトリを返す。"""
        if self._branch_number == 1:
            return self.root_dir / f"{self.date_str}"

        return self.root_dir / f"{self.date_str}-{self._branch_number}"

    def get_current_sequence_dir(self) -> Path:
        """現在のSequence番号に対応する互換表示用ディレクトリを返す。"""
        return self.get_current_experiment_dir() / f"image_{self._sequence_counter:03d}"

    def get_current_angle_scan_dir(self) -> Path:
        """現在のAngle Scan番号に対応する互換表示用ディレクトリを返す。"""
        return self.get_current_experiment_dir() / f"angle_scan_{self._angle_scan_counter:03d}"

    def refresh_sequence_counter_from_disk(self) -> None:
        """ディスク上の `image_NNN` 最大値をSequenceカウンタへ反映する。"""
        self._sequence_counter = self._search_max_sequence()

    def refresh_angle_scan_counter_from_disk(self) -> None:
        """ディスク上の `angle_scan_NNN` 最大値をAngle Scanカウンタへ反映する。"""
        self._angle_scan_counter = self._search_max_angle_scan()

    def refresh_capture_counters_from_disk(self) -> None:
        """撮影種別ごとの次番号をまとめて再同期する。"""
        self.refresh_sequence_counter_from_disk()
        self.refresh_angle_scan_counter_from_disk()

    def get_next_sequence_dir_name(self) -> str:
        """次に作成されるSequenceディレクトリ名をUI表示用に返す。"""
        return f"image_{self.get_next_sequence_number():03d}"

    def get_next_angle_scan_dir_name(self) -> str:
        """次に作成されるAngle Scanディレクトリ名をUI表示用に返す。"""
        return f"angle_scan_{self.get_next_angle_scan_number():03d}"

    def get_next_sequence_number(self) -> int:
        return self._sequence_counter + 1

    def get_next_angle_scan_number(self) -> int:
        return self._angle_scan_counter + 1

    def _search_max_branch(self) -> int:
        pattern = re.compile(rf"^{re.escape(self.date_str)}(?:-(\d+))?$")
        suffixes = [
            int(match.group(1) or 1)
            for path in Path(self.root_dir).iterdir()
            if path.is_dir() and (match := pattern.match(path.name))
        ]
        return max(suffixes, default=1)

    def _search_max_sequence(self) -> int:
        return self._search_max_number_in_current_experiment(r"^image_(\d{3})$")

    def _search_max_angle_scan(self) -> int:
        return self._search_max_number_in_current_experiment(r"^angle_scan_(\d{3})$")

    def _search_max_number_in_current_experiment(self, pattern_text: str) -> int:
        """現在の実験ディレクトリで、指定形式の最大3桁番号を探す。"""
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
        """手動branch更新時に、撮影Session番号と作成済みSession参照をリセットする。"""
        self._branch_number = self._branch_number + 1
        self._sequence_counter = 0
        self._angle_scan_counter = 0
        self._current_sequence_session = None
        self._current_angle_scan_session = None

    def _ensure_experiment_dir(self) -> Path:
        """Session作成前にルートと現在の実験ディレクトリを用意する。"""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        exp_dir = self.get_current_experiment_dir()
        exp_dir.mkdir(parents=True, exist_ok=True)
        return exp_dir

    def start_sequence_session(self) -> SequenceSession:
        """次の `image_NNN` を確定し、SequenceSessionを生成する。"""
        self.refresh_capture_counters_from_disk()
        exp_dir = self._ensure_experiment_dir()

        self._sequence_counter += 1
        sequence_dir = self.get_current_sequence_dir()
        sequence_dir.mkdir(parents=True, exist_ok=True)

        self._current_sequence_session = SequenceSession(
            sequence_dir,
            experiment_dir_name=exp_dir.name,
            sequence_number=self._sequence_counter,
        )
        logger.info("新規シーケンス作成: %s", sequence_dir)
        return self._current_sequence_session

    def start_angle_scan_session(self, scan_document: AngleScanDocument) -> AngleScanSession:
        """次の `angle_scan_NNN` とscan_idを確定し、AngleScanSessionを生成する。"""
        self.refresh_capture_counters_from_disk()
        self._ensure_experiment_dir()

        self._angle_scan_counter += 1
        scan_id = f"as{self._angle_scan_counter:03d}"
        scan_dir = self.get_current_angle_scan_dir()
        scan_dir.mkdir(parents=True, exist_ok=False)

        self._current_angle_scan_session = AngleScanSession(
            scan_dir,
            scan_id=scan_id,
            scan_document=scan_document,
        )
        logger.info("新規角度走査作成: %s", scan_dir)
        return self._current_angle_scan_session

    def start_new_sequence(self) -> None:
        """既存UI/テスト互換のSequence開始API。新規コードはSessionを直接使う。"""
        self.start_sequence_session()

    def save_frame(
        self,
        image_data: np.ndarray,
        exposure_ms: float,
        gain: float,
        metadata: dict,
    ) -> Path:
        """既存API互換のSequence保存。ファイル名生成はSequenceSessionへ委譲する。"""
        if self._current_sequence_session is None:
            msg = "シーケンスが開始されていません。"
            raise RuntimeError(msg)

        return self._current_sequence_session.save_raw_frame(
            image_data,
            exposure_ms,
            gain,
            metadata,
        )

    def start_new_angle_scan(self, scan_document: AngleScanDocument) -> tuple[str, Path]:
        """既存UI/テスト互換のAngle Scan開始API。"""
        session = self.start_angle_scan_session(scan_document)
        return session.scan_id, session.session_dir

    def save_angle_scan_frame(
        self,
        image_data: np.ndarray,
        scan_id: str,
        target_angle_deg: float,
        exposure_ms: float,
        gain: float,
        metadata: dict,
    ) -> Path:
        """既存API互換のAngle Scan保存。角度別保存処理はAngleScanSessionへ委譲する。"""
        if self._current_angle_scan_session is None:
            msg = "角度走査が開始されていません。"
            raise RuntimeError(msg)

        if scan_id != self._current_angle_scan_session.scan_id:
            msg = f"開始中の角度走査IDと一致しません: {scan_id}"
            raise RuntimeError(msg)

        return self._current_angle_scan_session.save_raw_frame(
            image_data,
            target_angle_deg,
            exposure_ms,
            gain,
            metadata,
        )

    @staticmethod
    def format_angle_dir_name(angle_deg: float) -> str:
        return AngleScanSession.format_angle_dir_name(angle_deg)

    @staticmethod
    def format_angle_scan_filename(
        scan_id: str,
        target_angle_deg: float,
        exposure_ms: float,
        gain: float,
    ) -> str:
        return AngleScanSession.format_angle_scan_filename(
            scan_id=scan_id,
            target_angle_deg=target_angle_deg,
            exposure_ms=exposure_ms,
            gain=gain,
        )
