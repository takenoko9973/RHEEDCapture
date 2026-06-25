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


class TiffSaveWorker(Protocol):
    """Use Caseが依存するTIFF保存ワーカーのProtocol。"""

    errors: list[Exception]

    def start(self) -> None:
        """保存処理を開始する。"""
        ...

    def enqueue(self, request: SaveRequest) -> None:
        """保存要求をキューへ投入する。"""
        ...

    def finish(self) -> None:
        """投入済み保存要求を処理し終えて停止する。"""
        ...
