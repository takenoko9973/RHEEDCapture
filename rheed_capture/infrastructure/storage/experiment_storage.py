from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from rheed_capture.data_formats.storage_naming import (
    ANGLE_SCAN_DIR_PATTERN,
    RECORDING_DIR_PATTERN,
    SEQUENCE_DIR_PATTERN,
)
from rheed_capture.infrastructure.storage.sessions.angle_scan import AngleScanSession
from rheed_capture.infrastructure.storage.sessions.recording import RecordingSession
from rheed_capture.infrastructure.storage.sessions.sequence import SequenceSession

if TYPE_CHECKING:
    from rheed_capture.data_formats.angle_scan_document import AngleScanDocument

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")


class ExperimentStorage:
    """実験日ディレクトリ、branch、撮影Session番号を管理するStorage入口。"""

    root_dir: Path

    _branch_number: int
    _sequence_counter: int
    _angle_scan_counter: int
    _recording_counter: int

    def __init__(self, root_dir: str | Path) -> None:
        """保存ルートを受け取り、日付branchと撮影カウンタを初期化する。"""
        self.date_str = datetime.now(JST).strftime("%y%m%d")
        self._branch_number = 1
        self._sequence_counter = 0
        self._angle_scan_counter = 0
        self._recording_counter = 0
        self._current_sequence_session: SequenceSession | None = None
        self._current_angle_scan_session: AngleScanSession | None = None
        self._current_recording_session: RecordingSession | None = None

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
        """現在のSequence番号に対応する表示用ディレクトリを返す。"""
        return self.get_current_experiment_dir() / SEQUENCE_DIR_PATTERN.format(
            number=self._sequence_counter
        )

    def get_current_angle_scan_dir(self) -> Path:
        """現在のAngle Scan番号に対応する表示用ディレクトリを返す。"""
        return self.get_current_experiment_dir() / ANGLE_SCAN_DIR_PATTERN.format(
            number=self._angle_scan_counter
        )

    def get_current_recording_dir(self) -> Path:
        """現在のRecording番号に対応する表示用ディレクトリを返す。"""
        return self.get_current_experiment_dir() / RECORDING_DIR_PATTERN.format(
            number=self._recording_counter
        )

    def refresh_sequence_counter_from_disk(self) -> None:
        """ディスク上の `image_NNN` 最大値をSequenceカウンタへ反映する。"""
        self._sequence_counter = self._search_max_sequence()

    def refresh_angle_scan_counter_from_disk(self) -> None:
        """ディスク上の `angle_scan_NNN` 最大値をAngle Scanカウンタへ反映する。"""
        self._angle_scan_counter = self._search_max_angle_scan()

    def refresh_recording_counter_from_disk(self) -> None:
        """ディスク上の `record-N` 最大値をRecordingカウンタへ反映する。"""
        self._recording_counter = self._search_max_recording()

    def refresh_capture_counters_from_disk(self) -> None:
        """撮影種別ごとの次番号をまとめて再同期する。"""
        self.refresh_sequence_counter_from_disk()
        self.refresh_angle_scan_counter_from_disk()
        self.refresh_recording_counter_from_disk()

    def get_next_sequence_dir_name(self) -> str:
        """次に作成されるSequenceディレクトリ名をUI表示用に返す。"""
        return SEQUENCE_DIR_PATTERN.format(number=self.get_next_sequence_number())

    def get_next_angle_scan_dir_name(self) -> str:
        """次に作成されるAngle Scanディレクトリ名をUI表示用に返す。"""
        return ANGLE_SCAN_DIR_PATTERN.format(number=self.get_next_angle_scan_number())

    def get_next_recording_dir_name(self) -> str:
        """次に作成されるRecordingディレクトリ名をUI表示用に返す。"""
        return RECORDING_DIR_PATTERN.format(number=self.get_next_recording_number())

    def get_next_sequence_number(self) -> int:
        """次に確定するSequence番号を返す。"""
        return self._sequence_counter + 1

    def get_next_angle_scan_number(self) -> int:
        """次に確定するAngle Scan番号を返す。"""
        return self._angle_scan_counter + 1

    def get_next_recording_number(self) -> int:
        """次に確定するRecording番号を返す。"""
        return self._recording_counter + 1

    def _search_max_branch(self) -> int:
        """保存ルート直下から現在日付の最大branch番号を探す。"""
        pattern = re.compile(rf"^{re.escape(self.date_str)}(?:-(\d+))?$")
        suffixes = [
            int(match.group(1) or 1)
            for path in Path(self.root_dir).iterdir()
            if path.is_dir() and (match := pattern.match(path.name))
        ]
        return max(suffixes, default=1)

    def _search_max_sequence(self) -> int:
        """現在の実験ディレクトリから最大Sequence番号を探す。"""
        return self._search_max_number_in_current_experiment(r"^image_(\d{3})$")

    def _search_max_angle_scan(self) -> int:
        """現在の実験ディレクトリから最大Angle Scan番号を探す。"""
        return self._search_max_number_in_current_experiment(r"^angle_scan_(\d{3})$")

    def _search_max_recording(self) -> int:
        """現在の実験ディレクトリから最大Recording番号を探す。"""
        return self._search_max_number_in_current_experiment(r"^record-(\d+)$")

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
        self._recording_counter = 0
        self._current_sequence_session = None
        self._current_angle_scan_session = None
        self._current_recording_session = None

    def _ensure_experiment_dir(self) -> Path:
        """Session作成前にルートと現在の実験ディレクトリを用意する。"""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        exp_dir = self.get_current_experiment_dir()
        exp_dir.mkdir(parents=True, exist_ok=True)
        return exp_dir

    def start_sequence_session(self) -> SequenceSession:
        """次の `image_NNN` を確定し、SequenceSessionを生成する。"""
        # 撮影開始直前にディスクを再走査し、外部作成済み番号との衝突を避ける。
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
        # scan_idとディレクトリ番号は同じカウンタから確定して対応を保つ。
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

    def start_recording_session(
        self,
        *,
        sample_name: str,
        exposure_ms: float,
        gain: int,
        rate_mode: str,
        target_interval_ms: float,
        duration_ms: float | None,
    ) -> RecordingSession:
        """次の `record-N` を確定し、RecordingSessionを生成する。"""
        # RecordingはSequence/Angle Scanと独立した番号系列で保存する。
        self.refresh_capture_counters_from_disk()
        self._ensure_experiment_dir()

        self._recording_counter += 1
        recording_dir = self.get_current_recording_dir()
        recording_dir.mkdir(parents=True, exist_ok=False)

        self._current_recording_session = RecordingSession(
            recording_dir,
            record_number=self._recording_counter,
            sample_name=sample_name,
            date=self.date_str,
            exposure_ms=exposure_ms,
            gain=gain,
            rate_mode=rate_mode,
            target_interval_ms=target_interval_ms,
            duration_ms=duration_ms,
        )
        logger.info("新規録画作成: %s", recording_dir)
        return self._current_recording_session

    @staticmethod
    def format_angle_dir_name(angle_deg: float) -> str:
        """Angle Scanの角度別サブディレクトリ名を生成する。"""
        return AngleScanSession.format_angle_dir_name(angle_deg)

    @staticmethod
    def format_angle_scan_filename(
        scan_id: str,
        target_angle_deg: float,
        exposure_ms: float,
        gain: float,
    ) -> str:
        """Angle ScanのTIFFファイル名を生成する。"""
        return AngleScanSession.format_angle_scan_filename(
            scan_id=scan_id,
            target_angle_deg=target_angle_deg,
            exposure_ms=exposure_ms,
            gain=gain,
        )
