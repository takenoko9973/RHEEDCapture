from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from rheed_capture.application.capture.save_worker import SaveRequest
    from rheed_capture.data_formats.recording import RecordingFrameRow


class _FakeCamera:
    """RecordingCaptureへ渡すテスト用Camera。"""

    def __init__(self, images: list[np.ndarray], *, sleep_sec: float = 0.0) -> None:
        """返す画像列と任意の取得遅延を保持する。"""
        self.images = images
        self.sleep_sec = sleep_sec
        self.exposures: list[float] = []
        self.gains: list[int] = []

    def set_exposure(self, exposure_ms: float) -> None:
        """設定された露光時間を記録する。"""
        self.exposures.append(exposure_ms)

    def set_gain(self, gain: int) -> None:
        """設定されたGainを記録する。"""
        self.gains.append(gain)

    def grab_one(self, timeout_ms: int) -> np.ndarray | None:  # noqa: ARG002
        """画像列から1枚返し、必要なら取得遅延を再現する。"""
        if self.sleep_sec:
            time.sleep(self.sleep_sec)

        return self.images.pop(0)


class _Session:
    """RecordingCaptureへ渡すテスト用RecordingSession。"""

    dir_name = "record-1"

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

    def __init__(self, *, cancel_after_first: CancellationToken | None = None) -> None:
        """保存要求と任意の1枚目キャンセルTokenを保持する。"""
        self.requests: list[SaveRequest] = []
        self.errors: list[Exception] = []
        self.cancel_after_first = cancel_after_first

    def start(self) -> None:
        """同期テスト用なので開始処理は行わない。"""

    def enqueue(self, request: SaveRequest) -> None:
        """保存要求を記録し、完了callbackを即時実行する。"""
        self.requests.append(request)
        if request.on_saved is not None:
            request.on_saved(request.file_path, 1.5)
        if self.cancel_after_first is not None and len(self.requests) == 1:
            self.cancel_after_first.cancel()

    def finish(self) -> None:
        """同期テスト用なので終了処理は行わない。"""


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

    capture = RecordingCapture(
        CaptureConditionApplier(camera),
        FrameGrabber(camera, retry_interval_sec=0),
        session,
        settings,
        save_worker=_SaveWorker(),
    )

    capture.run(
        CancellationToken(),
        hooks=RecordingHooks(on_saved_frames_changed=saved_counts.append),
    )

    assert session.status == "completed"
    assert camera.exposures == [1.0]
    assert camera.gains == [2]
    assert [row.frame_index for row, _ in session.rows] == [1, 2]
    assert [row.target_elapsed_ms for row, _ in session.rows] == [0.0, 1.0]
    assert saved_counts == [1, 2]


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


def test_recording_rejects_exposure_longer_than_interval() -> None:
    """露光時間が撮影間隔を超えるRecording設定を拒否する。"""
    with pytest.raises(ValueError, match="露光時間が撮影間隔より長い"):
        RecordingSettings(
            exposure_ms=500.0,
            gain=0,
            rate_mode="interval",
            target_interval_ms=300.0,
            duration_ms=None,
        )


def test_interval_from_fps() -> None:
    """FPSからinterval msへ変換できることを確認する。"""
    assert interval_from_fps(20.0) == 50.0
