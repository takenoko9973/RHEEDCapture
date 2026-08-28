"""取得統計をstatus bar表示用文字列へ変換する。"""

from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics
from rheed_capture.presentation.qt.preview.processor import PreviewDiagnostics

DECIMAL_BYTES_PER_MEGABYTE = 1_000_000


def format_preview_statistics(
    statistics: AcquisitionStatistics,
    diagnostics: PreviewDiagnostics | None = None,
) -> str:
    """Previewの短いstatus summaryを整形する。"""
    return _format_summary(
        "Preview",
        statistics,
        diagnostics=diagnostics,
        include_save_queue=False,
    )


def format_recording_statistics(
    statistics: AcquisitionStatistics,
    diagnostics: PreviewDiagnostics | None = None,
) -> str:
    """Recordingの短いstatus summaryを整形する。"""
    return _format_summary(
        "Recording",
        statistics,
        diagnostics=diagnostics,
        include_save_queue=True,
    )


def _format_summary(
    label: str,
    statistics: AcquisitionStatistics,
    *,
    diagnostics: PreviewDiagnostics | None,
    include_save_queue: bool,
) -> str:
    """取得種別共通の短いsummary項目を整形する。"""
    parts = [label, f"Camera {_format_fps(statistics.current_fps)} fps"]
    text = " | ".join(parts)
    text = _append_payload(text, statistics.payload_bytes_per_second)
    if statistics.accumulation_target > 1:
        text += (
            f" | Acc {statistics.accumulation_progress}"
            f"/{statistics.accumulation_target}"
        )
    if statistics.waiting_for_trigger:
        text += " | Waiting for trigger"
    if include_save_queue:
        text += f" | Save Q {statistics.save_queue_depth}"
    if diagnostics is not None:
        preview_drops = (
            diagnostics.preview_input_drop_count + diagnostics.preview_result_drop_count
        )
        graph_drops = diagnostics.graph_input_drop_count + diagnostics.graph_result_drop_count
        if preview_drops > 0 or graph_drops > 0:
            text += f" | Drops P/G {preview_drops}/{graph_drops}"
    return text


def _format_fps(value: float | None) -> str:
    """未定義FPSを`--`、定義済みFPSを小数1桁で返す。"""
    return "--" if value is None else f"{value:.1f}"


def _append_payload(text: str, payload_bytes_per_second: float | None) -> str:
    """取得可能な場合だけ10進MB/sの転送量表示を追加する。"""
    if payload_bytes_per_second is None:
        return text

    payload_megabytes_per_second = (
        payload_bytes_per_second / DECIMAL_BYTES_PER_MEGABYTE
    )
    return f"{text} | {payload_megabytes_per_second:.1f} MB/s"
