from __future__ import annotations

from typing import Self

import numpy as np
import pytest

from rheed_capture.application.capture import frame_capturer as frame_capturer_module
from rheed_capture.application.capture.frame_capturer import FrameCapturer
from rheed_capture.application.ports.camera import CameraError, CameraFrame
from rheed_capture.domain.capture_condition import CaptureCondition


class _FakeSoftwareTriggerSession:
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

    def execute_trigger(self) -> None:
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
        self.sessions: list[_FakeSoftwareTriggerSession] = []

    def set_exposure(self, exposure_ms: float) -> None:
        """設定された露光時間を記録する。"""
        self.exposures.append(exposure_ms)

    def set_gain(self, gain: int) -> None:
        """設定されたGainを記録する。"""
        self.gains.append(gain)

    def start_software_trigger_session(
        self,
        *,
        expected_frames: int | None,
    ) -> _FakeSoftwareTriggerSession:
        """次の結果を持つ新しいSessionを作成する。"""
        self.expected_frames.append(expected_frames)
        session = _FakeSoftwareTriggerSession(self.results.pop(0))
        self.sessions.append(session)
        return session


def _camera_frame(image: np.ndarray, ticks: int = 10) -> CameraFrame:
    """テスト用のCameraFrameを生成する。"""
    return CameraFrame(
        image=image,
        camera_timestamp_ticks=ticks,
        camera_timestamp_frequency_hz=125_000_000,
    )


def test_frame_capturer_captures_once_and_sets_camera_condition() -> None:
    """条件適用後にready、trigger、retrieveの順で1枚取得する。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([_camera_frame(image)])
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    captured = capturer.capture(CaptureCondition(exposure_ms=10.5, gain=2))

    assert np.array_equal(captured.image, image)
    assert captured.condition.exposure_ms == 10.5
    assert captured.camera_timestamp_ticks == 10
    assert captured.camera_timestamp_frequency_hz == 125_000_000
    assert camera.exposures == [10.5]
    assert camera.gains == [2]
    assert camera.expected_frames == [1]
    assert [name for name, _ in camera.sessions[0].calls] == [
        "wait",
        "trigger",
        "retrieve",
    ]
    assert camera.sessions[0].closed


def test_frame_capturer_retries_with_new_session() -> None:
    """取得失敗後は異常Sessionを閉じ、新しいSessionで同じフレームを再撮影する。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([CameraError("temporary"), _camera_frame(image)])
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    captured = capturer.capture(CaptureCondition(exposure_ms=20.0, gain=1))

    assert np.array_equal(captured.image, image)
    assert camera.expected_frames == [1, 1]
    assert len(camera.sessions) == 2
    assert all(session.closed for session in camera.sessions)


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

    captured = capturer.capture(CaptureCondition(exposure_ms=10.0, gain=0))

    wait_timeout = camera.sessions[0].calls[0][1]
    retrieve_timeout = camera.sessions[0].calls[2][1]
    assert wait_timeout is not None
    assert retrieve_timeout is not None
    assert 409 <= wait_timeout <= 411
    assert 209 <= retrieve_timeout <= 211
    assert retrieve_timeout < wait_timeout
    assert captured.timestamp


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
