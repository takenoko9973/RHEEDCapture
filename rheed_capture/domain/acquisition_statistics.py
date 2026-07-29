"""取得フレームのレートと転送量を計算するdomainロジック。"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


DEFAULT_SLIDING_WINDOW_SECONDS = 1.0
MIN_SAMPLES_FOR_RATE = 2
_ERR_WINDOW_POSITIVE = "window_seconds must be positive"
_ERR_STARTED_AT = "timestamp must not precede started_at"
_ERR_TIMESTAMP_ORDER = "timestamps must be non-decreasing"
_ERR_PAYLOAD_NON_NEGATIVE = "payload_bytes must be non-negative"
_ERR_PAYLOAD_INTEGER = "payload_bytes must be an integer or None"


@dataclass(frozen=True)
class AcquisitionStatistics:
    """取得統計のスナップショットを表す。"""

    current_fps: float | None
    average_fps: float | None
    frame_count: int
    payload_bytes_per_second: float | None


@dataclass(frozen=True)
class AcquisitionSample:
    """正常取得フレームの到着時刻と転送payloadを保持する。"""

    timestamp: float
    payload_bytes: int | None


class AcquisitionStatisticsMeter:
    """フレーム時刻のスライディング窓から取得統計を計算する。"""

    def __init__(
        self, window_seconds: float = DEFAULT_SLIDING_WINDOW_SECONDS
    ) -> None:
        """指定した秒数のスライディング窓を持つメーターを作成する。"""
        _validate_finite(window_seconds, "window_seconds")
        if window_seconds <= 0:
            raise ValueError(_ERR_WINDOW_POSITIVE)
        self._window_seconds = window_seconds
        self._started_at: float | None = None
        self._samples: deque[tuple[float, int | None]] = deque()
        self._last_frame_timestamp: float | None = None
        self._last_snapshot_timestamp: float | None = None
        self._frame_count = 0

    def reset(self, started_at: float | None = None) -> None:
        """累計とサンプル窓を消去し、必要なら取得開始時刻を設定する。"""
        if started_at is not None:
            _validate_finite(started_at, "started_at")
        self._started_at = started_at
        self._samples.clear()
        self._last_frame_timestamp = started_at
        self._last_snapshot_timestamp = started_at
        self._frame_count = 0

    def record_frame(self, timestamp: float, payload_bytes: int | None) -> None:
        """正常に取得した1フレームを時刻とpayloadサイズ付きで記録する。"""
        _validate_finite(timestamp, "timestamp")
        if self._started_at is not None and timestamp < self._started_at:
            raise ValueError(_ERR_STARTED_AT)
        if (
            self._last_frame_timestamp is not None
            and timestamp < self._last_frame_timestamp
        ):
            raise ValueError(_ERR_TIMESTAMP_ORDER)

        normalized_payload = _validate_payload(payload_bytes)
        self._samples.append((timestamp, normalized_payload))
        self._last_frame_timestamp = timestamp
        window_start = timestamp - self._window_seconds
        # 最新フレームより前の窓に戻ることはないため、保持量を窓長に制限する。
        while self._samples and self._samples[0][0] < window_start:
            self._samples.popleft()
        self._frame_count += 1

    def snapshot(
        self, timestamp: float, include_average: bool = True
    ) -> AcquisitionStatistics:
        """指定時刻時点の現在値と必要な場合の累計平均を返す。"""
        _validate_finite(timestamp, "timestamp")
        if self._started_at is not None and timestamp < self._started_at:
            raise ValueError(_ERR_STARTED_AT)
        if (
            self._last_frame_timestamp is not None
            and timestamp < self._last_frame_timestamp
        ):
            raise ValueError(_ERR_TIMESTAMP_ORDER)
        if (
            self._last_snapshot_timestamp is not None
            and timestamp < self._last_snapshot_timestamp
        ):
            raise ValueError(_ERR_TIMESTAMP_ORDER)

        window_start = timestamp - self._window_seconds
        window_samples = [
            sample for sample in self._samples if sample[0] >= window_start
        ]
        current_fps = _calculate_current_fps(window_samples)
        payload_rate = _calculate_payload_rate(window_samples)

        average_fps: float | None = None
        if include_average and self._started_at is not None:
            elapsed = timestamp - self._started_at
            if self._frame_count > 0 and elapsed > 0:
                average_fps = self._frame_count / elapsed

        statistics = AcquisitionStatistics(
            current_fps=current_fps,
            average_fps=average_fps,
            frame_count=self._frame_count,
            payload_bytes_per_second=payload_rate,
        )
        self._last_snapshot_timestamp = timestamp
        return statistics


def _validate_finite(value: float, name: str) -> None:
    """有限な実数であることを検証する。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        error_message = f"{name} must be a real number"
        raise TypeError(error_message)
    if not math.isfinite(float(value)):
        error_message = f"{name} must be finite"
        raise ValueError(error_message)


def _validate_payload(payload_bytes: int | None) -> int | None:
    """既知payloadの非負性と有限性を検証して内部表現へ変換する。"""
    if payload_bytes is None:
        return None
    if isinstance(payload_bytes, bool) or not isinstance(payload_bytes, int):
        raise TypeError(_ERR_PAYLOAD_INTEGER)
    _validate_finite(payload_bytes, "payload_bytes")
    if payload_bytes < 0:
        raise ValueError(_ERR_PAYLOAD_NON_NEGATIVE)
    return payload_bytes


def _calculate_current_fps(
    samples: Iterable[tuple[float, int | None]],
) -> float | None:
    """窓内の時刻列から現在FPSを算出する。"""
    timestamps = [timestamp for timestamp, _ in samples]
    if len(timestamps) < MIN_SAMPLES_FOR_RATE:
        return None
    elapsed = timestamps[-1] - timestamps[0]
    if elapsed <= 0:
        return None
    return (len(timestamps) - 1) / elapsed


def _calculate_payload_rate(
    samples: Iterable[tuple[float, int | None]],
) -> float | None:
    """窓内payloadの合計を先頭から末尾までの時間で割る。"""
    sample_list = list(samples)
    if len(sample_list) < MIN_SAMPLES_FOR_RATE:
        return None
    payloads = [payload for _, payload in sample_list]
    if any(payload is None for payload in payloads):
        return None
    elapsed = sample_list[-1][0] - sample_list[0][0]
    if elapsed <= 0:
        return None
    known_payloads = [payload for payload in payloads if payload is not None]
    return sum(known_payloads) / elapsed
