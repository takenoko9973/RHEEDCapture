from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RecordingFrameRow:
    """frames.csvへ1行として記録するRecordingフレーム情報。"""

    frame_index: int
    target_elapsed_ms: float
    # Recording開始からsoftware trigger発行直前までのPC monotonic経過時間。
    actual_elapsed_ms: float
    # software trigger発行直前のPC時刻。画像受信完了時刻ではない。
    timestamp: str
    # sourceにより、実機のcamera tickかシミュレーション時刻かを区別する。
    camera_timestamp_ticks: int
    camera_timestamp_frequency_hz: int
    camera_timestamp_source: Literal["camera", "host", "simulation"]
    exposure_ms: float
    gain: int
    camera_exposure_ms: float
    camera_gain: int
    filename: str
