from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from rheed_capture.application.capture.cancellation import CancellationToken
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.workers import recording_service
from rheed_capture.presentation.qt.workers.recording_service import (
    RecordingService,
    RecordingSettings,
)

if TYPE_CHECKING:
    import pytest


def test_recording_service_uses_storage_root_name_as_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RecordingServiceがStorage root名をsample名としてSessionへ渡す。"""
    camera = MagicMock(spec=CameraDevice)
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("STO")
    storage.start_recording_session.return_value.dir_name = "record-1"

    class _Capture:
        """RecordingCaptureの実行を抑止するテスト用差し替えクラス。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            """依存引数を受け取るだけで保持しない。"""

        def run(self, cancellation_token: CancellationToken, *, hooks: object) -> None:
            """撮影処理を実行せず即時終了する。"""

    monkeypatch.setattr(recording_service, "RecordingCapture", _Capture)

    service = RecordingService(
        camera,
        storage,
        RecordingSettings(
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=100.0,
            duration_ms=None,
        ),
    )

    assert service._run_recording_capture(CancellationToken()) == "record-1"  # noqa: SLF001
    storage.start_recording_session.assert_called_once_with(
        sample_name="STO",
        exposure_ms=50.0,
        gain=0,
        rate_mode="interval",
        target_interval_ms=100.0,
        duration_ms=None,
    )
