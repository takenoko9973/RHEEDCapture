from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import pytest

from rheed_capture.application.capture.angle_scan import (
    AngleScanCapture,
    AngleScanHooks,
    AngleScanSettings,
)
from rheed_capture.application.capture.cancellation import CancellationToken, CaptureCancelled
from rheed_capture.application.capture.frame_capturer import CapturedFrame, CaptureTiming
from rheed_capture.application.capture.sequence import SequenceCapture
from rheed_capture.application.ports.camera import FrameReadback
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.infrastructure.motor.defaults import DEFAULT_POSITION_UNITS_PER_DEG

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FakeFrameCapturer:
    def __init__(self) -> None:
        self.conditions: list[CaptureCondition] = []
        self.group_requests: list[tuple[int, float]] = []

    def capture(self, condition: CaptureCondition) -> CapturedFrame:
        self.conditions.append(condition)
        return CapturedFrame(
            image=np.ones((2, 2), dtype=np.uint16),
            condition=condition,
            readback=FrameReadback(
                exposure_ms=condition.exposure_ms,
                gain=condition.gain,
                camera_timestamp_ticks=100,
                camera_timestamp_frequency_hz=125_000_000,
                source="camera",
            ),
            timing=CaptureTiming(
                trigger_issued_at=datetime.fromisoformat("2026-06-17T00:00:00+09:00"),
                trigger_issued_monotonic_sec=1.0,
            ),
        )

    def capture_group(
        self,
        condition: CaptureCondition,
        *,
        frame_count: int,
        hardware_wait_timeout_sec: float,
        cancellation_token: CancellationToken,
    ) -> Iterator[CapturedFrame]:
        """蓄積撮影用に同じ条件のRawを逐次返す。"""
        del cancellation_token
        self.group_requests.append((frame_count, hardware_wait_timeout_sec))
        for _ in range(frame_count):
            yield self.capture(condition)


class _SequenceSession:
    dir_name = "image_001"

    def __init__(self) -> None:
        self.saved: list[CapturedFrame] = []

    def save_frame(self, captured_frame: CapturedFrame) -> None:
        self.saved.append(captured_frame)

    def save_accumulation_frame(
        self,
        captured_frame: CapturedFrame,
        *,
        group_index: int,
        raw_index: int,
    ) -> None:
        """蓄積Rawの保存順序を記録する。"""
        del group_index, raw_index
        self.saved.append(captured_frame)


class _AngleScanSession:
    scan_id = "as001"
    dir_name = "angle_scan_001"

    def __init__(self) -> None:
        self.saved: list[tuple[CapturedFrame, float]] = []

    def save_frame(self, captured_frame: CapturedFrame, target_angle_deg: float) -> None:
        self.saved.append((captured_frame, target_angle_deg))

    def save_accumulation_frame(
        self,
        captured_frame: CapturedFrame,
        target_angle_deg: float,
        *,
        condition_index: int,
        raw_index: int,
    ) -> None:
        """蓄積Rawの保存順序を記録する。"""
        del condition_index, raw_index
        self.saved.append((captured_frame, target_angle_deg))


class _Motor:
    def __init__(self) -> None:
        self.moves: list[tuple[int, float]] = []

    def move_relative_units(
        self,
        position_units: int,
        motor_speed_rpm: float = 4.0,
        *,
        timeout: float = 10.0,  # noqa: ARG002
    ) -> None:
        self.moves.append((position_units, motor_speed_rpm))


def test_sequence_capture_sorts_conditions_saves_all_and_reports_progress() -> None:
    frame_capturer = _FakeFrameCapturer()
    session = _SequenceSession()
    progress: list[tuple[int, int, float, int]] = []

    capture = SequenceCapture(
        frame_capturer,
        session,
        [
            CaptureCondition(exposure_ms=10.0, gain=0),
            CaptureCondition(exposure_ms=10.0, gain=2),
            CaptureCondition(exposure_ms=100.0, gain=0),
            CaptureCondition(exposure_ms=100.0, gain=2),
        ],
    )
    capture.run(
        CancellationToken(),
        on_progress=lambda current, total, condition: progress.append(
            (current, total, condition.exposure_ms, condition.gain)
        ),
    )

    assert [(c.exposure_ms, c.gain) for c in frame_capturer.conditions] == [
        (10.0, 0),
        (10.0, 2),
        (100.0, 0),
        (100.0, 2),
    ]
    assert len(session.saved) == 4
    assert frame_capturer.group_requests == [(1, 0.0)] * 4
    assert progress == [
        (1, 4, 10.0, 0),
        (2, 4, 10.0, 2),
        (3, 4, 100.0, 0),
        (4, 4, 100.0, 2),
    ]


def test_sequence_capture_stops_when_cancelled() -> None:
    frame_capturer = _FakeFrameCapturer()
    session = _SequenceSession()
    token = CancellationToken()
    token.cancel()
    capture = SequenceCapture(
        frame_capturer,
        session,
        [CaptureCondition(exposure_ms=10.0, gain=0)],
    )

    with pytest.raises(CaptureCancelled):
        capture.run(token)

    assert session.saved == []


def test_sequence_capture_saves_each_raw_and_notifies_clipped_sum() -> None:
    """蓄積時はRawを保存し、完了時だけuint16の合計画像を通知する。"""
    class _AccumulatingFrameCapturer(_FakeFrameCapturer):
        def capture_group(
            self,
            condition: CaptureCondition,
            *,
            frame_count: int,
            hardware_wait_timeout_sec: float,
            cancellation_token: CancellationToken,
        ) -> Iterator[CapturedFrame]:
            del frame_count, hardware_wait_timeout_sec, cancellation_token
            self.conditions.append(condition)
            for value in (40_000, 40_000):
                yield CapturedFrame(
                    image=np.full((2, 2), value, dtype=np.uint16),
                    condition=condition,
                    readback=FrameReadback(
                        exposure_ms=condition.exposure_ms,
                        gain=condition.gain,
                        camera_timestamp_ticks=value,
                        camera_timestamp_frequency_hz=125_000_000,
                        source="camera",
                    ),
                    timing=CaptureTiming(
                        trigger_issued_at=datetime.fromisoformat("2026-06-17T00:00:00+09:00"),
                        trigger_issued_monotonic_sec=1.0,
                    ),
                )

    session = _SequenceSession()
    notified: list[CapturedFrame] = []
    capture = SequenceCapture(
        _AccumulatingFrameCapturer(),
        session,
        [CaptureCondition(exposure_ms=10.0, gain=0)],
        accumulation_frames=2,
    )

    capture.run(CancellationToken(), on_frame_captured=notified.append)

    assert len(session.saved) == 2
    assert len(notified) == 1
    assert np.array_equal(notified[0].image, np.full((2, 2), 65_535, dtype=np.uint16))


def test_angle_scan_does_not_move_to_next_angle_until_group_completes() -> None:
    """途中Rawのtimeout後は次の角度へ移動しない。"""
    class _FailingFrameCapturer(_FakeFrameCapturer):
        def capture_group(
            self,
            condition: CaptureCondition,
            *,
            frame_count: int,
            hardware_wait_timeout_sec: float,
            cancellation_token: CancellationToken,
        ) -> Iterator[CapturedFrame]:
            del frame_count, hardware_wait_timeout_sec, cancellation_token
            yield self.capture(condition)
            msg = "Hardware trigger待機が設定時間を超過しました。"
            raise TimeoutError(msg)

    motor = _Motor()
    session = _AngleScanSession()
    capture = AngleScanCapture(
        _FailingFrameCapturer(),
        session,
        motor,
        [CaptureCondition(exposure_ms=10.0, gain=0)],
        AngleScanSettings(
            range_deg=0.5,
            interval_deg=0.5,
            direction="positive",
            settling_time_ms=0,
            return_to_start_after_scan=False,
            position_units_per_deg=DEFAULT_POSITION_UNITS_PER_DEG,
        ),
        accumulation_frames=2,
        trigger_wait_timeout_sec=1,
    )

    with pytest.raises(TimeoutError, match="設定時間"):
        capture.run(CancellationToken())

    assert len(session.saved) == 1
    assert motor.moves == []


def test_angle_scan_capture_moves_by_plan_saves_angles_and_returns_to_start() -> None:
    frame_capturer = _FakeFrameCapturer()
    session = _AngleScanSession()
    motor = _Motor()
    progress: list[tuple[int, int, float]] = []

    capture = AngleScanCapture(
        frame_capturer,
        session,
        motor,
        [CaptureCondition(exposure_ms=10.0, gain=0)],
        AngleScanSettings(
            range_deg=1.0,
            interval_deg=0.5,
            direction="positive",
            settling_time_ms=0,
            return_to_start_after_scan=True,
            position_units_per_deg=DEFAULT_POSITION_UNITS_PER_DEG,
            motor_speed_rpm=4.0,
        ),
    )
    capture.run(
        CancellationToken(),
        hooks=AngleScanHooks(
            on_progress=lambda current, total, angle: progress.append(
                (current, total, angle)
            )
        ),
    )

    assert [angle for _frame, angle in session.saved] == [0.0, 0.5, 1.0]
    assert [move[0] for move in motor.moves] == [16, 15, -31]
    assert frame_capturer.group_requests == [(1, 0.0)] * 3
    assert progress == [(1, 3, 0.0), (2, 3, 0.5), (3, 3, 1.0)]


def test_angle_scan_capture_waits_before_preview_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class TrackingFrameCapturer(_FakeFrameCapturer):
        def capture(self, condition: CaptureCondition) -> CapturedFrame:
            events.append("capture")
            return super().capture(condition)

    monkeypatch.setattr(
        "rheed_capture.application.capture.angle_scan.time.sleep",
        lambda _seconds: events.append("settle"),
    )
    capture = AngleScanCapture(
        TrackingFrameCapturer(),
        _AngleScanSession(),
        _Motor(),
        [CaptureCondition(exposure_ms=10.0, gain=0)],
        AngleScanSettings(
            range_deg=0.5,
            interval_deg=0.5,
            direction="positive",
            settling_time_ms=100,
            return_to_start_after_scan=False,
            position_units_per_deg=DEFAULT_POSITION_UNITS_PER_DEG,
        ),
    )

    capture.run(
        CancellationToken(),
        hooks=AngleScanHooks(before_capture_batch=lambda: events.append("pause")),
    )

    assert events[:3] == ["settle", "pause", "capture"]


def test_angle_scan_capture_does_not_capture_internal_zero_on_both_scan() -> None:
    frame_capturer = _FakeFrameCapturer()
    session = _AngleScanSession()

    capture = AngleScanCapture(
        frame_capturer,
        session,
        _Motor(),
        [CaptureCondition(exposure_ms=10.0, gain=0)],
        AngleScanSettings(
            range_deg=0.5,
            interval_deg=0.5,
            direction="both",
            settling_time_ms=0,
            return_to_start_after_scan=False,
            position_units_per_deg=DEFAULT_POSITION_UNITS_PER_DEG,
        ),
    )
    capture.run(CancellationToken())

    assert [angle for _frame, angle in session.saved] == [0.0, 0.5, -0.5]
