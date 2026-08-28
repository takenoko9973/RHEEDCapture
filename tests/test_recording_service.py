from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import numpy as np
import pytest

from rheed_capture.application.capture.cancellation import CancellationToken
from rheed_capture.application.capture.save_worker import SaveQueueTelemetry, SaveRequest
from rheed_capture.application.ports.camera import ImageFormatSnapshot
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
    from rheed_capture.infrastructure.storage.async_tiff_save_worker import (
        AsyncTiffSaveWorker,
    )


def _camera() -> MagicMock:
    """画像形式snapshotを返すRecording用camera mockを作る。"""
    camera = MagicMock(spec=CameraDevice)
    camera.configure_image_format.return_value = ImageFormatSnapshot(
        12,
        16,
        "Mono12Packed",
        "MsbAligned",
    )
    return camera


def test_recording_service_uses_storage_root_name_as_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RecordingServiceがStorage root名をsample名としてSessionへ渡す。"""
    camera = _camera()
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
        tiff_compression_enabled=True,
        image_format=camera.configure_image_format.return_value,
    )
    assert service.statistics_snapshot() is None


def test_recording_service_measures_captured_frames_not_saved_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保存通知とSession境界ではなく、正常取得フレームを累計する。"""
    camera = _camera()
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
            tiff_compression_enabled=True,
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
    camera = _camera()
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
    camera = _camera()
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


def test_recording_service_passes_compression_setting_to_storage_and_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recording圧縮booleanをSessionとRecordingCaptureへ同じ値で渡す。"""
    camera = _camera()
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("STO")
    storage.start_recording_session.return_value.dir_name = "record-1"
    capture_settings: list[RecordingSettings] = []

    class _Capture:
        """Recording設定の伝播だけを観測するdouble。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            """RecordingCaptureの設定引数を保持する。"""
            del kwargs
            capture_settings.append(cast("RecordingSettings", args[3]))

        def run(self, cancellation_token: CancellationToken, *, hooks: object) -> None:
            """撮影を実行せず即時終了する。"""
            del cancellation_token, hooks

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
            tiff_compression_enabled=False,
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
        tiff_compression_enabled=False,
        image_format=camera.configure_image_format.return_value,
    )
    assert capture_settings[0].tiff_compression_enabled is False


def test_recording_service_exposes_save_queue_depth_in_statistics_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recording中のqueue current/peakを既存統計snapshotへ伝播する。"""
    camera = _camera()
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("STO")
    storage.start_recording_session.return_value.dir_name = "record-1"
    observed: list[AcquisitionStatistics] = []

    class _Capture:
        """保存workerへ要求を入れて統計境界を観測するdouble。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            """注入された保存workerを保持する。"""
            del args
            self.save_worker = kwargs["save_worker"]

        def run(
            self,
            cancellation_token: CancellationToken,
            *,
            hooks: RecordingHooks,
        ) -> None:
            """未開始workerへ要求を入れ、Recording統計を取得する。"""
            del cancellation_token, hooks
            save_worker = cast("AsyncTiffSaveWorker", self.save_worker)
            save_worker.enqueue(
                SaveRequest(
                    file_path=Path("frame.tiff"),
                    image=np.zeros((2, 2), dtype=np.uint16),
                    metadata={},
                )
            )
            statistics = service.statistics_snapshot()
            assert statistics is not None
            observed.append(statistics)

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

    assert observed[0].save_queue_depth == 1
    assert observed[0].save_queue_peak_depth == 1


def test_recording_service_statistics_snapshot_reads_save_worker_once() -> None:
    """統計snapshotがworker参照を一度だけ読み、poll中の差替えで壊れない。"""

    class _WorkerReadRaceService(RecordingService):
        """worker属性の二度目の参照をNoneにする競合再現用Service。"""

        def __init__(
            self,
            camera_device: CameraDevice,
            storage: ExperimentStorage,
            settings: RecordingSettings,
        ) -> None:
            """競合再現フラグを初期化して親Serviceを作る。"""
            self._drop_worker_after_first_read = False
            self._worker_reads = 0
            super().__init__(camera_device, storage, settings)

        def __getattribute__(self, name: str) -> object:
            """workerの二度読みだけを再現して他の属性は通常取得する。"""
            if name == "_save_worker":
                attributes = object.__getattribute__(self, "__dict__")
                if attributes.get("_drop_worker_after_first_read", False):
                    reads = attributes["_worker_reads"]
                    attributes["_worker_reads"] = reads + 1
                    if reads > 0:
                        return None
            return super().__getattribute__(name)

    service = _WorkerReadRaceService(
        MagicMock(spec=CameraDevice),
        MagicMock(spec=ExperimentStorage),
        RecordingSettings(
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=100.0,
            duration_ms=None,
        ),
    )
    service._reset_statistics(active=True, started_at=0.0)  # noqa: SLF001
    worker = MagicMock()
    worker.queue_telemetry = SaveQueueTelemetry(current_depth=2, peak_depth=5)
    service._save_worker = worker  # noqa: SLF001
    service._drop_worker_after_first_read = True  # noqa: SLF001

    statistics = service.statistics_snapshot()

    assert statistics is not None
    assert statistics.save_queue_depth == 2
    assert statistics.save_queue_peak_depth == 5


def test_recording_service_clears_worker_and_deactivates_statistics_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """終了時のworker clearと統計inactive化の間をGUI pollへ見せない。"""

    class _Capture:
        """撮影処理を即時終了させるdouble。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            """RecordingCaptureの依存引数を受け取る。"""

        def run(self, cancellation_token: CancellationToken, *, hooks: object) -> None:
            """保存処理を行わず終了する。"""
            del cancellation_token, hooks

    class _ClearBlockingService(RecordingService):
        """worker clear直後を停止して統計pollとの整合性を検証するService。"""

        def __init__(
            self,
            camera_device: CameraDevice,
            storage: ExperimentStorage,
            settings: RecordingSettings,
        ) -> None:
            """clear停止用Eventと制御flagを初期化する。"""
            self.clear_started = threading.Event()
            self.allow_clear = threading.Event()
            self.hold_worker_clear = False
            super().__init__(camera_device, storage, settings)

        def __setattr__(self, name: str, value: object) -> None:
            """worker clear後、統計reset前の瞬間をテスト用に保持する。"""
            if (
                name == "_save_worker"
                and value is None
                and self.__dict__.get("hold_worker_clear", False)
            ):
                super().__setattr__(name, value)
                self.clear_started.set()
                if not self.allow_clear.wait(timeout=1):
                    msg = "worker clear test release timed out"
                    raise AssertionError(msg)
                return
            super().__setattr__(name, value)

    monkeypatch.setattr(recording_service, "RecordingCapture", _Capture)
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("STO")
    storage.start_recording_session.return_value.dir_name = "record-1"
    service = _ClearBlockingService(
        MagicMock(spec=CameraDevice),
        storage,
        RecordingSettings(
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=100.0,
            duration_ms=None,
        ),
    )
    service.hold_worker_clear = True
    run_thread = threading.Thread(
        target=lambda: service._run_recording_capture(CancellationToken()),  # noqa: SLF001
    )
    run_thread.start()

    assert service.clear_started.wait(timeout=1)
    snapshot_started = threading.Event()
    snapshot_done = threading.Event()
    snapshots: list[AcquisitionStatistics | None] = []

    def poll_statistics() -> None:
        """終了中の統計snapshotを別threadから取得する。"""
        snapshot_started.set()
        snapshots.append(service.statistics_snapshot())
        snapshot_done.set()

    poll_thread = threading.Thread(target=poll_statistics)
    poll_thread.start()
    try:
        assert snapshot_started.wait(timeout=1)
        assert not snapshot_done.wait(timeout=0.2)
    finally:
        service.allow_clear.set()
        run_thread.join(timeout=1)
        poll_thread.join(timeout=1)

    assert not run_thread.is_alive()
    assert not poll_thread.is_alive()
    assert snapshots == [None]
