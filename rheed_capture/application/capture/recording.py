from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

import numpy as np

from rheed_capture.application.capture.cancellation import CaptureCancelled
from rheed_capture.application.capture.frame_capturer import (
    CaptureConditionApplier,
    FrameGrabber,
    GrabbedFrame,
)
from rheed_capture.application.capture.save_worker import SaveRequest, TiffSaveWorker
from rheed_capture.data_formats.recording import RecordingFrameRow
from rheed_capture.data_formats.storage_naming import RECORDING_TIFF_COMPRESSION
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.domain.capture_defaults import DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS

if TYPE_CHECKING:
    from pathlib import Path

    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.application.ports.storage import RecordingSession

RateMode = Literal["fps", "interval"]
SavedFrameCallback = Callable[[int], None]
FrameCallback = Callable[[GrabbedFrame], None]
PreviewCallback = Callable[[np.ndarray], None]
ProgressCallback = Callable[[int, int], None]
WaitingCallback = Callable[[bool], None]


@dataclass(frozen=True)
class RecordingSettings:
    """Recording撮影1回分の撮影条件と時間条件。"""

    exposure_ms: float
    gain: int
    rate_mode: RateMode
    target_interval_ms: float
    duration_ms: float | None
    tiff_compression_enabled: bool = True

    def __post_init__(self) -> None:
        """生成時にモードに依存しない入力制約を検証する。"""
        validate_recording_settings(self, enforce_software_schedule=False)


@dataclass(frozen=True)
class RecordingHooks:
    """RecordingCaptureからUI層へ状態を通知するコールバック群。"""

    on_saved_frames_changed: SavedFrameCallback | None = None
    on_frame_captured: FrameCallback | None = None
    on_preview_frame_completed: PreviewCallback | None = None
    on_accumulation_progress: ProgressCallback | None = None
    on_waiting_for_trigger_changed: WaitingCallback | None = None


class RecordingCapture:
    """SoftwareまたはHardware triggerでRecording Rawを逐次保存するUse Case。"""

    def __init__(
        self,
        condition_applier: CaptureConditionApplier,
        frame_grabber: FrameGrabber,
        session: RecordingSession,
        settings: RecordingSettings,
        *,
        save_worker: TiffSaveWorker,
        accumulation_frames: int = 1,
        trigger_wait_timeout_sec: float = 0,
    ) -> None:
        """カメラ操作、保存先Session、保存ワーカーを注入して初期化する。"""
        if accumulation_frames <= 0:
            msg = "蓄積フレーム数は1以上にしてください。"
            raise ValueError(msg)
        if trigger_wait_timeout_sec < 0:
            msg = "Trigger待機時間は0以上にしてください。"
            raise ValueError(msg)

        validate_recording_settings(
            settings,
            enforce_software_schedule=frame_grabber.trigger_settings.mode == "software",
        )
        self.condition_applier = condition_applier
        self.frame_grabber = frame_grabber
        self.session = session
        self.settings = settings
        self.save_worker = save_worker
        self.accumulation_frames = accumulation_frames
        self.trigger_wait_timeout_sec = trigger_wait_timeout_sec

    def run(
        self,
        cancellation_token: CancellationToken,
        *,
        hooks: RecordingHooks | None = None,
    ) -> None:
        """撮影条件を適用して録画を実行し、Sessionの終了状態を記録する。"""
        hooks = hooks or RecordingHooks()
        cancelled = False
        worker_started = False

        try:
            self._apply_condition()
            self.save_worker.start()
            worker_started = True
            _, cancelled = self._run_capture_loop(cancellation_token, hooks)
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
        else:
            self.session.mark_completed()

    def _run_capture_loop(
        self,
        cancellation_token: CancellationToken,
        hooks: RecordingHooks,
    ) -> tuple[bool, bool]:
        """Trigger modeに対応する取得ループを実行する。"""
        if self.frame_grabber.trigger_settings.mode == "hardware":
            return self._run_hardware_capture_loop(cancellation_token, hooks)
        return self._run_software_capture_loop(cancellation_token, hooks)

    def _run_software_capture_loop(
        self,
        cancellation_token: CancellationToken,
        hooks: RecordingHooks,
    ) -> tuple[bool, bool]:
        """予定時刻を基準にSoftware schedulingでRawを取得する。"""
        start_monotonic = time.perf_counter()
        timeout_ms = int(self.settings.exposure_ms + DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS)
        frame_index = 1
        group_index = 1
        group_sum: np.ndarray | None = None

        # Recordingは正常なカメラSessionを全フレームで共有し、失敗時だけ再作成する。
        with self.frame_grabber.start_session(expected_frames=None) as trigger_session:
            while True:
                target_elapsed_ms = (frame_index - 1) * self.settings.target_interval_ms
                target_time = start_monotonic + target_elapsed_ms / 1000.0
                if not self._wait_until(target_time, cancellation_token):
                    return False, True

                grabbed = trigger_session.grab(timeout_ms)
                actual_elapsed_ms = (
                    grabbed.timing.trigger_issued_monotonic_sec - start_monotonic
                ) * 1000.0
                raw_index = self._raw_index_in_group(frame_index)
                group_sum = self._save_and_notify_raw(
                    frame_index,
                    group_index,
                    raw_index,
                    target_elapsed_ms,
                    actual_elapsed_ms,
                    grabbed,
                    group_sum,
                    hooks,
                )

                if raw_index == self.accumulation_frames:
                    self._notify_completed_preview(group_sum, hooks)
                    group_sum = None
                    group_index += 1

                if cancellation_token.is_cancelled():
                    return False, True
                if (
                    self.settings.duration_ms is not None
                    and actual_elapsed_ms >= self.settings.duration_ms
                ):
                    return True, False

                # 遅延時も番号を飛ばさず、次の元の予定時刻を同じ式で評価する。
                frame_index += 1

    def _run_hardware_capture_loop(
        self,
        cancellation_token: CancellationToken,
        hooks: RecordingHooks,
    ) -> tuple[bool, bool]:
        """初回timeoutとduration境界を分離してHardware Rawを取得する。"""
        frame_index = 1
        group_index = 1
        group_sum: np.ndarray | None = None
        first_raw_monotonic: float | None = None
        duration_deadline: float | None = None

        with self.frame_grabber.start_session(expected_frames=None) as trigger_session:
            while True:
                raw_index = self._raw_index_in_group(frame_index)
                completing_existing_group = raw_index != 1
                if (
                    duration_deadline is not None
                    and not completing_existing_group
                    and time.perf_counter() >= duration_deadline
                ):
                    return True, False

                wait_timeout_sec = self._hardware_wait_timeout(
                    first_raw_monotonic,
                    duration_deadline,
                    completing_existing_group,
                )

                try:
                    self._set_waiting(hooks, True)
                    grabbed = trigger_session.grab_hardware(
                        wait_timeout_sec=wait_timeout_sec,
                        cancellation_token=cancellation_token,
                    )
                except CaptureCancelled:
                    return False, True
                except TimeoutError as e:
                    if first_raw_monotonic is None:
                        msg = "Trigger Wait Timeout Error"
                        raise TimeoutError(msg) from e
                    # group外のduration残時間を使い切った場合は正常終了にする。
                    return True, False
                finally:
                    self._set_waiting(hooks, False)

                arrived_monotonic = grabbed.timing.trigger_issued_monotonic_sec
                if (
                    duration_deadline is not None
                    and raw_index == 1
                    and arrived_monotonic >= duration_deadline
                ):
                    # deadline以降に到着したRawを新groupとして保存しない。
                    return True, False

                if first_raw_monotonic is None:
                    first_raw_monotonic = arrived_monotonic
                    if self.settings.duration_ms is not None:
                        duration_deadline = (
                            first_raw_monotonic + self.settings.duration_ms / 1000.0
                        )

                actual_elapsed_ms = (arrived_monotonic - first_raw_monotonic) * 1000.0
                group_sum = self._save_and_notify_raw(
                    frame_index,
                    group_index,
                    raw_index,
                    None,
                    actual_elapsed_ms,
                    grabbed,
                    group_sum,
                    hooks,
                )

                if raw_index == self.accumulation_frames:
                    self._notify_completed_preview(group_sum, hooks)
                    group_sum = None
                    group_index += 1

                frame_index += 1

    def _apply_condition(self) -> None:
        """Recording用の単一撮影条件をカメラへ適用する。"""
        self.condition_applier.apply(
            CaptureCondition(
                exposure_ms=self.settings.exposure_ms,
                gain=self.settings.gain,
            )
        )

    def _hardware_wait_timeout(
        self,
        first_raw_monotonic: float | None,
        duration_deadline: float | None,
        completing_existing_group: bool,
    ) -> float:
        """Hardware Rawの現在の待機理由に対応するtimeoutを返す。"""
        if first_raw_monotonic is None:
            return self.trigger_wait_timeout_sec
        if completing_existing_group or duration_deadline is None:
            # 開始済みgroupはduration後でもN枚まで保持し、共通timeoutを使わない。
            return 0
        return max(0, duration_deadline - time.perf_counter())

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

    def _save_and_notify_raw(
        self,
        frame_index: int,
        group_index: int,
        raw_index: int,
        target_elapsed_ms: float | None,
        actual_elapsed_ms: float,
        grabbed: GrabbedFrame,
        group_sum: np.ndarray | None,
        hooks: RecordingHooks,
    ) -> np.ndarray:
        """Rawを直ちに保存キューへ渡し、統計と積算状態を通知する。"""
        self._enqueue_frame(
            frame_index,
            group_index,
            raw_index,
            target_elapsed_ms,
            actual_elapsed_ms,
            grabbed,
            hooks,
        )
        if hooks.on_frame_captured is not None:
            hooks.on_frame_captured(grabbed)
        if hooks.on_accumulation_progress is not None:
            hooks.on_accumulation_progress(raw_index, self.accumulation_frames)

        image_wide = np.asarray(grabbed.image, dtype=np.uint64)
        return image_wide if group_sum is None else group_sum + image_wide

    def _notify_completed_preview(
        self,
        group_sum: np.ndarray | None,
        hooks: RecordingHooks,
    ) -> None:
        """完了groupだけをuint16飽和画像としてPreviewへ通知する。"""
        if group_sum is None:
            msg = "蓄積撮影でRawフレームを取得できませんでした。"
            raise RuntimeError(msg)
        if hooks.on_preview_frame_completed is not None:
            preview_image = np.clip(group_sum, 0, np.iinfo(np.uint16).max).astype(np.uint16)
            hooks.on_preview_frame_completed(preview_image)

    def _raw_index_in_group(self, frame_index: int) -> int:
        """Raw通番から1始まりのgroup内Raw番号を返す。"""
        return (frame_index - 1) % self.accumulation_frames + 1

    def _set_waiting(self, hooks: RecordingHooks, waiting: bool) -> None:
        """Hardware trigger待機状態をUIへ通知する。"""
        if hooks.on_waiting_for_trigger_changed is not None:
            hooks.on_waiting_for_trigger_changed(waiting)

    def _enqueue_frame(
        self,
        frame_index: int,
        group_index: int,
        raw_index: int,
        target_elapsed_ms: float | None,
        actual_elapsed_ms: float,
        grabbed: GrabbedFrame,
        hooks: RecordingHooks,
    ) -> None:
        """取得済みRawを保存リクエストへ変換してキューへ投入する。"""
        if self.accumulation_frames == 1:
            file_path = self.session.build_frame_path(frame_index)
            filename = file_path.name
        else:
            file_path = self.session.build_accumulation_frame_path(group_index, raw_index)
            filename = file_path.relative_to(self.session.session_dir).as_posix()

        row = RecordingFrameRow(
            frame_index=frame_index,
            target_elapsed_ms=target_elapsed_ms,
            actual_elapsed_ms=actual_elapsed_ms,
            timestamp=grabbed.timing.trigger_issued_at.isoformat(),
            exposure_ms=self.settings.exposure_ms,
            gain=self.settings.gain,
            camera_exposure_ms=grabbed.readback.exposure_ms,
            camera_gain=grabbed.readback.gain,
            camera_timestamp_ticks=grabbed.readback.camera_timestamp_ticks,
            camera_timestamp_frequency_hz=grabbed.readback.camera_timestamp_frequency_hz,
            camera_timestamp_source=grabbed.readback.source,
            filename=filename,
        )
        row_holder: list[RecordingFrameRow | None] = [None]

        def on_enqueued(queue_depth: int) -> None:
            """enqueue admission時の待機深さを保存対象行へ束縛する。"""
            row_holder[0] = replace(row, save_queue_depth=queue_depth)

        self.save_worker.enqueue(
            SaveRequest(
                file_path=file_path,
                # 保存中に次の撮影でバッファが再利用されても内容が変わらないようにする。
                image=grabbed.image.copy(),
                metadata=self._build_metadata(row),
                compression=(
                    RECORDING_TIFF_COMPRESSION
                    if self.settings.tiff_compression_enabled
                    else None
                ),
                on_saved=self._build_saved_callback(row_holder, hooks),
                on_enqueued=on_enqueued,
            )
        )

    def _build_saved_callback(
        self,
        row_holder: list[RecordingFrameRow | None],
        hooks: RecordingHooks,
    ) -> Callable[[Path, float], None]:
        """保存完了時にenqueue時の行をCSVへ追記するcallbackを作る。"""
        def on_saved(_file_path: Path, save_elapsed_ms: float) -> None:
            """1 Raw保存後にSession状態とUI通知を更新する。"""
            row = row_holder[0]
            if row is None:
                msg = "保存要求のqueue depthが確定していません。"
                raise RuntimeError(msg)
            saved_frames = self.session.append_saved_frame(row, save_elapsed_ms)
            if hooks.on_saved_frames_changed is not None:
                hooks.on_saved_frames_changed(saved_frames)

        return on_saved

    def _build_metadata(self, row: RecordingFrameRow) -> dict[str, object]:
        """Build Raw-level metadata embedded in a Recording TIFF."""
        return {
            "capture_mode": "recording",
            "frame_index": row.frame_index,
            "target_elapsed_ms": row.target_elapsed_ms,
            "actual_elapsed_ms": row.actual_elapsed_ms,
            "timestamp": row.timestamp,
            "camera_exposure_ms": row.camera_exposure_ms,
            "camera_gain": row.camera_gain,
            "camera_timestamp_ticks": row.camera_timestamp_ticks,
            "camera_timestamp_frequency_hz": row.camera_timestamp_frequency_hz,
            "camera_timestamp_source": row.camera_timestamp_source,
            "exposure_ms": row.exposure_ms,
            "gain": row.gain,
        }


def validate_recording_settings(
    settings: RecordingSettings,
    *,
    enforce_software_schedule: bool,
) -> None:
    """Recording開始前にモードに対応する撮影条件を検証する。"""
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
    if enforce_software_schedule and settings.exposure_ms > settings.target_interval_ms:
        # Hardware triggerは外部時刻で進むため、このSoftware scheduling制約を適用しない。
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
