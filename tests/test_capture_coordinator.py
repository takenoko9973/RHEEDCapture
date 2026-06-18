from __future__ import annotations

import pytest

from rheed_capture.presentation.qt.capture_coordinator import (
    CaptureCoordinator,
    CaptureCoordinatorHooks,
)


class _HookRecorder:
    """Coordinatorから呼ばれるUI/Preview操作を順序つきで記録する。"""

    def __init__(self) -> None:
        self.events: list[str] = []

    def hooks(self) -> CaptureCoordinatorHooks:
        """テスト用の全Hookを生成する。"""
        return CaptureCoordinatorHooks(
            set_sequence_capturing=lambda value: self.events.append(f"seq-capturing:{value}"),
            set_angle_scan_capturing=lambda value: self.events.append(
                f"angle-capturing:{value}"
            ),
            set_sequence_enabled=lambda value: self.events.append(f"seq-enabled:{value}"),
            set_angle_scan_enabled=lambda value: self.events.append(f"angle-enabled:{value}"),
            set_motor_settings_enabled=lambda value: self.events.append(f"motor-enabled:{value}"),
            set_preview_controls_enabled=lambda value: self.events.append(
                f"preview-controls:{value}"
            ),
            stop_sequence_preview_timer=lambda: self.events.append("timer-stop"),
            start_sequence_preview_timer=lambda: self.events.append("timer-start"),
            pause_preview=lambda: self.events.append("preview-pause"),
            resume_preview=lambda: self.events.append("preview-resume"),
            refresh_storage_display=lambda: self.events.append("storage-refresh"),
        )


def test_begin_sequence_pauses_preview_after_entering_capture_state() -> None:
    recorder = _HookRecorder()
    coordinator = CaptureCoordinator(recorder.hooks())

    coordinator.begin_sequence(lambda: recorder.events.append("arm-start"))

    assert coordinator.active_mode == "sequence"
    assert recorder.events[:8] == [
        "seq-capturing:True",
        "angle-capturing:False",
        "seq-enabled:True",
        "angle-enabled:False",
        "motor-enabled:False",
        "preview-controls:False",
        "timer-stop",
        "arm-start",
    ]
    assert recorder.events[8] == "preview-pause"


def test_leave_returns_preview_and_ui_to_idle_state() -> None:
    recorder = _HookRecorder()
    coordinator = CaptureCoordinator(recorder.hooks())
    coordinator.begin_angle_scan(lambda: recorder.events.append("start-angle"))

    recorder.events.clear()
    coordinator.leave()

    assert coordinator.active_mode is None
    assert recorder.events == [
        "seq-capturing:False",
        "angle-capturing:False",
        "seq-enabled:True",
        "angle-enabled:True",
        "motor-enabled:True",
        "preview-controls:True",
        "preview-resume",
        "storage-refresh",
        "timer-start",
    ]


def test_begin_angle_scan_rolls_back_state_when_start_fails() -> None:
    recorder = _HookRecorder()
    coordinator = CaptureCoordinator(recorder.hooks())

    def fail_to_start() -> None:
        msg = "invalid angle scan settings"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="invalid angle scan settings"):
        coordinator.begin_angle_scan(fail_to_start)

    assert coordinator.active_mode is None
    assert "preview-resume" in recorder.events
