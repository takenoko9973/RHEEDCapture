from dataclasses import dataclass, field
from enum import StrEnum

from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap


class PreviewBackgroundStyle(StrEnum):
    SOLID = "solid"
    CHECKERBOARD = "checkerboard"


@dataclass(frozen=True)
class PreviewBackground:
    style: PreviewBackgroundStyle = PreviewBackgroundStyle.CHECKERBOARD
    primary_color: QColor = field(default_factory=lambda: QColor(68, 68, 68))
    secondary_color: QColor = field(default_factory=lambda: QColor(96, 96, 96))
    tile_size: int = 24


def build_preview_background_brush(background: PreviewBackground) -> QBrush:
    if background.style == PreviewBackgroundStyle.SOLID:
        return QBrush(background.primary_color)

    tile_size = max(2, background.tile_size)
    tile = QPixmap(tile_size * 2, tile_size * 2)
    tile.fill(background.primary_color)

    painter = QPainter(tile)
    painter.fillRect(tile_size, 0, tile_size, tile_size, background.secondary_color)
    painter.fillRect(0, tile_size, tile_size, tile_size, background.secondary_color)
    painter.end()
    return QBrush(tile)
