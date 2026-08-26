from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.application.capture.frame_capturer import CapturedFrame
from rheed_capture.domain.acquisition_statistics import AcquisitionStatisticsMeter
from rheed_capture.domain.image_processor import ImageProcessor

if TYPE_CHECKING:
    from collections.abc import Callable

InputT = TypeVar("InputT")
ResultT = TypeVar("ResultT")
_EMPTY = object()


class LatestOnlyMailbox[InputT]:
    """未処理項目を常に最新の1件だけ保持するthread-safe mailbox。"""

    def __init__(self) -> None:
        """空のmailboxを生成する。"""
        self._condition = threading.Condition()
        self._item: InputT | object = _EMPTY
        self._closed = False
        self._replace_count = 0

    def submit(self, item: InputT) -> bool:
        """項目を待機場所へ投入し、既存の未処理項目があれば置き換える。"""
        with self._condition:
            if self._closed:
                return False
            if self._item is not _EMPTY:
                self._replace_count += 1
            self._item = item
            self._condition.notify()
            return True

    def take_latest(self) -> InputT | None:
        """待機中の最新項目を待たずに取り出し、なければNoneを返す。"""
        with self._condition:
            if self._item is _EMPTY:
                return None
            item = cast("InputT", self._item)
            self._item = _EMPTY
            return item

    def wait_for_item(self) -> InputT | None:
        """項目が届くかmailboxが閉じるまで待機し、閉鎖時はNoneを返す。"""
        with self._condition:
            while self._item is _EMPTY and not self._closed:
                self._condition.wait()
            if self._closed:
                return None
            item = cast("InputT", self._item)
            self._item = _EMPTY
            return item

    def close(self) -> None:
        """mailboxを閉じ、待機中のworkerを起こす。"""
        with self._condition:
            self._closed = True
            self._item = _EMPTY
            self._condition.notify_all()

    @property
    def pending_count(self) -> int:
        """現在待機中の項目数を返す。"""
        with self._condition:
            return int(self._item is not _EMPTY)

    @property
    def replace_count(self) -> int:
        """古い未処理項目を置き換えた回数を返す。"""
        with self._condition:
            return self._replace_count


class LatestOnlyProcessor[InputT, ResultT]:
    """入力と結果をlatest-onlyで接続する専用処理worker。"""

    def __init__(
        self,
        process: Callable[[InputT], ResultT],
        *,
        name: str,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """処理関数とworker名を受け取り、まだ開始しないworkerを生成する。"""
        self._process = process
        self._on_error = on_error
        self.name = name
        self._input_mailbox: LatestOnlyMailbox[tuple[int, InputT]] = LatestOnlyMailbox()
        self._result_mailbox: LatestOnlyMailbox[ResultT] = LatestOnlyMailbox()
        self._lifecycle_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False
        self._processing = False
        self._processed_frames = 0
        self._processing_rate_meter = AcquisitionStatisticsMeter()
        self._rate_generation = 0

    def start(self) -> None:
        """処理workerを開始する。"""
        with self._lifecycle_lock:
            if self._started:
                return
            self._started = True
            self._thread = threading.Thread(
                target=self._run,
                name=f"rheed-{self.name}-processor",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout_sec: float = 2.0) -> None:
        """処理workerを停止し、処理中の1件が終了するまで待機する。"""
        self._input_mailbox.close()
        with self._lifecycle_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout_sec)
            if thread.is_alive():
                msg = f"{self.name} processor did not stop within {timeout_sec:g} sec"
                raise RuntimeError(msg)
        self._result_mailbox.close()

    def submit(self, item: InputT) -> bool:
        """処理を待たずに入力をmailboxへ投入する。"""
        with self._lifecycle_lock:
            generation = self._rate_generation
            return self._input_mailbox.submit((generation, item))

    def take_latest_result(self) -> ResultT | None:
        """GUI側が待たずに最新処理結果を1件だけ取り出す。"""
        return self._result_mailbox.take_latest()

    @property
    def input_pending_count(self) -> int:
        """処理workerの入力mailbox待機数を返す。"""
        return self._input_mailbox.pending_count

    @property
    def result_pending_count(self) -> int:
        """処理workerの結果mailbox待機数を返す。"""
        return self._result_mailbox.pending_count

    @property
    def input_drop_count(self) -> int:
        """入力mailboxで置き換えられた項目数を返す。"""
        return self._input_mailbox.replace_count

    @property
    def result_drop_count(self) -> int:
        """結果mailboxで置き換えられた結果数を返す。"""
        return self._result_mailbox.replace_count

    @property
    def processed_count(self) -> int:
        """処理完了した項目数を返す。"""
        with self._lifecycle_lock:
            return self._processed_frames

    def reset_rate(self) -> None:
        """処理FPSのrolling windowを境界から再開する。"""
        with self._lifecycle_lock:
            self._rate_generation += 1
            self._processing_rate_meter.reset()

    @property
    def processing_fps(self) -> float:
        """直近1秒の処理完了時刻から現在処理FPSを返す。"""
        with self._lifecycle_lock:
            statistics = self._processing_rate_meter.snapshot(
                time.perf_counter(),
                include_average=False,
            )
        return statistics.current_fps or 0.0

    @property
    def busy(self) -> bool:
        """処理workerが現在の項目を処理中か返す。"""
        with self._lifecycle_lock:
            return self._processing

    def _run(self) -> None:
        """mailboxから最新入力を取り出し、結果mailboxへ置く。"""
        while True:
            queued_item = self._input_mailbox.wait_for_item()
            if queued_item is None:
                return
            generation, item = queued_item
            with self._lifecycle_lock:
                self._processing = True
            try:
                result = self._process(item)
            except Exception as error:  # noqa: BLE001
                if self._on_error is not None:
                    self._on_error(error)
            else:
                self._result_mailbox.submit(result)
                with self._lifecycle_lock:
                    self._processed_frames += 1
                    if generation == self._rate_generation:
                        self._processing_rate_meter.record_frame(
                            time.perf_counter(),
                            None,
                        )
            finally:
                with self._lifecycle_lock:
                    self._processing = False


class PreviewProcessor(LatestOnlyProcessor[np.ndarray, np.ndarray]):
    """CLAHEまたは8bit変換だけを担当するPreview処理worker。"""

    def __init__(self, *, on_error: Callable[[Exception], None] | None = None) -> None:
        """Preview用のlatest-only workerを生成する。"""
        self._processing_lock = threading.Lock()
        self._processing_enabled = False
        super().__init__(self._process_image, name="preview", on_error=on_error)

    def set_processing_enabled(self, enabled: bool) -> None:
        """CLAHEを含むPreview画像処理のON/OFFを更新する。"""
        with self._processing_lock:
            self._processing_enabled = enabled

    def _process_image(self, raw_image: np.ndarray) -> np.ndarray:
        """Raw画像を表示用8bit画像へ変換する。"""
        with self._processing_lock:
            processing_enabled = self._processing_enabled
        if processing_enabled:
            return ImageProcessor.apply_double_clahe(raw_image)
        return ImageProcessor.to_8bit_preview(raw_image)


@dataclass(frozen=True)
class GraphResult:
    """Graph表示用histogramと統計量をまとめた処理結果。"""

    histogram: np.ndarray
    mean: float
    std: float


class GraphProcessor(LatestOnlyProcessor[np.ndarray, GraphResult]):
    """histogram、mean、stdだけを担当する独立Graph処理worker。"""

    def __init__(self, *, on_error: Callable[[Exception], None] | None = None) -> None:
        """Graph用のlatest-only workerを生成する。"""
        super().__init__(self._process_graph, name="graph", on_error=on_error)

    def _process_graph(self, raw_image: np.ndarray) -> GraphResult:
        """Raw画像から12bit histogramと統計量を計算する。"""
        image_12bit = np.right_shift(raw_image, 4).ravel()
        mean_val = float(np.mean(image_12bit))
        std_val = float(np.std(image_12bit))
        histogram, _ = np.histogram(image_12bit, range=(0, 4095), bins=256)
        return GraphResult(histogram, mean_val, std_val)


@dataclass(frozen=True)
class PreviewDiagnostics:
    """Preview、Graph、GUI表示の処理量とdrop数を保持する診断値。"""

    preview_processing_fps: float
    graph_processing_fps: float
    preview_display_fps: float
    graph_display_fps: float
    active_display_hz: float
    preview_processed_frames: int
    graph_processed_frames: int
    preview_display_frames: int
    graph_display_frames: int
    preview_input_drop_count: int
    graph_input_drop_count: int
    preview_result_drop_count: int
    graph_result_drop_count: int


class PreviewPipeline(QObject):
    """Preview画像とGraph統計を独立workerで処理し、GUIからlatest結果をpullする。"""

    image_ready = Signal(np.ndarray)
    histogram_ready = Signal(np.ndarray, float, float)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """PreviewとGraphの専用processorを生成する。"""
        super().__init__(parent)
        self._preview_processor = PreviewProcessor(
            on_error=lambda error: self._handle_processing_error("プレビュー", error)
        )
        self._graph_processor = GraphProcessor(
            on_error=lambda error: self._handle_processing_error("Graph", error)
        )
        self._display_lock = threading.Lock()
        self._preview_display_rate_meter = AcquisitionStatisticsMeter()
        self._graph_display_rate_meter = AcquisitionStatisticsMeter()
        self._preview_display_frames = 0
        self._graph_display_frames = 0
        self._active_display_hz = 0.0

    def start(self) -> None:
        """PreviewとGraphの処理workerを開始する。"""
        self._preview_processor.start()
        self._graph_processor.start()

    def stop(self) -> None:
        """PreviewとGraphの処理workerを停止する。"""
        preview_error: RuntimeError | None = None
        try:
            self._preview_processor.stop()
        except RuntimeError as error:
            preview_error = error
        finally:
            self._graph_processor.stop()
        if preview_error is not None:
            raise preview_error

    @property
    def preview_processor(self) -> PreviewProcessor:
        """Preview専用processorを返す。"""
        return self._preview_processor

    @property
    def graph_processor(self) -> GraphProcessor:
        """Graph専用processorを返す。"""
        return self._graph_processor

    @Slot(bool)
    def set_processing_enabled(self, enabled: bool) -> None:
        """CLAHEを含むPreview画像処理のON/OFFを切り替える。"""
        self._preview_processor.set_processing_enabled(enabled)

    @Slot(object)
    def process_frame(self, frame: object) -> None:
        """Raw画像またはCapturedFrameを処理mailboxへ投入する。"""
        self.submit_frame(frame)

    def submit_frame(self, frame: object) -> bool:
        """Raw画像をPreviewとGraphへ待たずに投入し、両方の受付結果を返す。"""
        raw_image = self._extract_raw_image(frame)
        if raw_image is None:
            return False
        preview_accepted = self._preview_processor.submit(raw_image)
        graph_accepted = self._graph_processor.submit(raw_image)
        return preview_accepted and graph_accepted

    def poll_results(self) -> bool:
        """GUI threadから最新結果だけを取り出して通知する。"""
        updated = False
        preview_image = self._preview_processor.take_latest_result()
        if preview_image is not None:
            self._record_preview_display()
            self.image_ready.emit(preview_image)
            updated = True

        graph_result = self._graph_processor.take_latest_result()
        if graph_result is not None:
            self._record_graph_display()
            self.histogram_ready.emit(
                graph_result.histogram,
                graph_result.mean,
                graph_result.std,
            )
            updated = True
        return updated

    def set_display_refresh_rate(self, refresh_rate_hz: float) -> None:
        """現在の表示refresh rateを診断値へ反映する。"""
        with self._display_lock:
            self._active_display_hz = refresh_rate_hz

    def reset_rates(self) -> None:
        """処理・表示FPSのrolling windowを境界から再開する。"""
        self._preview_processor.reset_rate()
        self._graph_processor.reset_rate()
        with self._display_lock:
            self._preview_display_rate_meter.reset()
            self._graph_display_rate_meter.reset()

    def diagnostics_snapshot(self) -> PreviewDiagnostics:
        """Preview、Graph、表示の処理量とdrop数を返す。"""
        with self._display_lock:
            timestamp = time.perf_counter()
            preview_display_statistics = self._preview_display_rate_meter.snapshot(
                timestamp,
                include_average=False,
            )
            graph_display_statistics = self._graph_display_rate_meter.snapshot(
                timestamp,
                include_average=False,
            )
            preview_display_frames = self._preview_display_frames
            graph_display_frames = self._graph_display_frames
            active_display_hz = self._active_display_hz
        return PreviewDiagnostics(
            preview_processing_fps=self._preview_processor.processing_fps,
            graph_processing_fps=self._graph_processor.processing_fps,
            preview_display_fps=preview_display_statistics.current_fps or 0.0,
            graph_display_fps=graph_display_statistics.current_fps or 0.0,
            active_display_hz=active_display_hz,
            preview_processed_frames=self._preview_processor.processed_count,
            graph_processed_frames=self._graph_processor.processed_count,
            preview_display_frames=preview_display_frames,
            graph_display_frames=graph_display_frames,
            preview_input_drop_count=self._preview_processor.input_drop_count,
            graph_input_drop_count=self._graph_processor.input_drop_count,
            preview_result_drop_count=self._preview_processor.result_drop_count,
            graph_result_drop_count=self._graph_processor.result_drop_count,
        )

    def _extract_raw_image(self, frame: object) -> np.ndarray | None:
        """ndarrayと撮影済みCapturedFrameを表示用Raw画像へ正規化する。"""
        if isinstance(frame, CapturedFrame):
            return frame.image
        if isinstance(frame, np.ndarray):
            return frame
        return None

    def _record_preview_display(self) -> None:
        """Preview結果をGUIへ通知した回数を記録する。"""
        with self._display_lock:
            self._preview_display_frames += 1
            self._preview_display_rate_meter.record_frame(time.perf_counter(), None)

    def _record_graph_display(self) -> None:
        """Graph結果をGUIへ通知した回数を記録する。"""
        with self._display_lock:
            self._graph_display_frames += 1
            self._graph_display_rate_meter.record_frame(time.perf_counter(), None)

    def _handle_processing_error(self, name: str, error: Exception) -> None:
        """processor threadの処理エラーをGUI通知へ変換する。"""
        self.error_occurred.emit(f"{name}更新エラー: {error}")
