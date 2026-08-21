from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from rheed_capture.application.capture.cancellation import CancellationToken
from rheed_capture.domain.acquisition_statistics import (
    AcquisitionSample,
    AcquisitionStatistics,
)
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.infrastructure.config.schema import AcquisitionSettings
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.workers import recording_service
from rheed_capture.presentation.qt.workers.recording_service import (
    RecordingService,
    RecordingSettings,
)

if TYPE_CHECKING:
    from rheed_capture.application.capture.recording import RecordingHooks


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
    assert service.statistics_snapshot() is None


def test_recording_service_measures_captured_frames_not_saved_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保存通知とSession境界ではなく、正常取得フレームを累計する。"""
    camera = MagicMock(spec=CameraDevice)
    camera.take_acquisition_sample.side_effect = [
        AcquisitionSample(timestamp=10.1, payload_bytes=1000),
        AcquisitionSample(timestamp=10.6, payload_bytes=1000),
    ]
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("STO")
    storage.start_recording_session.return_value.dir_name = "record-1"
    observed_statistics: list[AcquisitionStatistics] = []

    class _Capture:
        """正常取得と保存通知の順序を制御するRecordingCapture double。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            """依存引数はテスト対象外なので保持しない。"""

        def run(
            self,
            cancellation_token: CancellationToken,
            *,
            hooks: RecordingHooks,
        ) -> None:
            """保存通知を増やしても取得統計が増えないことを観測する。"""
            del cancellation_token
            recording_hooks = hooks
            assert recording_hooks.on_saved_frames_changed is not None
            recording_hooks.on_saved_frames_changed(1)
            recording_hooks.on_saved_frames_changed(2)
            assert recording_hooks.on_frame_captured is not None
            frame = MagicMock()
            frame.image = object()
            recording_hooks.on_frame_captured(frame)
            recording_hooks.on_frame_captured(frame)
            statistics = service.statistics_snapshot()
            assert statistics is not None
            observed_statistics.append(statistics)

    monkeypatch.setattr(recording_service, "RecordingCapture", _Capture)
    monotonic_times = iter([10.0, 10.6])
    monkeypatch.setattr(
        recording_service.time,
        "perf_counter",
        lambda: next(monotonic_times),
    )
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

    assert len(observed_statistics) == 1
    statistics = observed_statistics[0]
    assert statistics.current_fps == pytest.approx(2.0)
    assert statistics.average_fps == pytest.approx(2 / 0.6)
    assert statistics.frame_count == 2
    assert statistics.payload_bytes_per_second == pytest.approx(4000.0)
    assert service.statistics_snapshot() is None


def test_recording_service_clears_statistics_after_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recording例外終了後も取得統計を非表示状態へ戻す。"""
    camera = MagicMock(spec=CameraDevice)
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("STO")
    storage.start_recording_session.return_value.dir_name = "record-1"

    class _Capture:
        """Recording実行中の例外を再現するdouble。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            """依存引数は保持しない。"""

        def run(
            self,
            cancellation_token: CancellationToken,
            *,
            hooks: RecordingHooks,
        ) -> None:
            """Recording失敗を送出する。"""
            del cancellation_token, hooks
            msg = "recording failed"
            raise RuntimeError(msg)

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

    with pytest.raises(RuntimeError, match="recording failed"):
        service._run_recording_capture(CancellationToken())  # noqa: SLF001

    assert service.statistics_snapshot() is None


def test_recording_service_rejects_software_rate_above_fps_limit_before_storage() -> None:
    """Softwareの要求rateがFPS Limit超過ならSession作成前に失敗する。"""
    camera = MagicMock(spec=CameraDevice)
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("STO")
    service = RecordingService(
        camera,
        storage,
        RecordingSettings(
            exposure_ms=10.0,
            gain=0,
            rate_mode="fps",
            target_interval_ms=10.0,
            duration_ms=None,
        ),
        AcquisitionSettings(mode="software", fps_limit=50.0),
    )

    with pytest.raises(ValueError, match="FPS Limit"):
        service._run_recording_capture(CancellationToken())  # noqa: SLF001

    storage.start_recording_session.assert_not_called()
