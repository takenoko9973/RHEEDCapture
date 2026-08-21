from __future__ import annotations

from datetime import datetime
from typing import Self
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from rheed_capture.application.capture import frame_capturer as frame_capturer_module
from rheed_capture.application.capture.cancellation import CancellationToken
from rheed_capture.application.capture.frame_capturer import FrameCapturer
from rheed_capture.application.ports.camera import (
    CameraError,
    CameraFrame,
    FrameReadback,
    TriggerSettings,
)
from rheed_capture.domain.capture_condition import CaptureCondition


class _FakeTriggerCaptureSession:
    """FrameCapturer用のソフトトリガーSession test double。"""

    def __init__(self, result: CameraFrame | Exception) -> None:
        """1回の取得結果と呼出履歴を保持する。"""
        self.result = result
        self.calls: list[tuple[str, int | None]] = []
        self.closed = False

    def __enter__(self) -> Self:
        """Session自身を返す。"""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # noqa: ANN001
        """context終了時にSessionを閉じる。"""
        self.close()

    def wait_until_ready(self, timeout_ms: int) -> None:
        """TriggerReady待機の順序とtimeoutを記録する。"""
        self.calls.append(("wait", timeout_ms))

    def execute_software_trigger(self) -> None:
        """trigger発行順序を記録する。"""
        self.calls.append(("trigger", None))

    def retrieve_frame(self, timeout_ms: int) -> CameraFrame:
        """準備済みのCameraFrameまたは例外を返す。"""
        self.calls.append(("retrieve", timeout_ms))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self) -> None:
        """Sessionを冪等に終了する。"""
        self.closed = True


class _FakeCamera:
    """試行ごとに新しいソフトトリガーSessionを作るCamera test double。"""

    def __init__(self, results: list[CameraFrame | Exception]) -> None:
        """各試行で返す結果を保持する。"""
        self.results = results
        self.exposures: list[float] = []
        self.gains: list[int] = []
        self.expected_frames: list[int | None] = []
        self.trigger_settings: list[TriggerSettings] = []
        self.sessions: list[_FakeTriggerCaptureSession] = []

    def set_exposure(self, exposure_ms: float) -> None:
        """設定された露光時間を記録する。"""
        self.exposures.append(exposure_ms)

    def set_gain(self, gain: int) -> None:
        """設定されたGainを記録する。"""
        self.gains.append(gain)

    def start_trigger_session(
        self,
        *,
        settings: TriggerSettings,
        expected_frames: int | None,
    ) -> _FakeTriggerCaptureSession:
        """次の結果を持つ新しいSessionを作成する。"""
        self.trigger_settings.append(settings)
        self.expected_frames.append(expected_frames)
        session = _FakeTriggerCaptureSession(self.results.pop(0))
        self.sessions.append(session)
        return session


def _camera_frame(image: np.ndarray, ticks: int = 10) -> CameraFrame:
    """テスト用のCameraFrameを生成する。"""
    return CameraFrame(
        image=image,
        readback=FrameReadback(
            exposure_ms=11.0,
            gain=3,
            camera_timestamp_ticks=ticks,
            camera_timestamp_frequency_hz=125_000_000,
            source="camera",
        ),
    )


def test_frame_capturer_keeps_requested_condition_and_camera_readback() -> None:
    """要求条件とcamera読戻し値を区別して1回の撮影結果に保持する。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([_camera_frame(image)])
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    captured = capturer.capture(CaptureCondition(exposure_ms=10.5, gain=2))

    assert np.array_equal(captured.image, image)
    assert captured.condition.exposure_ms == 10.5
    assert captured.condition.gain == 2
    assert captured.readback.exposure_ms == 11.0
    assert captured.readback.gain == 3
    assert captured.readback.camera_timestamp_ticks == 10
    assert captured.readback.camera_timestamp_frequency_hz == 125_000_000
    assert captured.readback.source == "camera"
    assert captured.timing.trigger_issued_at.tzinfo == ZoneInfo("Asia/Tokyo")
    assert camera.exposures == [10.5]
    assert camera.gains == [2]
    assert camera.expected_frames == [1]
    assert [name for name, _ in camera.sessions[0].calls] == [
        "wait",
        "trigger",
        "retrieve",
    ]
    assert camera.sessions[0].closed


def test_frame_capturer_retries_with_successful_attempt_timing(monkeypatch) -> None:  # noqa: ANN001
    """再試行成功時は失敗試行ではなく成功試行の時刻を撮影結果へ残す。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([CameraError("temporary"), _camera_frame(image, ticks=20)])
    issued_at_values = iter(
        [
            datetime(2026, 7, 13, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            datetime(2026, 7, 13, 10, 1, tzinfo=ZoneInfo("Asia/Tokyo")),
        ]
    )

    class _FakeDateTime:
        """試行ごとに異なるtrigger発行時刻を返す。"""

        @staticmethod
        def now(_timezone) -> datetime:  # noqa: ANN001
            """次の固定時刻を返す。"""
            return next(issued_at_values)

    monkeypatch.setattr(frame_capturer_module, "datetime", _FakeDateTime)
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    captured = capturer.capture(CaptureCondition(exposure_ms=20.0, gain=1))

    assert np.array_equal(captured.image, image)
    assert captured.timing.trigger_issued_at.minute == 1
    assert captured.readback.camera_timestamp_ticks == 20
    assert camera.expected_frames == [1, 1]
    assert len(camera.sessions) == 2
    assert all(session.closed for session in camera.sessions)


def test_frame_capturer_retries_when_session_start_fails(monkeypatch) -> None:  # noqa: ANN001
    """初回のCamera Session開始失敗後に新しいSessionで再試行する。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([_camera_frame(image)])
    original_start = camera.start_trigger_session
    start_attempts = 0

    def start_session(
        *,
        settings: TriggerSettings,
        expected_frames: int | None,
    ) -> _FakeTriggerCaptureSession:
        """初回だけ開始エラーを発生させ、以後は通常Sessionを返す。"""
        nonlocal start_attempts
        start_attempts += 1
        if start_attempts == 1:
            msg = "temporary start failure"
            raise CameraError(msg)

        return original_start(settings=settings, expected_frames=expected_frames)

    monkeypatch.setattr(camera, "start_trigger_session", start_session)
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    captured = capturer.capture(CaptureCondition(exposure_ms=20.0, gain=1))

    assert np.array_equal(captured.image, image)
    assert start_attempts == 2
    assert camera.expected_frames == [1]
    assert camera.sessions[0].closed


def test_frame_capturer_passes_remaining_shared_deadline(monkeypatch) -> None:  # noqa: ANN001
    """ready待機とretrieveへ別枠でなく共通deadlineの残時間を渡す。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([_camera_frame(image)])
    monotonic_values = iter([0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr(
        frame_capturer_module.time,
        "perf_counter",
        lambda: next(monotonic_values),
    )
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    capturer.capture(CaptureCondition(exposure_ms=10.0, gain=0))

    wait_timeout = camera.sessions[0].calls[0][1]
    retrieve_timeout = camera.sessions[0].calls[2][1]
    assert wait_timeout is not None
    assert retrieve_timeout is not None
    assert 409 <= wait_timeout <= 411
    assert 209 <= retrieve_timeout <= 211
    assert retrieve_timeout < wait_timeout


def test_frame_capturer_raises_after_three_failures() -> None:
    """3つの異常Sessionを再利用せず、最大リトライ到達を通知する。"""
    camera = _FakeCamera(
        [CameraError("first"), TimeoutError("second"), CameraError("third")]
    )
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    with pytest.raises(RuntimeError, match="最大リトライ"):
        capturer.capture(CaptureCondition(exposure_ms=40.0, gain=4))

    assert camera.expected_frames == [1, 1, 1]
    assert all(session.closed for session in camera.sessions)


def test_hardware_group_timeout_does_not_retry_or_discard_saved_raw() -> None:
    """Hardware trigger timeoutは同一Rawを3回再試行せず、先行Rawを保持して失敗する。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([_camera_frame(image)])
    settings = TriggerSettings(
        mode="hardware",
        hardware_source="Line1",
        hardware_activation="RisingEdge",
        hardware_delay_us=0,
        fps_limit=None,
    )
    capturer = FrameCapturer(camera, trigger_settings=settings, retry_interval_sec=0)
    token = CancellationToken()

    frames = capturer.capture_group(
        CaptureCondition(exposure_ms=10.0, gain=0),
        frame_count=2,
        hardware_wait_timeout_sec=0.001,
        cancellation_token=token,
    )

    first = next(frames)
    camera.sessions[0].result = TimeoutError("trigger missing")
    with pytest.raises(TimeoutError, match="設定時間"):
        next(frames)

    assert np.array_equal(first.image, image)
    assert camera.exposures == [10.0]
    assert camera.gains == [0]
    assert camera.expected_frames == [2]
    assert len(camera.sessions) == 1
    assert camera.sessions[0].closed


def test_hardware_single_frame_group_uses_wait_timeout_without_retry() -> None:
    """N=1でもHardware trigger待機timeoutは再アームせず即時に失敗する。"""
    camera = _FakeCamera([TimeoutError("trigger missing")])
    settings = TriggerSettings(
        mode="hardware",
        hardware_source="Line1",
        hardware_activation="RisingEdge",
        hardware_delay_us=0,
        fps_limit=None,
    )
    capturer = FrameCapturer(camera, trigger_settings=settings, retry_interval_sec=0)

    frames = capturer.capture_group(
        CaptureCondition(exposure_ms=10.0, gain=0),
        frame_count=1,
        hardware_wait_timeout_sec=0.001,
        cancellation_token=CancellationToken(),
    )

    with pytest.raises(TimeoutError, match="設定時間"):
        next(frames)

    assert camera.expected_frames == [1]
    assert len(camera.sessions) == 1
    assert all(name == "retrieve" for name, _timeout_ms in camera.sessions[0].calls)
    assert camera.sessions[0].closed


def test_software_single_frame_group_keeps_existing_retry_behavior() -> None:
    """N=1のSoftware取得は従来どおりdeadline付きで再試行する。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([CameraError("temporary"), _camera_frame(image)])
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    frames = list(
        capturer.capture_group(
            CaptureCondition(exposure_ms=10.0, gain=0),
            frame_count=1,
            hardware_wait_timeout_sec=1,
            cancellation_token=CancellationToken(),
        )
    )

    assert len(frames) == 1
    assert np.array_equal(frames[0].image, image)
    assert camera.expected_frames == [1, 1]
    assert [name for name, _timeout_ms in camera.sessions[0].calls] == [
        "wait",
        "trigger",
        "retrieve",
    ]
