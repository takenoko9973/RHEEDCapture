from datetime import datetime

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.application.capture.frame_capturer import CapturedFrame, CaptureTiming
from rheed_capture.application.ports.camera import FrameReadback, ImageFormatSnapshot
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.presentation.qt.preview.processor import (
    GraphResult,
    PreviewInput,
    PreviewPipeline,
)

_IMAGE_FORMAT_12 = ImageFormatSnapshot(12, 16, "Mono12Packed", "MsbAligned")


def test_preview_pipeline_processes_raw_ndarray(qtbot: QtBot) -> None:
    pipeline = PreviewPipeline()
    raw = np.arange(16, dtype=np.uint16).reshape(4, 4) << 8
    images: list[np.ndarray] = []
    pipeline.image_ready.connect(images.append)
    pipeline.start()

    try:
        pipeline.process_frame(PreviewInput(raw, _IMAGE_FORMAT_12))
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
        image_format=_IMAGE_FORMAT_12,
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


def test_graph_label_matches_the_depth_of_the_polled_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非同期Graph結果のdepthとHistogram labelを同じ更新境界で通知する。"""
    pipeline = PreviewPipeline()
    graph_results = iter(
        (
            GraphResult(np.zeros(256, dtype=np.int64), 0.0, 0.0, 12),
            GraphResult(np.zeros(256, dtype=np.int64), 0.0, 0.0, 8),
        )
    )
    monkeypatch.setattr(
        pipeline.graph_processor,
        "take_latest_result",
        lambda: next(graph_results, None),
    )
    monkeypatch.setattr(pipeline.preview_processor, "take_latest_result", lambda: None)

    label_depths: list[int] = []
    histogram_label_depths: list[int] = []
    pipeline.image_format_changed.connect(label_depths.append)
    pipeline.histogram_ready.connect(
        lambda _histogram, _mean, _std: histogram_label_depths.append(label_depths[-1])
    )

    try:
        assert pipeline.submit_frame(
            PreviewInput(
                np.array([[0]], dtype=np.uint16),
                ImageFormatSnapshot(12, 16, "Mono12Packed", "MsbAligned"),
            )
        )
        assert pipeline.submit_frame(
            PreviewInput(
                np.array([[0]], dtype=np.uint8),
                ImageFormatSnapshot(8, 8, "Mono8", None),
            )
        )
        assert label_depths == []

        assert pipeline.poll_results()
        assert pipeline.poll_results()
    finally:
        pipeline.stop()

    assert histogram_label_depths == [12, 8]
