from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecordingFrameRow:
    """frames.csvへ1行として記録するRecordingフレーム情報。"""

    frame_index: int
    target_elapsed_ms: float
    # Recording開始からsoftware trigger発行直前までのPC monotonic経過時間。
    actual_elapsed_ms: float
    # software trigger発行直前のPC時刻。画像受信完了時刻ではない。
    timestamp: str
    # 同じフレームに付与されたカメラ内部時計の生tickとtick数/秒。
    camera_timestamp_ticks: int
    camera_timestamp_frequency_hz: int
    exposure_ms: float
    gain: int
    filename: str
