from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Self

import numpy as np
import pytest

from rheed_capture.application.capture.cancellation import CancellationToken
from rheed_capture.application.capture.frame_capturer import (
    CaptureConditionApplier,
    FrameGrabber,
)
from rheed_capture.application.capture.recording import (
    RecordingCapture,
    RecordingHooks,
    RecordingSettings,
    interval_from_fps,
)
from rheed_capture.application.ports.camera import (
    CameraError,
    CameraFrame,
    FrameReadback,
    TriggerSettings,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

    from rheed_capture.application.capture.save_worker import SaveRequest
    from rheed_capture.data_formats.recording import RecordingFrameRow

from rheed_capture.application.capture.save_worker import SaveQueueTelemetry


class _FakeCamera:
    """RecordingCaptureへ渡すテスト用Camera。"""

    def __init__(
        self,
        images: Sequence[np.ndarray | Exception],
        *,
        sleep_sec: float = 0.0,
        expected_mode: str = "software",
    ) -> None:
        """返す画像列と任意の取得遅延を保持する。"""
        self.images = list(images)
        self.sleep_sec = sleep_sec
        self.exposures: list[float] = []
        self.gains: list[int] = []
        self.sessions: list[_FakeTriggerCaptureSession] = []
        self.expected_mode = expected_mode

    def set_exposure(self, exposure_ms: float) -> None:
        """設定された露光時間を記録する。"""
        self.exposures.append(exposure_ms)

    def set_gain(self, gain: int) -> None:
        """設定されたGainを記録する。"""
        self.gains.append(gain)

    def start_trigger_session(
        self,
        *,
        settings: TriggerSettings,
        expected_frames: int | None,
    ) -> _FakeTriggerCaptureSession:
        """Recording用の長期Trigger Sessionを作成する。"""
        assert settings.mode == self.expected_mode
        session = _FakeTriggerCaptureSession(self, expected_frames=expected_frames)
        self.sessions.append(session)
        return session


class _FakeTriggerCaptureSession:
    """RecordingのSession再利用と再作成を観測するtest double。"""

    def __init__(self, camera: _FakeCamera, *, expected_frames: int | None) -> None:
        """共有画像列と予定フレーム数を保持する。"""
        self.camera = camera
        self.expected_frames = expected_frames
        self.closed = False
        self.trigger_count = 0

    def __enter__(self) -> Self:
        """Session自身を返す。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """context終了時にSessionを閉じる。"""
        self.close()

    def wait_until_ready(self, timeout_ms: int) -> None:
        """テストでは即座にtrigger readyとする。"""

    def execute_software_trigger(self) -> None:
        """発行されたソフトトリガー数を記録する。"""
        self.trigger_count += 1

    def retrieve_frame(self, timeout_ms: int) -> CameraFrame:  # noqa: ARG002
        """画像列から1枚返し、必要なら取得遅延や失敗を再現する。"""
        if self.closed:
            msg = "closed"
            raise CameraError(msg)
        if self.camera.sleep_sec:
            time.sleep(self.camera.sleep_sec)

        if not self.camera.images:
            msg = "trigger missing"
            raise TimeoutError(msg)
        result = self.camera.images.pop(0)
        if isinstance(result, Exception):
            raise result
        return CameraFrame(
            image=result,
            readback=FrameReadback(
                exposure_ms=1.25,
                gain=3,
                camera_timestamp_ticks=self.trigger_count,
                camera_timestamp_frequency_hz=125_000_000,
                source="camera",
            ),
        )

    def close(self) -> None:
        """Sessionを冪等に閉じる。"""
        self.closed = True


class _Session:
    """RecordingCaptureへ渡すテスト用RecordingSession。"""

    dir_name = "record-1"
    session_dir = Path("record-1")

    def __init__(self) -> None:
        """追記行と終了状態を初期化する。"""
        self.rows: list[tuple[RecordingFrameRow, float]] = []
        self.status = ""

    @property
    def saved_frames(self) -> int:
        """保存済み行数を返す。"""
        return len(self.rows)

    def build_frame_path(self, frame_index: int) -> Path:
        """指定frame indexのテスト用Pathを返す。"""
        return Path(f"sample_260625_rec-1_{frame_index:05d}.tiff")

    def build_accumulation_frame_path(self, group_index: int, raw_index: int) -> Path:
        """積算Recording用のgroup内Raw Pathを返す。"""
        return self.session_dir / f"group_{group_index:06d}" / f"raw_{raw_index:04d}.tiff"

    def append_saved_frame(self, row: RecordingFrameRow, save_elapsed_ms: float) -> int:
        """保存完了行を記録し、保存済み行数を返す。"""
        self.rows.append((row, save_elapsed_ms))
        return len(self.rows)

    def mark_completed(self) -> None:
        """Session状態を完了にする。"""
        self.status = "completed"

    def mark_cancelled(self) -> None:
        """Session状態をキャンセルにする。"""
        self.status = "cancelled"

    def mark_error(self, error_message: str) -> None:  # noqa: ARG002
        """Session状態をエラーにする。"""
        self.status = "error"


class _SaveWorker:
    """RecordingCaptureへ渡す同期実行のテスト用保存Worker。"""

    def __init__(
        self,
        *,
        cancel_after_first: CancellationToken | None = None,
        cancel_after_frames: int | None = None,
    ) -> None:
        """保存要求と任意の1枚目キャンセルTokenを保持する。"""
        self.requests: list[SaveRequest] = []
        self.errors: list[Exception] = []
        self.current_queue_depth = 0
        self.peak_queue_depth = 0
        self.cancel_after_first = cancel_after_first
        self.cancel_after_frames = cancel_after_frames

    @property
    def queue_telemetry(self) -> SaveQueueTelemetry:
        """同期workerの保存queue統計を返す。"""
        return SaveQueueTelemetry(
            current_depth=self.current_queue_depth,
            peak_depth=self.peak_queue_depth,
        )

    def start(self) -> None:
        """同期テスト用なので開始処理は行わない。"""

    def enqueue(self, request: SaveRequest) -> None:
        """保存要求を記録し、完了callbackを即時実行する。"""
        self.current_queue_depth += 1
        self.peak_queue_depth = max(self.peak_queue_depth, self.current_queue_depth)
        self.requests.append(request)
        on_enqueued = getattr(request, "on_enqueued", None)
        if on_enqueued is not None:
            on_enqueued(self.current_queue_depth)
        if request.on_saved is not None:
            request.on_saved(request.file_path, 1.5)
        should_cancel = (
            self.cancel_after_frames == len(self.requests)
            if self.cancel_after_frames is not None
            else len(self.requests) == 1
        )
        if self.cancel_after_first is not None and should_cancel:
            self.cancel_after_first.cancel()
        self.current_queue_depth -= 1

    def finish(self) -> None:
        """同期テスト用なので終了処理は行わない。"""


class _DeferredSaveWorker(_SaveWorker):
    """enqueue時depthを確定し、finishまで保存callbackを遅延するtest worker。"""

    def __init__(self, cancellation_token: CancellationToken) -> None:
        """遅延callbackと2枚目後の停止Tokenを初期化する。"""
        super().__init__()
        self.cancellation_token = cancellation_token
        self.pending_requests: list[SaveRequest] = []

    def enqueue(self, request: SaveRequest) -> None:
        """要求を待機させ、enqueue時点のdepth callbackだけを実行する。"""
        self.current_queue_depth += 1
        self.peak_queue_depth = max(self.peak_queue_depth, self.current_queue_depth)
        self.requests.append(request)
        on_enqueued = getattr(request, "on_enqueued", None)
        if on_enqueued is not None:
            on_enqueued(self.current_queue_depth)
        self.pending_requests.append(request)
        if len(self.requests) == 2:
            self.cancellation_token.cancel()

    def finish(self) -> None:
        """待機中要求を投入順にcallback処理してqueueを空にする。"""
        for request in self.pending_requests:
            if request.on_saved is not None:
                request.on_saved(request.file_path, 1.5)
            self.current_queue_depth -= 1


def test_recording_captures_zero_time_frame_and_stops_after_duration() -> None:
    """0ms時点の初回フレームを保存し、duration到達後に完了する。"""
    images = [np.full((2, 2), index, dtype=np.uint16) for index in range(1, 4)]
    camera = _FakeCamera(images)
    session = _Session()
    settings = RecordingSettings(
        exposure_ms=1.0,
        gain=2,
        rate_mode="interval",
        target_interval_ms=1.0,
        duration_ms=1.0,
    )
    saved_counts: list[int] = []
    worker = _SaveWorker()

    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(camera, retry_interval_sec=0),
        session,
        settings,
        save_worker=worker,
    )

    capture.run(
        CancellationToken(),
        hooks=RecordingHooks(on_saved_frames_changed=saved_counts.append),
    )

    assert session.status == "completed"
    assert camera.exposures == [1.0]
    assert camera.gains == [2]
    assert len(camera.sessions) == 1
    assert camera.sessions[0].expected_frames is None
    assert [row.frame_index for row, _ in session.rows] == [1, 2]
    assert [row.target_elapsed_ms for row, _ in session.rows] == [0.0, 1.0]
    assert [row.exposure_ms for row, _ in session.rows] == [1.0, 1.0]
    assert [row.gain for row, _ in session.rows] == [2, 2]
    assert [row.camera_exposure_ms for row, _ in session.rows] == [1.25, 1.25]
    assert [row.camera_gain for row, _ in session.rows] == [3, 3]
    assert [row.camera_timestamp_ticks for row, _ in session.rows] == [1, 2]
    assert worker.requests[0].metadata["camera_exposure_ms"] == 1.25
    assert worker.requests[0].metadata["camera_gain"] == 3
    assert worker.requests[0].metadata["camera_timestamp_frequency_hz"] == 125_000_000
    assert worker.requests[0].metadata["camera_timestamp_source"] == "camera"
    assert worker.requests[0].image is not images[0]
    assert np.array_equal(worker.requests[0].image, images[0])
    assert worker.requests[0].compression == "zlib"
    assert saved_counts == [1, 2]
    assert [row.save_queue_depth for row, _ in session.rows] == [1, 1]


def test_recording_compression_off_passes_none_to_save_request() -> None:
    """Recording圧縮OFFではTIFF保存要求へNoneを渡す。"""
    camera = _FakeCamera([np.ones((2, 2), dtype=np.uint16)])
    session = _Session()
    worker = _SaveWorker()
    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(camera, retry_interval_sec=0),
        session,
        RecordingSettings(
            exposure_ms=1.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=1.0,
            duration_ms=0.001,
            tiff_compression_enabled=False,
        ),
        save_worker=worker,
    )

    capture.run(CancellationToken())

    assert len(worker.requests) == 1
    assert worker.requests[0].compression is None


def test_recording_queue_depth_stays_bound_to_each_frame_until_save_callback() -> None:
    """保存callbackが遅延しても各CSV行が投入時depthに対応する。"""
    token = CancellationToken()
    camera = _FakeCamera(
        [
            np.ones((2, 2), dtype=np.uint16),
            np.full((2, 2), 2, dtype=np.uint16),
        ]
    )
    session = _Session()
    worker = _DeferredSaveWorker(token)
    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(camera, retry_interval_sec=0),
        session,
        RecordingSettings(
            exposure_ms=1.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=1.0,
            duration_ms=None,
        ),
        save_worker=worker,
    )

    capture.run(token)

    assert [row.frame_index for row, _ in session.rows] == [1, 2]
    assert [row.save_queue_depth for row, _ in session.rows] == [1, 2]
    assert worker.current_queue_depth == 0
    assert worker.peak_queue_depth == 2


def test_recording_stop_after_grab_saves_frame_then_cancels() -> None:
    """取得直後のキャンセルでも取得済みフレームは保存してから終了する。"""
    token = CancellationToken()
    camera = _FakeCamera([np.ones((2, 2), dtype=np.uint16)])
    session = _Session()
    worker = _SaveWorker(cancel_after_first=token)
    settings = RecordingSettings(
        exposure_ms=1.0,
        gain=0,
        rate_mode="interval",
        target_interval_ms=10.0,
        duration_ms=None,
    )

    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(camera, retry_interval_sec=0),
        session,
        settings,
        save_worker=worker,
    )

    capture.run(token)

    assert session.status == "cancelled"
    assert len(session.rows) == 1


def test_recording_stop_during_wait_returns_without_next_frame() -> None:
    """次フレーム待機中のキャンセルで追加撮影せず終了する。"""
    token = CancellationToken()
    camera = _FakeCamera(
        [
            np.ones((2, 2), dtype=np.uint16),
            np.full((2, 2), 2, dtype=np.uint16),
        ]
    )
    session = _Session()
    settings = RecordingSettings(
        exposure_ms=1.0,
        gain=0,
        rate_mode="interval",
        target_interval_ms=10_000.0,
        duration_ms=None,
    )
    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(camera, retry_interval_sec=0),
        session,
        settings,
        save_worker=_SaveWorker(),
    )

    thread = threading.Thread(target=lambda: capture.run(token))
    thread.start()
    while len(session.rows) < 1:
        time.sleep(0.001)

    started_cancel = time.perf_counter()
    token.cancel()
    thread.join(timeout=0.2)

    assert not thread.is_alive()
    assert time.perf_counter() - started_cancel < 0.2
    assert session.status == "cancelled"
    assert len(session.rows) == 1


def test_recording_recreates_failed_session_without_skipping_frame_index() -> None:
    """取得失敗時だけSessionを再作成し、同じframe indexを保存する。"""
    image = np.ones((2, 2), dtype=np.uint16)
    camera = _FakeCamera([CameraError("temporary"), image])
    session = _Session()
    settings = RecordingSettings(
        exposure_ms=1.0,
        gain=0,
        rate_mode="interval",
        target_interval_ms=1.0,
        duration_ms=0.001,
    )
    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(camera, retry_interval_sec=0),
        session,
        settings,
        save_worker=_SaveWorker(),
    )

    capture.run(CancellationToken())

    assert len(camera.sessions) == 2
    assert all(trigger_session.closed for trigger_session in camera.sessions)
    assert [row.frame_index for row, _ in session.rows] == [1]


def test_recording_rejects_exposure_longer_than_interval() -> None:
    """Software Recordingは露光時間が撮影間隔を超える条件を拒否する。"""
    settings = RecordingSettings(
        exposure_ms=500.0,
        gain=0,
        rate_mode="interval",
        target_interval_ms=300.0,
        duration_ms=None,
    )
    with pytest.raises(ValueError, match="露光時間が撮影間隔より長い"):
        RecordingCapture(
            CaptureConditionApplier(_FakeCamera([])),
            FrameGrabber(_FakeCamera([]), retry_interval_sec=0),
            _Session(),
            settings,
            save_worker=_SaveWorker(),
        )


def test_accumulation_recording_saves_raw_and_notifies_saturated_group_preview() -> None:
    """積算RecordingはRawを各受信直後に保存し、完了groupだけをPreviewへ送る。"""
    token = CancellationToken()
    session = _Session()
    worker = _SaveWorker(cancel_after_first=token, cancel_after_frames=2)
    capture = RecordingCapture(
        CaptureConditionApplier(
            camera := _FakeCamera(
                [
                    np.full((2, 2), 40_000, dtype=np.uint16),
                    np.full((2, 2), 40_000, dtype=np.uint16),
                ]
            )
        ),
        FrameGrabber(camera, retry_interval_sec=0),
        session,
        RecordingSettings(
            exposure_ms=1.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=1.0,
            duration_ms=None,
        ),
        save_worker=worker,
        accumulation_frames=2,
    )
    previews: list[np.ndarray] = []

    capture.run(token, hooks=RecordingHooks(on_preview_frame_completed=previews.append))

    assert session.status == "cancelled"
    assert [request.file_path.as_posix() for request in worker.requests] == [
        "record-1/group_000001/raw_0001.tiff",
        "record-1/group_000001/raw_0002.tiff",
    ]
    assert [row.filename for row, _ in session.rows] == [
        "group_000001/raw_0001.tiff",
        "group_000001/raw_0002.tiff",
    ]
    assert len(previews) == 1
    assert np.array_equal(previews[0], np.full((2, 2), 65_535, dtype=np.uint16))


def test_hardware_recording_first_trigger_timeout_marks_error() -> None:
    """Hardware Recordingは最初のRawだけ共通待機timeoutをエラーにする。"""
    camera = _FakeCamera([], expected_mode="hardware")
    session = _Session()
    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(
            camera,
            trigger_settings=TriggerSettings(
                mode="hardware",
                hardware_source="Line1",
                hardware_activation="RisingEdge",
                hardware_delay_us=0,
                fps_limit=None,
            ),
            retry_interval_sec=0,
        ),
        session,
        RecordingSettings(
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=1.0,
            duration_ms=1.0,
        ),
        save_worker=_SaveWorker(),
        trigger_wait_timeout_sec=0.001,
    )

    with pytest.raises(TimeoutError, match="Trigger Wait Timeout Error"):
        capture.run(CancellationToken())

    assert session.status == "error"
    assert session.rows == []


def test_hardware_recording_stops_normally_when_trigger_stops_after_first_raw() -> None:
    """最初のRaw後にTriggerが止まってもduration到達は正常終了にする。"""
    camera = _FakeCamera(
        [np.ones((2, 2), dtype=np.uint16)],
        expected_mode="hardware",
    )
    session = _Session()
    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(
            camera,
            trigger_settings=TriggerSettings(
                mode="hardware",
                hardware_source="Line1",
                hardware_activation="RisingEdge",
                hardware_delay_us=0,
                fps_limit=None,
            ),
            retry_interval_sec=0,
        ),
        session,
        RecordingSettings(
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=1.0,
            duration_ms=1.0,
        ),
        save_worker=_SaveWorker(),
    )

    capture.run(CancellationToken())

    assert session.status == "completed"
    assert [row.target_elapsed_ms for row, _ in session.rows] == [None]
    assert [row.actual_elapsed_ms for row, _ in session.rows] == [0.0]


def test_hardware_duration_finishes_started_group_without_starting_next_group() -> None:
    """duration後も開始済みgroupは完遂するが、次groupのRawは保存しない。"""
    camera = _FakeCamera(
        [
            np.full((2, 2), 1, dtype=np.uint16),
            np.full((2, 2), 2, dtype=np.uint16),
            np.full((2, 2), 3, dtype=np.uint16),
        ],
        sleep_sec=0.003,
        expected_mode="hardware",
    )
    session = _Session()
    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(
            camera,
            trigger_settings=TriggerSettings(
                mode="hardware",
                hardware_source="Line1",
                hardware_activation="RisingEdge",
                hardware_delay_us=0,
                fps_limit=None,
            ),
            retry_interval_sec=0,
        ),
        session,
        RecordingSettings(
            exposure_ms=50.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=1.0,
            duration_ms=1.0,
        ),
        save_worker=_SaveWorker(),
        accumulation_frames=2,
    )

    capture.run(CancellationToken())

    assert session.status == "completed"
    assert [row.frame_index for row, _ in session.rows] == [1, 2]
    assert [row.filename for row, _ in session.rows] == [
        "group_000001/raw_0001.tiff",
        "group_000001/raw_0002.tiff",
    ]


def test_interval_from_fps() -> None:
    """FPSからinterval msへ変換できることを確認する。"""
    assert interval_from_fps(20.0) == 50.0
