from datetime import datetime

import numpy as np
from pytestqt.qtbot import QtBot

from rheed_capture.application.capture.frame_capturer import CapturedFrame, CaptureTiming
from rheed_capture.application.ports.camera import FrameReadback
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.presentation.qt.preview.processor import PreviewPipeline


def test_preview_pipeline_processes_raw_ndarray(qtbot: QtBot) -> None:
    pipeline = PreviewPipeline()
    raw = np.arange(16, dtype=np.uint16).reshape(4, 4) << 8
    images: list[np.ndarray] = []
    pipeline.image_ready.connect(images.append)
    pipeline.start()

    try:
        pipeline.process_frame(raw)
        qtbot.waitUntil(pipeline.poll_results, timeout=1000)
    finally:
        pipeline.stop()

    image = images[0]
    assert image.dtype == np.uint8
    assert image.shape == raw.shape


def test_preview_pipeline_processes_captured_frame(qtbot: QtBot) -> None:
    pipeline = PreviewPipeline()
    frame = CapturedFrame(
        image=np.ones((4, 4), dtype=np.uint16) << 8,
        condition=CaptureCondition(exposure_ms=10.0, gain=0),
        readback=FrameReadback(
            exposure_ms=10.0,
            gain=0,
            camera_timestamp_ticks=100,
            camera_timestamp_frequency_hz=125_000_000,
            source="camera",
        ),
        timing=CaptureTiming(
            trigger_issued_at=datetime.fromisoformat("2026-06-17T00:00:00+09:00"),
            trigger_issued_monotonic_sec=1.0,
        ),
    )

    images: list[np.ndarray] = []
    pipeline.image_ready.connect(images.append)
    pipeline.start()
    try:
        pipeline.process_frame(frame)
        qtbot.waitUntil(pipeline.poll_results, timeout=1000)
    finally:
        pipeline.stop()

    assert len(images) == 1
