from __future__ import annotations

import csv
import json
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Literal
from zoneinfo import ZoneInfo

from rheed_capture.data_formats.storage_naming import (
    RECORDING_TIFF_COMPRESSION,
    RECORDING_TIFF_FILENAME_PATTERN,
)

if TYPE_CHECKING:
    from pathlib import Path

    from rheed_capture.data_formats.recording import RecordingFrameRow

JST = ZoneInfo("Asia/Tokyo")
RecordingStatus = Literal["running", "completed", "cancelled", "error"]


class RecordingSession:
    """1つのRecordingディレクトリ内のJSON/CSV/TIFF名を管理する。"""

    csv_header: ClassVar[list[str]] = [
        "frame_index",
        "target_elapsed_ms",
        "actual_elapsed_ms",
        "timestamp",
        "exposure_ms",
        "gain",
        "save_elapsed_ms",
        "filename",
    ]

    def __init__(
        self,
        session_dir: Path,
        *,
        record_number: int,
        sample_name: str,
        date: str,
        exposure_ms: float,
        gain: int,
        rate_mode: str,
        target_interval_ms: float,
        duration_ms: float | None,
    ) -> None:
        """Recordingのメタ情報を保持し、recording.jsonとframes.csvを初期化する。"""
        self.session_dir = session_dir
        self.record_number = record_number
        self.recording_id = f"rec-{record_number}"
        self.sample_name = sample_name
        self.date = date
        self.exposure_ms = exposure_ms
        self.gain = gain
        self.rate_mode = rate_mode
        self.target_interval_ms = target_interval_ms
        self.duration_ms = duration_ms
        self.created_at = datetime.now(JST).isoformat()
        self._saved_frames = 0
        self._lock = threading.Lock()

        self.recording_json_path = self.session_dir / "recording.json"
        self.frames_csv_path = self.session_dir / "frames.csv"
        self._csv_file = self.frames_csv_path.open("w", encoding="utf-8", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(self.csv_header)
        self._csv_file.flush()
        # 撮影中に中断しても状態が分かるよう、開始時点でrunningを書き出す。
        self._write_recording_document("running")

    @property
    def dir_name(self) -> str:
        """UI表示や完了通知に使うSessionディレクトリ名を返す。"""
        return self.session_dir.name

    @property
    def saved_frames(self) -> int:
        """保存完了済みフレーム数を返す。"""
        with self._lock:
            return self._saved_frames

    def build_frame_path(self, frame_index: int) -> Path:
        """Recordingの命名規則に従ってフレーム保存先を作る。"""
        filename = RECORDING_TIFF_FILENAME_PATTERN.format(
            sample_name=self.sample_name,
            date=self.date,
            record_number=self.record_number,
            frame_index=frame_index,
        )
        return self.session_dir / filename

    def append_saved_frame(self, row: RecordingFrameRow, save_elapsed_ms: float) -> int:
        """保存完了フレームをframes.csvへ追記し、保存枚数を返す。"""
        with self._lock:
            # 保存callbackは別スレッドから呼ばれるため、CSVとカウンタを同じlockで守る。
            self._csv_writer.writerow(
                [
                    row.frame_index,
                    f"{row.target_elapsed_ms:.3f}",
                    f"{row.actual_elapsed_ms:.3f}",
                    row.timestamp,
                    f"{row.exposure_ms:g}",
                    row.gain,
                    f"{save_elapsed_ms:.3f}",
                    row.filename,
                ]
            )
            self._csv_file.flush()
            self._saved_frames += 1
            return self._saved_frames

    def mark_completed(self) -> None:
        """Recordingを正常完了として記録する。"""
        self._finish("completed")

    def mark_cancelled(self) -> None:
        """Recordingをキャンセル終了として記録する。"""
        self._finish("cancelled")

    def mark_error(self, error_message: str) -> None:
        """Recordingをエラー終了として記録する。"""
        self._finish("error", error_message=error_message)

    def _finish(self, status: RecordingStatus, *, error_message: str | None = None) -> None:
        """終了状態を書き出してCSVファイルを閉じる。"""
        self._write_recording_document(status, error_message=error_message)
        self._csv_file.close()

    def _write_recording_document(
        self,
        status: RecordingStatus,
        *,
        error_message: str | None = None,
    ) -> None:
        """recording.jsonを現在の状態で上書きする。"""
        document = self._build_recording_document(status, error_message=error_message)
        with self.recording_json_path.open("w", encoding="utf-8") as f:
            json.dump(document, f, ensure_ascii=False, indent=2)

    def _build_recording_document(
        self,
        status: RecordingStatus,
        *,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """recording.jsonへ保存するdictを組み立てる。"""
        document: dict[str, Any] = {
            "schema_version": 1,
            "recording_id": self.recording_id,
            "status": status,
            "created_at": self.created_at,
            "sample_name": self.sample_name,
            "condition": {
                "exposure_ms": self.exposure_ms,
                "gain": self.gain,
            },
            "timing": {
                "rate_mode": self.rate_mode,
                "target_interval_ms": self.target_interval_ms,
                "duration_ms": self.duration_ms,
            },
            "storage": {
                "folder_name": self.session_dir.name,
                "filename_pattern": RECORDING_TIFF_FILENAME_PATTERN,
                "tiff_compression": RECORDING_TIFF_COMPRESSION,
            },
            "result": None,
        }
        if status != "running":
            document["finished_at"] = datetime.now(JST).isoformat()
            document["result"] = {"saved_frames": self.saved_frames}
        if error_message is not None:
            document["error_message"] = error_message

        return document
