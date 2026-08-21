"""取得統計のstatus bar表示文字列を検証する。"""

from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics
from rheed_capture.presentation.qt.viewmodels.acquisition_statistics import (
    format_preview_statistics,
    format_recording_statistics,
)


def test_preview_statistics_format_with_payload() -> None:
    """PreviewはCurrent FPSと10進MB/sのPayloadを表示する。"""
    statistics = AcquisitionStatistics(
        current_fps=138.44,
        average_fps=None,
        frame_count=10,
        payload_bytes_per_second=80_650_000.0,
    )

    assert (
        format_preview_statistics(statistics)
        == (
            "Preview | Raw count 10 | Raw FPS 138.4 | Accumulation 0/1"
            " | Payload 80.7 MB/s"
        )
    )


def test_preview_statistics_format_without_samples_or_payload() -> None:
    """Previewの未定義FPSは`--`とし、未知Payloadは省略する。"""
    statistics = AcquisitionStatistics(
        current_fps=None,
        average_fps=None,
        frame_count=0,
        payload_bytes_per_second=None,
    )

    assert (
        format_preview_statistics(statistics)
        == "Preview | Raw count 0 | Raw FPS -- | Accumulation 0/1"
    )


def test_recording_statistics_format_with_payload() -> None:
    """RecordingはCurrent、Average FPSとPayloadを表示する。"""
    statistics = AcquisitionStatistics(
        current_fps=138.44,
        average_fps=136.86,
        frame_count=100,
        payload_bytes_per_second=80_650_000.0,
    )

    assert format_recording_statistics(statistics) == (
        "Recording | Raw count 100 | Raw FPS 138.4 | Accumulation 0/1"
        " | Payload 80.7 MB/s"
    )


def test_recording_statistics_format_without_samples_or_payload() -> None:
    """Recordingの未定義値は`--`とし、未知Payloadは省略する。"""
    statistics = AcquisitionStatistics(
        current_fps=None,
        average_fps=None,
        frame_count=0,
        payload_bytes_per_second=None,
    )

    assert (
        format_recording_statistics(statistics)
        == "Recording | Raw count 0 | Raw FPS -- | Accumulation 0/1"
    )


def test_preview_statistics_format_shows_accumulation_and_waiting_state() -> None:
    """積算進捗とHardware trigger待機状態を明示する。"""
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
        "Preview | Raw count 3 | Raw FPS 10.0 | Accumulation 1/4"
        " | Waiting for trigger"
    )
