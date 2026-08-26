"""取得統計をstatus bar表示用文字列へ変換する。"""

from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics
from rheed_capture.presentation.qt.preview.processor import PreviewDiagnostics

DECIMAL_BYTES_PER_MEGABYTE = 1_000_000


def format_preview_statistics(statistics: AcquisitionStatistics) -> str:
    """PreviewのRaw count、Raw FPS、積算進捗、待機状態を整形する。"""
    text = _format_acquisition_status("Preview", statistics)
    return _append_payload(text, statistics.payload_bytes_per_second)


def format_recording_statistics(statistics: AcquisitionStatistics) -> str:
    """RecordingのRaw count、Raw FPS、積算進捗、待機状態を整形する。"""
    text = _format_acquisition_status("Recording", statistics)
    text = _append_payload(text, statistics.payload_bytes_per_second)
    return (
        f"{text} | Save queue "
        f"{statistics.save_queue_depth}/{statistics.save_queue_peak_depth}"
    )


def format_preview_realtime_diagnostics(diagnostics: PreviewDiagnostics) -> str:
    """PreviewとGraphの処理・表示FPS、表示Hz、drop数をstatus bar用に整形する。"""
    preview_drops = (
        diagnostics.preview_input_drop_count + diagnostics.preview_result_drop_count
    )
    graph_drops = diagnostics.graph_input_drop_count + diagnostics.graph_result_drop_count
    preview_text = (
        " | Preview proc/display "
        f"{diagnostics.preview_processing_fps:.1f}/"
        f"{diagnostics.preview_display_fps:.1f} fps"
    )
    graph_text = (
        " | Graph proc/display "
        f"{diagnostics.graph_processing_fps:.1f}/"
        f"{diagnostics.graph_display_fps:.1f} fps"
    )
    return (
        "Realtime"
        f"{preview_text}"
        f"{graph_text}"
        f" | Active display {diagnostics.active_display_hz:.1f} Hz"
        f" | Drops P/G {preview_drops}/{graph_drops}"
    )


def _format_acquisition_status(
    label: str,
    statistics: AcquisitionStatistics,
) -> str:
    """取得種別共通のRaw単位ステータスを整形する。"""
    current_fps = _format_fps(statistics.current_fps)
    text = (
        f"{label} | Raw count {statistics.frame_count}"
        f" | Raw FPS {current_fps}"
        f" | Accumulation {statistics.accumulation_progress}"
        f"/{statistics.accumulation_target}"
    )
    if statistics.waiting_for_trigger:
        text += " | Waiting for trigger"
    return text


def _format_fps(value: float | None) -> str:
    """未定義FPSを`--`、定義済みFPSを小数1桁で返す。"""
    return "--" if value is None else f"{value:.1f}"


def _append_payload(text: str, payload_bytes_per_second: float | None) -> str:
    """取得可能な場合だけ10進MB/sのPayload表示を追加する。"""
    if payload_bytes_per_second is None:
        return text

    payload_megabytes_per_second = (
        payload_bytes_per_second / DECIMAL_BYTES_PER_MEGABYTE
    )
    return f"{text} | Payload {payload_megabytes_per_second:.1f} MB/s"
