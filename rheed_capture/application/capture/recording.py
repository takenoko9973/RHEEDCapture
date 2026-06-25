from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from rheed_capture.application.capture.frame_capturer import (
    CaptureConditionApplier,
    FrameGrabber,
    GrabbedFrame,
)
from rheed_capture.application.capture.save_worker import SaveRequest, TiffSaveWorker
from rheed_capture.data_formats.recording import RecordingFrameRow
from rheed_capture.data_formats.storage_naming import (
    RECORDING_TIFF_COMPRESSION,
)
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.domain.capture_defaults import (
    DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS,
)

if TYPE_CHECKING:
    from pathlib import Path

    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.application.ports.storage import RecordingSession

RateMode = Literal["fps", "interval"]
SavedFrameCallback = Callable[[int], None]
FrameCallback = Callable[[GrabbedFrame], None]


@dataclass(frozen=True)
class RecordingSettings:
    """Recording撮影1回分の撮影条件と時間条件。"""

    exposure_ms: float
    gain: int
    rate_mode: RateMode
    target_interval_ms: float
    duration_ms: float | None

    def __post_init__(self) -> None:
        """生成時に撮影開始前の入力制約を検証する。"""
        validate_recording_settings(self)


@dataclass(frozen=True)
class RecordingHooks:
    """RecordingCaptureからUI層へ状態を通知するコールバック群。"""

    on_saved_frames_changed: SavedFrameCallback | None = None
    on_frame_captured: FrameCallback | None = None


class RecordingCapture:
    """一定間隔でフレームを取得し、保存ワーカーへ順次投入するUse Case。"""

    def __init__(
        self,
        condition_applier: CaptureConditionApplier,
        frame_grabber: FrameGrabber,
        session: RecordingSession,
        settings: RecordingSettings,
        *,
        save_worker: TiffSaveWorker,
    ) -> None:
        """カメラ操作、保存先Session、保存ワーカーを注入して初期化する。"""
        self.condition_applier = condition_applier
        self.frame_grabber = frame_grabber
        self.session = session
        self.settings = settings
        self.save_worker = save_worker

    def run(
        self,
        cancellation_token: CancellationToken,
        *,
        hooks: RecordingHooks | None = None,
    ) -> None:
        """撮影条件を適用して録画を実行し、Sessionの終了状態を記録する。"""
        hooks = hooks or RecordingHooks()
        cancelled = False
        completed = False
        worker_started = False

        try:
            self._apply_condition()
            self.save_worker.start()
            worker_started = True
            completed, cancelled = self._run_capture_loop(cancellation_token, hooks)
        except Exception as e:
            if worker_started:
                # 保存スレッドを閉じてから失敗状態を書き、未完了のjoin漏れを防ぐ。
                self.save_worker.finish()
            self.session.mark_error(str(e))
            raise

        self.save_worker.finish()
        if self.save_worker.errors:
            error_message = str(self.save_worker.errors[0])
            self.session.mark_error(error_message)
            raise RuntimeError(error_message)

        if cancelled:
            self.session.mark_cancelled()
        elif completed:
            self.session.mark_completed()
        else:
            self.session.mark_completed()

    def _run_capture_loop(
        self,
        cancellation_token: CancellationToken,
        hooks: RecordingHooks,
    ) -> tuple[bool, bool]:
        """予定時刻に合わせて撮影し、完了またはキャンセル状態を返す。"""
        start_monotonic = time.perf_counter()
        timeout_ms = int(self.settings.exposure_ms + DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS)
        frame_index = 1

        while True:
            # frame 1は開始時刻そのものを目標にし、以後はintervalで固定する。
            target_elapsed_ms = (frame_index - 1) * self.settings.target_interval_ms
            target_time = start_monotonic + target_elapsed_ms / 1000.0

            if not self._wait_until(target_time, cancellation_token):
                return False, True

            grabbed = self.frame_grabber.grab(timeout_ms)
            actual_elapsed_ms = (grabbed.monotonic_time_sec - start_monotonic) * 1000.0
            self._enqueue_frame(frame_index, target_elapsed_ms, actual_elapsed_ms, grabbed, hooks)

            if hooks.on_frame_captured is not None:
                hooks.on_frame_captured(grabbed)

            if cancellation_token.is_cancelled():
                return False, True

            if (
                self.settings.duration_ms is not None
                and actual_elapsed_ms >= self.settings.duration_ms
            ):
                return True, False

            frame_index += 1

    def _apply_condition(self) -> None:
        """Recording用の単一撮影条件をカメラへ適用する。"""
        self.condition_applier.apply(
            CaptureCondition(
                exposure_ms=self.settings.exposure_ms,
                gain=self.settings.gain,
            )
        )

    def _wait_until(self, target_time: float, cancellation_token: CancellationToken) -> bool:
        """キャンセルを監視しながら指定monotonic時刻まで待機する。"""
        while True:
            if cancellation_token.is_cancelled():
                return False

            remaining_sec = target_time - time.perf_counter()
            if remaining_sec <= 0:
                return True

            if cancellation_token.wait(remaining_sec):
                return False

    def _enqueue_frame(
        self,
        frame_index: int,
        target_elapsed_ms: float,
        actual_elapsed_ms: float,
        grabbed: GrabbedFrame,
        hooks: RecordingHooks,
    ) -> None:
        """取得済みフレームを保存リクエストへ変換してキューへ投入する。"""
        file_path = self.session.build_frame_path(frame_index)
        row = RecordingFrameRow(
            frame_index=frame_index,
            target_elapsed_ms=target_elapsed_ms,
            actual_elapsed_ms=actual_elapsed_ms,
            timestamp=grabbed.timestamp.isoformat(),
            exposure_ms=self.settings.exposure_ms,
            gain=self.settings.gain,
            filename=file_path.name,
        )
        metadata = self._build_metadata(row)

        self.save_worker.enqueue(
            SaveRequest(
                file_path=file_path,
                # 保存中に次の撮影でバッファが再利用されても内容が変わらないようにする。
                image=grabbed.image.copy(),
                metadata=metadata,
                compression=RECORDING_TIFF_COMPRESSION,
                on_saved=self._build_saved_callback(row, hooks),
            )
        )

    def _build_saved_callback(
        self,
        row: RecordingFrameRow,
        hooks: RecordingHooks,
    ) -> Callable[[Path, float], None]:
        """保存完了時にCSVへ追記し、保存枚数を通知するcallbackを作る。"""
        def on_saved(_file_path: Path, save_elapsed_ms: float) -> None:
            """1フレーム保存後にSession状態とUI通知を更新する。"""
            saved_frames = self.session.append_saved_frame(row, save_elapsed_ms)
            if hooks.on_saved_frames_changed is not None:
                hooks.on_saved_frames_changed(saved_frames)

        return on_saved

    def _build_metadata(self, row: RecordingFrameRow) -> dict:
        """Build metadata embedded in each Recording TIFF."""
        return {
            "capture_mode": "recording",
            "frame_index": row.frame_index,
            "target_elapsed_ms": row.target_elapsed_ms,
            "actual_elapsed_ms": row.actual_elapsed_ms,
            "timestamp": row.timestamp,
            "exposure_ms": row.exposure_ms,
            "gain": row.gain,
        }


def validate_recording_settings(settings: RecordingSettings) -> None:
    """Recording開始前に撮影条件と間隔の制約を検証する。"""
    if settings.exposure_ms <= 0:
        msg = "露光時間は正の値にしてください。"
        raise ValueError(msg)
    if settings.gain < 0:
        msg = "ゲインは0以上にしてください。"
        raise ValueError(msg)
    if settings.target_interval_ms <= 0:
        msg = "撮影間隔は正の値にしてください。"
        raise ValueError(msg)
    if settings.duration_ms is not None and settings.duration_ms <= 0:
        msg = "撮影時間は正の値にしてください。"
        raise ValueError(msg)
    if settings.exposure_ms > settings.target_interval_ms:
        # 露光が間隔を超えるとフレーム落ちなしの録画条件を満たせない。
        msg = (
            "露光時間が撮影間隔より長いため、録画を開始できません。\n\n"
            f"露光時間: {settings.exposure_ms:g} ms\n"
            f"撮影間隔: {settings.target_interval_ms:g} ms\n\n"
            f"撮影間隔を {settings.exposure_ms:g} ms 以上にするか、"
            "露光時間を短くしてください。"
        )
        raise ValueError(msg)


def interval_from_fps(fps: float) -> float:
    """FPS値を1フレームあたりの間隔msへ変換する。"""
    if fps <= 0:
        msg = "FPSは正の値にしてください。"
        raise ValueError(msg)

    return 1000.0 / fps


def normalize_duration_ms(duration_sec: float) -> float | None:
    """0秒以下を無期限として扱い、それ以外をmsへ変換する。"""
    if duration_sec <= 0:
        return None

    return duration_sec * 1000.0
