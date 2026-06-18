from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from rheed_capture.application.capture.frame_capturer import FrameCapturer
from rheed_capture.application.ports.camera import CameraError
from rheed_capture.domain.capture_condition import CaptureCondition


class _FakeCamera:
    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.exposures: list[float] = []
        self.gains: list[int] = []
        self.timeouts: list[int] = []

    def set_exposure(self, exposure_ms: float) -> None:
        self.exposures.append(exposure_ms)

    def set_gain(self, gain: int) -> None:
        self.gains.append(gain)

    def grab_one(self, timeout_ms: int) -> np.ndarray | None:
        self.timeouts.append(timeout_ms)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_frame_capturer_captures_once_and_sets_camera_condition() -> None:
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([image])
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    captured = capturer.capture(CaptureCondition(exposure_ms=10.5, gain=2))

    assert np.array_equal(captured.image, image)
    assert captured.condition.exposure_ms == 10.5
    assert camera.exposures == [10.5]
    assert camera.gains == [2]
    assert camera.timeouts == [510]


def test_frame_capturer_retries_none_result() -> None:
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([None, image])
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    captured = capturer.capture(CaptureCondition(exposure_ms=20.0, gain=1))

    assert np.array_equal(captured.image, image)
    assert len(camera.timeouts) == 2


def test_frame_capturer_retries_camera_error() -> None:
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([CameraError("temporary"), image])
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    captured = capturer.capture(CaptureCondition(exposure_ms=30.0, gain=3))

    assert np.array_equal(captured.image, image)
    assert len(camera.timeouts) == 2


def test_frame_capturer_raises_after_three_failures() -> None:
    camera = _FakeCamera([None, None, None])
    capturer = FrameCapturer(camera, retry_interval_sec=0)

    with pytest.raises(RuntimeError, match="最大リトライ"):
        capturer.capture(CaptureCondition(exposure_ms=40.0, gain=4))

    assert len(camera.timeouts) == 3
