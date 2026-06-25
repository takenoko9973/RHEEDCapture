from __future__ import annotations

import pytest

from rheed_capture.presentation.qt.capture_coordinator import (
    CaptureCoordinator,
    CaptureCoordinatorHooks,
)


class _HookRecorder:
    """Coordinatorから呼ばれるUI/Preview操作を順序つきで記録する。"""

    def __init__(self) -> None:
        """記録用イベントリストを初期化する。"""
        self.events: list[str] = []

    def hooks(self) -> CaptureCoordinatorHooks:
        """テスト用の全Hookを生成する。"""
        return CaptureCoordinatorHooks(
            set_sequence_capturing=lambda value: self.events.append(f"seq-capturing:{value}"),
            set_angle_scan_capturing=lambda value: self.events.append(
                f"angle-capturing:{value}"
            ),
            set_recording_capturing=lambda value: self.events.append(
                f"recording-capturing:{value}"
            ),
            set_sequence_enabled=lambda value: self.events.append(f"seq-enabled:{value}"),
            set_angle_scan_enabled=lambda value: self.events.append(f"angle-enabled:{value}"),
            set_recording_enabled=lambda value: self.events.append(
                f"recording-enabled:{value}"
            ),
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
    """Sequence開始時にUI状態を切り替えてからPreview停止を要求する。"""
    recorder = _HookRecorder()
    coordinator = CaptureCoordinator(recorder.hooks())

    coordinator.begin_sequence(lambda: recorder.events.append("arm-start"))

    assert coordinator.active_mode == "sequence"
    assert recorder.events[:10] == [
        "seq-capturing:True",
        "angle-capturing:False",
        "recording-capturing:False",
        "seq-enabled:True",
        "angle-enabled:False",
        "recording-enabled:False",
        "motor-enabled:False",
        "preview-controls:False",
        "timer-stop",
        "arm-start",
    ]
    assert recorder.events[10] == "preview-pause"


def test_begin_recording_pauses_preview_after_entering_capture_state() -> None:
    """Recording開始時にUI状態を切り替えてからPreview停止を要求する。"""
    recorder = _HookRecorder()
    coordinator = CaptureCoordinator(recorder.hooks())

    coordinator.begin_recording(lambda: recorder.events.append("arm-recording"))

    assert coordinator.active_mode == "recording"
    assert recorder.events[:10] == [
        "seq-capturing:False",
        "angle-capturing:False",
        "recording-capturing:True",
        "seq-enabled:False",
        "angle-enabled:False",
        "recording-enabled:True",
        "motor-enabled:False",
        "preview-controls:False",
        "timer-stop",
        "arm-recording",
    ]
    assert recorder.events[10] == "preview-pause"


def test_leave_returns_preview_and_ui_to_idle_state() -> None:
    """撮影終了時にPreviewとUIが通常状態へ戻ることを確認する。"""
    recorder = _HookRecorder()
    coordinator = CaptureCoordinator(recorder.hooks())
    coordinator.begin_angle_scan(lambda: recorder.events.append("start-angle"))

    recorder.events.clear()
    coordinator.leave()

    assert coordinator.active_mode is None
    assert recorder.events == [
        "seq-capturing:False",
        "angle-capturing:False",
        "recording-capturing:False",
        "seq-enabled:True",
        "angle-enabled:True",
        "recording-enabled:True",
        "motor-enabled:True",
        "preview-controls:True",
        "preview-resume",
        "storage-refresh",
        "timer-start",
    ]


def test_begin_angle_scan_rolls_back_state_when_start_fails() -> None:
    """Angle Scan開始失敗時にCoordinator状態を戻すことを確認する。"""
    recorder = _HookRecorder()
    coordinator = CaptureCoordinator(recorder.hooks())

    def fail_to_start() -> None:
        """Angle Scan開始失敗を発生させる。"""
        msg = "invalid angle scan settings"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="invalid angle scan settings"):
        coordinator.begin_angle_scan(fail_to_start)

    assert coordinator.active_mode is None
    assert "preview-resume" in recorder.events
