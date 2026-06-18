from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from rheed_capture.application.capture.frame_capturer import CapturedFrame
    from rheed_capture.data_formats.angle_scan_document import AngleScanDocument


class SequenceSession(Protocol):
    dir_name: str

    def save_frame(self, captured_frame: CapturedFrame) -> object:
        ...


class AngleScanSession(Protocol):
    scan_id: str
    dir_name: str

    def save_frame(self, captured_frame: CapturedFrame, target_angle_deg: float) -> object:
        ...


class CaptureStorage(Protocol):
    def start_sequence_session(self) -> SequenceSession:
        ...

    def start_angle_scan_session(self, scan_document: AngleScanDocument) -> AngleScanSession:
        ...
