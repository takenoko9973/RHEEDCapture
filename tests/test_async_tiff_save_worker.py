from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import numpy as np

from rheed_capture.application.capture.save_worker import SaveRequest
from rheed_capture.infrastructure.storage.async_tiff_save_worker import AsyncTiffSaveWorker


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


def test_async_tiff_save_worker_uses_bounded_queue_and_invokes_callback() -> None:
    """保存キューサイズ、圧縮指定、完了callback呼び出しを確認する。"""
    _Writer.saved = []
    worker = AsyncTiffSaveWorker(max_queue_size=8, tiff_writer=_Writer)
    callbacks: list[tuple[Path, float]] = []

    assert worker._queue.maxsize == 8  # noqa: SLF001

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
    worker = AsyncTiffSaveWorker(max_queue_size=8, tiff_writer=_Writer)

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
