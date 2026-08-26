from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import numpy as np


@dataclass(frozen=True)
class SaveRequest:
    """保存ワーカーへ渡すTIFF保存要求。"""

    file_path: Path
    image: np.ndarray
    metadata: dict
    compression: str | None = None
    on_saved: Callable[[Path, float], None] | None = None
    on_enqueued: Callable[[int], None] | None = None


@dataclass(frozen=True)
class SaveQueueTelemetry:
    """保存待機要求の現在値とRecording中の最大値を表す。"""

    current_depth: int
    peak_depth: int


class TiffSaveWorker(Protocol):
    """Use Caseが依存するTIFF保存ワーカーのProtocol。"""

    errors: list[Exception]

    @property
    def queue_telemetry(self) -> SaveQueueTelemetry:
        """保存queueのcurrent/peak待機深さを返す。"""
        ...

    def start(self) -> None:
        """保存処理を開始する。"""
        ...

    def enqueue(self, request: SaveRequest) -> None:
        """保存要求をキューへ投入する。"""
        ...

    def finish(self) -> None:
        """投入済み保存要求を処理し終えて停止する。"""
        ...
