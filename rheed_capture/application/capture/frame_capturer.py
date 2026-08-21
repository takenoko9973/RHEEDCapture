from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Never, Protocol, Self
from zoneinfo import ZoneInfo

from rheed_capture.application.ports.camera import (
    DEFAULT_TRIGGER_SETTINGS,
    Camera,
    CameraError,
    FrameReadback,
    TriggerCaptureSession,
    TriggerSettings,
)
from rheed_capture.domain.capture_defaults import (
    DEFAULT_CAPTURE_RETRY_INTERVAL_SEC,
    DEFAULT_CAPTURE_RETRY_LIMIT,
    DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

    import numpy as np

    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.domain.capture_condition import CaptureCondition

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class CaptureTiming:
    """アプリによるソフトウェアトリガー発行時刻を保持する。"""

    trigger_issued_at: datetime
    trigger_issued_monotonic_sec: float


@dataclass(frozen=True)
class CapturedFrame:
    """保存と通知へ渡す、1回分の撮影結果。"""

    # 保存画像はプレビュー用CLAHEやグリッドを適用しないRaw相当画像。
    image: np.ndarray
    condition: CaptureCondition
    readback: FrameReadback
    timing: CaptureTiming


@dataclass(frozen=True)
class GrabbedFrame:
    """カメラから取得したRaw画像と撮影時刻情報。"""

    image: np.ndarray
    readback: FrameReadback
    timing: CaptureTiming


class FrameCapture(Protocol):
    """撮影方式が依存する1フレーム取得インターフェース。"""

    def capture(self, condition: CaptureCondition) -> CapturedFrame:
        """指定条件で1フレームを取得する。"""
        ...

    def capture_group(
        self,
        condition: CaptureCondition,
        *,
        frame_count: int,
        hardware_wait_timeout_sec: float,
        cancellation_token: CancellationToken,
    ) -> Iterator[CapturedFrame]:
        """同一条件のRawフレーム群を逐次取得する。"""
        ...


class CaptureConditionApplier:
    """露光時間とゲインをカメラへ適用する。"""

    def __init__(self, camera: Camera) -> None:
        """設定対象のカメラPortを保持する。"""
        self.camera = camera

    def apply(self, condition: CaptureCondition) -> None:
        """撮影条件をカメラへ順に設定する。"""
        self.camera.set_exposure(condition.exposure_ms)
        self.camera.set_gain(condition.gain)


class FrameGrabber:
    """1フレーム取得、リトライ、取得時刻付与を担当する。"""

    def __init__(
        self,
        camera: Camera,
        *,
        trigger_settings: TriggerSettings = DEFAULT_TRIGGER_SETTINGS,
        max_retries: int = DEFAULT_CAPTURE_RETRY_LIMIT,
        retry_interval_sec: float = DEFAULT_CAPTURE_RETRY_INTERVAL_SEC,
    ) -> None:
        """カメラとリトライ条件を保持する。"""
        self.camera = camera
        self.trigger_settings = trigger_settings
        self.max_retries = max_retries
        self.retry_interval_sec = retry_interval_sec

    def grab(self, timeout_ms: int) -> GrabbedFrame:
        """1フレーム用セッションを使い、失敗時は新しいセッションで再試行する。"""
        with self.start_session(expected_frames=1) as session:
            return session.grab(timeout_ms)

    def start_session(self, *, expected_frames: int | None) -> FrameGrabberSession:
        """リトライ時にカメラセッションを再作成する取得Sessionを返す。"""
        return FrameGrabberSession(self, expected_frames=expected_frames)

    def _execute_single_grab(
        self,
        session: TriggerCaptureSession,
        timeout_ms: int,
    ) -> GrabbedFrame:
        """1回のdeadline内でready待機、trigger発行、frame取得を実行する。"""
        deadline = time.perf_counter() + timeout_ms / 1000.0

        if self.trigger_settings.mode == "software":
            session.wait_until_ready(self._remaining_timeout_ms(deadline))
            # PC時刻はカメラへtrigger命令を渡す直前を撮影時刻として記録する。
            trigger_issued_at = datetime.now(JST)
            trigger_issued_monotonic_sec = time.perf_counter()
            session.execute_software_trigger()
            camera_frame = session.retrieve_frame(self._remaining_timeout_ms(deadline))
        else:
            camera_frame = session.retrieve_frame(self._remaining_timeout_ms(deadline))
            # Hardware trigger時はRaw到着時をhost側の取得時刻として記録する。
            trigger_issued_at = datetime.now(JST)
            trigger_issued_monotonic_sec = time.perf_counter()

        return GrabbedFrame(
            image=camera_frame.image,
            readback=camera_frame.readback,
            timing=CaptureTiming(
                trigger_issued_at=trigger_issued_at,
                trigger_issued_monotonic_sec=trigger_issued_monotonic_sec,
            ),
        )

    def _remaining_timeout_ms(self, deadline: float) -> int:
        """共通deadlineまでの残り時間をSDKへ渡せる正のミリ秒へ変換する。"""
        remaining_sec = deadline - time.perf_counter()
        if remaining_sec <= 0:
            msg = "フレーム取得の期限を超過しました。"
            raise TimeoutError(msg)

        # SDKが整数msを要求するため、正の残時間を0msへ切り捨てない。
        return math.ceil(remaining_sec * 1000.0)

    def _raise_max_retry_error(self, error: Exception | None) -> Never:
        """最後に観測した例外を原因として、利用者向けの撮影失敗例外を投げる。"""
        msg = "最大リトライ回数に達しました。"
        if error:
            raise RuntimeError(msg) from error

        raise RuntimeError(msg)


class FrameGrabberSession:
    """正常時は再利用し、取得失敗時だけ再作成するApplication取得Session。"""

    def __init__(self, frame_grabber: FrameGrabber, *, expected_frames: int | None) -> None:
        """FrameGrabberとカメラ側の予定フレーム数を保持する。"""
        self.frame_grabber = frame_grabber
        self.expected_frames = expected_frames
        self._camera_session: TriggerCaptureSession | None = None

    def __enter__(self) -> Self:
        """取得時にカメラSessionを開始するApplication Sessionを返す。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Recordingの正常終了、例外、キャンセルでカメラセッションを閉じる。"""
        try:
            self.close()
        except CameraError:
            if exc_value is None:
                raise
            logger.exception("取得失敗後のカメラSession終了にも失敗しました")

    def grab(self, timeout_ms: int) -> GrabbedFrame:
        """現在のセッションで1枚取得し、失敗時は再アームして同じフレームを再試行する。"""
        last_error: Exception | None = None

        for attempt in range(1, self.frame_grabber.max_retries + 1):
            try:
                if self._camera_session is None:
                    self._open_camera_session()
                session = self._require_camera_session()
                return self.frame_grabber._execute_single_grab(  # noqa: SLF001
                    session,
                    timeout_ms,
                )
            except (CameraError, RuntimeError, TimeoutError) as e:
                logger.warning(
                    "撮影エラー (Attempt %d/%d): %s",
                    attempt,
                    self.frame_grabber.max_retries,
                    e,
                )
                last_error = e
                try:
                    self.close()
                except CameraError:
                    # 再撮影の原因を保持し、cleanup失敗は診断用に別途記録する。
                    logger.exception("取得失敗後のカメラSession終了にも失敗しました")
                if attempt < self.frame_grabber.max_retries:
                    time.sleep(self.frame_grabber.retry_interval_sec)

        self.frame_grabber._raise_max_retry_error(last_error)  # noqa: SLF001
        msg = "unreachable"
        raise AssertionError(msg)

    def grab_hardware(
        self,
        *,
        wait_timeout_sec: float,
        cancellation_token: CancellationToken,
    ) -> GrabbedFrame:
        """Hardware triggerの1 Rawを再試行せず、キャンセル可能な短い待機で取得する。"""
        if self._camera_session is None:
            self._open_camera_session()
        session = self._require_camera_session()

        deadline = (
            None
            if wait_timeout_sec == 0
            else time.perf_counter() + wait_timeout_sec
        )

        while True:
            cancellation_token.raise_if_cancelled()
            timeout_ms = self._hardware_poll_timeout_ms(deadline)
            try:
                camera_frame = session.retrieve_frame(timeout_ms)
            except TimeoutError as e:
                cancellation_token.raise_if_cancelled()
                if deadline is not None and time.perf_counter() >= deadline:
                    msg = "Hardware trigger待機が設定時間を超過しました。"
                    raise TimeoutError(msg) from e
                continue

            # Hardware triggerではRaw到着時をhost側の取得時刻として記録する。
            return GrabbedFrame(
                image=camera_frame.image,
                readback=camera_frame.readback,
                timing=CaptureTiming(
                    trigger_issued_at=datetime.now(JST),
                    trigger_issued_monotonic_sec=time.perf_counter(),
                ),
            )

    @staticmethod
    def _hardware_poll_timeout_ms(deadline: float | None) -> int:
        """Stop要求を待機中にも確認できるよう、SDK待機時間を短く制限する。"""
        poll_timeout_ms = 100
        if deadline is None:
            return poll_timeout_ms

        remaining_sec = deadline - time.perf_counter()
        if remaining_sec <= 0:
            msg = "Hardware trigger待機が設定時間を超過しました。"
            raise TimeoutError(msg)

        return min(poll_timeout_ms, math.ceil(remaining_sec * 1000.0))

    def close(self) -> None:
        """現在のカメラセッションがあれば閉じる。"""
        session = self._camera_session
        self._camera_session = None
        if session is not None:
            session.close()

    def _open_camera_session(self) -> None:
        """Camera Portから現在設定のTrigger Sessionを開始する。"""
        self._camera_session = self.frame_grabber.camera.start_trigger_session(
            settings=self.frame_grabber.trigger_settings,
            expected_frames=self.expected_frames,
        )

    def _require_camera_session(self) -> TriggerCaptureSession:
        """開始済みのカメラセッションを返す。"""
        if self._camera_session is None:
            msg = "Trigger Sessionが開始されていません。"
            raise CameraError(msg)

        return self._camera_session


class FrameCapturer:
    """既存Sequence/Angle Scan用に条件適用とフレーム取得をまとめる。"""

    def __init__(
        self,
        camera: Camera,
        *,
        trigger_settings: TriggerSettings = DEFAULT_TRIGGER_SETTINGS,
        max_retries: int = DEFAULT_CAPTURE_RETRY_LIMIT,
        retry_interval_sec: float = DEFAULT_CAPTURE_RETRY_INTERVAL_SEC,
    ) -> None:
        """条件適用とフレーム取得の小さな部品を組み合わせる。"""
        self.condition_applier = CaptureConditionApplier(camera)
        self.frame_grabber = FrameGrabber(
            camera,
            trigger_settings=trigger_settings,
            max_retries=max_retries,
            retry_interval_sec=retry_interval_sec,
        )

    def capture(self, condition: CaptureCondition) -> CapturedFrame:
        """指定条件を1回適用してから、リトライ付きで1枚取得する。"""
        self.condition_applier.apply(condition)
        timeout_ms = int(condition.exposure_ms + DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS)
        grabbed = self.frame_grabber.grab(timeout_ms)

        return CapturedFrame(
            image=grabbed.image,
            condition=condition,
            readback=grabbed.readback,
            timing=grabbed.timing,
        )

    def capture_group(
        self,
        condition: CaptureCondition,
        *,
        frame_count: int,
        hardware_wait_timeout_sec: float,
        cancellation_token: CancellationToken,
    ) -> Iterator[CapturedFrame]:
        """条件を1回だけ適用し、同じTrigger SessionからRawを逐次取得する。"""
        if frame_count <= 0:
            msg = "Raw取得数は1以上にしてください。"
            raise ValueError(msg)

        self.condition_applier.apply(condition)
        timeout_ms = int(condition.exposure_ms + DEFAULT_CAPTURE_TIMEOUT_MARGIN_MS)
        with self.frame_grabber.start_session(expected_frames=frame_count) as session:
            for _ in range(frame_count):
                cancellation_token.raise_if_cancelled()
                if self.frame_grabber.trigger_settings.mode == "hardware":
                    grabbed = session.grab_hardware(
                        wait_timeout_sec=hardware_wait_timeout_sec,
                        cancellation_token=cancellation_token,
                    )
                else:
                    # Software triggerのdeadlineと再試行規則は単一撮影時と同じにする。
                    grabbed = session.grab(timeout_ms)

                yield CapturedFrame(
                    image=grabbed.image,
                    condition=condition,
                    readback=grabbed.readback,
                    timing=grabbed.timing,
                )
