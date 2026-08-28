import numpy as np
from PySide6.QtGui import QColor
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.widgets.image_viewer import ImageViewer
from rheed_capture.presentation.qt.widgets.preview_background import (
    PreviewBackground,
    PreviewBackgroundStyle,
)


def test_image_viewer_renders_grid_overlay(qtbot: QtBot) -> None:
    """Grid overlayを有効にした画像をPixmapへ描画する。"""
    viewer = ImageViewer()
    qtbot.addWidget(viewer)
    viewer.resize(800, 600)
    viewer.show()

    viewer.set_grid_enabled(True)
    viewer.set_grid_shape(1, 2)
    viewer.update_image(np.full((120, 160), 128, dtype=np.uint8))

    grid_image = viewer.pixmap().toImage()
    grid_boundary_color = grid_image.pixelColor(400, 300)
    grid_outside_color = grid_image.pixelColor(100, 100)

    viewer.set_grid_enabled(False)
    plain_image = viewer.pixmap().toImage()

    assert grid_boundary_color != plain_image.pixelColor(400, 300)
    assert grid_outside_color == plain_image.pixelColor(100, 100)


def test_image_viewer_renders_configured_preview_background(qtbot: QtBot) -> None:
    """画像外側へ設定済みPreview背景を描画する。"""
    viewer = ImageViewer()
    qtbot.addWidget(viewer)
    viewer.resize(800, 600)
    viewer.show()
    viewer.set_preview_background(
        PreviewBackground(
            style=PreviewBackgroundStyle.CHECKERBOARD,
            primary_color=QColor(10, 20, 30),
            secondary_color=QColor(40, 50, 60),
            tile_size=16,
        )
    )

    viewer.update_image(np.full((100, 160), 128, dtype=np.uint8))
    rendered = viewer.grab().toImage()

    assert rendered.pixelColor(8, 8) == QColor(10, 20, 30)
    assert rendered.pixelColor(24, 8) == QColor(40, 50, 60)
