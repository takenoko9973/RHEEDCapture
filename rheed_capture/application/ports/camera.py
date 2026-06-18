from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np


class CameraError(RuntimeError):
    pass


class Camera(Protocol):
    def set_exposure(self, exposure_ms: float) -> None:
        ...

    def set_gain(self, gain: int) -> None:
        ...

    def grab_one(self, timeout_ms: int) -> np.ndarray | None:
        ...
