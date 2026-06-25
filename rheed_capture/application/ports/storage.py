from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from rheed_capture.application.capture.frame_capturer import CapturedFrame
    from rheed_capture.data_formats.angle_scan_document import AngleScanDocument
    from rheed_capture.data_formats.recording import RecordingFrameRow


class SequenceSession(Protocol):
    """Sequence撮影Use Caseが依存する保存SessionのPort。"""

    dir_name: str

    def save_frame(self, captured_frame: CapturedFrame) -> object:
        """Sequenceの1フレームを保存する。"""
        ...


class AngleScanSession(Protocol):
    """Angle Scan撮影Use Caseが依存する保存SessionのPort。"""

    scan_id: str
    dir_name: str

    def save_frame(self, captured_frame: CapturedFrame, target_angle_deg: float) -> object:
        """Angle Scanの1フレームを目標角度付きで保存する。"""
        ...


class RecordingSession(Protocol):
    """Recording撮影Use Caseが依存する保存SessionのPort。"""

    dir_name: str
    saved_frames: int

    def build_frame_path(self, frame_index: int) -> Path:
        """指定frame indexの保存先Pathを返す。"""
        ...

    def append_saved_frame(
        self,
        row: RecordingFrameRow,
        save_elapsed_ms: float,
    ) -> int:
        """保存完了したフレーム情報を記録し、保存済み枚数を返す。"""
        ...

    def mark_completed(self) -> None:
        """Recordingを正常完了として記録する。"""
        ...

    def mark_cancelled(self) -> None:
        """Recordingをキャンセル終了として記録する。"""
        ...

    def mark_error(self, error_message: str) -> None:
        """Recordingをエラー終了として記録する。"""
        ...


class CaptureStorage(Protocol):
    """撮影Use CaseがSession作成に使うStorage Port。"""

    def start_sequence_session(self) -> SequenceSession:
        """次のSequence保存Sessionを開始する。"""
        ...

    def start_angle_scan_session(self, scan_document: AngleScanDocument) -> AngleScanSession:
        """次のAngle Scan保存Sessionを開始する。"""
        ...
