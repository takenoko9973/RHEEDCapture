import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

from rheed_capture.presentation.qt.widgets.grid_spec import DEFAULT_GRID_SHAPE, normalize_grid_shape
from rheed_capture.presentation.qt.widgets.preview_background import (
    PreviewBackground,
    PreviewBackgroundStyle,
    build_preview_background_brush,
)


class ImageViewer(QLabel):
    def __init__(self) -> None:
        super().__init__("Camera not connected")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color: white;")

        self.setMinimumSize(720, 540)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        # 最新フレームを保持し、Grid設定だけ変わった時にも即再描画できるようにする。
        self._latest_image_data: np.ndarray | None = None
        self._grid_enabled = False
        self._grid_shape = DEFAULT_GRID_SHAPE
        # 背景設定
        self._background = PreviewBackground(
            style=PreviewBackgroundStyle.SOLID, primary_color=QColor(112, 112, 112)
        )
        self._background_brush = build_preview_background_brush(self._background)

    @Slot(np.ndarray)
    def update_image(self, image_data: np.ndarray) -> None:
        self._latest_image_data = image_data.copy()
        self._render_if_ready()

    @Slot(bool)
    def set_grid_enabled(self, enabled: bool) -> None:
        self._grid_enabled = enabled
        self._render_if_ready()

    @Slot(int, int)
    def set_grid_shape(self, rows: int, cols: int) -> None:
        self._grid_shape = normalize_grid_shape(rows, cols, fallback=self._grid_shape)
        self._render_if_ready()

    def set_preview_background(self, background: PreviewBackground) -> None:
        self._background = background
        self._background_brush = build_preview_background_brush(background)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(event.rect(), self._background_brush)
        painter.end()
        super().paintEvent(event)

    def _render_if_ready(self) -> None:
        # 直近フレームがある場合だけ再描画し、空状態での余計な処理を避ける。
        if self._latest_image_data is not None:
            self._render_image()

    def _render_image(self) -> None:
        image_data = self._latest_image_data
        if image_data is None:
            return

        # ウィンドウのサイズが1x1などの極端な状態の場合は処理をスキップ
        if self.width() <= 1 or self.height() <= 1:
            return

        height, width = image_data.shape
        bytes_per_line = width

        q_image = QImage(
            image_data.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8
        )
        pixmap = QPixmap.fromImage(q_image)

        scaled_pixmap = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if self._grid_enabled:
            self._draw_grid_overlay(scaled_pixmap, *self._grid_shape)
        self.setPixmap(scaled_pixmap)

    def _draw_grid_overlay(self, pixmap: QPixmap, rows: int, cols: int) -> None:
        # Gridは表示補助なので、表示サイズに合わせた座標で最後に重ねる。
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor(220, 220, 220, 160))
        pen.setWidth(1)
        painter.setPen(pen)

        width = pixmap.width()
        height = pixmap.height()
        for i in range(1, cols):
            x = round(width * i / cols)
            painter.drawLine(x, 0, x, height - 1)
        for i in range(1, rows):
            y = round(height * i / rows)
            painter.drawLine(0, y, width - 1, y)
        painter.end()
