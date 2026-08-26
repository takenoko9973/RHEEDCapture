"""取得統計のstatus bar表示文字列を検証する。"""

from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics
from rheed_capture.presentation.qt.preview.processor import PreviewDiagnostics
from rheed_capture.presentation.qt.viewmodels.acquisition_statistics import (
    format_preview_statistics,
    format_recording_statistics,
)


def test_preview_statistics_format_with_payload() -> None:
    """Preview summaryはCurrent FPSと10進MB/sの転送量を表示する。"""
    statistics = AcquisitionStatistics(
        current_fps=138.44,
        average_fps=None,
        frame_count=10,
        payload_bytes_per_second=80_650_000.0,
    )

    assert (
        format_preview_statistics(statistics)
        == "Preview | Camera 138.4 fps | 80.7 MB/s"
    )


def test_preview_statistics_format_without_samples_or_payload() -> None:
    """Preview summaryは未定義FPSを`--`とし、未知転送量を省略する。"""
    statistics = AcquisitionStatistics(
        current_fps=None,
        average_fps=None,
        frame_count=0,
        payload_bytes_per_second=None,
    )

    assert (
        format_preview_statistics(statistics)
        == "Preview | Camera -- fps"
    )


def test_recording_statistics_format_with_payload() -> None:
    """Recording summaryはCurrent FPS、転送量、current save queueを表示する。"""
    statistics = AcquisitionStatistics(
        current_fps=138.44,
        average_fps=136.86,
        frame_count=100,
        payload_bytes_per_second=80_650_000.0,
        save_queue_depth=12,
        save_queue_peak_depth=34,
    )

    formatted = format_recording_statistics(statistics)

    assert formatted == "Recording | Camera 138.4 fps | 80.7 MB/s | Save Q 12"
    assert "136.9" not in formatted
    assert "34" not in formatted


def test_recording_statistics_format_without_samples_or_payload() -> None:
    """Recording summaryは未定義FPSを`--`とし、未知転送量を省略する。"""
    statistics = AcquisitionStatistics(
        current_fps=None,
        average_fps=None,
        frame_count=0,
        payload_bytes_per_second=None,
        save_queue_depth=0,
        save_queue_peak_depth=0,
    )

    assert (
        format_recording_statistics(statistics)
        == "Recording | Camera -- fps | Save Q 0"
    )


def test_preview_statistics_format_shows_accumulation_and_waiting_state() -> None:
    """積算進捗とHardware trigger待機状態をsummaryへ追加する。"""
    statistics = AcquisitionStatistics(
        current_fps=10.0,
        average_fps=10.0,
        frame_count=3,
        payload_bytes_per_second=None,
        accumulation_progress=1,
        accumulation_target=4,
        waiting_for_trigger=True,
    )

    assert format_preview_statistics(statistics) == (
        "Preview | Camera 10.0 fps | Acc 1/4"
        " | Waiting for trigger"
    )


def test_statistics_format_shows_drop_totals_only_when_nonzero() -> None:
    """Preview/Graph dropがある場合だけsummaryへ合計を表示する。"""
    statistics = AcquisitionStatistics(
        current_fps=10.0,
        average_fps=None,
        frame_count=3,
        payload_bytes_per_second=None,
    )
    diagnostics = PreviewDiagnostics(
        preview_processing_fps=10.0,
        graph_processing_fps=10.0,
        preview_display_fps=10.0,
        graph_display_fps=10.0,
        active_display_hz=60.0,
        preview_processed_frames=3,
        graph_processed_frames=3,
        preview_display_frames=3,
        graph_display_frames=3,
        preview_input_drop_count=2,
        graph_input_drop_count=0,
        preview_result_drop_count=1,
        graph_result_drop_count=4,
    )

    assert format_preview_statistics(statistics, diagnostics) == (
        "Preview | Camera 10.0 fps | Drops P/G 3/4"
    )
