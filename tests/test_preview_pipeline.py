from datetime import datetime

import numpy as np
from pytestqt.qtbot import QtBot

from rheed_capture.application.capture.frame_capturer import CapturedFrame, CaptureTiming
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.presentation.qt.preview.processor import PreviewPipeline


def test_preview_pipeline_processes_raw_ndarray(qtbot: QtBot) -> None:
    pipeline = PreviewPipeline()
    raw = np.arange(16, dtype=np.uint16).reshape(4, 4) << 8

    with (
        qtbot.waitSignal(pipeline.image_ready, timeout=1000) as image_blocker,
        qtbot.waitSignal(pipeline.histogram_ready, timeout=1000),
    ):
        pipeline.process_frame(raw)

    assert image_blocker.args is not None
    image = image_blocker.args[0]
    assert image.dtype == np.uint8
    assert image.shape == raw.shape


def test_preview_pipeline_processes_captured_frame(qtbot: QtBot) -> None:
    pipeline = PreviewPipeline()
    frame = CapturedFrame(
        image=np.ones((4, 4), dtype=np.uint16) << 8,
        condition=CaptureCondition(exposure_ms=10.0, gain=0),
        timing=CaptureTiming(
            trigger_issued_at=datetime.fromisoformat("2026-06-17T00:00:00+09:00"),
            trigger_issued_monotonic_sec=1.0,
            exposure_started_ticks=100,
            exposure_timestamp_frequency_hz=125_000_000,
            exposure_timestamp_source="camera",
        ),
    )

    with qtbot.waitSignal(pipeline.image_ready, timeout=1000):
        pipeline.process_frame(frame)
