from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from rheed_capture.application.capture.angle_scan import (
    AngleScanCapture,
    AngleScanHooks,
    build_angle_scan_document_from_conditions,
)
from rheed_capture.application.capture.angle_scan import (
    AngleScanSettings as ApplicationAngleScanSettings,
)
from rheed_capture.application.capture.frame_capturer import (
    DEFAULT_CAPTURE_RETRY_LIMIT,
    FrameCapturer,
)
from rheed_capture.presentation.qt.workers.capture_worker import CaptureWorker

if TYPE_CHECKING:
    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.application.ports.motor import RotationMotor
    from rheed_capture.domain.capture_condition import CaptureCondition
    from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
    from rheed_capture.infrastructure.config.schema import AcquisitionSettings
    from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AngleScanSettings(ApplicationAngleScanSettings):
    preview_pause_timeout: float = 5.0


class AngleScanService(CaptureWorker):
    """AngleScanCaptureをQtスレッド上で実行するService。"""

    progress_update = Signal(int, int, float)
    scan_finished = Signal(bool, str)

    def __init__(
        self,
        camera_device: CameraDevice,
        storage: ExperimentStorage,
        motor: RotationMotor,
        conditions: list[CaptureCondition],
        settings: AngleScanSettings,
        acquisition_settings: AcquisitionSettings,
        parent: QObject | None = None,
    ) -> None:
        self.camera = camera_device
        self.storage = storage
        self.motor = motor
        self.settings = settings
        # 開始後にUI側の選択が変わっても、今回のscan.jsonと撮影条件は固定する。
        self._conditions = list(conditions)
        self.max_retries = DEFAULT_CAPTURE_RETRY_LIMIT
        self._trigger_settings = acquisition_settings.to_trigger_settings()
        self._accumulation_frames = (
            acquisition_settings.accumulation_frames
            if acquisition_settings.accumulation_enabled
            else 1
        )
        self._trigger_wait_timeout_sec = acquisition_settings.trigger_wait_timeout_sec
        # scan.jsonはセッション開始時に必要なため、角度計画と条件を事前に文書化する。
        self._scan_document = build_angle_scan_document_from_conditions(
            settings=self.settings,
            conditions=self._conditions,
            retry_limit=self.max_retries,
            accumulation_frames=self._accumulation_frames,
        )
        super().__init__(self._run_angle_scan_capture, parent=parent)
        self.finished.connect(self.scan_finished)

    def _run_angle_scan_capture(self, cancellation_token: CancellationToken) -> str:
        logger.info("角度走査撮影を開始します...")

        session = self.storage.start_angle_scan_session(self._scan_document)
        # Application層には解決済み条件だけを渡す。
        capture = AngleScanCapture(
            FrameCapturer(
                self.camera,
                trigger_settings=self._trigger_settings,
                max_retries=self.max_retries,
            ),
            session,
            self.motor,
            self._conditions,
            self.settings,
            accumulation_frames=self._accumulation_frames,
            trigger_wait_timeout_sec=self._trigger_wait_timeout_sec,
        )
        capture.run(
            cancellation_token,
            hooks=AngleScanHooks(
                on_motion_started=self.request_preview_resume,
                before_capture_batch=lambda: self.request_preview_pause(
                    self.settings.preview_pause_timeout
                ),
                on_progress=self.progress_update.emit,
                on_frame_captured=self.frame_captured.emit,
            ),
        )

        logger.info("角度走査撮影が正常に完了しました。")
        return str(session.dir_name)
