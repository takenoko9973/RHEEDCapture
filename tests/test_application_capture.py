from __future__ import annotations

import numpy as np
import pytest

from rheed_capture.application.capture.angle_scan import (
    AngleScanCapture,
    AngleScanHooks,
    AngleScanSettings,
)
from rheed_capture.application.capture.cancellation import CancellationToken, CaptureCancelled
from rheed_capture.application.capture.frame_capturer import CapturedFrame
from rheed_capture.application.capture.sequence import SequenceCapture
from rheed_capture.domain.capture_condition import CaptureCondition  # noqa: TC001
from rheed_capture.infrastructure.motor.defaults import DEFAULT_POSITION_UNITS_PER_DEG


class _FakeFrameCapturer:
    def __init__(self) -> None:
        self.conditions: list[CaptureCondition] = []

    def capture(self, condition: CaptureCondition) -> CapturedFrame:
        self.conditions.append(condition)
        return CapturedFrame(
            image=np.ones((2, 2), dtype=np.uint16),
            condition=condition,
            timestamp="2026-06-17T00:00:00+09:00",
        )


class _SequenceSession:
    dir_name = "image_001"

    def __init__(self) -> None:
        self.saved: list[CapturedFrame] = []

    def save_frame(self, captured_frame: CapturedFrame) -> None:
        self.saved.append(captured_frame)


class _AngleScanSession:
    scan_id = "as001"
    dir_name = "angle_scan_001"

    def __init__(self) -> None:
        self.saved: list[tuple[CapturedFrame, float]] = []

    def save_frame(self, captured_frame: CapturedFrame, target_angle_deg: float) -> None:
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
    progress: list[tuple[int, int]] = []

    capture = SequenceCapture(frame_capturer, session, [100.0, 10.0], [2, 0])
    capture.run(
        CancellationToken(),
        on_progress=lambda current, total: progress.append((current, total)),
    )

    assert [(c.exposure_ms, c.gain) for c in frame_capturer.conditions] == [
        (10.0, 0),
        (10.0, 2),
        (100.0, 0),
        (100.0, 2),
    ]
    assert len(session.saved) == 4
    assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_sequence_capture_stops_when_cancelled() -> None:
    frame_capturer = _FakeFrameCapturer()
    session = _SequenceSession()
    token = CancellationToken()
    token.cancel()
    capture = SequenceCapture(frame_capturer, session, [10.0], [0])

    with pytest.raises(CaptureCancelled):
        capture.run(token)

    assert session.saved == []


def test_angle_scan_capture_moves_by_plan_saves_angles_and_returns_to_start() -> None:
    frame_capturer = _FakeFrameCapturer()
    session = _AngleScanSession()
    motor = _Motor()
    progress: list[tuple[int, int, float]] = []

    capture = AngleScanCapture(
        frame_capturer,
        session,
        motor,
        [10.0],
        [0],
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
        [10.0],
        [0],
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
        [10.0],
        [0],
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
