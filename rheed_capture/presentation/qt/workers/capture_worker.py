from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal, Slot

from rheed_capture.application.capture.cancellation import CancellationToken

if TYPE_CHECKING:
    from collections.abc import Callable


class CaptureWorker(QThread):
    progress_updated = Signal(object)
    frame_captured = Signal(object)
    finished = Signal(bool, str)
    error_occurred = Signal(str)
    preview_pause_requested = Signal()
    preview_resume_requested = Signal()

    def __init__(
        self,
        run_capture: Callable[[CancellationToken], str],
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._run_capture = run_capture
        self._token = CancellationToken()
        self._preview_pause_event = threading.Event()

    def run(self) -> None:
        success = False
        saved_dir_name = ""
        try:
            saved_dir_name = self._run_capture(self._token)
            success = True
        except InterruptedError as e:
            self.error_occurred.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.error_occurred.emit(str(e))
        finally:
            self.finished.emit(success, saved_dir_name)

    def cancel(self) -> None:
        self._token.cancel()

    def request_preview_resume(self) -> None:
        self.preview_resume_requested.emit()

    def request_preview_pause(self, timeout_sec: float) -> None:
        self._preview_pause_event.clear()
        self.preview_pause_requested.emit()

        if self._preview_pause_event.wait(timeout_sec):
            return

        msg = "撮影前にプレビューを停止できませんでした。"
        raise TimeoutError(msg)

    @Slot()
    def notify_preview_paused(self) -> None:
        self._preview_pause_event.set()
