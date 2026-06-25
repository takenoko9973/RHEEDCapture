from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecordingFrameRow:
    """frames.csvへ1行として記録するRecordingフレーム情報。"""

    frame_index: int
    target_elapsed_ms: float
    actual_elapsed_ms: float
    timestamp: str
    exposure_ms: float
    gain: int
    filename: str
