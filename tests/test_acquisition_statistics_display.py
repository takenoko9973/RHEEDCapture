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
        == "Preview 138.4 fps | Payload 80.7 MB/s"
    )


def test_preview_statistics_format_without_samples_or_payload() -> None:
    """Previewの未定義FPSは`--`とし、未知Payloadは省略する。"""
    statistics = AcquisitionStatistics(
        current_fps=None,
        average_fps=None,
        frame_count=0,
        payload_bytes_per_second=None,
    )

    assert format_preview_statistics(statistics) == "Preview -- fps"


def test_recording_statistics_format_with_payload() -> None:
    """RecordingはCurrent、Average FPSとPayloadを表示する。"""
    statistics = AcquisitionStatistics(
        current_fps=138.44,
        average_fps=136.86,
        frame_count=100,
        payload_bytes_per_second=80_650_000.0,
    )

    assert format_recording_statistics(statistics) == (
        "Recording 138.4 fps | Avg 136.9 fps | Payload 80.7 MB/s"
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
        == "Recording -- fps | Avg -- fps"
    )
