from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

from rheed_capture.application.capture.frame_capturer import CapturedFrame, CaptureTiming
from rheed_capture.application.ports.camera import FrameReadback
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.domain.image_processor import ImageProcessor
from rheed_capture.presentation.qt.preview.processor import (
    LatestOnlyProcessor,
    PreviewPipeline,
)

if TYPE_CHECKING:
    import pytest
    from pytestqt.qtbot import QtBot


def _captured_frame() -> CapturedFrame:
    """Preview処理へ渡すCapturedFrameを作る。"""
    return CapturedFrame(
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


def test_latest_only_processor_replaces_busy_input_without_blocking(qtbot: QtBot) -> None:
    """処理中の中間Rawを捨て、submitをworker待ちにしない。"""
    first_started = threading.Event()
    release_first = threading.Event()
    processed: list[int] = []

    def slow_process(value: int) -> int:
        """1件目だけ停止して、mailbox置換を決定的にする。"""
        processed.append(value)
        if value == 1:
            first_started.set()
            assert release_first.wait(1.0)
        return value

    processor = LatestOnlyProcessor(slow_process, name="test-latest-only")
    processor.start()
    try:
        assert processor.submit(1)
        assert first_started.wait(1.0)

        started_at = time.perf_counter()
        assert processor.submit(2)
        assert processor.submit(3)
        submit_elapsed = time.perf_counter() - started_at

        assert submit_elapsed < 0.2
        assert processor.input_pending_count == 1
        assert processor.input_drop_count == 1

        release_first.set()
        qtbot.waitUntil(lambda: processor.processed_count == 2, timeout=1000)
        assert processed == [1, 3]
    finally:
        release_first.set()
        processor.stop()


def test_latest_only_processor_reset_ignores_inflight_old_generation(
    qtbot: QtBot,
) -> None:
    """reset後に新規submitがなくてもreset前入力の完了をrateへ記録しない。"""
    first_started = threading.Event()
    release_first = threading.Event()

    def slow_process(value: int) -> int:
        """1件目を止め、reset時点のbusyとpendingを同時に作る。"""
        if value == 1:
            first_started.set()
            assert release_first.wait(1.0)
        else:
            time.sleep(0.02)
        return value

    processor = LatestOnlyProcessor(slow_process, name="test-rate-generation")
    processor.start()
    try:
        assert processor.submit(1)
        assert first_started.wait(1.0)
        assert processor.busy
        assert processor.submit(2)
        assert processor.input_pending_count == 1

        processor.reset_rate()
        release_first.set()
        qtbot.waitUntil(lambda: processor.processed_count == 2, timeout=1000)

        assert processor.processing_fps == 0.0
    finally:
        release_first.set()
        processor.stop()


def test_latest_only_processor_keeps_only_latest_unpolled_result(qtbot: QtBot) -> None:
    """GUIが結果を読む前に新結果が完成しても、古い結果を蓄積しない。"""
    first_started = threading.Event()
    release_first = threading.Event()

    def slow_process(value: int) -> int:
        """1件目の完了を遅延させる。"""
        if value == 1:
            first_started.set()
            assert release_first.wait(1.0)
        return value

    processor = LatestOnlyProcessor(slow_process, name="test-result-latest-only")
    processor.start()
    try:
        assert processor.submit(1)
        assert first_started.wait(1.0)
        assert processor.submit(2)
        assert processor.submit(3)

        release_first.set()
        qtbot.waitUntil(lambda: processor.processed_count == 2, timeout=1000)
        assert processor.result_pending_count == 1
        assert processor.take_latest_result() == 3
        assert processor.take_latest_result() is None
    finally:
        release_first.set()
        processor.stop()


def test_preview_pipeline_processes_raw_and_captured_frame(qtbot: QtBot) -> None:
    """Raw ndarrayとCapturedFrameを独立処理へ投入して表示結果を通知する。"""
    pipeline = PreviewPipeline()
    images: list[np.ndarray] = []
    histograms: list[tuple[np.ndarray, float, float]] = []
    pipeline.image_ready.connect(images.append)
    pipeline.histogram_ready.connect(
        lambda histogram, mean, std: histograms.append((histogram, mean, std))
    )
    pipeline.start()
    try:
        raw = np.arange(16, dtype=np.uint16).reshape(4, 4) << 8
        assert pipeline.submit_frame(raw)
        qtbot.waitUntil(pipeline.poll_results, timeout=1000)

        assert images[-1].dtype == np.uint8
        assert images[-1].shape == raw.shape
        assert len(histograms) == 1

        assert pipeline.submit_frame(_captured_frame())
        qtbot.waitUntil(pipeline.poll_results, timeout=1000)
        assert len(images) == 2
        assert len(histograms) == 2
    finally:
        pipeline.stop()


def test_slow_preview_processing_does_not_block_graph_processing(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLAHE等の遅いPreview処理中もGraph処理を完了できる。"""
    preview_started = threading.Event()
    release_preview = threading.Event()
    original_to_8bit = ImageProcessor.to_8bit_preview

    def slow_to_8bit(image: np.ndarray) -> np.ndarray:
        """Preview側だけを停止する。"""
        preview_started.set()
        assert release_preview.wait(1.0)
        return original_to_8bit(image)

    monkeypatch.setattr(ImageProcessor, "to_8bit_preview", slow_to_8bit)
    pipeline = PreviewPipeline()
    histograms: list[tuple[np.ndarray, float, float]] = []
    pipeline.histogram_ready.connect(
        lambda histogram, mean, std: histograms.append((histogram, mean, std))
    )
    pipeline.start()
    try:
        assert pipeline.submit_frame(np.ones((4, 4), dtype=np.uint16) << 8)
        assert preview_started.wait(1.0)
        qtbot.waitUntil(
            lambda: pipeline.diagnostics_snapshot().graph_processed_frames >= 1,
            timeout=1000,
        )

        assert pipeline.poll_results()
        assert len(histograms) == 1
        assert pipeline.diagnostics_snapshot().preview_display_frames == 0
    finally:
        release_preview.set()
        pipeline.stop()


def test_preview_pipeline_emits_only_latest_result_when_display_is_slow(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """表示pollが遅れてもPreviewとGraphの未表示結果をFIFO蓄積しない。"""
    preview_started = threading.Event()
    release_preview = threading.Event()
    original_to_8bit = ImageProcessor.to_8bit_preview

    def slow_first_preview(image: np.ndarray) -> np.ndarray:
        """最初のPreview処理だけ停止して、次のRawをmailboxへ残す。"""
        if not preview_started.is_set():
            preview_started.set()
            assert release_preview.wait(1.0)
        return original_to_8bit(image)

    monkeypatch.setattr(ImageProcessor, "to_8bit_preview", slow_first_preview)
    pipeline = PreviewPipeline()
    images: list[np.ndarray] = []
    histograms: list[tuple[np.ndarray, float, float]] = []
    pipeline.image_ready.connect(images.append)
    pipeline.histogram_ready.connect(
        lambda histogram, mean, std: histograms.append((histogram, mean, std))
    )
    pipeline.start()
    try:
        for value in (1, 2, 3):
            assert pipeline.submit_frame(np.array([[value << 8]], dtype=np.uint16))
            if value == 1:
                assert preview_started.wait(1.0)

        release_preview.set()
        qtbot.waitUntil(
            lambda: pipeline.diagnostics_snapshot().preview_processed_frames >= 2,
            timeout=1000,
        )

        assert pipeline.poll_results()
        assert len(images) == 1
        assert len(histograms) == 1
        assert images[0].item() == 3
        assert histograms[0][1] == 48.0
        assert pipeline.poll_results() is False
    finally:
        release_preview.set()
        pipeline.stop()


def test_preview_pipeline_does_not_redraw_without_new_result() -> None:
    """新結果がないpollでは重い表示通知を発生させない。"""
    pipeline = PreviewPipeline()
    image_count = 0
    histogram_count = 0

    def count_image(_image: np.ndarray) -> None:
        """画像通知数を数える。"""
        nonlocal image_count
        image_count += 1

    def count_histogram(_histogram: np.ndarray, _mean: float, _std: float) -> None:
        """Graph通知数を数える。"""
        nonlocal histogram_count
        histogram_count += 1

    pipeline.image_ready.connect(count_image)
    pipeline.histogram_ready.connect(count_histogram)
    pipeline.start()
    try:
        assert pipeline.poll_results() is False
        assert image_count == 0
        assert histogram_count == 0
        assert pipeline.diagnostics_snapshot().preview_display_frames == 0
        assert pipeline.diagnostics_snapshot().graph_display_frames == 0
    finally:
        pipeline.stop()


def test_realtime_rates_reset_and_decay_after_idle(qtbot: QtBot) -> None:
    """処理・表示レートが境界で再開し、idle後に起動後平均へ戻らない。"""
    pipeline = PreviewPipeline()
    pipeline.start()

    def wait_for_frame(processed_count: int) -> None:
        """指定した処理完了数と表示通知を待つ。"""
        qtbot.waitUntil(
            lambda: pipeline.diagnostics_snapshot().preview_processed_frames
            >= processed_count,
            timeout=1000,
        )

        def poll_until_displayed() -> bool:
            """両方のlatest結果を表示へ反映する。"""
            pipeline.poll_results()
            diagnostics = pipeline.diagnostics_snapshot()
            return (
                diagnostics.preview_display_frames >= processed_count
                and diagnostics.graph_display_frames >= processed_count
            )

        qtbot.waitUntil(poll_until_displayed, timeout=1000)

    def wait_for_current_rates() -> None:
        """両processorと両表示のrolling rateが有効になるまで待つ。"""
        def rates_are_current() -> bool:
            """各経路に2件以上の直近sampleがあることを確認する。"""
            diagnostics = pipeline.diagnostics_snapshot()
            return all(
                rate > 0.0
                for rate in (
                    diagnostics.preview_processing_fps,
                    diagnostics.graph_processing_fps,
                    diagnostics.preview_display_fps,
                    diagnostics.graph_display_fps,
                )
            )

        qtbot.waitUntil(rates_are_current, timeout=1000)

    try:
        for value, processed_count in ((1, 1), (2, 2)):
            assert pipeline.submit_frame(np.array([[value << 8]], dtype=np.uint16))
            wait_for_frame(processed_count)

        wait_for_current_rates()
        active = pipeline.diagnostics_snapshot()
        assert active.preview_processing_fps > 0.0
        assert active.graph_processing_fps > 0.0
        assert active.preview_display_fps > 0.0
        assert active.graph_display_fps > 0.0

        pipeline.reset_rates()
        reset = pipeline.diagnostics_snapshot()
        assert reset.preview_processing_fps == 0.0
        assert reset.graph_processing_fps == 0.0
        assert reset.preview_display_fps == 0.0
        assert reset.graph_display_fps == 0.0

        for value, processed_count in ((3, 3), (4, 4)):
            assert pipeline.submit_frame(np.array([[value << 8]], dtype=np.uint16))
            wait_for_frame(processed_count)

        wait_for_current_rates()
        resumed = pipeline.diagnostics_snapshot()
        assert resumed.preview_processing_fps > 0.0
        assert resumed.graph_processing_fps > 0.0
        assert resumed.preview_display_fps > 0.0
        assert resumed.graph_display_fps > 0.0

        time.sleep(1.1)
        idle = pipeline.diagnostics_snapshot()
        assert idle.preview_processing_fps == 0.0
        assert idle.graph_processing_fps == 0.0
        assert idle.preview_display_fps == 0.0
        assert idle.graph_display_fps == 0.0
    finally:
        pipeline.stop()
