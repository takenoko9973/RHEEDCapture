from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import TYPE_CHECKING

from rheed_capture.application.capture.frame_capturer import CapturedFrame, FrameCapture
from rheed_capture.domain.capture_condition import CaptureCondition

if TYPE_CHECKING:
    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.application.ports.storage import SequenceSession
ProgressCallback = Callable[[int, int, CaptureCondition], None]
FrameCallback = Callable[[CapturedFrame], None]


class SequenceCapture:
    """Sequence固有の撮影順序だけを担当するQt非依存の実行クラス。"""

    def __init__(
        self,
        frame_capturer: FrameCapture,
        session: SequenceSession,
        exposure_list: list[float],
        gain_list: list[int],
    ) -> None:
        self.frame_capturer = frame_capturer
        self.session = session
        self.conditions = [
            CaptureCondition(exposure_ms=exposure_ms, gain=gain)
            for exposure_ms, gain in itertools.product(sorted(exposure_list), sorted(gain_list))
        ]

    @property
    def total_shots(self) -> int:
        """現在の条件リストから算出した総撮影枚数を返す。"""
        return len(self.conditions)

    def run(
        self,
        cancellation_token: CancellationToken,
        *,
        on_progress: ProgressCallback | None = None,
        on_frame_captured: FrameCallback | None = None,
    ) -> None:
        """全撮影条件を順に撮影・保存し、必要に応じて進捗とRawフレームを通知する。"""
        for shot_count, condition in enumerate(self.conditions, 1):
            cancellation_token.raise_if_cancelled()

            if on_progress is not None:
                on_progress(shot_count, self.total_shots, condition)

            captured_frame = self.frame_capturer.capture(condition)
            self.session.save_frame(captured_frame)

            if on_frame_captured is not None:
                on_frame_captured(captured_frame)
