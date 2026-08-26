from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING, Protocol

from rheed_capture.application.capture.save_worker import SaveQueueTelemetry
from rheed_capture.infrastructure.storage.tiff_writer import TiffWriter

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np

    from rheed_capture.application.capture.save_worker import SaveRequest


class TiffWriterType(Protocol):
    """AsyncTiffSaveWorkerが呼び出すTIFF writerのProtocol。"""

    @staticmethod
    def save(
        file_path: Path,
        image_data: np.ndarray,
        metadata: dict,
        *,
        compression: str | None,
    ) -> None:
        """TIFF画像を指定メタデータと圧縮設定で保存する。"""
        ...


class AsyncTiffSaveWorker:
    """TIFF保存を撮影ループから切り離して逐次実行するワーカー。"""

    def __init__(
        self,
        *,
        max_queue_size: int,
        tiff_writer: TiffWriterType = TiffWriter,
    ) -> None:
        """保存キューと専用スレッドを初期化する。"""
        self._queue: queue.Queue[SaveRequest | None] = queue.Queue(maxsize=max_queue_size)
        self._tiff_writer = tiff_writer
        self._thread = threading.Thread(target=self._run, daemon=False)
        self._errors: list[Exception] = []
        self._queue_condition = threading.Condition()
        self._queue_depth = 0
        self._peak_queue_depth = 0

    @property
    def errors(self) -> list[Exception]:
        """保存中に発生した例外のコピーを返す。"""
        return list(self._errors)

    @property
    def queue_depth(self) -> int:
        """保存待機中の要求数をthread-safeに返す。"""
        with self._queue_condition:
            return self._queue_depth

    @property
    def peak_queue_depth(self) -> int:
        """Recording開始後に観測した最大の保存待機要求数を返す。"""
        with self._queue_condition:
            return self._peak_queue_depth

    @property
    def queue_telemetry(self) -> SaveQueueTelemetry:
        """保存queueのcurrent/peakを同一snapshotとして返す。"""
        with self._queue_condition:
            return SaveQueueTelemetry(
                current_depth=self._queue_depth,
                peak_depth=self._peak_queue_depth,
            )

    def start(self) -> None:
        """保存スレッドを開始する。"""
        self._thread.start()

    def enqueue(self, request: SaveRequest) -> None:
        """保存要求をキューへ追加し、満杯なら撮影側を待たせる。"""
        with self._queue_condition:
            while self._queue_depth >= self._queue.maxsize:
                self._queue_condition.wait()

            self._queue_depth += 1
            queue_depth = self._queue_depth
            enqueued = False
            try:
                if request.on_enqueued is not None:
                    request.on_enqueued(queue_depth)
                self._queue.put_nowait(request)
                self._peak_queue_depth = max(self._peak_queue_depth, queue_depth)
                enqueued = True
            finally:
                if not enqueued:
                    self._queue_depth -= 1
                    self._queue_condition.notify_all()

    def finish(self) -> None:
        """終了シグナルを送り、保存スレッドの完了を待つ。"""
        self._queue.put(None)
        self._thread.join()

    def _run(self) -> None:
        """キューから保存要求を取り出し、終了シグナルまで処理する。"""
        while True:
            request = self._queue.get()
            try:
                if request is None:
                    return

                with self._queue_condition:
                    self._queue_depth -= 1
                    self._queue_condition.notify_all()
                self._save(request)
            finally:
                self._queue.task_done()

    def _save(self, request: SaveRequest) -> None:
        """1件のTIFF保存を実行し、結果通知または例外記録を行う。"""
        start = time.perf_counter()
        try:
            self._tiff_writer.save(
                request.file_path,
                request.image,
                request.metadata,
                compression=request.compression,
            )
        except Exception as e:  # noqa: BLE001
            # 保存失敗は撮影ループ外で発生するため、finish後にUse Caseへ伝える。
            self._errors.append(e)
            return

        save_elapsed_ms = (time.perf_counter() - start) * 1000.0
        try:
            if request.on_saved is not None:
                request.on_saved(request.file_path, save_elapsed_ms)
        except Exception as e:  # noqa: BLE001
            # CSV追記などの完了callback失敗も保存失敗として扱う。
            self._errors.append(e)
