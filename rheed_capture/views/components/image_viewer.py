import numpy as np
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


class ImageViewer(QLabel):
    def __init__(self) -> None:
        super().__init__("Camera not connected")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: black; color: white;")

        self.setMinimumSize(720, 540)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    @Slot(np.ndarray)
    def update_image(self, image_data: np.ndarray) -> None:
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
        self.setPixmap(scaled_pixmap)
