"""取得統計をstatus bar表示用文字列へ変換する。"""

from rheed_capture.domain.acquisition_statistics import AcquisitionStatistics

DECIMAL_BYTES_PER_MEGABYTE = 1_000_000


def format_preview_statistics(statistics: AcquisitionStatistics) -> str:
    """PreviewのCurrent FPSと任意のPayloadを整形する。"""
    current_fps = _format_fps(statistics.current_fps)
    text = f"Preview {current_fps} fps"
    return _append_payload(text, statistics.payload_bytes_per_second)


def format_recording_statistics(statistics: AcquisitionStatistics) -> str:
    """RecordingのCurrent、Average FPSと任意のPayloadを整形する。"""
    current_fps = _format_fps(statistics.current_fps)
    average_fps = _format_fps(statistics.average_fps)
    text = f"Recording {current_fps} fps | Avg {average_fps} fps"
    return _append_payload(text, statistics.payload_bytes_per_second)


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
