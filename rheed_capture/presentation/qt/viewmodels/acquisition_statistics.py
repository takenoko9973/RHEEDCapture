"""取得統計をstatus bar表示用文字列へ変換する。"""

from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics

DECIMAL_BYTES_PER_MEGABYTE = 1_000_000


def format_preview_statistics(statistics: AcquisitionStatistics) -> str:
    """PreviewのRaw count、Raw FPS、積算進捗、待機状態を整形する。"""
    text = _format_acquisition_status("Preview", statistics)
    return _append_payload(text, statistics.payload_bytes_per_second)


def format_recording_statistics(statistics: AcquisitionStatistics) -> str:
    """RecordingのRaw count、Raw FPS、積算進捗、待機状態を整形する。"""
    text = _format_acquisition_status("Recording", statistics)
    return _append_payload(text, statistics.payload_bytes_per_second)


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
