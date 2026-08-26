from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import numpy as np

from rheed_capture.application.capture.save_worker import SaveRequest
from rheed_capture.data_formats.storage_naming import RECORDING_SAVE_QUEUE_MAX_SIZE
from rheed_capture.infrastructure.storage.async_tiff_save_worker import AsyncTiffSaveWorker

if TYPE_CHECKING:
    from collections.abc import Callable


class _Writer:
    """保存要求のPathと圧縮設定だけを記録するテスト用writer。"""

    saved: ClassVar[list[tuple[Path, str | None]]] = []

    @staticmethod
    def save(
        file_path: Path,
        image_data: np.ndarray,
        metadata: dict,
        *,
        compression: str | None,
    ) -> None:
        """保存内容を記録し、実ファイルは作らない。"""
        _ = image_data, metadata
        _Writer.saved.append((file_path, compression))


class _BlockingWriter:
    """保存中に待機してqueueの待機深さを観測するwriter。"""

    started = threading.Event()
    release = threading.Event()
    saved: ClassVar[list[Path]] = []

    @staticmethod
    def save(
        file_path: Path,
        image_data: np.ndarray,
        metadata: dict,
        *,
        compression: str | None,
    ) -> None:
        """最初の保存を止め、保存されたPathを記録する。"""
        _ = image_data, metadata, compression
        _BlockingWriter.started.set()
        assert _BlockingWriter.release.wait(timeout=1)
        _BlockingWriter.saved.append(file_path)


def _request(
    index: int,
    *,
    on_enqueued: Callable[[int], None] | None = None,
) -> SaveRequest:
    """queue workerテスト用の保存要求を作る。"""
    return SaveRequest(
        file_path=Path(f"frame-{index}.tiff"),
        image=np.ones((2, 2), dtype=np.uint16),
        metadata={},
        on_enqueued=on_enqueued,
    )


def test_async_tiff_save_worker_uses_bounded_queue_and_invokes_callback() -> None:
    """保存キューサイズ、圧縮指定、完了callback呼び出しを確認する。"""
    _Writer.saved = []
    worker = AsyncTiffSaveWorker(
        max_queue_size=RECORDING_SAVE_QUEUE_MAX_SIZE,
        tiff_writer=_Writer,
    )
    callbacks: list[tuple[Path, float]] = []

    assert worker._queue.maxsize == 1000  # noqa: SLF001

    worker.start()
    worker.enqueue(
        SaveRequest(
            file_path=Path("frame.tiff"),
            image=np.ones((2, 2), dtype=np.uint16),
            metadata={},
            compression="zlib",
            on_saved=lambda path, elapsed: callbacks.append((path, elapsed)),
        )
    )
    worker.finish()

    assert _Writer.saved == [(Path("frame.tiff"), "zlib")]
    assert callbacks
    assert callbacks[0][0] == Path("frame.tiff")
    assert callbacks[0][1] >= 0


def test_async_tiff_save_worker_records_callback_errors() -> None:
    """完了callbackの例外がworker.errorsへ記録されることを確認する。"""
    _Writer.saved = []
    worker = AsyncTiffSaveWorker(
        max_queue_size=RECORDING_SAVE_QUEUE_MAX_SIZE,
        tiff_writer=_Writer,
    )

    def fail_callback(_path: Path, _elapsed_ms: float) -> None:
        """保存完了callback失敗を発生させる。"""
        msg = "csv failed"
        raise RuntimeError(msg)

    worker.start()
    worker.enqueue(
        SaveRequest(
            file_path=Path("frame.tiff"),
            image=np.ones((2, 2), dtype=np.uint16),
            metadata={},
            compression="zlib",
            on_saved=fail_callback,
        )
    )
    worker.finish()

    assert len(worker.errors) == 1
    assert str(worker.errors[0]) == "csv failed"


def test_async_tiff_save_worker_accepts_burst_over_previous_eight_frame_limit() -> None:
    """未開始workerでも旧8件上限に達せず、全要求をfinishでdrainする。"""
    _Writer.saved = []
    worker = AsyncTiffSaveWorker(
        max_queue_size=RECORDING_SAVE_QUEUE_MAX_SIZE,
        tiff_writer=_Writer,
    )

    depths: list[int] = []
    for index in range(9):
        worker.enqueue(_request(index, on_enqueued=depths.append))

    assert depths == list(range(1, 10))
    assert worker.queue_depth == 9
    assert worker.peak_queue_depth == 9

    worker.start()
    worker.finish()

    assert len(_Writer.saved) == 9
    assert worker.queue_depth == 0
    assert worker.peak_queue_depth == 9


def test_async_tiff_save_worker_reports_waiting_depth_and_peak_thread_safely() -> None:
    """保存中の要求を除くcurrent depthとpeakを保存進行に合わせて返す。"""
    _BlockingWriter.started = threading.Event()
    _BlockingWriter.release = threading.Event()
    _BlockingWriter.saved = []
    worker = AsyncTiffSaveWorker(max_queue_size=3, tiff_writer=_BlockingWriter)

    worker.start()
    worker.enqueue(_request(1))
    assert _BlockingWriter.started.wait(timeout=1)

    worker.enqueue(_request(2))
    worker.enqueue(_request(3))

    assert worker.queue_depth == 2
    assert worker.peak_queue_depth == 2

    _BlockingWriter.release.set()
    worker.finish()

    assert _BlockingWriter.saved == [
        Path("frame-1.tiff"),
        Path("frame-2.tiff"),
        Path("frame-3.tiff"),
    ]
    assert worker.queue_depth == 0
    assert worker.peak_queue_depth == 2


def test_async_tiff_save_worker_blocks_at_capacity_without_dropping_requests() -> None:
    """待機容量を超える投入だけをblockし、全要求を保存する。"""
    _BlockingWriter.started = threading.Event()
    _BlockingWriter.release = threading.Event()
    _BlockingWriter.saved = []
    worker = AsyncTiffSaveWorker(max_queue_size=3, tiff_writer=_BlockingWriter)

    worker.start()
    worker.enqueue(_request(1))
    assert _BlockingWriter.started.wait(timeout=1)
    worker.enqueue(_request(2))
    worker.enqueue(_request(3))
    worker.enqueue(_request(4))

    enqueue_started = threading.Event()
    enqueue_done = threading.Event()

    def enqueue_last_request() -> None:
        """容量が空くまで最後の要求を投入できないことを確認する。"""
        enqueue_started.set()
        worker.enqueue(_request(5))
        enqueue_done.set()

    enqueue_thread = threading.Thread(target=enqueue_last_request)
    enqueue_thread.start()
    try:
        assert enqueue_started.wait(timeout=1)
        assert not enqueue_done.wait(timeout=0.1)
    finally:
        _BlockingWriter.release.set()
        enqueue_thread.join(timeout=1)
        worker.finish()

    assert not enqueue_thread.is_alive()
    assert _BlockingWriter.saved == [
        Path("frame-1.tiff"),
        Path("frame-2.tiff"),
        Path("frame-3.tiff"),
        Path("frame-4.tiff"),
        Path("frame-5.tiff"),
    ]
