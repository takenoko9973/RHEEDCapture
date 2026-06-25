from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

CaptureMode = Literal["sequence", "angle_scan", "recording"]


@dataclass(frozen=True)
class CaptureCoordinatorHooks:
    """CaptureCoordinatorがMainWindowへ依存せずUI状態を変更するための操作群。"""

    set_sequence_capturing: Callable[[bool], None]
    set_angle_scan_capturing: Callable[[bool], None]
    set_recording_capturing: Callable[[bool], None]
    set_sequence_enabled: Callable[[bool], None]
    set_angle_scan_enabled: Callable[[bool], None]
    set_recording_enabled: Callable[[bool], None]
    set_motor_settings_enabled: Callable[[bool], None]
    set_preview_controls_enabled: Callable[[bool], None]
    stop_sequence_preview_timer: Callable[[], None]
    start_sequence_preview_timer: Callable[[], None]
    pause_preview: Callable[[], None]
    resume_preview: Callable[[], None]
    refresh_storage_display: Callable[[], None]


@dataclass(init=False)
class CaptureCoordinator:
    """撮影モード間の排他制御とプレビュー所有権の受け渡しをまとめる。"""

    def __init__(self, hooks: CaptureCoordinatorHooks | None = None) -> None:
        """必要なら初期hooksを受け取り、未撮影状態で初期化する。"""
        self.active_mode: CaptureMode | None = None
        self._hooks = hooks

    def bind(self, hooks: CaptureCoordinatorHooks) -> None:
        """MainWindow構築後に、実際のUI操作を差し込む。"""
        self._hooks = hooks

    def begin_sequence(self, arm_start_after_preview_pause: Callable[[], None]) -> None:
        """PreviewWorker停止完了後にSequenceを開始する流れを開始する。"""
        self.enter("sequence")

        try:
            arm_start_after_preview_pause()
            self._require_hooks().pause_preview()
        except Exception:
            self.leave()
            raise

    def begin_angle_scan(self, start_angle_scan: Callable[[], None]) -> None:
        """Angle Scanを開始する。プレビュー停止待ちは撮影Hook側で行う。"""
        self.enter("angle_scan")

        try:
            start_angle_scan()
        except Exception:
            self.leave()
            raise

    def begin_recording(self, arm_start_after_preview_pause: Callable[[], None]) -> None:
        """PreviewWorker停止完了後にRecordingを開始する流れを開始する。"""
        self.enter("recording")

        try:
            arm_start_after_preview_pause()
            self._require_hooks().pause_preview()
        except Exception:
            self.leave()
            raise

    def enter(self, mode: CaptureMode) -> None:
        """指定モードを唯一の撮影所有者として登録し、共通UI状態へ切り替える。"""
        if self.active_mode is not None:
            msg = f"既に撮影中です: {self.active_mode}"
            raise RuntimeError(msg)

        self.active_mode = mode
        self._apply_enter_state(mode)

    def leave(self) -> None:
        """撮影所有権を解除し、通常プレビューへ戻す。"""
        self.active_mode = None
        self._apply_leave_state()

    def is_capturing(self) -> bool:
        """撮影モードがカメラ所有権を持っている間はTrueを返す。"""
        return self.active_mode is not None

    def _apply_enter_state(self, mode: CaptureMode) -> None:
        """撮影開始時に各Panelと保存先プレビュー更新を共通状態へ切り替える。"""
        hooks = self._require_hooks()

        hooks.set_sequence_capturing(mode == "sequence")
        hooks.set_angle_scan_capturing(mode == "angle_scan")
        hooks.set_recording_capturing(mode == "recording")
        hooks.set_sequence_enabled(mode == "sequence")
        hooks.set_angle_scan_enabled(mode == "angle_scan")
        hooks.set_recording_enabled(mode == "recording")
        hooks.set_motor_settings_enabled(False)
        hooks.set_preview_controls_enabled(False)
        hooks.stop_sequence_preview_timer()

    def _apply_leave_state(self) -> None:
        """撮影終了時にUIとPreviewWorkerを通常状態へ戻す。"""
        hooks = self._require_hooks()

        hooks.set_sequence_capturing(False)
        hooks.set_angle_scan_capturing(False)
        hooks.set_recording_capturing(False)
        hooks.set_sequence_enabled(True)
        hooks.set_angle_scan_enabled(True)
        hooks.set_recording_enabled(True)
        hooks.set_motor_settings_enabled(True)
        hooks.set_preview_controls_enabled(True)
        hooks.resume_preview()
        hooks.refresh_storage_display()
        hooks.start_sequence_preview_timer()

    def _require_hooks(self) -> CaptureCoordinatorHooks:
        """UI操作が未接続のまま利用された場合は明示的に失敗させる。"""
        if self._hooks is None:
            msg = "CaptureCoordinator hooks are not bound."
            raise RuntimeError(msg)

        return self._hooks
